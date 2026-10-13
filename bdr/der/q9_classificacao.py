"""Classificação analítica e de-para explícito de despesas de publicidade eleitoral (Q9)."""

import hashlib
import unicodedata

# Grupos analíticos definidos para a Questão 9
GRUPOS_PUBLICIDADE = {
    "DIGITAL",
    "IMPRESSOS",
    "AUDIOVISUAL",
    "SONORA",
    "EVENTOS",
    "OUTROS",
    "NAO_PUBLICIDADE",
    "NAO_CLASSIFICADO",
}

# De-para explícito, auditável e versionável de categorias originais do TSE
# Mapeia: Categoria original TSE -> (grupo_analítico, eh_publicidade)
CATEGORIAS_ORIGINAIS_TSE = {
    # IMPRESSOS
    "Publicidade por materiais impressos": ("IMPRESSOS", True),
    "Publicidade por adesivos": ("IMPRESSOS", True),
    "Publicidade por jornais e revistas": ("IMPRESSOS", True),

    # DIGITAL
    "Despesa com Impulsionamento de Conteúdos": ("DIGITAL", True),
    "Impulsionamento de conteúdos": ("DIGITAL", True),
    "Criação e inclusão de páginas na internet": ("DIGITAL", True),

    # AUDIOVISUAL
    "Produção de programas de rádio, televisão ou vídeo": ("AUDIOVISUAL", True),

    # SONORA
    "Produção de jingles, vinhetas e slogans": ("SONORA", True),
    "Publicidade por carros de som": ("SONORA", True),

    # EVENTOS
    "Eventos de promoção da candidatura": ("EVENTOS", True),
    "Eventos de promoção de candidatura": ("EVENTOS", True),
    "Comícios": ("EVENTOS", True),

    # OUTROS (Publicidade)
    "Publicidade por outros meios": ("OUTROS", True),
    "Publicidade e propaganda": ("OUTROS", True),

    # NÃO PUBLICIDADE (Operacionais, administrativas, jurídicas, etc.)
    "Combustíveis e lubrificantes": ("NAO_PUBLICIDADE", False),
    "Despesas com pessoal": ("NAO_PUBLICIDADE", False),
    "Atividades de militância e mobilização de rua": ("NAO_PUBLICIDADE", False),
    "Serviços prestados por terceiros": ("NAO_PUBLICIDADE", False),
    "Serviços próprios prestados por terceiros": ("NAO_PUBLICIDADE", False),
    "Serviços advocatícios": ("NAO_PUBLICIDADE", False),
    "Serviços contábeis": ("NAO_PUBLICIDADE", False),
    "Encargos financeiros, taxas bancárias e/ou op. cartão de crédito": ("NAO_PUBLICIDADE", False),
    "Cessão ou locação de veículos": ("NAO_PUBLICIDADE", False),
    "Locação/cessão de bens móveis (exceto veículos)": ("NAO_PUBLICIDADE", False),
    "Locação/cessão de bens imóveis": ("NAO_PUBLICIDADE", False),
    "Alimentação": ("NAO_PUBLICIDADE", False),
    "Materiais de expediente": ("NAO_PUBLICIDADE", False),
    "Doações financeiras a outros candidatos/partidos": ("NAO_PUBLICIDADE", False),
    "Pesquisas ou testes eleitorais": ("NAO_PUBLICIDADE", False),
    "Taxa de Administração de Financiamento Coletivo": ("NAO_PUBLICIDADE", False),
    "Diversas a especificar": ("NAO_PUBLICIDADE", False),
    "Reembolsos de despesas": ("NAO_PUBLICIDADE", False),
    "Passagens e despesas com locomoção": ("NAO_PUBLICIDADE", False),
    "Segurança": ("NAO_PUBLICIDADE", False),
    "Hospedagem": ("NAO_PUBLICIDADE", False),
}


def _strip_accents(texto: str) -> str:
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).upper().strip()


def id_categoria(origem: str) -> str:
    norm = _strip_accents(origem or "NAO_INFORMADO")
    return hashlib.md5(f"CATEGORIA|{norm}".encode("utf-8")).hexdigest()


def classificar_categoria(origem: str | None) -> tuple[str, str, bool]:
    """Retorna (id_categoria, grupo_publicidade, eh_publicidade)."""
    if not origem or not origem.strip():
        cat = "NÃO INFORMADO"
        return id_categoria(cat), "NAO_CLASSIFICADO", False

    origem_limpa = origem.strip()
    if origem_limpa in CATEGORIAS_ORIGINAIS_TSE:
        grupo, eh_pub = CATEGORIAS_ORIGINAIS_TSE[origem_limpa]
        return id_categoria(origem_limpa), grupo, eh_pub

    # Tentativa insensível a acentos / caixa alta
    norm = _strip_accents(origem_limpa)
    for k, (grupo, eh_pub) in CATEGORIAS_ORIGINAIS_TSE.items():
        if _strip_accents(k) == norm:
            return id_categoria(origem_limpa), grupo, eh_pub

    # Fallback heurístico documentado para variações textuais
    if any(p in norm for p in ["IMPRESSO", "ADESIVO", "FOLHETO", "PANFLETO", "SANTINHO", "JORNAIS E REVISTAS"]):
        return id_categoria(origem_limpa), "IMPRESSOS", True
    if any(p in norm for p in ["IMPULSIONAMENTO", "PAGINA", "INTERNET", "WEBSITE", "DIGITAL"]):
        return id_categoria(origem_limpa), "DIGITAL", True
    if any(p in norm for p in ["RADIO", "TELEVISAO", "VIDEO", "AUDIOVISUAL"]):
        return id_categoria(origem_limpa), "AUDIOVISUAL", True
    if any(p in norm for p in ["JINGLE", "VINHETA", "SLOGAN", "CARRO DE SOM", "CARROS DE SOM"]):
        return id_categoria(origem_limpa), "SONORA", True
    if any(p in norm for p in ["COMICIO", "COMICIOS", "EVENTO DE PROMOCAO", "EVENTOS DE PROMOCAO"]):
        return id_categoria(origem_limpa), "EVENTOS", True
    if "PUBLICIDADE" in norm or "PROPAGANDA" in norm:
        return id_categoria(origem_limpa), "OUTROS", True

    return id_categoria(origem_limpa), "NAO_CLASSIFICADO", False
