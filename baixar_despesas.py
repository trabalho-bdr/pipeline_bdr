#!/usr/bin/env python3
"""Baixa somente despesas contratadas de candidatos do TSE até 2024."""

import argparse
from pathlib import Path

from bdr.der.q10_bruto import _baixar_recurso
from bdr.extracao import extrair_por_uf
from bdr.trajetoria.config import CDN_TSE, RECURSOS


ANOS_PADRAO = tuple(range(2002, 2025, 2))
UFS_PADRAO = ("CE", "MA", "MS", "RJ", "RN", "RS")


def baixar_despesas(ufs, anos, base):
    recurso = "despesas_contratadas_candidatos"
    config = RECURSOS[recurso]
    base = Path(base)
    zips = base / "zips" / recurso
    raw = base / "raw"
    zips.mkdir(parents=True, exist_ok=True)
    problemas = []

    for ano in sorted(set(anos)):
        if ano not in ANOS_PADRAO:
            raise ValueError(f"Ano inválido: {ano}. Use anos de 2002 a 2024.")
        nome = config["zip"].format(ano=ano)
        zip_path = zips / f"{nome}.zip"
        print(f"[{ano}] baixando prestação de contas de candidatos")
        try:
            status = _baixar_recurso(ano, recurso, zip_path)
            arquivos, nomes = extrair_por_uf(
                zip_path, raw, ano, config["partes"], list(ufs)
            )
            print(f"     ZIP: {status}; {len(nomes)} itens; {len(arquivos)} CSV(s) extraído(s)")
        except Exception as exc:
            problemas.append(f"{ano}: {exc}")
            print(f"     ERRO: {exc}")

    if problemas:
        raise RuntimeError("Falhas no download:\n- " + "\n- ".join(problemas))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ufs", nargs="+", default=UFS_PADRAO)
    parser.add_argument("--anos", nargs="+", type=int, default=ANOS_PADRAO)
    parser.add_argument("--dir", default="dados_bdr/trabalho_der/q10_brutos")
    args = parser.parse_args()
    baixar_despesas(args.ufs, args.anos, args.dir)
    print("Despesas contratadas baixadas sem carregar candidaturas ou transformar o DER.")


if __name__ == "__main__":
    main()
