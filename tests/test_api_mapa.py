import unittest
from unittest.mock import patch

import duckdb

from bdr.der.esquema import criar
from bdr.instalar_legenda_views import instalar
from frontend import main


class ApiMapaTest(unittest.TestCase):
    def test_motherduck_sem_schema_der_bdr_consulta_main(self):
        con = duckdb.connect(":memory:")
        try:
            con.execute("CREATE TABLE Exemplo (valor INTEGER)")
            con.execute("INSERT INTO Exemplo VALUES (7)")
            with patch.multiple(main, _con=con, BANCO="md:teste"):
                self.assertEqual(main._consultar('SELECT valor FROM "Exemplo"'), [{"valor": 7}])
        finally:
            con.close()

    def test_banco_online_quando_nao_ha_arquivo_local(self):
        with patch.dict("os.environ", {"BDR_BANCO": ""}), patch("frontend.main.os.path.isfile", return_value=False):
            self.assertEqual(main._obter_banco_padrao(), "md:pipeline_bdr_der_completo_v3")

    def test_segunda_localizacao_v3_tem_preferencia(self):
        with patch.dict("os.environ", {"BDR_BANCO": ""}), patch("frontend.main.os.path.isfile", side_effect=[False, True]):
            self.assertEqual(main._obter_banco_padrao(), str(main.RAIZ / "pipeline_bdr_der/dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb"))

    def test_banco_local_v3_tem_preferencia(self):
        with patch.dict("os.environ", {"BDR_BANCO": ""}), patch("frontend.main.os.path.isfile", side_effect=[True]):
            self.assertEqual(main._obter_banco_padrao(), str(main.RAIZ / "dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb"))

    def verificar_indicadores(self, motherduck):
        con = duckdb.connect(":memory:")
        try:
            if motherduck:
                # O banco remoto tem tabelas homônimas nos dois schemas.
                con.execute('CREATE TABLE "Participacao_Eleitoral" (ano INTEGER)')
                con.execute('INSERT INTO "Participacao_Eleitoral" VALUES (1998)')
                con.execute("CREATE SCHEMA der_bdr")
                con.execute("SET search_path = 'der_bdr,main'")
            criar(con)
            con.execute('''INSERT INTO "Municipio" VALUES
                ('2100055', '00001', 'Açailândia', 'MA', 'Nordeste')''')
            con.execute('''INSERT INTO "Participacao_Eleitoral" VALUES
                ('pe1', '2100055', 2024, NULL, 1000, 800, 200, 0.20)''')
            con.execute('''INSERT INTO "Censo_Municipio" VALUES
                ('2100055', 2022, 2000, NULL, 6000000, NULL, NULL)''')
            with patch.multiple(main, _con=con, _col_ano=None,
                                BANCO="md:teste" if motherduck else ":memory:"):
                self.assertEqual(main.anos(), {"anos": [2024]})
                dados = main.q3("MA", 2024)
                self.assertEqual(set(dados["municipios"]), {"2100055"})
                registro = dados["municipios"]["2100055"]
                self.assertEqual(registro["abstencao_pct"], 20.0)
                self.assertEqual(registro["pib_per_capita"], 3000.0)
        finally:
            con.close()

    def test_motherduck_consulta_der_mesmo_com_tabela_legada_em_main(self):
        self.verificar_indicadores(motherduck=True)

    def test_banco_local_consulta_main(self):
        self.verificar_indicadores(motherduck=False)

    def test_votos_legenda_por_municipio_e_partido(self):
        con = duckdb.connect(":memory:")
        try:
            criar(con)
            con.execute("INSERT INTO \"Municipio\" VALUES ('2100055', '00001', 'Açailândia', 'MA', 'Nordeste')")
            con.execute("INSERT INTO \"Partido\" VALUES ('p1', 'PL', 'Partido Liberal', 22)")
            con.execute("INSERT INTO \"Eleicao\" VALUES ('e1', 2022, 'Geral', 1, 'Deputado Federal', NULL)")
            con.execute("INSERT INTO \"Eleicao\" VALUES ('e2', 2022, 'Geral', 2, 'Deputado Federal', NULL)")
            con.execute("INSERT INTO \"Votos_Partido_Municipio\" VALUES ('v1', 'e1', 'p1', '2100055', 1, 80, 20)")
            con.execute("INSERT INTO \"Votos_Partido_Municipio\" VALUES ('v2', 'e2', 'p1', '2100055', 1, 900, 100)")
            with patch.multiple(main, _con=con, BANCO=":memory:"):
                self.assertIn({"ano": 2022, "cargo": "Deputado Federal"}, main.opcoes_legenda()["opcoes"])
                linhas = main.votos_legenda("MA", 2022, "Deputado Federal")["linhas"]
                self.assertEqual(len(linhas), 1)
                self.assertEqual((linhas[0]["votos_legenda"], linhas[0]["votos_nominais"]), (20, 80))
                instalar(con)
                self.assertEqual(main.votos_legenda("MA", 2022, "Deputado Federal")["linhas"], linhas)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
