import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from bdr.der.q10_bruto import retomar
from bdr.leitura import ALIASES


class RetomadaQ10Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.banco = Path(self.tmp.name) / "q10.duckdb"
        with duckdb.connect(str(self.banco)) as con:
            cols = ', '.join(f'{col} VARCHAR' for col in ALIASES['consulta_cand'])
            con.execute(f"CREATE TABLE stg_consulta_cand ({cols})")
            con.execute("""INSERT INTO stg_consulta_cand
                (ano, turno, uf, cd_eleicao, sequencial, nome_civil, cd_cargo, sg_ue)
                VALUES ('2024', '1', 'RN', '619', '100', 'MARIA', '13', '17612')""")
            con.execute("""CREATE TABLE stg_votos AS SELECT
                '2024' ANO_ELEICAO, '1' NR_TURNO, 'RN' SG_UF, '619' CD_ELEICAO,
                '17612' SG_UE, '100' SQ_CANDIDATO, '13' CD_CARGO, '50' QT_VOTOS_NOMINAIS""")
            con.execute("""CREATE TABLE stg_despesas AS SELECT
                '2024' ANO_ELEICAO, 'RN' SG_UF, '619' CD_ELEICAO,
                '100' SQ_CANDIDATO, 'Publicidade' DS_TIPO_DESPESA,
                '25,00' VR_DESPESA_CONTRATADA""")
            con.execute("CREATE TABLE stg_tipo_eleicao (ano INTEGER)")

    def test_retoma_duas_vezes_sem_download_e_preserva_staging(self):
        with patch('bdr.der.q10_bruto._baixar_recurso') as baixar:
            retomar(['RN'], [2024], self.banco)
            retomar(['RN'], [2024], self.banco)
            baixar.assert_not_called()
        with duckdb.connect(str(self.banco), read_only=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM candidatura').fetchone(), (1,))
            self.assertEqual(con.execute('SELECT sum(valor) FROM despesa_candidatura').fetchone(), (25.0,))
            self.assertEqual(con.execute('SELECT count(*) FROM stg_consulta_cand').fetchone(), (1,))

    def test_rejeita_escopo_diferente_e_carga_incompleta(self):
        with self.assertRaisesRegex(ValueError, 'Escopo'):
            retomar(['CE'], [2024], self.banco)
        with duckdb.connect(str(self.banco)) as con:
            con.execute('DROP TABLE stg_tipo_eleicao')
        with self.assertRaisesRegex(ValueError, 'staging completo'):
            retomar(['RN'], [2024], self.banco)

    def test_falha_reverte_transformacao_e_preserva_staging(self):
        def falhar(con, *args):
            con.execute('DELETE FROM stg_despesas')
            raise RuntimeError('falha simulada')

        with patch('bdr.der.q10_bruto.carregar', side_effect=falhar):
            with self.assertRaisesRegex(RuntimeError, 'falha simulada'):
                retomar(['RN'], [2024], self.banco)
        with duckdb.connect(str(self.banco), read_only=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM stg_despesas').fetchone(), (1,))
