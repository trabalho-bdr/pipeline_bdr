"""Executa Q3 e Q10 desde fontes oficiais e produz um único banco DER."""

import argparse
import os
from pathlib import Path

import duckdb

from bdr.der.esquema import TABELAS_DER
from bdr.der.q3_bruto import processar as processar_q3
from bdr.der.q10_bruto import processar as processar_q10
from bdr.der.transformacao import construir
from bdr.trajetoria.config import ANOS_TRAJETORIA


UFS_PADRAO = ("CE", "MA", "MS", "RJ", "RN", "RS")
Q3_ANOS = (2018, 2020, 2022, 2024)
Q10_ANOS = tuple(ANOS_TRAJETORIA)
SAIDA_PADRAO = Path("dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb")


def executar_completo(ufs, q3_anos, q10_anos, saida, planilhas_idhm, csv_idhm):
    """Baixa/processa fontes brutas e monta o DER sem ler bancos DER antigos."""
    anos_invalidos = sorted(set(q10_anos) - set(Q10_ANOS))
    if anos_invalidos:
        raise ValueError(
            "Q10 aceita somente anos eleitorais de 2002 a 2024; inválidos: "
            + ", ".join(map(str, anos_invalidos))
        )
    if saida.resolve() != SAIDA_PADRAO.resolve():
        raise ValueError(f"A saída desta carga deve ser {SAIDA_PADRAO}")
    base = Path("dados_bdr/trabalho_der")
    q3 = base / "q3_operacional.duckdb"
    q10 = base / "q10_operacional.duckdb"
    parcial = saida.with_name(saida.stem + ".parcial.duckdb")
    for temporario in (q3, q10):
        if temporario.is_file():
            temporario.unlink()
    processar_q3(ufs, q3_anos, q3, base / "q3_brutos", planilhas_idhm, csv_idhm)
    processar_q10(ufs, q10_anos, q10, base / "q10_brutos")
    if saida.is_file():
        saida.unlink()  # somente a saída local regenerável indicada na CLI
    if parcial.is_file():
        parcial.unlink()
    construir(q3, q10, parcial)
    parcial.replace(saida)
    q3.unlink()
    q10.unlink()
    print(f"Banco DER completo criado a partir dos dados brutos: {saida}")


def _atualizar_despesas(con, banco="pipeline_bdr_der_completo_v2"):
    """Completa despesas ausentes no destino e recalcula os totais em transação."""
    destino = '"' + banco.replace('"', '""') + '".main'
    con.execute("BEGIN TRANSACTION")
    try:
        origem = con.execute(
            'SELECT count(*) FROM origem.main."Despesa_Candidatura"'
        ).fetchone()[0]
        if not origem:
            raise RuntimeError("O banco local não contém despesas para enviar")
        ausentes = con.execute(f'''
            SELECT count(DISTINCT d.id_candidatura)
            FROM origem.main."Despesa_Candidatura" d
            LEFT JOIN {destino}."Candidatura" c USING (id_candidatura)
            WHERE c.id_candidatura IS NULL
        ''').fetchone()[0]
        if ausentes:
            raise RuntimeError(
                f"{ausentes} candidaturas das despesas locais não existem no destino. "
                "Confira se os bancos pertencem à mesma carga."
            )
        conflitos = con.execute(f'''
            SELECT count(*) FROM origem.main."Despesa_Candidatura" s
            JOIN {destino}."Despesa_Candidatura" d USING (id_despesa)
            WHERE s.id_candidatura IS DISTINCT FROM d.id_candidatura
               OR s.categoria IS DISTINCT FROM d.categoria
               OR s.valor IS DISTINCT FROM d.valor
        ''').fetchone()[0]
        if conflitos:
            raise RuntimeError(
                f"{conflitos} despesas já existem com dados diferentes no destino"
            )
        antes = con.execute(f'SELECT count(*) FROM {destino}."Despesa_Candidatura"').fetchone()[0]
        con.execute(f'''
            INSERT INTO {destino}."Despesa_Candidatura" (id_despesa, id_candidatura, categoria, valor)
            SELECT s.id_despesa, s.id_candidatura, s.categoria, s.valor
            FROM origem.main."Despesa_Candidatura" s
            WHERE NOT EXISTS (
                SELECT 1 FROM {destino}."Despesa_Candidatura" d WHERE d.id_despesa = s.id_despesa
            )
        ''')
        con.execute(f'''
            UPDATE {destino}."Candidatura" c SET gastos_campanha_total = t.total
            FROM (
                SELECT d.id_candidatura, sum(d.valor) total
                FROM {destino}."Despesa_Candidatura" d
                WHERE EXISTS (
                    SELECT 1 FROM origem.main."Despesa_Candidatura" s
                    WHERE s.id_candidatura = d.id_candidatura
                )
                GROUP BY d.id_candidatura
            ) t
            WHERE c.id_candidatura = t.id_candidatura
        ''')
        depois = con.execute(f'SELECT count(*) FROM {destino}."Despesa_Candidatura"').fetchone()[0]
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return depois - antes, depois


def publicar(local, atualizar_despesas=False, usuario_esperado=None):
    token = os.environ.get("MOTHERDUCK_TOKEN") or os.environ.get("motherduck_token")
    if token:
        os.environ["motherduck_token"] = token
    else:
        print("Sem token no ambiente; autentique-se pelo navegador para publicar.", flush=True)
    banco = "pipeline_bdr_der_completo_v2"
    con = duckdb.connect("md:")
    try:
        usuario = con.execute("SELECT current_user()").fetchone()[0]
        if usuario_esperado and usuario != usuario_esperado:
            raise RuntimeError(
                f"Conta autenticada: {usuario}; esperada: {usuario_esperado}. "
                "Nenhuma tabela foi enviada."
            )
        caminho = str(Path(local).resolve()).replace("'", "''")
        con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")
        if not atualizar_despesas:
            con.execute(f'CREATE DATABASE IF NOT EXISTS "{banco}"')
        con.execute(f'USE "{banco}"')
        if atualizar_despesas:
            usuario = con.execute("SELECT current_user()").fetchone()[0]
            antes = con.execute(
                f'SELECT count(*) FROM "{banco}".main."Despesa_Candidatura"'
            ).fetchone()[0]
            print(f"Usuário da conexão: {usuario}")
            print(f"Destino: {banco}.main.Despesa_Candidatura; antes: {antes:,}", flush=True)
            inseridas, total = _atualizar_despesas(con, banco)
            # Confere o destino após o commit, sem o banco local anexado à conexão.
            con.execute("DETACH origem")
            confirmado = con.execute(
                f'SELECT count(*) FROM "{banco}".main."Despesa_Candidatura"'
            ).fetchone()[0]
            if confirmado != total:
                raise RuntimeError(
                    f"Contagem após commit divergiu: {confirmado:,}; esperado: {total:,}"
                )
            print(f"Despesas: {inseridas:,} inseridas; {confirmado:,} confirmadas no destino")
            return
        existentes = {r[0].lower() for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog=? AND table_schema='main'",
            [banco],
        ).fetchall()}
        conflito = existentes.intersection(t.lower() for t in TABELAS_DER)
        if conflito:
            raise RuntimeError(
                f"Banco de teste já contém tabelas: {sorted(conflito)}. "
                "Para completar somente as despesas, use --atualizar-despesas."
            )
        esperados = {
            tabela: con.execute(
                f'SELECT count(*) FROM origem.main."{tabela}"'
            ).fetchone()[0]
            for tabela in TABELAS_DER
        }
        usuario = con.execute("SELECT current_user()").fetchone()[0]
        print(f"Usuário da conexão: {usuario}; destino: {banco}", flush=True)
        con.execute("BEGIN TRANSACTION")
        try:
            for tabela, definicao in TABELAS_DER.items():
                con.execute(f'CREATE TABLE "{banco}".main."{tabela}" ({definicao})')
            for tabela in TABELAS_DER:
                print(f"Enviando {tabela}: {esperados[tabela]:,} registros", flush=True)
                con.execute(f'INSERT INTO "{banco}".main."{tabela}" SELECT * FROM origem.main."{tabela}"')
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        con.execute("DETACH origem")
        for tabela, esperado in esperados.items():
            confirmado = con.execute(
                f'SELECT count(*) FROM "{banco}".main."{tabela}"'
            ).fetchone()[0]
            if confirmado != esperado:
                raise RuntimeError(
                    f"Contagem remota de {tabela}: {confirmado:,}; esperado: {esperado:,}"
                )
            print(f"Confirmado {banco}.main.{tabela}: {confirmado:,}", flush=True)
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    acao = ap.add_mutually_exclusive_group(required=True)
    acao.add_argument("--executar-completo", action="store_true")
    ap.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    ap.add_argument("--q3-anos", nargs="+", type=int, default=Q3_ANOS)
    ap.add_argument("--q10-anos", nargs="+", type=int, default=Q10_ANOS)
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--usuario-motherduck", help="Confere o usuário antes de enviar dados")
    ap.add_argument("--idhm-planilhas", default="planilhas",
                    help="Pasta com planilhas XLSX do IDHM 2010")
    ap.add_argument("--idhm-csv", default="dados_bdr/fontes/idhm.csv",
                    help="CSV IDHM 2010 já preparado, usado quando não há planilhas")
    acao.add_argument("--publicar-teste", action="store_true")
    acao.add_argument("--atualizar-despesas", action="store_true",
                      help="Completa despesas no MotherDuck existente e atualiza os totais")
    args = ap.parse_args()
    if args.executar_completo:
        executar_completo(args.ufs, args.q3_anos, args.q10_anos, args.saida,
                          args.idhm_planilhas, args.idhm_csv)
    if args.publicar_teste or args.atualizar_despesas:
        if not args.saida.is_file():
            ap.error(f"Banco local não encontrado: {args.saida}")
        publicar(args.saida, atualizar_despesas=args.atualizar_despesas,
                 usuario_esperado=args.usuario_motherduck)
        print("Publicado em pipeline_bdr_der_completo_v2")


if __name__ == "__main__":
    main()
