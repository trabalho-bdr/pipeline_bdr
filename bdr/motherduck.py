"""Envia um banco DuckDB local para um banco no MotherDuck."""
import getpass
import os
import re
from pathlib import Path

import duckdb

from .esquema import TABELAS


def _normalizar_token(token):
    """Normaliza formas comuns de cópia e rejeita valores que não sejam JWT."""
    token = (token or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        token = token[1:-1].strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
        raise ValueError(
            "Token inválido: use o access token completo do MotherDuck, no formato "
            "xxx.yyy.zzz (não use URL, nome do banco ou código de ativação)."
        )
    return token


def _validar(arquivo, nome_banco):
    arquivo = Path(arquivo).resolve()
    if not arquivo.is_file():
        raise ValueError(f"Banco local não encontrado: {arquivo}. Rode a etapa 'carregar' antes.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", nome_banco):
        raise ValueError("O nome do banco MotherDuck deve começar com uma letra e conter apenas letras, números e _.")
    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if not token:
        token = getpass.getpass("Token do MotherDuck (entrada oculta): ")
    token = _normalizar_token(token)
    # A extensão md reconhece esta variável; o token não é gravado no projeto.
    os.environ["motherduck_token"] = token
    os.environ["MOTHERDUCK_TOKEN"] = token
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


def _lista_ufs_sql(ufs):
    normalizadas = sorted({str(uf).strip().upper() for uf in ufs})
    invalidas = [uf for uf in normalizadas if not re.fullmatch(r"[A-Z]{2}", uf)]
    if invalidas:
        raise ValueError("UF inválida para remoção: " + ", ".join(invalidas))
    return ", ".join("'" + uf + "'" for uf in normalizadas)


def _remover_dados_ufs(con, nome_banco, ufs):
    lista_ufs = _lista_ufs_sql(ufs)
    if not lista_ufs:
        return
    municipios = (
        f'SELECT cod_tse FROM "{nome_banco}".main.municipio '
        f'WHERE uf IN ({lista_ufs})'
    )
    ids_ibge = (
        f'SELECT id_municipio FROM "{nome_banco}".main.municipio '
        f'WHERE uf IN ({lista_ufs}) AND id_municipio IS NOT NULL'
    )
    con.execute(
        f'DELETE FROM "{nome_banco}".main.votos_partido_municipio '
        f'WHERE cod_tse_municipio IN ({municipios})'
    )
    con.execute(
        f'DELETE FROM "{nome_banco}".main.participacao_eleitoral '
        f'WHERE cod_tse_municipio IN ({municipios})'
    )
    con.execute(
        f'DELETE FROM "{nome_banco}".main.censo_municipio '
        f'WHERE id_municipio IN ({ids_ibge})'
    )
    con.execute(
        f'DELETE FROM "{nome_banco}".main.municipio WHERE uf IN ({lista_ufs})'
    )


def enviar_membro(arquivo, nome_banco, substituir_ufs=False, remover_ufs=None):
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
            if repetidas and not substituir_ufs:
                raise ValueError("UF já presente no MotherDuck: " + ", ".join(uf for (uf,) in repetidas))
            if repetidas:
                _remover_dados_ufs(con, nome_banco, [uf for (uf,) in repetidas])
            if remover_ufs:
                _remover_dados_ufs(con, nome_banco, remover_ufs)
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
