"""Gera os ativos estáticos do mapa a partir do IBGE (executar uma vez, com internet).

    uv run python scripts/preparar_malhas.py

Saída em web/public/geo/: br_ufs.json, <UF>.json (TopoJSON municipal), catalogo.json, metadados.json.
Falha (código 1) se houver município ausente, extra, duplicado ou geometria vazia.
"""
import gzip
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

SAIDA = Path(__file__).resolve().parent / "public" / "geo"
UFS = {"CE": "23", "MA": "21", "MS": "50", "RJ": "33", "RN": "24", "RS": "43"}
API = "https://servicodados.ibge.gov.br/api"
Q_NACIONAL, Q_ESTADO = "minima", "intermediaria"


import time

def baixar(url, tentativas=3):
    for i in range(tentativas):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bdr"}), timeout=45) as r:
                dados = r.read()
                if r.info().get("Content-Encoding") == "gzip" or dados.startswith(b"\x1f\x8b"):
                    return gzip.decompress(dados)
                return dados
        except Exception as e:
            if i == tentativas - 1:
                raise
            time.sleep(2)


def codigos(topo):
    nome = next(iter(topo["objects"]))
    return [(g.get("properties", {}).get("codarea"), g) for g in topo["objects"][nome]["geometries"]]


def main():
    SAIDA.mkdir(parents=True, exist_ok=True)
    meta = {"fonte": "IBGE — API de Malhas v3 e API de Localidades v1", "baixado_em": date.today().isoformat(),
            "versao_territorial": "malha municipal vigente na data do download (confirmar no IBGE)",
            "aviso": "Malha atual: pode não refletir a divisão territorial de 2018/2020 em todos os casos.",
            "qualidade": {"ufs": Q_NACIONAL, "municipios": Q_ESTADO}, "arquivos": {}}
    
    arq_br = SAIDA / "br_ufs.json"
    if arq_br.is_file() and arq_br.stat().st_size > 1000:
        bruto = arq_br.read_bytes()
    else:
        bruto = baixar(f"{API}/v3/malhas/paises/BR?formato=application/json&qualidade={Q_NACIONAL}&intrarregiao=UF")
        arq_br.write_bytes(bruto)
    meta["arquivos"]["br_ufs.json"] = len(bruto)

    ufs = json.loads(baixar(f"{API}/v1/localidades/estados"))
    catalogo = {"ufs": [{"cod": str(u["id"]), "sigla": u["sigla"], "nome": u["nome"]} for u in ufs], "municipios": {}}
    erros = []
    for uf, cod in UFS.items():
        print(f"Processando {uf}...")
        cat = json.loads(baixar(f"{API}/v1/localidades/estados/{cod}/municipios"))
        catalogo["municipios"][uf] = [{"id": str(m["id"]), "nome": m["nome"]} for m in cat]
        arq_uf = SAIDA / f"{uf}.json"
        if arq_uf.is_file() and arq_uf.stat().st_size > 1000:
            bruto = arq_uf.read_bytes()
        else:
            bruto = baixar(f"{API}/v3/malhas/estados/{cod}?formato=application/json"
                           f"&qualidade={Q_ESTADO}&intrarregiao=municipio")
            arq_uf.write_bytes(bruto)
        meta["arquivos"][f"{uf}.json"] = len(bruto)
        pares = codigos(json.loads(bruto))
        geo = [c for c, _ in pares]
        esperado = {m["id"] for m in catalogo["municipios"][uf]}
        ausentes, extras = esperado - set(geo), set(geo) - esperado
        dup = {c for c in geo if geo.count(c) > 1}
        vazios = [c for c, g in pares if not g.get("arcs")]
        meta[uf] = {"municipios_catalogo": len(esperado), "geometrias": len(geo)}
        if ausentes or extras or dup or vazios:
            erros.append(f"{uf}: ausentes={sorted(ausentes)} extras={sorted(extras)} "
                         f"duplicados={sorted(dup)} vazios={vazios}")
    (SAIDA / "catalogo.json").write_text(json.dumps(catalogo, ensure_ascii=False), encoding="utf-8")
    (SAIDA / "metadados.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta["arquivos"], indent=1))
    if erros:
        print("COBERTURA INVÁLIDA:\n" + "\n".join(erros))
        sys.exit(1)
    print("Cobertura municipal validada nos 6 estados.")


if __name__ == "__main__":
    main()
