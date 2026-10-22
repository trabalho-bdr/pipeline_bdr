"""Uma foto oficial por pessoa, vinculada por (ano, UF, SQ_CANDIDATO) ao DER."""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from bdr.download import baixar
from bdr.ibge import UF_CODIGOS


FOTO_DDL = """id_candidato VARCHAR PRIMARY KEY,
    ano_foto INTEGER NOT NULL, uf VARCHAR NOT NULL, sq_candidato VARCHAR NOT NULL,
    arquivo_origem VARCHAR NOT NULL, url_fonte VARCHAR NOT NULL,
    mime_type VARCHAR NOT NULL, sha256 VARCHAR NOT NULL,
    tamanho_bytes BIGINT NOT NULL, largura INTEGER NOT NULL, altura INTEGER NOT NULL,
    imagem BLOB NOT NULL, coletada_em TIMESTAMP DEFAULT current_timestamp,
    FOREIGN KEY (id_candidato) REFERENCES Candidato(id_candidato)"""

PADRAO_FOTO = re.compile(r'^(?:F)?([A-Z]{2})[_-]?(\d+)(?:_div)?\.(?:jpe?g|png)$', re.IGNORECASE)


def chave_arquivo(nome):
    """Reconhece FMA123_div.jpeg e MA123.jpg, incluindo diretórios no ZIP."""
    base = nome.replace('\\', '/').rsplit('/', 1)[-1]
    match = PADRAO_FOTO.fullmatch(base)
    if not match:
        return None
    return match[1].upper(), str(int(match[2]))


def url_fotos(ano, uf):
    if uf not in UF_CODIGOS or not isinstance(ano, int) or ano < 2006 or ano > 2024 or ano % 2:
        raise ValueError('Fotos: informe UF brasileira e ano eleitoral entre 2006 e 2024')
    return (f'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/fotos/'
            f'foto_cand{ano}_{uf}_div.zip')


def criar_fotos(con):
    con.execute(f'CREATE TABLE IF NOT EXISTS Foto_Candidato ({FOTO_DDL})')


def planejar(con, ufs, ano_minimo=2020, anos=None):
    """Nunca liga por nome, número de urna ou sequencial isolado de outro ano."""
    if not ufs or set(ufs) - UF_CODIGOS.keys():
        raise ValueError('UFs inválidas')
    if ano_minimo < 2006 or ano_minimo > 2024:
        raise ValueError('Ano mínimo deve estar entre 2006 e 2024')
    # Agrupa ANTES de excluir IDs com foto: uma chave ambígua continua ambígua.
    return con.execute('''WITH chaves AS (
        SELECT e.ano, upper(trim(c.uf)) uf,
               cast(try_cast(trim(c.sequencial) AS BIGINT) AS VARCHAR) sq,
               min(c.id_candidato) id_candidato, count(DISTINCT c.id_candidato) identidades
        FROM Candidatura c JOIN Eleicao e USING(id_eleicao)
        WHERE e.ano BETWEEN ? AND 2024 AND e.ano % 2=0
          AND upper(trim(c.uf)) IN (SELECT unnest(?))
          AND (? IS NULL OR e.ano IN (SELECT unnest(?)))
          AND try_cast(trim(c.sequencial) AS BIGINT)>0
        GROUP BY 1,2,3)
        SELECT ano,uf,sq,id_candidato,identidades FROM chaves
        WHERE identidades>1 OR NOT EXISTS (
            SELECT 1 FROM Foto_Candidato f WHERE f.id_candidato=chaves.id_candidato)
        ORDER BY ano DESC, uf, sq''', [ano_minimo, ufs, anos, anos]).fetchall()


def _imagem(dados):
    if len(dados) > 16 * 1024 * 1024:
        raise ValueError('Imagem maior que 16 MiB')
    with Image.open(io.BytesIO(dados)) as img:
        if img.format not in ('JPEG', 'PNG'):
            raise ValueError(f'Formato inesperado: {img.format}')
        mime = 'image/jpeg' if img.format == 'JPEG' else 'image/png'
        largura, altura = img.size
        img.verify()
    return mime, largura, altura


def carregar_zip(con, zip_path, ano, uf, alvos, url):
    """Lê somente fotos esperadas; uma transação por UF/ano, sem extrair caminhos."""
    existentes = {r[0] for r in con.execute('SELECT id_candidato FROM Foto_Candidato').fetchall()}
    pendentes = {sq: candidato for sq, candidato in alvos.items() if candidato not in existentes}
    inseridas, avisos = 0, []
    if not pendentes:
        return inseridas, avisos
    with zipfile.ZipFile(zip_path) as z:
        membros = {}
        for info in z.infolist():
            chave = chave_arquivo(info.filename)
            if chave and chave[0] == uf and chave[1] in pendentes and not info.is_dir():
                membros.setdefault(chave[1], []).append(info)
        con.execute('BEGIN TRANSACTION')
        try:
            lote = []
            for sq, infos in sorted(membros.items()):
                candidato = pendentes[sq]
                if candidato in existentes:
                    continue
                if len(infos) != 1:
                    avisos.append(f'{ano}/{uf}/{sq}: múltiplas imagens no ZIP; vínculo ignorado')
                    continue
                info = infos[0]
                if info.file_size > 16 * 1024 * 1024:
                    avisos.append(f'{ano}/{uf}/{sq}: imagem maior que 16 MiB; ignorada')
                    continue
                dados = z.read(info)
                try:
                    mime, largura, altura = _imagem(dados)
                except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError) as erro:
                    avisos.append(f'{ano}/{uf}/{sq}: imagem inválida; {erro}')
                    continue
                lote.append((candidato, ano, uf, sq, info.filename, url, mime,
                             hashlib.sha256(dados).hexdigest(), len(dados), largura, altura, dados))
                existentes.add(candidato)
                inseridas += 1
                if len(lote) >= 100:
                    _inserir(con, lote)
                    lote.clear()
                    if inseridas % 5000 == 0:
                        print(f'Fotos {ano}/{uf}: {inseridas:,} imagens preparadas para gravação', flush=True)
            if lote:
                _inserir(con, lote)
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
    return inseridas, avisos


def _inserir(con, lote):
    con.executemany('''INSERT INTO Foto_Candidato
        (id_candidato,ano_foto,uf,sq_candidato,arquivo_origem,url_fonte,mime_type,
         sha256,tamanho_bytes,largura,altura,imagem) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', lote)


def executar(con, cache, ufs=None, ano_minimo=2020, anos=None, somente_cache=False):
    """Mais recente primeiro. IDs já fotografados nunca exigem outro arquivo."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    criar_fotos(con)
    ufs = sorted({u.upper() for u in ufs}) if ufs else [r[0] for r in con.execute(
        'SELECT DISTINCT upper(uf) FROM Municipio ORDER BY 1').fetchall()]
    chaves = planejar(con, ufs, ano_minimo, anos)
    ambiguas = [{'ano': a, 'uf': uf, 'sq_candidato': sq, 'identidades': n}
                for a, uf, sq, _id, n in chaves if n > 1]
    grupos = {}
    for ano, uf, sq, candidato, n in chaves:
        if n == 1:
            grupos.setdefault((ano, uf), {})[sq] = candidato
    manifesto = {'ufs': ufs, 'ano_minimo': ano_minimo, 'anos': anos,
                 'chaves_ambiguas': ambiguas, 'arquivos': [], 'avisos': []}
    for (ano, uf), alvos in sorted(grupos.items(), key=lambda item: (-item[0][0], item[0][1])):
        existentes = {r[0] for r in con.execute('SELECT id_candidato FROM Foto_Candidato').fetchall()}
        alvos = {sq: candidato for sq, candidato in alvos.items() if candidato not in existentes}
        if not alvos:
            continue
        url = url_fotos(ano, uf)
        zip_path = cache / 'zips' / f'foto_cand{ano}_{uf}_div.zip'
        registro = {'ano': ano, 'uf': uf, 'url': url, 'candidatos_pendentes': len(alvos)}
        print(f'Fotos {ano}/{uf}: {len(alvos):,} candidatos sem foto', flush=True)
        try:
            if somente_cache:
                if not zip_path.is_file():
                    raise FileNotFoundError('ZIP ausente no cache')
            else:
                baixar(url, zip_path)
            inseridas, avisos = carregar_zip(con, zip_path, ano, uf, alvos, url)
            manifesto['avisos'].extend(avisos)
            registro.update(status='processado', fotos_inseridas=inseridas)
            print(f'Fotos {ano}/{uf}: {inseridas:,} fotos vinculadas', flush=True)
        except (FileNotFoundError, RuntimeError, zipfile.BadZipFile) as erro:
            registro.update(status='indisponivel', erro=str(erro))
            print(f'Aviso: fotos {ano}/{uf} indisponíveis: {erro}', flush=True)
        manifesto['arquivos'].append(registro)
        _manifesto(cache, manifesto)
    manifesto['total_com_foto'] = con.execute('SELECT count(*) FROM Foto_Candidato').fetchone()[0]
    manifesto['candidatos_sem_foto_no_recorte'] = con.execute('''SELECT count(DISTINCT c.id_candidato)
        FROM Candidatura c JOIN Eleicao e USING(id_eleicao)
        WHERE upper(c.uf) IN (SELECT unnest(?)) AND e.ano BETWEEN ? AND 2024
          AND (? IS NULL OR e.ano IN (SELECT unnest(?))) AND NOT EXISTS (
        SELECT 1 FROM Foto_Candidato f WHERE f.id_candidato=c.id_candidato)''',
        [ufs, ano_minimo, anos, anos]).fetchone()[0]
    _manifesto(cache, manifesto)
    return manifesto


def _manifesto(cache, manifesto):
    parcial = cache / 'manifesto_fotos.part'
    parcial.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding='utf-8')
    parcial.replace(cache / 'manifesto_fotos.json')
