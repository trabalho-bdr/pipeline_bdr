import math
import unittest
from unittest.mock import patch

import duckdb
from fastapi import HTTPException

from frontend import main


class PublicidadeApiTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE Eleicao(id_eleicao VARCHAR,ano INTEGER,cargo VARCHAR)')
        self.con.execute('CREATE TABLE Candidatura(id_candidatura VARCHAR,id_eleicao VARCHAR,uf VARCHAR)')
        self.con.execute('CREATE TABLE Despesa_Candidatura(id_despesa VARCHAR,id_candidatura VARCHAR,categoria VARCHAR,valor DOUBLE)')
        self.con.execute("""INSERT INTO Eleicao VALUES ('e1',2024,'PREFEITO'),('e2',2024,'Prefeito'),
            ('e3',2020,'Prefeito'),('e4',2024,'Vereador'),('e5',2018,'PRESIDENTE')""")
        self.con.execute("""INSERT INTO Candidatura VALUES ('c1','e1','RJ'),('c2','e2','RJ'),
            ('c3','e1','MA'),('c4','e5','SP'),('c5','e3','RJ'),('c6','e4','RJ')""")
        self.con.executemany('INSERT INTO Despesa_Candidatura VALUES (?,?,?,?)', [
            ('d1','c1','Santinhos',100), ('d2','c1','Adesivos',50),
            ('d3','c2','SANTINHO IMPRESSO PARA CAMPANHA',200),
            ('d4','c2','Serviços contábeis',40), ('d5','c2','Facebook',30),
            ('d6','c1','Impulsionamento e santinhos',60), ('d7','c1','Santinhos',-10),
            ('d8','c3','Santinhos',999), ('d9','c4','Santinhos',5000),
            ('d10','c5','Santinhos',77), ('d11','c6','Santinhos',88),
            ('d12','c1','SANTINHO SEM VALOR',None), ('d13','c1','VIDEO SEM VALOR',float('inf')),
        ])
        self.scope = patch.multiple(main, _con=self.con, BANCO=':memory:')
        self.scope.start()
        self.addCleanup(self.scope.stop)
        main._resumo_q9_cache.cache_clear()
        self.addCleanup(main._resumo_q9_cache.cache_clear)

    def test_opcoes_agrupam_caixa_e_excluem_ufs_fora_do_recorte(self):
        opcoes = main.opcoes_q9()['opcoes']
        self.assertEqual(sum(o['ano'] == 2024 and o['cargo'] == 'PREFEITO' for o in opcoes), 1)
        self.assertFalse(any(o['cargo'] == 'PRESIDENTE' for o in opcoes))

    def test_valores_filtros_e_candidaturas_distintas(self):
        result = main.despesas_q9(2024, 'Prefeito', uf='RJ')
        r = result['resumo']
        self.assertEqual((r['publicidade'], r['total_campanha'], r['candidaturas']), (340, 470, 2))
        self.assertEqual((r['indefinido'], r['fora_publicidade'], r['sem_valor']), (90, 40, 2))
        self.assertEqual((r['em_revisao'], r['ajustes_negativos']), (200, 1))
        self.assertAlmostEqual(sum(g['participacao'] for g in result['grupos']), 100)
        self.assertEqual(sum(g['valor'] for g in result['grupos']), r['publicidade'])
        self.assertEqual(sum(c['valor'] for c in result['categorias']), r['publicidade'])
        self.assertGreater(sum(g['candidaturas'] for g in result['grupos']), r['candidaturas'])
        self.assertEqual(main.despesas_q9(2020, 'PREFEITO', uf='RJ')['resumo']['publicidade'], 77)
        self.assertEqual(main.despesas_q9(2024, 'VEREADOR', uf='RJ')['resumo']['publicidade'], 88)

    def test_criterio_explicito_nao_apresenta_toda_publicidade_como_validada(self):
        r = main.despesas_q9(2024, 'PREFEITO', uf='RJ', criterio='explicitas')['resumo']
        self.assertEqual((r['publicidade'], r['total_campanha'], r['excluido_criterio']), (140, 470, 200))
        self.assertEqual(r['em_revisao'], 0)

    def test_todas_ufs_ainda_respeita_as_seis_ufs(self):
        self.assertEqual(main.despesas_q9(2024, 'PREFEITO')['resumo']['publicidade'], 1339)

    def test_recorte_vazio_retorna_zero_sem_nan(self):
        result = main.despesas_q9(2018, 'SENADOR', uf='RJ')
        self.assertEqual(result['grupos'], [])
        self.assertEqual(result['resumo']['publicidade'], 0)
        self.assertTrue(all(math.isfinite(n) for n in result['resumo'].values()))

    def test_parametros_invalidos(self):
        for params in ((2016, 'PREFEITO', None, 'sugeridas'), (2024, '', None, 'sugeridas'),
                       (2024, 'PREFEITO', 'SP', 'sugeridas'), (2024, 'PREFEITO', None, 'outra')):
            with self.subTest(params=params), self.assertRaises(HTTPException) as error:
                main.despesas_q9(params[0], params[1], params[2], params[3])
            self.assertEqual(error.exception.status_code, 422)

    def test_views_existentes_sao_preferidas_sem_reclassificar(self):
        self.con.execute('''CREATE VIEW vw_q9_categorias AS SELECT DISTINCT categoria categoria_original,
            'Categoria do catálogo' categoria_padronizada,'Tipo do catálogo' grupo_despesa,
            TRUE eh_publicidade_sugerida,'ALIAS_EXPLICITO' status_classificacao,FALSE requer_revisao
            FROM Despesa_Candidatura''')
        result = main.despesas_q9(2024, 'PREFEITO', uf='RJ')
        self.assertEqual(result['origem_normalizacao'], 'views_q9')
        self.assertEqual(result['grupos'][0]['grupo'], 'Tipo do catálogo')
        self.assertEqual(result['resumo']['publicidade'], 470)

    def test_dimensao_incompleta_interrompe_sem_omitir_valores_silenciosamente(self):
        self.con.execute('''CREATE VIEW vw_q9_categorias AS SELECT 'Santinhos' categoria_original,
            'Santinhos' categoria_padronizada,'Impressos' grupo_despesa,TRUE eh_publicidade_sugerida,
            'ALIAS_EXPLICITO' status_classificacao,FALSE requer_revisao''')
        with self.assertRaises(HTTPException) as error:
            main.despesas_q9(2024, 'PREFEITO', uf='RJ')
        self.assertEqual(error.exception.status_code, 503)

    def test_nenhum_objeto_ou_registro_da_fonte_e_modificado(self):
        before = self.con.execute('SELECT * FROM Despesa_Candidatura ORDER BY id_despesa').fetchall()
        tables = self.con.execute('SHOW TABLES').fetchall()
        main.despesas_q9(2024, 'PREFEITO', uf='RJ')
        self.assertEqual(before, self.con.execute('SELECT * FROM Despesa_Candidatura ORDER BY id_despesa').fetchall())
        self.assertEqual(tables, self.con.execute('SHOW TABLES').fetchall())

    def test_atualizar_ignora_resultado_anterior_do_cache(self):
        self.assertEqual(main.despesas_q9(2024, 'PREFEITO', uf='RJ')['resumo']['publicidade'], 340)
        self.con.execute("INSERT INTO Despesa_Candidatura VALUES ('novo','c1','Santinhos',10)")
        self.assertEqual(main.despesas_q9(2024, 'PREFEITO', uf='RJ', atualizar=True)['resumo']['publicidade'], 350)


if __name__ == '__main__':
    unittest.main()
