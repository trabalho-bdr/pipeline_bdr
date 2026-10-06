"""Publica as tabelas de trajetória no banco MotherDuck existente."""

import getpass
import os
import re
from pathlib import Path

import duckdb

from bdr.motherduck import _normalizar_token

from .esquema import TABELAS_TRAJETORIA


def publicar(arquivo, nome_banco, substituir=False):
    arquivo = Path(arquivo).resolve()
    if not arquivo.is_file():
        raise ValueError(f"Banco histórico não encontrado: {arquivo}")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", nome_banco):
        raise ValueError("Nome de banco MotherDuck inválido.")
    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if not token:
        token = getpass.getpass("Token do MotherDuck (entrada oculta): ")
    token = _normalizar_token(token)
    os.environ["motherduck_token"] = token
    os.environ["MOTHERDUCK_TOKEN"] = token
    caminho = arquivo.as_posix().replace("'", "''")
    con = duckdb.connect("md:")
    try:
        con.execute(f"ATTACH '{caminho}' AS origem_q10 (READ_ONLY)")
        con.execute(f'CREATE DATABASE IF NOT EXISTS "{nome_banco}"')
        con.execute("BEGIN TRANSACTION")
        try:
            for tabela in TABELAS_TRAJETORIA:
                existe = con.execute(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_catalog=? AND table_schema='main' AND table_name=?",
                    [nome_banco, tabela],
                ).fetchone()[0]
                if existe and not substituir:
                    raise ValueError(
                        f"Tabela já existe no MotherDuck: {tabela}. Use --substituir."
                    )
                if existe:
                    con.execute(f'DROP TABLE "{nome_banco}".main.{tabela}')
                con.execute(
                    f'CREATE TABLE "{nome_banco}".main.{tabela} AS '
                    f'SELECT * FROM origem_q10.main.{tabela}'
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return nome_banco
