"""Envia somente Foto_Candidato ao MotherDuck existente, sem repetir fotos."""
import argparse
import os
import re
from pathlib import Path

import duckdb

from bdr.der.fotos import FOTO_DDL


def copiar_fotos(con, banco):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', banco):
        raise ValueError('Nome do banco inválido')
    destino = f'"{banco}".main'
    total = con.execute('SELECT count(*) FROM origem.main.Foto_Candidato').fetchone()[0]
    if not total:
        raise ValueError('Banco local sem fotos; execute baixar_fotos.py primeiro')
    # Verifica a candidatura de origem no destino, além da FK da pessoa.
    sem_vinculo = con.execute(f'''SELECT count(*) FROM origem.main.Foto_Candidato f
        WHERE NOT EXISTS (SELECT 1 FROM {destino}.Candidatura c
            JOIN {destino}.Eleicao e USING(id_eleicao)
            WHERE c.id_candidato=f.id_candidato AND e.ano=f.ano_foto
              AND upper(c.uf)=f.uf AND try_cast(c.sequencial AS BIGINT)=try_cast(f.sq_candidato AS BIGINT))''').fetchone()[0]
    if sem_vinculo:
        raise ValueError(f'{sem_vinculo} fotos sem candidatura correspondente no destino; nenhuma foto enviada')
    con.execute(f'USE "{banco}"')
    con.execute('BEGIN TRANSACTION')
    try:
        con.execute(f'CREATE TABLE IF NOT EXISTS {destino}.Foto_Candidato ({FOTO_DDL})')
        conflitos = con.execute(f'''SELECT count(*) FROM origem.main.Foto_Candidato o
            JOIN {destino}.Foto_Candidato d USING(id_candidato) WHERE o.sha256<>d.sha256''').fetchone()[0]
        if conflitos:
            raise ValueError(f'{conflitos} candidatos já têm outra foto no destino; nenhuma substituição automática')
        antes = con.execute(f'SELECT count(*) FROM {destino}.Foto_Candidato').fetchone()[0]
        con.execute(f'''INSERT INTO {destino}.Foto_Candidato SELECT o.* FROM origem.main.Foto_Candidato o
            WHERE NOT EXISTS (SELECT 1 FROM {destino}.Foto_Candidato d WHERE d.id_candidato=o.id_candidato)''')
        confirmados = con.execute(f'''SELECT count(*) FROM origem.main.Foto_Candidato o
            JOIN {destino}.Foto_Candidato d USING(id_candidato)
            WHERE o.sha256=d.sha256 AND o.imagem=d.imagem''').fetchone()[0]
        if confirmados != total:
            raise RuntimeError('Verificação de conteúdo divergiu; transação cancelada')
        depois = con.execute(f'SELECT count(*) FROM {destino}.Foto_Candidato').fetchone()[0]
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise
    return depois - antes, confirmados


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--banco-local', type=Path, default=Path('dados_bdr/saida/pipeline_bdr_der_completo_v2_demografia.duckdb'))
    ap.add_argument('--motherduck-db', default='pipeline_bdr_der_completo_v2')
    args = ap.parse_args()
    if not args.banco_local.is_file():
        ap.error('Banco local não encontrado')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', args.motherduck_db):
        ap.error('Nome MotherDuck inválido')
    token = os.environ.get('MOTHERDUCK_TOKEN') or os.environ.get('motherduck_token')
    if token:
        os.environ['motherduck_token'] = token
    caminho = args.banco_local.resolve().as_posix().replace("'", "''")
    with duckdb.connect('md:') as con:
        con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")
        inseridas, confirmadas = copiar_fotos(con, args.motherduck_db)
        print(f'Fotos: {inseridas} novas; {confirmadas} verificadas no MotherDuck')


if __name__ == '__main__':
    main()
