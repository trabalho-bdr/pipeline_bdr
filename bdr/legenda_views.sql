-- Execute no catalogo DER. As tabelas de origem devem estar no schema indicado
-- pelo instalador. Nao altera as tabelas de origem.
CREATE OR REPLACE VIEW "vw_legenda_municipio_partido" AS
SELECT
    e.id_eleicao,
    e.ano,
    e.cargo,
    e.turno,
    m.uf,
    m.id_municipio,
    m.nome AS municipio,
    p.id_partido,
    p.sigla AS partido,
    sum(coalesce(v.votos_legenda, 0))::BIGINT AS votos_legenda,
    sum(coalesce(v.votos_nominais, 0))::BIGINT AS votos_nominais
FROM "Votos_Partido_Municipio" v
JOIN "Eleicao" e ON e.id_eleicao = v.id_eleicao
JOIN "Municipio" m ON m.id_municipio = v.id_municipio
JOIN "Partido" p ON p.id_partido = v.id_partido
WHERE v.turno = 1 AND e.turno = 1
  AND e.cargo IN ('Deputado Federal', 'Deputado Estadual', 'Vereador')
  AND m.uf IN ('CE', 'MA', 'MS', 'RJ', 'RN', 'RS')
GROUP BY e.id_eleicao, e.ano, e.cargo, e.turno,
         m.uf, m.id_municipio, m.nome, p.id_partido, p.sigla;

CREATE OR REPLACE VIEW "vw_legenda_uf_partido" AS
SELECT ano, cargo, uf, id_partido, partido,
       sum(votos_legenda)::BIGINT AS votos_legenda,
       sum(votos_nominais)::BIGINT AS votos_nominais
FROM "vw_legenda_municipio_partido"
GROUP BY ano, cargo, uf, id_partido, partido;

CREATE OR REPLACE VIEW "vw_legenda_evolucao_partido" AS
SELECT ano, cargo, uf, id_partido, partido,
       sum(votos_legenda)::BIGINT AS votos_legenda,
       sum(votos_nominais)::BIGINT AS votos_nominais
FROM "vw_legenda_municipio_partido"
GROUP BY GROUPING SETS
    ((ano, cargo, uf, id_partido, partido),
     (ano, cargo, id_partido, partido));
