"""Catálogo SQLite auxiliar. Identificadores civis ficam somente como hashes locais."""
import os
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
UFS = ('CE', 'MA', 'MS', 'RJ', 'RN', 'RS')


def configuracao():
    imagens = Path(os.environ.get('BDR_FOTOS_DIR', RAIZ / 'dados_bdr/fotos/imagens')).resolve()
    banco = Path(os.environ.get('BDR_FOTOS_CATALOGO', RAIZ / 'dados_bdr/fotos/catalogo.sqlite3')).resolve()
    cache = Path(os.environ.get('BDR_FOTOS_CACHE', RAIZ / 'dados_bdr/fotos/zips')).resolve()
    return imagens, banco, cache


DDL = '''
CREATE TABLE IF NOT EXISTS pessoas (
 id_candidato TEXT PRIMARY KEY, bio TEXT, titulo TEXT);
CREATE TABLE IF NOT EXISTS internas (
 id_candidatura TEXT PRIMARY KEY, id_candidato TEXT NOT NULL,
 ano INTEGER, uf TEXT, sequencial TEXT);
CREATE INDEX IF NOT EXISTS internas_foto ON internas(ano,uf,sequencial);
CREATE TABLE IF NOT EXISTS fontes (
 dataset TEXT PRIMARY KEY, ano INTEGER, metadados TEXT NOT NULL, consultado TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cobertura (
 dataset TEXT, uf TEXT, status TEXT, detalhe TEXT, verificado TEXT,
 PRIMARY KEY(dataset,uf));
CREATE TABLE IF NOT EXISTS registros (
 chave TEXT PRIMARY KEY, dataset TEXT, ano INTEGER, data TEXT, ordem TEXT,
 uf TEXT, sequencial TEXT, eleicao TEXT, bio TEXT, cpf TEXT, titulo TEXT,
 id_cpf TEXT, origem TEXT, linha INTEGER);
CREATE INDEX IF NOT EXISTS registros_foto ON registros(ano,uf,sequencial);
CREATE INDEX IF NOT EXISTS registros_cpf ON registros(cpf,bio);
CREATE INDEX IF NOT EXISTS registros_titulo ON registros(titulo,bio);
CREATE TABLE IF NOT EXISTS vinculos (
 chave TEXT PRIMARY KEY, id_candidato TEXT, metodo TEXT);
CREATE INDEX IF NOT EXISTS vinculos_pessoa ON vinculos(id_candidato);
CREATE TABLE IF NOT EXISTS auditoria (
 chave TEXT, id_candidato TEXT, motivo TEXT, PRIMARY KEY(chave,id_candidato,motivo));
CREATE INDEX IF NOT EXISTS auditoria_pessoa ON auditoria(id_candidato);
CREATE TABLE IF NOT EXISTS imagens (
 ano INTEGER, uf TEXT, sequencial TEXT, status TEXT NOT NULL,
 caminho TEXT, mime TEXT, sha256 TEXT, tamanho INTEGER, largura INTEGER, altura INTEGER,
 url TEXT, arquivo TEXT, verificado TEXT, detalhe TEXT,
 PRIMARY KEY(ano,uf,sequencial));
CREATE TABLE IF NOT EXISTS verificacoes (
 ano INTEGER,uf TEXT,sequencial TEXT,mtime_ns INTEGER,sha256 TEXT,
 PRIMARY KEY(ano,uf,sequencial));
CREATE TABLE IF NOT EXISTS principais (
 id_candidato TEXT PRIMARY KEY, ultima_chave TEXT, foto_chave TEXT,
 foto_status TEXT, foto_anterior INTEGER, cobertura_completa INTEGER,
 consultado TEXT);
CREATE TABLE IF NOT EXISTS execucoes (
 inicio TEXT PRIMARY KEY, escopo TEXT, fim TEXT, relatorio TEXT);
'''


def abrir(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=120)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA busy_timeout=120000')
    con.execute('PRAGMA cache_size=-65536')  # teto de 64 MiB por conexão da CLI
    con.executescript(DDL)
    return con


def caminho_seguro(raiz, relativo):
    if not relativo or Path(relativo).is_absolute() or '\\' in relativo or ':' in relativo:
        raise ValueError('Caminho de imagem inválido')
    caminho = (Path(raiz) / relativo).resolve()
    if not caminho.is_relative_to(Path(raiz).resolve()):
        raise ValueError('Imagem fora do diretório configurado')
    return caminho


# Somente os dados necessários ao HTTP. Nunca expõe CPF/título/bio/arquivos-fonte.
CONSULTA_PUBLICA = '''SELECT p.id_candidato,
 CASE WHEN f.chave IS NOT NULL AND v.chave IS NULL THEN 'associacao_pendente' ELSE p.foto_status END foto_status,
 p.foto_anterior,
 p.cobertura_completa,p.consultado,
 r.ano ultima_ano,r.data ultima_data,r.uf ultima_uf,r.sequencial ultima_sequencial,
 ui.status ultima_foto_status,
 f.ano foto_ano,f.uf foto_uf,f.sequencial foto_sequencial,v.metodo,
 i.caminho,i.mime,i.sha256,i.tamanho,i.verificado
 FROM principais p LEFT JOIN registros r ON r.chave=p.ultima_chave
 LEFT JOIN imagens ui ON ui.ano=r.ano AND ui.uf=r.uf AND ui.sequencial=r.sequencial
 LEFT JOIN registros f ON f.chave=p.foto_chave
 LEFT JOIN vinculos v ON v.chave=f.chave AND v.id_candidato=p.id_candidato
 LEFT JOIN imagens i ON i.ano=f.ano AND i.uf=f.uf AND i.sequencial=f.sequencial
'''


class LeitorCatalogo:
    """Consultas indexadas em lote; conexão somente leitura por requisição, sem cache global gigante."""
    def __init__(self, banco, imagens):
        self.banco, self.imagens = Path(banco), Path(imagens)

    def buscar(self, ids):
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        try:
            if not self.banco.is_file():
                return {}
            con = sqlite3.connect(self.banco.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
            con.row_factory = sqlite3.Row
            try:
                resultado = {}
                for offset in range(0, len(ids), 500):
                    lote = ids[offset:offset + 500]
                    sql = CONSULTA_PUBLICA + ' WHERE p.id_candidato IN (' + ','.join('?' for _ in lote) + ')'
                    for row in con.execute(sql, lote):
                        resultado[row['id_candidato']] = dict(row)
                return resultado
            finally:
                con.close()
        except (sqlite3.Error, OSError):
            return {}

    def arquivo(self, row):
        if row.get('foto_status') != 'disponivel' or row.get('mime') not in ('image/jpeg', 'image/png'):
            return None
        try:
            path = caminho_seguro(self.imagens, row.get('caminho'))
            if path.is_file() and path.stat().st_size == row['tamanho']:
                return path
        except (ValueError, OSError):
            pass
        return None
