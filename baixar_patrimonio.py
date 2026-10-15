#!/usr/bin/env python3
"""Baixa e normaliza bens declarados por candidatos no TSE (2018-2024)."""

import argparse
from pathlib import Path

import duckdb

from bdr.download import baixar
from bdr.extracao import extrair_por_uf
from bdr.der.patrimonio import _normalizar_arquivo


CDN_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"
ANOS_PADRAO = (2018, 2020, 2022, 2024)
UFS_PADRAO = ("CE", "MA", "MS", "RJ", "RN", "RS")
RECURSO = "bem_candidato"


def baixar_patrimonio(ufs, anos, base, banco):
    anos = sorted(set(anos))
    invalidos = [ano for ano in anos if ano not in ANOS_PADRAO]
    if invalidos:
        raise ValueError("Use somente os anos 2018, 2020, 2022 e 2024.")
    base = Path(base)
    zips = base / "zips" / RECURSO
    raw = base / "raw"
    banco = Path(banco)
    banco.parent.mkdir(parents=True, exist_ok=True)
    if banco.exists():
        banco.unlink()
    con = duckdb.connect(str(banco))
    con.execute("""
        CREATE TABLE Patrimonio_Candidato (
            ano INTEGER,
            cd_eleicao VARCHAR,
            uf VARCHAR,
            sq_candidato VARCHAR,
            numero_candidato INTEGER,
            nome_candidato VARCHAR,
            tipo_bem VARCHAR,
            descricao_bem VARCHAR,
            valor_bem DOUBLE,
            data_atualizacao DATE,
            arquivo_origem VARCHAR
        )
    """)
    try:
        for ano in anos:
            nome_zip = f"bem_candidato_{ano}"
            zip_path = zips / f"{nome_zip}.zip"
            url = f"{CDN_TSE}/bem_candidato/{nome_zip}.zip"
            print(f"[{ano}] baixando {url}", flush=True)
            status = baixar(url, zip_path)
            partes = {RECURSO: f"{RECURSO}_{{ano}}_{{uf}}"}
            arquivos, nomes = extrair_por_uf(zip_path, raw, ano, partes, list(ufs))
            print(f"     ZIP: {status}; {len(nomes)} itens; {len(arquivos)} arquivo(s)", flush=True)
            for arquivo in arquivos:
                linhas = _normalizar_arquivo(con, arquivo)
                print(f"     {arquivo.name}: {linhas:,} bens", flush=True)
        total = con.execute("SELECT count(*) FROM Patrimonio_Candidato").fetchone()[0]
        if total == 0:
            raise ValueError("Nenhum bem foi carregado; verifique o layout dos arquivos do TSE.")
        con.execute("CREATE INDEX idx_patrimonio_candidato ON Patrimonio_Candidato (ano, uf, sq_candidato)")
        print(f"Patrimônio carregado: {total:,} bens em {banco}")
    finally:
        con.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    parser.add_argument("--anos", nargs="+", type=int, default=ANOS_PADRAO)
    parser.add_argument("--dir", default="dados_bdr/trabalho_der/patrimonio_brutos")
    parser.add_argument("--banco", default="dados_bdr/saida/patrimonio_candidatos_2018_2024.duckdb")
    args = parser.parse_args()
    baixar_patrimonio(args.ufs, args.anos, args.dir, args.banco)


if __name__ == "__main__":
    main()
