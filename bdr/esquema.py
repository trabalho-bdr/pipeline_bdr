"""Tabelas finais do DER para a Questão 3 no banco de cada membro.

Questão 3:
"Como características socioeconômicas dos municípios se relacionam com a distribuição
dos votos entre partidos e com a taxa de abstenção?"

As tabelas utilizam chaves naturais e identificadores oficiais (código TSE de 5 dígitos
e código IBGE de 7 dígitos), permitindo que cada membro processe seu recorte e a posterior
consolidação sem conflitos.
"""

TABELAS = {
    "municipio": """
        cod_tse VARCHAR PRIMARY KEY,      -- código TSE do município (5 dígitos)
        id_municipio VARCHAR,             -- código IBGE oficial (7 dígitos)
        nome VARCHAR,
        uf VARCHAR,
        regiao VARCHAR""",
    "eleicao": """
        ano INTEGER,
        cd_eleicao VARCHAR,
        turno SMALLINT,
        ds_eleicao VARCHAR,
        dt_eleicao DATE,
        PRIMARY KEY (ano, cd_eleicao, turno)""",
    "partido": """
        numero INTEGER,
        sigla VARCHAR,
        nome VARCHAR,
        PRIMARY KEY (numero, sigla)""",
    "votos_partido_municipio": """
        ano INTEGER,
        cd_eleicao VARCHAR,
        cd_cargo VARCHAR,
        cargo VARCHAR,
        turno SMALLINT,
        numero_partido INTEGER,
        sigla_partido VARCHAR,
        cod_tse_municipio VARCHAR,
        id_municipio VARCHAR,
        votos_nominais BIGINT,
        votos_legenda BIGINT,
        PRIMARY KEY (ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio)""",
    "participacao_eleitoral": """
        ano INTEGER,
        cd_eleicao VARCHAR,
        turno SMALLINT,
        cod_tse_municipio VARCHAR,
        id_municipio VARCHAR,
        eleitorado_apto BIGINT,
        comparecimento BIGINT,
        abstencoes BIGINT,
        taxa_abstencao DOUBLE,
        PRIMARY KEY (ano, cd_eleicao, turno, cod_tse_municipio)""",
    "censo_municipio": """
        id_municipio VARCHAR,
        ano_referencia INTEGER,
        populacao BIGINT,
        pib DECIMAL(18,2),
        pib_per_capita DECIMAL(18,2),
        idhm DOUBLE,
        PRIMARY KEY (id_municipio, ano_referencia)""",
}


def criar_tabelas(con):
    for nome, colunas in TABELAS.items():
        con.execute(f"DROP TABLE IF EXISTS {nome}")
        con.execute(f"CREATE TABLE {nome} ({colunas}\n)")
