/*
Questão 3
==========
Como as características socioeconômicas dos municípios se relacionam com a
distribuição dos votos entre partidos e com a taxa de abstenção?

Referências temporais disponíveis no DER:
- participação e votos: ano eleitoral selecionado (2022 ou 2024);
- população e PIB: 2022;
- IDHM: 2010.

Convenções dos perfis:
- renda: comparação do PIB per capita com a mediana dos municípios da UF;
- porte: pequeno abaixo de 100 mil habitantes e grande a partir de 100 mil.

Os parâmetros são posicionais e aparecem como "?". O Streamlit fornece esses
valores sem interpolar texto no SQL.
*/

-- name: q3_municipios
-- Objetivo: produzir uma linha por município com todas as variáveis usadas na
-- análise de abstenção e com as classificações de renda e porte.
-- Parâmetros: 1 = ano eleitoral; 2 = sigla da UF.
WITH filtro AS (
    SELECT cast(? AS INTEGER) AS ano, cast(? AS VARCHAR) AS uf
),
-- Transforma as linhas de anos de referência diferentes em uma linha por
-- município. Não atribui IDHM 2010 ou PIB 2022 a outro ano de referência.
socioeconomico AS (
    SELECT
        id_municipio,
        max(populacao) FILTER (WHERE ano_referencia = 2022) AS populacao,
        max(pib) FILTER (WHERE ano_referencia = 2022) AS pib,
        max(idhm) FILTER (WHERE ano_referencia = 2010) AS idhm
    FROM "Censo_Municipio"
    GROUP BY id_municipio
),
base AS (
    SELECT
        m.id_municipio,
        m.cod_tse,
        m.nome AS municipio,
        m.uf,
        f.ano,
        p.eleitorado_apto AS eleitorado,
        p.comparecimento,
        p.abstencoes,
        -- Prefere a taxa armazenada. O cálculo alternativo protege contra
        -- eleitorado zero e mantém a saída expressa em percentual.
        coalesce(
            p.taxa_abstencao,
            p.abstencoes::DOUBLE / nullif(p.eleitorado_apto, 0)
        ) * 100 AS abstencao_pct,
        s.populacao,
        s.pib,
        s.pib::DOUBLE / nullif(s.populacao, 0) AS pib_per_capita,
        s.idhm
    FROM filtro f
    JOIN "Municipio" m ON m.uf = f.uf
    JOIN "Participacao_Eleitoral" p
      ON p.id_municipio = m.id_municipio
     AND p.ano_participacao = f.ano
    LEFT JOIN socioeconomico s ON s.id_municipio = m.id_municipio
),
classificada AS (
    SELECT
        *,
        -- A mediana é calculada no recorte da UF selecionada; portanto,
        -- "Mais rico" e "Mais pobre" são perfis relativos dentro da UF.
        median(pib_per_capita) OVER () AS mediana_pib_per_capita
    FROM base
)
SELECT
    *,
    CASE
        WHEN pib_per_capita IS NULL THEN NULL
        WHEN pib_per_capita >= mediana_pib_per_capita THEN 'Mais rico'
        ELSE 'Mais pobre'
    END AS perfil_renda,
    CASE
        WHEN populacao IS NULL THEN NULL
        WHEN populacao < 100000 THEN 'Pequeno (<100 mil)'
        ELSE 'Grande (>=100 mil)'
    END AS perfil_porte
FROM classificada
ORDER BY municipio;

-- name: q3_cargos
-- Objetivo: preencher o seletor somente com cargos que realmente possuem
-- votos no recorte escolhido.
-- Parâmetros: 1 = UF; 2 = ano eleitoral; 3 = turno.
SELECT DISTINCT e.cargo
FROM "Votos_Partido_Municipio" v
JOIN "Municipio" m USING (id_municipio)
JOIN "Eleicao" e USING (id_eleicao)
WHERE m.uf = ? AND e.ano = ? AND v.turno = ?
ORDER BY e.cargo;

-- name: q3_votos_por_perfil
-- Objetivo: relacionar votos partidários com os mesmos indicadores e perfis
-- municipais usados na análise de abstenção. A consulta devolve todos os
-- partidos; qualquer limitação visual é responsabilidade do painel.
-- Parâmetros: 1 = ano; 2 = UF; 3 = turno; 4 = cargo.
WITH filtro AS (
    SELECT
        cast(? AS INTEGER) AS ano,
        cast(? AS VARCHAR) AS uf,
        cast(? AS SMALLINT) AS turno,
        cast(? AS VARCHAR) AS cargo
),
socioeconomico AS (
    SELECT
        id_municipio,
        max(populacao) FILTER (WHERE ano_referencia = 2022) AS populacao,
        max(pib) FILTER (WHERE ano_referencia = 2022) AS pib,
        max(idhm) FILTER (WHERE ano_referencia = 2010) AS idhm
    FROM "Censo_Municipio"
    GROUP BY id_municipio
),
municipios AS (
    SELECT
        m.id_municipio,
        m.nome AS municipio,
        m.uf,
        f.ano,
        p.eleitorado_apto AS eleitorado,
        coalesce(
            p.taxa_abstencao,
            p.abstencoes::DOUBLE / nullif(p.eleitorado_apto, 0)
        ) * 100 AS abstencao_pct,
        s.populacao,
        s.pib::DOUBLE / nullif(s.populacao, 0) AS pib_per_capita,
        s.idhm
    FROM filtro f
    JOIN "Municipio" m ON m.uf = f.uf
    JOIN "Participacao_Eleitoral" p
      ON p.id_municipio = m.id_municipio
     AND p.ano_participacao = f.ano
    LEFT JOIN socioeconomico s ON s.id_municipio = m.id_municipio
),
perfis AS (
    SELECT
        *,
        CASE
            WHEN pib_per_capita IS NULL THEN NULL
            WHEN pib_per_capita >= median(pib_per_capita) OVER () THEN 'Mais rico'
            ELSE 'Mais pobre'
        END AS perfil_renda,
        CASE
            WHEN populacao IS NULL THEN NULL
            WHEN populacao < 100000 THEN 'Pequeno (<100 mil)'
            ELSE 'Grande (>=100 mil)'
        END AS perfil_porte
    FROM municipios
)
SELECT
    p.id_municipio,
    p.municipio,
    p.uf,
    p.ano,
    f.turno,
    f.cargo,
    pa.sigla AS partido,
    v.votos_nominais,
    v.votos_legenda,
    -- A distribuição partidária considera votos nominais e de legenda.
    v.votos_nominais + coalesce(v.votos_legenda, 0) AS votos,
    p.eleitorado,
    p.abstencao_pct,
    p.populacao,
    p.pib_per_capita,
    p.idhm,
    p.perfil_renda,
    p.perfil_porte
FROM filtro f
JOIN "Eleicao" e
  ON e.ano = f.ano
 AND e.turno = f.turno
 AND e.cargo = f.cargo
JOIN "Votos_Partido_Municipio" v
  ON v.id_eleicao = e.id_eleicao
 AND v.turno = f.turno
JOIN perfis p ON p.id_municipio = v.id_municipio
JOIN "Partido" pa ON pa.id_partido = v.id_partido
ORDER BY p.municipio, pa.sigla;

-- name: q3_perfil_eleitorado
-- Parâmetros: ano eleitoral, UF. Uma linha por idade × gênero × escolaridade.
-- Quantidades representam eleitores cadastrados, não votos ou comparecimento.
SELECT p.*, m.nome AS municipio, m.uf,
       100.0 * quantidade_eleitores / nullif(sum(quantidade_eleitores)
           OVER (PARTITION BY p.id_municipio, p.ano), 0) AS percentual_eleitorado
FROM Perfil_Eleitorado_Municipio p JOIN Municipio m USING (id_municipio)
WHERE p.ano=? AND m.uf=?
ORDER BY m.nome, p.faixa_etaria, p.genero, p.grau_instrucao;

-- name: q3_demografia_partidos
-- Parâmetros: ano, UF, turno, cargo. Associação ecológica; nunca votos do grupo.
-- Agrega o perfil ANTES do join com votos para impedir multiplicação dos votos.
-- Jovens = 16 a 24 anos (faixas oficiais permitem esse corte sem interpolação).
WITH filtro AS (
    SELECT cast(? AS INTEGER) ano, cast(? AS VARCHAR) uf,
           cast(? AS SMALLINT) turno, cast(? AS VARCHAR) cargo
), perfil AS (
    SELECT id_municipio, ano, sum(quantidade_eleitores) AS total_perfil,
        100.0 * sum(quantidade_eleitores) FILTER (
            WHERE try_cast(regexp_extract(faixa_etaria, '^(\d+)', 1) AS INTEGER) >= 16
              AND try_cast(regexp_extract(faixa_etaria, '(\d+)\D*$', 1) AS INTEGER) <= 24
        ) / nullif(sum(quantidade_eleitores),0) AS jovens_16_24_pct,
        100.0 * sum(quantidade_eleitores) FILTER (WHERE genero='FEMININO')
            / nullif(sum(quantidade_eleitores),0) AS feminino_pct,
        100.0 * sum(quantidade_eleitores) FILTER (WHERE grau_instrucao='ANALFABETO')
            / nullif(sum(quantidade_eleitores),0) AS analfabetos_pct,
        100.0 * sum(quantidade_eleitores) FILTER (WHERE grau_instrucao='SUPERIOR COMPLETO')
            / nullif(sum(quantidade_eleitores),0) AS superior_completo_pct
    FROM Perfil_Eleitorado_Municipio WHERE ano=(SELECT ano FROM filtro)
    GROUP BY id_municipio, ano
), votos AS (
    SELECT v.id_municipio, v.id_eleicao, v.id_partido,
           sum(coalesce(v.votos_nominais,0)) AS votos_nominais,
           sum(coalesce(v.votos_legenda,0)) AS votos_legenda
    FROM Votos_Partido_Municipio v JOIN Eleicao e USING (id_eleicao)
    JOIN Municipio m USING (id_municipio)
    CROSS JOIN filtro f
    WHERE m.uf=f.uf AND e.ano=f.ano AND v.turno=f.turno AND e.cargo=f.cargo
    GROUP BY 1,2,3
)
SELECT m.id_municipio, m.nome AS municipio, m.uf, e.ano, e.turno, e.cargo,
       e.id_eleicao, pa.id_partido, pa.sigla AS partido,
       v.votos_nominais, v.votos_legenda,
       v.votos_nominais+v.votos_legenda AS votos,
       100.0*(v.votos_nominais+v.votos_legenda) / nullif(sum(v.votos_nominais+v.votos_legenda)
           OVER (PARTITION BY v.id_municipio, v.id_eleicao),0) AS votos_pct,
       100.0*v.votos_legenda / nullif(sum(v.votos_legenda)
           OVER (PARTITION BY v.id_municipio, v.id_eleicao),0) AS legenda_pct,
       p.total_perfil,
       CASE WHEN p.total_perfil>0 THEN coalesce(p.jovens_16_24_pct,0) END AS jovens_16_24_pct,
       CASE WHEN p.total_perfil>0 THEN coalesce(p.feminino_pct,0) END AS feminino_pct,
       CASE WHEN p.total_perfil>0 THEN coalesce(p.analfabetos_pct,0) END AS analfabetos_pct,
       CASE WHEN p.total_perfil>0 THEN coalesce(p.superior_completo_pct,0) END AS superior_completo_pct,
       c.idade_media_estimada, c.idade_mediana, c.indice_envelhecimento,
       c.ano_referencia AS ano_censo
FROM votos v JOIN Municipio m USING (id_municipio)
JOIN Eleicao e USING (id_eleicao) JOIN Partido pa USING (id_partido)
LEFT JOIN perfil p ON p.id_municipio=v.id_municipio AND p.ano=e.ano
LEFT JOIN Censo_Municipio c ON c.id_municipio=v.id_municipio AND c.ano_referencia=2022
ORDER BY m.nome, pa.sigla;
