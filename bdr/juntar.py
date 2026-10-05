"""Junta os pacotes dos membros num banco único consolidado para a Questão 3.

Regras de consolidação (chaves naturais e sem duplicação):
  - municipio: uma linha por cod_tse (preserva id_municipio, nome, uf, regiao)
  - eleicao: uma linha por (ano, cd_eleicao, turno)
  - partido: uma linha por (numero, sigla)
  - votos_partido_municipio: deduplicação por (ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio)
  - participacao_eleitoral: deduplicação por (ano, cd_eleicao, turno, cod_tse_municipio)
  - censo_municipio: deduplicação por (id_municipio, ano_referencia)
"""
import json
import shutil
import zipfile
from pathlib import Path

import duckdb

from .esquema import TABELAS

CONSOLIDACAO = {
    "municipio": """SELECT cod_tse, max(id_municipio), max(nome), max(uf), max(regiao)
                    FROM {src} GROUP BY cod_tse""",
    "eleicao": """SELECT ano, cd_eleicao, turno, max(ds_eleicao), min(dt_eleicao)
                  FROM {src} GROUP BY ano, cd_eleicao, turno""",
    "partido": """SELECT numero, sigla, max(nome)
                  FROM {src} GROUP BY numero, sigla""",
    "votos_partido_municipio": """SELECT * FROM {src} QUALIFY row_number() OVER (
        PARTITION BY ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio) = 1""",
    "participacao_eleitoral": """SELECT * FROM {src} QUALIFY row_number() OVER (
        PARTITION BY ano, cd_eleicao, turno, cod_tse_municipio) = 1""",
    "censo_municipio": """SELECT * FROM {src} QUALIFY row_number() OVER (
        PARTITION BY id_municipio, ano_referencia) = 1""",
}


def _lit(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _abrir_pacote(caminho, tmp):
    caminho = Path(caminho)
    if caminho.is_dir():
        return caminho
    destino = tmp / caminho.stem
    if destino.exists():
        shutil.rmtree(destino)
    with zipfile.ZipFile(caminho) as z:
        z.extractall(destino)
    return destino


def juntar(pacotes, banco_saida, pasta_tmp):
    pasta_tmp = Path(pasta_tmp)
    pasta_tmp.mkdir(parents=True, exist_ok=True)
    pastas = [_abrir_pacote(p, pasta_tmp) for p in pacotes]

    manifestos = []
    for pasta in pastas:
        m = pasta / "manifesto.json"
        if m.exists():
            dados = json.loads(m.read_text(encoding="utf-8"))
            manifestos.append(dados)
            print(f"   {dados.get('rotulo', pasta.name)}: UFs {', '.join(dados.get('ufs', []))}")

    Path(banco_saida).unlink(missing_ok=True)
    con = duckdb.connect(str(banco_saida))
    for tabela, colunas in TABELAS.items():
        arquivos = [p / "parquet" / f"{tabela}.parquet" for p in pastas]
        arquivos = [a for a in arquivos if a.exists()]
        con.execute(f"CREATE TABLE {tabela} ({colunas}\n)")
        if not arquivos:
            continue
        src = f"read_parquet([{', '.join(_lit(a.as_posix()) for a in arquivos)}], union_by_name=true)"
        con.execute(f"INSERT INTO {tabela} " + CONSOLIDACAO[tabela].format(src=src))

    _relatorio(con, manifestos)
    con.close()


def _relatorio(con, manifestos):
    print("\n" + "=" * 60)
    print("TABELAS CONSOLIDADAS (QUESTÃO 3)")
    print("=" * 60)
    for t in TABELAS:
        qtd = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"   {t:<26} {qtd:>12,} linhas")

    print("\nCobertura de Municípios e Votos por UF:")
    linhas = con.execute("""
        SELECT uf, count(DISTINCT cod_tse) AS municipios,
               count(DISTINCT id_municipio) AS com_ibge
        FROM municipio
        GROUP BY uf ORDER BY uf
    """).fetchall()
    for uf, muns, ibge in linhas:
        print(f"   {uf}: {muns} municípios ({ibge} vinculados ao IBGE)")

    votos = con.execute("""
        SELECT ano, sum(votos_nominais), sum(votos_legenda)
        FROM votos_partido_municipio
        GROUP BY ano ORDER BY ano
    """).fetchall()
    print("\nTotal de Votos Consolidados:")
    for ano, nom, leg in votos:
        print(f"   {ano}: {nom:,} nominais | {leg:,} legenda")

    partic = con.execute("""
        SELECT ano, turno, sum(eleitorado_apto), sum(comparecimento), sum(abstencoes),
               round(100.0 * sum(abstencoes) / nullif(sum(eleitorado_apto), 0), 2)
        FROM participacao_eleitoral
        GROUP BY ano, turno ORDER BY ano, turno
    """).fetchall()
    print("\nParticipação Eleitoral Consolidada:")
    for ano, turno, apt, comp, abst, tx in partic:
        print(f"   {ano} ({turno}º turno): {apt:,} aptos | {comp:,} comp. | {abst:,} abst. ({tx}%)")
    print("=" * 60)
