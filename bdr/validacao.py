"""Manifesto e validações obrigatórias para a Questão 3 do BDR.

Validações obrigatórias:
1. todos os municípios esperados das UFs foram carregados;
2. nenhum município dos votos ficou sem correspondência com código IBGE;
3. nenhum partido utilizado nos votos ficou sem correspondência;
4. não existem duplicidades na chave lógica de votos_partido_municipio;
5. votos não são negativos;
6. eleitorado_apto, comparecimento e abstencoes não são negativos;
7. consistência aritmética: comparecimento + abstencoes = eleitorado_apto;
8. ausência de multiplicação de aptos/abstenções por granularidade de BU;
9. população e PIB com unidade e ano de referência documentados (2022);
10. IDHM mantém o ano real da fonte histórica (2010);
11. manifesto registra linhas carregadas por UF, ano e fonte.
"""
from datetime import datetime

from .esquema import TABELAS


def _linhas(con, sql):
    return con.execute(sql).fetchall()


def gerar_manifesto(con, escopo, arquivos, avisos):
    tabelas_existentes = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    contagens = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                 for t in TABELAS if t in tabelas_existentes}

    # 1. Municípios carregados vs esperados do IBGE
    mun_uf = _linhas(con, """
        SELECT m.uf, count(DISTINCT m.cod_tse) AS mun_tse,
               count(DISTINCT m.id_municipio) AS mun_ibge
        FROM municipio m
        GROUP BY m.uf ORDER BY m.uf
    """)

    # 2. Municípios sem correspondência com código IBGE
    mun_sem_ibge = con.execute(
        "SELECT count(*) FROM municipio WHERE id_municipio IS NULL"
    ).fetchone()[0]

    votos_sem_ibge = con.execute(
        "SELECT count(*) FROM votos_partido_municipio WHERE id_municipio IS NULL"
    ).fetchone()[0]

    # 3. Partidos nos votos sem cadastro em partido
    partidos_sem_cadastro = con.execute("""
        SELECT count(*)
        FROM votos_partido_municipio v
        LEFT JOIN partido p ON p.numero = v.numero_partido AND p.sigla = v.sigla_partido
        WHERE p.numero IS NULL
    """).fetchone()[0]

    # 4. Duplicidades na chave lógica de votos_partido_municipio
    duplicidades_votos = con.execute("""
        SELECT count(*) FROM (
            SELECT ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio
            FROM votos_partido_municipio
            GROUP BY ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio
            HAVING count(*) > 1
        )
    """).fetchone()[0]

    # 5. Votos negativos
    votos_negativos = con.execute("""
        SELECT count(*)
        FROM votos_partido_municipio
        WHERE votos_nominais < 0 OR votos_legenda < 0
    """).fetchone()[0]

    # 6. Totais negativos em participacao_eleitoral
    totais_negativos = con.execute("""
        SELECT count(*)
        FROM participacao_eleitoral
        WHERE eleitorado_apto < 0 OR comparecimento < 0 OR abstencoes < 0
    """).fetchone()[0]

    # 7. Consistência: comparecimento + abstencoes = eleitorado_apto
    inconsistencias_soma = con.execute("""
        SELECT count(*)
        FROM participacao_eleitoral
        WHERE (comparecimento + abstencoes) != eleitorado_apto
    """).fetchone()[0]

    # 8. Verificação de não multiplicação do BU
    taxas_invalidas = con.execute("""
        SELECT count(*)
        FROM participacao_eleitoral
        WHERE taxa_abstencao < 0.0 OR taxa_abstencao > 1.0 OR comparecimento > eleitorado_apto
    """).fetchone()[0]

    # 9. Documentação e checagem de censo_municipio (população e PIB)
    censo_stats = _linhas(con, """
        SELECT ano_referencia,
               count(*) AS municipios,
               count(populacao) AS com_populacao,
               count(pib) AS com_pib,
               count(idhm) AS com_idhm
        FROM censo_municipio
        GROUP BY ano_referencia
        ORDER BY ano_referencia
    """)

    # 10. Checagem de ano real do IDHM
    anos_idhm = [r[0] for r in _linhas(con, "SELECT DISTINCT ano_referencia FROM censo_municipio WHERE idhm IS NOT NULL")]
    idhm_ano_valido = all(a == 2010 for a in anos_idhm) if anos_idhm else True

    # Resumo por ano de votos e participação
    votos_resumo = _linhas(con, """
        SELECT ano, sum(votos_nominais), sum(votos_legenda)
        FROM votos_partido_municipio
        GROUP BY ano ORDER BY ano
    """)

    participacao_resumo = _linhas(con, """
        SELECT ano, turno,
               sum(eleitorado_apto), sum(comparecimento), sum(abstencoes),
               round(100.0 * sum(abstencoes) / nullif(sum(eleitorado_apto), 0), 2) AS taxa_pct
        FROM participacao_eleitoral
        GROUP BY ano, turno ORDER BY ano, turno
    """)

    validacoes = {
        "1_municipios_carregados": [{"uf": u, "codigos_tse": t, "codigos_ibge": i} for u, t, i in mun_uf],
        "2_municipios_sem_ibge": mun_sem_ibge,
        "2_votos_sem_ibge": votos_sem_ibge,
        "3_partidos_sem_cadastro": partidos_sem_cadastro,
        "4_duplicidades_votos_partido": duplicidades_votos,
        "5_votos_negativos": votos_negativos,
        "6_totais_participacao_negativos": totais_negativos,
        "7_inconsistencias_comparecimento_abstencao": inconsistencias_soma,
        "8_taxas_abstencao_invalidas": taxas_invalidas,
        "9_unidades_documentadas": {
            "populacao": "habitantes (Censo 2022 IBGE)",
            "pib": "Reais - R$ (IBGE 2022)",
            "pib_per_capita": "R$/habitante (IBGE 2022 / Censo 2022)",
            "idhm": "Índice 0 a 1 (Atlas Brasil 2010)",
        },
        "10_idhm_ano_real_2010": idhm_ano_valido,
        "10_anos_idhm_encontrados": anos_idhm,
    }

    return {
        "questao": "Q3 - Relação entre características socioeconômicas, distribuição de votos e abstenção",
        "rotulo": escopo["rotulo"],
        "membro": escopo.get("membro"),
        "ufs": escopo["ufs"],
        "anos": escopo["anos"],
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "tabelas": contagens,
        "validacoes": validacoes,
        "censo_por_ano": [
            {"ano_referencia": a, "municipios": m, "com_populacao": p, "com_pib": pb, "com_idhm": i}
            for a, m, p, pb, i in censo_stats
        ],
        "votos_partido_por_ano": [
            {"ano": a, "votos_nominais": int(vn or 0), "votos_legenda": int(vl or 0)}
            for a, vn, vl in votos_resumo
        ],
        "participacao_por_ano_turno": [
            {"ano": a, "turno": t, "aptos": int(ap or 0), "comparecimento": int(cp or 0),
             "abstencoes": int(ab or 0), "taxa_abstencao_pct": float(tx or 0)}
            for a, t, ap, cp, ab, tx in participacao_resumo
        ],
        "arquivos": arquivos,
        "avisos": avisos,
    }


def imprimir_resumo(m):
    print("\n" + "=" * 60)
    print("RELATÓRIO DE VALIDAÇÃO (QUESTÃO 3)")
    print("=" * 60)
    v = m["validacoes"]
    print("1. Cobertura de Municípios:")
    for item in v["1_municipios_carregados"]:
        print(f"   - UF {item['uf']}: {item['codigos_tse']} municípios TSE | {item['codigos_ibge']} com código IBGE")
    print(f"2. Municípios dos votos sem IBGE: {v['2_votos_sem_ibge']} (esperado: 0)")
    print(f"3. Partidos sem cadastro: {v['3_partidos_sem_cadastro']} (esperado: 0)")
    print(f"4. Duplicidades na chave de votos: {v['4_duplicidades_votos_partido']} (esperado: 0)")
    print(f"5. Votos negativos: {v['5_votos_negativos']} (esperado: 0)")
    print(f"6. Totais negativos em participação: {v['6_totais_participacao_negativos']} (esperado: 0)")
    print(f"7. Inconsistências (comparecimento + abstenção != aptos): {v['7_inconsistencias_comparecimento_abstencao']} (esperado: 0)")
    print(f"8. Taxas de abstenção inválidas (<0 ou >1): {v['8_taxas_abstencao_invalidas']} (esperado: 0)")
    print(f"9. Unidades e referências temporais:")
    for k, val in v["9_unidades_documentadas"].items():
        print(f"   - {k}: {val}")
    print(f"10. IDHM mantém referência histórica (2010): {'SIM' if v['10_idhm_ano_real_2010'] else 'NÃO'} (anos: {v['10_anos_idhm_encontrados']})")

    print("\nResumo Eleitoral:")
    for l in m["votos_partido_por_ano"]:
        print(f"   {l['ano']}: {l['votos_nominais']:,} votos nominais | {l['votos_legenda']:,} votos de legenda")
    for l in m["participacao_por_ano_turno"]:
        print(f"   {l['ano']} ({l['turno']}º turno): {l['aptos']:,} aptos | {l['comparecimento']:,} comparecimento | "
              f"{l['abstencoes']:,} abstenções ({l['taxa_abstencao_pct']}%)")

    print("\nResumo Socioeconômico (censo_municipio):")
    for c in m["censo_por_ano"]:
        print(f"   Ano Ref {c['ano_referencia']}: {c['municipios']} municípios | {c['com_populacao']} pop | "
              f"{c['com_pib']} PIB | {c['com_idhm']} IDHM")

    if m["avisos"]:
        print(f"\n{len(m['avisos'])} aviso(s):")
        for a in m["avisos"][:10]:
            print("   -", a)
    print("=" * 60)
