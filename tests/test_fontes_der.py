"""Confere os layouts oficiais sem rede nem arquivos de banco: DuckDB em memória."""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from bdr.der.patrimonio import carregar_patrimonio
from bdr.der.q3_bruto import _carregar_votacao_partido
from bdr.der.transformacao import construir
from bdr.esquema import criar_tabelas
from bdr.trajetoria.esquema import criar_tabelas as criar_trajetoria


def escrever(path, colunas, linhas):
    with path.open('w', encoding='utf-8', newline='') as arquivo:
        writer = csv.writer(arquivo, delimiter=';')
        writer.writerow(colunas)
        writer.writerows(linhas)


class FontesDERTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.con = duckdb.connect(':memory:')
        self.addCleanup(self.con.close)

    def votos(self, ano, total=True):
        colunas = ['ANO_ELEICAO', 'NR_TURNO', 'SG_UF', 'CD_ELEICAO',
                   'CD_CARGO', 'DS_CARGO', 'CD_MUNICIPIO', 'NM_MUNICIPIO',
                   'NR_PARTIDO', 'SG_PARTIDO', 'NM_PARTIDO', 'NR_ZONA',
                   'QT_VOTOS_NOMINAIS_VALIDOS', 'QT_VOTOS_LEGENDA_VALIDOS',
                   'QT_VOTOS_NOMINAIS_CONVR_LEG' if ano == 2018 else 'QT_VOTOS_NOM_CONVR_LEG_VALIDOS',
                   'QT_VOTOS_NOMINAIS']
        linhas = [[ano, 1, 'RN', 619, 13, 'Vereador', '17612', 'Natal',
                   13, 'PT', 'Partido', zona, nominais, diretos, convertidos, 999]
                  for zona, nominais, diretos, convertidos in [(1, 3, 1, 3), (2, 5, 2, 4)]]
        if total:
            colunas.append('QT_TOTAL_VOTOS_LEG_VALIDOS')
            for linha, soma in zip(linhas, [4, 6]):
                linha.append(soma)
        arquivo = self.raiz / f'votacao_{ano}.csv'
        escrever(arquivo, colunas, linhas)
        return arquivo

    def test_votos_oficiais_dos_quatro_anos(self):
        criar_tabelas(self.con)
        for ano in (2018, 2020, 2022, 2024):
            _carregar_votacao_partido(self.con, self.votos(ano), ano, ['RN'])
        self.assertEqual(self.con.execute('''SELECT ano, votos_nominais, votos_legenda
            FROM votos_partido_municipio ORDER BY ano''').fetchall(),
            [(ano, 8, 10) for ano in (2018, 2020, 2022, 2024)])

    def test_legenda_sem_coluna_total_soma_convertidos_sem_duplicar(self):
        criar_tabelas(self.con)
        for ano in (2018, 2020, 2022, 2024):
            _carregar_votacao_partido(self.con, self.votos(ano, total=False), ano, ['RN'])
        self.assertEqual(self.con.execute('SELECT sum(votos_legenda) FROM votos_partido_municipio').fetchone(), (40,))

    def test_layout_ausente_votos_invalidos_e_recorte_errado_sao_recusados(self):
        criar_tabelas(self.con)
        arquivo = self.votos(2024)
        with self.assertRaisesRegex(ValueError, 'recorte'):
            _carregar_votacao_partido(self.con, arquivo, 2022, ['RN'])
        texto = arquivo.read_text(encoding='utf-8')
        arquivo.write_text(texto.replace('QT_TOTAL_VOTOS_LEG_VALIDOS', 'SEM_TOTAL')
                           .replace('QT_VOTOS_LEGENDA_VALIDOS', 'SEM_LEGENDA'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'legenda ausente'):
            _carregar_votacao_partido(self.con, arquivo)
        arquivo.write_text(texto.replace(';999;', ';999;invalido'), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'votos inválidos'):
            _carregar_votacao_partido(self.con, arquivo)

    def bens(self):
        self.con.execute('''CREATE TABLE candidatura
            (ano INTEGER, uf VARCHAR, cd_eleicao VARCHAR, sequencial VARCHAR,
             turno INTEGER, patrimonio DOUBLE)''')
        arquivos = {}
        for ano in (2018, 2020, 2022, 2024):
            arquivo = self.raiz / f'bem_candidato_{ano}_RN.csv'
            escrever(arquivo,
                ['ANO_ELEICAO', 'SG_UF', 'CD_ELEICAO', 'SQ_CANDIDATO',
                 'DS_TIPO_BEM_CANDIDATO', 'DS_BEM_CANDIDATO', 'VR_BEM_CANDIDATO',
                 'DT_ULT_ATUAL_BEM_CANDIDATO'],
                [[ano, 'RN', '619', '100', 'Casa', 'Imóvel', '1.234,56', '15/10/2026'],
                 [ano, 'RN', '619', '100', 'Depósito', 'Conta', '50,00', '15/10/2026']])
            arquivos[ano] = [arquivo]
            self.con.execute("INSERT INTO candidatura VALUES (?, 'RN', '619', '100', 1, 999)", [ano])
            self.con.execute("INSERT INTO candidatura VALUES (?, 'RN', '619', '200', 1, 999)", [ano])
        self.con.execute("INSERT INTO candidatura VALUES (2024, 'RN', '620', '100', 2, 999)")
        self.con.execute("INSERT INTO candidatura VALUES (2024, 'RN', '999', '100', 1, 999)")
        return arquivos

    def test_patrimonio_quatro_anos_sem_banco_extra_e_sem_misturar_eleicoes(self):
        arquivos = self.bens()
        with patch('bdr.der.patrimonio.baixar') as baixar, patch(
            'bdr.der.patrimonio.extrair_por_uf',
            side_effect=lambda zip, raw, ano, partes, ufs: (arquivos[ano], [])):
            for _ in range(2):
                carregar_patrimonio(self.con, ['RN'], [2018, 2020, 2022, 2024], self.raiz)
            self.assertEqual(baixar.call_count, 8)
        self.assertEqual(self.con.execute('SELECT count(*) FROM Patrimonio_Candidato').fetchone(), (8,))
        self.assertEqual(self.con.execute('SELECT count(*) FROM Patrimonio_Candidato WHERE data_atualizacao=DATE \'2026-10-15\'').fetchone(), (8,))
        self.assertEqual(self.con.execute("SELECT patrimonio FROM candidatura WHERE sequencial='100' AND cd_eleicao='619' ORDER BY ano").fetchall(), [(1284.56,)] * 4)
        self.assertEqual(self.con.execute("SELECT patrimonio FROM candidatura WHERE turno=2").fetchone(), (1284.56,))
        self.assertEqual(self.con.execute("SELECT count(patrimonio) FROM candidatura WHERE sequencial='200' OR cd_eleicao='999'").fetchone(), (0,))

    def test_patrimonio_incompleto_reverte_tudo(self):
        self.bens()
        with patch('bdr.der.patrimonio.baixar'), patch(
            'bdr.der.patrimonio.extrair_por_uf', return_value=([], [])):
            with self.assertRaisesRegex(ValueError, 'incompletos'):
                carregar_patrimonio(self.con, ['RN'], [2024], self.raiz)
        self.assertEqual(self.con.execute('SELECT min(patrimonio) FROM candidatura').fetchone(), (999.0,))
        self.assertNotIn(('Patrimonio_Candidato',), self.con.execute('SHOW TABLES').fetchall())

    def test_der_final_inclui_bens_totais_e_votos_sem_arquivos_de_banco(self):
        con = self.con
        con.execute("ATTACH ':memory:' AS q3")
        con.execute("USE q3")
        criar_tabelas(con)
        _carregar_votacao_partido(con, self.votos(2024), 2024, ['RN'])
        con.execute("UPDATE municipio SET id_municipio='2408102'")
        con.execute("ATTACH ':memory:' AS q10")
        con.execute("USE q10")
        criar_tabelas(con)
        criar_trajetoria(con)
        con.execute("INSERT INTO candidato (id_candidato, nome) VALUES ('pessoa', 'Maria')")
        con.execute("INSERT INTO cargo (cd_cargo, nome) VALUES ('13', 'Vereador')")
        con.execute("""INSERT INTO candidatura
            (id_candidatura,id_candidato,ano,cd_eleicao,turno,cd_cargo,uf,sequencial,
             numero_partido,sigla_partido,cod_tse_municipio)
            VALUES ('cand','pessoa',2024,'619',1,'13','RN','100',13,'PT','17612')""")
        arquivo = self.raiz / 'bem_candidato_2024_RN.csv'
        escrever(arquivo,
            ['ANO_ELEICAO','SG_UF','CD_ELEICAO','SQ_CANDIDATO','VR_BEM_CANDIDATO'],
            [[2024,'RN','619','100','123,45']])
        with patch('bdr.der.patrimonio.baixar'), patch(
            'bdr.der.patrimonio.extrair_por_uf', return_value=([arquivo], [])):
            carregar_patrimonio(con, ['RN'], [2024], self.raiz)
        con.execute('USE memory')

        class ConexaoEmMemoria:
            def execute(self, sql, *args):
                # As duas origens já foram anexadas em memória acima.
                if sql.startswith('ATTACH '):
                    return con
                return con.execute(sql, *args)

            def close(self):
                pass

        with patch('bdr.der.transformacao.duckdb.connect', return_value=ConexaoEmMemoria()), \
             patch('pathlib.Path.is_file', return_value=True), \
             patch('pathlib.Path.exists', return_value=False), patch('pathlib.Path.mkdir'):
            construir('q3_nao_criado.duckdb', 'q10_nao_criado.duckdb', 'final_nao_criado.duckdb')
        self.assertEqual(con.execute('SELECT patrimonio FROM Candidatura').fetchone(), (123.45,))
        self.assertEqual(con.execute('SELECT valor_bem FROM Patrimonio_Candidato').fetchone(), (123.45,))
        self.assertEqual(con.execute('SELECT votos_nominais, votos_legenda FROM Votos_Partido_Municipio').fetchone(), (8, 10))


if __name__ == '__main__':
    unittest.main()
