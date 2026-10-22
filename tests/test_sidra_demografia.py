import unittest
from unittest.mock import patch

from bdr.der.demografia import _converter_idades_sidra, _medias_sidra, indicadores_idade


class SidraDemografiaTest(unittest.TestCase):
    def resposta(self):
        linhas = [{'D1C': 'Município (Código)'}]
        for idade in [*range(101), 'total']:
            nome = ('Total' if idade == 'total' else 'Menos de 1 ano' if idade == 0
                    else '100 anos ou mais' if idade == 100 else f'{idade} anos')
            linhas.append({'NC': '6', 'D1C': '4314902', 'D2C': '93', 'D3C': '2022',
                           'D4C': '6794', 'D5C': str(idade), 'D5N': nome,
                           'D6C': '113635', 'V': '101' if idade == 'total' else '1'})
        return linhas

    def test_conversao_preserva_media_e_total(self):
        dados = _converter_idades_sidra(self.resposta(), {'4314902'})
        self.assertEqual(indicadores_idade(dados), {'4314902': 50})

    def test_recorte_errado_e_rejeitado(self):
        for campo, valor in [('D3C', '2010'), ('D4C', '4'), ('D2C', '1000093')]:
            dados = self.resposta()
            dados[1][campo] = valor
            with self.subTest(campo=campo), self.assertRaisesRegex(ValueError, 'fora do recorte'):
                _converter_idades_sidra(dados, {'4314902'})

    @patch('bdr.der.demografia._fonte_opcional')
    def test_consulta_mantem_ano_idades_e_totais(self, fonte):
        fonte.return_value = self.resposta()
        medias = _medias_sidra('RS', ['4314902'], ['total', '0', '1'], 'cache', [])
        self.assertEqual(medias, {'4314902': 50})
        url = fonte.call_args.args[1]
        self.assertIn('https://apisidra.ibge.gov.br/values/t/9514/n6/4314902', url)
        self.assertIn('/v/93/p/2022/c2/6794/', url)

    @patch('bdr.der.demografia._fonte_opcional', return_value=None)
    def test_indisponivel_nao_inventa_medias(self, fonte):
        self.assertEqual(_medias_sidra('RS', ['4314902'], ['1'], 'cache', []), {})


if __name__ == '__main__':
    unittest.main()
