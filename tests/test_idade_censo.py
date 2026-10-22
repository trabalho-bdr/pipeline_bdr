"""Valida a média etária sem carregar a DLL do DuckDB ou acessar a rede."""
import unittest

from bdr.der.demografia import indicadores_idade


class IdadeCensoTest(unittest.TestCase):
    def dados(self):
        resultados = []
        for idade in range(101):
            nome = ('Menos de 1 ano' if idade == 0 else
                    '100 anos ou mais' if idade == 100 else f'{idade} anos')
            valor = '2' if idade == 20 else '1' if idade == 100 else '-'
            resultados.append(self.resultado(nome, valor))
        resultados.append(self.resultado('Total', '3'))
        resultados.append(self.resultado('20 a 24 anos', '2'))
        return [{'resultados': resultados}]

    @staticmethod
    def resultado(nome, valor):
        return {'classificacoes': [{'id': '287', 'categoria': {'codigo': nome}}],
                'series': [{'localidade': {'id': '2408102'}, 'serie': {'2022': valor}}]}

    def test_media_ponderada_zero_sidra_e_grupo_aberto(self):
        self.assertAlmostEqual(indicadores_idade(self.dados())['2408102'], 140 / 3)

    def test_total_divergente_e_serie_incompleta_sao_recusados(self):
        dados = self.dados()
        dados[0]['resultados'][-2]['series'][0]['serie']['2022'] = '4'
        with self.assertRaisesRegex(ValueError, 'inconsistente'):
            indicadores_idade(dados)
        dados = self.dados()
        dados[0]['resultados'].pop(0)
        with self.assertRaisesRegex(ValueError, 'incompleto'):
            indicadores_idade(dados)

    def test_dado_suprimido_nao_e_convertido_em_zero(self):
        dados = self.dados()
        dados[0]['resultados'][0]['series'][0]['serie']['2022'] = '..'
        with self.assertRaisesRegex(ValueError, 'ausente'):
            indicadores_idade(dados)

    def test_zero_aos_93_anos_no_municipio_do_erro(self):
        dados = self.dados()
        for resultado in dados[0]['resultados']:
            resultado['series'][0]['localidade']['id'] = '2304269'
        dados[0]['resultados'][93]['series'][0]['serie']['2022'] = ' - '
        self.assertAlmostEqual(indicadores_idade(dados)['2304269'], 140 / 3)


if __name__ == '__main__':
    unittest.main()
