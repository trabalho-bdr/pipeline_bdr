"""Deduplicação de fotografias de candidatos com consolidação da foto mais recente.

Regras e invariantes:
- Mantém apenas a foto mais recente válida de cada pessoa no acervo completo.
- Destino padronizado: dados_bdr/fotos selecionadas/<ano>/<nome civil>_<sequencial>.<extensao>
- Exclui imagens excedentes na aplicação definitiva (--aplicar).
- Modo simulação por padrão (--simular / sem --aplicar).
- Sanitização estrita para sistema de arquivos Windows (proibidos, reservados, limites).
- Idempotência, retomabilidade, backup consistente WAL do SQLite e locks de concorrência.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import duckdb
from PIL import Image

from .catalogo import RAIZ, abrir, caminho_seguro, configuracao
from .fontes import agora, normalizar, sequencial

MAX_IMAGEM = 12 * 1024**2
MAX_PIXELS = 24_000_000

NOMES_RESERVADOS_WINDOWS = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10))
}


def sanitizar_nome_arquivo(nome_civil, sequencial_cand, extensao):
    """Sanitiza o nome do arquivo para compatibilidade estrita com Windows NTFS.

    - Remove apenas caracteres proibidos: < > : \" / \\ | ? * e controles ASCII (0-31).
    - Preserva acentuação e caracteres válidos.
    - Remove espaços e pontos nas extremidades; colapsa múltiplos espaços.
    - Trata nomes reservados do Windows (CON, PRN, AUX, NUL, COM1..9, LPT1..9).
    - Trata limites de comprimento de nome de arquivo (<= 240 caracteres).
    - Assegura extensão correta com ponto inicial.
    """
    nome_limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', str(nome_civil or ''))
    nome_limpo = ' '.join(nome_limpo.split()).strip('. ')
    if not nome_limpo:
        nome_limpo = 'CANDIDATO'

    sq_str = str(sequencial_cand or '').strip()
    sufixo = f"_{sq_str}" if sq_str else ''

    stem = f"{nome_limpo}{sufixo}".strip('. ')

    # Proteção de nomes reservados Windows
    if stem.upper() in NOMES_RESERVADOS_WINDOWS:
        stem = f"_{stem}"

    ext = extensao.strip().lower()
    if not ext.startswith('.'):
        ext = '.' + ext

    # Limite seguro para o stem dentro dos limites de 255 bytes/chars de NTFS
    max_stem = 240 - len(ext)
    if len(stem) > max_stem:
        max_nome = max(10, max_stem - len(sufixo))
        nome_limpo = nome_limpo[:max_nome].strip('. ')
        stem = f"{nome_limpo}{sufixo}".strip('. ')

    return f"{stem}{ext}"


def validar_arquivo_imagem(path, extensao_esperada=None, sha_esperado=None, tamanho_esperado=None, rapido=False, mtime_verificado=None):
    """Valida a decodificação completa, dimensões, integridade dos bytes e extensão real."""
    path = Path(path)
    if not path.is_file():
        return {'valido': False, 'motivo': 'Arquivo ausente'}

    try:
        stat = path.stat()
    except OSError as e:
        return {'valido': False, 'motivo': f'Erro ao ler stat: {e}'}

    if stat.st_size <= 0:
        return {'valido': False, 'motivo': 'Arquivo vazio (0 bytes)'}
    if stat.st_size > MAX_IMAGEM:
        return {'valido': False, 'motivo': 'Arquivo excede limite máximo de 12MB'}

    if tamanho_esperado is not None and stat.st_size != tamanho_esperado:
        return {'valido': False, 'motivo': f'Tamanho divergente (disco: {stat.st_size}, esperado: {tamanho_esperado})'}

    # Se a verificação rápida estiver ativa e o mtime coincidir com o verificado anteriormente no catálogo
    if rapido and mtime_verificado and stat.st_mtime_ns == mtime_verificado and sha_esperado:
        ext = path.suffix.lower()
        extensao_real = '.png' if ext == '.png' else '.jpg'
        mime = 'image/png' if extensao_real == '.png' else 'image/jpeg'
        return {
            'valido': True,
            'mime': mime,
            'extensao': extensao_real,
            'sha256': sha_esperado,
            'tamanho': stat.st_size,
            'mtime_ns': stat.st_mtime_ns,
        }

    # Hash SHA-256
    digest = hashlib.sha256()
    try:
        with path.open('rb') as f:
            while bloco := f.read(1024 * 1024):
                digest.update(bloco)
    except OSError as e:
        return {'valido': False, 'motivo': f'Erro de leitura de bytes: {e}'}

    sha = digest.hexdigest()
    if sha_esperado is not None and sha.lower() != sha_esperado.lower():
        return {'valido': False, 'motivo': f'SHA-256 divergente (disco: {sha}, esperado: {sha_esperado})'}

    # Verificação da decodificação com Pillow
    try:
        with Image.open(path) as img:
            formato = img.format
            largura, altura = img.size
            if formato not in ('JPEG', 'PNG') or largura * altura > MAX_PIXELS or min(largura, altura) < 1:
                return {'valido': False, 'motivo': f'Formato ({formato}) ou dimensões inválidas ({largura}x{altura})'}
            img.verify()

        with Image.open(path) as img:
            img.load()
    except Exception as e:
        return {'valido': False, 'motivo': f'Falha na decodificação de imagem: {e}'}

    mime = 'image/png' if formato == 'PNG' else 'image/jpeg'
    extensao_real = '.png' if formato == 'PNG' else '.jpg'

    if extensao_esperada and extensao_esperada.lower().replace('.', '') != extensao_real.replace('.', ''):
        return {'valido': False, 'motivo': f'Extensão esperada {extensao_esperada} incompatível com conteúdo real {extensao_real}'}

    return {
        'valido': True,
        'mime': mime,
        'extensao': extensao_real,
        'sha256': sha,
        'tamanho': stat.st_size,
        'largura': largura,
        'altura': altura,
        'mtime_ns': stat.st_mtime_ns,
    }


def fazer_backup_sqlite(banco_origem, banco_destino=None):
    """Realiza backup transacional consistente do SQLite considerando páginas WAL."""
    banco_origem = Path(banco_origem).resolve()
    if not banco_origem.is_file():
        raise FileNotFoundError(f"Catálogo SQLite não encontrado: {banco_origem}")

    if banco_destino is None:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        banco_destino = banco_origem.with_name(f"{banco_origem.stem}.backup_dedup_{ts}.sqlite3")
    else:
        banco_destino = Path(banco_destino).resolve()

    banco_destino.parent.mkdir(parents=True, exist_ok=True)

    con_origem = sqlite3.connect(f"file:{banco_origem.as_posix()}?mode=ro", uri=True, timeout=120)
    try:
        con_destino = sqlite3.connect(banco_destino)
        try:
            con_origem.backup(con_destino)
        finally:
            con_destino.close()
    finally:
        con_origem.close()

    return banco_destino


def obter_equivalencias_der(der_con):
    """Localiza pares de id_candidato com identidade comprovada (mesmo título, nascimento e nome civil)."""
    try:
        rows = der_con.execute("""
            SELECT c1.id_candidato, c2.id_candidato
            FROM Candidato c1
            JOIN Candidato c2 ON c1.titulo_eleitoral = c2.titulo_eleitoral
              AND c1.dt_nascimento = c2.dt_nascimento
              AND upper(trim(c1.nome_civil)) = upper(trim(c2.nome_civil))
              AND c1.id_candidato < c2.id_candidato
            WHERE c1.titulo_eleitoral IS NOT NULL AND c1.titulo_eleitoral != ''
        """).fetchall()
    except Exception:
        return {}

    # Disjoint Set Union (DSU) para agrupar IDs equivalentes
    pai = {}

    def achar(x):
        if pai.setdefault(x, x) != x:
            pai[x] = achar(pai[x])
        return pai[x]

    def uniao(x, y):
        rx, ry = achar(x), achar(y)
        if rx != ry:
            # Manter o menor lexicograficamente como canônico
            if rx < ry:
                pai[ry] = rx
            else:
                pai[rx] = ry

    for id1, id2 in rows:
        uniao(id1, id2)

    mapa_canonico = {}
    for x in list(pai.keys()):
        mapa_canonico[x] = achar(x)

    return mapa_canonico


def carregar_nomes_civis(der_con_ou_path, ids=None):
    """Recupera nome civil a partir do DER eleitoral (DuckDB) em modo somente leitura."""
    nomes = {}
    if not der_con_ou_path:
        return nomes

    close_der = False
    if isinstance(der_con_ou_path, (str, Path)):
        caminho = str(der_con_ou_path)
        der_con = duckdb.connect(caminho, read_only=not caminho.startswith('md:'))
        close_der = True
    else:
        der_con = der_con_ou_path

    try:
        if ids:
            lote_ids = list(dict.fromkeys(ids))
            for i in range(0, len(lote_ids), 2000):
                sub = lote_ids[i:i + 2000]
                placeholders = ','.join(['?'] * len(sub))
                sql = f"SELECT id_candidato, nome_civil FROM Candidato WHERE id_candidato IN ({placeholders}) AND nome_civil IS NOT NULL"
                for cid, nome in der_con.execute(sql, sub).fetchall():
                    if nome and str(nome).strip():
                        nomes[cid] = str(nome).strip()
        else:
            sql = "SELECT id_candidato, nome_civil FROM Candidato WHERE nome_civil IS NOT NULL AND nome_civil != ''"
            for cid, nome in der_con.execute(sql).fetchall():
                if nome and str(nome).strip():
                    nomes[cid] = str(nome).strip()
    finally:
        if close_der:
            der_con.close()

    return nomes


def obter_banco_der_padrao():
    env_banco = os.environ.get('BDR_BANCO')
    if env_banco:
        return env_banco if env_banco.startswith('md:') or env_banco == ':memory:' else str((RAIZ / env_banco).resolve())
    for caminho in (
        'dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb',
        'dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb',
    ):
        arq = RAIZ / caminho
        if arq.is_file():
            return str(arq)
    return None


def excluir_arquivo_seguro(caminho, raiz_permitida):
    """Exclui arquivo apenas se estiver estritamente dentro da raiz permitida de imagens."""
    p = Path(caminho).resolve()
    raiz = Path(raiz_permitida).resolve()
    if not p.is_relative_to(raiz):
        raise ValueError(f"Tentativa de exclusão fora do diretório permitido: {p}")
    if p.is_symlink():
        raise ValueError(f"Tentativa de exclusão de link simbólico: {p}")
    if not p.is_file():
        return False
    # Proteções adicionais contra tipos de arquivo proibidos
    ext = p.suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png'):
        raise ValueError(f"Recusado excluir arquivo que não é imagem: {p}")
    if p.name.lower().endswith(('.sqlite3', '.duckdb', '.zip', '.json', '.txt', '.log')):
        raise ValueError(f"Arquivo de sistema protegido contra exclusão: {p}")
    p.unlink()
    return True


class AuditoriaCatalogoDisco:
    """Confronta catálogo SQLite com o sistema de arquivos local."""

    def __init__(self, cat, raiz_imagens):
        self.cat = cat
        self.raiz_imagens = Path(raiz_imagens).resolve()

    def auditar(self, ids_escopo=None):
        """Identifica arquivos ausentes, corrompidos e associações contraditórias."""
        clausula_escopo = ''
        params = []
        if ids_escopo:
            placeholders = ','.join(['?'] * len(ids_escopo))
            clausula_escopo = f" AND v.id_candidato IN ({placeholders})"
            params = list(ids_escopo)

        sql = f"""
            SELECT DISTINCT i.ano, i.uf, i.sequencial, i.status, i.caminho, i.mime, i.sha256, i.tamanho
            FROM imagens i
            JOIN registros r ON r.ano=i.ano AND r.uf=i.uf AND r.sequencial=i.sequencial
            JOIN vinculos v ON v.chave=r.chave
            WHERE i.status = 'disponivel'{clausula_escopo}
        """
        rows = self.cat.execute(sql, params).fetchall()

        ausentes = []
        corrompidos = []
        validos = 0

        for r in rows:
            ano, uf, sq, st, cam_rel, mime, sha, tam = (
                r['ano'], r['uf'], r['sequencial'], r['status'], r['caminho'], r['mime'], r['sha256'], r['tamanho']
            )
            try:
                caminho_abs = caminho_seguro(self.raiz_imagens, cam_rel)
                res = validar_arquivo_imagem(caminho_abs, sha_esperado=sha, tamanho_esperado=tam)
                if not res['valido']:
                    if 'ausente' in res['motivo'].lower():
                        ausentes.append({'ano': ano, 'uf': uf, 'sequencial': sq, 'caminho': cam_rel, 'motivo': res['motivo']})
                    else:
                        corrompidos.append({'ano': ano, 'uf': uf, 'sequencial': sq, 'caminho': cam_rel, 'motivo': res['motivo']})
                else:
                    validos += 1
            except Exception as e:
                ausentes.append({'ano': ano, 'uf': uf, 'sequencial': sq, 'caminho': cam_rel, 'motivo': str(e)})

        return {
            'total_verificados': len(rows),
            'validos': validos,
            'ausentes': ausentes,
            'corrompidos': corrompidos,
        }


def construir_plano(cat, der_path_ou_con, raiz_origem, raiz_destino, ids_filtro=None, limite=None):
    """Constrói o plano completo de deduplicação sem realizar alterações."""
    raiz_origem = Path(raiz_origem).resolve()
    raiz_destino = Path(raiz_destino).resolve()

    # 1. Carregar equivalências de identidade comprovadas
    mapa_equivalencias = {}
    der_con = None
    close_der = False
    if der_path_ou_con:
        if isinstance(der_path_ou_con, (str, Path)):
            der_con = duckdb.connect(str(der_path_ou_con), read_only=not str(der_path_ou_con).startswith('md:'))
            close_der = True
        else:
            der_con = der_path_ou_con
        mapa_equivalencias = obter_equivalencias_der(der_con)

    # 2. Pessoas e ambiguidades da auditoria do catálogo
    ambiguidades_auditoria = set(r[0] for r in cat.execute(
        "SELECT DISTINCT id_candidato FROM auditoria WHERE motivo IN ('IDENTIDADE_AMBIGUA','CHAVE_FOTO_AMBIGUA')"
    ).fetchall())

    # 3. Carregar candidaturas com fotos vinculadas
    where_filtro = ''
    params_filtro = []
    if ids_filtro:
        placeholders = ','.join(['?'] * len(ids_filtro))
        where_filtro = f" WHERE v.id_candidato IN ({placeholders})"
        params_filtro = list(ids_filtro)

    sql = f"""
        SELECT v.id_candidato, r.chave, r.ano, r.data, r.uf, r.sequencial,
               i.status imagem_status, i.caminho, i.mime, i.sha256, i.tamanho,
               ver.mtime_ns ver_mtime_ns
        FROM vinculos v
        JOIN registros r ON r.chave = v.chave
        LEFT JOIN imagens i ON i.ano = r.ano AND i.uf = r.uf AND i.sequencial = r.sequencial
        LEFT JOIN verificacoes ver ON ver.ano = r.ano AND ver.uf = r.uf AND ver.sequencial = r.sequencial AND ver.sha256 = i.sha256
        {where_filtro}
    """
    rows = cat.execute(sql, params_filtro).fetchall()

    # Agrupar registros por identidade canônica da pessoa
    pessoas_dados = defaultdict(lambda: {
        'ids_associados': set(),
        'candidaturas': [],
    })

    todos_ids_candidato = set()
    for r in rows:
        cid = r['id_candidato']
        todos_ids_candidato.add(cid)
        canonico = mapa_equivalencias.get(cid, cid)
        pessoas_dados[canonico]['ids_associados'].add(cid)
        pessoas_dados[canonico]['candidaturas'].append(dict(r))

    # Também incluir pessoas do catálogo que não tinham vínculos para registro completo
    if ids_filtro:
        for cid in ids_filtro:
            canonico = mapa_equivalencias.get(cid, cid)
            pessoas_dados[canonico]['ids_associados'].add(cid)
            todos_ids_candidato.add(cid)

    # 4. Obtenção do nome civil via DER
    nomes_civis = carregar_nomes_civis(der_con, todos_ids_candidato)
    if close_der and der_con:
        der_con.close()

    plano_pessoas = []
    caminhos_destino_map = defaultdict(list)

    chaves_processadas = 0

    for canonico, dados in pessoas_dados.items():
        if limite and chaves_processadas >= limite:
            break
        chaves_processadas += 1
        if chaves_processadas % 25000 == 0:
            print(f"  Construindo plano: {chaves_processadas:,}/{len(pessoas_dados):,} pessoas analisadas...", flush=True)

        ids_associados = sorted(list(dados['ids_associados']))

        # Buscar nome civil associado (tentar pelos IDs equivalentes)
        nome_civil = None
        for cid in ids_associados:
            if cid in nomes_civis:
                nome_civil = nomes_civis[cid]
                break

        # Verificar se pessoa tem pendência de ambiguidade
        tem_ambiguidade = any(cid in ambiguidades_auditoria for cid in ids_associados)

        candidaturas = dados['candidaturas']

        # Se não há candidaturas ou nome civil
        if not nome_civil:
            # Preservar todos os arquivos dessa pessoa
            arquivos_preservar = [c for c in candidaturas if c.get('imagem_status') == 'disponivel' and c.get('caminho')]
            plano_pessoas.append({
                'id_pessoa': canonico,
                'ids_associados': ids_associados,
                'nome_civil': None,
                'status': 'pendente_sem_nome',
                'motivo_pendencia': 'Nome civil não encontrado no cadastro eleitoral',
                'foto_selecionada': None,
                'excedentes': [],
                'preservados': arquivos_preservar,
            })
            continue

        if tem_ambiguidade:
            arquivos_preservar = [c for c in candidaturas if c.get('imagem_status') == 'disponivel' and c.get('caminho')]
            plano_pessoas.append({
                'id_pessoa': canonico,
                'ids_associados': ids_associados,
                'nome_civil': nome_civil,
                'status': 'pendente_ambiguidade',
                'motivo_pendencia': 'Associação ambígua auditada no catálogo eleitoral',
                'foto_selecionada': None,
                'excedentes': [],
                'preservados': arquivos_preservar,
            })
            continue

        # Filtrar candidaturas que possuem imagem física potencialmente disponível
        candidaturas_com_imagem = [c for c in candidaturas if c.get('imagem_status') == 'disponivel' and c.get('caminho')]

        if not candidaturas_com_imagem:
            plano_pessoas.append({
                'id_pessoa': canonico,
                'ids_associados': ids_associados,
                'nome_civil': nome_civil,
                'status': 'sem_foto_valida',
                'motivo_pendencia': 'Nenhuma fotografia disponível associada à pessoa',
                'foto_selecionada': None,
                'excedentes': [],
                'preservados': [],
            })
            continue

        # Ordenar candidaturas por data da eleição decrescente (ou ano-01-01 se data ausente), depois ano
        def chave_ordem(c):
            data = c.get('data') or f"{c.get('ano')}-01-01"
            return (data, c.get('ano', 0), c.get('sequencial', ''))

        candidaturas_ordenadas = sorted(candidaturas_com_imagem, key=chave_ordem, reverse=True)

        # Detectar empate de data na candidatura mais recente entre imagens distintas
        candidatura_topo = candidaturas_ordenadas[0]
        data_topo = candidatura_topo.get('data') or f"{candidatura_topo.get('ano')}-01-01"

        empatadas = [
            c for c in candidaturas_ordenadas
            if (c.get('data') or f"{c.get('ano')}-01-01") == data_topo
        ]

        # Verificar se as empatadas apontam para arquivos com hashes ou caminhos distintos
        hashes_empatados = set(c.get('sha256') for c in empatadas if c.get('sha256'))
        if len(hashes_empatados) > 1:
            # Empate sem critério para desempate seguro -> Preservar
            plano_pessoas.append({
                'id_pessoa': canonico,
                'ids_associados': ids_associados,
                'nome_civil': nome_civil,
                'status': 'pendente_empate_data',
                'motivo_pendencia': f'Empate de imagens distintas na data mais recente ({data_topo})',
                'foto_selecionada': None,
                'excedentes': [],
                'preservados': candidaturas_com_imagem,
            })
            continue

        # Selecionar a foto mais recente que esteja de fato válida no disco
        selecionada = None
        foto_anterior_utilizada = False
        motivo_escolha = 'Fotografia mais recente válida'
        candidaturas_invalidas_mais_recentes = []

        for idx, cand in enumerate(candidaturas_ordenadas):
            cam_rel = cand.get('caminho')
            caminho_completo = None
            origem_utilizada = raiz_origem
            for r_cand in (raiz_origem, raiz_destino):
                try:
                    p = caminho_seguro(r_cand, cam_rel)
                    if p.is_file():
                        caminho_completo = p
                        origem_utilizada = r_cand
                        break
                except Exception:
                    pass

            validacao = (
                validar_arquivo_imagem(
                    caminho_completo,
                    sha_esperado=cand.get('sha256'),
                    tamanho_esperado=cand.get('tamanho'),
                    rapido=True,
                    mtime_verificado=cand.get('ver_mtime_ns'),
                )
                if caminho_completo else {'valido': False, 'motivo': 'Caminho inválido'}
            )

            if validacao['valido']:
                selecionada = cand
                selecionada_val = validacao
                if idx > 0:
                    foto_anterior_utilizada = True
                    motivo_escolha = f"Foto anterior ({cand['ano']}) selecionada porque a mais recente falhou na validação local"
                break
            else:
                candidaturas_invalidas_mais_recentes.append({
                    'ano': cand.get('ano'),
                    'sequencial': cand.get('sequencial'),
                    'caminho': cam_rel,
                    'motivo': validacao['motivo'],
                })

        if not selecionada:
            plano_pessoas.append({
                'id_pessoa': canonico,
                'ids_associados': ids_associados,
                'nome_civil': nome_civil,
                'status': 'pendente_arquivo_invalido',
                'motivo_pendencia': 'Nenhuma das fotos vinculadas pôde ser validada fisicamente no disco',
                'foto_selecionada': None,
                'excedentes': [],
                'preservados': candidaturas_com_imagem,
                'erros_validacao': candidaturas_invalidas_mais_recentes,
            })
            continue

        # Determinar caminho final sanitizado
        extensao = selecionada_val['extensao']
        nome_arquivo = sanitizar_nome_arquivo(nome_civil, selecionada['sequencial'], extensao)
        caminho_relativo_final = f"{selecionada['ano']}/{nome_arquivo}"
        caminho_final_abs = raiz_destino / caminho_relativo_final

        # Identificar imagens excedentes daquela pessoa
        # São candidaturas com imagens distintas da selecionada
        excedentes = []
        for cand in candidaturas_com_imagem:
            # Não é excedente se for exatamente o mesmo arquivo físico selecionado
            if cand['ano'] == selecionada['ano'] and cand['uf'] == selecionada['uf'] and cand['sequencial'] == selecionada['sequencial']:
                continue
            excedentes.append({
                'ano': cand['ano'],
                'uf': cand['uf'],
                'sequencial': cand['sequencial'],
                'caminho_relativo': cand['caminho'],
                'sha256': cand.get('sha256'),
                'tamanho': cand.get('tamanho'),
            })

        item_plano = {
            'id_pessoa': canonico,
            'ids_associados': ids_associados,
            'nome_civil': nome_civil,
            'status': 'consolidar',
            'foto_anterior': foto_anterior_utilizada,
            'motivo_escolha': motivo_escolha,
            'foto_selecionada': {
                'ano': selecionada['ano'],
                'uf': selecionada['uf'],
                'sequencial': selecionada['sequencial'],
                'data': selecionada.get('data'),
                'caminho_origem_relativo': selecionada['caminho'],
                'caminho_destino_relativo': caminho_relativo_final,
                'caminho_destino_absoluto': str(caminho_final_abs),
                'sha256': selecionada_val['sha256'],
                'tamanho': selecionada_val['tamanho'],
                'mime': selecionada_val['mime'],
            },
            'excedentes': excedentes,
            'preservados': [],
        }

        plano_pessoas.append(item_plano)
        caminhos_destino_map[caminho_relativo_final].append(item_plano)

    # 5. Detecção de colisões de caminhos finais entre pessoas distintas
    colisoes_detectadas = 0
    for cam_rel, itens in caminhos_destino_map.items():
        if len(itens) > 1:
            colisoes_detectadas += 1
            for item in itens:
                item['status'] = 'pendente_colisao_destino'
                item['motivo_pendencia'] = f'Colisão de caminho final ({cam_rel}) com outra pessoa'
                if item.get('foto_selecionada'):
                    item['preservados'].append(item['foto_selecionada'])
                if item.get('excedentes'):
                    item['preservados'].extend(item['excedentes'])
                item['foto_selecionada'] = None
                item['excedentes'] = []

    resumo = {
        'total_pessoas_analisadas': len(plano_pessoas),
        'consolidadas': sum(1 for p in plano_pessoas if p['status'] == 'consolidar'),
        'foto_anterior_utilizada': sum(1 for p in plano_pessoas if p.get('foto_anterior')),
        'sem_foto_valida': sum(1 for p in plano_pessoas if p['status'] == 'sem_foto_valida'),
        'pendencias_ambiguidade': sum(1 for p in plano_pessoas if p['status'] == 'pendente_ambiguidade'),
        'pendencias_empate': sum(1 for p in plano_pessoas if p['status'] == 'pendente_empate_data'),
        'pendencias_sem_nome': sum(1 for p in plano_pessoas if p['status'] == 'pendente_sem_nome'),
        'pendencias_colisao': sum(1 for p in plano_pessoas if p['status'] == 'pendente_colisao_destino'),
        'pendencias_arquivo_invalido': sum(1 for p in plano_pessoas if p['status'] == 'pendente_arquivo_invalido'),
        'total_excedentes_para_excluir': sum(len(p['excedentes']) for p in plano_pessoas if p['status'] == 'consolidar'),
        'bytes_excedentes_recuperados': sum(
            sum(e.get('tamanho') or 0 for e in p['excedentes'])
            for p in plano_pessoas if p['status'] == 'consolidar'
        ),
    }

    return {
        'resumo': resumo,
        'plano': plano_pessoas,
        'raiz_origem': str(raiz_origem),
        'raiz_destino': str(raiz_destino),
    }


def executar_deduplicacao(plano_completo, cat_path, raiz_origem, raiz_destino, aplicar=False):
    """Executa a deduplicação: se aplicar=False, apenas simula. Se True, consolida e exclui excedentes."""
    raiz_origem = Path(raiz_origem).resolve()
    raiz_destino = Path(raiz_destino).resolve()
    cat_path = Path(cat_path).resolve()

    resumo_plano = plano_completo['resumo']
    itens = plano_completo['plano']

    manifesto = {
        'data_execucao': agora(),
        'modo': 'aplicacao' if aplicar else 'simulacao',
        'raiz_origem': str(raiz_origem),
        'raiz_destino': str(raiz_destino),
        'mantidos': [],
        'removidos': [],
        'preservados_pendencia': [],
        'erros': [],
    }

    if not aplicar:
        for p in itens:
            if p['status'] == 'consolidar':
                sel = p['foto_selecionada']
                manifesto['mantidos'].append({
                    'id_pessoa': p['id_pessoa'],
                    'nome_civil': p['nome_civil'],
                    'origem': sel['caminho_origem_relativo'],
                    'destino': sel['caminho_destino_relativo'],
                    'ano': sel['ano'],
                    'uf': sel['uf'],
                    'sequencial': sel['sequencial'],
                    'sha256': sel['sha256'],
                    'tamanho': sel['tamanho'],
                    'motivo': p['motivo_escolha'],
                })
                for exc in p['excedentes']:
                    manifesto['removidos'].append({
                        'id_pessoa': p['id_pessoa'],
                        'origem': exc['caminho_relativo'],
                        'ano': exc['ano'],
                        'uf': exc['uf'],
                        'sequencial': exc['sequencial'],
                        'sha256': exc.get('sha256'),
                        'tamanho': exc.get('tamanho'),
                        'motivo': 'Excedente de pessoa consolidada',
                    })
            else:
                manifesto['preservados_pendencia'].append({
                    'id_pessoa': p['id_pessoa'],
                    'nome_civil': p.get('nome_civil'),
                    'status': p['status'],
                    'motivo': p.get('motivo_pendencia'),
                    'arquivos_preservados': p.get('preservados', []),
                })

        return {
            'sucesso': True,
            'modo': 'simulacao',
            'resumo': resumo_plano,
            'manifesto': manifesto,
        }

    # === MODO APLICAÇÃO ===
    # 1. Trava de concorrência com aquisição
    lock = cat_path.with_suffix('.lock')
    if lock.is_file():
        raise RuntimeError(f"Lock de concorrência existente ({lock}). Não execute simultaneamente com a aquisição.")

    try:
        with lock.open('x', encoding='utf8') as lk:
            lk.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError(f"Lock de aquisição criado por outro processo: {lock}")

    backup_path = None
    try:
        # 2. Backup WAL-consistente do SQLite antes de qualquer mutação
        backup_path = fazer_backup_sqlite(cat_path)

        cat = abrir(cat_path)

        arquivos_publicados = 0
        arquivos_excluidos = 0
        bytes_recuperados = 0

        raiz_destino.mkdir(parents=True, exist_ok=True)

        for p in itens:
            if p['status'] != 'consolidar':
                manifesto['preservados_pendencia'].append({
                    'id_pessoa': p['id_pessoa'],
                    'nome_civil': p.get('nome_civil'),
                    'status': p['status'],
                    'motivo': p.get('motivo_pendencia'),
                    'arquivos_preservados': p.get('preservados', []),
                })
                continue

            sel = p['foto_selecionada']
            origem_rel = sel['caminho_origem_relativo']
            destino_rel = sel['caminho_destino_relativo']

            caminho_origem = caminho_seguro(raiz_origem, origem_rel)
            caminho_destino = raiz_destino / destino_rel
            caminho_destino.parent.mkdir(parents=True, exist_ok=True)

            # Verificar se destino já existe e é válido
            destino_valido = False
            if caminho_destino.is_file():
                check = validar_arquivo_imagem(caminho_destino, sha_esperado=sel['sha256'], tamanho_esperado=sel['tamanho'])
                if check['valido']:
                    destino_valido = True
                else:
                    # Conflito de conteúdo no destino
                    manifesto['erros'].append({
                        'id_pessoa': p['id_pessoa'],
                        'erro': f"Destino {destino_rel} já existe com conteúdo diferente",
                    })
                    continue

            if not destino_valido:
                # Publicação atômica via arquivo temporário na pasta de destino
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(dir=caminho_destino.parent, prefix='tmp_', suffix='.part', delete=False) as tmp_f:
                        tmp_path = Path(tmp_f.name)
                        with caminho_origem.open('rb') as f_in:
                            shutil.copyfileobj(f_in, tmp_f)

                    # Validar temporário
                    val_tmp = validar_arquivo_imagem(tmp_path, sha_esperado=sel['sha256'], tamanho_esperado=sel['tamanho'])
                    if not val_tmp['valido']:
                        tmp_path.unlink(missing_ok=True)
                        manifesto['erros'].append({
                            'id_pessoa': p['id_pessoa'],
                            'erro': f"Validação do arquivo temporário falhou: {val_tmp['motivo']}",
                        })
                        continue

                    # Atômico replace
                    tmp_path.replace(caminho_destino)
                finally:
                    if tmp_path and tmp_path.exists():
                        tmp_path.unlink(missing_ok=True)

            # Confirmar existência e integridade do destino final
            val_final = validar_arquivo_imagem(caminho_destino, sha_esperado=sel['sha256'], tamanho_esperado=sel['tamanho'])
            if not val_final['valido']:
                manifesto['erros'].append({
                    'id_pessoa': p['id_pessoa'],
                    'erro': f"Destino final não pôde ser confirmado: {val_final['motivo']}",
                })
                continue

            arquivos_publicados += 1

            # Atualizar catálogo SQLite
            # 1. Atualizar registro da imagem selecionada com novo caminho (normalizado com '/')
            cat.execute("""
                UPDATE imagens
                SET caminho = ?, status = 'disponivel', verificado = ?, detalhe = 'Consolidada na pasta fotos selecionadas'
                WHERE ano = ? AND uf = ? AND sequencial = ?
            """, (PurePosixPath(destino_rel).as_posix(), agora(), sel['ano'], sel['uf'], sel['sequencial']))

            cat.execute("""
                INSERT OR REPLACE INTO verificacoes VALUES (?, ?, ?, ?, ?)
            """, (sel['ano'], sel['uf'], sel['sequencial'], val_final['mtime_ns'], sel['sha256']))

            # 2. Atualizar todos os IDs associados para apontar para a foto escolhida
            for cid in p['ids_associados']:
                cat.execute("""
                    UPDATE principais
                    SET foto_status = 'disponivel', foto_anterior = ?, consultado = ?
                    WHERE id_candidato = ?
                """, (int(p.get('foto_anterior', False)), agora(), cid))

            # 3. Tratar imagens excedentes da pessoa no catálogo
            for exc in p['excedentes']:
                cat.execute("""
                    UPDATE imagens
                    SET status = 'excluida_consolidacao',
                        detalhe = 'Fotografia histórica removida por consolidação na mais recente',
                        caminho = NULL
                    WHERE ano = ? AND uf = ? AND sequencial = ?
                """, (exc['ano'], exc['uf'], exc['sequencial']))

                cat.execute("""
                    DELETE FROM verificacoes WHERE ano = ? AND uf = ? AND sequencial = ?
                """, (exc['ano'], exc['uf'], exc['sequencial']))

            cat.commit()

            manifesto['mantidos'].append({
                'id_pessoa': p['id_pessoa'],
                'nome_civil': p['nome_civil'],
                'origem': origem_rel,
                'destino': destino_rel,
                'ano': sel['ano'],
                'uf': sel['uf'],
                'sequencial': sel['sequencial'],
                'sha256': sel['sha256'],
                'tamanho': sel['tamanho'],
                'motivo': p['motivo_escolha'],
            })

            # Excluir cópia original da foto selecionada (se não for o mesmo caminho físico)
            if caminho_origem.resolve() != caminho_destino.resolve():
                try:
                    if excluir_arquivo_seguro(caminho_origem, raiz_origem):
                        pass
                except Exception as e:
                    manifesto['erros'].append({'id_pessoa': p['id_pessoa'], 'erro': f"Falha ao excluir original {origem_rel}: {e}"})

            # Excluir arquivos físicos das imagens excedentes
            for exc in p['excedentes']:
                cam_exc_rel = exc['caminho_relativo']
                if not cam_exc_rel:
                    continue
                try:
                    caminho_exc = caminho_seguro(raiz_origem, cam_exc_rel)
                    tamanho_exc = exc.get('tamanho') or (caminho_exc.stat().st_size if caminho_exc.is_file() else 0)
                    if excluir_arquivo_seguro(caminho_exc, raiz_origem):
                        arquivos_excluidos += 1
                        bytes_recuperados += tamanho_exc
                        manifesto['removidos'].append({
                            'id_pessoa': p['id_pessoa'],
                            'caminho': cam_exc_rel,
                            'ano': exc['ano'],
                            'uf': exc['uf'],
                            'sequencial': exc['sequencial'],
                            'tamanho': tamanho_exc,
                        })
                except Exception as e:
                    manifesto['erros'].append({'id_pessoa': p['id_pessoa'], 'erro': f"Falha ao excluir excedente {cam_exc_rel}: {e}"})

        cat.close()

        resumo_aplicacao = {
            'backup_sqlite': str(backup_path),
            'arquivos_publicados': arquivos_publicados,
            'arquivos_excluidos': arquivos_excluidos,
            'bytes_recuperados': bytes_recuperados,
            'espaco_recuperado_mb': round(bytes_recuperados / (1024**2), 2),
            'total_consolidados': resumo_plano['consolidadas'],
            'total_pendencias': (
                resumo_plano['pendencias_ambiguidade']
                + resumo_plano['pendencias_empate']
                + resumo_plano['pendencias_sem_nome']
                + resumo_plano['pendencias_colisao']
                + resumo_plano['pendencias_arquivo_invalido']
            ),
        }

        return {
            'sucesso': True,
            'modo': 'aplicacao',
            'resumo_plano': resumo_plano,
            'resumo_aplicacao': resumo_aplicacao,
            'manifesto': manifesto,
        }
    finally:
        lock.unlink(missing_ok=True)


def salvar_relatorios(resultado, raiz_saida=None):
    """Salva os relatórios JSON, resumo de texto e manifesto fora da pasta de fotos selecionadas."""
    if raiz_saida is None:
        raiz_saida = RAIZ / 'dados_bdr/fotos'
    raiz_saida = Path(raiz_saida).resolve()
    raiz_saida.mkdir(parents=True, exist_ok=True)

    relatorio_json = raiz_saida / 'relatorio_deduplicacao.json'
    manifesto_json = raiz_saida / 'manifesto_arquivos.json'
    resumo_txt = raiz_saida / 'resumo_deduplicacao.txt'

    # 1. Relatório JSON
    with relatorio_json.open('w', encoding='utf8') as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    # 2. Manifesto de arquivos
    manifesto = resultado.get('manifesto', {})
    with manifesto_json.open('w', encoding='utf8') as f:
        json.dump(manifesto, f, ensure_ascii=False, indent=2)

    # 3. Resumo legível
    linhas = []
    linhas.append("=" * 80)
    linhas.append("RELATÓRIO DE DEDUPLICAÇÃO E CONSOLIDAÇÃO DE FOTOS DE CANDIDATOS")
    linhas.append("=" * 80)
    linhas.append(f"Data: {agora()}")
    linhas.append(f"Modo: {resultado.get('modo', '').upper()}")
    linhas.append("-" * 80)

    resumo = resultado.get('resumo') or resultado.get('resumo_plano', {})
    linhas.append(f"Pessoas analisadas no escopo:       {resumo.get('total_pessoas_analisadas', 0):,}")
    linhas.append(f"Pessoas com fotografia consolidada: {resumo.get('consolidadas', 0):,}")
    linhas.append(f"  - Foto anterior utilizada:        {resumo.get('foto_anterior_utilizada', 0):,}")
    linhas.append(f"Pessoas sem foto válida:            {resumo.get('sem_foto_valida', 0):,}")
    linhas.append(f"Pendências de ambiguidade:          {resumo.get('pendencias_ambiguidade', 0):,}")
    linhas.append(f"Pendências de empate de datas:      {resumo.get('pendencias_empate', 0):,}")
    linhas.append(f"Pendências de colisão de caminho:   {resumo.get('pendencias_colisao', 0):,}")
    linhas.append(f"Pendências de nome ausente:         {resumo.get('pendencias_sem_nome', 0):,}")
    linhas.append(f"Pendências de arquivo inválido:     {resumo.get('pendencias_arquivo_invalido', 0):,}")
    linhas.append(f"Imagens excedentes previstas:       {resumo.get('total_excedentes_para_excluir', 0):,}")
    mb_rec = resumo.get('bytes_excedentes_recuperados', 0) / (1024**2)
    linhas.append(f"Espaço excedente estimado:          {mb_rec:,.2f} MB")

    if 'resumo_aplicacao' in resultado:
        app = resultado['resumo_aplicacao']
        linhas.append("-" * 80)
        linhas.append("RESULTADO DA APLICAÇÃO:")
        linhas.append(f"Backup do catálogo gerado em:       {app.get('backup_sqlite')}")
        linhas.append(f"Fotografias finais publicadas:      {app.get('arquivos_publicados', 0):,}")
        linhas.append(f"Arquivos excedentes excluídos:      {app.get('arquivos_excluidos', 0):,}")
        linhas.append(f"Espaço real recuperado em disco:    {app.get('espaco_recuperado_mb', 0):,.2f} MB")

    linhas.append("=" * 80)

    with resumo_txt.open('w', encoding='utf8') as f:
        f.write('\n'.join(linhas))

    return {
        'relatorio_json': str(relatorio_json),
        'manifesto_json': str(manifesto_json),
        'resumo_txt': str(resumo_txt),
    }
