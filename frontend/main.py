"""API somente leitura do mapa de apuração (FastAPI + DuckDB/MotherDuck).

Rodar na raiz do repositório:  uv run uvicorn api.main:app --port 8000
Variáveis: BDR_BANCO (banco DER local ou md:pipeline_bdr_der_completo),
MOTHERDUCK_TOKEN (somente no servidor), BDR_CORS (origens separadas por vírgula).
"""
import logging
import os
import threading

import duckdb
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from bdr.consultas_apuracao import consulta

def _obter_banco_padrao():
    env_banco = os.environ.get("BDR_BANCO")
    if env_banco:
        return env_banco
    for caminho in (
        "dados_bdr/saida/pipeline_bdr_der_completo.duckdb",
        "pipeline_bdr_der/dados_bdr/saida/pipeline_bdr_der.duckdb",
    ):
        if os.path.isfile(caminho):
            return caminho
    return "md:pipeline_bdr_der_completo"

BANCO = _obter_banco_padrao()
UFS = {"CE", "MA", "MS", "RJ", "RN", "RS"}
log = logging.getLogger("api")
app = FastAPI(title="Apuração BDR", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_methods=["GET"], allow_headers=[],
                   allow_origins=os.environ.get("BDR_CORS", "http://localhost:5173").split(","))
_con, _lock = None, threading.Lock()


def _conexao():
    """Uma conexão por processo; cada requisição usa seu próprio cursor (thread-safe no DuckDB)."""
    global _con
    with _lock:
        if _con is None:
            if BANCO.startswith("md:"):
                token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
                if not token:
                    raise RuntimeError("Configure MOTHERDUCK_TOKEN no processo da API para consultar o banco online")
                os.environ["motherduck_token"] = token
                _con = duckdb.connect(BANCO)
                try:
                    _con.execute("SET search_path = 'der_bdr,main'")
                except Exception:
                    pass
            else:
                _con = duckdb.connect(BANCO, read_only=True)
        return _con


def _consultar(sql, params=()):
    try:
        cur = _conexao().cursor()
        try:
            if BANCO.startswith("md:"):
                # Os cursores DuckDB não herdam o search_path da conexão.
                cur.execute("SET search_path = 'der_bdr,main'")
            cur.execute(sql, list(params))
            colunas = [d[0] for d in cur.description]
            return [dict(zip(colunas, r)) for r in cur.fetchall()]
        finally:
            cur.close()
    except Exception:  # não vaza detalhes internos nem credenciais
        log.exception("falha de consulta")
        detalhe = ("Banco online não configurado: defina MOTHERDUCK_TOKEN no processo da API"
                   if BANCO.startswith("md:") and not (os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token"))
                   else "Dados indisponíveis no momento")
        raise HTTPException(503, detalhe)


def _limpo(v):
    if isinstance(v, float) and v != v:
        return None
    return float(v) if hasattr(v, "as_tuple") else v


_col_ano = None

def _obter_coluna_ano():
    global _col_ano
    if _col_ano is None:
        try:
            cols = [c[0].lower() for c in _conexao().execute('DESCRIBE "Participacao_Eleitoral"').fetchall()]
            _col_ano = "ano" if "ano" in cols else "ano_participacao"
        except Exception:
            _col_ano = "ano"
    return _col_ano


@app.get("/api/anos")
def anos():
    col = _obter_coluna_ano()
    r = _consultar(f'SELECT DISTINCT {col} AS ano FROM "Participacao_Eleitoral" WHERE {col} IS NOT NULL ORDER BY 1')
    return {"anos": [x["ano"] for x in r]}


@app.get("/api/q3/{uf}/{ano}")
def q3(uf: str, ano: int):
    """Indicadores municipais (Q3) de uma UF/ano. Chave = código IBGE (Municipio.id_municipio)."""
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(422, "UF fora do recorte")
    if ano not in set(anos()["anos"]):
        raise HTTPException(422, "Ano sem dados de participação")
    sql = consulta("q3_municipios")
    if _obter_coluna_ano() == "ano":
        sql = sql.replace("p.ano_participacao", "p.ano")
    linhas = _consultar(sql, [ano, uf])
    saida = {str(r["id_municipio"]).zfill(7): {k: _limpo(v) for k, v in r.items()} for r in linhas}
    return {"uf": uf, "ano": ano, "municipios": saida}


@app.get("/api/legenda/opcoes")
def opcoes_legenda():
    linhas = _consultar('''
        SELECT DISTINCT e.ano, e.cargo
        FROM "Votos_Partido_Municipio" v
        JOIN "Eleicao" e ON e.id_eleicao = v.id_eleicao
        WHERE v.turno = 1 AND e.ano IS NOT NULL AND e.cargo IS NOT NULL
        ORDER BY e.ano DESC, e.cargo
    ''')
    return {"opcoes": linhas}


@app.get("/api/legenda/{uf}/{ano}")
def votos_legenda(uf: str, ano: int, cargo: str):
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(422, "UF fora do recorte")
    if (ano, cargo) not in {(r["ano"], r["cargo"]) for r in opcoes_legenda()["opcoes"]}:
        raise HTTPException(422, "Ano ou cargo sem votos partidários")
    linhas = _consultar('''
        SELECT m.id_municipio, m.nome AS municipio, pa.id_partido, pa.sigla AS partido,
               sum(coalesce(v.votos_legenda, 0))::BIGINT AS votos_legenda,
               sum(coalesce(v.votos_nominais, 0))::BIGINT AS votos_nominais
        FROM "Votos_Partido_Municipio" v
        JOIN "Eleicao" e ON e.id_eleicao = v.id_eleicao
        JOIN "Municipio" m ON m.id_municipio = v.id_municipio
        JOIN "Partido" pa ON pa.id_partido = v.id_partido
        WHERE m.uf = ? AND e.ano = ? AND e.cargo = ? AND v.turno = 1
        GROUP BY m.id_municipio, m.nome, pa.id_partido, pa.sigla
        ORDER BY m.nome, pa.sigla
    ''', [uf, ano, cargo])
    return {"uf": uf, "ano": ano, "cargo": cargo, "linhas": linhas}
