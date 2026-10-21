import asyncio
import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import duckdb
from PIL import Image
from starlette.requests import Request

from bdr.fotos import aquisicao as aq
from bdr.fotos.catalogo import LeitorCatalogo, abrir, caminho_seguro
from bdr.fotos.cli import executar, parser
from bdr.fotos.fontes import (biografia, descobrir, hash_texto, linhas_cadastro, membro_seguro,
                              recurso_fotos, sequencial, titulo, url_oficial)
from frontend import fotos, main


class FotosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.banco = self.raiz / 'catalogo.sqlite3'
        self.imagens = self.raiz / 'imagens'
        self.cat = abrir(self.banco)
        self.addCleanup(self.cat.close)
        self.bio = biografia('MARIA SILVA', '1980-01-01')
        self.titulo = titulo('12345678901')
        self.cat.execute('INSERT INTO pessoas VALUES (?,?,?)', ('p1', self.bio, self.titulo))
        self.cat.execute('INSERT INTO internas VALUES (?,?,?,?,?)', ('c1', 'p1', 2012, 'MA', '100'))
        self.cat.commit()

    def registro(self, chave, ano, sq, data=None, titulo_hash=None, bio=None, cpf=None, id_cpf=None):
        data = data or f'{ano}-10-06'
        self.cat.execute('INSERT INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (chave, f'candidatos-{ano}', ano, data, data, 'MA', sq, 'eleicao', bio or self.bio,
             cpf, titulo_hash or self.titulo, id_cpf, 'consulta.csv', 2))
        self.cat.commit()

    def zip_imagens(self, itens=None, formato='JPEG'):
        stream = io.BytesIO()
        Image.new('RGB', (12, 16), 'red').save(stream, formato)
        path = self.raiz / 'fotos.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for nome, conteudo in itens or [('MA100_div.jpg', stream.getvalue())]:
                info = zipfile.ZipInfo()
                info.filename = nome  # preserva inclusive barra invertida maliciosa no Windows
                z.writestr(info, conteudo)
        return path

    def disponivel(self, ano=2012, sq='100', chave='r1'):
        path = self.zip_imagens([(f'MA{sq}_div.jpg', self.jpeg())])
        aq.extrair_pacote(self.cat, path, self.imagens, ano, 'MA', [sq], 'https://cdn.tse.jus.br/f.zip')

    def jpeg(self):
        stream = io.BytesIO()
        Image.new('RGB', (12, 16)).save(stream, 'JPEG')
        return stream.getvalue()

    def test_sequenciais_preservados_como_texto_e_marcadores_rejeitados(self):
        self.assertEqual(sequencial(' 001000 '), '001000')
        for value in (None, '', '-1', '0', '#NULO', '#NULO#', '#NE', '#NE#', '1.0', 'nan'):
            self.assertIsNone(sequencial(value))

    def test_reconhecedores_oficiais_inspecionados(self):
        self.assertEqual(aq.identificar_foto('MA100000006157_div.jpg'), ('MA', '100000006157', 'jpg'))
        self.assertEqual(aq.identificar_foto('pasta/FMA100002141968_div.jpg'), ('MA', '100002141968', 'jpg'))
        self.assertIsNone(aq.identificar_foto('candidato123.jpg'))

    def test_pessoa_entre_anos_usa_documento_e_nao_sequencial_permanente(self):
        self.registro('r1', 2012, '100')
        self.registro('r2', 2024, '200')
        self.registro('r3', 2026, '300')  # candidatura nova não existe no DER
        aq.vincular(self.cat)
        self.disponivel(2026, '300')
        aq.selecionar_principais(self.cat)
        row = LeitorCatalogo(self.banco, self.imagens).buscar(['p1'])['p1']
        self.assertEqual((row['foto_ano'], row['ultima_ano']), (2026, 2026))
        self.assertEqual(self.cat.execute('SELECT count(*) FROM internas').fetchone()[0], 1)

    def test_ancora_nao_depende_de_hash_interno_ser_cpf(self):
        self.cat.execute('UPDATE pessoas SET titulo=NULL')
        self.registro('r1', 2012, '100', cpf='hash-documento')
        self.registro('r2', 2026, '999', titulo_hash='outro', cpf='hash-documento')
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM vinculos').fetchone()[0], 2)

    def test_recuperacao_sequencial_ausente_fica_no_catalogo_auditavel(self):
        self.cat.execute('UPDATE internas SET sequencial=NULL')
        self.registro('r1', 2012, '100')
        aq.vincular(self.cat)
        self.assertIn('TITULO', self.cat.execute('SELECT metodo FROM vinculos').fetchone()[0])
        self.assertIsNone(self.cat.execute('SELECT sequencial FROM internas').fetchone()[0])

    def test_cpf_pipeline_quando_cpf_valido_reproduz_o_hash(self):
        self.cat.execute('UPDATE pessoas SET titulo=NULL')
        self.registro('r1', 2026, '300', id_cpf='p1')
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT id_candidato FROM vinculos').fetchone()[0], 'p1')

    def test_cpf_comprovado_permite_mudanca_de_nome_e_audita_divergencia(self):
        self.cat.execute('UPDATE pessoas SET titulo=NULL')
        self.registro('r1', 2012, '100', cpf='documento-validado')
        self.registro('r2', 2026, '200', cpf='documento-validado', titulo_hash='outro',
                      bio=biografia('MARIA OUTRO SOBRENOME', '1980-01-01'))
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute("SELECT id_candidato FROM vinculos WHERE chave='r2'").fetchone()[0], 'p1')
        self.assertTrue(self.cat.execute("SELECT 1 FROM auditoria WHERE chave='r2' AND motivo='CPF_BIO_DIVERGENTE'").fetchone())

    def test_homonimo_documento_diferente_nao_vincula(self):
        self.registro('r1', 2026, '300', titulo_hash='outro-documento')
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM vinculos').fetchone()[0], 0)

    def test_identidade_ambigua_nao_escolhe_pessoa(self):
        self.cat.execute('INSERT INTO pessoas VALUES (?,?,?)', ('p2', self.bio, self.titulo))
        self.registro('r1', 2026, '300')
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM vinculos').fetchone()[0], 0)
        self.assertEqual(self.cat.execute("SELECT count(*) FROM auditoria WHERE motivo='IDENTIDADE_AMBIGUA'").fetchone()[0], 2)

    def test_mesma_chave_de_foto_para_pessoas_distintas_e_bloqueada(self):
        outra_bio = biografia('JOAO SILVA', '1970-01-01')
        self.cat.execute('INSERT INTO pessoas VALUES (?,?,?)', ('p2', outra_bio, 'outro-documento'))
        self.cat.execute("INSERT INTO internas VALUES ('c2','p2',2012,'MA','100')")
        self.registro('r1', 2012, '100', '2012-10-07')
        self.registro('r2', 2012, '100', '2012-10-28', titulo_hash='outro-documento', bio=outra_bio)
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM vinculos').fetchone()[0], 0)
        self.assertEqual(self.cat.execute("SELECT count(*) FROM auditoria WHERE motivo='CHAVE_FOTO_AMBIGUA'").fetchone()[0], 2)

    def test_api_recusa_selecao_antiga_quando_vinculo_foi_bloqueado(self):
        self.registro('r1', 2012, '100')
        aq.vincular(self.cat)
        self.disponivel()
        aq.selecionar_principais(self.cat)
        self.cat.execute('DELETE FROM vinculos')
        self.cat.commit()
        leitor = LeitorCatalogo(self.banco, self.imagens)
        row = leitor.buscar(['p1'])['p1']
        self.assertEqual(row['foto_status'], 'associacao_pendente')
        self.assertIsNone(leitor.arquivo(row))

    def test_titulo_correto_com_nascimento_divergente_nao_vincula(self):
        self.registro('r1', 2026, '300', bio=biografia('MARIA SILVA', '1981-01-01'))
        aq.vincular(self.cat)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM vinculos').fetchone()[0], 0)

    def test_foto_anterior_sem_esconder_candidatura_recente_e_falha(self):
        self.registro('r1', 2012, '100')
        self.registro('r2', 2026, '300')
        aq.vincular(self.cat)
        self.disponivel()
        aq.gravar_imagem(self.cat, 2026, 'MA', '300', 'erro_temporario')
        aq.selecionar_principais(self.cat)
        row = LeitorCatalogo(self.banco, self.imagens).buscar(['p1'])['p1']
        self.assertEqual((row['foto_ano'], row['ultima_ano'], row['foto_anterior'], row['cobertura_completa']), (2012, 2026, 1, 0))

    def test_suplementar_ordenada_pela_data_e_turnos_compartilham_arquivo(self):
        self.registro('r1', 2024, '100', '2024-05-10')
        self.registro('r2', 2024, '200', '2024-12-01')
        self.registro('r3', 2024, '200', '2024-12-15')
        aq.vincular(self.cat)
        self.disponivel(2024, '200')
        aq.selecionar_principais(self.cat)
        row = LeitorCatalogo(self.banco, self.imagens).buscar(['p1'])['p1']
        self.assertEqual(row['ultima_data'], '2024-12-15')
        self.assertEqual(self.cat.execute('SELECT count(*) FROM imagens').fetchone()[0], 1)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM principais').fetchone()[0], 1)

    def test_candidaturas_distintas_na_mesma_data_sinalizam_ambiguidade(self):
        self.registro('r1', 2026, '100')
        self.registro('r2', 2026, '200')
        aq.vincular(self.cat)
        aq.selecionar_principais(self.cat)
        self.assertEqual(self.cat.execute('SELECT foto_status FROM principais').fetchone()[0], 'associacao_ambigua')

    def test_ausente_corrompida_extensao_incompativel_e_formato_desconhecido(self):
        png = io.BytesIO()
        Image.new('RGB', (3, 4)).save(png, 'PNG')
        path = self.zip_imagens([('MA100_div.jpg', b'corrompida'), ('MA200_div.jpg', png.getvalue())])
        aq.extrair_pacote(self.cat, path, self.imagens, 2012, 'MA', ['100', '200', '300'], 'url')
        self.assertEqual(dict(self.cat.execute('SELECT sequencial,status FROM imagens')), {
            '100': 'imagem_invalida', '200': 'imagem_invalida', '300': 'nao_encontrada'})
        path = self.zip_imagens([('formato-inedito.jpg', self.jpeg())])
        aq.extrair_pacote(self.cat, path, self.imagens, 2012, 'MA', ['400'], 'url')
        self.assertEqual(self.cat.execute("SELECT status FROM imagens WHERE sequencial='400'").fetchone()[0], 'formato_desconhecido')

    def test_zip_inseguro_e_paths_de_catalogo_rejeitados(self):
        for nome in ('../MA100_div.jpg', '/absoluto.jpg', 'C:/a.jpg', 'pasta\\a.jpg'):
            with self.subTest(nome=nome), self.assertRaises(ValueError):
                aq.extrair_pacote(self.cat, self.zip_imagens([(nome, self.jpeg())]), self.imagens, 2012, 'MA', ['100'], 'url')
        with self.assertRaises(ValueError):
            caminho_seguro(self.imagens, '../secreto')

    def test_imagem_muito_grande_rejeitada_sem_publicar_arquivo(self):
        with patch.object(aq, 'MAX_IMAGEM', 10):
            self.disponivel()
        self.assertEqual(self.cat.execute('SELECT status FROM imagens').fetchone()[0], 'imagem_invalida')
        self.assertEqual(list(self.imagens.rglob('*.jpg')), [])

    def test_retomada_preserva_mtime_e_nao_duplica(self):
        self.disponivel()
        path = self.imagens / '2012/MA/100.jpg'
        mtime = path.stat().st_mtime_ns
        self.disponivel()
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM imagens').fetchone()[0], 1)

    def test_retomada_revalida_arquivo_local_antes_de_pular_extracao(self):
        self.disponivel()
        path = self.imagens / '2012/MA/100.jpg'
        path.write_bytes(b'invalida')
        aq.revalidar_imagens(self.cat, self.imagens)
        self.assertEqual(self.cat.execute('SELECT status FROM imagens').fetchone()[0], 'imagem_invalida')
        self.disponivel()
        self.assertEqual(self.cat.execute('SELECT status FROM imagens').fetchone()[0], 'disponivel')

    def test_atualizacao_explicita_substitui_foto_da_mesma_chave(self):
        self.disponivel()
        antes = self.cat.execute('SELECT sha256 FROM imagens').fetchone()[0]
        nova = io.BytesIO()
        Image.new('RGB', (12, 16), 'blue').save(nova, 'JPEG')
        path = self.zip_imagens([('MA100_div.jpg', nova.getvalue())])
        aq.extrair_pacote(self.cat, path, self.imagens, 2012, 'MA', ['100'], 'url', atualizar=True)
        self.assertNotEqual(self.cat.execute('SELECT sha256 FROM imagens').fetchone()[0], antes)
        self.assertEqual(self.cat.execute('SELECT count(*) FROM imagens').fetchone()[0], 1)

    def test_nao_adquire_historicas_quando_ja_tem_recente(self):
        self.registro('r1', 2012, '100')
        self.registro('r2', 2026, '200')
        aq.vincular(self.cat)
        self.disponivel(2026, '200')
        aq.preparar_selecao(self.cat)
        self.assertEqual(aq.necessidades(self.cat, 2012, 'MA'), [])

    def test_falha_de_pacote_preserva_outros_e_estado_temporario(self):
        p = {'ano': 2012, 'resources': [{'name': 'MA - Fotos de candidatos', 'url': 'https://cdn.tse.jus.br/f.zip'}]}
        with patch('bdr.fotos.aquisicao.pacote_local', side_effect=RuntimeError('offline')):
            aq.adquirir_pacote(self.banco, self.imagens, self.raiz, p, 'MA', ['100'])
        self.assertEqual(self.cat.execute('SELECT status FROM imagens').fetchone()[0], 'erro_temporario')
        self.disponivel(2024, '200')
        self.assertEqual(self.cat.execute("SELECT count(*) FROM imagens WHERE status='disponivel'").fetchone()[0], 1)

    def test_atualizacao_falha_preserva_imagem_e_registra_pendencia(self):
        self.disponivel()
        p = {'ano': 2012, 'dataset': 'candidatos-2012', 'resources': [
            {'name': 'MA - Fotos de candidatos', 'url': 'https://cdn.tse.jus.br/f.zip'}]}
        with patch('bdr.fotos.aquisicao.pacote_local', side_effect=RuntimeError('offline')):
            aq.adquirir_pacote(self.banco, self.imagens, self.raiz, p, 'MA', ['100'], atualizar=True)
        self.assertEqual(self.cat.execute('SELECT status FROM imagens').fetchone()[0], 'disponivel')
        self.assertEqual(self.cat.execute("SELECT status FROM cobertura WHERE dataset='candidatos-2012::fotos'").fetchone()[0], 'erro_temporario')

    def test_catalogo_sem_arquivo_funciona_sem_criar_banco(self):
        path = self.raiz / 'ausente.sqlite3'
        self.assertEqual(LeitorCatalogo(path, self.imagens).buscar(['p1']), {})
        self.assertFalse(path.exists())

    def test_api_usa_foto_principal_mantem_contexto_e_nao_baixa(self):
        self.registro('r1', 2026, '300')
        aq.vincular(self.cat)
        self.disponivel(2026, '300')
        aq.selecionar_principais(self.cat)
        candidato = {'id_candidato': 'p1', 'id_candidatura': 'c1', 'ano': 2012, 'partido': 'ABC', 'nome': 'Maria'}
        with patch('frontend.fotos.leitor', return_value=LeitorCatalogo(self.banco, self.imagens)), \
             patch('bdr.download.baixar', side_effect=AssertionError('HTTP não pode adquirir')), \
             patch.object(main, '_consultar', side_effect=AssertionError('rota de foto não consulta DER')):
            enriquecido = fotos.enriquecer([candidato])[0]
            self.assertEqual((enriquecido['ano'], enriquecido['foto_ano'], enriquecido['partido']), (2012, 2026, 'ABC'))
            self.assertNotIn('foto_url', candidato)
            request = Request({'type': 'http', 'headers': []})
            response = fotos.foto_candidato('p1', request)
            self.assertEqual(response.media_type, 'image/jpeg')
            etag = response.headers['etag']
            request = Request({'type': 'http', 'headers': [(b'if-none-match', etag.encode())]})
            self.assertEqual(fotos.foto_candidato('p1', request).status_code, 304)
            self.assertFalse(any(k in enriquecido for k in ('titulo', 'cpf', 'bio')))

    def test_http_asgi_com_e_sem_catalogo(self):
        async def get(path):
            mensagens = []
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                mensagens.append(message)
            await main.app({'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                'query_string': b'', 'headers': [], 'server': ('test', 80), 'client': ('test', 1)}, receive, send)
            return mensagens
        with patch('frontend.fotos.leitor', return_value=LeitorCatalogo(self.banco, self.imagens)):
            self.assertEqual(asyncio.run(get('/api/candidatos/p1/foto'))[0]['status'], 404)
            self.registro('r1', 2012, '100')
            aq.vincular(self.cat)
            self.disponivel()
            aq.selecionar_principais(self.cat)
            mensagens = asyncio.run(get('/api/candidatos/p1/foto'))
            self.assertEqual(mensagens[0]['status'], 200)
            self.assertEqual(b''.join(m.get('body', b'') for m in mensagens[1:]), self.jpeg())

    def test_fonte_csv_streaming_filtra_ufs_e_valida_cpf(self):
        path = self.raiz / 'cadastro.zip'
        csv = ('ANO_ELEICAO;SG_UF;SQ_CANDIDATO;NM_CANDIDATO;DT_NASCIMENTO;NR_CPF_CANDIDATO\n'
               '2026;MA;300;MARIA SILVA;01/01/1980;11144477735\n'
               '2026;SP;400;MARIA SILVA;01/01/1980;11144477735\n')
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('consulta_cand_2026_BRASIL.csv', csv.encode('cp1252'))
        rows = list(linhas_cadastro(path, ['MA']))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cpf'], hash_texto('CPF|11144477735'))

    def test_descoberta_registra_urls_e_rejeita_fontes_externas(self):
        dado = {'success': True, 'result': {'count': 1, 'results': [{'name': 'candidatos-2026',
               'resources': [{'name': 'MA - Fotos de candidatos', 'url': 'https://cdn.tse.jus.br/real.zip'}]}]}}
        with patch('bdr.fotos.fontes.json_oficial', return_value=dado) as call:
            pacotes = descobrir(self.raiz)
            self.assertEqual(recurso_fotos(pacotes[0], 'MA'), 'https://cdn.tse.jus.br/real.zip')
            descobrir(self.raiz)
            self.assertEqual(call.call_count, 1)
        with self.assertRaises(ValueError):
            url_oficial('https://tse.jus.br.exemplo.com/f.zip')

    def test_cli_completa_fonte_identidade_imagem_catalogo_e_retomada(self):
        der_path = self.raiz / 'der.duckdb'
        der = duckdb.connect(str(der_path))
        der.execute('CREATE TABLE Candidato(id_candidato VARCHAR,nome_civil VARCHAR,dt_nascimento DATE,titulo_eleitoral VARCHAR)')
        der.execute('CREATE TABLE Eleicao(id_eleicao VARCHAR,ano INTEGER)')
        der.execute('CREATE TABLE Candidatura(id_candidatura VARCHAR,id_candidato VARCHAR,id_eleicao VARCHAR,uf VARCHAR,sequencial VARCHAR)')
        der.execute("INSERT INTO Candidato VALUES ('p1','MARIA SILVA','1980-01-01','12345678901')")
        der.execute("INSERT INTO Eleicao VALUES ('e1',2012)")
        der.execute("INSERT INTO Candidatura VALUES ('c1','p1','e1','MA','100')")
        before = der.execute('SELECT * FROM Candidatura').fetchall()
        der.close()
        cadastro = self.raiz / 'consulta.zip'
        csv = ('ANO_ELEICAO;SG_UF;SQ_CANDIDATO;NM_CANDIDATO;DT_NASCIMENTO;NR_TITULO_ELEITORAL_CANDIDATO;NM_EMAIL\n'
               '2012;MA;100;MARIA SILVA;01/01/1980;12345678901;invalido\x81\n'
               '2026;MA;300;MARIA SILVA;01/01/1980;12345678901;outro\n')
        with zipfile.ZipFile(cadastro, 'w') as z:
            z.writestr('consulta_cand_2026_MA.csv', csv.encode('latin1'))
        imagens = self.zip_imagens([('FMA300_div.jpg', self.jpeg())])
        pacote = {'dataset': 'candidatos-2026', 'ano': 2026, 'resources': [
            {'name': 'Candidatos', 'url': 'https://cdn.tse.jus.br/cadastro.zip'},
            {'name': 'MA - Fotos de candidatos', 'url': 'https://cdn.tse.jus.br/fotos.zip'}]}
        args = parser().parse_args(['adquirir', '--banco', str(der_path), '--todos', '--uf', 'MA',
            '--catalogo', str(self.banco), '--imagens', str(self.imagens), '--cache', str(self.raiz)])
        with patch('bdr.fotos.cli.descobrir', return_value=[pacote]), \
             patch('bdr.fotos.aquisicao.pacote_local', side_effect=lambda url, *a: cadastro if 'cadastro' in url else imagens):
            resultado = executar(args)
            self.assertEqual(resultado['fotos_disponiveis'], 1)
            self.assertFalse(resultado['busca_completa'])
            mtime = (self.imagens / '2026/MA/300.jpg').stat().st_mtime_ns
            executar(args)
            self.assertEqual((self.imagens / '2026/MA/300.jpg').stat().st_mtime_ns, mtime)
            args.retomar_fotos = True
            with patch('bdr.fotos.cli.duckdb.connect', side_effect=AssertionError('retomada não abre DER')), \
                 patch('bdr.fotos.cli.descobrir', side_effect=AssertionError('retomada não descobre fontes novas')):
                retomada = executar(args)
                self.assertEqual(retomada['fotos_disponiveis'], 1)
                self.assertEqual((self.imagens / '2026/MA/300.jpg').stat().st_mtime_ns, mtime)
        der = duckdb.connect(str(der_path), read_only=True)
        self.assertEqual(der.execute('SELECT * FROM Candidatura').fetchall(), before)
        der.close()

    def test_filtro_pessoa_nao_adquire_outros_ja_presentes_no_catalogo(self):
        self.cat.execute('INSERT INTO pessoas VALUES (?,?,?)', ('p2', self.bio, 'outro'))
        self.registro('r1', 2012, '100')
        self.registro('r2', 2026, '200', titulo_hash='outro')
        aq.vincular(self.cat)
        self.cat.execute('CREATE TEMP TABLE ativos(id_candidato TEXT PRIMARY KEY)')
        self.cat.execute("INSERT INTO ativos VALUES ('p1')")
        aq.preparar_selecao(self.cat)
        self.assertEqual(aq.necessidades(self.cat, 2026, 'MA'), [])


if __name__ == '__main__':
    unittest.main()
