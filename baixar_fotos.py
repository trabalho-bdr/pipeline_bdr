"""Acrescenta uma foto oficial por candidato ao DER local, com retomada automática."""
import argparse
from pathlib import Path

import duckdb

from bdr.der.fotos import executar


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--banco', type=Path, default=Path('dados_bdr/saida/pipeline_bdr_der_completo_v2_demografia.duckdb'))
    ap.add_argument('--ufs', nargs='+', help='Padrão: UFs da tabela Municipio do DER')
    ap.add_argument('--ano-minimo', type=int, default=2020)
    ap.add_argument('--anos', nargs='+', type=int, help='Opcional: limitar os anos consultados')
    ap.add_argument('--cache', type=Path, default=Path('dados_bdr/fotos'))
    ap.add_argument('--somente-cache', action='store_true', help='Carrega ZIPs existentes sem acessar a rede')
    args = ap.parse_args()
    if not args.banco.is_file():
        ap.error(f'Banco não encontrado: {args.banco}')
    if args.anos and any(ano < 2006 or ano > 2024 or ano % 2 for ano in args.anos):
        ap.error('Use anos eleitorais de 2006 a 2024')
    with duckdb.connect(str(args.banco)) as con:
        resultado = executar(con, args.cache, args.ufs, args.ano_minimo, args.anos, args.somente_cache)
        print(f"Fotos no DER: {resultado['total_com_foto']:,}; candidatos ainda sem foto no recorte: "
              f"{resultado['candidatos_sem_foto_no_recorte']:,}")


if __name__ == '__main__':
    main()
