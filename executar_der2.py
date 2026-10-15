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
Q3_ANOS = (2022, 2024)
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


def _contar(con, qualificada):
    return con.execute(f"SELECT count(*) FROM {qualificada}").fetchone()[0]


def _copiar_tabelas(con, banco, origem="origem", substituir=False, lote=250_000):
    """Copia cada tabela em sua própria transação e confere a contagem no destino.

    Diferente da versão anterior (uma única transação com tudo), uma falha em
    Despesa_Candidatura aparece como erro explícito em vez de resultar em tabela
    vazia, e a tabela grande é enviada em lotes.
    """
    locais = {t: _contar(con, f'{origem}.main."{t}"') for t in TABELAS_DER}
    print("Contagem local:", locais, flush=True)
    if locais["Despesa_Candidatura"] == 0:
        raise RuntimeError(
            "Despesa_Candidatura está vazia no arquivo local que seria publicado; "
            "confira se este é o arquivo certo (dados_bdr/saida/*.duckdb)."
        )

    existentes = {r[0].lower() for r in con.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_catalog=? AND table_schema='main'", [banco]).fetchall()}
    conflito = existentes.intersection(t.lower() for t in TABELAS_DER)
    if conflito and not substituir:
        raise RuntimeError(f"O banco já contém tabelas {sorted(conflito)}; use --substituir")
    if conflito:  # filhas antes das pais, por causa das FKs
        for tabela in reversed(list(TABELAS_DER)):
            con.execute(f'DROP TABLE IF EXISTS "{banco}".main."{tabela}"')

    con.execute(f'USE "{banco}"')  # as FKs do esquema não são qualificadas
    for tabela, definicao in TABELAS_DER.items():  # ordem respeita as FKs
        destino = f'"{banco}".main."{tabela}"'
        con.execute(f"CREATE TABLE {destino} ({definicao})")
        total = locais[tabela]
        for ini in range(0, max(total, 1), lote):
            con.execute(
                f'INSERT INTO {destino} SELECT * FROM {origem}.main."{tabela}" '
                f"WHERE rowid >= {ini} AND rowid < {ini + lote}"
            )
            print(f"  {tabela}: {min(ini + lote, total)}/{total}", flush=True)
        remoto = _contar(con, destino)
        if remoto != total:
            raise RuntimeError(f"{tabela}: local={total} remoto={remoto}")
    return locais


def publicar(local, substituir=False):
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        raise RuntimeError("Configure MOTHERDUCK_TOKEN no ambiente antes da publicação")
    os.environ["motherduck_token"] = token
    banco = "pipeline_bdr_der_completo_v2"
    con = duckdb.connect("md:")
    try:
        caminho = str(Path(local).resolve()).replace("'", "''")
        con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")
        con.execute(f'CREATE DATABASE IF NOT EXISTS "{banco}"')
        _copiar_tabelas(con, banco, "origem", substituir)
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--executar-completo", action="store_true")
    ap.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    ap.add_argument("--q3-anos", nargs="+", type=int, default=Q3_ANOS)
    ap.add_argument("--q10-anos", nargs="+", type=int, default=Q10_ANOS)
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--idhm-planilhas", default="planilhas",
                    help="Pasta com planilhas XLSX do IDHM 2010")
    ap.add_argument("--idhm-csv", default="dados_bdr/fontes/idhm.csv",
                    help="CSV IDHM 2010 já preparado, usado quando não há planilhas")
    ap.add_argument("--publicar-teste", action="store_true")
    ap.add_argument("--substituir", action="store_true",
                    help="recria as tabelas já existentes no MotherDuck")
    args = ap.parse_args()
    if args.executar_completo and args.publicar_teste:
        ap.error("Execute a carga local e a publicação em comandos separados")
    if args.executar_completo:
        executar_completo(args.ufs, args.q3_anos, args.q10_anos, args.saida,
                          args.idhm_planilhas, args.idhm_csv)
    if args.publicar_teste:
        if not args.saida.is_file():
            ap.error(f"Banco local não encontrado: {args.saida}")
        publicar(args.saida, args.substituir)
        print("Publicado em pipeline_bdr_der_completo_v2")
    if not args.executar_completo and not args.publicar_teste:
        ap.error("Informe --executar-completo ou --publicar-teste")


if __name__ == "__main__":
    main()
