#!/usr/bin/env python3
"""Publica somente Despesa_Candidatura no MotherDuck."""

import argparse
import os
import re
from pathlib import Path

import duckdb

from bdr.motherduck import _normalizar_token


TABELA = "Despesa_Candidatura"


def publicar(arquivo, nome_banco, substituir=False):
    arquivo = Path(arquivo).resolve()
    if not arquivo.is_file():
        raise ValueError(f"Banco local não encontrado: {arquivo}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", nome_banco):
        raise ValueError("Nome de banco MotherDuck inválido.")

    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if not token:
        raise ValueError("Defina MOTHERDUCK_TOKEN antes de publicar.")
    token = _normalizar_token(token)
    os.environ["motherduck_token"] = token

    caminho = arquivo.as_posix().replace("'", "''")
    con = duckdb.connect("md:")
    try:
        con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")
        origem = con.execute(
            f'SELECT count(*) FROM origem.main."{TABELA}"'
        ).fetchone()[0]
        if origem == 0:
            raise ValueError("A tabela Despesa_Candidatura local está vazia.")
        con.execute(f'CREATE DATABASE IF NOT EXISTS "{nome_banco}"')
        existe = con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_catalog=? AND table_schema='main' AND table_name=?",
            [nome_banco, TABELA],
        ).fetchone()[0]
        if existe and not substituir:
            raise ValueError(
                f"A tabela {TABELA} já existe no MotherDuck. Use --substituir."
            )
        if existe:
            con.execute(f'DROP TABLE "{nome_banco}".main."{TABELA}"')
        con.execute(
            f'CREATE TABLE "{nome_banco}".main."{TABELA}" AS '
            f'SELECT * FROM origem.main."{TABELA}"'
        )
        print(f"{origem:,} despesas publicadas em {nome_banco}.{TABELA}")
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--banco-local",
        default="dados_bdr/saida/pipeline_bdr_der_completo.duckdb",
    )
    parser.add_argument("--motherduck-db", default="pipeline_bdr_despesas")
    parser.add_argument("--substituir", action="store_true")
    args = parser.parse_args()
    publicar(args.banco_local, args.motherduck_db, args.substituir)


if __name__ == "__main__":
    main()
