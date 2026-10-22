import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import duckdb
from PIL import Image

from bdr.der.esquema import criar
from bdr.der.fotos import chave_arquivo, carregar_zip, executar, planejar, url_fotos
from publicar_fotos import copiar_fotos


def jpeg():
    arquivo = io.BytesIO()
    Image.new('RGB', (8, 10), 'white').save(arquivo, format='JPEG')
    return arquivo.getvalue()


class FotosTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        criar(self.con)
        self.con.execute("INSERT INTO Candidato(id_candidato,nome_civil) VALUES ('p1','Pessoa um'),('p2','Pessoa dois')")
        self.con.execute("INSERT INTO Municipio VALUES ('m','00001','Cidade','RN','Nordeste')")
        self.con.execute("INSERT INTO Eleicao(id_eleicao,ano,turno) VALUES ('e24',2024,1),('e22',2022,1),('e24t2',2024,2)")
        self.candidatura('c1', 'p1', 'e24', '123')
        self.candidatura('c2', 'p1', 'e22', '999')
        self.candidatura('c3', 'p2', 'e24', '456')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

    def candidatura(self, id, pessoa, eleicao, sq):
        self.con.execute('''INSERT INTO Candidatura(id_candidatura,id_eleicao,id_candidato,id_municipio,uf,sequencial)
            VALUES (?,?,?,'m','RN',?)''', [id, eleicao, pessoa, sq])

    def zip(self, arquivos):
        destino = self.raiz / 'fotos.zip'
        with zipfile.ZipFile(destino, 'w') as z:
            for nome, dados in arquivos:
                z.writestr(nome, dados)
        return destino

    def test_nomes_reais_e_antigos_sem_confundir_numero(self):
        self.assertEqual(chave_arquivo('pasta/FRN000123_div.jpeg'), ('RN','123'))
        self.assertEqual(chave_arquivo('MA233112.jpg'), ('MA','233112'))
        self.assertIsNone(chave_arquivo('leiame.pdf'))

    def test_foto_certa_por_uf_e_sq_e_reexecucao_nao_duplica(self):
        z = self.zip([('FRN123_div.jpeg', jpeg()), ('FMA456_div.jpeg', jpeg())])
        n, avisos = carregar_zip(self.con, z, 2024, 'RN', {'123':'p1', '456':'p2'}, 'TSE')
        self.assertEqual((n, avisos), (1, []))
        self.assertEqual(self.con.execute('SELECT id_candidato,uf,sq_candidato,imagem FROM Foto_Candidato').fetchone(), ('p1','RN','123',jpeg()))
        self.assertEqual(carregar_zip(self.con, z, 2024, 'RN', {'123':'p1'}, 'TSE')[0], 0)

    def test_ambiguidade_nao_e_escondida_por_candidato_ja_com_foto(self):
        self.candidatura('c4','p2','e24','123')
        self.candidatura('c5','p1','e24t2','123')
        planos = planejar(self.con, ['RN'])
        chave = [r for r in planos if r[:3] == (2024,'RN','123')][0]
        self.assertEqual(chave[-1], 2)

    def test_imagem_invalida_nao_e_salva(self):
        z = self.zip([('FRN123_div.jpeg', b'<html>erro</html>')])
        n, avisos = carregar_zip(self.con, z, 2024, 'RN', {'123':'p1'}, 'TSE')
        self.assertEqual(n, 0)
        self.assertTrue(avisos)

    def test_duas_imagens_mesma_chave_nao_escolhem_arbitrariamente(self):
        z = self.zip([('FRN123_div.jpeg', jpeg()), ('RN123.jpg', jpeg())])
        n, avisos = carregar_zip(self.con, z, 2024, 'RN', {'123':'p1'}, 'TSE')
        self.assertEqual(n, 0)
        self.assertTrue(avisos)

    @patch('bdr.der.fotos.baixar')
    def test_historico_so_busca_pessoas_sem_foto_e_404_nao_interrompe(self, baixar):
        z = self.zip([('FRN123_div.jpeg', jpeg())])
        def download(url, destino):
            if '2024' in url:
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(z.read_bytes())
                return 'baixado'
            raise FileNotFoundError(url)
        baixar.side_effect = download
        r = executar(self.con, self.raiz / 'cache', ['RN'])
        self.assertEqual(r['total_com_foto'], 1)
        self.assertEqual(baixar.call_count, 1)  # p1 tem foto; não consulta ZIP de 2022
        self.assertEqual(r['candidatos_sem_foto_no_recorte'], 1)

    @patch('bdr.der.fotos.baixar', side_effect=FileNotFoundError('404'))
    def test_404_nao_interrompe_busca_historica(self, baixar):
        r = executar(self.con, self.raiz / 'cache', ['RN'])
        self.assertEqual(r['total_com_foto'], 0)
        self.assertEqual(baixar.call_count, 2)
        self.assertEqual([a['status'] for a in r['arquivos']], ['indisponivel', 'indisponivel'])

    def test_ano_e_uf_de_outro_candidato_nao_atribuem_foto(self):
        self.candidatura('c4','p2','e22','123')
        planos = planejar(self.con, ['RN'])
        self.assertEqual([r[3] for r in planos if r[:3] == (2022,'RN','123')], ['p2'])
        self.assertEqual([r[3] for r in planos if r[:3] == (2024,'RN','123')], ['p1'])

    def test_publicacao_incremental_blob_e_idempotente(self):
        z = self.zip([('FRN123_div.jpeg', jpeg())])
        carregar_zip(self.con, z, 2024, 'RN', {'123':'p1'}, 'TSE')
        self.con.execute("ATTACH ':memory:' AS origem")
        self.con.execute('CREATE TABLE origem.main.Foto_Candidato AS SELECT * FROM memory.main.Foto_Candidato')
        self.con.execute('DELETE FROM memory.main.Foto_Candidato')
        self.assertEqual(copiar_fotos(self.con, 'memory'), (1,1))
        self.assertEqual(copiar_fotos(self.con, 'memory'), (0,1))
        self.assertEqual(self.con.execute('SELECT imagem FROM memory.main.Foto_Candidato').fetchone()[0], jpeg())

    def test_url_oficial(self):
        self.assertEqual(url_fotos(2024,'RN'), 'https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2024/fotos/foto_cand2024_RN_div.zip')


if __name__ == '__main__':
    unittest.main()
