"""Tabelas finais do domínio de trajetória eleitoral."""

TABELAS_TRAJETORIA = {
    "cargo": """
        cd_cargo VARCHAR PRIMARY KEY,
        nome VARCHAR,
        esfera VARCHAR,
        poder VARCHAR,
        ordem_hierarquica INTEGER""",
    "candidato": """
        id_candidato VARCHAR PRIMARY KEY,
        titulo_eleitoral VARCHAR,
        nome VARCHAR,
        nome_urna VARCHAR,
        data_nascimento DATE,
        genero VARCHAR,
        raca VARCHAR,
        grau_instrucao VARCHAR,
        ocupacao VARCHAR,
        uf_nascimento VARCHAR,
        metodo_identidade VARCHAR,
        identidade_ambigua BOOLEAN DEFAULT FALSE""",
    "candidatura": """
        id_candidatura VARCHAR PRIMARY KEY,
        id_candidato VARCHAR NOT NULL,
        ano INTEGER NOT NULL,
        cd_eleicao VARCHAR NOT NULL,
        turno SMALLINT NOT NULL,
        cd_cargo VARCHAR NOT NULL,
        numero_partido INTEGER,
        sigla_partido VARCHAR,
        uf VARCHAR,
        cod_tse_municipio VARCHAR,
        numero_candidato INTEGER,
        idade_eleicao INTEGER,
        sequencial VARCHAR,
        escolaridade_candidatura VARCHAR,
        situacao_registro VARCHAR,
        patrimonio DOUBLE,
        publicidade_propaganda DOUBLE,
        reeleicao BOOLEAN""",
    "resultado_candidatura": """
        id_candidatura VARCHAR PRIMARY KEY,
        votos BIGINT,
        percentual_votos DOUBLE,
        colocacao INTEGER,
        situacao_final VARCHAR,
        eleito BOOLEAN,
        suplente BOOLEAN,
        segundo_turno BOOLEAN""",
}


def criar_tabelas(con):
    for nome, colunas in TABELAS_TRAJETORIA.items():
        con.execute(f"DROP TABLE IF EXISTS {nome}")
        con.execute(f"CREATE TABLE {nome} ({colunas})")
