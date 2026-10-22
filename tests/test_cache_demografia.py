"""Retentativas de rede simuladas; não requer DuckDB nem conexão externa."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from bdr.der.demografia import _cache_json


class CacheDemografiaTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.arquivo = Path(tmp.name) / 'ibge' / 'idades_2022_RS.json'
        self.url = 'https://example.invalid/ibge'

    def erro(self, codigo):
        return urllib.error.HTTPError(self.url, codigo, 'Erro simulado', {}, None)

    @patch('bdr.der.demografia.time.sleep')
    @patch('bdr.der.demografia._requisicao_json')
    def test_500_temporario_repete_e_salva_somente_resposta_completa(self, requisicao, sleep):
        requisicao.side_effect = [self.erro(500), self.erro(503), [{'id': '93'}]]
        self.assertEqual(_cache_json(self.url, self.arquivo), [{'id': '93'}])
        self.assertEqual(requisicao.call_count, 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [2, 4])
        self.assertEqual(json.loads(self.arquivo.read_text(encoding='utf-8')), [{'id': '93'}])
        self.assertFalse(self.arquivo.with_suffix('.part').exists())
        _cache_json(self.url, self.arquivo)
        self.assertEqual(requisicao.call_count, 3)  # retomada usa o cache

    @patch('bdr.der.demografia.time.sleep')
    @patch('bdr.der.demografia._requisicao_json')
    def test_falha_persistente_preserva_cache_de_outras_ufs(self, requisicao, sleep):
        self.arquivo.parent.mkdir(parents=True)
        existente = self.arquivo.with_name('idades_2022_RN.json')
        existente.write_text('[1]', encoding='utf-8')
        requisicao.side_effect = self.erro(500)
        with self.assertRaisesRegex(RuntimeError, '4 tentativas.*idades_2022_RS.json'):
            _cache_json(self.url, self.arquivo)
        self.assertEqual(requisicao.call_count, 4)
        self.assertEqual(sleep.call_count, 3)
        self.assertFalse(self.arquivo.exists())
        self.assertEqual(existente.read_text(encoding='utf-8'), '[1]')

    @patch('bdr.der.demografia.time.sleep')
    @patch('bdr.der.demografia._requisicao_json')
    def test_404_nao_repete(self, requisicao, sleep):
        requisicao.side_effect = self.erro(404)
        with self.assertRaises(urllib.error.HTTPError):
            _cache_json(self.url, self.arquivo)
        self.assertEqual(requisicao.call_count, 1)
        sleep.assert_not_called()

    @patch('bdr.der.demografia.time.sleep')
    @patch('bdr.der.demografia._requisicao_json')
    def test_timeout_repete(self, requisicao, sleep):
        requisicao.side_effect = [TimeoutError('tempo esgotado'), []]
        self.assertEqual(_cache_json(self.url, self.arquivo), [])
        self.assertEqual(requisicao.call_count, 2)


if __name__ == '__main__':
    unittest.main()
