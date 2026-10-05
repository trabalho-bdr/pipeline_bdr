import unittest

import duckdb

from bdr.transformacao import SQL_PARTICIPACAO_HIBRIDA


class ParticipacaoHibridaTest(unittest.TestCase):
    def test_completa_eleicao_ausente_sem_duplicar_detalhe(self):
        con = duckdb.connect()
        con.execute("""
            CREATE TABLE participacao_eleitoral (
                ano INTEGER, cd_eleicao VARCHAR, turno SMALLINT,
                cod_tse_municipio VARCHAR, id_municipio VARCHAR,
                eleitorado_apto BIGINT, comparecimento BIGINT,
                abstencoes BIGINT, taxa_abstencao DOUBLE
            );
            CREATE VIEW v_det AS
                SELECT * FROM (VALUES
                    (2022, 2, '547', 'MS1', '1', 100, 80, 20)
                ) t(ano, turno, cd_eleicao, cod_tse_municipio, nr_zona,
                    aptos, comparecimento, abstencoes);
            CREATE VIEW v_bu AS
                SELECT * FROM (VALUES
                    (2022, 2, '545', 'CE1', '1', '1', 90, 70, 20),
                    (2022, 2, '545', 'MS1', '1', '1', 100, 80, 20),
                    (2022, 2, '547', 'MS1', '1', '1', 100, 80, 20)
                ) t(ano, turno, cd_eleicao, cod_tse_municipio, nr_zona,
                    nr_secao, aptos, comparecimento, abstencoes);
        """)

        con.execute(SQL_PARTICIPACAO_HIBRIDA)

        self.assertEqual(
            con.execute("""
                SELECT cd_eleicao, cod_tse_municipio, eleitorado_apto
                FROM participacao_eleitoral ORDER BY 1, 2
            """).fetchall(),
            [('545', 'CE1', 90), ('545', 'MS1', 100), ('547', 'MS1', 100)],
        )


if __name__ == "__main__":
    unittest.main()
