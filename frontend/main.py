"""API somente leitura do mapa de apuração (FastAPI + DuckDB/MotherDuck).

Rodar na raiz do repositório:  uv run uvicorn api.main:app --port 8000
Variáveis: BDR_BANCO (padrão: banco DER local; ou md:pipeline_bdr_der_completo),
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
    padrao = "dados_bdr/saida/pipeline_bdr_der_completo.duckdb"
    alt = "pipeline_bdr_der/dados_bdr/saida/pipeline_bdr_der.duckdb"
    return alt if not os.path.exists(padrao) and os.path.exists(alt) else padrao

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
                if os.environ.get("MOTHERDUCK_TOKEN"):
                    os.environ["motherduck_token"] = os.environ["MOTHERDUCK_TOKEN"]
                _con = duckdb.connect(BANCO)
            else:
                _con = duckdb.connect(BANCO, read_only=True)
        return _con


def _consultar(sql, params=()):
    try:
        cur = _conexao().cursor()
        try:
            cur.execute(sql, list(params))
            colunas = [d[0] for d in cur.description]
            return [dict(zip(colunas, r)) for r in cur.fetchall()]
        finally:
            cur.close()
    except Exception:  # não vaza detalhes internos nem credenciais
        log.exception("falha de consulta")
        raise HTTPException(503, "Dados indisponíveis no momento")


def _limpo(v):
    if isinstance(v, float) and v != v:
        return None
    return float(v) if hasattr(v, "as_tuple") else v


@app.get("/api/anos")
def anos():
    r = _consultar('SELECT DISTINCT ano_participacao AS ano FROM "Participacao_Eleitoral" '
                   "WHERE ano_participacao IS NOT NULL ORDER BY 1")
    return {"anos": [x["ano"] for x in r]}


@app.get("/api/q3/{uf}/{ano}")
def q3(uf: str, ano: int):
    """Indicadores municipais (Q3) de uma UF/ano. Chave = código IBGE (Municipio.id_municipio)."""
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(422, "UF fora do recorte")
    if ano not in set(anos()["anos"]):
        raise HTTPException(422, "Ano sem dados de participação")
    linhas = _consultar(consulta("q3_municipios"), [ano, uf])
    saida = {str(r["id_municipio"]).zfill(7): {k: _limpo(v) for k, v in r.items()} for r in linhas}
    return {"uf": uf, "ano": ano, "municipios": saida}
