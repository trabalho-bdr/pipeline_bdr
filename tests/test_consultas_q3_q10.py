"""Testes unitários e de integração para comprovar a execução perfeita das consultas das Questões 3 e 10."""
import unittest
import duckdb

from bdr.esquema import criar_tabelas as criar_tabelas_q3
from bdr.consultas import (
    consultar_abstencao_por_idhm,
    consultar_correlacao_socioeconomica,
    consultar_votos_partido_por_desenvolvimento,
    consultar_perfil_partidos_vencedores,
    consultar_matriz_municipios
)
from bdr.trajetoria.esquema import criar_tabelas as criar_tabelas_q10
from bdr.trajetoria.consultas import (
    consultar_padroes_carreira,
    consultar_fidelidade_partidaria,
    consultar_mobilidade_cargos,
    consultar_taxa_reeleicao,
    consultar_linha_tempo_candidato
)


class TestQuestao3(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        criar_tabelas_q3(self.con)
        
        # Popula dados de teste para a Questão 3
        self.con.execute("""
            INSERT INTO municipio VALUES 
                ('00001', '3304557', 'Rio de Janeiro', 'RJ', 'Sudeste'),
                ('00002', '2408102', 'Natal', 'RN', 'Nordeste');
                
            INSERT INTO eleicao VALUES 
                (2022, '1', 1, 'Eleição Geral 2022', '2022-10-02'),
                (2024, '2', 1, 'Eleição Municipal 2024', '2024-10-06');
                
            INSERT INTO partido VALUES 
                (13, 'PT', 'Partido dos Trabalhadores'),
                (22, 'PL', 'Partido Liberal');
                
            INSERT INTO censo_municipio VALUES 
                ('3304557', 2010, NULL, NULL, NULL, 0.799),
                ('3304557', 2022, 6000000, 300000000000.00, 50000.00, NULL),
                ('2408102', 2010, NULL, NULL, NULL, 0.763),
                ('2408102', 2022, 800000, 24000000000.00, 30000.00, NULL);
                
            INSERT INTO participacao_eleitoral VALUES 
                (2022, '1', 1, '00001', '3304557', 100000, 80000, 20000, 0.20),
                (2022, '1', 1, '00002', '2408102', 50000, 40000, 10000, 0.20),
                (2024, '2', 1, '00001', '3304557', 105000, 81000, 24000, 0.2285),
                (2024, '2', 1, '00002', '2408102', 52000, 41000, 11000, 0.2115);
                
            INSERT INTO votos_partido_municipio VALUES 
                (2022, '1', '1', 'PRESIDENTE', 1, 13, 'PT', '00001', '3304557', 45000, 5000),
                (2022, '1', '1', 'PRESIDENTE', 1, 22, 'PL', '00001', '3304557', 30000, 0),
                (2022, '1', '1', 'PRESIDENTE', 1, 13, 'PT', '00002', '2408102', 25000, 2000),
                (2022, '1', '1', 'PRESIDENTE', 1, 22, 'PL', '00002', '2408102', 13000, 0),
                (2024, '2', '11', 'PREFEITO', 1, 13, 'PT', '00001', '3304557', 35000, 0),
                (2024, '2', '11', 'PREFEITO', 1, 22, 'PL', '00001', '3304557', 46000, 0),
                (2024, '2', '11', 'PREFEITO', 1, 13, 'PT', '00002', '2408102', 22000, 0),
                (2024, '2', '11', 'PREFEITO', 1, 22, 'PL', '00002', '2408102', 19000, 0);
        """)

    def tearDown(self):
        self.con.close()

    def test_consultar_abstencao_por_idhm(self):
        df = consultar_abstencao_por_idhm(self.con)
        self.assertFalse(df.empty)
        self.assertIn('faixa_idhm', df.columns)
        self.assertIn('taxa_abstencao_pct', df.columns)
        self.assertEqual(len(df), 2)  # 2022 e 2024

    def test_consultar_correlacao_socioeconomica(self):
        df = consultar_correlacao_socioeconomica(self.con)
        self.assertFalse(df.empty)
        self.assertIn('corr_abstencao_pib_per_capita', df.columns)

    def test_consultar_votos_partido_por_desenvolvimento(self):
        df = consultar_votos_partido_por_desenvolvimento(self.con, 2022, 'PRESIDENTE')
        self.assertFalse(df.empty)
        self.assertIn('pct_dos_votos_no_grupo', df.columns)

    def test_consultar_perfil_partidos_vencedores(self):
        df = consultar_perfil_partidos_vencedores(self.con, 2024, 'PREFEITO')
        self.assertFalse(df.empty)
        self.assertIn('qtd_municipios_vencidos', df.columns)
        self.assertIn('pib_per_capita_medio', df.columns)

    def test_consultar_matriz_municipios(self):
        df = consultar_matriz_municipios(self.con)
        self.assertFalse(df.empty)
        self.assertIn('partido_mais_votado', df.columns)


class TestQuestao10(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect()
        criar_tabelas_q10(self.con)

        # Popula dados de teste para a Questão 10
        self.con.execute("""
            INSERT INTO cargo VALUES 
                ('13', 'Vereador', 'MUNICIPAL', 'LEGISLATIVO', 1),
                ('11', 'Prefeito', 'MUNICIPAL', 'EXECUTIVO', 2),
                ('6', 'Deputado Federal', 'FEDERAL', 'LEGISLATIVO', 4);
                
            INSERT INTO candidato VALUES 
                ('cand_1', 'MARIA DA SILVA', 'MARIA', '1980-01-01', 'FEMININO', 'SUPERIOR', 'ADVOGADO', 'RN', 'CPF', FALSE),
                ('cand_2', 'JOAO DOS SANTOS', 'JOAO', '1975-05-10', 'MASCULINO', 'SUPERIOR', 'MÉDICO', 'RJ', 'CPF', FALSE);
                
            INSERT INTO candidatura VALUES 
                ('cand1_2020', 'cand_1', 2020, '426', 1, '13', 13, 'PT', 'RN', '17612', 13123, 'DEFERIDO', FALSE),
                ('cand1_2024', 'cand_1', 2024, '619', 1, '11', 40, 'PSB', 'RN', '17612', 40, 'DEFERIDO', FALSE),
                ('cand2_2022', 'cand_2', 2022, '545', 1, '6', 22, 'PL', 'RJ', NULL, 2222, 'DEFERIDO', FALSE);
                
            INSERT INTO resultado_candidatura VALUES 
                ('cand1_2020', 500, 15.5, 1, 'ELEITO POR QP', TRUE, FALSE, FALSE),
                ('cand1_2024', 12000, 48.0, 2, 'NÃO ELEITO', FALSE, FALSE, FALSE),
                ('cand2_2022', 80000, 12.0, 1, 'ELEITO POR QP', TRUE, FALSE, FALSE);
        """)

    def tearDown(self):
        self.con.close()

    def test_consultar_padroes_carreira(self):
        df = consultar_padroes_carreira(self.con)
        self.assertFalse(df.empty)
        self.assertIn('padrao_carreira', df.columns)

    def test_consultar_fidelidade_partidaria(self):
        df = consultar_fidelidade_partidaria(self.con)
        self.assertFalse(df.empty)
        self.assertIn('faixa_fidelidade', df.columns)

    def test_consultar_mobilidade_cargos(self):
        df = consultar_mobilidade_cargos(self.con)
        self.assertFalse(df.empty)
        self.assertIn('tipo_mobilidade', df.columns)

    def test_consultar_taxa_reeleicao(self):
        df = consultar_taxa_reeleicao(self.con)
        self.assertFalse(df.empty)
        self.assertIn('taxa_sucesso_reeleicao_pct', df.columns)

    def test_consultar_linha_tempo_candidato(self):
        df = consultar_linha_tempo_candidato(self.con, 'MARIA')
        self.assertFalse(df.empty)
        self.assertEqual(len(df), 2)  # 2020 e 2024
        self.assertIn('nome_urna', df.columns)


if __name__ == '__main__':
    unittest.main()
