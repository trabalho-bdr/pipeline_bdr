"""Inspeciona ou instala as views de votos de legenda no DER.

Uso: python -m bdr.instalar_legenda_views [--apply] [--database md:...]
Sem --apply, executa somente consultas de leitura.
"""
import argparse
import getpass
import os
from pathlib import Path

import duckdb


SQL = Path(__file__).with_name("legenda_views.sql")
TABELAS = {"eleicao", "municipio", "partido", "votos_partido_municipio"}
VIEWS = ("vw_legenda_municipio_partido", "vw_legenda_uf_partido", "vw_legenda_evolucao_partido")


def schema_der(con):
    rows = con.execute("""SELECT table_schema, lower(table_name)
        FROM information_schema.tables
        WHERE table_catalog = current_database()
          AND table_schema IN ('der_bdr', 'main')""").fetchall()
    for schema in ("der_bdr", "main"):
        presentes = {nome for origem, nome in rows if origem == schema}
        if TABELAS <= presentes:
            return schema
    raise RuntimeError("Nenhum schema contém as quatro tabelas necessárias para votos por legenda")


def _totais(con, schema):
    return con.execute(f'''
        SELECT e.ano, e.cargo, m.uf,
               sum(coalesce(v.votos_legenda, 0))::BIGINT,
               sum(coalesce(v.votos_nominais, 0))::BIGINT
        FROM "{schema}"."Votos_Partido_Municipio" v
        JOIN "{schema}"."Eleicao" e ON e.id_eleicao = v.id_eleicao
        JOIN "{schema}"."Municipio" m ON m.id_municipio = v.id_municipio
        JOIN "{schema}"."Partido" p ON p.id_partido = v.id_partido
        WHERE v.turno = 1 AND e.turno = 1
          AND e.cargo IN ('Deputado Federal', 'Deputado Estadual', 'Vereador')
          AND m.uf IN ('CE', 'MA', 'MS', 'RJ', 'RN', 'RS')
        GROUP BY e.ano, e.cargo, m.uf ORDER BY 1, 2, 3
    ''').fetchall()


def instalar(con):
    schema = schema_der(con)
    esperado = _totais(con, schema)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"SET search_path = '{schema}'")
        con.execute(SQL.read_text(encoding="utf-8"))
        obtido = con.execute(f'''
            SELECT ano, cargo, uf, sum(votos_legenda)::BIGINT,
                   sum(votos_nominais)::BIGINT
            FROM "{schema}"."vw_legenda_municipio_partido"
            GROUP BY ano, cargo, uf ORDER BY 1, 2, 3
        ''').fetchall()
        if obtido != esperado:
            raise RuntimeError("Os totais da view não conferem com as tabelas de origem")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return schema, len(obtido)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default=os.environ.get("BDR_BANCO", "md:pipeline_bdr_der_completo_v2"))
    parser.add_argument("--apply", action="store_true", help="Cria ou atualiza as views no banco")
    args = parser.parse_args()
    if args.database.startswith("md:"):
        token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
        if not token:
            token = getpass.getpass("Token MotherDuck (entrada oculta): ")
        os.environ["motherduck_token"] = token
    con = duckdb.connect(args.database)
    try:
        schema = schema_der(con)
        totais = _totais(con, schema)
        print(f"Banco: {args.database}; schema: {schema}; recortes com dados: {len(totais)}")
        if args.apply:
            schema, total = instalar(con)
            print(f"Views instaladas em {schema}: {', '.join(VIEWS)}; {total} recortes validados")
        else:
            print("Consulta de leitura concluída. Use --apply para instalar as views.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
