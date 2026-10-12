"""Leitura dos CSVs para tabelas de staging (stg_*), com nomes de coluna padronizados.

Os nomes de coluna do TSE mudam entre anos. Cada campo tem uma lista de nomes
alternativos; o primeiro encontrado no cabeçalho é usado. Campos opcionais ausentes
viram NULL e geram aviso; campos obrigatórios ausentes interrompem a carga.
Para incluir um nome novo, basta acrescentá-lo na lista do campo.
"""

import re

# campo padronizado -> nomes possíveis no arquivo do TSE (em maiúsculas)
_ELEICAO = {
    "ano": ["ANO_ELEICAO"],
    "cd_eleicao": ["CD_ELEICAO", "CODIGO_ELEICAO"],
    "ds_eleicao": ["DS_ELEICAO", "DESCRICAO_ELEICAO"],
    "tipo_eleicao": ["NM_TIPO_ELEICAO", "DS_TIPO_ELEICAO"],
    "turno": ["NR_TURNO", "NUM_TURNO"],
    "dt_eleicao": ["DT_ELEICAO", "DATA_ELEICAO"],
    "uf": ["SG_UF", "SIGLA_UF"],
    "cd_cargo": ["CD_CARGO", "CODIGO_CARGO"],
    "cargo": ["DS_CARGO", "DESCRICAO_CARGO"],
}
_MUNZONA = {
    "cd_municipio": ["CD_MUNICIPIO", "CODIGO_MUNICIPIO"],
    "nm_municipio": ["NM_MUNICIPIO", "NOME_MUNICIPIO"],
    "nr_zona": ["NR_ZONA", "NUM_ZONA"],
}
_PARTIDO = {
    "numero_partido": ["NR_PARTIDO", "NUMERO_PARTIDO"],
    "sigla_partido": ["SG_PARTIDO", "SIGLA_PARTIDO"],
    "nome_partido": ["NM_PARTIDO", "NOME_PARTIDO"],
}

ALIASES = {
    "boletim_urna": {
        "ano": ["ANO_ELEICAO"],
        "turno": ["NR_TURNO", "NUM_TURNO"],
        "uf": ["SG_UF", "SIGLA_UF"],
        "cd_eleicao": ["CD_ELEICAO", "CODIGO_ELEICAO"],
        "ds_eleicao": ["DS_ELEICAO", "DESCRICAO_ELEICAO"],
        "dt_pleito": ["DT_PLEITO", "DT_BU_RECEBIDO", "DT_EMISSAO_BU"],
        "cd_municipio": ["CD_MUNICIPIO", "CODIGO_MUNICIPIO"],
        "nm_municipio": ["NM_MUNICIPIO", "NOME_MUNICIPIO"],
        "nr_zona": ["NR_ZONA", "NUM_ZONA"],
        "nr_secao": ["NR_SECAO", "NUM_SECAO"],
        "cd_cargo": ["CD_CARGO_PERGUNTA", "CD_CARGO", "CODIGO_CARGO"],
        "cargo": ["DS_CARGO_PERGUNTA", "DS_CARGO", "DESCRICAO_CARGO"],
        "numero_partido": ["NR_PARTIDO", "NUMERO_PARTIDO"],
        "sigla_partido": ["SG_PARTIDO", "SIGLA_PARTIDO"],
        "nome_partido": ["NM_PARTIDO", "NOME_PARTIDO"],
        "aptos": ["QT_APTOS", "QTD_APTOS"],
        "comparecimento": ["QT_COMPARECIMENTO", "QTD_COMPARECIMENTO"],
        "abstencoes": ["QT_ABSTENCOES", "QTD_ABSTENCOES"],
        "cd_tipo_votavel": ["CD_TIPO_VOTAVEL"],
        "ds_tipo_votavel": ["DS_TIPO_VOTAVEL"],
        "nr_votavel": ["NR_VOTAVEL"],
        "nm_votavel": ["NM_VOTAVEL"],
        "votos": ["QT_VOTOS", "QUANTIDADE_VOTOS"],
    },
    "consulta_cand": {
        **_ELEICAO, **_PARTIDO,
        "sg_ue": ["SG_UE", "SIGLA_UE"],
        "sequencial": ["SQ_CANDIDATO", "SEQUENCIAL_CANDIDATO"],
        "numero_urna": ["NR_CANDIDATO", "NUMERO_CANDIDATO"],
        "nome_civil": ["NM_CANDIDATO", "NOME_CANDIDATO"],
        "nome_urna": ["NM_URNA_CANDIDATO", "NOME_URNA_CANDIDATO"],
        "cpf": ["NR_CPF_CANDIDATO", "CPF_CANDIDATO"],
        "titulo_eleitoral": ["NR_TITULO_ELEITORAL_CANDIDATO", "NUM_TITULO_ELEITORAL_CANDIDATO"],
        "situacao_registro": ["DS_SITUACAO_CANDIDATURA", "DES_SITUACAO_CANDIDATURA",
                              "DS_DETALHE_SITUACAO_CAND"],
        "dt_nascimento": ["DT_NASCIMENTO", "DATA_NASCIMENTO"],
        "uf_nascimento": ["SG_UF_NASCIMENTO", "SIGLA_UF_NASCIMENTO"],
        "idade_eleicao": ["NR_IDADE_DATA_POSSE", "IDADE_DATA_ELEICAO"],
        "genero": ["DS_GENERO", "DESCRICAO_SEXO"],
        "escolaridade": ["DS_GRAU_INSTRUCAO", "DESCRICAO_GRAU_INSTRUCAO"],
        "raca": ["DS_COR_RACA", "DESCRICAO_COR_RACA"],
        "ocupacao": ["DS_OCUPACAO", "DESCRICAO_OCUPACAO"],
        "resultado": ["DS_SIT_TOT_TURNO", "DESC_SIT_TOT_TURNO"],
        "patrimonio": ["VR_BEM_CANDIDATO", "VALOR_BENS"],
    },
    "votacao_partido_munzona": {
        **_ELEICAO, **_MUNZONA, **_PARTIDO,
        "votos_nominais": ["QT_VOTOS_NOMINAIS", "QT_VOTOS_NOMINAIS_VALIDOS"],
        "votos_legenda": ["QT_VOTOS_LEGENDA", "QT_VOTOS_LEGENDA_VALIDOS"],
    },
    "detalhe_votacao_munzona": {
        **_ELEICAO, **_MUNZONA,
        "aptos": ["QT_APTOS", "QTD_APTOS"],
        "comparecimento": ["QT_COMPARECIMENTO", "QTD_COMPARECIMENTO"],
        "abstencoes": ["QT_ABSTENCOES", "QTD_ABSTENCOES"],
        "brancos": ["QT_VOTOS_BRANCOS", "QTD_VOTOS_BRANCOS"],
        "nulos": ["QT_VOTOS_NULOS", "QTD_VOTOS_NULOS"],
    },
}

OBRIGATORIOS = {
    "boletim_urna": {"ano", "turno", "uf", "cd_eleicao", "cd_municipio", "nr_zona", "nr_secao",
                     "cd_cargo", "aptos", "comparecimento", "abstencoes", "votos"},
    "consulta_cand": {"ano", "cd_cargo", "sequencial"},
    "votacao_partido_munzona": {"ano", "turno", "cd_cargo", "numero_partido", "cd_municipio",
                                "votos_nominais", "votos_legenda"},
    "detalhe_votacao_munzona": {"ano", "turno", "cd_cargo", "cd_municipio", "aptos",
                                "comparecimento", "abstencoes"},
}

LAYOUTS_SEM_CABECALHO = {}
PADROES_FALLBACK = {}


class ErroLayout(Exception):
    pass


def _lit(texto):
    return "'" + str(texto).replace("'", "''") + "'"


def _ident(nome):
    return '"' + nome.replace('"', '""') + '"'


def criar_staging(con):
    for arquivo, campos in ALIASES.items():
        colunas = ", ".join(f"{c} VARCHAR" for c in campos)
        con.execute(f"DROP TABLE IF EXISTS stg_{arquivo}")
        con.execute(f"CREATE TABLE stg_{arquivo} ({colunas}, arquivo_origem VARCHAR)")


def carregar_arquivo(con, arquivo, ano, caminho):
    """Insere um CSV em stg_<arquivo>. Devolve (linhas, avisos)."""
    with open(caminho, encoding="utf-8") as f:
        primeira = f.readline().rstrip("\r\n")
    cabecalho = [c.strip().strip('"') for c in primeira.split(";")]
    por_maiuscula = {c.upper(): c for c in cabecalho}
    obrigatorios = OBRIGATORIOS.get(arquivo, set())
    tem_cabecalho = any(a in por_maiuscula
                        for campo in obrigatorios | {"ano"} for a in ALIASES[arquivo].get(campo, []))

    if tem_cabecalho:
        leitura = (f"read_csv({_lit(caminho)}, delim=';', quote='\"', escape='\"', "
                   f"header=true, all_varchar=true)")
    elif (arquivo, ano) in LAYOUTS_SEM_CABECALHO:
        nomes = LAYOUTS_SEM_CABECALHO[(arquivo, ano)]
        por_maiuscula = {n.upper(): n for n in nomes}
        leitura = (f"read_csv({_lit(caminho)}, delim=';', quote='\"', escape='\"', header=false, "
                   f"all_varchar=true, names=[{', '.join(_lit(n) for n in nomes)}])")
    else:
        raise ErroLayout(
            f"{caminho.name}: arquivo sem cabeçalho reconhecível. Se for layout antigo, "
            f"copie a ordem das colunas do leiame.pdf para LAYOUTS_SEM_CABECALHO[('{arquivo}', {ano})] "
            f"em bdr/leitura.py. Primeira linha: {primeira[:120]}")

    selecoes, avisos, faltando, assumidos = [], [], [], []
    for campo, nomes in ALIASES[arquivo].items():
        achado = next((por_maiuscula[n] for n in nomes if n in por_maiuscula), None)
        if not achado and (arquivo, campo) in PADROES_FALLBACK:
            padrao = re.compile(PADROES_FALLBACK[(arquivo, campo)])
            candidatas = [orig for maiusc, orig in por_maiuscula.items() if padrao.search(maiusc)]
            if len(candidatas) == 1:
                achado = candidatas[0]
                assumidos.append(f"{caminho.name}: '{campo}' lido da coluna {achado} "
                                 f"(nome não previsto; confira e, se estiver certo, acrescente em ALIASES)")
        if achado:
            selecoes.append(f"{_ident(achado)} AS {campo}")
        elif campo == "ano":
            selecoes.append(f"'{ano}' AS ano")
        else:
            selecoes.append(f"NULL::VARCHAR AS {campo}")
            (faltando if campo in obrigatorios else avisos).append(campo)
    if faltando:
        raise ErroLayout(f"{caminho.name}: campos obrigatórios não encontrados: {', '.join(faltando)}.\n"
                         f"   Colunas do arquivo: {', '.join(cabecalho)}\n"
                         f"   Acrescente o nome certo em ALIASES (bdr/leitura.py).")

    linhas = con.execute(
        f"INSERT INTO stg_{arquivo} SELECT {', '.join(selecoes)}, {_lit(caminho.name)} FROM {leitura}"
    ).fetchone()[0]
    return linhas, assumidos + [f"{caminho.name}: coluna ausente (fica NULL): {c}" for c in avisos]
