import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch

import duckdb

from bdr.der.esquema import TABELAS_DER, criar
from executar_der import _atualizar_despesas, publicar


def _candidaturas(con, ids):
    con.execute("INSERT INTO Eleicao (id_eleicao) VALUES ('eleicao')")
    con.execute("INSERT INTO Candidato (id_candidato) VALUES ('pessoa')")
    for identificador in ids:
        con.execute(
            "INSERT INTO Candidatura (id_candidatura, id_eleicao, id_candidato) "
            "VALUES (?, 'eleicao', 'pessoa')", [identificador]
        )


class AtualizacaoDespesasTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        arquivo = Path(self.tmp.name) / "origem.duckdb"
        self.arquivo = arquivo
        with duckdb.connect(str(arquivo)) as fonte:
            criar(fonte)
            _candidaturas(fonte, ["c1", "c2"])
            fonte.execute("""INSERT INTO Despesa_Candidatura VALUES
                ('d1', 'c1', 'Publicidade', 100),
                ('d2', 'c1', 'Transporte', 20),
                ('d3', 'c2', 'Publicidade', 50)""")
        self.con = duckdb.connect()
        self.addCleanup(self.con.close)
        criar(self.con)
        caminho = arquivo.as_posix().replace("'", "''")
        self.con.execute(f"ATTACH '{caminho}' AS origem (READ_ONLY)")

    def test_preenche_tabela_vazia_com_dependencias_e_nao_duplica(self):
        _candidaturas(self.con, ["c1", "c2", "c3"])
        self.con.execute("UPDATE Candidatura SET gastos_campanha_total = 999 WHERE id_candidatura = 'c3'")
        self.con.execute("INSERT INTO Resultado_Candidatura (id_resultado, id_candidatura) VALUES ('r1', 'c1')")
        self.con.execute("INSERT INTO Cargo (id_cargo, id_candidatura) VALUES ('cargo1', 'c1')")
        self.assertEqual(_atualizar_despesas(self.con, "memory"), (3, 3))
        self.assertEqual(
            self.con.execute("SELECT id_candidatura, gastos_campanha_total FROM Candidatura ORDER BY 1").fetchall(),
            [("c1", 120), ("c2", 50), ("c3", 999)],
        )
        self.assertEqual(_atualizar_despesas(self.con, "memory"), (0, 3))
        self.assertEqual(self.con.execute("SELECT count(*) FROM Resultado_Candidatura").fetchone()[0], 1)

    def test_completa_carga_parcial_e_soma_despesas_existentes(self):
        _candidaturas(self.con, ["c1", "c2"])
        self.con.execute("""INSERT INTO Despesa_Candidatura VALUES
            ('d1', 'c1', 'Publicidade', 100), ('extra', 'c1', 'Outros', 10)""")
        self.assertEqual(_atualizar_despesas(self.con, "memory"), (2, 4))
        self.assertEqual(
            self.con.execute("SELECT gastos_campanha_total FROM Candidatura WHERE id_candidatura = 'c1'").fetchone()[0],
            130,
        )

    def test_candidatura_ausente_interrompe_sem_inserir(self):
        _candidaturas(self.con, ["c1"])
        with self.assertRaisesRegex(RuntimeError, "não existem no destino"):
            _atualizar_despesas(self.con, "memory")
        self.assertEqual(self.con.execute("SELECT count(*) FROM Despesa_Candidatura").fetchone()[0], 0)

    def test_despesa_divergente_interrompe_sem_alterar(self):
        _candidaturas(self.con, ["c1", "c2"])
        self.con.execute("INSERT INTO Despesa_Candidatura VALUES ('d1', 'c1', 'Publicidade', 999)")
        with self.assertRaisesRegex(RuntimeError, "dados diferentes"):
            _atualizar_despesas(self.con, "memory")
        self.assertEqual(self.con.execute("SELECT id_despesa, valor FROM Despesa_Candidatura").fetchall(), [("d1", 999)])
        self.assertEqual(self.con.execute("SELECT count(gastos_campanha_total) FROM Candidatura").fetchone()[0], 0)

    def test_erro_de_schema_reverte_insercao(self):
        _candidaturas(self.con, ["c1", "c2"])
        # Simula um destino antigo sem a coluna de total; a inserção deve ser revertida.
        for tabela in ("Cargo", "Resultado_Candidatura", "Despesa_Candidatura"):
            self.con.execute(f'DROP TABLE "{tabela}"')
        self.con.execute("ALTER TABLE Candidatura RENAME COLUMN gastos_campanha_total TO total_antigo")
        self.con.execute(f'CREATE TABLE "Despesa_Candidatura" ({TABELAS_DER["Despesa_Candidatura"]})')
        with self.assertRaises(duckdb.BinderException):
            _atualizar_despesas(self.con, "memory")
        self.assertEqual(self.con.execute("SELECT count(*) FROM Despesa_Candidatura").fetchone()[0], 0)

    def test_destino_explicito_com_outro_banco_ativo(self):
        _candidaturas(self.con, ["c1", "c2"])
        self.con.execute("USE origem")
        self.assertEqual(_atualizar_despesas(self.con, "memory"), (3, 3))
        self.assertEqual(self.con.execute('SELECT count(*) FROM memory.main.Despesa_Candidatura').fetchone()[0], 3)
        self.assertEqual(self.con.execute('SELECT sum(valor) FROM origem.main.Despesa_Candidatura').fetchone()[0], 170)

    def test_destino_ausente_nao_usa_tabela_da_origem(self):
        _candidaturas(self.con, ["c1", "c2"])
        self.con.execute("DROP TABLE memory.main.Despesa_Candidatura")
        self.con.execute("USE origem")
        with self.assertRaises(duckdb.CatalogException):
            _atualizar_despesas(self.con, "memory")
        self.assertEqual(self.con.execute('SELECT count(*) FROM origem.main.Despesa_Candidatura').fetchone()[0], 3)

    def test_publicacao_confere_destino_sem_origem_anexada(self):
        self.con.execute("DETACH origem")
        self.con.execute("ATTACH ':memory:' AS pipeline_bdr_der_completo_v2")
        self.con.execute("USE pipeline_bdr_der_completo_v2")
        criar(self.con)
        _candidaturas(self.con, ["c1", "c2"])
        saida = StringIO()
        with patch.dict("os.environ", {"MOTHERDUCK_TOKEN": "teste"}):
            with patch("executar_der.duckdb.connect", return_value=self.con):
                with redirect_stdout(saida):
                    publicar(self.arquivo, atualizar_despesas=True)
        self.assertIn("pipeline_bdr_der_completo_v2.main.Despesa_Candidatura; antes: 0", saida.getvalue())
        self.assertIn("3 inseridas; 3 confirmadas no destino", saida.getvalue())

    def test_conta_diferente_interrompe_antes_de_criar_banco(self):
        conexao = Mock()
        conexao.execute.return_value.fetchone.return_value = ("outra_conta",)
        with patch.dict("os.environ", {"MOTHERDUCK_TOKEN": "teste"}):
            with patch("executar_der.duckdb.connect", return_value=conexao):
                with self.assertRaisesRegex(RuntimeError, "esperada: camillylarissa05"):
                    publicar(self.arquivo, usuario_esperado="camillylarissa05")
        conexao.execute.assert_called_once_with("SELECT current_user()")
        conexao.close.assert_called_once()

    def test_publicacao_inicial_confere_todas_as_tabelas(self):
        self.con.execute("DETACH origem")
        con = self.con

        class DestinoLocal:
            def execute(self, sql, *args):
                if sql == 'CREATE DATABASE IF NOT EXISTS "pipeline_bdr_der_completo_v2"':
                    return con.execute("ATTACH ':memory:' AS pipeline_bdr_der_completo_v2")
                return con.execute(sql, *args)

            def close(self):
                con.close()

        saida = StringIO()
        with patch.dict("os.environ", {"MOTHERDUCK_TOKEN": "teste"}):
            with patch("executar_der.duckdb.connect", return_value=DestinoLocal()):
                with redirect_stdout(saida):
                    publicar(self.arquivo)
        self.assertEqual(saida.getvalue().count("Confirmado pipeline_bdr_der_completo_v2.main."), len(TABELAS_DER))
        self.assertIn("Confirmado pipeline_bdr_der_completo_v2.main.Despesa_Candidatura: 3", saida.getvalue())
        self.assertIn("Confirmado pipeline_bdr_der_completo_v2.main.Candidatura: 2", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
