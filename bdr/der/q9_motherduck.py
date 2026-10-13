"""Publicação incremental e segura das tabelas da Questão 9 no MotherDuck."""

import getpass
import os
from pathlib import Path

import duckdb

from bdr.motherduck import _normalizar_token
from .esquema import TABELAS_Q9


def publicar_q9(local_duckdb: Path | str, nome_banco: str = "pipeline_bdr_der_completo"):
    """Publica exclusivamente as tabelas de Q9 em um banco MotherDuck existente."""
    local_duckdb = Path(local_duckdb).resolve()
    if not local_duckdb.is_file():
        raise FileNotFoundError(f"Banco local não encontrado: {local_duckdb}")

    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if not token:
        token = getpass.getpass("Token do MotherDuck (entrada oculta): ")
    token = _normalizar_token(token)
    os.environ["motherduck_token"] = token
    os.environ["MOTHERDUCK_TOKEN"] = token

    caminho_sql = local_duckdb.as_posix().replace("'", "''")
    con = duckdb.connect("md:")
    try:
        # 1. Verifica existência do banco remoto
        bancos = [r[0].lower() for r in con.execute("SHOW DATABASES").fetchall()]
        if nome_banco.lower() not in bancos:
            raise RuntimeError(f"Banco remoto '{nome_banco}' não foi encontrado no MotherDuck.")

        con.execute(f'USE "{nome_banco}"')

        # 2. Confirma que a tabela Candidatura existe
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

        # 3. Anexa o banco local em modo somente leitura
        con.execute(f"ATTACH '{caminho_sql}' AS origem_q9 (READ_ONLY)")

        # 4. Validação de integridade entre IDs locais e remotos
        orfaos_remotos = con.execute(f"""
            SELECT count(*)
            FROM origem_q9.main."Despesa_Campanha" loc
            LEFT JOIN "{nome_banco}".main."Candidatura" rem
                   ON loc.id_candidatura = rem.id_candidatura
            WHERE rem.id_candidatura IS NULL
        """).fetchone()[0]

        if orfaos_remotos > 0:
            raise RuntimeError(
                f"Publicação recusada: {orfaos_remotos} despesas locais referenciam candidaturas que não existem "
                f"no banco remoto '{nome_banco}'. Os identificadores locais divergem do banco remoto."
            )

        # 5. Criar/atualizar exclusivamente tabelas pertencentes à Q9
        con.execute("BEGIN TRANSACTION")
        try:
            for tab, definicao in TABELAS_Q9.items():
                con.execute(f'CREATE TABLE IF NOT EXISTS "{nome_banco}".main."{tab}" ({definicao})')

            # Inserção idempotente com ON CONFLICT
            con.execute(f"""
                INSERT INTO "{nome_banco}".main."Categoria_Despesa"
                SELECT * FROM origem_q9.main."Categoria_Despesa"
                ON CONFLICT (id_categoria_despesa) DO NOTHING
            """)

            con.execute(f"""
                INSERT INTO "{nome_banco}".main."Despesa_Campanha"
                SELECT * FROM origem_q9.main."Despesa_Campanha"
                ON CONFLICT (id_despesa) DO UPDATE SET
                    id_candidatura = EXCLUDED.id_candidatura,
                    id_categoria_despesa = EXCLUDED.id_categoria_despesa,
                    valor_contratado = EXCLUDED.valor_contratado,
                    descricao_despesa = EXCLUDED.descricao_despesa,
                    tipo_prestacao_contas = EXCLUDED.tipo_prestacao_contas
            """)

            origem_tem_rejeitada = con.execute("""
                SELECT count(*) FROM information_schema.tables
                WHERE table_catalog='origem_q9' AND table_schema='main' AND table_name='Despesa_Rejeitada'
            """).fetchone()[0] > 0
            if origem_tem_rejeitada:
                con.execute(f"""
                    INSERT INTO "{nome_banco}".main."Despesa_Rejeitada"
                    SELECT * FROM origem_q9.main."Despesa_Rejeitada"
                    ON CONFLICT (id_rejeicao) DO NOTHING
                """)

            # Atualiza métrica agregada publicidade_propaganda
            con.execute(f"""
                UPDATE "{nome_banco}".main."Candidatura" c
                SET publicidade_propaganda = sub.total_pub
                FROM (
                    SELECT
                        d.id_candidatura,
                        sum(d.valor_contratado)::DOUBLE AS total_pub
                    FROM "{nome_banco}".main."Despesa_Campanha" d
                    JOIN "{nome_banco}".main."Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
                    WHERE cat.eh_publicidade = true
                    GROUP BY d.id_candidatura
                ) sub
                WHERE c.id_candidatura = sub.id_candidatura
            """)

            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        total_cat = con.execute(f'SELECT count(*) FROM "{nome_banco}".main."Categoria_Despesa"').fetchone()[0]
        total_desp = con.execute(f'SELECT count(*) FROM "{nome_banco}".main."Despesa_Campanha"').fetchone()[0]
        print(f"=== RELATÓRIO DE PUBLICAÇÃO MOTHERDUCK (Q9) ===")
        print(f"  Banco remoto: {nome_banco}")
        print(f"  Tabelas publicadas: Categoria_Despesa ({total_cat:,} registros), Despesa_Campanha ({total_desp:,} registros)")
        print(f"  Tabelas das demais questões: intactas e preservadas.")
    finally:
        con.close()
