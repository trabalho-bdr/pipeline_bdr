import unittest

from bdr.motherduck import _lista_ufs_sql, _normalizar_token


class MotherDuckTokenTest(unittest.TestCase):
    def test_rejeita_valor_que_nao_e_jwt(self):
        with self.assertRaisesRegex(ValueError, "Token inválido"):
            _normalizar_token("nome-do-banco")

    def test_remove_prefixo_bearer_e_aspas(self):
        self.assertEqual(_normalizar_token("Bearer aaa.bbb.ccc"), "aaa.bbb.ccc")
        self.assertEqual(_normalizar_token("'aaa.bbb.ccc'"), "aaa.bbb.ccc")

    def test_valida_e_normaliza_ufs_para_remocao(self):
        self.assertEqual(_lista_ufs_sql(["se", "SE"]), "'SE'")
        with self.assertRaisesRegex(ValueError, "UF inválida"):
            _lista_ufs_sql(["Sergipe"])


if __name__ == "__main__":
    unittest.main()
