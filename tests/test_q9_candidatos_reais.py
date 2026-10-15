"""Regressões da cópia local v2, somente leitura; ignoradas se ela não existir.

Valores dependem do catálogo sugerido da Q9. Não testam efeito causal.
Rodar: uv run python -m unittest discover -s tests -p 'test_q9_candidatos_reais.py' -v
"""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from frontend import main, q9


BANCO = Path(__file__).resolve().parents[1] / 'dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb'
CASOS = {
    'Darlene': ('ebb6239b2013bc8d5900fc6ad4dbd137', 'RS', (297126.69, 309600.05), (0, 1), 45.71016862687289),
    'Mainardi': ('963f080f7d19f68e6f4a13abe1a04d5d', 'RS', (182467.80, 619524.00), (0, 1), 47.04181724751639),
    'Sarto': ('e5d2a5cd64245d784e23ebe4d647e7f0', 'CE', (5278558.35, 11322449.82), (1, 0), 67.37461739855439),
}


@unittest.skipUnless(BANCO.is_file(), 'Requer a cópia local pipeline_bdr_der_completo_v2.duckdb')
class CandidatosReaisQ9Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = duckdb.connect(str(BANCO), read_only=True)
        cls.scope = patch.multiple(main, _con=cls.con, BANCO=str(BANCO))
        cls.scope.start()
        main._evolucao_q9_cache.cache_clear()
        main._resumo_q9_cache.cache_clear()
        cls.dados = {nome: main.evolucao_q9('PREFEITO', uf, id_candidato=id)
                     for nome, (id, uf, *_) in CASOS.items()}

    @classmethod
    def tearDownClass(cls):
        main._evolucao_q9_cache.cache_clear()
        main._resumo_q9_cache.cache_clear()
        cls.scope.stop()
        cls.con.close()

    def conferir(self, nome):
        identidade, uf, valores, resultados, mudanca = CASOS[nome]
        d = self.dados[nome]
        self.assertEqual(d['entidade']['id_candidato'], identidade)
        self.assertEqual([a['ano'] for a in d['serie']], [2020, 2024])
        for ano, valor, resultado in zip(d['serie'], valores, resultados):
            self.assertEqual(ano['candidaturas'], 1)
            self.assertEqual(ano['resultado']['analisadas'], 1)
            self.assertEqual(ano['resultado']['eleitas'], resultado)
            self.assertAlmostEqual(ano['publicidade'], valor, places=2)
            self.assertAlmostEqual(sum(g['valor'] for g in ano['grupos']), valor, places=2)
            self.assertAlmostEqual(sum(g['participacao'] for g in ano['grupos']), 100)
        c = d['comparacoes'][0]
        self.assertEqual(c['coorte']['pares'], 1)
        self.assertAlmostEqual(c['mudanca_pp'], mudanca)
        self.assertEqual(c['coorte']['novas_vitorias'], int(resultados == (0, 1)))
        self.assertEqual(c['coorte']['vitorias_consecutivas'], 0)
        # Uma pessoa não forma dois grupos de comparação para estimar diferença de taxas.
        self.assertTrue(all(a['diferenca_taxas_pp'] is None for a in c['associacoes']))
        json.dumps(d, allow_nan=False)

    def test_darlene_muda_composicao_com_total_parecido_e_passa_a_eleita(self):
        self.conferir('Darlene')
        a, b = self.dados['Darlene']['serie']
        self.assertEqual((a['partidos'], b['partidos']), (['PT'], ['PT']))
        self.assertAlmostEqual((b['publicidade'] / a['publicidade'] - 1) * 100, 4.197993697569,
                               places=3)
        ga, gb = ({g['grupo']: g for g in x['grupos']} for x in (a, b))
        self.assertAlmostEqual(ga['Produção audiovisual']['valor'], 215000)
        self.assertAlmostEqual(gb['Produção audiovisual']['valor'], 113250)
        self.assertAlmostEqual(ga['Materiais impressos']['valor'], 15735.69)
        self.assertAlmostEqual(gb['Materiais impressos']['valor'], 98631.40)
        self.assertEqual(a['em_revisao'], a['publicidade'])

    def test_mainardi_muda_composicao_e_amplia_total(self):
        self.conferir('Mainardi')

    def test_sarto_muda_composicao_e_perde_sem_contar_segundo_turno_duas_vezes(self):
        self.conferir('Sarto')
        self.assertEqual(self.dados['Sarto']['comparacoes'][0]['coorte']['variacao_taxa_pp'], -100)

    def test_historico_reconcilia_com_painel_anual_e_resultados_brutos(self):
        refs = q9._fontes(main._consultar)
        for nome, (identidade, uf, *_) in CASOS.items():
            for ano in self.dados[nome]['serie']:
                with self.subTest(candidato=nome, ano=ano['ano']):
                    rows = main._consultar(f'''SELECT c.id_candidatura,
                        (SELECT count(*) FROM {refs['despesa_candidatura']} d
                         WHERE d.id_candidatura=c.id_candidatura) despesas
                        FROM {refs['candidatura']} c JOIN {refs['eleicao']} e USING(id_eleicao)
                        WHERE c.id_candidato=? AND e.ano=? AND upper(e.cargo)='PREFEITO' AND c.uf=?''',
                        [identidade, ano['ano'], uf])
                    soma = sum(main.despesas_q9(ano['ano'], 'PREFEITO', uf,
                        id_candidatura=r['id_candidatura'])['resumo']['publicidade'] for r in rows if r['despesas'])
                    self.assertAlmostEqual(soma, ano['publicidade'], places=2)
                    ids = [r['id_candidatura'] for r in rows]
                    brutos = main._consultar(f'''SELECT resultado FROM {refs['resultado_candidatura']}
                        WHERE id_candidatura IN (SELECT unnest(?::VARCHAR[])) ORDER BY turno DESC''', [ids])
                    self.assertEqual(ano['resultados'], [brutos[0]['resultado']])


if __name__ == '__main__':
    unittest.main()
