#!/usr/bin/env python3
"""Junta os pacotes dos 4 membros num banco único (etapa de quem faz o load).

Uso:
  python juntar.py membro1_para_drive.zip membro2_para_drive.zip membro3_para_drive.zip membro4_para_drive.zip
  python juntar.py dados_bdr/drive/*.zip --saida dados_bdr/bdr_consolidado.duckdb
"""
import argparse

from bdr.juntar import juntar


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pacotes", nargs="+", help="ZIPs (ou pastas) gerados por executar.py")
    p.add_argument("--saida", default="dados_bdr/bdr_consolidado.duckdb")
    p.add_argument("--tmp", default="dados_bdr/_juntar")
    a = p.parse_args()
    print("Pacotes")
    juntar(a.pacotes, a.saida, a.tmp)
    print(f"\nBanco consolidado: {a.saida}")


if __name__ == "__main__":
    main()
