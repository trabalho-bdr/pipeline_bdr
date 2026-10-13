"""Executa Q3, Q10 e Q9 desde fontes oficiais e produz um único banco DER."""

import argparse
import os
from pathlib import Path

import duckdb

from bdr.der.esquema import TABELAS_DER
from bdr.der.q3_bruto import processar as processar_q3
from bdr.der.q10_bruto import processar as processar_q10
from bdr.der.q9_bruto import (
    ANOS_PADRAO_Q9,
    UFS_PADRAO_Q9,
    processar_q9,
    validar_q9,
)
from bdr.der.q9_motherduck import publicar_q9
from bdr.der.transformacao import construir
from bdr.trajetoria.config import ANOS_TRAJETORIA


UFS_PADRAO = ("CE", "MA", "MS", "RJ", "RN", "RS")
Q3_ANOS = (2022, 2024)
Q10_ANOS = tuple(ANOS_TRAJETORIA)
Q9_ANOS = tuple(ANOS_PADRAO_Q9)
Q9_UFS = tuple(UFS_PADRAO_Q9)
SAIDA_PADRAO = Path("dados_bdr/saida/pipeline_bdr_der_completo.duckdb")


def validar_integridade_der(caminho_banco):
    """Valida integridade referencial e chaves das tabelas do DER completo."""
    con = duckdb.connect(str(caminho_banco), read_only=True)
    try:
        tabelas = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        faltando = set(TABELAS_DER.keys()) - tabelas
        if faltando:
            raise ValueError(f"Tabelas contratuais ausentes no DER final: {sorted(faltando)}")

        # Valida chaves estrangeiras fundamentais
        cand_eleicao_orfaos = con.execute("""
            SELECT count(*) FROM "Candidatura" c
            LEFT JOIN "Eleicao" e ON c.id_eleicao = e.id_eleicao
            WHERE e.id_eleicao IS NULL
        """).fetchone()[0]

        desp_cand_orfaos = con.execute("""
            SELECT count(*) FROM "Despesa_Campanha" d
            LEFT JOIN "Candidatura" c ON d.id_candidatura = c.id_candidatura
            WHERE c.id_candidatura IS NULL
        """).fetchone()[0]

        desp_cat_orfaos = con.execute("""
            SELECT count(*) FROM "Despesa_Campanha" d
            LEFT JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
            WHERE cat.id_categoria_despesa IS NULL
        """).fetchone()[0]

        if cand_eleicao_orfaos > 0 or desp_cand_orfaos > 0 or desp_cat_orfaos > 0:
            raise ValueError(
                f"Violação de integridade referencial: "
                f"cand_eleicao={cand_eleicao_orfaos}, desp_cand={desp_cand_orfaos}, desp_cat={desp_cat_orfaos}"
            )
        print("Validação de integridade referencial concluída com sucesso.", flush=True)
    finally:
        con.close()


def executar_completo(ufs, q3_anos, q10_anos, q9_ufs, q9_anos, saida, planilhas_idhm, csv_idhm):
    """Baixa/processa fontes brutas e monta o DER sem ler bancos DER antigos."""
    if saida.resolve() != SAIDA_PADRAO.resolve():
        raise ValueError(f"A saída desta carga deve ser {SAIDA_PADRAO}")
    base = Path("dados_bdr/trabalho_der")
    q3 = base / "q3_operacional.duckdb"
    q10 = base / "q10_operacional.duckdb"
    parcial = saida.with_name(saida.stem + ".parcial.duckdb")
    for temporario in (q3, q10):
        if temporario.is_file():
            temporario.unlink()

    # Etapas 1 e 2: Extrair dados de Q3 e Q10
    processar_q3(ufs, q3_anos, q3, base / "q3_brutos", planilhas_idhm, csv_idhm)
    processar_q10(ufs, q10_anos, q10, base / "q10_brutos")

    if saida.is_file():
        saida.unlink()  # somente a saída local regenerável indicada na CLI
    if parcial.is_file():
        parcial.unlink()

    # Etapas 3 e 4: Construir o DER inicial e integrar dados de Q9
    construir(q3, q10, parcial)
    processar_q9(q9_ufs, q9_anos, parcial, base / "q9_brutos")

    # Etapa 5: Validar integridade referencial, duplicatas e contagens
    validar_integridade_der(parcial)

    # Etapa 6: Gerar o arquivo DuckDB final
    parcial.replace(saida)
    q3.unlink(missing_ok=True)
    q10.unlink(missing_ok=True)
    print(f"Banco DER completo criado a partir dos dados brutos: {saida}")


def executar_somente_q9(q9_ufs, q9_anos, saida):
    """Executa isoladamente a carga e atualização de Q9 em banco DER já existente."""
    if not saida.is_file():
        raise FileNotFoundError(
            f"Banco DER principal não encontrado em: {saida}.\n"
            f"Execute primeiro a carga completa com --executar-completo antes de executar --somente-q9."
        )
    base = Path("dados_bdr/trabalho_der")
    print(f"Executando exclusivamente a carga da Questão 9 no banco existente: {saida}")
    processar_q9(q9_ufs, q9_anos, saida, base / "q9_brutos")
    validar_integridade_der(saida)
    print(f"Carga da Questão 9 concluída com sucesso em: {saida}")


def publicar(local, banco_remoto="pipeline_bdr_der_completo"):
    """Publica o DER completo no MotherDuck."""
    token = os.environ.get("MOTHERDUCK_TOKEN")
    if not token:
        raise RuntimeError("Configure MOTHERDUCK_TOKEN no ambiente antes da publicação")
    os.environ["motherduck_token"] = token
    banco = banco_remoto
    con = duckdb.connect("md:")
    try:
        caminho = str(Path(local).resolve()).replace("'", "''")
        con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")
        con.execute(f'CREATE DATABASE IF NOT EXISTS "{banco}"')
        con.execute(f'USE "{banco}"')
        existentes = {r[0].lower() for r in con.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_catalog=? AND table_schema='main'",
            [banco],
        ).fetchall()}
        conflito = existentes.intersection(t.lower() for t in TABELAS_DER)
        if conflito:
            raise RuntimeError(f"Banco de teste já contém tabelas: {sorted(conflito)}")
        con.execute("BEGIN TRANSACTION")
        try:
            for tabela, definicao in TABELAS_DER.items():
                con.execute(f'CREATE TABLE "{tabela}" ({definicao})')
            for tabela in TABELAS_DER:
                con.execute(f'INSERT INTO "{tabela}" SELECT * FROM origem.main."{tabela}"')
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--executar-completo", action="store_true",
                    help="Executa a pipeline completa (Q3, Q10 e Q9)")
    ap.add_argument("--somente-q9", action="store_true",
                    help="Executa exclusivamente a carga de Q9 sobre banco existente")
    ap.add_argument("--publicar-q9", action="store_true",
                    help="Publica incrementalmente apenas as tabelas de Q9 no MotherDuck")
    ap.add_argument("--publicar-teste", action="store_true",
                    help="Publica todo o banco DER no MotherDuck")
    ap.add_argument("--ufs", nargs="+", default=UFS_PADRAO,
                    help="UFs para Q3 e Q10")
    ap.add_argument("--q3-anos", nargs="+", type=int, default=Q3_ANOS)
    ap.add_argument("--q10-anos", nargs="+", type=int, default=Q10_ANOS)
    ap.add_argument("--q9-anos", nargs="+", type=int, default=Q9_ANOS,
                    help="Anos específicos da Q9 (padrão: 2018 2020 2022 2024)")
    ap.add_argument("--q9-ufs", nargs="+", default=Q9_UFS,
                    help="UFs específicas da Q9 (padrão: CE MA MS RJ RN RS)")
    ap.add_argument("--saida", type=Path, default=SAIDA_PADRAO)
    ap.add_argument("--banco-remoto", default="pipeline_bdr_der_completo",
                    help="Nome do banco de destino no MotherDuck")
    ap.add_argument("--idhm-planilhas", default="planilhas",
                    help="Pasta com planilhas XLSX do IDHM 2010")
    ap.add_argument("--idhm-csv", default="dados_bdr/fontes/idhm.csv",
                    help="CSV IDHM 2010 já preparado, usado quando não há planilhas")
    args = ap.parse_args()

    acoes = [args.executar_completo, args.somente_q9, args.publicar_q9, args.publicar_teste]
    if sum(bool(a) for a in acoes) > 1:
        ap.error("Execute apenas uma ação por comando (--executar-completo, --somente-q9, --publicar-q9 ou --publicar-teste)")
    if sum(bool(a) for a in acoes) == 0:
        ap.error("Informe uma ação: --executar-completo, --somente-q9, --publicar-q9 ou --publicar-teste")

    if args.executar_completo:
        executar_completo(args.ufs, args.q3_anos, args.q10_anos, args.q9_ufs, args.q9_anos,
                          args.saida, args.idhm_planilhas, args.idhm_csv)

    if args.somente_q9:
        executar_somente_q9(args.q9_ufs, args.q9_anos, args.saida)

    if args.publicar_q9:
        if not args.saida.is_file():
            ap.error(f"Banco local não encontrado: {args.saida}")
        publicar_q9(args.saida, args.banco_remoto)

    if args.publicar_teste:
        if not args.saida.is_file():
            ap.error(f"Banco local não encontrado: {args.saida}")
        publicar(args.saida, args.banco_remoto)
        print(f"Publicado em {args.banco_remoto}")


if __name__ == "__main__":
    main()
