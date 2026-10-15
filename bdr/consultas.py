"""Consultas SQL analíticas para a Questão 3 do BDR.

Questão 3:
"Como características socioeconômicas dos municípios se relacionam com a distribuição
dos votos entre partidos e com a taxa de abstenção?"
"""

def consultar_abstencao_por_idhm(con):
    """Consulta 1.1: Agrupa a taxa de abstenção por faixas de IDHM."""
    sql = """
        SELECT 
            CASE 
                WHEN c.idhm < 0.550 THEN '1. Muito Baixo (< 0.550)'
                WHEN c.idhm BETWEEN 0.550 AND 0.699 THEN '2. Médio (0.550 - 0.699)'
                WHEN c.idhm BETWEEN 0.700 AND 0.799 THEN '3. Alto (0.700 - 0.799)'
                WHEN c.idhm >= 0.800 THEN '4. Muito Alto (>= 0.800)'
                ELSE 'Não informado'
            END AS faixa_idhm,
            p.ano,
            p.turno,
            count(DISTINCT m.id_municipio) AS total_municipios,
            sum(p.eleitorado_apto) AS total_eleitores,
            sum(p.abstencoes) AS total_abstencoes,
            round(100.0 * sum(p.abstencoes) / nullif(sum(p.eleitorado_apto), 0), 2) AS taxa_abstencao_pct
        FROM participacao_eleitoral p
        JOIN municipio m ON p.cod_tse_municipio = m.cod_tse
        JOIN censo_municipio c ON m.id_municipio = c.id_municipio AND c.ano_referencia = 2010
        GROUP BY 1, p.ano, p.turno
        ORDER BY p.ano, p.turno, 1;
    """
    return con.execute(sql).df()


def consultar_correlacao_socioeconomica(con):
    """Consulta 1.2: Calcula a correlação estatística de Pearson entre abstenção e indicadores."""
    sql = """
        SELECT 
            p.ano,
            p.turno,
            round(corr(p.taxa_abstencao, c2022.pib_per_capita), 4) AS corr_abstencao_pib_per_capita,
            round(corr(p.taxa_abstencao, c2022.populacao), 4) AS corr_abstencao_populacao,
            round(corr(p.taxa_abstencao, c2010.idhm), 4) AS corr_abstencao_idhm
        FROM participacao_eleitoral p
        JOIN municipio m ON p.cod_tse_municipio = m.cod_tse
        LEFT JOIN censo_municipio c2022 ON m.id_municipio = c2022.id_municipio AND c2022.ano_referencia = 2022
        LEFT JOIN censo_municipio c2010 ON m.id_municipio = c2010.id_municipio AND c2010.ano_referencia = 2010
        GROUP BY p.ano, p.turno
        ORDER BY p.ano, p.turno;
    """
    return con.execute(sql).df()


def consultar_votos_partido_por_desenvolvimento(con, ano=2022, cargo='PRESIDENTE'):
    """Consulta 2.1: Distribuição percentual de votos por partido e nível de IDHM."""
    sql = f"""
        WITH votos_agregados AS (
            SELECT 
                v.ano,
                v.cargo,
                v.sigla_partido,
                CASE 
                    WHEN c.idhm < 0.650 THEN 'Baixo/Médio IDHM (< 0.650)'
                    ELSE 'Alto/Muito Alto IDHM (>= 0.650)'
                END AS nivel_desenvolvimento,
                sum(v.votos_nominais + v.votos_legenda) AS total_votos_partido
            FROM votos_partido_municipio v
            JOIN municipio m ON v.cod_tse_municipio = m.cod_tse
            JOIN censo_municipio c ON m.id_municipio = c.id_municipio AND c.ano_referencia = 2010
            WHERE v.ano = {ano} AND upper(v.cargo) = upper('{cargo}')
            GROUP BY v.ano, v.cargo, v.sigla_partido, nivel_desenvolvimento
        ),
        totais_nivel AS (
            SELECT ano, cargo, nivel_desenvolvimento, sum(total_votos_partido) AS votos_totais_nivel
            FROM votos_agregados
            GROUP BY ano, cargo, nivel_desenvolvimento
        )
        SELECT 
            va.nivel_desenvolvimento,
            va.sigla_partido,
            va.total_votos_partido,
            round(100.0 * va.total_votos_partido / tn.votos_totais_nivel, 2) AS pct_dos_votos_no_grupo
        FROM votos_agregados va
        JOIN totais_nivel tn 
          ON va.ano = tn.ano AND va.cargo = tn.cargo AND va.nivel_desenvolvimento = tn.nivel_desenvolvimento
        ORDER BY va.nivel_desenvolvimento, va.total_votos_partido DESC;
    """
    return con.execute(sql).df()


def consultar_perfil_partidos_vencedores(con, ano=2024, cargo='PREFEITO'):
    """Consulta 2.2: Perfil socioeconômico médio dos municípios vencidos por cada partido."""
    sql = f"""
        WITH partido_vencedor AS (
            SELECT 
                v.ano,
                v.cargo,
                v.cod_tse_municipio,
                v.id_municipio,
                v.sigla_partido,
                sum(v.votos_nominais + v.votos_legenda) AS total_votos
            FROM votos_partido_municipio v
            WHERE v.ano = {ano} AND upper(v.cargo) = upper('{cargo}')
            GROUP BY v.ano, v.cargo, v.cod_tse_municipio, v.id_municipio, v.sigla_partido
            QUALIFY row_number() OVER (
                PARTITION BY v.ano, v.cargo, v.cod_tse_municipio 
                ORDER BY sum(v.votos_nominais + v.votos_legenda) DESC
            ) = 1

        )
        SELECT 
            pv.sigla_partido,
            count(DISTINCT pv.id_municipio) AS qtd_municipios_vencidos,
            round(avg(c2022.pib_per_capita), 2) AS pib_per_capita_medio,
            round(avg(c2022.populacao), 0) AS populacao_media,
            round(avg(c2010.idhm), 3) AS idhm_medio
        FROM partido_vencedor pv
        JOIN censo_municipio c2022 ON pv.id_municipio = c2022.id_municipio AND c2022.ano_referencia = 2022
        LEFT JOIN censo_municipio c2010 ON pv.id_municipio = c2010.id_municipio AND c2010.ano_referencia = 2010
        GROUP BY pv.sigla_partido
        ORDER BY qtd_municipios_vencidos DESC;
    """
    return con.execute(sql).df()


def consultar_matriz_municipios(con):
    """Consulta 3.1: Matriz consolidada de perfil por município (Abstenção, Votação e Renda)."""
    sql = """
        SELECT 
            m.uf,
            m.nome AS municipio,
            c2022.populacao,
            c2022.pib_per_capita,
            c2010.idhm,
            p.ano,
            p.turno,
            p.taxa_abstencao,
            (
                SELECT v.sigla_partido 
                FROM votos_partido_municipio v 
                WHERE v.cod_tse_municipio = m.cod_tse 
                  AND v.ano = p.ano 
                  AND v.turno = p.turno
                GROUP BY v.sigla_partido 
                ORDER BY sum(v.votos_nominais + v.votos_legenda) DESC 
                LIMIT 1
            ) AS partido_mais_votado
        FROM participacao_eleitoral p
        JOIN municipio m ON p.cod_tse_municipio = m.cod_tse
        LEFT JOIN censo_municipio c2022 ON m.id_municipio = c2022.id_municipio AND c2022.ano_referencia = 2022
        LEFT JOIN censo_municipio c2010 ON m.id_municipio = c2010.id_municipio AND c2010.ano_referencia = 2010
        ORDER BY m.uf, m.nome, p.ano, p.turno;
    """
    return con.execute(sql).df()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    banco = sys.argv[1] if len(sys.argv) > 1 else "dados_bdr/bdr_consolidado.duckdb"
    if Path(banco).exists():
        import duckdb
        con = duckdb.connect(banco, read_only=True)
        print(f"Executando consultas da Questão 3 no banco: {banco}\n")
    else:
        print(f"Banco '{banco}' não encontrado. Executando em ambiente de demonstração...\n")
        import duckdb
        from bdr.esquema import criar_tabelas
        con = duckdb.connect()
        criar_tabelas(con)
        con.execute("""
            INSERT INTO municipio VALUES ('00001', '3304557', 'Rio de Janeiro', 'RJ', 'Sudeste'), ('00002', '2408102', 'Natal', 'RN', 'Nordeste');
            INSERT INTO eleicao VALUES (2022, '1', 1, 'Eleição Geral', '2022-10-02'), (2024, '2', 1, 'Eleição Municipal', '2024-10-06');
            INSERT INTO partido VALUES (13, 'PT', 'Partido dos Trabalhadores'), (22, 'PL', 'Partido Liberal');
            INSERT INTO censo_municipio VALUES ('3304557', 2010, NULL, NULL, NULL, 0.799), ('3304557', 2022, 6000000, 300000000000.0, 50000.0, NULL), ('2408102', 2010, NULL, NULL, NULL, 0.763), ('2408102', 2022, 800000, 24000000000.0, 30000.0, NULL);
            INSERT INTO participacao_eleitoral VALUES (2022, '1', 1, '00001', '3304557', 100000, 80000, 20000, 0.20), (2022, '1', 1, '00002', '2408102', 50000, 40000, 10000, 0.20), (2024, '2', 1, '00001', '3304557', 105000, 81000, 24000, 0.2285), (2024, '2', 1, '00002', '2408102', 52000, 41000, 11000, 0.2115);
            INSERT INTO votos_partido_municipio VALUES (2022, '1', '1', 'PRESIDENTE', 1, 13, 'PT', '00001', '3304557', 45000, 5000), (2022, '1', '1', 'PRESIDENTE', 1, 22, 'PL', '00001', '3304557', 30000, 0), (2024, '2', '11', 'PREFEITO', 1, 22, 'PL', '00001', '3304557', 46000, 0), (2024, '2', '11', 'PREFEITO', 1, 13, 'PT', '00002', '2408102', 22000, 0);
        """)

    print("=" * 60)
    print("RELATÓRIO DE CONSULTAS SQL — QUESTÃO 3")
    print("=" * 60)
    print("\n1. Abstenção por Faixa de IDHM:")
    print(consultar_abstencao_por_idhm(con).to_string())
    print("\n2. Correlações Socioeconômicas:")
    print(consultar_correlacao_socioeconomica(con).to_string())
    print("\n3. Votação de Partidos por Nível de Desenvolvimento:")
    print(consultar_votos_partido_por_desenvolvimento(con, 2022, 'PRESIDENTE').to_string())
    print("\n4. Perfil Socioeconômico dos Partidos Vencedores:")
    print(consultar_perfil_partidos_vencedores(con, 2024, 'PREFEITO').to_string())
    print("\n5. Matriz Consolidada de Municípios:")
    print(consultar_matriz_municipios(con).to_string())
    con.close()

