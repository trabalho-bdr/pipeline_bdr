"""Esquema final do DER para Q3 e Q10. A ordem das colunas é contratual."""

TABELAS_DER = {
    "Municipio": "id_municipio VARCHAR PRIMARY KEY, cod_tse VARCHAR UNIQUE, nome VARCHAR, uf VARCHAR, regiao VARCHAR",
    "Partido": "id_partido VARCHAR PRIMARY KEY, sigla VARCHAR, nome VARCHAR, numero INTEGER",
    "Eleicao": "id_eleicao VARCHAR PRIMARY KEY, ano INTEGER, tipo_eleicao VARCHAR, turno SMALLINT, cargo VARCHAR, data DATE",
    "Candidato": "id_candidato VARCHAR PRIMARY KEY, titulo_eleitoral VARCHAR, nome_civil VARCHAR, dt_nascimento DATE, genero VARCHAR, raca VARCHAR, ocupacao VARCHAR",
    "Censo_Municipio": "id_municipio VARCHAR, ano_referencia INTEGER, populacao BIGINT, idhm DOUBLE, pib DECIMAL(18,2), idade_mediana DOUBLE, indice_envelhecimento DOUBLE, PRIMARY KEY (id_municipio, ano_referencia), FOREIGN KEY (id_municipio) REFERENCES Municipio(id_municipio)",
    "Participacao_Eleitoral": "id_participacao VARCHAR PRIMARY KEY, id_municipio VARCHAR NOT NULL, ano_participacao INTEGER, cargo VARCHAR, eleitorado_apto BIGINT, comparecimento BIGINT, abstencoes BIGINT, taxa_abstencao DOUBLE, FOREIGN KEY (id_municipio) REFERENCES Municipio(id_municipio)",
    "Candidatura": "id_candidatura VARCHAR PRIMARY KEY, id_eleicao VARCHAR NOT NULL, id_candidato VARCHAR NOT NULL, id_municipio VARCHAR, id_partido VARCHAR, uf VARCHAR, nome_urna VARCHAR, numero_urna INTEGER, idade_eleicao INTEGER, situacao_registro VARCHAR, sequencial VARCHAR, escolaridade_candidatura VARCHAR, patrimonio DOUBLE, gastos_campanha_total DOUBLE, FOREIGN KEY (id_eleicao) REFERENCES Eleicao(id_eleicao), FOREIGN KEY (id_candidato) REFERENCES Candidato(id_candidato), FOREIGN KEY (id_municipio) REFERENCES Municipio(id_municipio), FOREIGN KEY (id_partido) REFERENCES Partido(id_partido)",
    "Despesa_Candidatura": "id_despesa VARCHAR PRIMARY KEY, id_candidatura VARCHAR NOT NULL, categoria VARCHAR NOT NULL, valor DOUBLE, FOREIGN KEY (id_candidatura) REFERENCES Candidatura(id_candidatura)",
    "Resultado_Candidatura": "id_resultado VARCHAR PRIMARY KEY, id_candidatura VARCHAR NOT NULL, turno SMALLINT, resultado VARCHAR, votos BIGINT, FOREIGN KEY (id_candidatura) REFERENCES Candidatura(id_candidatura)",
    "Cargo": "id_cargo VARCHAR PRIMARY KEY, nome VARCHAR, id_candidatura VARCHAR NOT NULL, FOREIGN KEY (id_candidatura) REFERENCES Candidatura(id_candidatura)",
    "Votos_Partido_Municipio": "id_votos VARCHAR PRIMARY KEY, id_eleicao VARCHAR NOT NULL, id_partido VARCHAR NOT NULL, id_municipio VARCHAR NOT NULL, turno SMALLINT, votos_nominais BIGINT, votos_legenda BIGINT, FOREIGN KEY (id_eleicao) REFERENCES Eleicao(id_eleicao), FOREIGN KEY (id_partido) REFERENCES Partido(id_partido), FOREIGN KEY (id_municipio) REFERENCES Municipio(id_municipio)",
}


def criar(con):
    for nome, definicao in TABELAS_DER.items():
        con.execute(f'CREATE TABLE "{nome}" ({definicao})')
