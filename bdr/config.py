"""Configuração central para a Questão 3 do BDR.

Questão 3:
"Como características socioeconômicas dos municípios se relacionam com a distribuição
dos votos entre partidos e com a taxa de abstenção?"

Escopo temporal: 2018, 2020, 2022 e 2024.
Escopo de membros: cada membro é responsável por exatamente 2 UFs.
Fontes: Boletins de Urna (TSE), Comparecimento e Abstenção / Detalhe da Votação (TSE),
        Indicadores do IBGE (Localidades, Censo 2022, PIB) e IDHM (Atlas Brasil).
"""

ANOS_Q3 = [2018, 2020, 2022, 2024]

# Divisão definitiva para a Questão 3 (cada membro com exatamente 2 UFs):
# Membros 2 e 3 definidos; Membros 1 e 4 com estrutura editável para o grupo.
MEMBROS = {
    1: {"ufs": ["AC", "AL"]},  # Membro 1: configurar UFs definitivas se necessário
    2: {"ufs": ["MA", "SE"]},  # Membro 2: MA, SE
    3: {"ufs": ["RJ", "RN"]},  # Membro 3: RJ, RN
    4: {"ufs": ["PB", "PI"]},  # Membro 4: configurar UFs definitivas se necessário
}

CDN_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"

# BUweb oficial por UF e turno (Portal de Dados Abertos do TSE)
CDN_BOLETINS_TSE = "https://cdn.tse.jus.br/estatistica/sead/eleicoes"
BOLETINS_TSE = {
    (2022, 1): "051020221321",
    (2022, 2): "311020221535",
    (2024, 1): "091020241636",
    (2024, 2): "281020241046",
}

# De-para oficial TSE <-> IBGE de municípios
URL_DE_PARA_TSE = f"{CDN_TSE}/municipio_tse_ibge/municipio_tse_ibge.zip"

# Detalhe da votação / comparecimento e abstenção do TSE
ARQUIVOS_TSE_Q3 = {
    "detalhe_votacao_munzona": {
        "pasta": "detalhe_votacao_munzona",
        "zip": "detalhe_votacao_munzona_{ano}",
        "partes": {"detalhe_votacao_munzona": "detalhe_votacao_munzona_{ano}_{uf}"},
    },
}


def montar_escopo(membro=None, ufs=None, anos=None, incluir_br=False):
    """Define o recorte para a Questão 3.

    Com --membro usa a divisão do grupo (2 UFs por membro, anos 2022 e 2024).
    Sem --membro usa recorte livre (--ufs e --anos).
    Garante que arquivos de outras perguntas NÃO entrem no plano de execução.
    """
    if membro is not None:
        if membro not in MEMBROS:
            raise ValueError(f"Membro inválido: {membro}. Escolha entre {sorted(MEMBROS)}.")
        cfg = MEMBROS[membro]
        siglas = [u.upper() for u in cfg["ufs"]]
        if len(siglas) != 2:
            raise ValueError(f"O membro {membro} deve possuir exatamente 2 UFs (encontrado: {siglas}).")
        anos_base = list(ANOS_Q3)
        if anos:
            anos_base = sorted(set(anos_base) & set(anos))
        rotulo = f"membro{membro}"
    else:
        if not ufs:
            raise ValueError("Informe --membro ou --ufs.")
        siglas = [u.upper() for u in ufs]
        anos_base = sorted(set(anos or ANOS_Q3) & set(ANOS_Q3))
        if not anos_base:
            anos_base = sorted(set(anos or ANOS_Q3))
        rotulo = "recorte_" + "-".join(siglas)

    # 2018/2020 têm votação partidária própria; 2022/2024 usam BUweb.
    anos_partido = [ano for ano in anos_base if ano in (2018, 2020)]
    anos_bu = [ano for ano in anos_base if ano in (2022, 2024)]
    plano = {"detalhe_votacao_munzona": anos_bu}
    if anos_partido:
        plano["votacao_partido_munzona"] = anos_partido
    if anos_bu:
        plano["boletim_urna"] = anos_bu

    return {
        "rotulo": rotulo,
        "membro": membro,
        "ufs": siglas,
        "anos": anos_base,
        "br": False,
        "plano": plano,
    }
