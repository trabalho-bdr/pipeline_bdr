"""Carga operacional Q10 a partir dos ZIPs oficiais, um ano/UF de cada vez."""

from pathlib import Path

import duckdb

from bdr.download import baixar
from bdr.esquema import criar_tabelas as criar_dimensoes_operacionais
from bdr.extracao import extrair_por_uf
from bdr.leitura import ALIASES as ALIASES_LEITURA, carregar_arquivo
from bdr.trajetoria.config import CDN_TSE, RECURSOS
from bdr.trajetoria.transformacao import carregar


def _lit(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ident(valor):
    return '"' + str(valor).replace('"', '""') + '"'


def _votos_arquivo(con, caminho):
    fonte = f"read_csv({_lit(caminho.as_posix())}, delim=';', header=true, all_varchar=true)"
    cols = {r[0].upper(): r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {fonte}").fetchall()}

    def campo(*nomes, padrao="NULL"):
        for nome in nomes:
            if nome in cols:
                return f"nullif(trim({_ident(cols[nome])}), '')"
        return padrao

    ano = campo("ANO_ELEICAO", "ANO")
    turno = campo("NR_TURNO", "NUM_TURNO", padrao="'1'")
    uf = campo("SG_UF", "SIGLA_UF")
    eleicao = campo("CD_ELEICAO", "CODIGO_ELEICAO")
    ue = campo("SG_UE", "CD_MUNICIPIO", "CODIGO_MUNICIPIO")
    sequencial = campo("SQ_CANDIDATO", "SEQUENCIAL_CANDIDATO")
    cargo = campo("CD_CARGO", "CODIGO_CARGO")
    votos = campo("QT_VOTOS_NOMINAIS", "QTD_VOTOS_NOMINAIS", "QT_VOTOS")
    if "SQ_CANDIDATO" not in cols and "SEQUENCIAL_CANDIDATO" not in cols:
        raise ValueError(f"Sequencial ausente no arquivo {caminho}")
    con.execute(f"""INSERT INTO stg_votos
        SELECT {ano}, {turno}, {uf}, {eleicao}, {ue}, {sequencial}, {cargo},
               cast(sum(coalesce(try_cast({votos} AS BIGINT),0)) AS VARCHAR)
        FROM {fonte}
        WHERE {sequencial} IS NOT NULL
        GROUP BY 1,2,3,4,5,6,7""")


def _fonte_candidatos(con):
    con.execute("""CREATE TEMP VIEW fonte_candidatos AS SELECT
        ano ANO_ELEICAO, turno NR_TURNO, uf SG_UF,
        cd_eleicao CD_ELEICAO, ds_eleicao DS_ELEICAO,
        dt_eleicao DT_ELEICAO, sequencial SQ_CANDIDATO,
        cpf NR_CPF_CANDIDATO, nome_civil NM_CANDIDATO,
        nome_urna NM_URNA_CANDIDATO, dt_nascimento DT_NASCIMENTO,
        genero DS_GENERO, raca DS_COR_RACA,
        escolaridade DS_GRAU_INSTRUCAO, ocupacao DS_OCUPACAO,
        uf_nascimento SG_UF_NASCIMENTO,
        cd_cargo CD_CARGO, cargo DS_CARGO,
        numero_partido NR_PARTIDO, sigla_partido SG_PARTIDO,
        nome_partido NM_PARTIDO, sg_ue SG_UE,
        numero_urna NR_CANDIDATO, idade_eleicao NR_IDADE_DATA_POSSE,
        situacao_registro DS_SITUACAO_CANDIDATURA,
        resultado DS_SIT_TOT_TURNO,
        patrimonio VR_BEM_CANDIDATO,
        titulo_eleitoral NR_TITULO_ELEITORAL_CANDIDATO
        FROM stg_consulta_cand""")


def processar(ufs, anos, banco, trabalho):
    banco, trabalho = Path(banco), Path(trabalho)
    if banco.exists():
        raise FileExistsError(f"Banco operacional já existe: {banco}")
    banco.parent.mkdir(parents=True, exist_ok=True)
    trabalho.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(banco))
    try:
        cols = ",".join(f"{campo} VARCHAR" for campo in ALIASES_LEITURA["consulta_cand"])
        con.execute(f"CREATE TABLE stg_consulta_cand ({cols}, arquivo_origem VARCHAR)")
        con.execute("""CREATE TABLE stg_votos (
            ANO_ELEICAO VARCHAR, NR_TURNO VARCHAR, SG_UF VARCHAR,
            CD_ELEICAO VARCHAR, SG_UE VARCHAR, SQ_CANDIDATO VARCHAR,
            CD_CARGO VARCHAR, QT_VOTOS_NOMINAIS VARCHAR)""")
        for ano in anos:
            for recurso in ("consulta_cand", "votacao_candidato_munzona"):
                cfg = RECURSOS[recurso]
                nome = cfg["zip"].format(ano=ano)
                zip_path = trabalho / "zips" / recurso / f"{nome}.zip"
                baixar(f"{CDN_TSE}/{cfg['pasta']}/{nome}.zip", zip_path)
                for uf in ufs:
                    arquivos, _ = extrair_por_uf(zip_path, trabalho / "raw", ano,
                                                 cfg["partes"], [uf])
                    if len(arquivos) != 1:
                        raise ValueError(f"Arquivo oficial ausente: {recurso}/{ano}/{uf}")
                    arquivo = arquivos[0]
                    if recurso == "consulta_cand":
                        carregar_arquivo(con, recurso, ano, arquivo)
                    else:
                        _votos_arquivo(con, arquivo)
                    arquivo.unlink()  # CSV temporário já incorporado ao staging
                    print(f"Q10 {recurso} {ano}/{uf} carregado", flush=True)
                zip_path.unlink()  # ZIP anual já extraído e carregado com sucesso
        con.execute("""CREATE TABLE stg_tipo_eleicao AS
            SELECT try_cast(ano AS INTEGER) ano, cd_eleicao,
                   try_cast(turno AS SMALLINT) turno, cd_cargo,
                   CASE WHEN count(DISTINCT nullif(trim(tipo_eleicao),''))=1
                        THEN min(nullif(trim(tipo_eleicao),'')) END tipo_eleicao,
                   min(coalesce(try_strptime(dt_eleicao,'%d/%m/%Y')::DATE,
                                try_cast(dt_eleicao AS DATE))) data_eleicao
            FROM stg_consulta_cand GROUP BY 1,2,3,4""")
        criar_dimensoes_operacionais(con)
        _fonte_candidatos(con)
        carregar(con, "fonte_candidatos", "stg_votos")
        con.execute("DROP TABLE stg_votos")
        con.execute("DROP TABLE stg_consulta_cand")
    finally:
        con.close()
    return banco
