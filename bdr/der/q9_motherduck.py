"""Publicação incremental e segura das tabelas da Questão 9 no MotherDuck."""

import getpass
import os
import re
from pathlib import Path

import duckdb

from bdr.motherduck import _normalizar_token
from .esquema import TABELAS_Q9, criar_views_q9


def validar_candidaturas_remotas(con, nome_banco: str) -> dict:
    """Valida correspondência unívoca de atributos entre candidaturas locais e remotas.

    Compara atributos eleitorais oficiais:
      - sequencial (sq_candidato oficial do TSE)
      - sigla da UF
      - número de urna
      - ano da eleição
      - turno da eleição
    """
    query = f"""
        WITH cands_locais AS (
            SELECT DISTINCT
                c.id_candidatura,
                trim(c.sequencial) AS sq_candidato,
                upper(trim(c.uf)) AS uf,
                c.numero_urna,
                e.ano,
                e.turno
            FROM origem_q9.main."Candidatura" c
            JOIN origem_q9.main."Eleicao" e ON c.id_eleicao = e.id_eleicao
            WHERE c.id_candidatura IN (
                SELECT DISTINCT id_candidatura FROM origem_q9.main."Despesa_Campanha"
            )
        ),
        cands_remotas AS (
            SELECT
                c.id_candidatura,
                trim(c.sequencial) AS sq_candidato,
                upper(trim(c.uf)) AS uf,
                c.numero_urna,
                e.ano,
                e.turno
            FROM "{nome_banco}".main."Candidatura" c
            JOIN "{nome_banco}".main."Eleicao" e ON c.id_eleicao = e.id_eleicao
        )
        SELECT
            loc.id_candidatura,
            loc.sq_candidato AS loc_sq,
            loc.uf AS loc_uf,
            loc.numero_urna AS loc_num,
            loc.ano AS loc_ano,
            loc.turno AS loc_turno,
            rem.id_candidatura AS rem_id,
            rem.sq_candidato AS rem_sq,
            rem.uf AS rem_uf,
            rem.numero_urna AS rem_num,
            rem.ano AS rem_ano,
            rem.turno AS rem_turno,
            CASE
                WHEN rem.id_candidatura IS NULL THEN 'INEXISTENTE_NO_REMOTA'
                WHEN rem.sq_candidato != loc.sq_candidato THEN 'SEQUENCIAL_DIVERGENTE'
                WHEN rem.uf != loc.uf THEN 'UF_DIVERGENTE'
                WHEN rem.ano != loc.ano THEN 'ANO_ELEICAO_DIVERGENTE'
                WHEN rem.turno != loc.turno THEN 'TURNO_DIVERGENTE'
                WHEN loc.numero_urna IS NOT NULL AND rem.numero_urna IS NOT NULL AND loc.numero_urna != rem.numero_urna
                    THEN 'NUMERO_URNA_DIVERGENTE'
                ELSE 'VALIDO'
            END AS diagnostico
        FROM cands_locais loc
        LEFT JOIN cands_remotas rem ON loc.id_candidatura = rem.id_candidatura
    """
    linhas = con.execute(query).fetchall()
    total_verificados = len(linhas)
    validos = [r for r in linhas if r[12] == "VALIDO"]
    inconsistencias = [r for r in linhas if r[12] != "VALIDO"]

    relatorio = {
        "total_verificados": total_verificados,
        "total_validos": len(validos),
        "total_inconsistencias": len(inconsistencias),
        "inconsistencias": inconsistencias,
    }
    return relatorio


def publicar_q9(local_duckdb: Path | str, nome_banco: str = "pipeline_bdr_der_completo", con=None):
    """Publica incrementalmente e com garantia transacional as tabelas de Q9 no MotherDuck.

    Regras contratuais da Questão 9:
      1. Candidatura e todas as tabelas fora de Q9 permanecem 100% INTACTAS.
      2. Valida atributos oficiais locais vs remotos antes de qualquer escrita.
      3. Substituição atômica por (ano, uf) eliminando registros obsoletos sem duplicar.
      4. Reversão completa (ROLLBACK) em caso de qualquer falha.
    """
    local_duckdb = Path(local_duckdb).resolve()
    if not local_duckdb.is_file():
        raise FileNotFoundError(f"Banco local não encontrado: {local_duckdb}")

    conexao_externa = con is not None
    if not conexao_externa:
        token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
        if not token:
            token = getpass.getpass("Token do MotherDuck (entrada oculta): ")
        token = _normalizar_token(token)
        os.environ["motherduck_token"] = token
        os.environ["MOTHERDUCK_TOKEN"] = token
        con = duckdb.connect("md:")

    try:
        # 1. Verifica existência do banco remoto
        bancos = [r[0].lower() for r in con.execute("SHOW DATABASES").fetchall()]
        if nome_banco.lower() not in bancos:
            raise RuntimeError(f"Banco remoto '{nome_banco}' não foi encontrado no MotherDuck.")

        con.execute(f'USE "{nome_banco}"')

        # 2. Confirma que a tabela Candidatura existe no remoto
        tabelas_remotas = {
            r[0].lower() for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_catalog=? AND table_schema='main'",
                [nome_banco],
            ).fetchall()
        }
        if "candidatura" not in tabelas_remotas:
            raise RuntimeError(
                f"Tabela 'Candidatura' não existe no banco remoto '{nome_banco}'. "
                f"Execute a publicação da base principal antes de integrar a Q9."
            )

        # 3. Anexa o banco local em modo somente leitura (se não estiver anexado)
        caminho_sql = local_duckdb.as_posix().replace("'", "''")
        dbs_atuais = {r[0].lower() for r in con.execute("SHOW DATABASES").fetchall()}
        if "origem_q9" not in dbs_atuais:
            con.execute(f"ATTACH '{caminho_sql}' AS origem_q9 (READ_ONLY)")

        # 4. Validação rigorosa entre candidaturas locais e remotas
        relatorio = validar_candidaturas_remotas(con, nome_banco)
        print("=== RELATÓRIO DE VALIDAÇÃO LOCAL x MOTHERDUCK (Q9) ===")
        print(f"  Candidaturas verificadas: {relatorio['total_verificados']:,}")
        print(f"  Correspondências válidas: {relatorio['total_validos']:,}")
        print(f"  Inconsistências detectadas: {relatorio['total_inconsistencias']:,}")

        if relatorio["total_inconsistencias"] > 0:
            print("\n  DETALHAMENTO DAS PRIMEIRAS INCONSISTÊNCIAS:")
            for inc in relatorio["inconsistencias"][:10]:
                print(
                    f"    - ID: {inc[0]} | Motivo: {inc[12]} | "
                    f"Local: sq={inc[1]}, uf={inc[2]}, ano={inc[4]}, turno={inc[5]} | "
                    f"Remoto: sq={inc[7]}, uf={inc[8]}, ano={inc[10]}, turno={inc[11]}"
                )
            raise ValueError(
                f"Publicação recusada: {relatorio['total_inconsistencias']} candidaturas locais possuem divergências cadastrais "
                f"ou não existem no banco remoto '{nome_banco}'. Nenhuma alteração foi realizada."
            )

        # 5. Publicação atômica das tabelas exclusivas da Q9
        con.execute("BEGIN TRANSACTION")
        try:
            # Garante que tabelas de Q9 existam no banco remoto
            for tab, definicao in TABELAS_Q9.items():
                con.execute(f'CREATE TABLE IF NOT EXISTS "{nome_banco}".main."{tab}" ({definicao})')

            # Determina escopo (ano, uf) presente na origem local
            con.execute("DROP TABLE IF EXISTS scope_q9_publicacao")
            con.execute("""
                CREATE TEMP TABLE scope_q9_publicacao AS
                SELECT DISTINCT ano, uf FROM origem_q9.main."Despesa_Campanha"
                UNION
                SELECT DISTINCT ano, uf FROM origem_q9.main."Despesa_Rejeitada"
            """)

            # Substituição idempotente: remove dados obsoletos para os anos e UFs publicados
            con.execute(f"""
                DELETE FROM "{nome_banco}".main."Despesa_Campanha"
                WHERE (ano, uf) IN (SELECT ano, uf FROM scope_q9_publicacao);

                DELETE FROM "{nome_banco}".main."Despesa_Rejeitada"
                WHERE (ano, uf) IN (SELECT ano, uf FROM scope_q9_publicacao);
            """)

            # Insere categorias (sem conflitos com FKs existentes)
            con.execute(f"""
                INSERT INTO "{nome_banco}".main."Categoria_Despesa"
                SELECT * FROM origem_q9.main."Categoria_Despesa"
                ON CONFLICT (id_categoria_despesa) DO NOTHING
            """)

            # Insere despesas de campanha
            con.execute(f"""
                INSERT INTO "{nome_banco}".main."Despesa_Campanha"
                SELECT * FROM origem_q9.main."Despesa_Campanha"
            """)

            # Insere despesas rejeitadas se houver
            origem_tem_rejeitada = con.execute("""
                SELECT count(*) FROM information_schema.tables
                WHERE table_catalog='origem_q9' AND table_schema='main' AND table_name='Despesa_Rejeitada'
            """).fetchone()[0] > 0
            if origem_tem_rejeitada:
                con.execute(f"""
                    INSERT INTO "{nome_banco}".main."Despesa_Rejeitada"
                    SELECT * FROM origem_q9.main."Despesa_Rejeitada"
                """)

            # Cria/atualiza exclusivamente views da Q9 (Candidatura NÃO É MODIFICADA!)
            criar_views_q9(con, prefixo=f'"{nome_banco}".main')

            # Validações de integridade antes do commit
            orfaos = con.execute(f"""
                SELECT count(*) FROM "{nome_banco}".main."Despesa_Campanha" d
                LEFT JOIN "{nome_banco}".main."Candidatura" c ON d.id_candidatura = c.id_candidatura
                WHERE c.id_candidatura IS NULL
            """).fetchone()[0]
            if orfaos > 0:
                raise RuntimeError(f"Violação de integridade referencial: {orfaos} despesas sem candidatura no banco remoto.")

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        total_cat = con.execute(f'SELECT count(*) FROM "{nome_banco}".main."Categoria_Despesa"').fetchone()[0]
        total_desp = con.execute(f'SELECT count(*) FROM "{nome_banco}".main."Despesa_Campanha"').fetchone()[0]
        total_rej = con.execute(f'SELECT count(*) FROM "{nome_banco}".main."Despesa_Rejeitada"').fetchone()[0]
        print(f"=== SUCESSO: PUBLICAÇÃO MOTHERDUCK (Q9) CONCLUÍDA ===")
        print(f"  Banco remoto: {nome_banco}")
        print(f"  Categoria_Despesa: {total_cat:,} registros")
        print(f"  Despesa_Campanha: {total_desp:,} registros")
        print(f"  Despesa_Rejeitada: {total_rej:,} registros")
        print(f"  View criada: vw_publicidade_candidatura")
        print(f"  Tabelas das demais questões (Candidatura, Eleicao, etc.): intactas e 100% preservadas.")
    finally:
        try:
            con.execute("DETACH origem_q9")
        except Exception:
            pass
        if not conexao_externa:
            con.close()
