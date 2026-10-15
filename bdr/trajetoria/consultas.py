"""Consultas SQL analíticas para a Questão 10 do BDR (Trajetória Eleitoral dos Candidatos).

Questão 10:
"Como as carreiras políticas se estruturam ao longo do tempo em termos de continuidade
(candidaturas contínuas vs. interrupções), mobilidade de cargos (progressão hierárquica),
troca de partidos (migração partidária) e taxa de sucesso/reeleição?"
"""

def consultar_padroes_carreira(con):
    """Consulta 1: Analisa continuidade vs. interrupções nas carreiras politicas."""
    sql = """
        WITH com_lag AS (
            SELECT 
                c.id_candidato,
                c.ano,
                CASE WHEN c.ano % 4 = 0 THEN 'Eleição Municipal' ELSE 'Eleição Geral' END AS ciclo_eleitoral,
                c.ano - lag(c.ano) OVER (
                    PARTITION BY c.id_candidato, CASE WHEN c.ano % 4 = 0 THEN 'Eleição Municipal' ELSE 'Eleição Geral' END 
                    ORDER BY c.ano
                ) AS hiato
            FROM candidatura c
        ),
        historico AS (
            SELECT 
                id_candidato,
                ciclo_eleitoral,
                min(ano) AS primeiro_ano,
                max(ano) AS ultimo_ano,
                count(DISTINCT ano) AS total_eleicoes,
                max(hiato) AS maior_hiato
            FROM com_lag
            GROUP BY id_candidato, ciclo_eleitoral
        ),
        classificacao AS (
            SELECT 
                id_candidato,
                ciclo_eleitoral,
                CASE 
                    WHEN total_eleicoes = 1 THEN '1. Candidatura Única'
                    WHEN maior_hiato = 4 THEN '2. Carreira Contínua'
                    ELSE '3. Com Interrupção e Retorno'
                END AS padrao_carreira
            FROM historico
        )
        SELECT 
            ciclo_eleitoral,
            padrao_carreira,
            count(DISTINCT id_candidato) AS total_candidatos,
            round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY ciclo_eleitoral), 2) AS pct_do_total
        FROM classificacao
        GROUP BY ciclo_eleitoral, padrao_carreira
        ORDER BY ciclo_eleitoral, padrao_carreira;
    """
    return con.execute(sql).df()


def consultar_fidelidade_partidaria(con):
    """Consulta 2: Avalia a troca e migração partidária entre os candidatos."""
    sql = """
        WITH trocas AS (
            SELECT 
                c.id_candidato,
                cand.nome,
                count(DISTINCT c.sigla_partido) AS total_partidos,
                count(DISTINCT c.ano) AS total_eleicoes,
                string_agg(DISTINCT c.sigla_partido, ' -> ') AS partidos_utilizados
            FROM candidatura c
            JOIN candidato cand ON c.id_candidato = cand.id_candidato
            GROUP BY c.id_candidato, cand.nome
        )
        SELECT 
            CASE 
                WHEN total_partidos = 1 THEN 'Fiel (1 Partido)'
                WHEN total_partidos = 2 THEN '2 Partidos'
                WHEN total_partidos BETWEEN 3 AND 4 THEN '3 a 4 Partidos'
                ELSE '5+ Partidos (Alta Infidelidade)'
            END AS faixa_fidelidade,
            count(*) AS quantidade_candidatos,
            round(avg(total_eleicoes), 2) AS media_eleicoes_disputadas
        FROM trocas
        GROUP BY 1
        ORDER BY quantidade_candidatos DESC;
    """
    return con.execute(sql).df()


def consultar_mobilidade_cargos(con):
    """Consulta 3: Analisa a progressão hierárquica nos cargos disputados."""
    sql = """
        WITH trajetoria_cargos AS (
            SELECT 
                c.id_candidato,
                c.ano,
                cg.nome AS cargo,
                cg.esfera,
                cg.poder,
                cg.ordem_hierarquica,
                lag(cg.ordem_hierarquica) OVER (PARTITION BY c.id_candidato ORDER BY c.ano) AS hierarquia_anterior,
                lag(cg.nome) OVER (PARTITION BY c.id_candidato ORDER BY c.ano) AS cargo_anterior
            FROM candidatura c
            JOIN cargo cg ON c.cd_cargo = cg.cd_cargo
        )
        SELECT 
            CASE 
                WHEN hierarquia_anterior IS NULL THEN 'Primeira Candidatura'
                WHEN ordem_hierarquica > hierarquia_anterior THEN 'Ascensão (Progressão)'
                WHEN ordem_hierarquica = hierarquia_anterior THEN 'Manutenção de Nível'
                ELSE 'Descensão (Recuo)'
            END AS tipo_mobilidade,
            count(*) AS quantidade_transicoes,
            round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_transicoes
        FROM trajetoria_cargos
        GROUP BY 1
        ORDER BY quantidade_transicoes DESC;
    """
    return con.execute(sql).df()


def consultar_taxa_reeleicao(con):
    """Consulta 4: Mede o sucesso eleitoral e a taxa de vitória em reeleições."""
    sql = """
        SELECT 
            c.ano,
            c.uf,
            count(c.id_candidatura) AS total_candidaturas,
            count(c.id_candidatura) FILTER (WHERE c.reeleicao) AS tentativas_reeleicao,
            count(c.id_candidatura) FILTER (WHERE r.eleito) AS total_eleitos,
            count(c.id_candidatura) FILTER (WHERE c.reeleicao AND r.eleito) AS reeleitos_com_sucesso,
            round(100.0 * count(c.id_candidatura) FILTER (WHERE c.reeleicao AND r.eleito) / 
                  nullif(count(c.id_candidatura) FILTER (WHERE c.reeleicao), 0), 2) AS taxa_sucesso_reeleicao_pct
        FROM candidatura c
        JOIN resultado_candidatura r ON c.id_candidatura = r.id_candidatura
        GROUP BY c.ano, c.uf
        ORDER BY c.ano DESC, c.uf;
    """
    return con.execute(sql).df()


def consultar_linha_tempo_candidato(con, termo_busca):
    """Consulta 5: Retorna o histórico de candidaturas de um candidato por busca no nome de urna."""
    sql = f"""
        SELECT 
            cand.nome_urna,
            c.ano,
            c.uf,
            cg.nome AS cargo_disputado,
            c.sigla_partido,
            c.numero_candidato,
            coalesce(r.votos, 0) AS votos_recebidos,
            r.percentual_votos,
            r.colocacao,
            r.situacao_final,
            CASE WHEN r.eleito THEN 'SIM' ELSE 'NÃO' END AS foi_eleito
        FROM candidatura c
        JOIN candidato cand ON c.id_candidato = cand.id_candidato
        JOIN cargo cg ON c.cd_cargo = cg.cd_cargo
        LEFT JOIN resultado_candidatura r ON c.id_candidatura = r.id_candidatura
        WHERE lower(cand.nome_urna) LIKE lower('%{termo_busca.replace("'", "''")}%')
        ORDER BY cand.nome_urna, c.ano, c.turno;
    """
    return con.execute(sql).df()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    banco = sys.argv[1] if len(sys.argv) > 1 else "dados_bdr/q10/trajetoria.duckdb"
    if Path(banco).exists():
        import duckdb
        con = duckdb.connect(banco, read_only=True)
        print(f"Executando consultas da Questão 10 no banco: {banco}\n")
    else:
        print(f"Banco '{banco}' não encontrado. Executando em ambiente de demonstração...\n")
        import duckdb
        from bdr.trajetoria.esquema import criar_tabelas
        con = duckdb.connect()
        criar_tabelas(con)
        con.execute("""
            INSERT INTO cargo VALUES ('13', 'Vereador', 'MUNICIPAL', 'LEGISLATIVO', 1), ('11', 'Prefeito', 'MUNICIPAL', 'EXECUTIVO', 2), ('6', 'Deputado Federal', 'FEDERAL', 'LEGISLATIVO', 4);
            INSERT INTO candidato VALUES ('c1', 'MARIA DA SILVA', 'MARIA SILVA', '1980-01-01', 'F', 'SUPERIOR', 'ADVOGADA', 'RN', 'CPF', FALSE), ('c2', 'JOAO SOUZA', 'JOAO SOUZA', '1975-05-10', 'M', 'SUPERIOR', 'MÉDICO', 'RJ', 'CPF', FALSE);
            INSERT INTO candidatura VALUES ('c1_2020', 'c1', 2020, '426', 1, '13', 13, 'PT', 'RN', '17612', 13123, 'DEFERIDO', FALSE), ('c1_2024', 'c1', 2024, '619', 1, '11', 40, 'PSB', 'RN', '17612', 40, 'DEFERIDO', FALSE), ('c2_2022', 'c2', 2022, '545', 1, '6', 22, 'PL', 'RJ', NULL, 2222, 'DEFERIDO', FALSE);
            INSERT INTO resultado_candidatura VALUES ('c1_2020', 500, 15.5, 1, 'ELEITO', TRUE, FALSE, FALSE), ('c1_2024', 12000, 48.0, 2, 'NÃO ELEITO', FALSE, FALSE, FALSE), ('c2_2022', 80000, 12.0, 1, 'ELEITO', TRUE, FALSE, FALSE);
        """)

    print("=" * 60)
    print("RELATÓRIO DE CONSULTAS SQL — QUESTÃO 10")
    print("=" * 60)
    print("\n1. Padrões de Carreira:")
    print(consultar_padroes_carreira(con).to_string())
    print("\n2. Fidelidade Partidária:")
    print(consultar_fidelidade_partidaria(con).to_string())
    print("\n3. Mobilidade de Cargos:")
    print(consultar_mobilidade_cargos(con).to_string())
    print("\n4. Taxa de Reeleição:")
    print(consultar_taxa_reeleicao(con).to_string())
    print("\n5. Linha do Tempo Individual:")
    print(consultar_linha_tempo_candidato(con, 'MARIA').to_string())
    con.close()

