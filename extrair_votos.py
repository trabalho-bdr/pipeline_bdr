#!/usr/bin/env python3
"""Extrai votos nominais e votos de legenda do TSE por partido e município."""

import argparse
from pathlib import Path

import duckdb

from bdr.download import baixar
from bdr.extracao import extrair_por_uf
from bdr.trajetoria.config import ANOS_TRAJETORIA, CDN_TSE, UFS_PADRAO


def _lit(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ident(valor):
    return '"' + str(valor).replace('"', '""') + '"'


def _campo(colunas, *nomes, padrao="NULL"):
    for nome in nomes:
        if nome in colunas:
            return f"nullif(trim({_ident(colunas[nome])}), '')"
    return padrao


def extrair(ufs, anos, destino, trabalho):
    destino = Path(destino)
    trabalho = Path(trabalho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    trabalho.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()

    con = duckdb.connect(str(destino))
    try:
        con.execute("""
            CREATE TABLE votos_nominais_legenda (
                ano INTEGER,
                turno SMALLINT,
                uf VARCHAR,
                cd_eleicao VARCHAR,
                cd_cargo VARCHAR,
                cargo VARCHAR,
                numero_partido INTEGER,
                sigla_partido VARCHAR,
                nome_partido VARCHAR,
                cod_tse_municipio VARCHAR,
                votos_nominais BIGINT,
                votos_legenda BIGINT,
                PRIMARY KEY (ano, turno, uf, cd_eleicao, cd_cargo,
                             numero_partido, cod_tse_municipio)
            )
        """)
        for ano in anos:
            nome = f"votacao_partido_munzona_{ano}"
            zip_path = trabalho / "zips" / f"{nome}.zip"
            baixar(f"{CDN_TSE}/votacao_partido_munzona/{nome}.zip", zip_path)
            arquivos, _ = extrair_por_uf(
                zip_path,
                trabalho / "raw",
                ano,
                {"votacao_partido_munzona": "votacao_partido_munzona_{ano}_{uf}"},
                ufs,
            )
            for arquivo in arquivos:
                fonte = f"read_csv({_lit(arquivo.as_posix())}, delim=';', header=true, all_varchar=true)"
                colunas = {r[0].upper(): r[0] for r in con.execute(
                    f"DESCRIBE SELECT * FROM {fonte}"
                ).fetchall()}
                ano_col = _campo(colunas, "ANO_ELEICAO", "ANO", padrao=str(ano))
                turno = _campo(colunas, "NR_TURNO", "NUM_TURNO", padrao="'1'")
                uf = _campo(colunas, "SG_UF", "SIGLA_UF")
                eleicao = _campo(colunas, "CD_ELEICAO", "CODIGO_ELEICAO")
                cargo = _campo(colunas, "DS_CARGO", "DESCRICAO_CARGO")
                cd_cargo = _campo(colunas, "CD_CARGO", "CODIGO_CARGO")
                partido = _campo(colunas, "NR_PARTIDO", "NUMERO_PARTIDO")
                sigla = _campo(colunas, "SG_PARTIDO", "SIGLA_PARTIDO")
                nome_partido = _campo(colunas, "NM_PARTIDO", "NOME_PARTIDO")
                municipio = _campo(colunas, "CD_MUNICIPIO", "CODIGO_MUNICIPIO", "SG_UE")
                nominal = _campo(colunas, "QT_VOTOS_NOMINAIS", "QT_VOTOS_NOMINAIS_VALIDOS", padrao="'0'")
                legenda = _campo(colunas, "QT_VOTOS_LEGENDA", "QT_VOTOS_LEGENDA_VALIDOS", padrao="'0'")
                con.execute(f"""
                    INSERT INTO votos_nominais_legenda
                    SELECT try_cast({ano_col} AS INTEGER),
                           try_cast({turno} AS SMALLINT), upper({uf}), {eleicao},
                           {cd_cargo}, {cargo}, try_cast({partido} AS INTEGER),
                           upper({sigla}), {nome_partido}, lpad({municipio}, 5, '0'),
                           sum(coalesce(try_cast({nominal} AS BIGINT), 0)),
                           sum(coalesce(try_cast({legenda} AS BIGINT), 0))
                    FROM {fonte}
                    WHERE {municipio} IS NOT NULL AND {partido} IS NOT NULL
                    GROUP BY ALL
                """)
                arquivo.unlink(missing_ok=True)
                print(f"Votos nominais/legenda {ano}/{arquivo.stem.rsplit('_', 1)[-1]} carregados", flush=True)
            zip_path.unlink(missing_ok=True)
    finally:
        con.close()
    return destino


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    parser.add_argument("--anos", nargs="+", type=int, default=ANOS_TRAJETORIA)
    parser.add_argument("--saida", type=Path, default=Path("dados_bdr/saida/votos_nominais_legenda.duckdb"))
    parser.add_argument("--trabalho", type=Path, default=Path("dados_bdr/trabalho_votos"))
    args = parser.parse_args()
    extrair(args.ufs, args.anos, args.saida, args.trabalho)
    print(f"Banco gerado: {args.saida}")


if __name__ == "__main__":
    main()
