import unittest
from unittest.mock import patch

import duckdb

from bdr.der.esquema import criar
from frontend import main


class ApiMapaTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
