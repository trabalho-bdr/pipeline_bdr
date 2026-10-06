"""Escopo e fontes oficiais da trajetória eleitoral."""

ANOS_TRAJETORIA = list(range(2002, 2025, 2))
UFS_PADRAO = ["CE", "MA", "MS", "RJ", "RN", "RS"]
CDN_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele"

RECURSOS = {
    "consulta_cand": {
        "pasta": "consulta_cand",
        "zip": "consulta_cand_{ano}",
        "partes": {"consulta_cand": "consulta_cand_{ano}_{uf}"},
    },
    "votacao_candidato_munzona": {
        "pasta": "votacao_candidato_munzona",
        "zip": "votacao_candidato_munzona_{ano}",
        "partes": {
            "votacao_candidato_munzona": "votacao_candidato_munzona_{ano}_{uf}"
        },
    },
}


def montar_escopo(ufs=None, anos=None):
    siglas = sorted({u.strip().upper() for u in (ufs or UFS_PADRAO)})
    invalidas = [u for u in siglas if len(u) != 2 or not u.isalpha()]
    if invalidas:
        raise ValueError("UF inválida: " + ", ".join(invalidas))
    anos_escolhidos = sorted(set(anos or ANOS_TRAJETORIA))
    fora = [a for a in anos_escolhidos if a not in ANOS_TRAJETORIA]
    if fora:
        raise ValueError("Ano fora do período 2002-2024: " + ", ".join(map(str, fora)))
    return {
        "ufs": siglas,
        "anos": anos_escolhidos,
        "rotulo": "trajetoria_" + "-".join(siglas),
    }
