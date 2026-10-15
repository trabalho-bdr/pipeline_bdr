-- Análise de patrimônio x sucesso eleitoral: existe relação entre o patrimônio de
-- um candidato e o seu sucesso eleitoral?
--
-- Fonte: Candidatura.patrimonio (valor de bens que o próprio candidato declarou
-- ao TSE, em reais), Resultado_Candidatura.resultado e Eleicao.ano. O patrimônio
-- é declarado por candidatura, então tudo aqui é por candidatura (não por candidato).
--
-- Regras de classificação do resultado (conferidas nos valores reais):
--   sucesso   : começa com 'ELEITO' (ELEITO, ELEITO POR QP, ELEITO POR MÉDIA).
--               Nunca LIKE '%ELEITO%': 'NÃO ELEITO' também contém 'ELEITO'.
--   insucesso : 'NÃO ELEITO' e 'SUPLENTE' (disputou e não assumiu cadeira).
--   excluídos : '#NULO' e '2º TURNO' (resultado indefinido) e qualquer valor
--               novo, que não deve virar "fracasso" por engano.
-- Cada candidatura conta uma vez, pelo resultado do último turno. Vices e
-- suplentes de cargo ficam fora: o sucesso deles depende da chapa.
-- A comparação é sempre dentro de um ano e de um cargo, porque patrimônios de
-- cargos diferentes não são comparáveis.
--
-- Só PREFEITO e VEREADOR têm município (id_municipio); deputados, senador e
-- governador disputam no estado inteiro e só aparecem por UF.
--
-- Todas as consultas começam com o mesmo bloco "base". Para filtrar, acrescente
-- condições no WHERE do bloco, por exemplo: AND e.ano = 2024 AND c.uf = 'RN'

-- name: q2_cobertura_patrimonio
-- Rode esta primeiro: quantas candidaturas têm patrimônio utilizável (não nulo
-- e não negativo) e quantas ficam fora por resultado indefinido. Cobertura baixa
-- significa que as demais consultas não representam bem os candidatos.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
)
SELECT ano, cargo,
       count(*) AS candidaturas_totais,
       count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0) AS com_patrimonio_valido,
       count(*) FILTER (WHERE patrimonio < 0) AS patrimonio_negativo_suspeito,
       count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NULL) AS sem_resultado_definido,
       round(100.0 * count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0) / count(*), 2) AS cobertura_pct
FROM base
GROUP BY ano, cargo
ORDER BY ano, cargo;


-- name: q2_patrimonio_medio_por_situacao
-- Patrimônio médio e mediano de eleitos x não eleitos, por ano e cargo. A mediana
-- é mais confiável: poucos patrimônios muito altos puxam a média.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
)
SELECT ano, cargo,
       CASE WHEN eleito = 1 THEN 'Eleito' ELSE 'Não eleito' END AS situacao,
       count(*) AS candidaturas,
       round(avg(patrimonio), 2) AS patrimonio_medio,
       round(median(patrimonio), 2) AS patrimonio_mediano
FROM base
WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL
GROUP BY ano, cargo, situacao
ORDER BY ano, cargo, situacao;


-- name: q2_correlacao_patrimonio_sucesso
-- Correlação de Pearson entre patrimônio e sucesso (1 = eleito, 0 = não), por ano e
-- cargo. Dá o resumo em um número, mas o patrimônio é muito assimétrico; por isso
-- também se calcula com o log do patrimônio. A leitura principal continua sendo a
-- consulta por decis.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
)
SELECT ano, cargo,
       corr(patrimonio, eleito) AS correlacao_patrimonio_x_eleito,
       corr(ln(patrimonio + 1), eleito) AS correlacao_log_patrimonio_x_eleito,
       count(*) AS candidaturas_consideradas
FROM base
WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL
GROUP BY ano, cargo
ORDER BY ano, cargo;


-- name: q2_taxa_sucesso_por_decil_patrimonio
-- Taxa de sucesso por decil de patrimônio dentro de cada ano e cargo (decil 1 =
-- menores patrimônios, 10 = maiores). É a forma mais direta de responder à questão:
-- se taxa_sucesso_pct sobe do decil 1 ao 10, há relação positiva. Empates (muitos
-- candidatos declaram 0) são desempatados por id_candidatura para o resultado ser
-- sempre o mesmo.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
), faixas AS (
    SELECT ano, cargo, patrimonio, eleito,
           ntile(10) OVER (PARTITION BY ano, cargo ORDER BY patrimonio, id_candidatura) AS decil
    FROM base
    WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL
)
SELECT ano, cargo, decil,
       round(min(patrimonio), 2) AS patrimonio_min,
       round(max(patrimonio), 2) AS patrimonio_max,
       count(*) AS candidaturas,
       sum(eleito) AS eleitos,
       round(100.0 * sum(eleito) / count(*), 2) AS taxa_sucesso_pct
FROM faixas
GROUP BY ano, cargo, decil
ORDER BY ano, cargo, decil;


-- name: q2_patrimonio_por_uf_e_situacao
-- Mesma comparação eleitos x não eleitos, quebrada por ano, cargo e UF. Serve para
-- checar se a relação se repete nos estados ou se é efeito de um só.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
)
SELECT ano, cargo, uf,
       CASE WHEN eleito = 1 THEN 'Eleito' ELSE 'Não eleito' END AS situacao,
       count(*) AS candidaturas,
       round(median(patrimonio), 2) AS patrimonio_mediano
FROM base
WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL
GROUP BY ano, cargo, uf, situacao
ORDER BY ano, cargo, uf, situacao;


-- name: q2_patrimonio_por_municipio
-- Um valor por município (só prefeito e vereador): é esta consulta que pinta o mapa
-- por município. 'analisadas' são as candidaturas com patrimônio válido e resultado
-- definido; municípios com poucas têm medianas instáveis.
WITH ultimo AS (
    SELECT id_candidatura, resultado FROM Resultado_Candidatura
    QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY turno DESC) = 1
), base AS (
    SELECT c.id_candidatura, e.ano, upper(cg.nome) AS cargo, c.uf, c.id_municipio, c.patrimonio,
           CASE WHEN starts_with(upper(u.resultado), 'ELEITO') THEN 1
                WHEN upper(u.resultado) IN ('NÃO ELEITO', 'NAO ELEITO', 'SUPLENTE') THEN 0 END AS eleito
    FROM Candidatura c
    JOIN Cargo cg ON cg.id_candidatura = c.id_candidatura
    JOIN Eleicao e ON e.id_eleicao = c.id_eleicao
    LEFT JOIN ultimo u ON u.id_candidatura = c.id_candidatura
    WHERE upper(cg.nome) IN ('PREFEITO', 'VEREADOR', 'DEPUTADO ESTADUAL', 'DEPUTADO FEDERAL',
                             'SENADOR', 'GOVERNADOR', 'PRESIDENTE')
      AND e.ano IN (2018, 2020, 2022, 2024)
)
SELECT b.ano, b.cargo, b.uf, b.id_municipio, m.nome AS municipio,
       count(*) AS candidaturas,
       count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL) AS analisadas,
       coalesce(sum(eleito) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL), 0) AS eleitos,
       round(100.0 * sum(eleito) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL) / nullif(count(*) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL), 0), 2) AS taxa_sucesso_pct,
       round(median(patrimonio) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL), 2) AS patrimonio_mediano,
       round(median(patrimonio) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL AND eleito = 1), 2) AS patrimonio_mediano_eleitos,
       round(median(patrimonio) FILTER (WHERE patrimonio IS NOT NULL AND patrimonio >= 0 AND eleito IS NOT NULL AND eleito = 0), 2) AS patrimonio_mediano_nao_eleitos
FROM base b
LEFT JOIN Municipio m ON m.id_municipio = b.id_municipio
WHERE b.id_municipio IS NOT NULL
GROUP BY b.ano, b.cargo, b.uf, b.id_municipio, m.nome
ORDER BY b.ano, b.cargo, b.uf, m.nome;
