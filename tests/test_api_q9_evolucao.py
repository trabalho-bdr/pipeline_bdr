import json
import unittest
from unittest.mock import patch

import duckdb
from fastapi import HTTPException

from frontend import main


class EvolucaoPublicidadeTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE Eleicao(id_eleicao VARCHAR, ano INTEGER, cargo VARCHAR)')
        self.con.execute('CREATE TABLE Candidato(id_candidato VARCHAR, nome_civil VARCHAR)')
        self.con.execute('CREATE TABLE Partido(id_partido VARCHAR, sigla VARCHAR, nome VARCHAR)')
        self.con.execute('''CREATE TABLE Candidatura(id_candidatura VARCHAR,id_candidato VARCHAR,
            id_eleicao VARCHAR,id_partido VARCHAR,uf VARCHAR,id_municipio VARCHAR)''')
        self.con.execute('CREATE TABLE Despesa_Candidatura(id_despesa VARCHAR,id_candidatura VARCHAR,categoria VARCHAR,valor DOUBLE)')
        self.con.execute('CREATE TABLE Resultado_Candidatura(id_candidatura VARCHAR,turno INTEGER,resultado VARCHAR)')
        self.con.execute("INSERT INTO Eleicao VALUES ('e20',2020,'PREFEITO'),('e24',2024,'Prefeito'),('v24',2024,'VEREADOR')")
        self.con.execute("INSERT INTO Partido VALUES ('p','ABC','Partido ABC'),('q','XYZ','Partido XYZ')")
        self.con.executemany('INSERT INTO Candidato VALUES (?,?)', [(x, f'Pessoa {x}') for x in 'abcde'])
        for ano, pessoa, partido in ((20,'a','p'),(24,'a','p'),(20,'b','p'),(24,'b','p'),
                                      (20,'c','p'),(24,'c','q'),(24,'d','p'),(24,'e','p')):
            cid = f'{pessoa}{ano}'
            self.con.execute("INSERT INTO Candidatura VALUES (?,?,?,?, 'RJ','m1')", [cid,pessoa,f'e{ano}',partido])
            resultado = 'ELEITO' if pessoa in ('a','d') or (pessoa == 'c' and ano == 20) else 'NÃO ELEITO'
            if pessoa == 'e':
                resultado = '#NULO'
            self.con.execute('INSERT INTO Resultado_Candidatura VALUES (?,2,?)', [cid,resultado])
            if pessoa != 'd':
                categoria = 'Bandeiras' if pessoa == 'b' or ano == 24 and pessoa in ('a','c') else 'Santinhos'
                valor = 50 if pessoa == 'c' else 40 if pessoa == 'e' else 100
                self.con.execute('INSERT INTO Despesa_Candidatura VALUES (?,?,?,?)', [cid,cid,categoria,valor])
        self.con.execute("INSERT INTO Resultado_Candidatura VALUES ('a20',1,'2º TURNO'),('a24',1,'NÃO ELEITO')")
        # Nenhuma dessas linhas deve afetar o recorte de prefeito nas seis UFs.
        self.con.execute("INSERT INTO Candidatura VALUES ('sp','a','e24','p','SP','m2'),('vereador','a','v24','p','RJ','m1')")
        self.con.execute("INSERT INTO Despesa_Candidatura VALUES ('sp','sp','Bandeiras',9000),('v','vereador','Bandeiras',9000)")
        self.scope = patch.multiple(main, _con=self.con, BANCO=':memory:')
        self.scope.start()
        self.addCleanup(self.scope.stop)
        main._evolucao_q9_cache.cache_clear()
        self.addCleanup(main._evolucao_q9_cache.cache_clear)

    def resumo(self, **kwargs):
        return main.evolucao_q9('Prefeito', 'RJ', **kwargs)

    def test_taxas_incluem_sem_despesas_excluem_indefinidos_e_nao_multiplicam_por_turnos(self):
        d = self.resumo(id_partido='p')
        a, b = d['serie']
        self.assertEqual((a['ano'], a['publicidade'], a['candidaturas']), (2020,250,3))
        self.assertEqual((b['ano'], b['publicidade'], b['candidaturas']), (2024,240,4))
        self.assertEqual((b['resultado']['analisadas'],b['resultado']['eleitas'],b['sem_resultado']), (3,2,1))
        self.assertEqual((b['com_despesas'],b['com_perfil']), (3,3))
        self.assertAlmostEqual(b['resultado']['taxa'], 200/3)
        self.assertAlmostEqual(sum(g['participacao'] for g in a['grupos']), 100)
        self.assertAlmostEqual(d['comparacoes'][0]['mudanca_pp'], 100 * (200/240 - 100/250))

    def test_coorte_mesmas_pessoas_partido_territorio_e_analise_por_categoria(self):
        c = self.resumo(id_partido='p')['comparacoes'][0]
        self.assertEqual((c['candidatos_repetidos'],c['perfis_comparaveis'],c['coorte']['pares']), (2,2,2))
        self.assertEqual((c['coorte']['antes']['taxa'],c['coorte']['depois']['taxa']), (50,50))
        self.assertEqual(c['coorte']['vitorias_consecutivas'], 1)
        self.assertEqual(c['faixas'][0]['pares'], 1)
        self.assertEqual(c['faixas'][2]['pares'], 1)
        linha = next(x for x in c['associacoes'] if x['ampliaram']['pares'])
        self.assertEqual((linha['ampliaram']['pares'],linha['outros']['pares'],linha['diferenca_taxas_pp']), (1,1,100))
        self.assertEqual(linha['ampliaram']['vitorias_consecutivas'], 1)

    def test_candidato_segue_identidade_quando_troca_partido(self):
        d = self.resumo(id_candidato='c')
        self.assertEqual([a['partidos'] for a in d['serie']], [['ABC'],['XYZ']])
        self.assertEqual(d['comparacoes'][0]['coorte']['pares'], 1)
        self.assertEqual(d['comparacoes'][0]['coorte']['variacao_taxa_pp'], -100)
        self.assertEqual(d['comparacoes'][0]['coorte']['vitorias_consecutivas'], 0)
        self.assertEqual(d['entidade'], {'id_candidato':'c','nome_civil':'Pessoa c'})

    def test_mudanca_de_municipio_e_identidade_ambigua_nao_formam_par(self):
        self.con.execute("UPDATE Candidatura SET id_municipio='m2' WHERE id_candidatura='a24'")
        d = self.resumo(id_candidato='a')
        self.assertEqual(d['comparacoes'][0]['candidatos_repetidos'], 0)
        self.assertIsNone(d['comparacoes'][0]['coorte']['depois']['taxa'])

    def test_ausencia_de_participacao_nao_vira_derrota_ou_zero_percentual(self):
        d = self.resumo(id_candidato='d')
        self.assertEqual(d['serie'][0]['candidaturas'], 0)
        self.assertIsNone(d['serie'][0]['resultado']['taxa'])
        self.assertEqual(d['serie'][1]['resultado']['taxa'], 100)
        self.assertEqual(d['serie'][1]['com_perfil'], 0)
        self.assertIsNone(d['comparacoes'][0]['mudanca_pp'])
        json.dumps(d, allow_nan=False)

    def test_saldos_negativos_preservados_sem_percentuais_invalidos(self):
        self.con.execute("INSERT INTO Despesa_Candidatura VALUES ('ajuste','a24','Santinhos',-10)")
        d = self.resumo(id_candidato='a')
        self.assertEqual(d['serie'][1]['publicidade'], 90)
        self.assertTrue(all(g['participacao'] is None for g in d['serie'][1]['grupos']))
        self.assertEqual(d['comparacoes'][0]['perfis_comparaveis'], 0)

    def test_ultimo_turno_conflitante_nao_e_contado_como_sucesso(self):
        self.con.execute("INSERT INTO Resultado_Candidatura VALUES ('a24',2,'NÃO ELEITO')")
        d = self.resumo(id_candidato='a')
        self.assertEqual(d['serie'][1]['sem_resultado'], 1)
        self.assertEqual(d['serie'][1]['publicidade'], 100)

    def test_novas_vitorias_e_criterio_conservador(self):
        self.con.execute("UPDATE Resultado_Candidatura SET resultado='ELEITO POR QP' WHERE id_candidatura='b24'")
        d = self.resumo(id_candidato='b', criterio='explicitas')
        self.assertEqual(d['comparacoes'][0]['coorte']['novas_vitorias'], 1)
        self.assertEqual(d['comparacoes'][0]['coorte']['vitorias_consecutivas'], 0)
        self.assertEqual(d['comparacoes'][0]['mudanca_pp'], 0)

    def test_cache_separa_partido_candidato_e_atualizacao(self):
        self.assertEqual(self.resumo(id_candidato='a')['serie'][1]['publicidade'], 100)
        self.assertEqual(self.resumo(id_partido='p')['serie'][1]['publicidade'], 240)
        self.con.execute("UPDATE Despesa_Candidatura SET valor=200 WHERE id_despesa='a24'")
        self.assertEqual(self.resumo(id_candidato='a')['serie'][1]['publicidade'], 100)
        self.assertEqual(self.resumo(id_candidato='a',atualizar=True)['serie'][1]['publicidade'], 200)

    def test_segundo_turno_em_outra_candidatura_reune_gastos_e_resultado_final(self):
        self.con.execute("UPDATE Resultado_Candidatura SET resultado='2º TURNO',turno=1 WHERE id_candidatura='a20'")
        self.con.execute("INSERT INTO Candidatura VALUES ('a20segundo','a','e20','p','RJ','m1')")
        self.con.execute("INSERT INTO Resultado_Candidatura VALUES ('a20segundo',2,'ELEITO')")
        self.con.execute("INSERT INTO Despesa_Candidatura VALUES ('adicional','a20segundo','Santinhos',50)")
        d = self.resumo(id_candidato='a')
        self.assertEqual(d['serie'][0]['candidaturas'],1)
        self.assertEqual(d['serie'][0]['publicidade'],150)
        self.assertEqual(d['serie'][0]['resultado']['taxa'],100)
        self.assertEqual(d['serie'][0]['sem_resultado'],0)
        self.assertEqual(d['comparacoes'][0]['coorte']['pares'],1)
        self.assertEqual(d['comparacoes'][0]['coorte']['vitorias_consecutivas'],1)

    def test_validacao_e_lista_de_partidos(self):
        self.assertEqual([p['sigla'] for p in main.partidos_q9('Prefeito','RJ')['partidos']], ['ABC','XYZ'])
        for params in ({}, {'id_partido':'p','id_candidato':'a'}, {'id_partido':'p','criterio':'outro'}):
            with self.subTest(params=params), self.assertRaises(HTTPException) as erro:
                self.resumo(**params)
            self.assertEqual(erro.exception.status_code,422)
        with self.assertRaises(HTTPException) as erro:
            self.resumo(id_partido="' OR 1=1 --")
        self.assertEqual(erro.exception.status_code,404)
        with self.assertRaises(HTTPException):
            main.evolucao_q9('VICE-PREFEITO',id_partido='p')


if __name__ == '__main__':
    unittest.main()
