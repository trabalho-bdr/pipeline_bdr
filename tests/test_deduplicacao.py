"""Testes unitários e de integração para a deduplicação de fotos de candidatos."""

import asyncio
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb
from PIL import Image
from starlette.requests import Request

from bdr.fotos import aquisicao as aq
from bdr.fotos.catalogo import LeitorCatalogo, abrir, caminho_seguro
from bdr.fotos.deduplicacao import (
    AuditoriaCatalogoDisco,
    construir_plano,
    executar_deduplicacao,
    fazer_backup_sqlite,
    sanitizar_nome_arquivo,
    validar_arquivo_imagem,
)
from bdr.fotos.fontes import biografia, hash_texto, sequencial, titulo
from frontend import fotos, main


class DeduplicacaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

        self.banco_sqlite = self.raiz / "catalogo.sqlite3"
        self.raiz_origem = self.raiz / "imagens"
        self.raiz_destino = self.raiz / "fotos selecionadas"
        self.raiz_origem.mkdir(parents=True, exist_ok=True)
        self.raiz_destino.mkdir(parents=True, exist_ok=True)

        self.cat = abrir(self.banco_sqlite)
        self.addCleanup(self.cat.close)

        # Banco DER temporário (DuckDB)
        self.banco_der = self.raiz / "der.duckdb"
        self.der = duckdb.connect(str(self.banco_der))
        self.addCleanup(self.der.close)
        self.der.execute("""
            CREATE TABLE Candidato(
                id_candidato VARCHAR PRIMARY KEY,
                titulo_eleitoral VARCHAR,
                nome_civil VARCHAR,
                dt_nascimento DATE
            )
        """)

    def criar_imagem_disco(self, caminho_relativo, cor="blue", formato="JPEG"):
        """Cria uma imagem física no disco com bytes válidos e Pillow decodificável."""
        stream = io.BytesIO()
        Image.new("RGB", (30, 40), cor).save(stream, formato)
        bytes_img = stream.getvalue()

        destino = self.raiz_origem / caminho_relativo
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(bytes_img)

        digest = hashlib.sha256(bytes_img).hexdigest()
        return {
            "caminho": caminho_relativo,
            "caminho_abs": destino,
            "sha256": digest,
            "tamanho": len(bytes_img),
            "mime": "image/jpeg" if formato == "JPEG" else "image/png",
            "bytes": bytes_img,
        }

    def cadastrar_candidato_der(self, cid, nome, titulo_eleitoral="111111111111", dt_nasc="1980-01-01"):
        self.der.execute(
            "INSERT OR REPLACE INTO Candidato VALUES (?, ?, ?, ?)",
            (cid, titulo_eleitoral, nome, dt_nasc),
        )

    def cadastrar_foto_catalogo(self, cid, ano, uf, sq, img_info, data=None):
        data = data or f"{ano}-10-06"
        chave = f"reg_{ano}_{uf}_{sq}"
        bio = biografia("NOME", "1980-01-01")

        self.cat.execute("INSERT OR IGNORE INTO pessoas VALUES (?,?,?)", (cid, bio, None))
        self.cat.execute(
            "INSERT OR REPLACE INTO registros VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                chave,
                f"candidatos-{ano}",
                ano,
                data,
                data,
                uf,
                sq,
                "eleicao",
                bio,
                None,
                None,
                None,
                "teste.csv",
                1,
            ),
        )
        self.cat.execute(
            "INSERT OR REPLACE INTO vinculos VALUES (?,?,?)",
            (chave, cid, "TESTE"),
        )
        self.cat.execute(
            "INSERT OR REPLACE INTO imagens VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                ano,
                uf,
                sq,
                "disponivel",
                img_info["caminho"],
                img_info["mime"],
                img_info["sha256"],
                img_info["tamanho"],
                30,
                40,
                "https://tse.jus.br/f.zip",
                "arq.jpg",
                "2026-01-01",
                None,
            ),
        )
        self.cat.execute(
            "INSERT OR REPLACE INTO principais VALUES (?,?,?,?,?,?,?)",
            (cid, chave, chave, "disponivel", 0, 1, "2026-01-01"),
        )
        self.cat.commit()

    def test_sanitizacao_windows(self):
        """Cenário: Nomes com caracteres proibidos, reservados, limites e espaços finais."""
        # 1. Caracteres proibidos e espaços
        nome1 = '  JOÃO DA SILVA: O "GRANDE" * <TESTE> ? | / \\ '
        limpo1 = sanitizar_nome_arquivo(nome1, "12345", ".jpg")
        self.assertNotIn(":", limpo1)
        self.assertNotIn('"', limpo1)
        self.assertNotIn("*", limpo1)
        self.assertNotIn("<", limpo1)
        self.assertNotIn(">", limpo1)
        self.assertNotIn("?", limpo1)
        self.assertNotIn("|", limpo1)
        self.assertNotIn("/", limpo1)
        self.assertNotIn("\\", limpo1)
        self.assertTrue(limpo1.endswith("_12345.jpg"))
        self.assertFalse(limpo1.endswith(" .jpg"))

        # 2. Nomes reservados do Windows
        limpo_aux = sanitizar_nome_arquivo("AUX", "1", ".jpg")
        self.assertTrue(limpo_aux.startswith("_AUX_1") or not limpo_aux.startswith("AUX."))

        # 3. Limite de comprimento
        nome_longo = "A" * 300
        limpo_longo = sanitizar_nome_arquivo(nome_longo, "999", ".png")
        self.assertLessEqual(len(limpo_longo), 245)
        self.assertTrue(limpo_longo.endswith("_999.png"))

    def test_pessoa_varios_anos_mantem_mais_recente_e_exclui_demais(self):
        """Cenário: Pessoa com candidaturas em 2012, 2020 e 2024."""
        cid = "p_multi"
        self.cadastrar_candidato_der(cid, "CARLOS EDUARDO SILVA")

        img_2012 = self.criar_imagem_disco("2012/MA/100.jpg", "red")
        img_2020 = self.criar_imagem_disco("2020/MA/200.jpg", "green")
        img_2024 = self.criar_imagem_disco("2024/MA/300.jpg", "blue")

        self.cadastrar_foto_catalogo(cid, 2012, "MA", "100", img_2012, "2012-10-07")
        self.cadastrar_foto_catalogo(cid, 2020, "MA", "200", img_2020, "2020-11-15")
        self.cadastrar_foto_catalogo(cid, 2024, "MA", "300", img_2024, "2024-10-06")

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        resumo = plano["resumo"]
        self.assertEqual(resumo["consolidadas"], 1)
        self.assertEqual(resumo["total_excedentes_para_excluir"], 2)

        # Aplicar
        resultado = executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        self.assertTrue(resultado["sucesso"])
        self.assertEqual(resultado["resumo_aplicacao"]["arquivos_publicados"], 1)
        self.assertEqual(resultado["resumo_aplicacao"]["arquivos_excluidos"], 2)

        # Verificar se destino tem exatamente a de 2024
        esperado_dest = self.raiz_destino / "2024" / "CARLOS EDUARDO SILVA_300.jpg"
        self.assertTrue(esperado_dest.is_file())
        self.assertEqual(esperado_dest.read_bytes(), img_2024["bytes"])

        # Verificar se as originais de 2012, 2020 e 2024 foram removidas da pasta original
        self.assertFalse(img_2012["caminho_abs"].is_file())
        self.assertFalse(img_2020["caminho_abs"].is_file())
        self.assertFalse(img_2024["caminho_abs"].is_file())

        # Verificar que catálogo marcou excedentes como excluida_consolidacao
        st_2012 = self.cat.execute("SELECT status FROM imagens WHERE ano=2012 AND sequencial='100'").fetchone()[0]
        st_2020 = self.cat.execute("SELECT status FROM imagens WHERE ano=2020 AND sequencial='200'").fetchone()[0]
        st_2024 = self.cat.execute("SELECT status, caminho FROM imagens WHERE ano=2024 AND sequencial='300'").fetchone()
        self.assertEqual(st_2012, "excluida_consolidacao")
        self.assertEqual(st_2020, "excluida_consolidacao")
        self.assertEqual(st_2024[0], "disponivel")
        self.assertEqual(st_2024[1], "2024/CARLOS EDUARDO SILVA_300.jpg")

    def test_pessoa_com_unica_imagem(self):
        """Cenário: Pessoa com uma única imagem."""
        cid = "p_unica"
        self.cadastrar_candidato_der(cid, "ANA PAULA SANTOS")
        img = self.criar_imagem_disco("2024/RJ/555.jpg", "yellow")
        self.cadastrar_foto_catalogo(cid, 2024, "RJ", "555", img)

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        self.assertEqual(plano["resumo"]["total_excedentes_para_excluir"], 0)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        esperado = self.raiz_destino / "2024" / "ANA PAULA SANTOS_555.jpg"
        self.assertTrue(esperado.is_file())
        self.assertFalse(img["caminho_abs"].is_file())

    def test_homonimos_distintos_nao_unificados(self):
        """Cenário: Pessoas homônimas (mesmo nome civil, mas id_candidato e sequenciais diferentes)."""
        cid1, cid2 = "h1", "h2"
        self.cadastrar_candidato_der(cid1, "JOSE SILVA", "111111111111", "1970-01-01")
        self.cadastrar_candidato_der(cid2, "JOSE SILVA", "222222222222", "1985-05-10")

        img1 = self.criar_imagem_disco("2024/CE/1001.jpg", "magenta")
        img2 = self.criar_imagem_disco("2024/RN/2002.jpg", "cyan")

        self.cadastrar_foto_catalogo(cid1, 2024, "CE", "1001", img1)
        self.cadastrar_foto_catalogo(cid2, 2024, "RN", "2002", img2)

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid1, cid2])
        self.assertEqual(plano["resumo"]["consolidadas"], 2)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        dest1 = self.raiz_destino / "2024" / "JOSE SILVA_1001.jpg"
        dest2 = self.raiz_destino / "2024" / "JOSE SILVA_2002.jpg"

        self.assertTrue(dest1.is_file())
        self.assertTrue(dest2.is_file())
        self.assertEqual(dest1.read_bytes(), img1["bytes"])
        self.assertEqual(dest2.read_bytes(), img2["bytes"])

    def test_ids_equivalentes_identidade_comprovada(self):
        """Cenário: Dois id_candidato distintos que correspondem comprovadamente à mesma pessoa no DER."""
        id1, id2 = "equiv_a", "equiv_b"
        nome = "MARIA HELENA DIAS"
        tit = "987654321012"
        dt = "1975-08-20"

        self.cadastrar_candidato_der(id1, nome, tit, dt)
        self.cadastrar_candidato_der(id2, nome, tit, dt)

        # id1 tem foto antiga em 2016; id2 tem foto mais recente em 2024
        img_2016 = self.criar_imagem_disco("2016/MS/10.jpg", "orange")
        img_2024 = self.criar_imagem_disco("2024/MS/20.jpg", "purple")

        self.cadastrar_foto_catalogo(id1, 2016, "MS", "10", img_2016, "2016-10-02")
        self.cadastrar_foto_catalogo(id2, 2024, "MS", "20", img_2024, "2024-10-06")

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[id1, id2])
        # Ambos os IDs foram unificados sob a mesma pessoa canônica
        self.assertEqual(plano["resumo"]["consolidadas"], 1)
        self.assertEqual(plano["resumo"]["total_excedentes_para_excluir"], 1)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        # O arquivo final deve ser o mais recente (2024)
        dest = self.raiz_destino / "2024" / "MARIA HELENA DIAS_20.jpg"
        self.assertTrue(dest.is_file())
        self.assertFalse(img_2016["caminho_abs"].is_file())

        # Ambos os IDs em principais devem apontar para a foto escolhida
        row1 = self.cat.execute("SELECT foto_status FROM principais WHERE id_candidato=?", (id1,)).fetchone()[0]
        row2 = self.cat.execute("SELECT foto_status FROM principais WHERE id_candidato=?", (id2,)).fetchone()[0]
        self.assertEqual(row1, "disponivel")
        self.assertEqual(row2, "disponivel")

    def test_imagem_recente_ausente_usa_foto_anterior(self):
        """Cenário: Foto mais recente (2024) ausente ou corrompida -> usa 2020 com foto_anterior=True."""
        cid = "p_fallback"
        self.cadastrar_candidato_der(cid, "ROBERTO SOUZA")

        img_2020 = self.criar_imagem_disco("2020/RS/100.jpg", "gray")
        # Registramos 2024 no catálogo, mas não criamos o arquivo no disco (ou criamos corrompido)
        info_2024 = {
            "caminho": "2024/RS/200.jpg",
            "mime": "image/jpeg",
            "sha256": "fakehash",
            "tamanho": 1000,
        }

        self.cadastrar_foto_catalogo(cid, 2020, "RS", "100", img_2020, "2020-11-15")
        self.cadastrar_foto_catalogo(cid, 2024, "RS", "200", info_2024, "2024-10-06")

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        self.assertEqual(plano["resumo"]["consolidadas"], 1)
        self.assertEqual(plano["resumo"]["foto_anterior_utilizada"], 1)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        dest = self.raiz_destino / "2020" / "ROBERTO SOUZA_100.jpg"
        self.assertTrue(dest.is_file())

        # Verifica se catálogo registrou foto_anterior=1
        foto_ant = self.cat.execute("SELECT foto_anterior FROM principais WHERE id_candidato=?", (cid,)).fetchone()[0]
        self.assertEqual(foto_ant, 1)

    def test_empate_datas_ambiguidade_preserva_originais(self):
        """Cenário: Duas imagens distintas empatadas na mesma data mais recente -> preserva sem exclusão."""
        cid = "p_empate"
        self.cadastrar_candidato_der(cid, "PATRICIA LIMA")

        img_a = self.criar_imagem_disco("2024/MA/111.jpg", "red")
        img_b = self.criar_imagem_disco("2024/MA/222.jpg", "blue")

        self.cadastrar_foto_catalogo(cid, 2024, "MA", "111", img_a, "2024-10-06")
        self.cadastrar_foto_catalogo(cid, 2024, "MA", "222", img_b, "2024-10-06")

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        self.assertEqual(plano["resumo"]["pendencias_empate"], 1)
        self.assertEqual(plano["resumo"]["consolidadas"], 0)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        # Nenhuma imagem excluída
        self.assertTrue(img_a["caminho_abs"].is_file())
        self.assertTrue(img_b["caminho_abs"].is_file())

    def test_colisao_caminhos_finais_preserva_originais(self):
        """Cenário: Duas pessoas distintas gerando o mesmo caminho final -> não sobrescreve, preserva."""
        c1, c2 = "col_1", "col_2"
        # Mesmo nome e mesmo sequencial (em UFs distintas) no mesmo ano, mas pessoas distintas
        self.cadastrar_candidato_der(c1, "LUCAS PEREIRA", "111111111111", "1980-01-01")
        self.cadastrar_candidato_der(c2, "LUCAS PEREIRA", "222222222222", "1990-05-15")

        img1 = self.criar_imagem_disco("2024/CE/999.jpg", "green")
        img2 = self.criar_imagem_disco("2024/MA/999.jpg", "black")

        self.cadastrar_foto_catalogo(c1, 2024, "CE", "999", img1)
        self.cadastrar_foto_catalogo(c2, 2024, "MA", "999", img2)

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[c1, c2])
        self.assertEqual(plano["resumo"]["pendencias_colisao"], 2)
        self.assertEqual(plano["resumo"]["consolidadas"], 0)

        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        # Ambas preservadas
        self.assertTrue(img1["caminho_abs"].is_file())
        self.assertTrue(img2["caminho_abs"].is_file())

    def test_destino_existente_com_conteudo_diferente(self):
        """Cenário: O destino já existe com bytes divergentes -> não sobrescreve."""
        cid = "p_diverge"
        self.cadastrar_candidato_der(cid, "FERNANDO ALVES")
        img = self.criar_imagem_disco("2024/RJ/777.jpg", "white")
        self.cadastrar_foto_catalogo(cid, 2024, "RJ", "777", img)

        dest_conflito = self.raiz_destino / "2024" / "FERNANDO ALVES_777.jpg"
        dest_conflito.parent.mkdir(parents=True, exist_ok=True)
        dest_conflito.write_bytes(b"CONTEUDO_TOTALMENTE_DIFERENTE")

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        resultado = executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)

        self.assertTrue(len(resultado["manifesto"]["erros"]) > 0)
        # O arquivo original foi preservado e não deletado
        self.assertTrue(img["caminho_abs"].is_file())

    def test_simulacao_nao_altera_nada(self):
        """Cenário: Modo simulação não modifica nenhum arquivo em disco nem o banco operacional."""
        cid = "p_sim"
        self.cadastrar_candidato_der(cid, "SIMULACAO CANDIDATO")
        img1 = self.criar_imagem_disco("2012/RN/1.jpg", "red")
        img2 = self.criar_imagem_disco("2024/RN/2.jpg", "blue")
        self.cadastrar_foto_catalogo(cid, 2012, "RN", "1", img1)
        self.cadastrar_foto_catalogo(cid, 2024, "RN", "2", img2)

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        res = executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=False)

        self.assertEqual(res["modo"], "simulacao")
        # Destino NÃO deve existir
        dest = self.raiz_destino / "2024" / "SIMULACAO CANDIDATO_2.jpg"
        self.assertFalse(dest.exists())
        # Originais continuam intactas
        self.assertTrue(img1["caminho_abs"].is_file())
        self.assertTrue(img2["caminho_abs"].is_file())
        # Banco inalterado
        st = self.cat.execute("SELECT status FROM imagens WHERE ano=2012 AND sequencial='1'").fetchone()[0]
        self.assertEqual(st, "disponivel")

    def test_reexecucao_idempotente_e_sem_duplicacao(self):
        """Cenário: Reexecução reconhece arquivo final existente e não cria duplicações."""
        cid = "p_idemp"
        self.cadastrar_candidato_der(cid, "REEXECUTAVEL")
        img1 = self.criar_imagem_disco("2016/CE/10.jpg", "red")
        img2 = self.criar_imagem_disco("2024/CE/20.jpg", "blue")
        self.cadastrar_foto_catalogo(cid, 2016, "CE", "10", img1)
        self.cadastrar_foto_catalogo(cid, 2024, "CE", "20", img2)

        # 1ª execução
        plano1 = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        executar_deduplicacao(plano1, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)

        dest = self.raiz_destino / "2024" / "REEXECUTAVEL_20.jpg"
        self.assertTrue(dest.is_file())

        # 2ª execução
        plano2 = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        exec2 = executar_deduplicacao(plano2, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        self.assertTrue(exec2["sucesso"])
        self.assertTrue(dest.is_file())

    def test_interrupcao_e_retomada(self):
        """Cenário: Interrupção após publicar arquivo no destino mas antes de atualizar catálogo e excluir."""
        cid = "p_interrompido"
        self.cadastrar_candidato_der(cid, "INTERRUPCAO TESTE")
        img1 = self.criar_imagem_disco("2016/CE/101.jpg", "red")
        img2 = self.criar_imagem_disco("2024/CE/202.jpg", "blue")
        self.cadastrar_foto_catalogo(cid, 2016, "CE", "101", img1)
        self.cadastrar_foto_catalogo(cid, 2024, "CE", "202", img2)

        # Simular interrupção: o arquivo final já foi publicado no destino, mas a transação do catálogo foi abortada
        dest = self.raiz_destino / "2024" / "INTERRUPCAO TESTE_202.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(img2["bytes"])

        # O arquivo original e excedente ainda existem
        self.assertTrue(img1["caminho_abs"].is_file())
        self.assertTrue(img2["caminho_abs"].is_file())

        # Retomada
        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        res = executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)
        self.assertTrue(res["sucesso"])

        # Destino íntegro
        self.assertTrue(dest.is_file())
        self.assertEqual(dest.read_bytes(), img2["bytes"])
        # Original e excedentes devidamente limpos
        self.assertFalse(img1["caminho_abs"].is_file())
        self.assertFalse(img2["caminho_abs"].is_file())
        # Catálogo atualizado corretamente
        row = self.cat.execute("SELECT caminho, status FROM imagens WHERE ano=2024 AND sequencial='202'").fetchone()
        row_ant = self.cat.execute("SELECT status FROM imagens WHERE ano=2016 AND sequencial='101'").fetchone()[0]
        self.assertEqual(row_ant, "excluida_consolidacao")

    def test_api_integrada_apos_mudanca_de_caminhos(self):
        """Cenário: API /api/candidatos/{id}/foto funciona servindo foto de fotos selecionadas."""
        cid = "p_api"
        self.cadastrar_candidato_der(cid, "TESTE API FOTO")
        img = self.criar_imagem_disco("2024/MA/888.jpg", "pink")
        self.cadastrar_foto_catalogo(cid, 2024, "MA", "888", img)

        plano = construir_plano(self.cat, self.der, self.raiz_origem, self.raiz_destino, ids_filtro=[cid])
        executar_deduplicacao(plano, self.banco_sqlite, self.raiz_origem, self.raiz_destino, aplicar=True)

        leitor = LeitorCatalogo(self.banco_sqlite, self.raiz_origem)
        row = leitor.buscar([cid])[cid]
        self.assertEqual(row["foto_status"], "disponivel")
        # LeitorCatalogo localiza a foto no fotos selecionadas
        caminho_encontrado = leitor.arquivo(row)
        self.assertIsNotNone(caminho_encontrado)
        self.assertTrue(str(caminho_encontrado).endswith("TESTE API FOTO_888.jpg"))

        # Testar chamada ASGI
        async def get(path):
            mensagens = []
            async def receive():
                return {'type': 'http.request', 'body': b'', 'more_body': False}
            async def send(message):
                mensagens.append(message)
            await main.app(
                {
                    'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                    'method': 'GET', 'scheme': 'http', 'path': path, 'raw_path': path.encode(),
                    'query_string': b'', 'headers': [], 'server': ('test', 80), 'client': ('test', 1),
                },
                receive,
                send,
            )
            return mensagens

        with patch('frontend.fotos.leitor', return_value=leitor):
            mensagens = asyncio.run(get(f'/api/candidatos/{cid}/foto'))
            self.assertEqual(mensagens[0]['status'], 200)
            corpo = b''.join(m.get('body', b'') for m in mensagens[1:])
            self.assertEqual(corpo, img['bytes'])


if __name__ == '__main__':
    unittest.main()
