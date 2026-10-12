import unittest

import duckdb

from bdr.consultas_apuracao import carregar_consultas, consulta
from bdr.der.esquema import criar


class ConsultasApuracaoTest(unittest.TestCase):
    def setUp(self):
        self.con = duckdb.connect(":memory:")
        criar(self.con)
        self.con.execute("""INSERT INTO "Municipio" VALUES
            ('m1','00001','Município Pequeno','RJ','Sudeste'),
            ('m2','00002','Município Grande','RJ','Sudeste')""")
        self.con.execute("""INSERT INTO "Partido" VALUES
            ('p1','ABC','Partido ABC',10), ('p2','XYZ','Partido XYZ',20)""")
        self.con.execute("""INSERT INTO "Eleicao" VALUES
            ('e1',2024,'Municipal',1,'PREFEITO',DATE '2024-10-06'),
            ('e2',2022,'Geral',1,'DEPUTADO FEDERAL',DATE '2022-10-02')""")
        self.con.execute("""INSERT INTO "Candidato" VALUES
            ('cand1','titulo1','Nome Civil',DATE '1980-01-01','M','Parda','Professor')""")
        self.con.execute("""INSERT INTO "Censo_Municipio" VALUES
            ('m1',2022,50000,NULL,500000000,NULL,NULL),
            ('m1',2010,NULL,0.650,NULL,NULL,NULL),
            ('m2',2022,200000,NULL,6000000000,NULL,NULL),
            ('m2',2010,NULL,0.800,NULL,NULL,NULL)""")
        self.con.execute("""INSERT INTO "Participacao_Eleitoral" VALUES
            ('pe1','m1',2024,NULL,40000,32000,8000,0.20),
            ('pe2','m2',2024,NULL,160000,144000,16000,0.10)""")
        self.con.execute("""INSERT INTO "Candidatura" VALUES
            ('ca1','e1','cand1','m1','p1','RJ','NOME DE URNA PROIBIDO',10,44,
             'APTO','seq1','SUPERIOR',NULL,NULL),
            ('ca2','e2','cand1',NULL,'p2','MS','OUTRO NOME DE URNA',20,42,
             'APTO','seq2','SUPERIOR',NULL,NULL)""")
        self.con.execute("""INSERT INTO "Resultado_Candidatura" VALUES
            ('r1','ca1',1,'ELEITO POR QP',12345),
            ('r2','ca2',1,'NÃO ELEITO',2345)""")
        self.con.execute("""INSERT INTO "Cargo" VALUES
            ('cg1','PREFEITO','ca1'), ('cg2','DEPUTADO FEDERAL','ca2')""")
        self.con.execute("""INSERT INTO "Votos_Partido_Municipio" VALUES
            ('v1','e1','p1','m1',1,10000,1000),
            ('v2','e1','p2','m2',1,20000,2000)""")

    def tearDown(self):
        self.con.close()

    def test_arquivo_contem_as_quatro_consultas(self):
        self.assertEqual(
            set(carregar_consultas()),
            {"q3_municipios", "q3_cargos", "q3_votos_por_perfil", "q10_trajetorias"},
        )

    def test_q3_reune_indicadores_perfis_abstencao_e_votos(self):
        municipios = self.con.execute(consulta("q3_municipios"), [2024, "RJ"]).df()
        self.assertEqual(set(municipios["perfil_renda"]), {"Mais rico", "Mais pobre"})
        self.assertEqual(set(municipios["perfil_porte"]), {"Pequeno (<100 mil)", "Grande (>=100 mil)"})
        self.assertEqual(set(municipios["abstencao_pct"]), {10.0, 20.0})
        self.assertEqual(set(municipios["idhm"]), {0.65, 0.8})

        cargos = self.con.execute(consulta("q3_cargos"), ["RJ", 2024, 1]).fetchall()
        self.assertEqual(cargos, [("PREFEITO",)])

        votos = self.con.execute(
            consulta("q3_votos_por_perfil"), [2024, "RJ", 1, "PREFEITO"]
        ).df()
        self.assertEqual(votos["votos"].sum(), 33000)
        self.assertEqual(set(votos["partido"]), {"ABC", "XYZ"})

    def test_q10_usa_id_nome_civil_e_traz_trajetoria_completa(self):
        sql = consulta("q10_trajetorias")
        self.assertNotIn("nome_urna", sql.lower())
        trajetoria = self.con.execute(sql, ["RJ"]).df()
        self.assertEqual(len(trajetoria), 2)
        self.assertEqual(set(trajetoria["uf"]), {"RJ", "MS"})
        linha = trajetoria[trajetoria["uf"] == "RJ"].iloc[0]
        self.assertEqual(linha["id_candidato"], "cand1")
        self.assertEqual(linha["nome_civil"], "Nome Civil")
        self.assertEqual(linha["municipio"], "Município Pequeno")
        self.assertEqual(linha["uf"], "RJ")
        self.assertEqual(linha["votos"], 12345)
        self.assertEqual(linha["resultado"], "ELEITO POR QP")
        self.assertTrue(linha["eleito"])
        self.assertNotIn("NOME DE URNA PROIBIDO", trajetoria.to_string())
        self.assertNotIn("OUTRO NOME DE URNA", trajetoria.to_string())


if __name__ == "__main__":
    unittest.main()
