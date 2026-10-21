"""Entrega local de fotos; não importa a aquisição nem abre o banco eleitoral."""
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from bdr.fotos.catalogo import LeitorCatalogo, configuracao

router = APIRouter()


@lru_cache(maxsize=4)
def _leitor(banco, imagens):
    return LeitorCatalogo(banco, imagens)


def leitor():
    imagens, banco, _ = configuracao()
    return _leitor(str(banco), str(imagens))


def enriquecer(candidatos):
    """Uma consulta SQLite indexada por lote, sem modificar objetos do cache da Q9."""
    catalogo = leitor()
    fotos = catalogo.buscar([c['id_candidato'] for c in candidatos])
    resultado = []
    for candidato in candidatos:
        row = fotos.get(candidato['id_candidato'], {})
        status = row.get('foto_status', 'nao_processada')
        disponivel = bool(catalogo.arquivo(row))
        if status == 'disponivel' and not disponivel:
            status = 'arquivo_indisponivel'
        resultado.append({**candidato,
            'foto_url': '/api/candidatos/' + quote(candidato['id_candidato'], safe='') + '/foto?v=' + row['sha256'][:16] if disponivel else None,
            'foto_ano': row.get('foto_ano') if disponivel else None,
            'foto_status': status,
            'foto_anterior': bool(row.get('foto_anterior')) if disponivel else False,
            'foto_cobertura_completa': bool(row.get('cobertura_completa')),
            'foto_ultima_status': row.get('ultima_foto_status', 'nao_processada'),
            'foto_ultima_candidatura': {'ano': row.get('ultima_ano'), 'data': row.get('ultima_data'),
                                      'uf': row.get('ultima_uf')} if row.get('ultima_ano') else None})
    return resultado


@router.get('/api/candidatos/{id_candidato}/foto')
def foto_candidato(id_candidato: str, request: Request):
    catalogo = leitor()
    row = catalogo.buscar([id_candidato]).get(id_candidato, {})
    path = catalogo.arquivo(row)
    if not path:
        raise HTTPException(404, 'Foto local indisponível', headers={'Cache-Control': 'no-store'})
    etag = '"' + row['sha256'] + '"'
    headers = {'Cache-Control': 'public, max-age=3600, must-revalidate', 'ETag': etag,
               'X-Content-Type-Options': 'nosniff'}
    if etag in [tag.strip() for tag in request.headers.get('if-none-match', '').split(',')]:
        return Response(status_code=304, headers=headers)
    return FileResponse(path, media_type=row['mime'], headers=headers)
