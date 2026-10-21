#!/usr/bin/env python3
"""Script executável para deduplicar as fotografias dos candidatos.

Mantém somente a foto mais recente de cada pessoa e exclui as demais imagens
associadas a ela.

Uso:
  uv run python deduplicar_fotos.py              # Modo simulação (padrão)
  uv run python deduplicar_fotos.py --aplicar    # Efetiva consolidação e exclusão
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Assegurar raiz do projeto no sys.path
RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bdr.fotos.catalogo import abrir, configuracao
from bdr.fotos.deduplicacao import (
    AuditoriaCatalogoDisco,
    construir_plano,
    executar_deduplicacao,
    obter_banco_der_padrao,
    salvar_relatorios,
)


def parser():
    p = argparse.ArgumentParser(
        description="Deduplicação e consolidação das fotos de candidatos na imagem mais recente."
    )
    p.add_argument(
        "--aplicar",
        action="store_true",
        help="Aplica as mudanças: move a foto escolhida para 'fotos selecionadas', atualiza o catálogo e exclui os excedentes.",
    )
    p.add_argument(
        "--simular",
        action="store_true",
        help="Modo simulação (padrão se --aplicar não for informado). Não altera arquivos nem o banco.",
    )
    p.add_argument(
        "--banco",
        default=os.environ.get("BDR_BANCO"),
        help="Caminho do DER local DuckDB (ex.: dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb). Aberto somente para leitura.",
    )

    padrao_origem = RAIZ / "dados_bdr" / "fotos" / "imagens"
    padrao_destino = RAIZ / "dados_bdr" / "fotos selecionadas"
    padrao_catalogo = RAIZ / "dados_bdr" / "fotos" / "catalogo.sqlite3"

    p.add_argument(
        "--catalogo",
        type=Path,
        default=padrao_catalogo,
        help="Caminho do catálogo SQLite (default: dados_bdr/fotos/catalogo.sqlite3)",
    )
    p.add_argument(
        "--origem",
        type=Path,
        default=padrao_origem,
        help="Diretório das fotos originais (default: dados_bdr/fotos/imagens)",
    )
    p.add_argument(
        "--destino",
        type=Path,
        default=padrao_destino,
        help="Diretório final das fotos selecionadas (default: 'dados_bdr/fotos selecionadas')",
    )
    p.add_argument(
        "--saida-relatorios",
        type=Path,
        default=RAIZ / "dados_bdr" / "fotos",
        help="Diretório onde relatórios e manifestos serão salvos (fora de fotos selecionadas)",
    )
    p.add_argument(
        "--pessoa",
        action="append",
        default=[],
        help="id_candidato para processamento pontual; pode ser repetido",
    )
    p.add_argument(
        "--limite",
        type=int,
        default=None,
        help="Limite de pessoas para análise ou processamento em lote",
    )
    p.add_argument(
        "--auditar-disco",
        action="store_true",
        help="Confronta integralmente o catálogo com os arquivos presentes em disco",
    )
    return p


def main():
    args = parser().parse_args()

    # O modo de simulação é o padrão
    modo_aplicar = bool(args.aplicar)
    modo_str = "APLICAÇÃO EFETIVA" if modo_aplicar else "SIMULAÇÃO (Sem alterações em disco)"

    print("=" * 80)
    print("DEDUPLICAÇÃO DE FOTOS - CANDIDATOS BDR")
    print(f"Modo: {modo_str}")
    print(f"Catálogo: {args.catalogo}")
    print(f"Origem:   {args.origem}")
    print(f"Destino:  {args.destino}")
    print("=" * 80)

    if not args.catalogo.is_file():
        sys.exit(f"Erro: Catálogo SQLite não encontrado em {args.catalogo}")

    banco_der = args.banco or obter_banco_der_padrao()
    if not banco_der:
        sys.exit("Erro: Banco DER não configurado. Informe --banco ou configure BDR_BANCO.")

    print(f"Consultando DER eleitoral (somente leitura): {banco_der}")

    cat = abrir(args.catalogo)
    try:
        if args.auditar_disco:
            print("Confrontando catálogo com os arquivos em disco...")
            auditor = AuditoriaCatalogoDisco(cat, args.origem)
            resultado_auditoria = auditor.auditar(args.pessoa if args.pessoa else None)
            print(f"  Verificados: {resultado_auditoria['total_verificados']}")
            print(f"  Válidos:     {resultado_auditoria['validos']}")
            print(f"  Ausentes:    {len(resultado_auditoria['ausentes'])}")
            print(f"  Corrompidos: {len(resultado_auditoria['corrompidos'])}")

        print("Construindo plano de consolidação e exclusão...")
        plano = construir_plano(
            cat=cat,
            der_path_ou_con=banco_der,
            raiz_origem=args.origem,
            raiz_destino=args.destino,
            ids_filtro=args.pessoa if args.pessoa else None,
            limite=args.limite,
        )

        resumo = plano["resumo"]
        print("\n--- RESUMO DO PLANO ---")
        print(f"Pessoas analisadas:             {resumo['total_pessoas_analisadas']:,}")
        print(f"Pessoas consolidadas:           {resumo['consolidadas']:,}")
        print(f"  - Foto anterior utilizada:    {resumo['foto_anterior_utilizada']:,}")
        print(f"Pessoas sem foto válida:        {resumo['sem_foto_valida']:,}")
        print(f"Pendências de ambiguidade:      {resumo['pendencias_ambiguidade']:,}")
        print(f"Pendências de empate de datas:  {resumo['pendencias_empate']:,}")
        print(f"Pendências de colisão de rota:  {resumo['pendencias_colisao']:,}")
        print(f"Pendências de nome ausente:     {resumo['pendencias_sem_nome']:,}")
        print(f"Pendências de arquivo inválido: {resumo['pendencias_arquivo_invalido']:,}")
        print(f"Imagens excedentes a excluir:   {resumo['total_excedentes_para_excluir']:,}")
        print(f"Espaço excedente a recuperar:   {resumo['bytes_excedentes_recuperados'] / (1024**2):,.2f} MB")
        print("-----------------------\n")
    finally:
        cat.close()

    print(f"Executando processo em modo: {modo_str}...")
    resultado = executar_deduplicacao(
        plano_completo=plano,
        cat_path=args.catalogo,
        raiz_origem=args.origem,
        raiz_destino=args.destino,
        aplicar=modo_aplicar,
    )

    caminhos_rel = salvar_relatorios(resultado, args.saida_relatorios)
    print("\nRelatórios gerados com sucesso:")
    print(f"  JSON detalhado: {caminhos_rel['relatorio_json']}")
    print(f"  Manifesto:      {caminhos_rel['manifesto_json']}")
    print(f"  Resumo texto:   {caminhos_rel['resumo_txt']}")

    if not modo_aplicar:
        print("\n[SIMULAÇÃO CONCLUÍDA SEM ALTERAÇÕES NOS ARQUIVOS]")
        print("Para efetivar a consolidação e exclusão definitiva dos excedentes, execute com a flag --aplicar:")
        print(f'  uv run python deduplicar_fotos.py --aplicar --origem "{args.origem}" --destino "{args.destino}"')
    else:
        print("\n[APLICAÇÃO CONCLUÍDA COM SUCESSO]")


if __name__ == "__main__":
    main()
