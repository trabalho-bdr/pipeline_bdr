/*
Questão 9
=========
Pergunta de pesquisa:
"Em quais tipos de publicidade e propaganda eleitoral os candidatos concentram seus gastos de campanha?"

Escopo analítico:
- Anos eleitorais: 2018, 2020, 2022 e 2024.
- Unidades Federativas: CE, MA, MS, RJ, RN e RS.
- Entidades DER: Despesa_Campanha, Categoria_Despesa, Candidatura, Candidato, Cargo, Partido, Eleicao.

Todas as consultas evitam dupla contagem considerando apenas registros deduplicados de despesas
contratadas e indicam valores nominais em reais (R$).
*/

-- name: q9_gastos_por_categoria_original
-- Objetivo 1: Calcular os gastos totais de publicidade por categoria original informada pelo TSE.
SELECT
    cat.origem_despesa,
    cat.grupo_publicidade,
    count(d.id_despesa) AS total_despesas,
    sum(d.valor_contratado) AS valor_total_nominal
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
WHERE cat.eh_publicidade = true
GROUP BY cat.origem_despesa, cat.grupo_publicidade
ORDER BY valor_total_nominal DESC;


-- name: q9_gastos_por_grupo_analitico
-- Objetivo 2: Calcular os gastos totais por grupo analítico de propaganda (DIGITAL, IMPRESSOS, AUDIOVISUAL, SONORA, EVENTOS, OUTROS).
SELECT
    cat.grupo_publicidade,
    count(d.id_despesa) AS total_despesas,
    sum(d.valor_contratado) AS valor_total_nominal,
    round(100.0 * sum(d.valor_contratado) / sum(sum(d.valor_contratado)) OVER (), 2) AS percentual_do_total_publicidade
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
WHERE cat.eh_publicidade = true
GROUP BY cat.grupo_publicidade
ORDER BY valor_total_nominal DESC;


-- name: q9_participacao_percentual_categorias
-- Objetivo 3: Determinar os percentuais de participação de cada categoria individual no total de publicidade.
WITH totais AS (
    SELECT
        sum(d.valor_contratado) AS total_geral_publicidade
    FROM "Despesa_Campanha" d
    JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
    WHERE cat.eh_publicidade = true
)
SELECT
    cat.origem_despesa,
    cat.grupo_publicidade,
    sum(d.valor_contratado) AS valor_total_nominal,
    round(100.0 * sum(d.valor_contratado) / max(t.total_geral_publicidade), 2) AS percentual_participacao
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
CROSS JOIN totais t
WHERE cat.eh_publicidade = true
GROUP BY cat.origem_despesa, cat.grupo_publicidade
ORDER BY valor_total_nominal DESC;


-- name: q9_evolucao_modalidades_por_ano
-- Objetivo 4: Comparar as modalidades de publicidade por ano eleitoral (valores nominais em R$).
-- Nota: Os valores apresentados são nominais de cada eleição e não possuem correção monetária inflacionária.
SELECT
    d.ano,
    cat.grupo_publicidade,
    count(d.id_despesa) AS total_despesas,
    sum(d.valor_contratado) AS valor_nominal_ano,
    round(100.0 * sum(d.valor_contratado) / sum(sum(d.valor_contratado)) OVER (PARTITION BY d.ano), 2) AS percentual_no_ano
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
WHERE cat.eh_publicidade = true
GROUP BY d.ano, cat.grupo_publicidade
ORDER BY d.ano, valor_nominal_ano DESC;


-- name: q9_distribuicao_modalidades_por_uf
-- Objetivo 5: Comparar a concentração de gastos em publicidade por Unidade Federativa.
SELECT
    d.uf,
    cat.grupo_publicidade,
    count(d.id_despesa) AS total_despesas,
    sum(d.valor_contratado) AS valor_nominal_uf,
    round(100.0 * sum(d.valor_contratado) / sum(sum(d.valor_contratado)) OVER (PARTITION BY d.uf), 2) AS percentual_na_uf
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
WHERE cat.eh_publicidade = true
GROUP BY d.uf, cat.grupo_publicidade
ORDER BY d.uf, valor_nominal_uf DESC;


-- name: q9_gastos_candidato_cargo_partido
-- Objetivo 6: Analisar a concentração dos gastos de publicidade por candidatura, cargo e partido.
SELECT
    d.ano,
    d.uf,
    cg.nome AS cargo,
    coalesce(p.sigla, 'Sem partido') AS partido,
    c.nome_urna AS candidato_nome,
    cat.grupo_publicidade,
    sum(d.valor_contratado) AS total_publicidade_grupo
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
JOIN "Candidatura" c ON d.id_candidatura = c.id_candidatura
JOIN "Cargo" cg ON cg.id_candidatura = c.id_candidatura
LEFT JOIN "Partido" p ON c.id_partido = p.id_partido
WHERE cat.eh_publicidade = true
GROUP BY d.ano, d.uf, cg.nome, p.sigla, c.nome_urna, cat.grupo_publicidade
ORDER BY total_publicidade_grupo DESC;


-- name: q9_concentracao_financeira
-- Objetivo 7: Apontar as categorias com maior concentração financeira (acumulado e ranking).
WITH ranking_categorias AS (
    SELECT
        cat.origem_despesa,
        cat.grupo_publicidade,
        sum(d.valor_contratado) AS total_gasto,
        row_number() OVER (ORDER BY sum(d.valor_contratado) DESC) AS ranking
    FROM "Despesa_Campanha" d
    JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
    WHERE cat.eh_publicidade = true
    GROUP BY cat.origem_despesa, cat.grupo_publicidade
)
SELECT
    ranking,
    origem_despesa,
    grupo_publicidade,
    total_gasto,
    sum(total_gasto) OVER (ORDER BY ranking) AS gasto_acumulado,
    round(100.0 * sum(total_gasto) OVER (ORDER BY ranking) / sum(total_gasto) OVER (), 2) AS percentual_acumulado
FROM ranking_categorias
ORDER BY ranking;


-- name: q9_nao_classificados_e_pendencias
-- Objetivo 8: Identificar despesas não classificadas, sem valor financeiro ou rejeitadas na auditoria.
SELECT
    'DESPESAS_SEM_VALOR' AS tipo_pendencia,
    count(*) AS quantidade,
    0.00 AS valor_pendente
FROM "Despesa_Campanha"
WHERE valor_contratado IS NULL OR valor_contratado = 0
UNION ALL
SELECT
    'CATEGORIAS_NAO_CLASSIFICADAS' AS tipo_pendencia,
    count(d.id_despesa) AS quantidade,
    coalesce(sum(d.valor_contratado), 0.00) AS valor_pendente
FROM "Despesa_Campanha" d
JOIN "Categoria_Despesa" c ON d.id_categoria_despesa = c.id_categoria_despesa
WHERE c.grupo_publicidade = 'NAO_CLASSIFICADO'
UNION ALL
SELECT
    'DESPESAS_REJEITADAS_AUDITORIA' AS tipo_pendencia,
    count(*) AS quantidade,
    coalesce(sum(valor_contratado), 0.00) AS valor_pendente
FROM "Despesa_Rejeitada";
