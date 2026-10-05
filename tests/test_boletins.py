import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from bdr.boletins import extrair_boletim, obter_boletins, planejar
from bdr.config import MEMBROS, montar_escopo
from bdr.download import baixar

COLUNAS = ["ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_ELEICAO", "CD_MUNICIPIO",
           "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "DS_CARGO_PERGUNTA",
           "DS_TIPO_VOTAVEL", "QT_VOTOS", "NM_VOTAVEL"]


class BoletinsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.recurso = planejar(["RN"], [2024], [2])[0]
        self.zip_path = self.base / "bu.zip"
        self.destino = self.base / "saida.csv"

    def zip_fixture(self, linhas, colunas=COLUNAS):
        conteudo = io.StringIO(newline="")
        escritor = csv.writer(conteudo, delimiter=";")
        escritor.writerow(colunas)
        escritor.writerows(linhas)
        with zipfile.ZipFile(self.zip_path, "w") as z:
            z.writestr(f"subpasta/{self.recurso['nome']}.csv", conteudo.getvalue().encode("latin-1"))
            z.writestr("leiame.pdf", b"documentacao")

    def test_plano_tem_oito_recortes_distintos(self):
        plano = planejar(["rn", "RJ", "RJ"], [2024, 2022], [2, 1])
        self.assertEqual(len(plano), 8)
        self.assertEqual(len({r["url"] for r in plano}), 8)
        self.assertTrue(all("/buweb/bweb_" in r["url"] for r in plano))
        for args in [([], [2024], [1]), (["RN"], [2020], [1]), (["RN"], [2024], [3])]:
            with self.assertRaises(ValueError):
                planejar(*args)

    def test_planejar_aceita_qualquer_uf(self):
        plano = planejar(["SP", "MA", "SE"], [2024], [1])
        self.assertEqual(len(plano), 3)
        self.assertEqual({r["uf"] for r in plano}, {"MA", "SE", "SP"})

    def test_escopo_membros_q3_duas_ufs(self):
        for membro_id in sorted(MEMBROS):
            escopo = montar_escopo(membro=membro_id)
            self.assertEqual(len(escopo["ufs"]), 2, f"Membro {membro_id} não tem exatamente 2 UFs")
            self.assertEqual(escopo["anos"], [2022, 2024])
            self.assertEqual(set(escopo["plano"].keys()), {"boletim_urna", "detalhe_votacao_munzona"})
            self.assertEqual(escopo["plano"]["boletim_urna"], [2022, 2024])
            self.assertEqual(escopo["plano"]["detalhe_votacao_munzona"], [2022, 2024])

    def test_escopo_nao_contem_arquivos_outras_perguntas(self):
        escopo = montar_escopo(ufs=["RJ", "SP"], anos=[2022, 2024])
        self.assertNotIn("consulta_cand", escopo["plano"])
        self.assertNotIn("prestacao_contas", escopo["plano"])
        self.assertNotIn("perfil_eleitorado", escopo["plano"])
        self.assertNotIn("consulta_vagas", escopo["plano"])
        self.assertNotIn("votacao_candidato_munzona", escopo["plano"])
        self.assertEqual(set(escopo["plano"].keys()), {"boletim_urna", "detalhe_votacao_munzona"})

    def test_preserva_votos_acentos_e_conta_secoes_sem_repetir(self):
        linhas = [
            [2024, 2, "RN", 620, 17612, 2, 445, 11, "Prefeito", "Nominal", 100, "JOÃO"],
            [2024, 2, "RN", 620, 17612, 2, 445, 11, "Prefeito", "Branco", 5, "Branco"],
            [2024, 2, "RN", 620, 17612, 2, 446, 11, "Prefeito", "Nominal", 70, "MARIA"],
            [2024, 2, "RN", 621, 17612, 2, 445, 3, "Governador", "Nominal", 80, "JOSÉ"],
        ]
        self.zip_fixture(linhas)
        meta = extrair_boletim(self.zip_path, self.destino, self.recurso)
        self.assertEqual((meta["linhas"], meta["secoes"], meta["municipios"]), (4, 2, 1))
        self.assertEqual({v["tipo_voto"]: v["votos"] for v in meta["votos_por_cargo_tipo"]
                          if v["codigo_cargo"] == "11"},
                         {"Nominal": 170, "Branco": 5})
        with self.destino.open(encoding="utf-8", newline="") as f:
            dados = list(csv.reader(f, delimiter=";"))
        self.assertEqual(dados[0], COLUNAS)
        self.assertEqual(dados[1][-1], "JOÃO")
        self.assertEqual(extrair_boletim(self.zip_path, self.destino, self.recurso), meta)
        # CSV interrompido ou truncado não é considerado um cache completo.
        self.destino.write_text("incompleto", encoding="utf-8")
        self.assertEqual(extrair_boletim(self.zip_path, self.destino, self.recurso), meta)

    def test_erro_de_recorte_nao_publica_csv_parcial(self):
        self.zip_fixture([[2024, 1, "RN", 619, 17612, 2, 445, 11, "Prefeito", "Nominal", 5, "A"]])
        with self.assertRaisesRegex(ValueError, "fora do recorte"):
            extrair_boletim(self.zip_path, self.destino, self.recurso)
        self.assertFalse(self.destino.exists())
        self.assertFalse(self.destino.with_suffix(".csv.part").exists())

    def test_layout_ausente_nao_publica_csv(self):
        self.zip_fixture([], ["ANO_ELEICAO"])
        with self.assertRaisesRegex(ValueError, "Colunas ausentes"):
            extrair_boletim(self.zip_path, self.destino, self.recurso)
        self.assertFalse(self.destino.exists())

    def test_falha_fica_no_manifesto(self):
        caminho, meta = obter_boletins([self.recurso], self.base, sem_download=True)
        self.assertFalse(meta["completo"])
        self.assertEqual(len(meta["problemas"]), 1)
        self.assertEqual(json.loads(caminho.read_text(encoding="utf-8")), meta)

    def test_download_truncado_nao_vira_cache(self):
        resp = io.BytesIO(b"abc")
        resp.headers = {"Content-Length": "10"}
        destino = self.base / "download.zip"
        with patch("bdr.download.urllib.request.urlopen", return_value=resp):
            with self.assertRaisesRegex(RuntimeError, "Download incompleto"):
                baixar("https://example.test/arquivo.zip", destino, tentativas=1)
        self.assertFalse(destino.exists())


if __name__ == "__main__":
    unittest.main()
