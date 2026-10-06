#!/usr/bin/env python3
"""Junta os pacotes dos 4 membros num banco único (etapa de quem faz o load).

Uso:
  python juntar.py membro1_para_drive.zip membro2_para_drive.zip membro3_para_drive.zip membro4_para_drive.zip
  python juntar.py dados_bdr/drive/*.zip --saida dados_bdr/bdr_consolidado.duckdb
"""
import argparse
import json
import zipfile
from pathlib import Path

from bdr.juntar import juntar
from bdr.motherduck import enviar_banco


def validar_quatro_membros(pacotes):
    rotulos = []
    for pacote in pacotes:
        caminho = Path(pacote)
        if caminho.is_dir():
            manifesto = json.loads((caminho / "manifesto.json").read_text(encoding="utf-8"))
        else:
            with zipfile.ZipFile(caminho) as arquivo:
                manifesto = json.loads(arquivo.read("manifesto.json"))
        rotulos.append(manifesto.get("rotulo"))
    esperados = {f"membro{i}" for i in range(1, 5)}
    if len(rotulos) != 4 or set(rotulos) != esperados:
        raise ValueError(f"Para o upload consolidado, informe exatamente os pacotes dos membros 1, 2, 3 e 4 (recebidos: {rotulos}).")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pacotes", nargs="+", help="ZIPs (ou pastas) gerados por executar.py")
    p.add_argument("--saida", default="dados_bdr/bdr_consolidado.duckdb")
    p.add_argument("--tmp", default="dados_bdr/_juntar")
    p.add_argument("--motherduck-db", help="envia o banco consolidado para um novo banco no MotherDuck")
    a = p.parse_args()
    if a.motherduck_db:
        try:
            validar_quatro_membros(a.pacotes)
        except (ValueError, OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as e:
            p.exit(1, f"ERRO nos pacotes: {e}\n")
    print("Pacotes")
    juntar(a.pacotes, a.saida, a.tmp)
    print(f"\nBanco consolidado: {a.saida}")
    if a.motherduck_db:
        try:
            nome = enviar_banco(a.saida, a.motherduck_db)
        except ValueError as e:
            p.exit(1, f"ERRO: {e}\n")
        print(f"Banco consolidado enviado ao MotherDuck: {nome}")


if __name__ == "__main__":
    main()
