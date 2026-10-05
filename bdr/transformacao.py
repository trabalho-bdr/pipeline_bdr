"""Do staging (stg_*) para as tabelas finais do DER para a Questão 3."""
from pathlib import Path

MACROS = """
CREATE OR REPLACE MACRO limpa(x) AS
    CASE WHEN x IS NULL OR trim(x) IN ('', '#NULO#', '#NULO', '#NE#', '#NE', '-1', '-3', '-4')
         THEN NULL ELSE trim(x) END;
CREATE OR REPLACE MACRO inteiro(x) AS TRY_CAST(limpa(x) AS BIGINT);
CREATE OR REPLACE MACRO data_br(x) AS TRY_CAST(TRY_STRPTIME(left(limpa(x), 10), '%d/%m/%Y') AS DATE);
CREATE OR REPLACE MACRO moeda(x) AS TRY_CAST(replace(limpa(x), ',', '.') AS DECIMAL(18,2));
CREATE OR REPLACE MACRO norm(x) AS upper(strip_accents(limpa(x)));
CREATE OR REPLACE MACRO cod_mun(x) AS
    CASE WHEN regexp_matches(limpa(x), '^[0-9]+$') THEN lpad(limpa(x), 5, '0') END;
"""

VIEWS = """
CREATE OR REPLACE VIEW v_bu AS SELECT
    inteiro(ano) AS ano,
    inteiro(turno) AS turno,
    upper(limpa(uf)) AS uf,
    coalesce(limpa(cd_eleicao), 'NA') AS cd_eleicao,
    limpa(ds_eleicao) AS ds_eleicao,
    data_br(dt_pleito) AS dt_eleicao,
    cod_mun(cd_municipio) AS cod_tse_municipio,
    limpa(nm_municipio) AS nm_municipio,
    limpa(nr_zona) AS nr_zona,
    limpa(nr_secao) AS nr_secao,
    limpa(cd_cargo) AS cd_cargo,
    limpa(cargo) AS cargo,
    inteiro(numero_partido) AS numero_partido,
    upper(limpa(sigla_partido)) AS sigla_partido,
    limpa(nome_partido) AS nome_partido,
    inteiro(aptos) AS aptos,
    inteiro(comparecimento) AS comparecimento,
    inteiro(abstencoes) AS abstencoes,
    upper(limpa(ds_tipo_votavel)) AS tipo_votavel,
    limpa(cd_tipo_votavel) AS cd_tipo_votavel,
    coalesce(inteiro(votos), 0) AS votos
FROM stg_boletim_urna;

CREATE OR REPLACE VIEW v_det AS SELECT
    inteiro(ano) AS ano,
    inteiro(turno) AS turno,
    upper(limpa(uf)) AS uf,
    coalesce(limpa(cd_eleicao), 'NA') AS cd_eleicao,
    limpa(ds_eleicao) AS ds_eleicao,
    data_br(dt_eleicao) AS dt_eleicao,
    cod_mun(cd_municipio) AS cod_tse_municipio,
    limpa(nm_municipio) AS nm_municipio,
    limpa(nr_zona) AS nr_zona,
    limpa(cd_cargo) AS cd_cargo,
    limpa(cargo) AS cargo,
    inteiro(aptos) AS aptos,
    inteiro(comparecimento) AS comparecimento,
    inteiro(abstencoes) AS abstencoes,
    inteiro(brancos) AS brancos,
    inteiro(nulos) AS nulos
FROM stg_detalhe_votacao_munzona;
"""

CARGAS_BASE = {
    "eleicao": """
        INSERT INTO eleicao
        SELECT ano, cd_eleicao, turno, max(ds_eleicao), min(dt_eleicao)
        FROM v_bu
        WHERE ano IS NOT NULL AND cd_eleicao IS NOT NULL AND turno IS NOT NULL
        GROUP BY ano, cd_eleicao, turno""",

    "partido": """
        INSERT INTO partido
        SELECT numero_partido, sigla_partido, max(nome_partido)
        FROM v_bu
        WHERE numero_partido IS NOT NULL AND numero_partido > 0 AND sigla_partido IS NOT NULL
        GROUP BY numero_partido, sigla_partido""",

    "municipio": """
        INSERT INTO municipio (cod_tse, id_municipio, nome, uf, regiao)
        SELECT cod_tse_municipio, NULL, max(nm_municipio), max(uf), NULL
        FROM v_bu
        WHERE cod_tse_municipio IS NOT NULL
        GROUP BY cod_tse_municipio""",

    "votos_partido_municipio": """
        INSERT INTO votos_partido_municipio
        SELECT
            ano,
            cd_eleicao,
            cd_cargo,
            max(cargo) AS cargo,
            turno,
            numero_partido,
            sigla_partido,
            cod_tse_municipio,
            NULL AS id_municipio,
            sum(CASE WHEN tipo_votavel = 'NOMINAL' OR cd_tipo_votavel = '1' THEN votos ELSE 0 END) AS votos_nominais,
            sum(CASE WHEN tipo_votavel = 'LEGENDA' OR cd_tipo_votavel = '4' THEN votos ELSE 0 END) AS votos_legenda
        FROM v_bu
        WHERE ano IS NOT NULL
          AND numero_partido IS NOT NULL
          AND numero_partido > 0
          AND cod_tse_municipio IS NOT NULL
        GROUP BY ano, cd_eleicao, cd_cargo, turno, numero_partido, sigla_partido, cod_tse_municipio""",
}

# 1. Agregação híbrida: detalhe oficial quando disponível e BU para eleições
# ausentes no detalhe (ex.: eleição presidencial, 2º turno de 2022).
SQL_PARTICIPACAO_HIBRIDA = """
WITH detalhe_zona AS (
    SELECT
        ano,
        cd_eleicao,
        turno,
        cod_tse_municipio,
        nr_zona,
        max(aptos) AS aptos,
        max(comparecimento) AS comparecimento,
        max(abstencoes) AS abstencoes
    FROM v_det
    WHERE ano IS NOT NULL AND cod_tse_municipio IS NOT NULL
    GROUP BY ano, cd_eleicao, turno, cod_tse_municipio, nr_zona
), detalhe_municipio AS (
    SELECT
        ano,
        cd_eleicao,
        turno,
        cod_tse_municipio,
        sum(aptos) AS aptos,
        sum(comparecimento) AS comparecimento,
        sum(abstencoes) AS abstencoes
    FROM detalhe_zona
    GROUP BY ano, cd_eleicao, turno, cod_tse_municipio
), bu_secao AS (
    SELECT
        ano,
        cd_eleicao,
        turno,
        cod_tse_municipio,
        nr_zona,
        nr_secao,
        max(aptos) AS aptos,
        max(comparecimento) AS comparecimento,
        max(abstencoes) AS abstencoes
    FROM v_bu
    WHERE ano IS NOT NULL AND cod_tse_municipio IS NOT NULL
    GROUP BY ano, cd_eleicao, turno, cod_tse_municipio, nr_zona, nr_secao
), bu_municipio AS (
    SELECT
        ano,
        cd_eleicao,
        turno,
        cod_tse_municipio,
        sum(aptos) AS aptos,
        sum(comparecimento) AS comparecimento,
        sum(abstencoes) AS abstencoes
    FROM bu_secao
    GROUP BY ano, cd_eleicao, turno, cod_tse_municipio
), combinado AS (
    SELECT * FROM detalhe_municipio
    UNION ALL
    SELECT b.*
    FROM bu_municipio b
    WHERE NOT EXISTS (
        SELECT 1
        FROM detalhe_municipio d
        WHERE d.ano = b.ano
          AND d.cd_eleicao = b.cd_eleicao
          AND d.turno = b.turno
          AND d.cod_tse_municipio = b.cod_tse_municipio
    )
)
INSERT INTO participacao_eleitoral
SELECT
    ano,
    cd_eleicao,
    turno,
    cod_tse_municipio,
    NULL AS id_municipio,
    sum(aptos) AS eleitorado_apto,
    sum(comparecimento) AS comparecimento,
    sum(abstencoes) AS abstencoes,
    sum(abstencoes)::DOUBLE / nullif(sum(aptos), 0) AS taxa_abstencao
FROM combinado
GROUP BY ano, cd_eleicao, turno, cod_tse_municipio
"""

# 2. Agregação a partir do Boletim de Urna (deduplicação mandatória por seção/urna)
SQL_PARTICIPACAO_BU = """
WITH secao_urna AS (
    SELECT
        ano,
        cd_eleicao,
        turno,
        cod_tse_municipio,
        nr_zona,
        nr_secao,
        max(aptos) AS aptos,
        max(comparecimento) AS comparecimento,
        max(abstencoes) AS abstencoes
    FROM v_bu
    WHERE ano IS NOT NULL AND cod_tse_municipio IS NOT NULL
    GROUP BY ano, cd_eleicao, turno, cod_tse_municipio, nr_zona, nr_secao
)
INSERT INTO participacao_eleitoral
SELECT
    ano,
    cd_eleicao,
    turno,
    cod_tse_municipio,
    NULL AS id_municipio,
    sum(aptos) AS eleitorado_apto,
    sum(comparecimento) AS comparecimento,
    sum(abstencoes) AS abstencoes,
    sum(abstencoes)::DOUBLE / nullif(sum(aptos), 0) AS taxa_abstencao
FROM secao_urna
GROUP BY ano, cd_eleicao, turno, cod_tse_municipio
"""


def _lit(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def montar_tabelas(con, de_para=None):
    """Cria macros e views e popula as tabelas finais da Q3 a partir do staging."""
    con.execute(MACROS)
    con.execute(VIEWS)

    for tabela, sql in CARGAS_BASE.items():
        con.execute(sql)
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        print(f"   {tabela:<26} {n:>12,} linhas")

    # Participação Eleitoral: usa detalhe_votacao_munzona preferencialmente se disponível
    tabelas_existentes = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    tem_detalhe = False
    if "stg_detalhe_votacao_munzona" in tabelas_existentes:
        tem_detalhe = con.execute("SELECT count(*) FROM stg_detalhe_votacao_munzona").fetchone()[0] > 0

    if tem_detalhe:
        con.execute(SQL_PARTICIPACAO_HIBRIDA)
        fonte_partic = "detalhe_votacao_munzona + BU para eleições ausentes"
    else:
        con.execute(SQL_PARTICIPACAO_BU)
        fonte_partic = "boletim_urna (deduplicado)"

    n_partic = con.execute("SELECT count(*) FROM participacao_eleitoral").fetchone()[0]
    print(f"   {'participacao_eleitoral':<26} {n_partic:>12,} linhas (fonte: {fonte_partic})")

    # 1. Aplica o de-para oficial TSE <-> IBGE
    if de_para and Path(de_para).exists():
        _aplicar_de_para(con, de_para)

    # 2. Atualiza macrorregião a partir de stg_ibge_municipio se disponível
    if "stg_ibge_municipio" in tabelas_existentes:
        con.execute("""
            UPDATE municipio m
            SET regiao = ib.regiao,
                nome = coalesce(m.nome, ib.nome)
            FROM stg_ibge_municipio ib
            WHERE m.id_municipio = ib.id_municipio
        """)

    # 3. Propaga id_municipio para votos_partido_municipio e participacao_eleitoral
    con.execute("""
        UPDATE votos_partido_municipio v
        SET id_municipio = m.id_municipio
        FROM municipio m
        WHERE v.cod_tse_municipio = m.cod_tse
    """)
    con.execute("""
        UPDATE participacao_eleitoral p
        SET id_municipio = m.id_municipio
        FROM municipio m
        WHERE p.cod_tse_municipio = m.cod_tse
    """)

    # 4. Popula censo_municipio (população e PIB de 2022; IDHM com ano real de 2010)
    if "stg_ibge_censo" in tabelas_existentes:
        con.execute("""
            INSERT INTO censo_municipio (id_municipio, ano_referencia, populacao, pib, pib_per_capita, idhm)
            SELECT
                c.id_municipio,
                2022 AS ano_referencia,
                c.populacao,
                c.pib,
                c.pib / nullif(c.populacao, 0) AS pib_per_capita,
                NULL AS idhm
            FROM stg_ibge_censo c
            JOIN municipio m ON m.id_municipio = c.id_municipio
        """)

    if "stg_idhm" in tabelas_existentes:
        con.execute("""
            INSERT INTO censo_municipio (id_municipio, ano_referencia, populacao, pib, pib_per_capita, idhm)
            SELECT
                h.id_municipio,
                coalesce(h.ano_referencia, 2010) AS ano_referencia,
                NULL AS populacao,
                NULL AS pib,
                NULL AS pib_per_capita,
                h.idhm
            FROM stg_idhm h
            JOIN municipio m ON m.id_municipio = h.id_municipio
            ON CONFLICT (id_municipio, ano_referencia) DO UPDATE SET idhm = EXCLUDED.idhm
        """)

    n_censo = con.execute("SELECT count(*) FROM censo_municipio").fetchone()[0]
    print(f"   {'censo_municipio':<26} {n_censo:>12,} linhas")


def _aplicar_de_para(con, caminho):
    """Preenche municipio.id_municipio (IBGE) a partir de um CSV com códigos TSE e IBGE."""
    caminho = Path(caminho)
    with open(caminho, encoding="latin-1") as f:
        primeira = f.readline()
        delim = ";" if ";" in primeira else ","

    try:
        rel = con.execute(f"SELECT * FROM read_csv({_lit(caminho.as_posix())}, delim='{delim}', all_varchar=true) LIMIT 0")
        csv_sql = f"read_csv({_lit(caminho.as_posix())}, delim='{delim}', all_varchar=true)"
    except Exception:
        rel = con.execute(f"SELECT * FROM read_csv({_lit(caminho.as_posix())}, delim='{delim}', all_varchar=true, ignore_errors=true) LIMIT 0")
        csv_sql = f"read_csv({_lit(caminho.as_posix())}, delim='{delim}', all_varchar=true, ignore_errors=true)"

    cols = {d[0].lower(): d[0] for d in rel.description}
    tse = next((cols[c] for c in ("cod_tse", "id_municipio_tse", "cd_municipio_tse", "cd_municipio") if c in cols), None)
    ibge = next((cols[c] for c in ("id_municipio", "cod_ibge", "id_municipio_ibge", "cd_municipio_ibge") if c in cols), None)

    if not (tse and ibge):
        print(f"   de-para ignorado: não achei colunas de código TSE e IBGE em {caminho}")
        return

    con.execute(f"""
        UPDATE municipio m SET id_municipio = d.ibge
        FROM (SELECT lpad(trim("{tse}"), 5, '0') AS tse, trim("{ibge}") AS ibge
              FROM {csv_sql}) d
        WHERE m.cod_tse = d.tse""")

    sem = con.execute("SELECT count(*) FROM municipio WHERE id_municipio IS NULL").fetchone()[0]
    print(f"   de-para aplicado ({caminho.name}); municípios sem código IBGE: {sem}")
