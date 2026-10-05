"""Envia um banco DuckDB local para um novo banco no MotherDuck."""
import os
import re
from pathlib import Path

import duckdb

from .esquema import TABELAS


def _validar(arquivo, nome_banco):
    arquivo = Path(arquivo).resolve()
    if not arquivo.is_file():
        raise ValueError(f"Banco local não encontrado: {arquivo}. Rode a etapa 'carregar' antes.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", nome_banco):
        raise ValueError("O nome do banco MotherDuck deve começar com uma letra e conter apenas letras, números e _.")
    if not os.environ.get("MOTHERDUCK_TOKEN") and not os.environ.get("motherduck_token"):
        raise ValueError("Defina MOTHERDUCK_TOKEN no ambiente antes do upload.")
    return arquivo


def enviar_banco(arquivo, nome_banco):
    arquivo = _validar(arquivo, nome_banco)

    caminho_sql = arquivo.as_posix().replace("'", "''")
    con = duckdb.connect("md:")
    try:
        con.execute(f'CREATE DATABASE "{nome_banco}" FROM \'{caminho_sql}\'')
    finally:
        con.close()
    return nome_banco


def enviar_membro(arquivo, nome_banco):
    """Acrescenta as tabelas finais de um membro a um banco MotherDuck compartilhado."""
    arquivo = _validar(arquivo, nome_banco)
    caminho_sql = arquivo.as_posix().replace("'", "''")
    con = duckdb.connect("md:")
    try:
        con.execute(f"ATTACH '{caminho_sql}' AS origem_bdr (READ_ONLY)")
        con.execute(f'CREATE DATABASE IF NOT EXISTS "{nome_banco}"')
        con.execute("BEGIN TRANSACTION")
        try:
            for tabela, colunas in TABELAS.items():
                con.execute(f'CREATE TABLE IF NOT EXISTS "{nome_banco}".main.{tabela} ({colunas})')
            repetidas = con.execute(
                f'SELECT DISTINCT o.uf FROM origem_bdr.main.municipio o '
                f'JOIN "{nome_banco}".main.municipio d ON o.uf = d.uf ORDER BY o.uf'
            ).fetchall()
            if repetidas:
                raise ValueError("UF já presente no MotherDuck: " + ", ".join(uf for (uf,) in repetidas))
            for tabela in TABELAS:
                con.execute(
                    f'INSERT INTO "{nome_banco}".main.{tabela} '
                    f'SELECT * FROM origem_bdr.main.{tabela} ON CONFLICT DO NOTHING'
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()
    return nome_banco
