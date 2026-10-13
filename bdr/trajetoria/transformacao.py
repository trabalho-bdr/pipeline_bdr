"""Normaliza layouts históricos do TSE nas tabelas de trajetória."""

from pathlib import Path

from .esquema import criar_tabelas


def _cpf_valido(valor):
    """Retorna somente CPF com os dois dígitos verificadores válidos."""
    if valor is None:
        return None
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return None
    for tamanho in (9, 10):
        resto = sum(int(digitos[i]) * (tamanho + 1 - i) for i in range(tamanho)) % 11
        verificador = 0 if resto < 2 else 11 - resto
        if int(digitos[tamanho]) != verificador:
            return None
    return digitos


ALIASES = {
    "ano": ["ANO_ELEICAO", "ANO"],
    "turno": ["NR_TURNO", "NUM_TURNO"],
    "uf": ["SG_UF", "SIGLA_UF"],
    "cd_eleicao": ["CD_ELEICAO", "CODIGO_ELEICAO"],
    "ds_eleicao": ["DS_ELEICAO", "DESCRICAO_ELEICAO"],
    "dt_eleicao": ["DT_ELEICAO", "DATA_ELEICAO"],
    "sq_candidato": ["SQ_CANDIDATO", "SEQUENCIAL_CANDIDATO"],
    "cpf": ["NR_CPF_CANDIDATO", "CPF_CANDIDATO"],
    "titulo": ["NR_TITULO_ELEITORAL_CANDIDATO", "NR_TITULO_ELEITORAL", "NR_TITULO_CANDIDATO"],
    "nome": ["NM_CANDIDATO", "NOME_CANDIDATO"],
    "nome_urna": ["NM_URNA_CANDIDATO", "NOME_URNA_CANDIDATO"],
    "nascimento": ["DT_NASCIMENTO", "DATA_NASCIMENTO"],
    "genero": ["DS_GENERO", "DESCRICAO_SEXO"],
    "raca": ["DS_COR_RACA", "DS_RACA_COR", "DS_COR_RACA_CANDIDATO"],
    "instrucao": ["DS_GRAU_INSTRUCAO", "DESCRICAO_GRAU_INSTRUCAO"],
    "ocupacao": ["DS_OCUPACAO", "DESCRICAO_OCUPACAO"],
    "uf_nascimento": ["SG_UF_NASCIMENTO", "SIGLA_UF_NASCIMENTO"],
    "cd_cargo": ["CD_CARGO", "CODIGO_CARGO"],
    "cargo": ["DS_CARGO", "DESCRICAO_CARGO"],
    "numero_partido": ["NR_PARTIDO", "NUMERO_PARTIDO"],
    "sigla_partido": ["SG_PARTIDO", "SIGLA_PARTIDO"],
    "nome_partido": ["NM_PARTIDO", "NOME_PARTIDO"],
    "cod_municipio": ["SG_UE", "CD_MUNICIPIO", "CODIGO_MUNICIPIO"],
    "numero_candidato": ["NR_CANDIDATO", "NUMERO_CANDIDATO"],
    "idade": ["NR_IDADE_DATA_POSSE", "NR_IDADE_DATA_ELEICAO"],
    "situacao_registro": ["DS_SITUACAO_CANDIDATURA", "DS_DETALHE_SITUACAO_CAND"],
    "resultado": ["DS_SIT_TOT_TURNO", "DESC_SIT_TOT_TURNO"],
    "patrimonio": ["VR_BEM_CANDIDATO", "VALOR_BENS"],
    "tipo_despesa": ["DS_TIPO_DESPESA", "DESCRICAO_TIPO_DESPESA", "DS_DESPESA"],
    "valor_despesa": ["VR_DESPESA_CONTRATADA", "VALOR_DESPESA_CONTRATADA"],
    "reeleicao": ["ST_REELEICAO"],
    "votos": ["QT_VOTOS_NOMINAIS", "QTD_VOTOS_NOMINAIS", "QT_VOTOS"],
}


def _lit(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ident(valor):
    return '"' + str(valor).replace('"', '""') + '"'


def _fonte(arquivos):
    if isinstance(arquivos, str):
        if not arquivos.replace("_", "").isalnum():
            raise ValueError("Nome inválido de tabela de staging")
        return arquivos
    lista = ", ".join(_lit(Path(a).as_posix()) for a in arquivos)
    return f"read_csv([{lista}], delim=';', header=true, all_varchar=true, union_by_name=true)"


def _colunas(con, fonte):
    return {r[0].upper(): r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {fonte}").fetchall()}


def _expr(colunas, chave, padrao="NULL"):
    presentes = [colunas[a] for a in ALIASES[chave] if a in colunas]
    if not presentes:
        return padrao
    termos = [f"nullif(trim({_ident(c)}), '')" for c in presentes]
    return "coalesce(" + ", ".join(termos + [padrao]) + ")"


def _data(expr):
    return (
        f"coalesce(try_strptime({expr}, '%d/%m/%Y')::DATE, "
        f"try_strptime({expr}, '%Y-%m-%d')::DATE)"
    )


def _valor_monetario(expr):
    return f"try_cast(replace(replace({expr}, '.', ''), ',', '.') AS DOUBLE)"


def carregar(con, arquivos_candidatos, arquivos_votos, arquivos_despesas=()):
    if not arquivos_candidatos:
        raise ValueError("Nenhum arquivo consulta_cand foi encontrado.")
    criar_tabelas(con)
    con.create_function("cpf_valido_bdr", _cpf_valido, ["VARCHAR"], "VARCHAR", null_handling="special")
    cand = _fonte(arquivos_candidatos)
    cc = _colunas(con, cand)

    ano = f"try_cast({_expr(cc, 'ano')} AS INTEGER)"
    turno = f"coalesce(try_cast({_expr(cc, 'turno')} AS SMALLINT), 1)"
    uf = f"upper({_expr(cc, 'uf')})"
    eleicao = _expr(cc, "cd_eleicao", "'NA'")
    sq = _expr(cc, "sq_candidato")
    cpf = _expr(cc, "cpf")
    nome = _expr(cc, "nome")
    nascimento_raw = _expr(cc, "nascimento")
    nascimento = _data(nascimento_raw)
    cd_cargo = _expr(cc, "cd_cargo", "'NA'")
    numero_partido = f"try_cast({_expr(cc, 'numero_partido')} AS INTEGER)"
    sigla = f"upper({_expr(cc, 'sigla_partido')})"
    cod_mun = _expr(cc, "cod_municipio")
    id_pessoa = (
        "md5(CASE WHEN " + cpf + " IS NOT NULL THEN 'CPF|' || " + cpf +
        " ELSE 'BIO|' || upper(strip_accents(coalesce(" + nome + ", ''))) || '|' || "
        "coalesce(cast(" + nascimento + " AS VARCHAR), '') || '|' || " +
        "coalesce(upper(" + _expr(cc, "uf_nascimento") + "), '') END)"
    )
    id_candidatura = (
        "md5(cast(" + ano + " AS VARCHAR) || '|' || coalesce(" + eleicao + ", 'NA') || '|' || "
        "cast(" + turno + " AS VARCHAR) || '|' || coalesce(" + uf + ", '') || '|' || "
        "coalesce(" + cod_mun + ", '') || '|' || "
        "coalesce(" + sq + ", " + nome + ") || '|' || coalesce(" + cd_cargo + ", 'NA'))"
    )

    despesas = _fonte(arquivos_despesas) if arquivos_despesas else None
    if despesas:
        dc = _colunas(con, despesas)
        despesa_ano = f"try_cast({_expr(dc, 'ano')} AS INTEGER)"
        despesa_uf = f"upper({_expr(dc, 'uf')})"
        despesa_eleicao = _expr(dc, 'cd_eleicao', "'NA'")
        despesa_sq = _expr(dc, 'sq_candidato')
        despesa_tipo = _expr(dc, 'tipo_despesa')
        despesa_valor = _valor_monetario(_expr(dc, 'valor_despesa'))
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE despesas_normalizadas AS
            SELECT {despesa_ano} AS despesa_ano, {despesa_uf} AS despesa_uf,
                   {despesa_eleicao} AS despesa_eleicao,
                   {despesa_sq} AS despesa_sq_candidato,
                   nullif(trim({despesa_tipo}), '') AS categoria,
                   {despesa_valor} AS valor
            FROM {despesas}
            WHERE {despesa_tipo} IS NOT NULL AND {despesa_valor} IS NOT NULL
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE gastos_por_candidatura AS
            SELECT despesa_ano, despesa_uf, despesa_eleicao, despesa_sq_candidato,
                   sum(valor) AS gastos_campanha_total
            FROM despesas_normalizadas
            GROUP BY 1, 2, 3, 4
        """)
    else:
        con.execute("""
            CREATE OR REPLACE TEMP TABLE despesas_normalizadas AS
            SELECT NULL::INTEGER despesa_ano, NULL::VARCHAR despesa_uf,
                   NULL::VARCHAR despesa_eleicao, NULL::VARCHAR despesa_sq_candidato,
                   NULL::VARCHAR categoria, NULL::DOUBLE valor
            WHERE false
        """)
        con.execute("""
            CREATE OR REPLACE TEMP TABLE gastos_por_candidatura AS
                 SELECT NULL::INTEGER despesa_ano, NULL::VARCHAR despesa_uf,
                     NULL::VARCHAR despesa_eleicao, NULL::VARCHAR despesa_sq_candidato,
                     NULL::DOUBLE gastos_campanha_total
            WHERE false
        """)

    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE src_candidatura AS
        SELECT
            {id_candidatura} AS id_candidatura,
            {id_pessoa} AS id_candidato,
            {_expr(cc, 'titulo')} AS titulo_eleitoral,
            {ano} AS ano,
            {eleicao} AS cd_eleicao,
            {turno} AS turno,
            {uf} AS uf,
            {sq} AS sq_candidato,
            cpf_valido_bdr({cpf}) AS cpf_validado,
            {nome} AS nome,
            {_expr(cc, 'nome_urna')} AS nome_urna,
            {nascimento} AS data_nascimento,
            {_expr(cc, 'genero')} AS genero,
            {_expr(cc, 'raca')} AS raca,
            {_expr(cc, 'instrucao')} AS grau_instrucao,
            {_expr(cc, 'ocupacao')} AS ocupacao,
            {f'upper({_expr(cc, "uf_nascimento")})'} AS uf_nascimento,
            {cd_cargo} AS cd_cargo,
            {_expr(cc, 'cargo')} AS cargo,
            {numero_partido} AS numero_partido,
            {sigla} AS sigla_partido,
            {_expr(cc, 'nome_partido')} AS nome_partido,
            CASE WHEN regexp_matches(coalesce({cod_mun}, ''), '^[0-9]+$')
                 THEN lpad({cod_mun}, 5, '0') END AS cod_tse_municipio,
            try_cast({_expr(cc, 'numero_candidato')} AS INTEGER) AS numero_candidato,
            try_cast({_expr(cc, 'idade')} AS INTEGER) AS idade_eleicao,
            {sq} AS sequencial,
            {_expr(cc, 'instrucao')} AS escolaridade_candidatura,
            {_expr(cc, 'situacao_registro')} AS situacao_registro,
            upper({_expr(cc, 'resultado')}) AS situacao_final,
            try_cast(replace(replace({_expr(cc, 'patrimonio')}, '.', ''), ',', '.') AS DOUBLE) AS patrimonio,
            pp.gastos_campanha_total,
            upper({_expr(cc, 'reeleicao')}) IN ('S', 'SIM', '1') AS reeleicao,
            {_expr(cc, 'ds_eleicao')} AS ds_eleicao,
            {_data(_expr(cc, 'dt_eleicao'))} AS dt_eleicao,
            CASE WHEN {cpf} IS NOT NULL THEN 'CPF' ELSE 'BIOGRAFICO' END AS metodo_identidade
                FROM {cand}
                LEFT JOIN gastos_por_candidatura pp
                      ON pp.despesa_ano = {ano} AND pp.despesa_uf = {uf}
                 AND pp.despesa_sq_candidato = {sq}
                 AND (pp.despesa_eleicao = 'NA' OR pp.despesa_eleicao = {eleicao})
        WHERE {ano} IS NOT NULL AND {nome} IS NOT NULL
    """)

    con.execute("""CREATE TEMP TABLE identidade_bio AS
        SELECT bio_chave, count(DISTINCT cpf_validado) quant_cpf,
               min(cpf_validado) cpf_unico
        FROM (
                        SELECT cpf_validado,
                            CASE WHEN data_nascimento IS NOT NULL
                                THEN regexp_replace(upper(strip_accents(trim(nome))), '\\s+', ' ', 'g')
                                         || '|' || cast(data_nascimento AS VARCHAR) || '|' || coalesce(uf_nascimento, '') END bio_chave
            FROM src_candidatura)
        WHERE bio_chave IS NOT NULL GROUP BY bio_chave""")
    con.execute("""UPDATE src_candidatura s SET
        id_candidato = CASE
            WHEN s.cpf_validado IS NOT NULL THEN md5('CPF|' || s.cpf_validado)
            WHEN i.quant_cpf = 1 THEN md5('CPF|' || i.cpf_unico)
            WHEN i.quant_cpf = 0 THEN md5('BIO|' || i.bio_chave)
            ELSE md5('BIO_UNICA|' || s.id_candidatura) END,
        metodo_identidade = CASE
            WHEN s.cpf_validado IS NOT NULL THEN 'CPF'
            WHEN i.quant_cpf = 1 THEN 'BIO_MATCH_CPF'
            WHEN i.quant_cpf = 0 THEN 'BIO'
            ELSE 'AMBIGUA' END
        FROM identidade_bio i
        WHERE i.bio_chave = regexp_replace(upper(strip_accents(trim(s.nome))), '\\s+', ' ', 'g')
            || '|' || cast(s.data_nascimento AS VARCHAR) || '|' || coalesce(s.uf_nascimento, '')""")
    con.execute("""UPDATE src_candidatura SET
        id_candidato=md5('BIO_UNICA|' || id_candidatura), metodo_identidade='AMBIGUA'
        WHERE cpf_validado IS NULL AND data_nascimento IS NULL""")

    con.execute("""
        INSERT INTO candidato
        SELECT id_candidato, max(titulo_eleitoral), max(nome), max(nome_urna), min(data_nascimento),
               max(genero), max(raca), max(grau_instrucao), max(ocupacao), max(uf_nascimento),
               max(metodo_identidade), count(DISTINCT nome) > 1
        FROM src_candidatura GROUP BY id_candidato
    """)
    con.execute("""
        INSERT INTO cargo
        SELECT cd_cargo, max(cargo),
               CASE WHEN max(cargo) IN ('Prefeito','Vice-Prefeito','Vereador') THEN 'MUNICIPAL'
                    WHEN max(cargo) IN ('Governador','Vice-Governador','Deputado Estadual','Deputado Distrital') THEN 'ESTADUAL'
                    ELSE 'FEDERAL' END,
               CASE WHEN max(cargo) IN ('Presidente','Vice-Presidente','Governador','Vice-Governador','Prefeito','Vice-Prefeito')
                    THEN 'EXECUTIVO' ELSE 'LEGISLATIVO' END,
               CASE max(cargo) WHEN 'Vereador' THEN 1 WHEN 'Prefeito' THEN 2
                    WHEN 'Deputado Estadual' THEN 3 WHEN 'Deputado Distrital' THEN 3
                    WHEN 'Deputado Federal' THEN 4 WHEN 'Senador' THEN 5
                    WHEN 'Governador' THEN 6 WHEN 'Presidente' THEN 7 ELSE NULL END
        FROM src_candidatura WHERE cd_cargo IS NOT NULL GROUP BY cd_cargo
    """)
    con.execute("""
        INSERT INTO candidatura
        SELECT id_candidatura, id_candidato, ano, cd_eleicao, turno, cd_cargo,
               numero_partido, sigla_partido, uf, cod_tse_municipio,
               numero_candidato, idade_eleicao, sequencial, escolaridade_candidatura,
               situacao_registro, patrimonio, gastos_campanha_total, reeleicao
        FROM src_candidatura
        QUALIFY row_number() OVER (PARTITION BY id_candidatura ORDER BY sq_candidato) = 1
    """)
    con.execute("""
        INSERT INTO despesa_candidatura
        SELECT md5('DESPESA|' || cast(d.despesa_ano AS VARCHAR) || '|' ||
                   d.despesa_eleicao || '|' || d.despesa_uf || '|' ||
                   d.despesa_sq_candidato || '|' || d.categoria),
               c.id_candidatura, d.categoria, sum(d.valor)
        FROM despesas_normalizadas d
        JOIN candidatura c
                    ON c.ano = d.despesa_ano AND c.uf = d.despesa_uf
                 AND trim(c.sequencial) = trim(d.despesa_sq_candidato)
                 AND (d.despesa_eleicao = 'NA' OR c.cd_eleicao = d.despesa_eleicao)
        GROUP BY c.id_candidatura, d.despesa_ano, d.despesa_eleicao,
                 d.despesa_uf, d.despesa_sq_candidato, d.categoria
    """)

    # Complementa dimensões compartilhadas quando elas já existem no banco.
    existentes = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    if "eleicao" in existentes:
        con.execute("""
            INSERT INTO eleicao
            SELECT ano, cd_eleicao, turno, max(ds_eleicao), min(dt_eleicao)
            FROM src_candidatura GROUP BY ano, cd_eleicao, turno
            ON CONFLICT DO NOTHING
        """)
    if "partido" in existentes:
        con.execute("""
            INSERT INTO partido
            SELECT numero_partido, sigla_partido, max(nome_partido)
            FROM src_candidatura
            WHERE numero_partido IS NOT NULL AND sigla_partido IS NOT NULL
            GROUP BY numero_partido, sigla_partido ON CONFLICT DO NOTHING
        """)

    if arquivos_votos:
        votos = _fonte(arquivos_votos)
        cv = _colunas(con, votos)
        va = f"try_cast({_expr(cv, 'ano')} AS INTEGER)"
        vt = f"coalesce(try_cast({_expr(cv, 'turno')} AS SMALLINT), 1)"
        ve = _expr(cv, "cd_eleicao", "'NA'")
        vu = f"upper({_expr(cv, 'uf')})"
        vsq = _expr(cv, "sq_candidato")
        vcargo = _expr(cv, "cd_cargo", "'NA'")
        vmunicipio = _expr(cv, "cod_municipio")
        vvotos = f"coalesce(try_cast({_expr(cv, 'votos')} AS BIGINT), 0)"
        con.execute(f"""
            CREATE OR REPLACE TEMP VIEW votos_candidatura AS
            SELECT md5(cast({va} AS VARCHAR) || '|' || coalesce({ve}, 'NA') || '|' ||
                       cast({vt} AS VARCHAR) || '|' || coalesce({vu}, '') || '|' ||
                       coalesce({vmunicipio}, '') || '|' ||
                       coalesce({vsq}, '') || '|' || coalesce({vcargo}, 'NA')) AS id_candidatura,
                   sum({vvotos}) AS votos
            FROM {votos}
            WHERE {va} IS NOT NULL AND {vsq} IS NOT NULL
            GROUP BY ALL
        """)
    else:
        con.execute("CREATE OR REPLACE TEMP VIEW votos_candidatura AS SELECT NULL::VARCHAR id_candidatura, NULL::BIGINT votos WHERE false")

    con.execute("""
        INSERT INTO resultado_candidatura
        SELECT c.id_candidatura, max(v.votos), NULL, NULL, max(s.situacao_final),
               starts_with(coalesce(max(s.situacao_final), ''), 'ELEITO'),
               contains(coalesce(max(s.situacao_final), ''), 'SUPLENTE'),
               c.turno = 2
        FROM candidatura c
        JOIN src_candidatura s USING (id_candidatura)
        LEFT JOIN votos_candidatura v USING (id_candidatura)
        GROUP BY c.id_candidatura, c.turno
    """)
    con.execute("""
        UPDATE resultado_candidatura r
        SET percentual_votos = x.percentual,
            colocacao = x.colocacao
        FROM (
            SELECT c.id_candidatura,
                   100.0 * coalesce(r2.votos, 0) /
                       nullif(sum(coalesce(r2.votos, 0)) OVER grupo, 0) AS percentual,
                   dense_rank() OVER (
                       PARTITION BY c.ano, c.cd_eleicao, c.turno, c.cd_cargo,
                                    c.uf, coalesce(c.cod_tse_municipio, '')
                       ORDER BY coalesce(r2.votos, 0) DESC
                   ) AS colocacao
            FROM candidatura c
            JOIN resultado_candidatura r2 USING (id_candidatura)
            WINDOW grupo AS (
                PARTITION BY c.ano, c.cd_eleicao, c.turno, c.cd_cargo,
                             c.uf, coalesce(c.cod_tse_municipio, '')
            )
        ) x
        WHERE r.id_candidatura = x.id_candidatura
    """)

    con.execute("""
        CREATE OR REPLACE VIEW vw_trajetoria_candidato AS
        WITH base AS (
            SELECT c.id_candidato, c.id_candidatura, c.ano, c.cd_cargo,
                   c.sigla_partido, c.uf, c.cod_tse_municipio,
                   r.eleito, r.suplente, r.votos,
                   lag(c.ano) OVER (PARTITION BY c.id_candidato ORDER BY c.ano) AS ano_anterior
            FROM candidatura c
            LEFT JOIN resultado_candidatura r USING (id_candidatura)
        )
        SELECT id_candidato, min(ano) AS primeira_candidatura,
               max(ano) AS ultima_candidatura, count(*) AS candidaturas,
               count(*) FILTER (WHERE eleito) AS vitorias,
               count(DISTINCT sigla_partido) AS partidos,
               count(DISTINCT cd_cargo) AS cargos,
               count(DISTINCT uf) AS ufs,
               max(ano - ano_anterior) AS maior_intervalo_anos,
               max(ano - ano_anterior) > 2 AS teve_interrupcao
        FROM base GROUP BY id_candidato
    """)
