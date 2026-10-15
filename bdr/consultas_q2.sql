-- Questão 2: existe relação entre o patrimônio de um candidato e sua taxa
-- de sucesso em eleições?
--
-- Fonte: Candidatura.patrimonio (valor declarado na própria candidatura,
-- em reais, já convertido do formato brasileiro "1.234,56" para DOUBLE)
-- e Resultado_Candidatura.resultado (texto vindo de DS_SIT_TOT_TURNO do TSE).
--
-- Cuidado: 'resultado' contém tanto 'ELEITO', 'ELEITO POR QP', 'ELEITO POR
-- MÉDIA' quanto 'NÃO ELEITO' — e 'NÃO ELEITO' contém a substring 'ELEITO'.
-- Por isso o sucesso é sempre testado com starts_with(upper(resultado),
-- 'ELEITO'), nunca com LIKE '%ELEITO%'.
--
-- Patrimônio é declarado por candidatura (pode variar a cada eleição que a
-- pessoa disputou), então todas as consultas abaixo operam no nível de
-- candidatura, não de candidato.

-- name: q2_patrimonio_medio_por_situacao
-- Visão geral: patrimônio médio e mediano de eleitos vs não eleitos.
-- A mediana é mais robusta aqui porque a distribuição de patrimônio é
-- fortemente assimétrica (poucos candidatos muito ricos puxam a média).
SELECT
    CASE WHEN starts_with(upper(r.resultado), 'ELEITO')
         THEN 'Eleito' ELSE 'Não eleito' END AS situacao,
    count(*) AS candidaturas,
    round(avg(c.patrimonio), 2) AS patrimonio_medio,
    round(median(c.patrimonio), 2) AS patrimonio_mediano
FROM Candidatura c
JOIN Resultado_Candidatura r USING (id_candidatura)
WHERE c.patrimonio IS NOT NULL AND c.patrimonio >= 0
GROUP BY situacao
ORDER BY situacao;


-- name: q2_correlacao_patrimonio_sucesso
-- Correlação de Pearson entre patrimônio e um indicador binário de sucesso
-- (1 = eleito, 0 = não eleito). Útil como resumo de uma linha, mas pouco
-- informativo sozinho: relação entre dinheiro e eleição costuma ser não
-- linear (log-patrimônio tende a se comportar melhor), por isso a consulta
-- seguinte (por decis) é a mais importante para interpretar o resultado.
SELECT
    corr(c.patrimonio,
         CASE WHEN starts_with(upper(r.resultado), 'ELEITO') THEN 1.0 ELSE 0.0 END
    ) AS correlacao_patrimonio_x_eleito,
    corr(ln(c.patrimonio + 1),
         CASE WHEN starts_with(upper(r.resultado), 'ELEITO') THEN 1.0 ELSE 0.0 END
    ) AS correlacao_log_patrimonio_x_eleito,
    count(*) AS candidaturas_consideradas
FROM Candidatura c
JOIN Resultado_Candidatura r USING (id_candidatura)
WHERE c.patrimonio IS NOT NULL AND c.patrimonio >= 0;


-- name: q2_taxa_sucesso_por_decil_patrimonio
-- Taxa de sucesso eleitoral por decil de patrimônio (decil 1 = mais pobres,
-- decil 10 = mais ricos). É a forma mais direta de visualizar a relação:
-- se a taxa_sucesso_pct crescer de forma consistente do decil 1 ao 10,
-- há evidência de relação positiva entre patrimônio e sucesso.
WITH base AS (
    SELECT
        c.id_candidatura,
        c.patrimonio,
        CASE WHEN starts_with(upper(r.resultado), 'ELEITO') THEN 1 ELSE 0 END AS eleito
    FROM Candidatura c
    JOIN Resultado_Candidatura r USING (id_candidatura)
    WHERE c.patrimonio IS NOT NULL AND c.patrimonio >= 0
),
faixas AS (
    SELECT *, ntile(10) OVER (ORDER BY patrimonio) AS decil
    FROM base
)
SELECT
    decil,
    round(min(patrimonio), 2) AS patrimonio_min,
    round(max(patrimonio), 2) AS patrimonio_max,
    count(*) AS candidaturas,
    sum(eleito) AS eleitos,
    round(100.0 * sum(eleito) / count(*), 2) AS taxa_sucesso_pct
FROM faixas
GROUP BY decil
ORDER BY decil;


-- name: q2_patrimonio_por_cargo_e_situacao
-- Mesma visão da primeira consulta, mas quebrada por cargo. Importante
-- porque patrimônio médio e taxa de sucesso variam muito por cargo
-- (um candidato a prefeito e um a vereador não são comparáveis em valor
-- absoluto); sem esse controle, o resultado agregado pode refletir apenas
-- a mistura de cargos na amostra, não uma relação real entre patrimônio e
-- sucesso dentro de cada disputa.
SELECT
    cg.nome AS cargo,
    CASE WHEN starts_with(upper(r.resultado), 'ELEITO')
         THEN 'Eleito' ELSE 'Não eleito' END AS situacao,
    count(*) AS candidaturas,
    round(avg(c.patrimonio), 2) AS patrimonio_medio,
    round(median(c.patrimonio), 2) AS patrimonio_mediano
FROM Candidatura c
JOIN Resultado_Candidatura r USING (id_candidatura)
JOIN Cargo cg USING (id_candidatura)
WHERE c.patrimonio IS NOT NULL AND c.patrimonio >= 0
GROUP BY cg.nome, situacao
ORDER BY cg.nome, situacao;


-- name: q2_cobertura_patrimonio
-- Checagem de qualidade: quantas candidaturas têm patrimônio utilizável
-- (não nulo e não negativo) vs o total. Rode isto antes de interpretar as
-- consultas acima — se a cobertura for baixa, a amostra pode não
-- representar bem a população de candidatos.
SELECT
    count(*) AS candidaturas_totais,
    count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0) AS com_patrimonio_valido,
    count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio < 0) AS patrimonio_negativo_suspeito,
    round(100.0 * count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0) / count(*), 2)
        AS cobertura_pct
FROM Candidatura;
