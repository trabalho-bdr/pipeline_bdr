import unittest

import duckdb

from bdr.der.esquema import criar
from bdr.instalar_legenda_views import instalar, schema_der


class LegendaViewsTest(unittest.TestCase):
    def test_views_agregam_ufs_anos_e_excluem_cargos_majoritarios(self):
        con = duckdb.connect(":memory:")
        try:
            criar(con)
            con.execute("""INSERT INTO "Municipio" VALUES
                ('2100055','1','Município MA','MA','Nordeste'),
                ('2300101','2','Município CE','CE','Nordeste')""")
            con.execute("INSERT INTO \"Partido\" VALUES ('p1','PL','Partido Liberal',22)")
            con.execute("""INSERT INTO "Eleicao" VALUES
                ('e22',2022,'Geral',1,'Deputado Federal',NULL),
                ('e24',2024,'Municipal',1,'Vereador',NULL),
                ('eg',2022,'Geral',1,'Governador',NULL)""")
            con.execute("""INSERT INTO "Votos_Partido_Municipio" VALUES
                ('v1','e22','p1','2100055',1,80,20),
                ('v2','e22','p1','2300101',1,50,10),
                ('v3','e24','p1','2100055',1,60,15),
                ('v4','eg','p1','2100055',1,100,0)""")
            self.assertEqual(schema_der(con), "main")
            self.assertEqual(instalar(con), ("main", 3))
            self.assertEqual(instalar(con), ("main", 3))
            self.assertEqual(con.execute('SELECT sum(votos_legenda) FROM vw_legenda_municipio_partido').fetchone()[0], 45)
            self.assertEqual(con.execute("SELECT votos_legenda FROM vw_legenda_evolucao_partido WHERE ano=2022 AND uf IS NULL").fetchone()[0], 30)
            self.assertEqual(con.execute("SELECT votos_legenda FROM vw_legenda_uf_partido WHERE ano=2022 AND uf='MA'").fetchone()[0], 20)
            self.assertEqual(con.execute('SELECT count(*) FROM vw_legenda_municipio_partido WHERE cargo=\'Governador\'').fetchone()[0], 0)
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
