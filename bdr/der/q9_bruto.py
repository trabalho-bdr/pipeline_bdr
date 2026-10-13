"""Carga e integração da Questão 9 (Publicidade Eleitoral) no DER.

Processa despesas eleitorais oficiais de 2018, 2020, 2022 e 2024 para CE, MA, MS, RJ, RN, RS.
"""

from pathlib import Path
import re
import duckdb

from bdr.download import baixar
from bdr.extracao import extrair_por_uf
from bdr.trajetoria.config import CDN_TSE
from .esquema import TABELAS_Q9
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
    # Se algum arquivo não foi encontrado diretamente pelo modelo, verifica nomes no zip
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


def carregar_arquivo_despesas(con, caminho: Path, ano_escopo: int):
    """Carrega um CSV de despesas em tabela de staging."""
    with open(caminho, encoding="utf-8") as f:
        primeira_linha = f.readline().rstrip("\r\n")
    cabecalho = [c.strip().strip('"') for c in primeira_linha.split(";")]
    por_maiuscula = {c.upper(): c for c in cabecalho}

    # Valida presença de colunas obrigatórias
    selecoes = []
    faltando = []
    for campo, aliases in ALIASES_DESPESAS.items():
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

    con.execute(f"""
        INSERT INTO stg_q9_despesas_brutas
        SELECT
            {', '.join(selecoes)},
            {_lit(caminho.name)} AS arquivo_origem
        FROM read_csv({_lit(caminho.as_posix())}, delim=';', quote='\"', escape='\"',
                      header=true, all_varchar=true)
    """)


def processar_q9(ufs=UFS_PADRAO_Q9, anos=ANOS_PADRAO_Q9, banco="dados_bdr/saida/pipeline_bdr_der_completo.duckdb",
                 trabalho="dados_bdr/trabalho_der/q9_brutos", manter_zips=True):
    """Carga completa e idempotente dos dados da Questão 9 no banco DER.

    Integra Categoria_Despesa e Despesa_Campanha relacionando a Candidatura.
    """
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
        # Garante a existência das tabelas Q9 no DER
        criar_tabelas_q9(con)

        # Prepara tabelas de staging
        con.execute("DROP TABLE IF EXISTS stg_q9_despesas_brutas")
        cols_stg = ", ".join(f"{campo} VARCHAR" for campo in ALIASES_DESPESAS)
        con.execute(f"CREATE TEMP TABLE stg_q9_despesas_brutas ({cols_stg}, arquivo_origem VARCHAR)")

        print(f"Q9: Iniciando extração e carga para anos={anos_norm}, ufs={ufs_norm}...")
        for ano in anos_norm:
            zip_ano = baixar_despesas_ano(ano, pasta_zips)
            arquivos_uf = extrair_despesas_uf(zip_ano, pasta_raw, ano, ufs_norm)
            for arq in arquivos_uf:
                print(f"  Q9 lendo {arq.name}...", flush=True)
                carregar_arquivo_despesas(con, arq, ano)
                arq.unlink(missing_ok=True)  # Remove CSV temporário após leitura
            if not manter_zips:
                zip_ano.unlink(missing_ok=True)

        total_linhas_brutas = con.execute("SELECT count(*) FROM stg_q9_despesas_brutas").fetchone()[0]
        print(f"Q9: Total de registros brutos em staging: {total_linhas_brutas:,}")
        if total_linhas_brutas == 0:
            raise ValueError("Nenhum registro de despesa foi carregado para o escopo informado.")

        # Tratamento e normalização dos dados brutos
        con.execute("""
            CREATE TEMP TABLE stg_q9_normalizadas AS
            SELECT
                try_cast(ano AS INTEGER) AS ano,
                upper(trim(uf)) AS uf,
                trim(cd_eleicao) AS cd_eleicao,
                trim(sq_candidato) AS sq_candidato,
                trim(sq_despesa) AS sq_despesa,
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
                arquivo_origem
            FROM stg_q9_despesas_brutas
            WHERE ano IS NOT NULL AND sq_candidato IS NOT NULL
        """)

        # Deduplicação rigorosa: se sq_despesa existe, prioriza prestação Final e data mais recente
        con.execute("""
            CREATE TEMP TABLE stg_q9_deduplicadas AS
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT
                    *,
                    row_number() OVER (
                        PARTITION BY ano, sq_candidato, coalesce(sq_despesa, md5(coalesce(cast(data_despesa AS VARCHAR),'') || '|' || coalesce(cast(valor_contratado AS VARCHAR),'') || '|' || coalesce(descricao_despesa,'')))
                        ORDER BY
                            CASE
                                WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%FINAL%' THEN 1
                                WHEN upper(coalesce(tipo_prestacao_contas, '')) LIKE '%RETIFICADORA%' THEN 2
                                ELSE 3
                            END,
                            dt_prestacao_contas DESC NULLS LAST
                    ) AS rn
                FROM stg_q9_normalizadas
            )
            WHERE rn = 1
        """)

        total_dedup = con.execute("SELECT count(*) FROM stg_q9_deduplicadas").fetchone()[0]
        print(f"Q9: Registros após deduplicação: {total_dedup:,}")

        # Popula tabela Categoria_Despesa com todas as categorias distintas encontradas
        categorias_brutas = con.execute("SELECT DISTINCT origem_despesa FROM stg_q9_deduplicadas").fetchall()
        for (origem,) in categorias_brutas:
            cat_id, grupo, eh_pub = classificar_categoria(origem)
            origem_val = origem if origem else "NÃO INFORMADO"
            con.execute("""
                INSERT INTO "Categoria_Despesa" (id_categoria_despesa, origem_despesa, grupo_publicidade, eh_publicidade)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (id_categoria_despesa) DO NOTHING
            """, [cat_id, origem_val, grupo, eh_pub])

        # Lookup de Candidaturas existentes no DER
        con.execute("""
            CREATE TEMP TABLE cand_lookup AS
            SELECT
                c.id_candidatura,
                c.sequencial AS sq_candidato,
                c.uf,
                e.ano,
                e.turno,
                e.cargo
            FROM "Candidatura" c
            JOIN "Eleicao" e ON c.id_eleicao = e.id_eleicao
        """)

        con.execute("""
            CREATE TEMP TABLE cand_contagem AS
            SELECT ano, sq_candidato, count(*) AS total_cands
            FROM cand_lookup
            GROUP BY ano, sq_candidato
        """)

        # Identificação unívoca ou rejeição (Seção 7)
        # 1. Candidato não encontrado
        # 2. Correspondência unívoca (total_cands = 1)
        # 3. Correspondência com desambiguação por turno (total_cands > 1 e turno confere com exatidão)
        # 4. Ambiguidade não resolvida
        con.execute("""
            CREATE TEMP TABLE stg_q9_correspondencia AS
            WITH unicos AS (
                SELECT
                    d.*,
                    c.id_candidatura,
                    'OK_UNICO' AS status_match
                FROM stg_q9_deduplicadas d
                JOIN cand_contagem cc ON cc.ano = d.ano AND cc.sq_candidato = d.sq_candidato
                JOIN cand_lookup c ON c.ano = d.ano AND c.sq_candidato = d.sq_candidato
                WHERE cc.total_cands = 1
            ),
            multiplos AS (
                SELECT
                    d.*,
                    c.id_candidatura,
                    c.turno AS cand_turno,
                    count(*) OVER (PARTITION BY d.ano, d.sq_candidato, d.sq_despesa, d.data_despesa, d.valor_contratado) AS candidaturas_turno_match
                FROM stg_q9_deduplicadas d
                JOIN cand_contagem cc ON cc.ano = d.ano AND cc.sq_candidato = d.sq_candidato
                JOIN cand_lookup c ON c.ano = d.ano AND c.sq_candidato = d.sq_candidato
                WHERE cc.total_cands > 1
                  AND d.turno IS NOT NULL
                  AND c.turno = d.turno
            ),
            multiplos_resolvidos AS (
                SELECT
                    ano, uf, cd_eleicao, sq_candidato, sq_despesa, turno,
                    data_despesa, origem_despesa, descricao_despesa, valor_contratado,
                    tipo_prestacao_contas, dt_prestacao_contas, arquivo_origem,
                    id_candidatura,
                    'OK_TURNO' AS status_match
                FROM multiplos
                WHERE candidaturas_turno_match = 1
            ),
            sucessos AS (
                SELECT * FROM unicos
                UNION ALL
                SELECT * FROM multiplos_resolvidos
            )
            SELECT
                d.*,
                s.id_candidatura,
                CASE
                    WHEN s.id_candidatura IS NOT NULL THEN 'VINCULADO'
                    WHEN cc.total_cands IS NULL OR cc.total_cands = 0 THEN 'CANDIDATO_NAO_ENCONTRADO'
                    ELSE 'CORRESPONDENCIA_AMBIGUA'
                END AS motivo_status
            FROM stg_q9_deduplicadas d
            LEFT JOIN cand_contagem cc ON cc.ano = d.ano AND cc.sq_candidato = d.sq_candidato
            LEFT JOIN sucessos s ON s.ano = d.ano AND s.sq_candidato = d.sq_candidato
                AND coalesce(s.sq_despesa, '') = coalesce(d.sq_despesa, '')
                AND coalesce(cast(s.data_despesa AS VARCHAR), '') = coalesce(cast(d.data_despesa AS VARCHAR), '')
                AND coalesce(cast(s.valor_contratado AS VARCHAR), '') = coalesce(cast(d.valor_contratado AS VARCHAR), '')
                AND coalesce(s.descricao_despesa, '') = coalesce(d.descricao_despesa, '')
        """)

        # Grava Despesa_Rejeitada
        con.execute("""
            INSERT INTO "Despesa_Rejeitada"
            SELECT
                md5('REJEICAO|' || cast(ano AS VARCHAR) || '|' || sq_candidato || '|' ||
                    coalesce(sq_despesa, '') || '|' || coalesce(cast(valor_contratado AS VARCHAR), '') || '|' ||
                    coalesce(cast(data_despesa AS VARCHAR), '')) AS id_rejeicao,
                motivo_status AS motivo_rejeicao,
                ano, uf, cd_eleicao, sq_candidato, sq_despesa, turno,
                data_despesa, origem_despesa, descricao_despesa, valor_contratado
            FROM stg_q9_correspondencia
            WHERE motivo_status != 'VINCULADO'
            ON CONFLICT (id_rejeicao) DO NOTHING
        """)

        # Prepara chave primária determinística e insere em Despesa_Campanha
        con.execute("""
            INSERT INTO "Despesa_Campanha" (
                id_despesa, id_candidatura, id_categoria_despesa, ano, uf, cd_eleicao,
                sq_candidato, sequencial_despesa_tse, turno, data_despesa, descricao_despesa,
                valor_contratado, tipo_prestacao_contas
            )
            SELECT
                md5('DESPESA|' || cast(d.ano AS VARCHAR) || '|' || d.sq_candidato || '|' ||
                    coalesce(d.sq_despesa, md5(coalesce(cast(d.data_despesa AS VARCHAR),'') || '|' ||
                    coalesce(cast(d.valor_contratado AS VARCHAR),'') || '|' || coalesce(d.descricao_despesa,'')))) AS id_despesa,
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
            FROM stg_q9_correspondencia d
            JOIN "Categoria_Despesa" cat ON cat.origem_despesa = coalesce(d.origem_despesa, 'NÃO INFORMADO')
            WHERE d.motivo_status = 'VINCULADO'
            ON CONFLICT (id_despesa) DO UPDATE SET
                id_candidatura = EXCLUDED.id_candidatura,
                id_categoria_despesa = EXCLUDED.id_categoria_despesa,
                valor_contratado = EXCLUDED.valor_contratado,
                descricao_despesa = EXCLUDED.descricao_despesa,
                tipo_prestacao_contas = EXCLUDED.tipo_prestacao_contas
        """)

        # Atualiza métrica Candidatura.publicidade_propaganda com base nas despesas oficiais de publicidade
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

        # Relatório de auditoria e validação
        relatorio = validar_q9(con)
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
