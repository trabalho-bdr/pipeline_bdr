"""Carga e integração da Questão 9 (Publicidade Eleitoral) no DER.

Processa despesas eleitorais oficiais de 2018, 2020, 2022 e 2024 para CE, MA, MS, RJ, RN, RS.
Implementa deduplicação rigorosa, resolução unívoca de candidaturas (incluindo 2º turno)
e substituição transacional por ano/UF para garantir idempotência e ausência de dados obsoletos.
"""

from pathlib import Path
import re
import duckdb

from bdr.download import baixar
from bdr.extracao import extrair_por_uf
from bdr.trajetoria.config import CDN_TSE
from .esquema import TABELAS_Q9, criar_views_q9
from .q9_classificacao import classificar_categoria, id_categoria


UFS_PADRAO_Q9 = ("CE", "MA", "MS", "RJ", "RN", "RS")
ANOS_PADRAO_Q9 = (2018, 2020, 2022, 2024)

ALIASES_DESPESAS = {
    "ano": ["AA_ELEICAO", "ANO_ELEICAO", "ANO"],
    "turno": ["ST_TURNO", "NR_TURNO", "NUM_TURNO"],
    "tipo_prestacao_contas": ["TP_PRESTACAO_CONTAS", "TIPO_PRESTACAO_CONTAS", "DS_TP_PRESTACAO_CONTAS"],
    "dt_prestacao_contas": ["DT_PRESTACAO_CONTAS", "DATA_PRESTACAO_CONTAS"],
    "cd_eleicao": ["CD_ELEICAO", "CODIGO_ELEICAO"],
    "uf": ["SG_UF", "SIGLA_UF"],
    "sq_candidato": ["SQ_CANDIDATO", "SEQUENCIAL_CANDIDATO"],
    "sq_despesa": ["SQ_DESPESA", "SEQUENCIAL_DESPESA", "ID_DESPESA"],
    "dt_despesa": ["DT_DESPESA", "DATA_DESPESA"],
    "origem_despesa": ["DS_ORIGEM_DESPESA", "DESCRICAO_ORIGEM_DESPESA", "DS_TIPO_DESPESA"],
    "descricao_despesa": ["DS_DESPESA", "DESCRICAO_DESPESA"],
    "valor_contratado": ["VR_DESPESA_CONTRATADA", "VALOR_DESPESA_CONTRATADA"],
    "cd_cargo": ["CD_CARGO", "CODIGO_CARGO"],
    "ds_cargo": ["DS_CARGO", "DESCRICAO_CARGO"],
    "nr_documento": ["NR_DOCUMENTO", "NUMERO_DOCUMENTO"],
}

OBRIGATORIOS_DESPESAS = {"ano", "uf", "sq_candidato", "valor_contratado", "origem_despesa"}


def _lit(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ident(valor):
    return '"' + str(valor).replace('"', '""') + '"'


def obter_url_zip_despesas(ano: int) -> list[str]:
    """Retorna lista de URLs oficiais candidatas para o ano de prestação de contas."""
    return [
        f"{CDN_TSE}/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip",
        f"{CDN_TSE}/despesas_contratadas_candidatos/despesas_contratadas_candidatos_{ano}.zip",
    ]


def baixar_despesas_ano(ano: int, pasta_zips: Path) -> Path:
    """Baixa o ZIP de despesas do ano, com fallback de URL e cache."""
    pasta_zips.mkdir(parents=True, exist_ok=True)
    destino_primario = pasta_zips / f"prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
    if destino_primario.exists() and destino_primario.stat().st_size > 0:
        return destino_primario

    urls = obter_url_zip_despesas(ano)
    ultimo_erro = None
    for url in urls:
        nome_arquivo = url.split("/")[-1]
        destino = pasta_zips / nome_arquivo
        if destino.exists() and destino.stat().st_size > 0:
            return destino
        try:
            print(f"Tentando baixar despesas de {ano} via {url}...", flush=True)
            res = baixar(url, destino)
            if res in ("cache", "baixado") and destino.exists() and destino.stat().st_size > 0:
                return destino
        except Exception as exc:
            ultimo_erro = exc
            print(f"Falha ao tentar {url}: {exc}", flush=True)
            continue
    raise FileNotFoundError(f"Não foi possível baixar arquivos oficiais de despesas para o ano {ano}: {ultimo_erro}")


def extrair_despesas_uf(zip_path: Path, raiz_raw: Path, ano: int, ufs: list[str]) -> list[Path]:
    """Extrai os CSVs de despesas contratadas para as UFs solicitadas."""
    partes = {
        "despesas_contratadas_candidatos": "despesas_contratadas_candidatos_{ano}_{uf}"
    }
    arquivos, nomes_zip = extrair_por_uf(zip_path, raiz_raw, ano, partes, ufs)
    ufs_encontradas = {
        re.search(r"_(?:[0-9]{4}_)?([A-Z]{2})\.(?:csv|txt)$", a.name, re.IGNORECASE).group(1).upper()
        for a in arquivos if re.search(r"_(?:[0-9]{4}_)?([A-Z]{2})\.(?:csv|txt)$", a.name, re.IGNORECASE)
    }
    faltando = [u for u in ufs if u not in ufs_encontradas]
    if faltando:
        raise FileNotFoundError(
            f"Faltam arquivos de despesas para {ano} nas seguintes UFs: {faltando}. "
            f"Arquivos no ZIP: {[n for n in nomes_zip if 'despesa' in n.lower()][:10]}"
        )
    return arquivos


def criar_tabelas_q9(con):
    """Garante que as tabelas de Q9 existam no banco."""
    for nome, definicao in TABELAS_Q9.items():
        con.execute(f'CREATE TABLE IF NOT EXISTS "{nome}" ({definicao})')
    criar_views_q9(con)


def carregar_arquivo_despesas(con, caminho: Path, ano_escopo: int):
    """Carrega um CSV de despesas em tabela de staging."""
    with open(caminho, encoding="utf-8") as f:
        primeira_linha = f.readline().rstrip("\r\n")
    cabecalho = [c.strip().strip('"') for c in primeira_linha.split(";")]
    por_maiuscula = {c.upper(): c for c in cabecalho}

    # Verifica se a tabela stg_q9_despesas_brutas existe e quais colunas ela possui
    cols_existentes = {
        row[1].lower() for row in con.execute("PRAGMA table_info('stg_q9_despesas_brutas')").fetchall()
    }
    if not cols_existentes:
        con.execute("DROP SEQUENCE IF EXISTS seq_staging_q9")
        con.execute("CREATE TEMP SEQUENCE seq_staging_q9 START 1")
        cols_stg = ", ".join(f"{campo} VARCHAR" for campo in ALIASES_DESPESAS)
        con.execute(f"""
            CREATE TEMP TABLE stg_q9_despesas_brutas (
                id_staging BIGINT DEFAULT nextval('seq_staging_q9'),
                {cols_stg},
                arquivo_origem VARCHAR
            )
        """)
        cols_existentes = {
            row[1].lower() for row in con.execute("PRAGMA table_info('stg_q9_despesas_brutas')").fetchall()
        }

    campos_alvo = [campo for campo in ALIASES_DESPESAS.keys() if campo.lower() in cols_existentes]
    selecoes = []
    faltando = []
    for campo in campos_alvo:
        aliases = ALIASES_DESPESAS[campo]
        achado = next((por_maiuscula[a] for a in aliases if a in por_maiuscula), None)
        if achado:
            selecoes.append(f"nullif(trim({_ident(achado)}), '') AS {campo}")
        elif campo == "ano":
            selecoes.append(f"'{ano_escopo}' AS ano")
        else:
            selecoes.append(f"NULL::VARCHAR AS {campo}")
            if campo in OBRIGATORIOS_DESPESAS:
                faltando.append(campo)

    if faltando:
        raise ValueError(
            f"Arquivo {caminho.name} não possui os campos obrigatórios: {faltando}. "
            f"Colunas presentes: {cabecalho[:15]}"
        )

    cols_insert = list(campos_alvo)
    if "arquivo_origem" in cols_existentes:
        cols_insert.append("arquivo_origem")
        selecoes.append(f"{_lit(caminho.name)} AS arquivo_origem")

    con.execute(f"""
        INSERT INTO stg_q9_despesas_brutas (
            {', '.join(cols_insert)}
        )
        SELECT
            {', '.join(selecoes)}
        FROM read_csv({_lit(caminho.as_posix())}, delim=';', quote='\"', escape='\"',
                      header=true, all_varchar=true)
    """)


def processar_q9(ufs=UFS_PADRAO_Q9, anos=ANOS_PADRAO_Q9, banco="dados_bdr/saida/pipeline_bdr_der_completo.duckdb",
                 trabalho="dados_bdr/trabalho_der/q9_brutos", manter_zips=True):
    """Carga completa, idempotente e transacional dos dados da Questão 9 no banco DER."""
    banco = Path(banco)
    if not banco.is_file():
        raise FileNotFoundError(
            f"Banco DER não encontrado em: {banco}. Execute primeiro a pipeline DER ou forneça o arquivo existente."
        )

    trabalho = Path(trabalho)
    pasta_zips = trabalho / "zips"
    pasta_raw = trabalho / "raw"
    trabalho.mkdir(parents=True, exist_ok=True)

    ufs_norm = sorted({u.strip().upper() for u in ufs})
    anos_norm = sorted(set(anos))

    con = duckdb.connect(str(banco))
    try:
        criar_tabelas_q9(con)

        # Prepara tabelas de staging com identificador sequencial único por linha
        con.execute("DROP TABLE IF EXISTS stg_q9_despesas_brutas")
        con.execute("DROP SEQUENCE IF EXISTS seq_staging_q9")
        con.execute("CREATE TEMP SEQUENCE seq_staging_q9 START 1")
        cols_stg = ", ".join(f"{campo} VARCHAR" for campo in ALIASES_DESPESAS)
        con.execute(f"""
            CREATE TEMP TABLE stg_q9_despesas_brutas (
                id_staging BIGINT DEFAULT nextval('seq_staging_q9'),
                {cols_stg},
                arquivo_origem VARCHAR
            )
        """)

        print(f"Q9: Iniciando extração e carga para anos={anos_norm}, ufs={ufs_norm}...")
        for ano in anos_norm:
            zip_ano = baixar_despesas_ano(ano, pasta_zips)
            arquivos_uf = extrair_despesas_uf(zip_ano, pasta_raw, ano, ufs_norm)
            for arq in arquivos_uf:
                print(f"  Q9 lendo {arq.name}...", flush=True)
                carregar_arquivo_despesas(con, arq, ano)
                arq.unlink(missing_ok=True)
            if not manter_zips:
                zip_ano.unlink(missing_ok=True)

        total_linhas_brutas = con.execute("SELECT count(*) FROM stg_q9_despesas_brutas").fetchone()[0]
        print(f"Q9: Total de registros brutos em staging: {total_linhas_brutas:,}")
        if total_linhas_brutas == 0:
            raise ValueError("Nenhum registro de despesa foi carregado para o escopo informado.")

        # 1. Normalização de tipos e campos
        con.execute("""
            CREATE TEMP TABLE stg_q9_normalizadas AS
            SELECT
                id_staging,
                try_cast(ano AS INTEGER) AS ano,
                upper(trim(uf)) AS uf,
                nullif(trim(cd_eleicao), '') AS cd_eleicao,
                trim(sq_candidato) AS sq_candidato,
                nullif(trim(sq_despesa), '') AS sq_despesa,
                try_cast(turno AS SMALLINT) AS turno,
                coalesce(
                    try_strptime(dt_despesa, '%d/%m/%Y')::DATE,
                    try_strptime(dt_despesa, '%Y-%m-%d')::DATE,
                    try_cast(dt_despesa AS DATE)
                ) AS data_despesa,
                nullif(trim(origem_despesa), '') AS origem_despesa,
                nullif(trim(descricao_despesa), '') AS descricao_despesa,
                try_cast(replace(replace(valor_contratado, '.', ''), ',', '.') AS DECIMAL(18,2)) AS valor_contratado,
                nullif(trim(tipo_prestacao_contas), '') AS tipo_prestacao_contas,
                coalesce(
                    try_strptime(dt_prestacao_contas, '%d/%m/%Y')::DATE,
                    try_strptime(dt_prestacao_contas, '%Y-%m-%d')::DATE,
                    try_cast(dt_prestacao_contas AS DATE)
                ) AS dt_prestacao_contas,
                nullif(trim(cd_cargo), '') AS cd_cargo,
                nullif(trim(nr_documento), '') AS nr_documento,
                arquivo_origem
            FROM stg_q9_despesas_brutas
            WHERE ano IS NOT NULL AND sq_candidato IS NOT NULL
        """)

        # 2. Identificação de conflitos não resolvíveis na prestação de contas
        con.execute("""
            CREATE TEMP TABLE conflitos_despesa AS
            SELECT
                ano, cd_eleicao, uf, sq_candidato, sq_despesa
            FROM stg_q9_normalizadas
            WHERE sq_despesa IS NOT NULL
            GROUP BY ano, cd_eleicao, uf, sq_candidato, sq_despesa
            HAVING count(DISTINCT valor_contratado) > 1
               AND count(DISTINCT CASE
                   WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%RETIFICADORA%' THEN 1
                   WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%FINAL%' THEN 2
                   WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%PARCIAL%' THEN 3
                   ELSE 4
               END) = 1
        """)

        # 3. Deduplicação de Despesas
        # - Chave de identificação real:
        #   * Quando sq_despesa existe: identificado por (ano, cd_eleicao, uf, sq_candidato, sq_despesa).
        #   * Quando sq_despesa é ausente: chave composta por atributos do lançamento (nr_documento, data, valor, origem, descricao, turno).
        # - Prestações repetidas (ex: Parcial vs Final) são consolidadas priorizando:
        #   Retificadora (1) > Final (2) > Parcial (3) > Outros (4) e data de prestação mais recente.
        # - Despesas legítimas que compartilham atributos parciais mas possuem sq_despesa ou documentos diferentes NÃO são descartadas.
        con.execute("""
            CREATE TEMP TABLE stg_q9_pre_dedup AS
            SELECT
                *,
                CASE
                    WHEN sq_despesa IS NOT NULL THEN 'SQ|' || sq_despesa
                    ELSE 'FALLBACK|' || coalesce(nr_documento, '') || '|' ||
                         coalesce(cast(data_despesa AS VARCHAR), '') || '|' ||
                         coalesce(cast(valor_contratado AS VARCHAR), '') || '|' ||
                         coalesce(origem_despesa, '') || '|' ||
                         coalesce(descricao_despesa, '') || '|' ||
                         coalesce(cast(turno AS VARCHAR), '')
                END AS chave_despesa,
                row_number() OVER (
                    PARTITION BY
                        ano, cd_eleicao, uf, sq_candidato, tipo_prestacao_contas,
                        CASE
                            WHEN sq_despesa IS NOT NULL THEN 'SQ|' || sq_despesa
                            ELSE 'FALLBACK|' || coalesce(nr_documento, '') || '|' ||
                                 coalesce(cast(data_despesa AS VARCHAR), '') || '|' ||
                                 coalesce(cast(valor_contratado AS VARCHAR), '') || '|' ||
                                 coalesce(origem_despesa, '') || '|' ||
                                 coalesce(descricao_despesa, '') || '|' ||
                                 coalesce(cast(turno AS VARCHAR), '')
                        END
                    ORDER BY id_staging
                ) AS ocorrencia_no_tipo
            FROM stg_q9_normalizadas;

            CREATE TEMP TABLE stg_q9_deduplicadas AS
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY
                            ano,
                            cd_eleicao,
                            uf,
                            sq_candidato,
                            chave_despesa,
                            ocorrencia_no_tipo
                        ORDER BY
                            CASE
                                WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%RETIFICADORA%' THEN 1
                                WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%FINAL%' THEN 2
                                WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%PARCIAL%' THEN 3
                                ELSE 4
                            END,
                            dt_prestacao_contas DESC NULLS LAST,
                            id_staging DESC
                    ) AS rn
                FROM stg_q9_pre_dedup
            )
            WHERE rn = 1
        """)

        total_dedup = con.execute("SELECT count(*) FROM stg_q9_deduplicadas").fetchone()[0]
        print(f"Q9: Registros após deduplicação: {total_dedup:,}")

        # 4. Lookup de Candidaturas com todos os identificadores oficiais
        con.execute("""
            CREATE TEMP TABLE cand_lookup AS
            SELECT
                c.id_candidatura,
                trim(c.sequencial) AS sq_candidato,
                upper(trim(c.uf)) AS uf,
                c.numero_urna,
                e.ano,
                e.turno,
                max(upper(trim(coalesce(cg.nome, e.cargo, '')))) AS cargo
            FROM "Candidatura" c
            JOIN "Eleicao" e ON c.id_eleicao = e.id_eleicao
            LEFT JOIN "Cargo" cg ON cg.id_candidatura = c.id_candidatura
            GROUP BY
                c.id_candidatura,
                c.sequencial,
                c.uf,
                c.numero_urna,
                e.ano,
                e.turno
        """)

        # 5. Correspondência rigorosa com Candidatura
        # - Candidato disputando 1 turno: vinculado univocamente se turno compatível.
        # - Candidato disputando 2 turnos: desambiguado pelo turno da despesa.
        # - Sem turno em candidatura de múltiplos turnos: rejeitado com CORRESPONDENCIA_AMBIGUA.
        # - Turno divergente do cadastro: rejeitado com TURNO_INCOMPATIVEL.
        # - Não cadastrado ou em outra UF: rejeitado com motivo específico.
        con.execute("""
            CREATE TEMP TABLE matches_cand AS
            SELECT
                d.id_staging,
                cl.id_candidatura,
                cl.turno AS cand_turno,
                count(*) OVER (PARTITION BY d.id_staging) AS total_matches_uf
            FROM stg_q9_deduplicadas d
            JOIN cand_lookup cl
              ON cl.ano = d.ano
             AND cl.sq_candidato = d.sq_candidato
             AND cl.uf = d.uf;

            CREATE TEMP TABLE matches_validos AS
            SELECT
                m.id_staging,
                m.id_candidatura
            FROM matches_cand m
            JOIN stg_q9_deduplicadas d ON d.id_staging = m.id_staging
            WHERE (d.turno IS NULL AND m.total_matches_uf = 1)
               OR (d.turno IS NOT NULL AND m.cand_turno = d.turno)
            QUALIFY count(*) OVER (PARTITION BY m.id_staging) = 1;

            CREATE TEMP TABLE stg_q9_correspondencia AS
            SELECT
                d.*,
                CASE WHEN conf.sq_despesa IS NOT NULL THEN NULL ELSE mv.id_candidatura END AS id_candidatura,
                CASE
                    WHEN conf.sq_despesa IS NOT NULL THEN 'CONFLITO_LANCAMENTO_DESPESA'
                    WHEN mv.id_candidatura IS NOT NULL THEN 'VINCULADO'
                    WHEN NOT EXISTS (SELECT 1 FROM cand_lookup cl WHERE cl.ano = d.ano AND cl.sq_candidato = d.sq_candidato)
                        THEN 'CANDIDATO_NAO_ENCONTRADO'
                    WHEN NOT EXISTS (SELECT 1 FROM cand_lookup cl WHERE cl.ano = d.ano AND cl.sq_candidato = d.sq_candidato AND cl.uf = d.uf)
                        THEN 'CANDIDATO_UF_DIVERGENTE'
                    WHEN d.turno IS NULL AND (SELECT count(*) FROM matches_cand mc WHERE mc.id_staging = d.id_staging) > 1
                        THEN 'CORRESPONDENCIA_AMBIGUA'
                    WHEN d.turno IS NOT NULL AND NOT EXISTS (SELECT 1 FROM matches_cand mc WHERE mc.id_staging = d.id_staging AND mc.cand_turno = d.turno)
                        THEN 'TURNO_INCOMPATIVEL'
                    ELSE 'CORRESPONDENCIA_AMBIGUA'
                END AS motivo_status
            FROM stg_q9_deduplicadas d
            LEFT JOIN matches_validos mv ON mv.id_staging = d.id_staging
            LEFT JOIN conflitos_despesa conf
                   ON conf.ano = d.ano
                  AND coalesce(conf.cd_eleicao, '') = coalesce(d.cd_eleicao, '')
                  AND conf.uf = d.uf
                  AND conf.sq_candidato = d.sq_candidato
                  AND conf.sq_despesa = d.sq_despesa;
        """)

        # 6. Ordenação determinística para geração de IDs reprodutíveis
        con.execute("""
            CREATE TEMP TABLE stg_q9_ordenada AS
            SELECT
                *,
                row_number() OVER (
                    PARTITION BY
                        ano, coalesce(cd_eleicao, ''), uf, sq_candidato,
                        coalesce(sq_despesa, ''),
                        coalesce(nr_documento, ''),
                        coalesce(cast(data_despesa AS VARCHAR), ''),
                        coalesce(cast(valor_contratado AS VARCHAR), ''),
                        coalesce(origem_despesa, ''),
                        coalesce(descricao_despesa, ''),
                        coalesce(cast(turno AS VARCHAR), '')
                    ORDER BY id_staging
                ) AS ordem_ocorrencia
            FROM stg_q9_correspondencia
        """)

        # 7. Transação atômica: substituição por (ano, uf) eliminando registros obsoletos
        con.execute("BEGIN TRANSACTION")
        try:
            # Popula Categoria_Despesa
            categorias_brutas = con.execute("SELECT DISTINCT origem_despesa FROM stg_q9_ordenada").fetchall()
            for (origem,) in categorias_brutas:
                cat_id, grupo, eh_pub = classificar_categoria(origem)
                origem_val = origem if origem else "NÃO INFORMADO"
                con.execute("""
                    INSERT INTO "Categoria_Despesa" (id_categoria_despesa, origem_despesa, grupo_publicidade, eh_publicidade)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT (id_categoria_despesa) DO NOTHING
                """, [cat_id, origem_val, grupo, eh_pub])

            # Remove registros existentes para os anos e UFs em processamento
            con.execute("""
                DELETE FROM "Despesa_Campanha"
                WHERE (ano, uf) IN (SELECT DISTINCT ano, uf FROM stg_q9_ordenada);

                DELETE FROM "Despesa_Rejeitada"
                WHERE (ano, uf) IN (SELECT DISTINCT ano, uf FROM stg_q9_ordenada);
            """)

            # Insere Despesa_Campanha com id determinístico
            con.execute("""
                INSERT INTO "Despesa_Campanha" (
                    id_despesa, id_candidatura, id_categoria_despesa, ano, uf, cd_eleicao,
                    sq_candidato, sequencial_despesa_tse, turno, data_despesa, descricao_despesa,
                    valor_contratado, tipo_prestacao_contas
                )
                SELECT
                    md5('DESPESA|' || cast(d.ano AS VARCHAR) || '|' || coalesce(d.cd_eleicao, '') || '|' ||
                        d.uf || '|' || d.sq_candidato || '|' ||
                        coalesce(d.sq_despesa,
                            'FALLBACK|' || coalesce(d.nr_documento, '') || '|' ||
                            coalesce(cast(d.data_despesa AS VARCHAR), '') || '|' ||
                            coalesce(cast(d.valor_contratado AS VARCHAR), '') || '|' ||
                            coalesce(d.origem_despesa, '') || '|' ||
                            coalesce(d.descricao_despesa, '') || '|' ||
                            coalesce(cast(d.turno AS VARCHAR), '') || '|' ||
                            cast(d.ordem_ocorrencia AS VARCHAR)
                        )
                    ) AS id_despesa,
                    d.id_candidatura,
                    cat.id_categoria_despesa,
                    d.ano,
                    d.uf,
                    d.cd_eleicao,
                    d.sq_candidato,
                    d.sq_despesa AS sequencial_despesa_tse,
                    d.turno,
                    d.data_despesa,
                    d.descricao_despesa,
                    d.valor_contratado,
                    d.tipo_prestacao_contas
                FROM stg_q9_ordenada d
                JOIN "Categoria_Despesa" cat ON cat.origem_despesa = coalesce(d.origem_despesa, 'NÃO INFORMADO')
                WHERE d.motivo_status = 'VINCULADO'
            """)

            # Insere Despesa_Rejeitada com id determinístico
            con.execute("""
                INSERT INTO "Despesa_Rejeitada" (
                    id_rejeicao, motivo_rejeicao, ano, uf, cd_eleicao, sq_candidato,
                    sequencial_despesa_tse, turno, data_despesa, origem_despesa, descricao_despesa,
                    valor_contratado
                )
                SELECT
                    md5('REJEICAO|' || cast(ano AS VARCHAR) || '|' || coalesce(cd_eleicao, '') || '|' ||
                        uf || '|' || sq_candidato || '|' ||
                        coalesce(sq_despesa, '') || '|' || coalesce(cast(valor_contratado AS VARCHAR), '') || '|' ||
                        coalesce(cast(data_despesa AS VARCHAR), '') || '|' || cast(ordem_ocorrencia AS VARCHAR)
                    ) AS id_rejeicao,
                    motivo_status AS motivo_rejeicao,
                    ano, uf, cd_eleicao, sq_candidato, sq_despesa, turno,
                    data_despesa, origem_despesa, descricao_despesa, valor_contratado
                FROM stg_q9_ordenada
                WHERE motivo_status != 'VINCULADO'
            """)

            # Atualiza views da Q9
            criar_views_q9(con)

            # Atualiza Candidatura.publicidade_propaganda local para compatibilidade com rotinas legadas
            con.execute("""
                UPDATE "Candidatura" c
                SET publicidade_propaganda = sub.total_pub
                FROM (
                    SELECT
                        d.id_candidatura,
                        sum(d.valor_contratado)::DOUBLE AS total_pub
                    FROM "Despesa_Campanha" d
                    JOIN "Categoria_Despesa" cat ON d.id_categoria_despesa = cat.id_categoria_despesa
                    WHERE cat.eh_publicidade = true
                    GROUP BY d.id_candidatura
                ) sub
                WHERE c.id_candidatura = sub.id_candidatura
            """)

            # Validação rigorosa antes do commit
            relatorio = validar_q9(con)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

        print("=== RELATÓRIO DE CARGA Q9 ===")
        for k, v in relatorio.items():
            print(f"  {k}: {v}")

    finally:
        con.close()


def validar_q9(con) -> dict:
    """Valida integridade e métricas de Q9 no banco informado."""
    total_despesas = con.execute('SELECT count(*) FROM "Despesa_Campanha"').fetchone()[0]
    total_pub = con.execute("""
        SELECT count(*), coalesce(sum(valor_contratado), 0)
        FROM "Despesa_Campanha" d
        JOIN "Categoria_Despesa" c ON d.id_categoria_despesa = c.id_categoria_despesa
        WHERE c.eh_publicidade = true
    """).fetchone()
    total_nao_pub = con.execute("""
        SELECT count(*), coalesce(sum(valor_contratado), 0)
        FROM "Despesa_Campanha" d
        JOIN "Categoria_Despesa" c ON d.id_categoria_despesa = c.id_categoria_despesa
        WHERE c.eh_publicidade = false
    """).fetchone()
    total_rejeitadas = con.execute('SELECT count(*) FROM "Despesa_Rejeitada"').fetchone()[0]
    orfaos_cand = con.execute("""
        SELECT count(*) FROM "Despesa_Campanha" d
        LEFT JOIN "Candidatura" c ON d.id_candidatura = c.id_candidatura
        WHERE c.id_candidatura IS NULL
    """).fetchone()[0]
    orfaos_cat = con.execute("""
        SELECT count(*) FROM "Despesa_Campanha" d
        LEFT JOIN "Categoria_Despesa" c ON d.id_categoria_despesa = c.id_categoria_despesa
        WHERE c.id_categoria_despesa IS NULL
    """).fetchone()[0]

    if orfaos_cand > 0 or orfaos_cat > 0:
        raise ValueError(f"Violação de integridade referencial: orfaos_cand={orfaos_cand}, orfaos_cat={orfaos_cat}")

    return {
        "despesas_vinculadas": total_despesas,
        "despesas_publicidade_qtd": total_pub[0],
        "despesas_publicidade_valor": float(total_pub[1]),
        "despesas_operacionais_qtd": total_nao_pub[0],
        "despesas_operacionais_valor": float(total_nao_pub[1]),
        "despesas_rejeitadas": total_rejeitadas,
        "orfaos_candidatura": orfaos_cand,
        "orfaos_categoria": orfaos_cat,
    }
