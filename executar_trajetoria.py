#!/usr/bin/env python3
"""Executa a pipeline histórica de trajetória eleitoral (2002-2024)."""

import argparse
import sys

from bdr.trajetoria.config import ANOS_TRAJETORIA, UFS_PADRAO, montar_escopo
from bdr.trajetoria.motherduck import publicar
from bdr.trajetoria.pipeline import Pastas, baixar_fontes, carregar_validar, exportar_dados


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    p.add_argument("--anos", nargs="+", type=int, default=ANOS_TRAJETORIA)
    p.add_argument(
        "--etapas", nargs="+",
        choices=["baixar", "carregar", "validar", "exportar", "motherduck"],
        default=["baixar", "carregar", "exportar"],
    )
    p.add_argument("--dir", default="dados_bdr/q10")
    p.add_argument("--apagar-zips", action="store_true")
    p.add_argument("--motherduck-db")
    p.add_argument("--substituir", action="store_true")
    a = p.parse_args()
    if "motherduck" in a.etapas and not a.motherduck_db:
        p.error("--etapas motherduck exige --motherduck-db")
    escopo = montar_escopo(a.ufs, a.anos)
    pastas = Pastas(a.dir, escopo["rotulo"])
    print(f"Trajetória eleitoral | UFs: {', '.join(escopo['ufs'])}")
    print(f"Anos: {', '.join(map(str, escopo['anos']))}")
    registro, problemas = [], []
    try:
        if "baixar" in a.etapas:
            registro, problemas = baixar_fontes(escopo, pastas, a.apagar_zips)
        if "carregar" in a.etapas or "validar" in a.etapas:
            carregar_validar(escopo, pastas, registro, problemas)
        if "exportar" in a.etapas:
            destino = exportar_dados(pastas)
            print(f"Backup Parquet: {destino}")
        if "motherduck" in a.etapas:
            publicar(pastas.banco, a.motherduck_db, a.substituir)
            print(f"Trajetória publicada no MotherDuck: {a.motherduck_db}")
    except (ValueError, RuntimeError) as exc:
        sys.exit(f"ERRO: {exc}")


if __name__ == "__main__":
    main()
