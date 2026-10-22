"""Gera uma cópia do DER com perfil do eleitorado e idade municipal, sem publicar."""
import argparse
import shutil
from pathlib import Path

import duckdb

from bdr.der.demografia import enriquecer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", type=Path, required=True)
    parser.add_argument("--saida", type=Path, required=True)
    parser.add_argument("--anos", nargs="+", type=int, default=[2018, 2020, 2022, 2024])
    parser.add_argument("--cache", type=Path, default=Path("dados_bdr/demografia"))
    parser.add_argument("--retomar", action="store_true", help="Reutiliza a cópia parcial após falha")
    args = parser.parse_args()
    if not args.origem.is_file():
        parser.error("Banco de origem não encontrado")
    if args.saida.exists():
        parser.error("A saída já existe; escolha um novo arquivo")
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    parcial = args.saida.with_suffix(".parcial.duckdb")
    if parcial.exists() and not args.retomar:
        parser.error(f"Arquivo parcial já existe: {parcial}")
    # A origem é somente inspecionada; o enriquecimento acontece na cópia.
    with duckdb.connect(str(args.origem), read_only=True) as origem:
        ufs = [r[0] for r in origem.execute("SELECT DISTINCT uf FROM Municipio").fetchall()]
        anos = {r[0] for r in origem.execute("SELECT DISTINCT ano FROM Eleicao").fetchall()}
    anos_carga = sorted(set(args.anos) & anos)
    if set(args.anos) - anos:
        print(f"Aviso: anos sem eleições na origem serão ignorados: {sorted(set(args.anos) - anos)}")
    if not anos_carga:
        parser.error("Nenhum dos anos solicitados existe nas eleições da origem")
    if args.origem.with_suffix(args.origem.suffix + ".wal").exists():
        parser.error("Feche a conexão que escreve na origem antes de copiar o banco (WAL presente)")
    if not parcial.exists():
        shutil.copy2(args.origem, parcial)
    with duckdb.connect(str(parcial)) as con:
        enriquecer(con, ufs, anos_carga, args.cache)
    parcial.replace(args.saida)
    print(f"DER enriquecido: {args.saida}")


if __name__ == "__main__":
    main()
