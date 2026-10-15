import unittest
from unittest.mock import patch

import duckdb
from fastapi import HTTPException

from frontend import main

MUN_A, MUN_B, MUN_CE = '2400109', '2400208', '2300101'


class PatrimonioApiTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        self.con.execute('CREATE TABLE Eleicao(id_eleicao VARCHAR, ano INTEGER)')
        self.con.execute('CREATE TABLE Municipio(id_municipio VARCHAR, nome VARCHAR)')
        self.con.execute('CREATE TABLE Candidatura(id_candidatura VARCHAR, id_eleicao VARCHAR, id_municipio VARCHAR, uf VARCHAR, patrimonio DOUBLE)')
        self.con.execute('CREATE TABLE Cargo(id_candidatura VARCHAR, nome VARCHAR)')
        self.con.execute('CREATE TABLE Resultado_Candidatura(id_candidatura VARCHAR, turno SMALLINT, resultado VARCHAR)')
        self.con.executemany('INSERT INTO Eleicao VALUES (?,?)', [('e2020', 2020), ('e2022', 2022), ('e2024', 2024)])
        self.con.executemany('INSERT INTO Municipio VALUES (?,?)', [(MUN_A, 'ACARI'), (MUN_B, 'ASSÚ'), (MUN_CE, 'ABAIARA')])
        # (id, eleição, município, uf, patrimônio, cargo, [(turno, resultado)])
        casos = [
            ('c1', 'e2024', MUN_A, 'RN', 100, 'VEREADOR', [(1, 'ELEITO POR QP')]),
            ('c2', 'e2024', MUN_A, 'RN', 200, 'VEREADOR', [(1, 'ELEITO POR MÉDIA')]),
            ('c3', 'e2024', MUN_A, 'RN', 50, 'VEREADOR', [(1, 'NÃO ELEITO')]),
            ('c4', 'e2024', MUN_B, 'RN', 10, 'VEREADOR', [(1, 'SUPLENTE')]),
            ('c5', 'e2024', MUN_B, 'RN', 999, 'VEREADOR', [(1, '#NULO')]),         # excluído: resultado indefinido
            ('c6', 'e2024', MUN_B, 'RN', 888, 'VEREADOR', [(1, '2º TURNO')]),      # excluído: resultado indefinido
            ('c7', 'e2024', MUN_B, 'RN', None, 'VEREADOR', [(1, 'ELEITO')]),       # sem patrimônio
            ('c8', 'e2024', MUN_B, 'RN', -5, 'VEREADOR', [(1, 'ELEITO')]),         # patrimônio negativo
            ('c9', 'e2024', MUN_A, 'RN', 300, 'PREFEITO', [(1, '2º TURNO'), (2, 'ELEITO')]),
            ('c10', 'e2024', MUN_A, 'RN', 40, 'PREFEITO', [(1, '2º TURNO'), (2, 'NÃO ELEITO')]),
            ('c11', 'e2024', MUN_CE, 'CE', 70, 'Vereador', [(1, 'NÃO ELEITO')]),    # cargo em outra caixa
            ('c12', 'e2024', MUN_A, 'RN', 500, 'VICE-PREFEITO', [(1, 'ELEITO')]),  # fora do recorte
            ('c13', 'e2020', MUN_A, 'RN', 500, 'VEREADOR', [(1, 'ELEITO')]),       # outro ano
            ('c14', 'e2022', None, 'RN', 1000, 'DEPUTADO FEDERAL', [(1, 'ELEITO')]),    # cargo estadual: sem município
            ('c15', 'e2022', None, 'RN', 100, 'DEPUTADO FEDERAL', [(1, 'NÃO ELEITO')]),
        ]
        for cid, ele, mun, uf, pat, cargo, resultados in casos:
            self.con.execute('INSERT INTO Candidatura VALUES (?,?,?,?,?)', [cid, ele, mun, uf, pat])
            self.con.execute('INSERT INTO Cargo VALUES (?,?)', [cid, cargo])
            for turno, res in resultados:
                self.con.execute('INSERT INTO Resultado_Candidatura VALUES (?,?,?)', [cid, turno, res])
        escopo = patch.multiple(main, _con=self.con, BANCO=':memory:')
        escopo.start()
        self.addCleanup(escopo.stop)
        for cache in (main._resumo_q2_cache, main._municipios_q2_cache):
            cache.cache_clear()
            self.addCleanup(cache.cache_clear)

    def situacao(self, dados, nome):
        return next(s for s in dados['resumo_situacao'] if s['situacao'] == nome)

    # ---------- opções e filtros ----------
    def test_opcoes_listam_pares_ano_cargo_existentes_sem_vices(self):
        d = main.opcoes_q2()
        self.assertEqual([(o['ano'], o['cargo']) for o in d['opcoes']], [
            (2024, 'PREFEITO'), (2024, 'VEREADOR'), (2022, 'DEPUTADO FEDERAL'), (2020, 'VEREADOR')])
        self.assertEqual(d['anos'], [2018, 2020, 2022, 2024])

    def test_filtros_invalidos_sao_recusados(self):
        for kwargs in ({'uf': 'SP'}, {'cargo': 'VICE-PREFEITO'}, {'ano': 2016}, {'municipio': '12'}):
            for rota in (main.patrimonio_q2, main.municipios_q2):
                if rota is main.municipios_q2 and 'municipio' in kwargs:
                    continue
                with self.subTest(rota=rota.__name__, **kwargs), self.assertRaises(HTTPException) as erro:
                    rota(**kwargs)
                self.assertEqual(erro.exception.status_code, 422)

    def test_ano_filtra_a_eleicao(self):
        d = main.patrimonio_q2(ano=2020, cargo='VEREADOR')
        self.assertEqual(self.situacao(d, 'eleito')['candidaturas'], 1)   # só c13
        self.assertEqual(d['cobertura']['total'], 1)

    # ---------- regras de classificação ----------
    def test_sucesso_nao_confunde_nao_eleito_e_suplente_conta_como_insucesso(self):
        d = main.patrimonio_q2(ano=2024, cargo='VEREADOR', uf='RN')
        eleito, nao = self.situacao(d, 'eleito'), self.situacao(d, 'nao_eleito')
        self.assertEqual((eleito['candidaturas'], eleito['patrimonio_mediano']), (2, 150))
        self.assertEqual((nao['candidaturas'], nao['patrimonio_mediano']), (2, 30))   # NÃO ELEITO + SUPLENTE

    def test_resultado_indefinido_e_patrimonio_invalido_ficam_fora_e_sao_contados(self):
        c = main.patrimonio_q2(ano=2024, cargo='VEREADOR', uf='RN')['cobertura']
        self.assertEqual((c['total'], c['validos'], c['negativos'], c['sem_resultado_definido']), (8, 6, 1, 2))
        self.assertAlmostEqual(c['cobertura_pct'], 75.0)

    def test_candidatura_com_dois_turnos_conta_uma_vez_pelo_ultimo(self):
        d = main.patrimonio_q2(ano=2024, cargo='PREFEITO', uf='RN')
        self.assertEqual(self.situacao(d, 'eleito')['candidaturas'], 1)
        self.assertEqual(self.situacao(d, 'nao_eleito')['candidaturas'], 1)
        self.assertEqual(d['cobertura']['sem_resultado_definido'], 0)

    def test_cargo_e_comparado_sem_diferenciar_caixa(self):
        d = main.patrimonio_q2(ano=2024, cargo='vereador')
        self.assertEqual(d['cargo'], 'VEREADOR')
        self.assertEqual(self.situacao(d, 'nao_eleito')['candidaturas'], 3)   # inclui c11 (CE)

    def test_decis_somam_as_candidaturas_analisadas_e_correlacao_e_positiva(self):
        d = main.patrimonio_q2(ano=2024, cargo='VEREADOR', uf='RN')
        self.assertEqual(sum(x['candidaturas'] for x in d['decis']), 4)
        self.assertEqual(sum(x['eleitos'] for x in d['decis']), 2)
        self.assertGreater(d['correlacao']['linear'], 0)

    def test_sem_patrimonio_no_banco_nao_quebra_e_informa_cobertura_zero(self):
        self.con.execute('UPDATE Candidatura SET patrimonio = NULL')
        d = main.patrimonio_q2(ano=2024, cargo='VEREADOR')
        self.assertEqual((d['decis'], d['resumo_situacao']), ([], []))
        self.assertEqual(d['cobertura']['validos'], 0)
        self.assertEqual(d['cobertura']['cobertura_pct'], 0.0)

    # ---------- município ----------
    def test_resumo_por_municipio(self):
        d = main.patrimonio_q2(ano=2024, cargo='VEREADOR', municipio=MUN_A)
        self.assertEqual(self.situacao(d, 'eleito')['candidaturas'], 2)
        self.assertEqual(self.situacao(d, 'nao_eleito')['candidaturas'], 1)

    def test_municipios_devolve_uma_linha_por_municipio_com_medianas_por_situacao(self):
        d = main.municipios_q2(ano=2024, cargo='VEREADOR')
        self.assertTrue(d['tem_municipio'])
        por_id = {m['id_municipio']: m for m in d['municipios']}
        a, b = por_id[MUN_A], por_id[MUN_B]
        self.assertEqual((a['municipio'], a['analisadas'], a['eleitos']), ('ACARI', 3, 2))
        self.assertEqual((a['patrimonio_mediano'], a['patrimonio_mediano_eleitos'], a['patrimonio_mediano_nao_eleitos']), (100, 150, 50))
        self.assertAlmostEqual(a['taxa_sucesso_pct'], 200 / 3)
        self.assertEqual((b['candidaturas'], b['analisadas'], b['eleitos']), (5, 1, 0))
        self.assertIsNone(b['patrimonio_mediano_eleitos'])
        self.assertEqual({u['uf'] for u in d['ufs']}, {'RN', 'CE'})

    def test_cargo_estadual_nao_tem_municipio_so_uf(self):
        d = main.municipios_q2(ano=2022, cargo='DEPUTADO FEDERAL')
        self.assertFalse(d['tem_municipio'])
        self.assertEqual(d['municipios'], [])
        rn = d['ufs'][0]
        self.assertEqual((rn['uf'], rn['analisadas'], rn['eleitos']), ('RN', 2, 1))

    def test_filtro_de_municipio_exclui_cargos_estaduais(self):
        d = main.patrimonio_q2(ano=2022, cargo='DEPUTADO FEDERAL', municipio=MUN_A)
        self.assertEqual(d['cobertura']['total'], 0)


if __name__ == '__main__':
    unittest.main()
