#!/usr/bin/env python3
"""Executa a pipeline de dados eleitorais e socioeconômicos da Questão 3 do BDR.

Questão 3:
"Como características socioeconômicas dos municípios se relacionam com a distribuição
dos votos entre partidos e com a taxa de abstenção?"

Escopo temporal: 2022 e 2024.
Cada membro da equipe é responsável por exatamente 2 UFs.

Etapas (todas por padrão):
  baixar    Boletins de Urna (TSE), indicadores socioeconômicos (IBGE) e de-para TSE-IBGE
  carregar  Staging e tabelas do DER (DuckDB) com todas as validações obrigatórias
  exportar  Parquet + manifesto -> dados_bdr/saida/<membro>_para_drive.zip

Exemplos de execução:
  uv run python executar.py --membro 3                      # recorte completo do membro 3 (RJ, RN)
  uv run python executar.py --ufs RJ --anos 2024           # teste com uma UF e um ano
  uv run python executar.py --membro 3 --etapas baixar      # somente download
  uv run python executar.py --membro 3 --etapas carregar exportar # reutiliza dados locais
"""
import argparse
import sys

from bdr.config import MEMBROS, montar_escopo
from bdr.leitura import ErroLayout
from bdr.motherduck import enviar_membro
from bdr.pipeline import Pastas, etapa_baixar, etapa_carregar, etapa_exportar


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    quem = p.add_mutually_exclusive_group(required=True)
    quem.add_argument("--membro", type=int, choices=sorted(MEMBROS),
                      help="número do membro do grupo (processa as 2 UFs atribuídas)")
    quem.add_argument("--ufs", nargs="+", help="recorte livre de UFs (ex.: RJ RN)")
    p.add_argument("--anos", type=int, nargs="+", help="anos a processar (padrão: 2022 2024)")
    p.add_argument("--etapas", nargs="+", choices=["baixar", "carregar", "exportar", "motherduck"],
                   default=["baixar", "carregar", "exportar"],
                   help="etapas a executar (padrão: baixar carregar exportar)")
    p.add_argument("--motherduck-db", help="nome do banco compartilhado no MotherDuck (usado com --etapas motherduck)")
    p.add_argument("--substituir-ufs", action="store_true",
                   help="substitui no MotherDuck as UFs já existentes pela versão local")
    p.add_argument("--remover-ufs-motherduck", nargs="+", metavar="UF",
                   help="remove estas UFs do MotherDuck durante a atualização")
    p.add_argument("--dir", default="dados_bdr", help="pasta base de dados (padrão: dados_bdr)")
    p.add_argument("--de-para", default="dados_bdr/fontes/municipio_tse_ibge.csv",
                   help="CSV de correspondência município TSE <-> IBGE (opcional)")
    p.add_argument("--apagar-zips", action="store_true", help="apaga os ZIPs baixados após extração")
    a = p.parse_args()
    if "motherduck" in a.etapas and not a.motherduck_db:
        p.error("--etapas motherduck exige --motherduck-db")
    if a.motherduck_db and "motherduck" not in a.etapas:
        p.error("--motherduck-db exige --etapas motherduck")

    escopo = montar_escopo(a.membro, a.ufs, a.anos)
    pastas = Pastas(a.dir, escopo["rotulo"])

    print("=" * 60)
    print(f"PIPELINE BDR - QUESTÃO 3 | {escopo['rotulo'].upper()}")
    print(f"UFs: {', '.join(escopo['ufs'])} | Anos: {', '.join(str(ano) for ano in escopo['anos'])}")
    print(f"Fontes TSE: Boletins de Urna (BUweb)")
    print(f"Fontes IBGE: Localidades, População Censo 2022, PIB 2022 e IDHM 2010")
    print("=" * 60)

    try:
        if "baixar" in a.etapas:
            problemas = etapa_baixar(escopo, pastas, a.apagar_zips)
            if problemas:
                print("\nAVISOS DE DOWNLOAD:\n   " + "\n   ".join(problemas))
        if "carregar" in a.etapas:
            etapa_carregar(escopo, pastas, a.de_para)
        if "exportar" in a.etapas:
            zip_final = etapa_exportar(pastas)
            print(f"\nPacote exportado para o Drive: {zip_final}")
        if "motherduck" in a.etapas:
            nome = enviar_membro(
                pastas.banco, a.motherduck_db, a.substituir_ufs,
                a.remover_ufs_motherduck,
            )
            print(f"\nDados do membro adicionados ao banco MotherDuck: {nome}")
    except ValueError as e:
        sys.exit(f"\nERRO: {e}")
    except ErroLayout as e:
        sys.exit(f"\nERRO DE LAYOUT: {e}")


if __name__ == "__main__":
    main()
