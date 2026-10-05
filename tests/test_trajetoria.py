import tempfile
import unittest
from pathlib import Path

import duckdb

from bdr.esquema import criar_tabelas as criar_tabelas_q3
from bdr.trajetoria.config import montar_escopo
from bdr.trajetoria.transformacao import carregar
from bdr.trajetoria.validacao import validar


class TrajetoriaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)
        self.cand = self.raiz / "consulta.csv"
        self.votos = self.raiz / "votos.csv"
        self.cand.write_text(
            "ANO_ELEICAO;NR_TURNO;SG_UF;CD_ELEICAO;DS_ELEICAO;DT_ELEICAO;"
            "SQ_CANDIDATO;NR_CPF_CANDIDATO;NM_CANDIDATO;NM_URNA_CANDIDATO;"
            "DT_NASCIMENTO;DS_GENERO;CD_CARGO;DS_CARGO;NR_PARTIDO;SG_PARTIDO;"
            "NM_PARTIDO;SG_UE;NR_CANDIDATO;DS_SITUACAO_CANDIDATURA;"
            "DS_SIT_TOT_TURNO;ST_REELEICAO\n"
            "2020;1;RN;426;Eleição Municipal;15/11/2020;100;11122233344;"
            "MARIA SILVA;MARIA;01/01/1980;FEMININO;13;Vereador;13;PT;"
            "Partido dos Trabalhadores;17612;13123;DEFERIDO;ELEITO;N\n"
            "2024;1;RN;619;Eleição Municipal;06/10/2024;200;11122233344;"
            "MARIA SILVA;MARIA;01/01/1980;FEMININO;11;Prefeito;40;PSB;"
            "Partido Socialista Brasileiro;17612;40;DEFERIDO;NÃO ELEITO;N\n",
            encoding="utf-8",
        )
        self.votos.write_text(
            "ANO_ELEICAO;NR_TURNO;SG_UF;CD_ELEICAO;SQ_CANDIDATO;CD_CARGO;"
            "CD_MUNICIPIO;QT_VOTOS_NOMINAIS\n"
            "2020;1;RN;426;100;13;17612;500\n"
            "2024;1;RN;619;200;11;17612;1000\n",
            encoding="utf-8",
        )

    def test_unifica_pessoa_e_preserva_candidaturas(self):
        con = duckdb.connect()
        criar_tabelas_q3(con)
        carregar(con, [self.cand], [self.votos])
        self.assertEqual(con.execute("SELECT count(*) FROM candidato").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT count(*) FROM candidatura").fetchone()[0], 2)
        self.assertEqual(
            con.execute("SELECT sum(votos) FROM resultado_candidatura").fetchone()[0],
            1500,
        )
        self.assertEqual(
            con.execute("SELECT round(sum(percentual_votos), 2) FROM resultado_candidatura").fetchone()[0],
            200.0,
        )
        self.assertEqual(
            con.execute("SELECT min(colocacao), max(colocacao) FROM resultado_candidatura").fetchone(),
            (1, 1),
        )
        self.assertEqual(
            con.execute("SELECT candidaturas, partidos, cargos FROM vw_trajetoria_candidato").fetchone(),
            (2, 2, 2),
        )

    def test_manifesto_detecta_ano_ausente(self):
        con = duckdb.connect()
        criar_tabelas_q3(con)
        carregar(con, [self.cand], [self.votos])
        escopo = montar_escopo(["RN"], [2020, 2022, 2024])
        manifesto = validar(con, escopo, {})
        self.assertFalse(manifesto["completo"])
        self.assertIn("anos sem candidaturas: 2022", manifesto["problemas"])


if __name__ == "__main__":
    unittest.main()
