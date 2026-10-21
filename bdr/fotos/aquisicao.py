"""Identidade auditável, seleção cronológica e extração limitada das imagens."""
import hashlib
import json
import re
import tempfile
import time
import warnings
import zipfile
from pathlib import Path

from PIL import Image

from .catalogo import UFS, abrir, caminho_seguro
from .fontes import (agora, biografia, hash_texto, linhas_cadastro, membro_seguro,
                     pacote_local, recurso_cadastro, recurso_fotos, sequencial, titulo)

MAX_IMAGEM = 12 * 1024**2
MAX_PIXELS = 24_000_000


def fontes_der(con):
    rows = con.execute('''SELECT table_catalog,table_schema,table_name
        FROM information_schema.tables WHERE table_catalog=current_database()
        AND table_schema IN ('der_bdr','main')''').fetchall()
    for schema in ('der_bdr', 'main'):
        found = {n.lower(): '.'.join('"' + x.replace('"', '""') + '"' for x in (cat, sch, n))
                 for cat, sch, n in rows if sch == schema}
        if {'candidato', 'candidatura', 'eleicao'} <= found.keys():
            return found
    raise ValueError('Banco sem as tabelas Candidato, Candidatura e Eleicao no DER')


def importar_internas(der, cat, ufs=UFS, pessoas=()):
    """Somente SELECT no DER, fetchmany; não interpreta hashes como sequenciais."""
    refs = fontes_der(der)
    cat.execute('DROP TABLE IF EXISTS temp.ativos')
    cat.execute('CREATE TEMP TABLE ativos(id_candidato TEXT PRIMARY KEY)')
    where = 'c.uf IN (' + ','.join('?' for _ in ufs) + ')'
    params = list(ufs)
    if pessoas:
        where += ' AND c.id_candidato IN (' + ','.join('?' for _ in pessoas) + ')'
        params.extend(pessoas)
    sql = f'''SELECT DISTINCT a.id_candidato,a.nome_civil,a.dt_nascimento,a.titulo_eleitoral
        FROM {refs['candidato']} a JOIN {refs['candidatura']} c USING(id_candidato)
        WHERE {where}'''
    cur = der.execute(sql, params)
    total = 0
    while rows := cur.fetchmany(1000):
        cat.executemany('INSERT OR REPLACE INTO pessoas VALUES (?,?,?)',
                        [(i, biografia(n, str(d)), titulo(t)) for i, n, d, t in rows])
        cat.executemany('INSERT OR IGNORE INTO ativos VALUES (?)', [(r[0],) for r in rows])
        total += len(rows)
    sql = f'''SELECT c.id_candidatura,c.id_candidato,e.ano,c.uf,c.sequencial
        FROM {refs['candidatura']} c JOIN {refs['eleicao']} e USING(id_eleicao) WHERE {where}'''
    cur = der.execute(sql, params)
    candidaturas, invalidas = 0, 0
    while rows := cur.fetchmany(1000):
        valores = []
        for i, p, ano, uf, sq in rows:
            sq = sequencial(sq)
            invalidas += sq is None
            valores.append((i, p, ano, uf, sq))
        cat.executemany('INSERT OR REPLACE INTO internas VALUES (?,?,?,?,?)', valores)
        candidaturas += len(rows)
    cat.commit()
    return {'pessoas': total, 'candidaturas': candidaturas, 'sequenciais_invalidos': invalidas}


def importar_fonte(cat, pacote, cache, ufs, atualizar=False):
    dataset = pacote['dataset']
    cat.execute('INSERT OR REPLACE INTO fontes VALUES (?,?,?,?)',
                (dataset, pacote['ano'], json.dumps(pacote, ensure_ascii=False), pacote.get('consultado', agora())))
    cat.commit()
    prontas = {r[0] for r in cat.execute("SELECT uf FROM cobertura WHERE dataset=? AND status='ok'", (dataset,))}
    if set(ufs) <= prontas and not atualizar:
        print(f'  {dataset}: cadastro já validado', flush=True)
        return
    try:
        path = pacote_local(recurso_cadastro(pacote), cache, atualizar)
        cat.execute('BEGIN')
        marcas = ','.join('?' for _ in ufs)
        cat.execute(f'DELETE FROM registros WHERE dataset=? AND uf IN ({marcas})', [dataset, *ufs])
        lote, total, invalidas, vistas = [], 0, 0, set()
        sql = 'INSERT OR IGNORE INTO registros VALUES (' + ','.join('?' for _ in range(14)) + ')'
        for row in linhas_cadastro(path, ufs):
            if row is None:
                invalidas += 1
                continue
            vistas.add(row['uf'])
            chave = hash_texto('|'.join(str(row[k] or '') for k in ('ano','uf','sequencial','eleicao','data')) + '|' + dataset)
            lote.append((chave, dataset, row['ano'], row['data'], row['ordem'], row['uf'], row['sequencial'],
                         row['eleicao'], row['bio'], row['cpf'], row['titulo'], row['id_cpf'],
                         row['origem'], row['linha']))
            # A chave exclui turno: a mesma candidatura não se torna mais recente por ter 2º turno.
            if len(lote) >= 1000:
                cat.executemany(sql, lote)
                total += len(lote)
                lote.clear()
        if lote:
            cat.executemany(sql, lote)
            total += len(lote)
        for uf in ufs:
            status = 'ok' if uf in vistas and not invalidas else 'incompleto'
            cat.execute('INSERT OR REPLACE INTO cobertura VALUES (?,?,?,?,?)',
                        (dataset, uf, status, f'{total} linhas; {invalidas} sequenciais inválidos', agora()))
        cat.commit()
        print(f'  {dataset}: {total} linhas lidas; {invalidas} inválidas', flush=True)
    except Exception as e:
        cat.rollback()
        status = ('pacote_indisponivel' if isinstance(e, FileNotFoundError) else
                  'formato_desconhecido' if isinstance(e, ValueError) else
                  'pacote_invalido' if isinstance(e, zipfile.BadZipFile) else 'erro_temporario')
        for uf in ufs:
            cat.execute('INSERT OR REPLACE INTO cobertura VALUES (?,?,?,?,?)',
                        (dataset, uf, status, type(e).__name__ + ': ' + str(e)[:250], agora()))
        cat.commit()
        print(f'  {dataset}: {status}: {e}', flush=True)


def vincular(cat):
    """Duas etapas: âncora interna; propagação por CPF comprovado ou título+biografia.

    O título sozinho nunca decide. Só o hash CPF|... comprovado com CPF válido da
    fonte permite reconhecer a modalidade CPF da pipeline. Variações biográficas
    com CPF comprovado são auditadas. IDs de outras origens
    continuam intactos e são resolvidos pelas âncoras/título+biografia.
    """
    script = '''
    DROP TABLE IF EXISTS temp.evidencias;
    CREATE TEMP TABLE evidencias(chave TEXT,id_candidato TEXT,metodo TEXT);
    INSERT INTO evidencias
      SELECT r.chave,i.id_candidato,'ANO_UF_SEQUENCIAL_BIO'
      FROM registros r JOIN internas i ON r.ano=i.ano AND r.uf=i.uf AND r.sequencial=i.sequencial
      JOIN pessoas p ON p.id_candidato=i.id_candidato
      WHERE r.bio=p.bio AND (p.titulo IS NULL OR r.titulo IS NULL OR p.titulo=r.titulo);
    INSERT INTO evidencias
      SELECT r.chave,p.id_candidato,'CPF_VALIDO_HASH_PIPELINE'
      FROM registros r JOIN pessoas p ON p.id_candidato=r.id_cpf;
    INSERT OR IGNORE INTO auditoria
      SELECT r.chave,p.id_candidato,'CPF_BIO_DIVERGENTE'
      FROM registros r JOIN pessoas p ON p.id_candidato=r.id_cpf WHERE r.bio IS NOT p.bio;
    INSERT INTO evidencias
      SELECT r.chave,p.id_candidato,'TITULO_BIO_EXATOS'
      FROM registros r JOIN pessoas p ON p.titulo=r.titulo AND p.bio=r.bio;
    INSERT OR IGNORE INTO auditoria
      SELECT r.chave,i.id_candidato,'DIVERGENCIA_CADASTRO_INTERNO'
      FROM registros r JOIN internas i ON r.ano=i.ano AND r.uf=i.uf AND r.sequencial=i.sequencial
      JOIN pessoas p ON p.id_candidato=i.id_candidato
      WHERE r.bio IS NOT p.bio OR (p.titulo IS NOT NULL AND r.titulo IS NOT NULL AND p.titulo<>r.titulo);
    DROP TABLE IF EXISTS temp.ancoras;
    CREATE TEMP TABLE ancoras AS SELECT chave,min(id_candidato) id_candidato
      FROM evidencias GROUP BY chave HAVING count(DISTINCT id_candidato)=1;
    DROP TABLE IF EXISTS temp.tokens;
    CREATE TEMP TABLE tokens AS
      SELECT DISTINCT r.cpf token,r.bio,a.id_candidato,'CPF_VALIDO_ANCORA' metodo
      FROM ancoras a JOIN registros r USING(chave) WHERE r.cpf IS NOT NULL
      UNION SELECT DISTINCT r.titulo,r.bio,a.id_candidato,'TITULO_ANCORA_BIO'
      FROM ancoras a JOIN registros r USING(chave) WHERE r.titulo IS NOT NULL;
    CREATE INDEX temp.tokens_chave ON tokens(token,bio);
    INSERT INTO evidencias
      SELECT r.chave,t.id_candidato,t.metodo FROM registros r JOIN tokens t ON t.token=r.cpf;
    INSERT INTO evidencias
      SELECT r.chave,t.id_candidato,t.metodo FROM registros r JOIN tokens t ON t.token=r.titulo AND t.bio=r.bio;
    INSERT OR IGNORE INTO auditoria SELECT r.chave,t.id_candidato,'CPF_BIO_DIVERGENTE'
      FROM registros r JOIN tokens t ON t.token=r.cpf WHERE r.bio IS NOT t.bio;
    INSERT OR IGNORE INTO auditoria SELECT r.chave,t.id_candidato,'TITULO_BIO_DIVERGENTE'
      FROM registros r JOIN tokens t ON t.token=r.titulo WHERE r.bio IS NOT t.bio;
    CREATE INDEX temp.evidencias_chave ON evidencias(chave,id_candidato);
    DELETE FROM vinculos;
    INSERT INTO vinculos SELECT chave,min(id_candidato),min(metodo)
      FROM evidencias GROUP BY chave HAVING count(DISTINCT id_candidato)=1;
    INSERT OR IGNORE INTO auditoria SELECT chave,id_candidato,'IDENTIDADE_AMBIGUA'
      FROM evidencias WHERE chave IN (
        SELECT chave FROM evidencias GROUP BY chave HAVING count(DISTINCT id_candidato)>1);
    INSERT OR IGNORE INTO auditoria SELECT r.chave,v.id_candidato,'DATA_ELEICAO_AUSENTE'
      FROM registros r JOIN vinculos v USING(chave) WHERE r.data IS NULL;
    '''
    passos = [sql.strip() for sql in script.split(';') if sql.strip()]
    for numero, sql in enumerate(passos, 1):
        cat.execute(sql)
        if numero % 5 == 0 or numero == len(passos):
            print(f'  Identidade: etapa {numero}/{len(passos)} concluída', flush=True)
    bloquear_chaves_ambiguas(cat)
    cat.commit()


def bloquear_chaves_ambiguas(cat):
    """Uma chave de imagem compartilhada entre turnos só pode identificar uma pessoa."""
    cat.execute('DROP TABLE IF EXISTS temp.chaves_foto_ambiguas')
    cat.execute('''CREATE TEMP TABLE chaves_foto_ambiguas AS
        SELECT r.ano,r.uf,r.sequencial FROM registros r JOIN vinculos v USING(chave)
        GROUP BY r.ano,r.uf,r.sequencial HAVING count(DISTINCT v.id_candidato)>1''')
    cat.execute('CREATE INDEX temp.chaves_ambiguas ON chaves_foto_ambiguas(ano,uf,sequencial)')
    cat.execute('''INSERT OR IGNORE INTO auditoria
        SELECT r.chave,v.id_candidato,'CHAVE_FOTO_AMBIGUA' FROM registros r
        JOIN vinculos v USING(chave) JOIN chaves_foto_ambiguas a
        ON a.ano=r.ano AND a.uf=r.uf AND a.sequencial=r.sequencial''')
    cat.execute('''DELETE FROM vinculos WHERE chave IN (SELECT r.chave FROM registros r
        JOIN chaves_foto_ambiguas a ON a.ano=r.ano AND a.uf=r.uf AND a.sequencial=r.sequencial)''')
    quant = cat.execute('SELECT count(*) FROM chaves_foto_ambiguas').fetchone()[0]
    print(f'  Identidade: {quant} chaves de imagem com pessoas distintas bloqueadas', flush=True)


# Reconhecedores independentes e explícitos. Cada ZIP é inspecionado; nomes diferentes
# destes não são adivinhados. A presença de uma extensão conhecida não valida a imagem.
PADROES_FOTO = (
    re.compile(r'(?P<uf>[A-Z]{2})(?P<sq>[0-9]+)_div\.(?P<ext>jpg|jpeg|png)', re.I),
    re.compile(r'F(?P<uf>[A-Z]{2})(?P<sq>[0-9]+)_div\.(?P<ext>jpg|jpeg|png)', re.I),
)


def identificar_foto(nome):
    for padrao in PADROES_FOTO:
        match = padrao.fullmatch(Path(nome).name)
        if match and sequencial(match['sq']):
            return match['uf'].upper(), match['sq'], match['ext'].lower()
    return None


def validar_imagem(path, extensao=None):
    if Path(path).stat().st_size > MAX_IMAGEM:
        raise ValueError('Imagem excede o limite')
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(path) as img:
            formato, (largura, altura) = img.format, img.size
            if formato not in ('JPEG', 'PNG') or largura * altura > MAX_PIXELS or min(largura, altura) < 1:
                raise ValueError('Formato ou dimensões de imagem inválidos')
            if extensao and formato != ('PNG' if extensao == 'png' else 'JPEG'):
                raise ValueError('Extensão incompatível com o conteúdo')
            img.verify()
        with Image.open(path) as img:
            img.load()  # verify() sozinho não detecta todas as imagens truncadas
    digest = hashlib.sha256()
    with open(path, 'rb') as entrada:
        while bloco := entrada.read(1024**2):
            digest.update(bloco)
    return {'mime': 'image/png' if formato == 'PNG' else 'image/jpeg', 'sha256': digest.hexdigest(),
            'tamanho': Path(path).stat().st_size, 'largura': largura, 'altura': altura,
            'mtime_ns': Path(path).stat().st_mtime_ns}


def imagem_existente(cat, raiz, ano, uf, sq):
    row = cat.execute("""SELECT i.*,v.mtime_ns FROM imagens i LEFT JOIN verificacoes v
                      ON v.ano=i.ano AND v.uf=i.uf AND v.sequencial=i.sequencial AND v.sha256=i.sha256
                      WHERE i.ano=? AND i.uf=? AND i.sequencial=? AND i.status='disponivel'""",
                      (ano, uf, sq)).fetchone()
    if row:
        try:
            path = caminho_seguro(raiz, row['caminho'])
            stat = path.stat()
            if stat.st_size != row['tamanho']:
                return False
            if row['mtime_ns'] == stat.st_mtime_ns:
                return True
            digest = hashlib.sha256()
            with path.open('rb') as entrada:
                while bloco := entrada.read(1024**2):
                    digest.update(bloco)
            # Bytes idênticos aos já decodificados/verificados dispensam nova decodificação.
            if digest.hexdigest() == row['sha256']:
                cat.execute('INSERT OR REPLACE INTO verificacoes VALUES (?,?,?,?,?)',
                            (ano, uf, sq, stat.st_mtime_ns, row['sha256']))
                return True
            return False
        except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            pass
    return False


def comitar(con, tentativas=10, espera=0.3):
    for i in range(tentativas):
        try:
            con.commit()
            return
        except Exception as e:
            if 'locked' in str(e).lower() and i < tentativas - 1:
                time.sleep(espera * (i + 1))
            else:
                raise


def gravar_imagem(cat, ano, uf, sq, status, url=None, arquivo=None, detalhe=None, caminho=None, dados=None):
    dados = dados or {}
    for i in range(10):
        try:
            cat.execute('INSERT OR REPLACE INTO imagens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (ano, uf, sq, status, caminho, dados.get('mime'), dados.get('sha256'), dados.get('tamanho'),
                         dados.get('largura'), dados.get('altura'), url, arquivo, agora(), detalhe))
            if status == 'disponivel' and dados.get('mtime_ns') is not None:
                cat.execute('INSERT OR REPLACE INTO verificacoes VALUES (?,?,?,?,?)',
                            (ano, uf, sq, dados['mtime_ns'], dados['sha256']))
            return
        except Exception as e:
            if 'locked' in str(e).lower() and i < 9:
                time.sleep(0.3 * (i + 1))
            else:
                raise


def extrair_pacote(cat, path, raiz, ano, uf, necessarias, url, atualizar=False):
    """Indexa apenas metadados do ZIP e copia uma imagem por vez, nunca extractall()."""
    necessarias = set(necessarias)
    indice, desconhecidas = {}, 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            membro = membro_seguro(info)
            if info.is_dir() or membro.suffix.lower() == '.pdf':
                continue
            chave = identificar_foto(membro.name)
            if not chave:
                desconhecidas += 1
                continue
            estado, sq, extensao = chave
            if estado == uf and sq in necessarias:
                indice.setdefault(sq, []).append((info, extensao))
        for posicao, sq in enumerate(sorted(necessarias), 1):
            if posicao % 100 == 0:
                comitar(cat)  # lotes curtos permitem que os outros pacotes gravem seu progresso
            if posicao % 1000 == 0:
                print(f'    {ano}/{uf}: {posicao}/{len(necessarias)} imagens examinadas', flush=True)
            if not atualizar and imagem_existente(cat, raiz, ano, uf, sq):
                continue
            encontrados = indice.get(sq, [])
            if not encontrados:
                gravar_imagem(cat, ano, uf, sq, 'formato_desconhecido' if desconhecidas else 'nao_encontrada', url,
                              detalhe=f'{desconhecidas} entradas não reconhecidas')
                continue
            if len(encontrados) > 1:
                gravar_imagem(cat, ano, uf, sq, 'associacao_ambigua', url, detalhe='Mais de uma imagem para a chave')
                continue
            info, extensao = encontrados[0]
            tmp = None
            try:
                if info.file_size > MAX_IMAGEM:
                    raise ValueError('Imagem excede o limite descompactado')
                relativo = f'{ano}/{uf}/{sq}.{extensao}'
                destino = caminho_seguro(raiz, relativo)
                destino.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=destino.parent, suffix='.part', delete=False) as saida:
                    tmp = Path(saida.name)
                    with z.open(info) as entrada:
                        total = 0
                        while bloco := entrada.read(64 * 1024):
                            total += len(bloco)
                            if total > MAX_IMAGEM:
                                raise ValueError('Imagem excede o limite descompactado')
                            saida.write(bloco)
                dados = validar_imagem(tmp, extensao)
                tmp.replace(destino)
                gravar_imagem(cat, ano, uf, sq, 'disponivel', url, info.filename, caminho=relativo, dados=dados)
            except (OSError, ValueError, zipfile.BadZipFile, Image.DecompressionBombError,
                    Image.DecompressionBombWarning) as e:
                gravar_imagem(cat, ano, uf, sq, 'imagem_invalida', url, info.filename, str(e)[:250])
            finally:
                if tmp:
                    tmp.unlink(missing_ok=True)
        comitar(cat)


def preparar_selecao(cat):
    objeto = cat.execute("SELECT type FROM sqlite_temp_master WHERE name='opcoes_foto'").fetchone()
    if objeto:
        cat.execute('DROP ' + ('VIEW' if objeto[0] == 'view' else 'TABLE') + ' temp.opcoes_foto')
    cat.executescript('''
    CREATE TEMP TABLE opcoes_foto AS
      SELECT v.id_candidato,r.*,i.status imagem_status FROM vinculos v JOIN registros r USING(chave)
      LEFT JOIN imagens i ON i.ano=r.ano AND i.uf=r.uf AND i.sequencial=r.sequencial;
    CREATE INDEX temp.opcoes_pessoa ON opcoes_foto(id_candidato,ordem,imagem_status);
    CREATE INDEX temp.opcoes_chave ON opcoes_foto(chave);
    CREATE INDEX temp.opcoes_pacote ON opcoes_foto(ano,uf);
    ''')


def revalidar_imagens(cat, raiz):
    """Antes de retomar, arquivos ausentes/alterados voltam à fila de aquisição."""
    ultimo = (0, '', '')
    examinadas = 0
    while True:
        rows = cat.execute('''SELECT ano,uf,sequencial FROM imagens WHERE status='disponivel'
            AND (ano,uf,sequencial)>(?,?,?) ORDER BY ano,uf,sequencial LIMIT 500''', ultimo).fetchall()
        if not rows:
            break
        for row in rows:
            if not imagem_existente(cat, raiz, *row):
                cat.execute("UPDATE imagens SET status='imagem_invalida',detalhe='Falhou a verificação local na retomada' WHERE ano=? AND uf=? AND sequencial=?", tuple(row))
        cat.commit()
        examinadas += len(rows)
        if examinadas % 5000 == 0:
            print(f'  Retomada: {examinadas} arquivos locais conferidos', flush=True)
        ultimo = tuple(rows[-1])


def necessidades(cat, ano, uf, atualizar=False):
    # Uma foto disponível mais recente dispensa fotos históricas dessa pessoa.
    ativos = (' AND o.id_candidato IN (SELECT id_candidato FROM ativos)'
              if cat.execute("SELECT 1 FROM sqlite_temp_master WHERE name='ativos'").fetchone() else '')
    return [r[0] for r in cat.execute('''SELECT DISTINCT o.sequencial FROM opcoes_foto o
       WHERE o.ano=? AND o.uf=? AND (? OR coalesce(o.imagem_status,'')<>'disponivel')
       AND NOT EXISTS (SELECT 1 FROM opcoes_foto f WHERE f.id_candidato=o.id_candidato
          AND f.imagem_status='disponivel' AND f.ordem>o.ordem)''' + ativos, (ano, uf, int(atualizar)))]


def adquirir_pacote(banco, raiz, cache, pacote, uf, sqs, atualizar=False):
    cat = abrir(banco)
    ano, url = pacote['ano'], None
    cobertura = pacote.get('dataset', f'candidatos-{ano}') + '::fotos'
    try:
        url = recurso_fotos(pacote, uf)
        path = pacote_local(url, cache, atualizar)
        extrair_pacote(cat, path, raiz, ano, uf, sqs, url, atualizar)
        for i in range(10):
            try:
                cat.execute('INSERT OR REPLACE INTO cobertura VALUES (?,?,?,?,?)',
                            (cobertura, uf, 'ok', url, agora()))
                comitar(cat)
                break
            except Exception as err:
                if 'locked' in str(err).lower() and i < 9:
                    time.sleep(0.3 * (i + 1))
                else:
                    raise
        print(f'  fotos {ano}/{uf}: {len(sqs)} chaves processadas', flush=True)
    except Exception as e:
        status = ('pacote_indisponivel' if isinstance(e, FileNotFoundError) else
                  'formato_desconhecido' if isinstance(e, ValueError) else
                  'pacote_invalido' if isinstance(e, zipfile.BadZipFile) else 'erro_temporario')
        for sq in sqs:
            # Uma atualização com falha não destrói um arquivo válido já adquirido.
            if not imagem_existente(cat, raiz, ano, uf, sq):
                gravar_imagem(cat, ano, uf, sq, status, url, detalhe=type(e).__name__ + ': ' + str(e)[:250])
        for i in range(10):
            try:
                cat.execute('INSERT OR REPLACE INTO cobertura VALUES (?,?,?,?,?)',
                            (cobertura, uf, status, (url or '') + ' | ' + type(e).__name__ + ': ' + str(e)[:250], agora()))
                comitar(cat)
                break
            except Exception as err:
                if 'locked' in str(err).lower() and i < 9:
                    time.sleep(0.3 * (i + 1))
                else:
                    break
        print(f'  fotos {ano}/{uf}: {status}: {e}', flush=True)
    finally:
        cat.close()


def selecionar_principais(cat, completa=False):
    preparar_selecao(cat)
    cat.executescript('''
    DROP TABLE IF EXISTS temp.ultimas;
    CREATE TEMP TABLE ultimas AS SELECT id_candidato,max(ordem) ordem FROM opcoes_foto GROUP BY id_candidato;
    CREATE INDEX temp.ultimas_id ON ultimas(id_candidato);
    DROP TABLE IF EXISTS temp.ultima_unica;
    CREATE TEMP TABLE ultima_unica AS
      SELECT o.id_candidato,min(o.chave) chave,
       count(DISTINCT cast(o.ano AS TEXT)||'|'||o.uf||'|'||o.sequencial) quant
      FROM opcoes_foto o JOIN ultimas u ON u.id_candidato=o.id_candidato AND u.ordem=o.ordem
      GROUP BY o.id_candidato;
    DROP TABLE IF EXISTS temp.fotos_validas;
    CREATE TEMP TABLE fotos_validas AS SELECT *,row_number() OVER (
      PARTITION BY id_candidato ORDER BY ordem DESC,chave) posicao FROM opcoes_foto WHERE imagem_status='disponivel';
    ''')
    # Substitui a seleção em uma transação: leitores continuam vendo a seleção anterior.
    cat.execute('DELETE FROM principais')
    cat.execute('''INSERT INTO principais
      SELECT p.id_candidato,u.chave,CASE WHEN u.quant=1 THEN f.chave END,
       CASE WHEN u.quant>1 THEN 'associacao_ambigua' WHEN f.chave IS NOT NULL THEN 'disponivel'
            WHEN u.chave IS NULL AND EXISTS (SELECT 1 FROM auditoria a WHERE a.id_candidato=p.id_candidato
              AND a.motivo IN ('IDENTIDADE_AMBIGUA','CHAVE_FOTO_AMBIGUA')) THEN 'associacao_ambigua'
            WHEN u.chave IS NULL AND EXISTS (SELECT 1 FROM auditoria a WHERE a.id_candidato=p.id_candidato)
              THEN 'associacao_pendente'
            ELSE coalesce(o.imagem_status,'nao_processada') END,
       CASE WHEN f.ordem<o.ordem THEN 1 ELSE 0 END,?,?
      FROM pessoas p LEFT JOIN ultima_unica u ON u.id_candidato=p.id_candidato
      LEFT JOIN opcoes_foto o ON o.chave=u.chave
      LEFT JOIN fotos_validas f ON f.id_candidato=p.id_candidato AND f.posicao=1''', (int(completa), agora()))
    cat.commit()


def relatorio(cat):
    total = cat.execute('SELECT count(*) FROM pessoas').fetchone()[0]
    disponiveis = cat.execute("SELECT count(*) FROM principais WHERE foto_status='disponivel'").fetchone()[0]
    return {'pessoas_processadas': total, 'fotos_disponiveis': disponiveis,
            'arquivos_fisicos': cat.execute("SELECT count(*) FROM imagens WHERE status='disponivel'").fetchone()[0],
            'fotos_por_ano': dict(cat.execute('''SELECT r.ano,count(*) FROM principais p JOIN registros r ON r.chave=p.foto_chave
                WHERE p.foto_status='disponivel' GROUP BY r.ano ORDER BY r.ano''').fetchall()),
            'foto_anterior': cat.execute("SELECT count(*) FROM principais WHERE foto_anterior=1 AND foto_status='disponivel'").fetchone()[0],
            'estados': dict(cat.execute('SELECT foto_status,count(*) FROM principais GROUP BY foto_status').fetchall()),
            'auditoria': dict(cat.execute('SELECT motivo,count(*) FROM auditoria GROUP BY motivo').fetchall()),
            'aquisicao_imagens': dict(cat.execute('SELECT status,count(*) FROM imagens GROUP BY status').fetchall()),
            'pessoas_sem_vinculo': cat.execute('''SELECT count(*) FROM pessoas p WHERE NOT EXISTS
                (SELECT 1 FROM vinculos v WHERE v.id_candidato=p.id_candidato)''').fetchone()[0],
            'pessoas_com_ambiguidades': cat.execute("SELECT count(DISTINCT id_candidato) FROM auditoria WHERE motivo IN ('IDENTIDADE_AMBIGUA','CHAVE_FOTO_AMBIGUA')").fetchone()[0],
            'pessoas_com_divergencias': cat.execute("SELECT count(DISTINCT id_candidato) FROM auditoria WHERE motivo LIKE '%DIVERGEN%'").fetchone()[0],
            'cobertura': [dict(r) for r in cat.execute('SELECT * FROM cobertura ORDER BY dataset DESC,uf')],
            'busca_completa': bool(total and cat.execute('SELECT min(cobertura_completa) FROM principais').fetchone()[0]),
            'limite': 'Última candidatura identificada em CE, MA, MS, RJ, RN e RS; não é uma busca nacional.'}
