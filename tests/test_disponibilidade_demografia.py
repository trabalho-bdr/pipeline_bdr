"""Fontes opcionais: ausência externa não apaga dados nem interrompe outras fontes."""
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from bdr.der.demografia import _fonte_opcional, enriquecer


class DisponibilidadeTest(unittest.TestCase):
    def test_fonte_ausente_gera_aviso(self):
        avisos = []
        resultado = _fonte_opcional(Mock(side_effect=FileNotFoundError('ano ausente')),
                                    avisos=avisos, rotulo='Perfil 2018')
        self.assertIsNone(resultado)
        self.assertIn('Perfil 2018', avisos[0])

    def test_dado_invalido_nao_e_tratado_como_fonte_ausente(self):
        with self.assertRaises(ValueError):
            _fonte_opcional(Mock(side_effect=ValueError('total inconsistente')),
                            avisos=[], rotulo='Censo')

    @patch('bdr.der.demografia._cache_json', side_effect=RuntimeError('HTTP 500'))
    @patch('bdr.der.demografia.baixar', side_effect=FileNotFoundError('404'))
    def test_todas_fontes_indisponiveis_concluem_sem_apagar_dados(self, baixar, cache):
        con = Mock()
        con.execute.return_value.fetchall.return_value = []
        con.execute.return_value.fetchone.return_value = (0,)
        with tempfile.TemporaryDirectory() as tmp:
            enriquecer(con, ['RS'], [2018, 2024], tmp)
            relatorio = json.loads((Path(tmp) / 'avisos_ultima_carga.json').read_text(encoding='utf-8'))
        comandos = [c.args[0] for c in con.execute.call_args_list]
        self.assertIn('COMMIT', comandos)
        self.assertFalse(any('DELETE FROM' in sql for sql in comandos))
        con.executemany.assert_not_called()
        self.assertEqual(relatorio['anos_perfil_disponiveis'], [])
        self.assertGreaterEqual(len(relatorio['avisos']), 4)

    @patch('bdr.der.demografia.baixar', side_effect=FileNotFoundError('404'))
    @patch('bdr.der.demografia._cache_json')
    def test_indicadores_carregam_mesmo_sem_media(self, cache, baixar):
        meta = {'classificacoes': [{'id': 287, 'categorias': [{'id': 1, 'nome': 'Total'}]}]}
        indicadores = [{'id': '10613', 'resultados': [{'series': [
            {'localidade': {'id': '4300034'}, 'serie': {'2022': '38'}}]}]}]
        cache.side_effect = [meta, urllib.error.HTTPError('url', 500, 'falha', {}, None), indicadores]
        con = Mock()
        con.execute.return_value.fetchall.return_value = []
        con.execute.return_value.fetchone.return_value = (0,)
        with tempfile.TemporaryDirectory() as tmp:
            enriquecer(con, ['RS'], [2024], tmp)
        self.assertEqual(con.executemany.call_args.args[1], [('4300034', None, 38.0, None)])


if __name__ == '__main__':
    unittest.main()
