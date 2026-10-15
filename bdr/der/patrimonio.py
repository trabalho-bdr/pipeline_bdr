#!/usr/bin/env python3
"""Baixa e normaliza bens declarados por candidatos no TSE (2018-2024)."""

from pathlib import Path

from bdr.download import baixar
from bdr.extracao import extrair_por_uf


CDN_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ANOS_PADRAO = (2018, 2020, 2022, 2024)
UFS_PADRAO = ("CE", "MA", "MS", "RJ", "RN", "RS")
RECURSO = "bem_candidato"


def _lit(value):
    return "'" + str(value).replace("'", "''") + "'"


def _ident(value):
    return '"' + str(value).replace('"', '""') + '"'


def _campo(colunas, *nomes, padrao="NULL"):
    for nome in nomes:
        if nome in colunas:
            return f"nullif(trim({_ident(colunas[nome])}), '')"
    return padrao


def _fonte(con, caminho):
    literal = _lit(Path(caminho).resolve().as_posix())
    return f"read_csv({literal}, delim=';', quote='\"', escape='\"', header=true, all_varchar=true)"


def _normalizar_arquivo(con, caminho):
    fonte = _fonte(con, caminho)
    colunas = {r[0].upper(): r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {fonte}").fetchall()}
    ano = _campo(colunas, "ANO_ELEICAO", "AA_ELEICAO")
    eleicao = _campo(colunas, "CD_ELEICAO", "CODIGO_ELEICAO")
    uf = _campo(colunas, "SG_UF", "SIGLA_UF")
    sequencial = _campo(colunas, "SQ_CANDIDATO", "SEQUENCIAL_CANDIDATO")
    numero = _campo(colunas, "NR_CANDIDATO", "NUMERO_CANDIDATO")
    nome = _campo(colunas, "NM_CANDIDATO", "NOME_CANDIDATO")
    tipo = _campo(colunas, "DS_TIPO_BEM_CANDIDATO", "DS_TIPO_BEM", "TIPO_BEM")
    descricao = _campo(colunas, "DS_BEM_CANDIDATO", "DS_BEM", "DESCRICAO_BEM")
    valor = _campo(colunas, "VR_BEM_CANDIDATO", "VR_BEM", "VALOR_BEM")
    atualizado = _campo(colunas, "DT_ULT_ATUAL_BEM_CANDIDATO", "DT_ULTIMA_ATUALIZACAO", "DT_ATUALIZACAO")
    obrigatorias = {"ANO_ELEICAO", "SG_UF", "CD_ELEICAO", "SQ_CANDIDATO", "VR_BEM_CANDIDATO"}
    if obrigatorias - colunas.keys():
        raise ValueError(f"Colunas de bens ausentes em {caminho}: {sorted(obrigatorias - colunas.keys())}")
    valor_numero = (
        f"try_cast(CASE WHEN instr({valor}, ',') > 0 "
        f"THEN replace(replace({valor}, '.', ''), ',', '.') "
        f"ELSE {valor} END AS DOUBLE)"
    )
    data = (
        f"coalesce(try_strptime({atualizado}, '%d/%m/%Y')::DATE, "
        f"try_strptime({atualizado}, '%Y-%m-%d')::DATE)"
    )
    con.execute(f"""
        INSERT INTO Patrimonio_Candidato
        SELECT try_cast({ano} AS INTEGER), {eleicao}, upper({uf}), {sequencial},
               try_cast({numero} AS INTEGER), {nome}, {tipo}, {descricao},
               CASE WHEN {valor_numero} >= 0 THEN {valor_numero} END,
               {data}, {_lit(Path(caminho).name)}
        FROM {fonte}
        WHERE {sequencial} IS NOT NULL
    """)
    return con.execute(
        "SELECT count(*) FROM Patrimonio_Candidato WHERE arquivo_origem=?",
        [Path(caminho).name],
    ).fetchone()[0]


def carregar_patrimonio(con, ufs, anos, base):
    """Carrega os bens no banco operacional Q10 já aberto, sem banco adicional."""
    from .esquema import TABELAS_DER

    anos = sorted(set(anos))
    ufs = sorted({uf.upper() for uf in ufs})
    if not anos or set(anos) - set(ANOS_PADRAO):
        raise ValueError("Patrimônio aceita os anos 2018, 2020, 2022 e 2024")
    base = Path(base)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute("DROP TABLE IF EXISTS Patrimonio_Candidato")
        con.execute(f"CREATE TABLE Patrimonio_Candidato ({TABELAS_DER['Patrimonio_Candidato']})")
        for ano in anos:
            nome = f"bem_candidato_{ano}"
            zip_path = base / "zips" / f"{nome}.zip"
            url = f"{CDN_TSE}/{RECURSO}/{nome}.zip"
            print(f"Patrimônio {ano}: {url}", flush=True)
            baixar(url, zip_path)
            partes = {RECURSO: "bem_candidato_{ano}_{uf}"}
            arquivos, _ = extrair_por_uf(zip_path, base / "raw", ano, partes, ufs)
            esperados = {f"{nome}_{uf}.csv".lower() for uf in ufs}
            if {Path(a).name.lower() for a in arquivos} != esperados:
                raise ValueError(f"Arquivos de patrimônio incompletos para {ano}; esperados: {sorted(esperados)}")
            for arquivo in arquivos:
                _normalizar_arquivo(con, arquivo)
                fora = con.execute("""SELECT count(*) FROM Patrimonio_Candidato
                    WHERE arquivo_origem=? AND (ano IS DISTINCT FROM ? OR uf IS NULL OR uf NOT IN
                    (SELECT unnest(?::VARCHAR[])))""", [Path(arquivo).name, ano, ufs]).fetchone()[0]
                if fora:
                    raise ValueError(f"Patrimônio fora do recorte em {arquivo}")
            qtd, validos = con.execute("""SELECT count(*), count(valor_bem)
                FROM Patrimonio_Candidato WHERE ano=?""", [ano]).fetchone()
            if not qtd or not validos:
                raise ValueError(f"Patrimônio {ano} sem bens/valores válidos; carga interrompida")
            print(f"Patrimônio {ano}: {qtd:,} bens, {validos:,} valores válidos", flush=True)
        con.execute("""CREATE OR REPLACE TEMP TABLE patrimonio_total AS
            SELECT ano, uf, cd_eleicao, sq_candidato,
                   CASE WHEN count(valor_bem)=count(*) THEN sum(valor_bem) END total
            FROM Patrimonio_Candidato
            GROUP BY ano, uf, cd_eleicao, sq_candidato""")
        con.execute("""UPDATE candidatura SET patrimonio=NULL
            WHERE ano IN (SELECT unnest(?::INTEGER[]))
              AND upper(trim(uf)) IN (SELECT unnest(?::VARCHAR[]))""", [anos, ufs])
        con.execute("""UPDATE candidatura c SET patrimonio=p.total
            FROM patrimonio_total p
            WHERE c.ano=p.ano AND upper(trim(c.uf))=p.uf
              AND trim(c.sequencial)=p.sq_candidato AND c.cd_eleicao=p.cd_eleicao""")
        # A declaração é da candidatura; o segundo turno pode ter outro CD_ELEICAO.
        # Só reutiliza quando há uma única eleição de origem para esse sequencial.
        con.execute("""UPDATE candidatura c SET patrimonio=p.total
            FROM (SELECT ano, uf, sq_candidato, max(total) total
                  FROM patrimonio_total GROUP BY ano, uf, sq_candidato
                  HAVING count(*)=1) p
            WHERE c.turno=2 AND c.ano=p.ano AND upper(trim(c.uf))=p.uf
              AND trim(c.sequencial)=p.sq_candidato
              AND NOT EXISTS (SELECT 1 FROM patrimonio_total ex
                  WHERE ex.ano=c.ano AND ex.uf=upper(trim(c.uf))
                    AND ex.sq_candidato=trim(c.sequencial) AND ex.cd_eleicao=c.cd_eleicao)""")
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


