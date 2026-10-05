#!/usr/bin/env python3
"""Baixa BUs oficiais do TSE: RJ/RN, 2022/2024, primeiro e segundo turno.

Não requer pacotes externos. Mantém todas as colunas do CSV, em UTF-8.
Exemplo: python baixar_boletins.py --ufs RJ RN --anos 2022 2024 --turnos 1 2
"""
import argparse

from bdr.boletins import obter_boletins, planejar


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ufs", nargs="+", type=str.upper, choices=["RJ", "RN"], default=["RJ", "RN"])
    p.add_argument("--anos", nargs="+", type=int, choices=[2022, 2024], default=[2022, 2024])
    p.add_argument("--turnos", nargs="+", type=int, choices=[1, 2], default=[1, 2])
    p.add_argument("--dir", default="dados_bdr", help="Pasta base dos dados")
    p.add_argument("--listar", action="store_true", help="Mostra os links sem baixar")
    p.add_argument("--sem-download", action="store_true", help="Usa os ZIPs em cache para extrair")
    a = p.parse_args()
    plano = planejar(a.ufs, a.anos, a.turnos)
    if a.listar:
        for r in plano:
            print(f"{r['ano']} {r['uf']} {r['turno']}t: {r['url']}")
        return 0
    caminho, manifesto = obter_boletins(plano, a.dir, a.sem_download)
    print(f"\nManifesto: {caminho}")
    if not manifesto["completo"]:
        print("Recorte incompleto. Corrija os erros e execute novamente; arquivos completos são reutilizados.")
        return 1
    print(f"Concluído: {len(manifesto['arquivos'])} arquivos de boletins de urna.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
