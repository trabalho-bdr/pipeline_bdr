"""Testes automatizados completos para a Questão 9 (Publicidade Eleitoral).

Contempla os 10 cenários obrigatórios de teste e compatibilidade total com a pipeline.
"""

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
from bdr.der.q9_motherduck import publicar_q9, validar_candidaturas_remotas


class Questao9Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.raiz = Path(self.tmp.name)

    def _criar_banco_base(self, caminho_duckdb: Path):
        """Cria um banco DER base com candidatos fictícios para 2018, 2020, 2022, 2024."""
        con = duckdb.connect(str(caminho_duckdb))
        criar(con)

        con.execute("""
            INSERT INTO "Municipio" VALUES
            ('MUN_RN_1', '17612', 'NATAL', 'RN', 'NORDESTE'),
            ('MUN_CE_1', '13897', 'FORTALEZA', 'CE', 'NORDESTE');

            INSERT INTO "Partido" VALUES
            ('PART_13', 'PT', 'Partido dos Trabalhadores', 13),
            ('PART_40', 'PSB', 'Partido Socialista Brasileiro', 40);

            INSERT INTO "Eleicao" VALUES
            ('ELE_2018_1', 2018, 'Gerais', 1, 'Governador', '2018-10-07'),
            ('ELE_2018_2', 2018, 'Gerais', 2, 'Governador', '2018-10-28'),
            ('ELE_2020_1', 2020, 'Municipal', 1, 'Prefeito', '2020-11-15'),
            ('ELE_2022_1', 2022, 'Gerais', 1, 'Deputado Federal', '2022-10-02'),
            ('ELE_2024_1', 2024, 'Municipal', 1, 'Vereador', '2024-10-06');

            INSERT INTO "Candidato" VALUES
            ('CAND_1', '123456', 'MARIA DA SILVA', '1980-01-01', 'FEMININO', 'PARDA', 'PROFESSORA'),
            ('CAND_2', '654321', 'JOAO DE SOUZA', '1975-05-10', 'MASCULINO', 'BRANCA', 'ADVOGADO');

            INSERT INTO "Candidatura" VALUES
            ('CANDIDATURA_2018_T1', 'ELE_2018_1', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 38, 'DEFERIDO', '1001', 'SUPERIOR', 10000.0, NULL),
            ('CANDIDATURA_2018_T2', 'ELE_2018_2', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 38, 'DEFERIDO', '1001', 'SUPERIOR', 10000.0, NULL),
            ('CANDIDATURA_2020_T1', 'ELE_2020_1', 'CAND_1', 'MUN_RN_1', 'PART_13', 'RN', 'MARIA', 13, 40, 'DEFERIDO', '2001', 'SUPERIOR', 15000.0, NULL),
            ('CANDIDATURA_2022_T1', 'ELE_2022_1', 'CAND_2', 'MUN_CE_1', 'PART_40', 'CE', 'JOAO', 40, 47, 'DEFERIDO', '3001', 'SUPERIOR', 50000.0, NULL),
            ('CANDIDATURA_2024_T1', 'ELE_2024_1', 'CAND_2', 'MUN_CE_1', 'PART_40', 'CE', 'JOAO', 40, 49, 'DEFERIDO', '4001', 'SUPERIOR', 60000.0, NULL);

            INSERT INTO "Cargo" VALUES
            ('CARGO_1', 'Governador', 'CANDIDATURA_2018_T1'),
            ('CARGO_2', 'Governador', 'CANDIDATURA_2018_T2'),
            ('CARGO_3', 'Prefeito', 'CANDIDATURA_2020_T1'),
            ('CARGO_4', 'Deputado Federal', 'CANDIDATURA_2022_T1'),
            ('CARGO_5', 'Vereador', 'CANDIDATURA_2024_T1');
        """)
        con.close()

    def _criar_zip_despesas(self, zips_dir: Path, ano: int, uf: str, conteudo_csv: str):
        zips_dir.mkdir(parents=True, exist_ok=True)
        zip_path = zips_dir / f"prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr(f"despesas_contratadas_candidatos_{ano}_{uf}.csv", conteudo_csv.encode("latin-1"))
        return zip_path

    # =========================================================================
    # 10 CENÁRIOS OBRIGATÓRIOS EXIGIDOS NA PIPELINE DA Q9
    # =========================================================================

    def test_cenario_1_duas_despesas_legitimas_compartilham_identificadores_parciais(self):
        """Cenário 1: Duas despesas legítimas que compartilham atributos parciais (mesmo candidato,

        data e valor, mas sq_despesa ou documentos diferentes) NÃO podem ser descartadas.
        """
        banco = self.raiz / "banco_cenario1.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario1"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO;NR_DOCUMENTO\n"
            # Despesa 1: Panfletos
            "2018;1;Final;10/11/2018;297;RN;1001;D_001;01/09/2018;Publicidade por materiais impressos;Panfletos Lote 1;500,00;03;DOC_101\n"
            # Despesa 2: Mesma data, mesmo valor, mesma categoria, mesmo candidato, mas sq_despesa e documento distintos
            "2018;1;Final;10/11/2018;297;RN;1001;D_002;01/09/2018;Publicidade por materiais impressos;Panfletos Lote 2;500,00;03;DOC_102\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            linhas = con.execute("""
                SELECT sequencial_despesa_tse, valor_contratado, descricao_despesa
                FROM "Despesa_Campanha"
                ORDER BY sequencial_despesa_tse
            """).fetchall()
            self.assertEqual(len(linhas), 2, "Ambas as despesas legítimas devem ser mantidas!")
            self.assertEqual(linhas[0][0], "D_001")
            self.assertEqual(linhas[1][0], "D_002")
            total_valor = con.execute('SELECT sum(valor_contratado) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(float(total_valor), 1000.00)
        finally:
            con.close()

    def test_cenario_2_despesa_repetida_em_prestacoes_diferentes(self):
        """Cenário 2: Uma despesa repetida em prestações de contas diferentes (Parcial vs Final)

        deve ser consolidada elegendo a versão Final/Retificadora mais recente, sem duplicar o valor.
        """
        banco = self.raiz / "banco_cenario2.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario2"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO;NR_DOCUMENTO\n"
            # Lançamento na 1ª Parcial
            "2018;1;1ª Parcial;15/09/2018;297;RN;1001;D_REP;01/09/2018;Publicidade por materiais impressos;Cartazes;1000,00;03;NF_99\n"
            # Mesmo lançamento reapresentado na Prestação Final
            "2018;1;Final;10/11/2018;297;RN;1001;D_REP;01/09/2018;Publicidade por materiais impressos;Cartazes;1000,00;03;NF_99\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            despesas = con.execute("""
                SELECT count(*), sum(valor_contratado), max(tipo_prestacao_contas)
                FROM "Despesa_Campanha"
                WHERE sequencial_despesa_tse = 'D_REP'
            """).fetchone()
            self.assertEqual(despesas[0], 1, "A despesa não pode ser inserida duas vezes!")
            self.assertEqual(float(despesas[1]), 1000.00, "O valor não pode ser somado em dobro!")
            self.assertEqual(despesas[2], "Final", "Deve priorizar a versão Final sobre a Parcial")
        finally:
            con.close()

    def test_cenario_3_candidatura_com_primeiro_e_segundo_turnos(self):
        """Cenário 3: Candidato com primeiro e segundo turnos deve ter cada despesa vinculada

        estritamente à candidatura correta, sem duplicação entre os turnos.
        """
        banco = self.raiz / "banco_cenario3.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario3"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            # Despesa de Turno 1
            "2018;1;Final;10/11/2018;297;RN;1001;D_T1;01/09/2018;Publicidade por materiais impressos;Impressos T1;700,00;03\n"
            # Despesa de Turno 2
            "2018;2;Final;10/11/2018;297;RN;1001;D_T2;15/10/2018;Publicidade por adesivos;Adesivos T2;350,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            linhas = con.execute("""
                SELECT sequencial_despesa_tse, id_candidatura, valor_contratado
                FROM "Despesa_Campanha"
                ORDER BY sequencial_despesa_tse
            """).fetchall()
            self.assertEqual(len(linhas), 2)
            self.assertEqual(linhas[0], ("D_T1", "CANDIDATURA_2018_T1", 700.00))
            self.assertEqual(linhas[1], ("D_T2", "CANDIDATURA_2018_T2", 350.00))

            # Verifica que a view calcula os totais separados por candidatura
            view_res = con.execute("""
                SELECT id_candidatura, total_publicidade
                FROM "vw_publicidade_candidatura"
                ORDER BY id_candidatura
            """).fetchall()
            self.assertEqual(view_res, [("CANDIDATURA_2018_T1", 700.0), ("CANDIDATURA_2018_T2", 350.0)])
        finally:
            con.close()

    def test_cenario_4_despesa_sem_candidatura_correspondente(self):
        """Cenário 4: Despesa de candidato inexistente não pode entrar em Despesa_Campanha

        e deve ser registrada em Despesa_Rejeitada com o motivo CANDIDATO_NAO_ENCONTRADO.
        """
        banco = self.raiz / "banco_cenario4.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario4"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            # Candidato 99999 não cadastrado
            "2018;1;Final;10/11/2018;297;RN;99999;D_FANTASMA;01/09/2018;Publicidade por materiais impressos;Santinhos;250,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            total_vinculadas = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total_vinculadas, 0, "Despesa órfã não pode ser vinculada!")

            rejeitadas = con.execute("""
                SELECT sq_candidato, motivo_rejeicao, valor_contratado
                FROM "Despesa_Rejeitada"
            """).fetchall()
            self.assertEqual(len(rejeitadas), 1)
            self.assertEqual(rejeitadas[0], ("99999", "CANDIDATO_NAO_ENCONTRADO", 250.00))
        finally:
            con.close()

    def test_cenario_5_despesa_com_correspondencia_ambigua(self):
        """Cenário 5: Candidato com 1º e 2º turnos recebendo despesa sem turno informado

        deve ser rejeitada com motivo CORRESPONDENCIA_AMBIGUA, sem vincular arbitrariamente.
        """
        banco = self.raiz / "banco_cenario5.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario5"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            # ST_TURNO vazio para candidato 1001 (que disputou 1º e 2º turnos)
            "2018;;Final;10/11/2018;297;RN;1001;D_AMBIGUA;01/09/2018;Publicidade por materiais impressos;Sem Turno;450,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            total_vinculadas = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total_vinculadas, 0, "Despesa ambígua não pode ser vinculada arbitrariamente!")

            rejeitadas = con.execute("""
                SELECT sq_candidato, motivo_rejeicao, valor_contratado
                FROM "Despesa_Rejeitada"
            """).fetchall()
            self.assertEqual(len(rejeitadas), 1)
            self.assertEqual(rejeitadas[0], ("1001", "CORRESPONDENCIA_AMBIGUA", 450.00))
        finally:
            con.close()

    def test_cenario_6_identificadores_locais_e_remotos_iguais_candidaturas_diferentes(self):
        """Cenário 6: Validação de MotherDuck deve recusar publicação se id_candidatura existir no

        remoto mas pertencer a um candidato diferente (atributos divergentes: sequencial/uf).
        """
        banco_local = self.raiz / "banco_local_c6.duckdb"
        banco_remoto = self.raiz / "banco_remoto_c6.duckdb"

        # Banco local possui Maria (sq=1001, RN, 2018)
        self._criar_banco_base(banco_local)
        trabalho = self.raiz / "trab_c6"
        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D1;01/09/2018;Publicidade por materiais impressos;Panfleto;600,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco_local, trabalho=trabalho)

        # Banco remoto possui CANDIDATURA_2018_T1, porém com sequencial diferente (outro candidato!)
        self._criar_banco_base(banco_remoto)
        con_remoto = duckdb.connect(str(banco_remoto))
        con_remoto.execute("""
            UPDATE "Candidatura"
            SET sequencial = '9999_DIVERGENTE'
            WHERE id_candidatura = 'CANDIDATURA_2018_T1'
        """)
        con_remoto.close()

        # Simula conexão MotherDuck usando multi-banco local
        sim_con = duckdb.connect()
        sim_con.execute(f"ATTACH '{banco_remoto.as_posix()}' AS \"pipeline_bdr_der_completo\"")

        with self.assertRaises(ValueError) as ctx:
            publicar_q9(banco_local, nome_banco="pipeline_bdr_der_completo", con=sim_con)

        self.assertIn("Publicação recusada", str(ctx.exception))
        self.assertIn("divergências cadastrais", str(ctx.exception))

        # Confirma que nenhuma despesa foi publicada no banco remoto
        rem_desp = sim_con.execute("""
            SELECT count(*) FROM information_schema.tables
            WHERE table_catalog='pipeline_bdr_der_completo' AND table_schema='main' AND table_name='Despesa_Campanha'
        """).fetchone()[0]
        if rem_desp > 0:
            total = sim_con.execute('SELECT count(*) FROM "pipeline_bdr_der_completo".main."Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total, 0, "Nenhuma despesa pode ter sido publicada!")
        sim_con.close()

    def test_cenario_7_reexecucao_sem_duplicacao_de_valores(self):
        """Cenário 7: Executar a carga duas vezes para a mesma fonte não pode duplicar valores nem

        gerar registros redundantes (idempotência local e remota).
        """
        banco = self.raiz / "banco_cenario7.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario7"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_IDEMP;01/09/2018;Publicidade por materiais impressos;Adesivos;1200,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)

        # Execução 1
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)
        con = duckdb.connect(str(banco))
        total_1 = con.execute('SELECT count(*), sum(valor_contratado) FROM "Despesa_Campanha"').fetchone()
        con.close()

        # Execução 2
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)
        con = duckdb.connect(str(banco))
        total_2 = con.execute('SELECT count(*), sum(valor_contratado) FROM "Despesa_Campanha"').fetchone()
        con.close()

        self.assertEqual(total_1, total_2)
        self.assertEqual(total_2[0], 1)
        self.assertEqual(float(total_2[1]), 1200.00)

        # Testa também publicação idempotente duas vezes no remoto
        banco_remoto = self.raiz / "remoto_cenario7.duckdb"
        self._criar_banco_base(banco_remoto)
        sim_con = duckdb.connect()
        sim_con.execute(f"ATTACH '{banco_remoto.as_posix()}' AS \"pipeline_bdr_der_completo\"")

        publicar_q9(banco, nome_banco="pipeline_bdr_der_completo", con=sim_con)
        rem_1 = sim_con.execute('SELECT count(*), sum(valor_contratado) FROM "pipeline_bdr_der_completo".main."Despesa_Campanha"').fetchone()

        publicar_q9(banco, nome_banco="pipeline_bdr_der_completo", con=sim_con)
        rem_2 = sim_con.execute('SELECT count(*), sum(valor_contratado) FROM "pipeline_bdr_der_completo".main."Despesa_Campanha"').fetchone()

        self.assertEqual(rem_1, rem_2)
        self.assertEqual(rem_2[0], 1)
        self.assertEqual(float(rem_2[1]), 1200.00)
        sim_con.close()

    def test_cenario_8_atualizacao_remove_registros_obsoletos(self):
        """Cenário 8: Atualização com exclusão/correção na fonte deve remover registros que deixaram

        de existir no escopo (ano, uf) sem deixar dados obsoletos.
        """
        banco = self.raiz / "banco_cenario8.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cenario8"

        # Carga inicial com 2 despesas
        csv_v1 = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_MANTER;01/09/2018;Publicidade por materiais impressos;Panfletos;500,00;03\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_OBSOLETA;01/09/2018;Publicidade por materiais impressos;Cancelado;300,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv_v1)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        self.assertEqual(con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0], 2)
        con.close()

        # Atualização da fonte: D_OBSOLETA foi removida
        csv_v2 = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_MANTER;01/09/2018;Publicidade por materiais impressos;Panfletos;500,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv_v2)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            despesas_restantes = con.execute('SELECT sequencial_despesa_tse FROM "Despesa_Campanha"').fetchall()
            self.assertEqual(len(despesas_restantes), 1)
            self.assertEqual(despesas_restantes[0][0], "D_MANTER")
        finally:
            con.close()

    def test_cenario_9_falha_publicacao_com_reversao_transacao(self):
        """Cenário 9: Falha inesperada durante a publicação deve executar ROLLBACK e deixar o estado

        remoto completamente revertido e íntegro.
        """
        banco_local = self.raiz / "banco_local_c9.duckdb"
        banco_remoto = self.raiz / "banco_remoto_c9.duckdb"
        self._criar_banco_base(banco_local)
        self._criar_banco_base(banco_remoto)

        # Carga inicial válida no local
        trabalho = self.raiz / "trab_c9"
        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_OK;01/09/2018;Publicidade por materiais impressos;Panfleto;400,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco_local, trabalho=trabalho)

        # Publica estado 1 com sucesso
        sim_con = duckdb.connect()
        sim_con.execute(f"ATTACH '{banco_remoto.as_posix()}' AS \"pipeline_bdr_der_completo\"")
        publicar_q9(banco_local, nome_banco="pipeline_bdr_der_completo", con=sim_con)
        self.assertEqual(sim_con.execute('SELECT count(*) FROM "pipeline_bdr_der_completo".main."Despesa_Campanha"').fetchone()[0], 1)

        # Simula uma falha inesperada durante a execução da transação (ex: erro de view/disco)
        from unittest.mock import patch

        with patch("bdr.der.q9_motherduck.criar_views_q9", side_effect=RuntimeError("Falha de IO/Rede simulada no commit")):
            with self.assertRaisesRegex(RuntimeError, "Falha de IO/Rede simulada"):
                publicar_q9(banco_local, nome_banco="pipeline_bdr_der_completo", con=sim_con)

        # Verifica que o banco remoto executou ROLLBACK e preservou o estado anterior intacto (1 registro)
        self.assertEqual(sim_con.execute('SELECT count(*) FROM "pipeline_bdr_der_completo".main."Despesa_Campanha"').fetchone()[0], 1)
        sim_con.close()

    def test_cenario_10_candidatura_e_outras_tabelas_permanecem_inalteradas(self):
        """Cenário 10: Executar a publicação de Q9 não pode modificar nenhum dado de Candidatura ou

        das outras tabelas fora da Q9 (Q3 e Q10 intactas).
        """
        banco_local = self.raiz / "banco_local_c10.duckdb"
        banco_remoto = self.raiz / "banco_remoto_c10.duckdb"
        self._criar_banco_base(banco_local)
        self._criar_banco_base(banco_remoto)

        trabalho = self.raiz / "trab_c10"
        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_10;01/09/2018;Publicidade por materiais impressos;Banner;1500,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco_local, trabalho=trabalho)

        sim_con = duckdb.connect()
        sim_con.execute(f"ATTACH '{banco_remoto.as_posix()}' AS \"pipeline_bdr_der_completo\"")

        # Snapshot exato de Candidatura e Municipio antes da publicação
        cand_antes = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Candidatura" ORDER BY id_candidatura').fetchall()
        mun_antes = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Municipio" ORDER BY id_municipio').fetchall()
        ele_antes = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Eleicao" ORDER BY id_eleicao').fetchall()

        # Executa publicação de Q9
        publicar_q9(banco_local, nome_banco="pipeline_bdr_der_completo", con=sim_con)

        cand_depois = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Candidatura" ORDER BY id_candidatura').fetchall()
        mun_depois = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Municipio" ORDER BY id_municipio').fetchall()
        ele_depois = sim_con.execute('SELECT * FROM "pipeline_bdr_der_completo".main."Eleicao" ORDER BY id_eleicao').fetchall()

        self.assertEqual(cand_antes, cand_depois, "Candidatura NÃO PODE sofrer nenhuma alteração em --publicar-q9!")
        self.assertEqual(mun_antes, mun_depois, "Municipio deve permanecer intacta!")
        self.assertEqual(ele_antes, ele_depois, "Eleicao deve permanecer intacta!")

        # Confirma que a view vw_publicidade_candidatura foi criada e calcula a métrica dinamicamente
        view_res = sim_con.execute("""
            SELECT id_candidatura, total_publicidade
            FROM "pipeline_bdr_der_completo".main."vw_publicidade_candidatura"
            WHERE id_candidatura = 'CANDIDATURA_2018_T1'
        """).fetchone()
        self.assertEqual(view_res, ("CANDIDATURA_2018_T1", 1500.0))
        sim_con.close()

    # =========================================================================
    # OUTROS TESTES DE SUPORTE E COMPATIBILIDADE
    # =========================================================================

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
            self.assertTrue(len(cat_id) == 32)

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

    def test_compatibilidade_consultas_sql(self):
        """Testa todas as 8 consultas SQL de bdr/consultas_q9.sql contra um banco com dados válidos."""
        banco = self.raiz / "der_consultas.duckdb"
        self._criar_banco_base(banco)

        con = duckdb.connect(str(banco))
        try:
            con.execute("""
                INSERT INTO "Categoria_Despesa" VALUES
                ('CAT_IMP', 'Publicidade por materiais impressos', 'IMPRESSOS', true),
                ('CAT_DIG', 'Despesa com Impulsionamento de Conteúdos', 'DIGITAL', true),
                ('CAT_COMB', 'Combustíveis e lubrificantes', 'NAO_PUBLICIDADE', false);

                INSERT INTO "Despesa_Campanha" VALUES
                ('DESP_1', 'CANDIDATURA_2018_T1', 'CAT_IMP', 2018, 'RN', '297', '1001', 'D1', 1, '2018-09-01', 'Panfletos', 1000.00, 'Final'),
                ('DESP_2', 'CANDIDATURA_2018_T2', 'CAT_IMP', 2018, 'RN', '297', '1001', 'D2', 2, '2018-10-15', 'Cartazes', 500.00, 'Final'),
                ('DESP_3', 'CANDIDATURA_2022_T1', 'CAT_DIG', 2022, 'CE', '546', '3001', 'D3', 1, '2022-09-10', 'Anúncio Web', 2500.00, 'Final'),
                ('DESP_4', 'CANDIDATURA_2022_T1', 'CAT_COMB', 2022, 'CE', '546', '3001', 'D4', 1, '2022-09-12', 'Gasolina', 400.00, 'Final');

                INSERT INTO "Despesa_Rejeitada" VALUES
                ('REJ_1', 'CANDIDATO_NAO_ENCONTRADO', 2018, 'RN', '297', '9999', 'D9', 1, '2018-09-01', 'Publicidade por adesivos', 'Adesivo', 150.00);
            """)

            sql_file = Path("bdr/consultas_q9.sql")
            self.assertTrue(sql_file.is_file(), "bdr/consultas_q9.sql não existe")
            conteudo = sql_file.read_text(encoding="utf-8")

            blocos = [b for b in conteudo.split("-- name:")[1:] if b.strip()]
            self.assertGreaterEqual(len(blocos), 8, "Devem existir ao menos 8 consultas em consultas_q9.sql")

            for bloco in blocos:
                linhas = bloco.strip().splitlines()
                nome_consulta = linhas[0].strip()
                sql_puro = "\n".join(l for l in linhas[1:] if not l.strip().startswith("--")).strip()
                if not sql_puro:
                    continue
                res = con.execute(sql_puro).fetchall()
                self.assertIsNotNone(res, f"Consulta {nome_consulta} falhou ao retornar resultado")
        finally:
            con.close()

    def test_conversao_valores_monetarios(self):
        """Testa conversão de valores monetários no padrão brasileiro para DECIMAL(18,2)."""
        con = duckdb.connect()
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

    def test_somente_q9_nao_modifica_candidatura(self):
        """Auditoria 1: Comprova que --somente-q9 trata Candidatura como estritamente somente-leitura.

        Nenhum registro ou coluna de Candidatura (incluindo publicidade_propaganda) pode ser alterado.
        """
        banco = self.raiz / "banco_leitura_cand.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_leitura_cand"

        # Preenche valor preexistente em Candidatura.publicidade_propaganda para atestar preservação
        con = duckdb.connect(str(banco))
        con.execute('UPDATE "Candidatura" SET publicidade_propaganda = 9999.50 WHERE id_candidatura = \'CANDIDATURA_2018_T1\'')
        cand_antes = con.execute('SELECT * FROM "Candidatura" ORDER BY id_candidatura').fetchall()
        ele_antes = con.execute('SELECT * FROM "Eleicao" ORDER BY id_eleicao').fetchall()
        part_antes = con.execute('SELECT * FROM "Partido" ORDER BY id_partido').fetchall()
        con.close()

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_TEST;01/09/2018;Publicidade por materiais impressos;Panfletos;500,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            cand_depois = con.execute('SELECT * FROM "Candidatura" ORDER BY id_candidatura').fetchall()
            ele_depois = con.execute('SELECT * FROM "Eleicao" ORDER BY id_eleicao').fetchall()
            part_depois = con.execute('SELECT * FROM "Partido" ORDER BY id_partido').fetchall()

            self.assertEqual(cand_antes, cand_depois, "Candidatura foi alterada! Deve ser estritamente somente-leitura.")
            self.assertEqual(ele_antes, ele_depois, "Eleicao foi alterada!")
            self.assertEqual(part_antes, part_depois, "Partido foi alterado!")

            # Verifica que o valor preexistente de publicidade_propaganda permanece intacto
            val_preservado = con.execute("""
                SELECT publicidade_propaganda FROM "Candidatura" WHERE id_candidatura = 'CANDIDATURA_2018_T1'
            """).fetchone()[0]
            self.assertEqual(val_preservado, 9999.50)
        finally:
            con.close()

    def test_totais_publicidade_acessiveis_pela_view_q9(self):
        """Auditoria 2: Comprova que os totais de publicidade são acessíveis pela view vw_publicidade_candidatura."""
        banco = self.raiz / "banco_view_totais.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_view_totais"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_PUB_1;01/09/2018;Publicidade por materiais impressos;Panfletos;400,00;03\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_PUB_2;05/09/2018;Despesa com Impulsionamento de Conteúdos;Anúncio;600,00;03\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_OPER;08/09/2018;Combustíveis e lubrificantes;Gasolina;200,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            view_res = con.execute("""
                SELECT id_candidatura, total_publicidade, quantidade_despesas_publicidade
                FROM "vw_publicidade_candidatura"
                WHERE id_candidatura = 'CANDIDATURA_2018_T1'
            """).fetchone()
            self.assertIsNotNone(view_res, "View deve retornar dados para a candidatura.")
            self.assertEqual(view_res[0], "CANDIDATURA_2018_T1")
            self.assertEqual(float(view_res[1]), 1000.00, "Total de publicidade deve somar apenas itens de publicidade (400 + 600).")
            self.assertEqual(view_res[2], 2, "Quantidade de itens de publicidade deve ser 2.")
        finally:
            con.close()

    def test_despesa_eleicao_diferente_rejeitada(self):
        """Auditoria 3: Comprova que uma despesa não pode ser associada a candidatura de eleição diferente."""
        banco = self.raiz / "banco_eleicao_incompativel.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_eleicao_incompativel"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            # cd_eleicao 9999 não existe para 2018
            "2018;1;Final;10/11/2018;9999;RN;1001;D_ELE_ERR;01/09/2018;Publicidade por materiais impressos;Panfleto;300,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            total_vinculadas = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total_vinculadas, 0, "Despesa de eleição incompatível não pode ser vinculada!")

            rejeitadas = con.execute("""
                SELECT sq_candidato, motivo_rejeicao, valor_contratado
                FROM "Despesa_Rejeitada"
            """).fetchall()
            self.assertEqual(len(rejeitadas), 1)
            self.assertEqual(rejeitadas[0], ("1001", "ELEICAO_INCOMPATIVEL", 300.00))
        finally:
            con.close()

    def test_despesa_cargo_diferente_rejeitada(self):
        """Auditoria 4: Comprova que uma despesa não pode ser associada a candidatura de cargo diferente."""
        banco = self.raiz / "banco_cargo_incompativel.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_cargo_incompativel"

        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            # Candidato 1001 concorre a Governador (03), despesa informa cargo 06 (Deputado Federal)
            "2018;1;Final;10/11/2018;297;RN;1001;D_CARGO_ERR;01/09/2018;Publicidade por materiais impressos;Panfleto;800,00;06\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            total_vinculadas = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
            self.assertEqual(total_vinculadas, 0, "Despesa de cargo incompatível não pode ser vinculada!")

            rejeitadas = con.execute("""
                SELECT sq_candidato, motivo_rejeicao, valor_contratado
                FROM "Despesa_Rejeitada"
            """).fetchall()
            self.assertEqual(len(rejeitadas), 1)
            self.assertEqual(rejeitadas[0], ("1001", "CARGO_INCOMPATIVEL", 800.00))
        finally:
            con.close()

    def test_equivalencia_codigos_tse_e_identificadores_der(self):
        """Auditoria 5: Comprova que códigos oficiais do TSE e identificadores internos do DER

        se relacionam corretamente quando há equivalência válida.
        """
        banco = self.raiz / "banco_equiv_tse.duckdb"
        self._criar_banco_base(banco)
        trabalho = self.raiz / "trab_equiv_tse"

        # DER tem: id_eleicao = 'ELE_2018_1', Cargo.nome = 'Governador'
        # Fonte TSE tem: CD_ELEICAO = '297', CD_CARGO = '03'
        csv = (
            "AA_ELEICAO;ST_TURNO;TP_PRESTACAO_CONTAS;DT_PRESTACAO_CONTAS;CD_ELEICAO;SG_UF;SQ_CANDIDATO;"
            "SQ_DESPESA;DT_DESPESA;DS_ORIGEM_DESPESA;DS_DESPESA;VR_DESPESA_CONTRATADA;CD_CARGO\n"
            "2018;1;Final;10/11/2018;297;RN;1001;D_EQUIV;01/09/2018;Publicidade por materiais impressos;Equivalente;950,00;03\n"
        )
        self._criar_zip_despesas(trabalho / "zips", 2018, "RN", csv)
        processar_q9(ufs=["RN"], anos=[2018], banco=banco, trabalho=trabalho)

        con = duckdb.connect(str(banco))
        try:
            despesa = con.execute("""
                SELECT d.id_candidatura, d.valor_contratado, c.sequencial
                FROM "Despesa_Campanha" d
                JOIN "Candidatura" c ON d.id_candidatura = c.id_candidatura
                WHERE d.sequencial_despesa_tse = 'D_EQUIV'
            """).fetchone()
            self.assertIsNotNone(despesa, "A despesa com códigos oficiais do TSE deve vincular com sucesso via equivalência!")
            self.assertEqual(despesa[0], "CANDIDATURA_2018_T1")
            self.assertEqual(float(despesa[1]), 950.00)
            self.assertEqual(despesa[2], "1001")
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()

