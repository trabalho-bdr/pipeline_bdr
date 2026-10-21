"""Descoberta CKAN e leitura incremental dos cadastros oficiais, sem extraí-los no disco."""
import csv
import hashlib
import io
import json
import re
import stat
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from bdr.download import baixar
from bdr.trajetoria.transformacao import ALIASES, _cpf_valido

PORTAL = 'https://dadosabertos.tse.jus.br'
MAX_PACOTE = 4 * 1024**3
MAX_CADASTRO = 3 * 1024**3


def agora():
    return datetime.now(timezone.utc).isoformat()


def hash_texto(texto):
    return hashlib.sha256(texto.encode('utf8')).hexdigest()


def sequencial(valor):
    texto = str(valor).strip() if valor is not None else ''
    return texto if re.fullmatch(r'[0-9]+', texto) and int(texto) > 0 else None


def titulo(valor):
    """Título é chave candidata, sempre acompanhado de nome+nascimento exatos."""
    texto = str(valor or '').strip()
    if not re.fullmatch(r'[0-9]{1,12}', texto) or int(texto) == 0:
        return None
    return hash_texto('TITULO|' + texto.zfill(12))


def normalizar(texto):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD', str(texto or ''))
                           if unicodedata.category(c) != 'Mn').upper().split())


def data_iso(valor):
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(valor).strip(), fmt).date().isoformat()
        except ValueError:
            pass
    return None


def biografia(nome, nascimento):
    data = data_iso(nascimento)
    nome = normalizar(nome)
    return hash_texto(nome + '|' + data) if nome and data else None


def url_oficial(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not (p.hostname == 'tse.jus.br' or (p.hostname or '').endswith('.tse.jus.br')):
        raise ValueError('Recurso fora do domínio HTTPS oficial do TSE')
    return url


def json_oficial(url):
    url_oficial(url)
    erro = None
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as resposta:
                url_oficial(resposta.url)
                data = resposta.read(16 * 1024**2 + 1)
                if len(data) > 16 * 1024**2:
                    raise ValueError('Metadados excedem o limite')
                return json.loads(data)
        except (OSError, ValueError) as e:
            erro = e
            if tentativa < 2:
                time.sleep(tentativa + 1)
    raise RuntimeError('Não foi possível consultar o catálogo oficial') from erro


def descobrir(cache, atualizar=False):
    """Enumera os conjuntos reais, inclusive conjuntos suplementares com candidatos no nome."""
    path = Path(cache) / 'catalogo-tse.json'
    if path.exists() and not atualizar:
        return json.loads(path.read_text(encoding='utf8'))
    pacotes, inicio = [], 0
    while True:
        query = urllib.parse.urlencode({'q': 'candidatos', 'rows': 100, 'start': inicio})
        data = json_oficial(PORTAL + '/api/3/action/package_search?' + query)
        if not data.get('success'):
            raise ValueError('Resposta inválida da API CKAN')
        resultado = data['result']
        for item in resultado['results']:
            nome = item['name']
            match = re.search(r'(?:^|-)candidatos-(\d{4})(?:-|$)', nome)
            if match:
                pacotes.append({'dataset': nome, 'ano': int(match[1]), 'resources': item['resources'],
                                'url': PORTAL + '/dataset/' + nome, 'consultado': agora()})
        inicio += len(resultado['results'])
        if inicio >= resultado['count']:
            break
        if not resultado['results']:
            raise ValueError('Catálogo CKAN truncado')
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(pacotes, ensure_ascii=False), encoding='utf8')
    tmp.replace(path)
    return pacotes


def recurso_cadastro(pacote):
    recursos = [r for r in pacote['resources'] if normalizar(r.get('name')) == 'CANDIDATOS']
    if len(recursos) != 1:
        raise ValueError('Cadastro ausente ou ambíguo nos metadados')
    return url_oficial(recursos[0]['url'])


def recurso_fotos(pacote, uf):
    recursos = [r for r in pacote['resources']
                if normalizar(r.get('name')) == f'{uf} - FOTOS DE CANDIDATOS']
    if not recursos:
        raise FileNotFoundError('Pacote de fotos não publicado no catálogo')
    if len(recursos) != 1:
        raise ValueError('Mais de um pacote oficial de fotos para a UF')
    return url_oficial(recursos[0]['url'])


def membro_seguro(info):
    # ZipInfo normaliza barras invertidas no Windows; orig_filename preserva a entrada.
    nome = info.orig_filename
    path = PurePosixPath(nome)
    modo = info.external_attr >> 16
    if ('\\' in nome or ':' in nome or path.is_absolute() or '..' in path.parts
            or '\x00' in nome or stat.S_ISLNK(modo)):
        raise ValueError('ZIP com caminho inseguro')
    return path


def validar_zip(path):
    with zipfile.ZipFile(path) as z:
        if len(z.infolist()) > 2_000_000:
            raise ValueError('ZIP com entradas demais')
        for info in z.infolist():
            membro_seguro(info)
        # CRC e conteúdo de cada entrada utilizada são verificados ao terminar a leitura.


def pacote_local(url, cache, atualizar=False):
    nome = PurePosixPath(urllib.parse.urlsplit(url).path).name
    if not nome.lower().endswith('.zip'):
        raise ValueError('Recurso oficial não é um pacote ZIP reconhecido')
    destino = Path(cache) / nome
    try:
        baixar(url_oficial(url), destino, tentativas=3, timeout=60, max_bytes=MAX_PACOTE,
               atualizar=atualizar, validar=validar_zip)
    except (zipfile.BadZipFile, ValueError):
        # Cache inválido não é aceito silenciosamente; --atualizar permite substituí-lo.
        raise
    return destino


def linhas_cadastro(path, ufs):
    """Layouts com cabeçalho e aliases da pipeline. Layout desconhecido falha explicitamente."""
    with zipfile.ZipFile(path) as z:
        arquivos = [i for i in z.infolist() if not i.is_dir() and i.filename.lower().endswith('.csv')]
        separados = [i for i in arquivos if any(re.search('_' + uf + r'\.csv$', i.filename, re.I) for uf in ufs)]
        arquivos = separados or [i for i in arquivos if re.search(r'_BRASIL\.csv$', i.filename, re.I)]
        if not arquivos:
            raise ValueError('Nenhum CSV reconhecido para o recorte')
        for info in arquivos:
            membro_seguro(info)
            if info.file_size > MAX_CADASTRO:
                raise ValueError('Cadastro excede o limite descompactado')
            # Mesmo Latin-1 utilizado por bdr/extracao.py; alguns cadastros contêm
            # bytes C1 indefinidos em CP1252. Não substitui caracteres da identidade.
            with z.open(info) as raw, io.TextIOWrapper(raw, encoding='latin-1', newline='') as stream:
                reader = csv.DictReader(stream, delimiter=';')
                cols = {c.strip('\ufeff').upper(): c for c in (reader.fieldnames or [])}
                campos = {k: next((cols[a] for a in aliases if a in cols), None) for k, aliases in ALIASES.items()}
                if not all(campos[k] for k in ('ano', 'uf', 'sq_candidato', 'nome', 'nascimento')):
                    raise ValueError('Layout de cadastro desconhecido')
                for linha, row in enumerate(reader, 2):
                    def campo(k):
                        return (row.get(campos[k]) or '').strip() if campos.get(k) else ''
                    uf = campo('uf').upper()
                    if uf not in ufs:
                        continue
                    sq = sequencial(campo('sq_candidato'))
                    if not sq:
                        yield None  # conta pendências de registros inválidos
                        continue
                    ano = int(campo('ano'))
                    data = data_iso(campo('dt_eleicao'))
                    cpf = _cpf_valido(campo('cpf'))
                    yield {'ano': ano, 'data': data, 'ordem': data or f'{ano}-01-01',
                           'uf': uf, 'sequencial': sq, 'eleicao': campo('cd_eleicao'),
                           'bio': biografia(campo('nome'), campo('nascimento')),
                           'cpf': hash_texto('CPF|' + cpf) if cpf else None,
                           'id_cpf': hashlib.md5(('CPF|' + cpf).encode()).hexdigest() if cpf else None,
                           'titulo': titulo(campo('titulo')), 'origem': info.filename, 'linha': linha}
