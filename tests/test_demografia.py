import csv
import tempfile
import unittest
from pathlib import Path

import duckdb

from bdr.consultas_apuracao import consulta
from bdr.der.demografia import carregar_perfil, indicadores_idade
from bdr.der.esquema import criar


class DemografiaTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        criar(self.con)
        self.con.execute("INSERT INTO Municipio VALUES ('2408102','17612','Natal','RN','Nordeste')")
        self.con.execute("INSERT INTO Eleicao VALUES ('e',2024,'Municipal',1,'VEREADOR',NULL)")
        self.con.execute("INSERT INTO Partido VALUES ('p','ABC','ABC',10),('q','XYZ','XYZ',20)")
        self.con.execute("INSERT INTO Votos_Partido_Municipio VALUES ('v','e','p','2408102',1,60,20),('w','e','q','2408102',1,10,10)")

    def perfil(self, quantidade='30'):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        arquivo = Path(tmp.name) / 'perfil.csv'
        with arquivo.open('w', encoding='utf-8', newline='') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow(['ANO_ELEICAO','SG_UF','CD_MUNICIPIO','DS_FAIXA_ETARIA',
                        'DS_GENERO','DS_GRAU_ESCOLARIDADE','QT_ELEITORES_PERFIL'])
            w.writerows([[2024,'RN','17612','21 A 24 ANOS','FEMININO','SUPERIOR COMPLETO',quantidade],
                         [2024,'RN','17612','21 A 24 ANOS','FEMININO','SUPERIOR COMPLETO',10],
                         [2024,'RN','17612','25 A 29 ANOS','MASCULINO','ANALFABETO',60]])
        return arquivo

    def test_cruzamento_soma_zonas_sem_multiplicar_votos(self):
        carregar_perfil(self.con, [self.perfil()], 2024, ['RN'], 'TSE')
        self.assertEqual(self.con.execute('SELECT sum(quantidade_eleitores),count(*) FROM Perfil_Eleitorado_Municipio').fetchone(), (100,2))
        d = self.con.execute(consulta('q3_demografia_partidos'), [2024,'RN',1,'VEREADOR']).df()
        self.assertEqual(d.votos.sum(), 100)
        self.assertEqual(d.votos_legenda.sum(), 30)
        self.assertEqual(d.votos_pct.sum(), 100)
        self.assertEqual(set(d.jovens_16_24_pct), {40})
        self.assertEqual(set(d.feminino_pct), {40})
        self.assertEqual(set(d.analfabetos_pct), {60})

    def test_perfil_ausente_nao_vira_zero_e_preserva_votos(self):
        d = self.con.execute(consulta('q3_demografia_partidos'), [2024,'RN',1,'VEREADOR']).df()
        self.assertEqual(d.votos.sum(), 100)
        self.assertTrue(d.jovens_16_24_pct.isna().all())

    def test_quantidade_invalida_interrompe_carga(self):
        with self.assertRaisesRegex(ValueError, 'inválidas'):
            carregar_perfil(self.con, [self.perfil('-1')], 2024, ['RN'], 'TSE')
        self.assertEqual(self.con.execute('SELECT count(*) FROM Perfil_Eleitorado_Municipio').fetchone()[0],0)

    def test_layout_2022_2024_e_substituicao_preservam_totais(self):
        arquivo = self.perfil()
        carregar_perfil(self.con, [arquivo], 2024, ['RN'], 'TSE antigo')
        texto = arquivo.read_text(encoding='utf-8')
        arquivo.write_text(texto.replace('ANO_ELEICAO', 'AA_ELEICAO')
                           .replace('QT_ELEITORES_PERFIL', 'QT_ELEITORES'), encoding='utf-8')
        carregar_perfil(self.con, [arquivo], 2024, ['RN'], 'TSE novo', substituir=True)
        self.assertEqual(self.con.execute('SELECT sum(quantidade_eleitores), count(*) FROM Perfil_Eleitorado_Municipio').fetchone(), (100, 2))

    def test_arquivos_com_layouts_diferentes_no_mesmo_lote(self):
        antigo = self.perfil()
        novo = self.perfil()
        novo.write_text(novo.read_text(encoding='utf-8').replace('ANO_ELEICAO', 'AA_ELEICAO')
                        .replace('QT_ELEITORES_PERFIL', 'QT_ELEITORES'), encoding='utf-8')
        carregar_perfil(self.con, [antigo, novo], 2024, ['RN'], 'TSE')
        self.assertEqual(self.con.execute('SELECT sum(quantidade_eleitores) FROM Perfil_Eleitorado_Municipio').fetchone()[0], 200)

    def test_media_nao_duplica_grupos_e_rejeita_serie_incompleta(self):
        resultados = []
        for idade in [*range(101), 'total', 'grupo']:
            nome = ('Total' if idade=='total' else '0 a 4 anos' if idade=='grupo' else
                    'Menos de 1 ano' if idade==0 else '100 anos ou mais' if idade==100 else f'{idade} anos')
            resultados.append({'classificacoes':[{'id':'287','categoria':{'id':nome}}],
                               'series':[{'localidade':{'id':'2408102'},'serie':{'2022': '101' if idade=='total' else '1'}}]})
        self.assertEqual(indicadores_idade([{'resultados':resultados}]), {'2408102':50})
        with self.assertRaisesRegex(ValueError, 'incompleto'):
            indicadores_idade([{'resultados':resultados[1:]}])


if __name__ == '__main__':
    unittest.main()
