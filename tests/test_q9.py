"""Testes automatizados completos para a Questão 9 (Publicidade Eleitoral)."""

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

import duckdb

from bdr.der.esquema import TABELAS_DER, TABELAS_Q9, criar
from bdr.der.q9_bruto import (
    carregar_arquivo_despesas,
    extrair_despesas_uf,
    processar_q9,
    validar_q9,
)
from bdr.der.q9_classificacao import classificar_categoria, id_categoria


class Questao9Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

    def _criar_banco_base(self, caminho_duckdb: Path):
        """Cria um banco DER base com candidatos fictícios para 2018, 2020, 2022, 2024."""
        con = duckdb.connect(str(caminho_duckdb))
        criar(con)

        # Inserção de Município
        con.execute("""
            INSERT INTO "Municipio" VALUES
            ('MUN_RN_1', '17612', 'NATAL', 'RN', 'NORDESTE'),
            ('MUN_CE_1', '13897', 'FORTALEZA', 'CE', 'NORDESTE')
        """)

        # Inserção de Partido
        con.execute("""
            INSERT INTO "Partido" VALUES
            ('PART_13', 'PT', 'Partido dos Trabalhadores', 13),
            ('PART_40', 'PSB', 'Partido Socialista Brasileiro', 40)
        """)

        # Inserção de Eleições (incluindo 1º e 2º turnos)
        con.execute("""
            INSERT INTO "Eleicao" VALUES
            ('ELE_2018_1', 2018, 'Gerais', 1, 'Governador', '2018-10-07'),
            ('ELE_2018_2', 2018, 'Gerais', 2, 'Governador', '2018-10-28'),
            ('ELE_2020_1', 2020, 'Municipal', 1, 'Prefeito', '2020-11-15'),
            ('ELE_2022_1', 2022, 'Gerais', 1, 'Deputado Federal', '2022-10-02'),
            ('ELE_2024_1', 2024, 'Municipal', 1, 'Vereador', '2024-10-06')
        """)

        # Inserção de Candidatos
        con.execute("""
            INSERT INTO "Candidato" VALUES
            ('CAND_1', '123456', 'MARIA DA SILVA', '1980-01-01', 'FEMININO', 'PARDA', 'PROFESSORA'),
            ('CAND_2', '654321', 'JOAO DE SOUZA', '1975-05-10', 'MASCULINO', 'BRANCA', 'ADVOGADO')
        """)

        # Inserção de Candidaturas:
        # CANDIDATURA 1: 2018, Turno 1 (CAND_1, sq=1001)
        # CANDIDATURA 2: 2018, Turno 2 (CAND_1, sq=1001) - Segundo Turno!
        # CANDIDATURA 3: 2020, Turno 1 (CAND_1, sq=2001)
        # CANDIDATURA 4: 2022, Turno 1 (CAND_2, sq=3001)
        # CANDIDATURA 5: 2024, Turno 1 (CAND_2, sq=4001)
        con.execute("""
            INSERT INTO "Candidatura" VALUES
            ('CANDIDATURA_2018_T1', 'ELE_2018_1', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 38, 'DEFERIDO', '1001', 'SUPERIOR', 10000.0, NULL),
            ('CANDIDATURA_2018_T2', 'ELE_2018_2', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 38, 'DEFERIDO', '1001', 'SUPERIOR', 10000.0, NULL),
            ('CANDIDATURA_2020_T1', 'ELE_2020_1', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 40, 'DEFERIDO', '2001', 'SUPERIOR', 15000.0, NULL),
            ('CANDIDATURA_2022_T1', 'ELE_2022_1', 'CAND_2', 'MUN_CE_1', 'PART_40', 'CE', 'JOAO', 40, 47, 'DEFERIDO', '3001', 'SUPERIOR', 50000.0, NULL),
            ('CANDIDATURA_2024_T1', 'ELE_2024_1', 'CAND_2', 'MUN_CE_1', 'PART_40', 'CE', 'JOAO', 40, 49, 'DEFERIDO', '4001', 'SUPERIOR', 60000.0, NULL)
        """)

        # Inserção de Cargo
        con.execute("""
            INSERT INTO "Cargo" VALUES
            ('CARGO_1', 'Governador', 'CANDIDATURA_2018_T1'),
            ('CARGO_2', 'Governador', 'CANDIDATURA_2018_T2'),
            ('CARGO_3', 'Prefeito', 'CANDIDATURA_2020_T1'),
            ('CARGO_4', 'Deputado Federal', 'CANDIDATURA_2022_T1'),
            ('CARGO_5', 'Vereador', 'CANDIDATURA_2024_T1')
        """)
        con.close()

    def test_classificacao_publicidade(self):
        """Testa regras do de-para de classificação e grupos analíticos de publicidade."""
        casos = [
            ("Publicidade por materiais impressos", "IMPRESSOS", True),
            ("Publicidade por adesivos", "IMPRESSOS", True),
            ("Publicidade por jornais e revistas", "IMPRESSOS", True),
            ("Despesa com Impulsionamento de Conteúdos", "DIGITAL", True),
            ("Impulsionamento de conteúdos", "DIGITAL", True),
            ("Criação e inclusão de páginas na internet", "DIGITAL", True),
            ("Produção de programas de rádio, televisão ou vídeo", "AUDIOVISUAL", True),
            ("Produção de jingles, vinhetas e slogans", "SONORA", True),
            ("Publicidade por carros de som", "SONORA", True),
            ("Eventos de promoção da candidatura", "EVENTOS", True),
            ("Comícios", "EVENTOS", True),
            ("Combustíveis e lubrificantes", "NAO_PUBLICIDADE", False),
            ("Serviços advocatícios", "NAO_PUBLICIDADE", False),
            ("Serviços contábeis", "NAO_PUBLICIDADE", False),
            ("Despesas com pessoal", "NAO_PUBLICIDADE", False),
            ("Encargos financeiros, taxas bancárias e/ou op. cartão de crédito", "NAO_PUBLICIDADE", False),
            ("Categoria Estranha Qualquer", "NAO_CLASSIFICADO", False),
            (None, "NAO_CLASSIFICADO", False),
            ("", "NAO_CLASSIFICADO", False),
        ]
        for origem, grupo_esperado, eh_pub_esperado in casos:
            cat_id, grupo, eh_pub = classificar_categoria(origem)
            self.assertEqual(grupo, grupo_esperado, f"Falha no grupo de: {origem}")
            self.assertEqual(eh_pub, eh_pub_esperado, f"Falha em eh_publicidade de: {origem}")
            self.assertTrue(len(cat_id) == 32)  # Hash MD5

    def test_extracao_zip(self):
        """Testa extração de CSVs por UF de dentro de arquivo ZIP."""
        zip_path = self.raiz / "teste_despesas.zip"
        csv_conteudo = "AA_ELEICAO;SG_UF;SQ_CANDIDATO;VR_DESPESA_CONTRATADA;DS_ORIGEM_DESPESA\n2022;RN;3001;150,00;Publicidade por adesivos\n"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("despesas_contratadas_candidatos_2022_RN.csv", csv_conteudo.encode("latin-1"))

        raw_dir = self.raiz / "raw"
        arquivos = extrair_despesas_uf(zip_path, raw_dir, 2022, ["RN"])
        self.assertEqual(len(arquivos), 1)
        self.assertTrue(arquivos[0].exists())
        self.assertIn("Publicidade por adesivos", arquivos[0].read_text(encoding="utf-8"))

    def test_reconhecimento_aliases_layouts_2018_a_2024(self):
        """Testa suporte a layouts com AA_ELEICAO, ST_TURNO, TP_PRESTACAO_CONTAS e outros aliases."""
        con = duckdb.connect()
        con.execute("CREATE TEMP TABLE stg_q9_despesas_brutas (" +
                    ", ".join(f"{c} VARCHAR" for c in [
                        "ano", "turno", "tipo_prestacao_contas", "dt_prestacao_contas",
                        "cd_eleicao", "uf", "sq_candidato", "sq_despesa", "dt_despesa",
                        "origem_despesa", "descricao_despesa", "valor_contratado", "cd_cargo"
                    ]) + ", arquivo_origem VARCHAR)")

        # Layout com aliases típicos de 2018
        csv_2018 = self.raiz / "despesas_2018.csv"
        csv_2018.write_text(
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;90001;01/09/2018;Publicidade por materiais impressos;Panfletos;1.250,50;03\n",
            encoding="utf-8"
        )
        carregar_arquivo_despesas(con, csv_2018, 2018)

        # Layout alternativo com ANO_ELEICAO, NR_TURNO
        csv_2022 = self.raiz / "despesas_2022.csv"
        csv_2022.write_text(
            "ANO_ELEICAO;NR_TURNO;TIPO_PRESTACAO_CONTAS;DATA_PRESTACAO_CONTAS;CODIGO_ELEICAO;SIGLA_UF;SEQUENCIAL_CANDIDATO;"
            "SEQUENCIAL_DESPESA;DATA_DESPESA;DS_ORIGEM_DESPESA;DESCRICAO_DESPESA;VALOR_DESPESA_CONTRATADA;CODIGO_CARGO\n"
            "2022;1;Final;20/10/2022;546;CE;3001;90002;15/09/2022;Despesa com Impulsionamento de Conteúdos;Anúncios;3.500,00;06\n",
            encoding="utf-8"
        )
        carregar_arquivo_despesas(con, csv_2022, 2022)

        linhas = con.execute("SELECT ano, turno, tipo_prestacao_contas, origem_despesa, valor_contratado FROM stg_q9_despesas_brutas ORDER BY ano").fetchall()
        self.assertEqual(len(linhas), 2)
        self.assertEqual(linhas[0], ('2018', '1', 'Final', 'Publicidade por materiais impressos', '1.250,50'))
        self.assertEqual(linhas[1], ('2022', '1', 'Final', 'Despesa com Impulsionamento de Conteúdos', '3.500,00'))

    def test_carga_completa_deduplicacao_segundo_turno_e_metricas(self):
        """Testa o pipeline completo de Q9 incluindo deduplicação, segundo turno, não encontrados e métricas."""
        banco = self.raiz / "der_teste.duckdb"
        self._criar_banco_base(banco)

        # Prepara pasta de trabalho mock com ZIPs contendo dados de teste
        trabalho = self.raiz / "trabalho_q9"
        zips_dir = trabalho / "zips"
        zips_dir.mkdir(parents=True, exist_ok=True)

        # Criar ZIP 2018 para RN:
        # - Despesa 1: Candidato 1001, Turno 1 (Vincula a CANDIDATURA_2018_T1)
        # - Despesa 2: Candidato 1001, Turno 2 (Vincula a CANDIDATURA_2018_T2) - Não duplica!
        # - Despesa 3: Candidato 1001, Turno 1 em Parcial e Final (Deduplicação por SQ_DESPESA)
        # - Despesa 4: Combustível (Não publicidade)
        # - Despesa 5: Candidato 9999 inexistente (Rejeitada)
        zip_2018 = zips_dir / "prestacao_de_contas_eleitorais_candidatos_2018.zip"
        with zipfile.ZipFile(zip_2018, "w") as z:
            csv_rn = (
                "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
                "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
                # Turno 1
                "2018;1;Final;10/11/2018;297;RN;1001;D101;01/09/2018;Publicidade por materiais impressos;Impressos T1;1000,00;03\n"
                # Turno 2
                "2018;2;Final;10/11/2018;297;RN;1001;D102;15/10/2018;Publicidade por adesivos;Adesivos T2;500,00;03\n"
                # Duplicata de D101 em prestação parcial (deve ser descartada na deduplicação)
                "2018;1;1ª Parcial;15/09/2018;297;RN;1001;D101;01/09/2018;Publicidade por materiais impressos;Impressos T1;1000,00;03\n"
                # Combustível (Não publicidade)
                "2018;1;Final;10/11/2018;297;RN;1001;D103;05/09/2018;Combustíveis e lubrificantes;Gasolina;300,00;03\n"
                # Candidato sem cadastro
                "2018;1;Final;10/11/2018;297;RN;9999;D104;01/09/2018;Publicidade por materiais impressos;Sem Candidato;200,00;03\n"
            )
            z.writestr("despesas_contratadas_candidatos_2018_RN.csv", csv_rn.encode("latin-1"))

        # Executa processar_q9
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            # 1. Verifica Despesa_Campanha (deve ter exatamente 3 despesas: D101, D102, D103)
            despesas = con.execute('SELECT sequencial_despesa_tse, id_candidatura, valor_contratado FROM "Despesa_Campanha" ORDER BY sequencial_despesa_tse').fetchall()
            self.assertEqual(len(despesas), 3)

            # D101 vinculada ao Turno 1
            self.assertEqual(despesas[0], ('D101', 'CANDIDATURA_2018_T1', 1000.00))
            # D102 vinculada ao Turno 2
            self.assertEqual(despesas[1], ('D102', 'CANDIDATURA_2018_T2', 500.00))
            # D103 vinculada ao Turno 1
            self.assertEqual(despesas[2], ('D103', 'CANDIDATURA_2018_T1', 300.00))

            # 2. Verifica Despesa_Rejeitada (deve ter exatamente D104 com CANDIDATO_NAO_ENCONTRADO)
            rejeitadas = con.execute('SELECT sq_candidato, motivo_rejeicao, valor_contratado FROM "Despesa_Rejeitada"').fetchall()
            self.assertEqual(len(rejeitadas), 1)
            self.assertEqual(rejeitadas[0], ('9999', 'CANDIDATO_NAO_ENCONTRADO', 200.00))

            # 3. Verifica atualização de Candidatura.publicidade_propaganda
            # Turno 1 tem R$ 1000 de impressos (combustível R$ 300 NÃO deve entrar)
            pub_t1 = con.execute("SELECT publicidade_propaganda FROM \"Candidatura\" WHERE id_candidatura = 'CANDIDATURA_2018_T1'").fetchone()[0]
            self.assertEqual(pub_t1, 1000.0)

            # Turno 2 tem R$ 500 de adesivos
            pub_t2 = con.execute("SELECT publicidade_propaganda FROM \"Candidatura\" WHERE id_candidatura = 'CANDIDATURA_2018_T2'").fetchone()[0]
            self.assertEqual(pub_t2, 500.0)

            # 4. Testa IDEMPOTÊNCIA: rodar novamente não duplica nada
            processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)
            total_apos_reexec = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total_apos_reexec, 3)

        finally:
            con.close()

    def test_compatibilidade_consultas_sql(self):
        """Testa todas as 8 consultas SQL de bdr/consultas_q9.sql contra um banco com dados válidos."""
        banco = self.raiz / "der_consultas.duckdb"
        self._criar_banco_base(banco)

        con = duckdb.connect(str(banco))
        try:
            # Insere dados de categorias e despesas
            con.execute("""
                INSERT INTO "Categoria_Despesa" VALUES
                ('CAT_IMP', 'Publicidade por materiais impressos', 'IMPRESSOS', true),
                ('CAT_DIG', 'Despesa com Impulsionamento de Conteúdos', 'DIGITAL', true),
                ('CAT_COMB', 'Combustíveis e lubrificantes', 'NAO_PUBLICIDADE', false)
            """)

            con.execute("""
                INSERT INTO "Despesa_Campanha" VALUES
                ('DESP_1', 'CANDIDATURA_2018_T1', 'CAT_IMP', 2018, 'RN', '297', '1001', 'D1', 1, '2018-09-01', 'Panfletos', 1000.00, 'Final'),
                ('DESP_2', 'CANDIDATURA_2018_T2', 'CAT_IMP', 2018, 'RN', '297', '1001', 'D2', 2, '2018-10-15', 'Cartazes', 500.00, 'Final'),
                ('DESP_3', 'CANDIDATURA_2022_T1', 'CAT_DIG', 2022, 'CE', '546', '3001', 'D3', 1, '2022-09-10', 'Anúncio Web', 2500.00, 'Final'),
                ('DESP_4', 'CANDIDATURA_2022_T1', 'CAT_COMB', 2022, 'CE', '546', '3001', 'D4', 1, '2022-09-12', 'Gasolina', 400.00, 'Final')
            """)

            con.execute("""
                INSERT INTO "Despesa_Rejeitada" VALUES
                ('REJ_1', 'CANDIDATO_NAO_ENCONTRADO', 2018, 'RN', '297', '9999', 'D9', 1, '2018-09-01', 'Publicidade por adesivos', 'Adesivo', 150.00)
            """)

            # Carrega arquivo SQL
            sql_file = Path("bdr/consultas_q9.sql")
            self.assertTrue(sql_file.is_file(), "bdr/consultas_q9.sql não existe")
            conteudo = sql_file.read_text(encoding="utf-8")

            # Separa as consultas por blocos demarcados por '-- name:' (ignora cabeçalho antes do primeiro -- name:)
            blocos = [b for b in conteudo.split("-- name:")[1:] if b.strip()]
            self.assertGreaterEqual(len(blocos), 8, "Devem existir ao menos 8 consultas em consultas_q9.sql")

            for bloco in blocos:
                linhas = bloco.strip().splitlines()
                nome_consulta = linhas[0].strip()
                sql_puro = "\n".join(l for l in linhas[1:] if not l.strip().startswith("--")).strip()
                if not sql_puro:
                    continue
                # Executa cada consulta individual
                res = con.execute(sql_puro).fetchall()
                self.assertIsNotNone(res, f"Consulta {nome_consulta} falhou ao retornar resultado")
        finally:
            con.close()

    def test_conversao_valores_monetarios(self):
        """Testa conversão de valores monetários no padrão brasileiro para DECIMAL(18,2)."""
        con = duckdb.connect()
        # Testa que strings vazias e nulos resultam em NULL (não 0.00)
        query = """
            SELECT
                try_cast(replace(replace('1.234.567,89', '.', ''), ',', '.') AS DECIMAL(18,2)) AS v1,
                try_cast(replace(replace('500,00', '.', ''), ',', '.') AS DECIMAL(18,2)) AS v2,
                try_cast(replace(replace('-150,50', '.', ''), ',', '.') AS DECIMAL(18,2)) AS v3,
                try_cast(replace(replace(nullif(trim(''), ''), '.', ''), ',', '.') AS DECIMAL(18,2)) AS v4,
                try_cast(replace(replace(nullif(trim(NULL), ''), '.', ''), ',', '.') AS DECIMAL(18,2)) AS v5
        """
        v1, v2, v3, v4, v5 = con.execute(query).fetchone()
        self.assertEqual(float(v1), 1234567.89)
        self.assertEqual(float(v2), 500.00)
        self.assertEqual(float(v3), -150.50)
        self.assertIsNone(v4)
        self.assertIsNone(v5)

    def test_validacao_publicacao_incremental(self):
        """Testa regras de validação da publicação incremental de Q9."""
        from bdr.der.q9_motherduck import publicar_q9

        # Arquivo inexistente deve falhar
        with self.assertRaises(FileNotFoundError):
            publicar_q9(self.raiz / "arquivo_fantasma.duckdb")


if __name__ == "__main__":
    unittest.main()
