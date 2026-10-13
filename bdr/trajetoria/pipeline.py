"""Orquestra download, carga, validação e exportação da trajetória."""

from pathlib import Path

import duckdb

from bdr.download import baixar
from bdr.extracao import destino_raw, extrair_por_uf
from bdr.esquema import criar_tabelas as criar_tabelas_q3

from .config import CDN_TSE, RECURSOS
from .exportacao import exportar
from .transformacao import carregar
from .validacao import imprimir, salvar, validar


class Pastas:
    def __init__(self, base, rotulo):
        self.base = Path(base)
        self.zips = self.base / "zips"
        self.raw = self.base / "raw"
        self.saida = self.base / "saida" / rotulo
        self.banco = self.saida / f"{rotulo}.duckdb"
        self.manifesto = self.saida / "manifesto.json"


def baixar_fontes(escopo, pastas, apagar_zips=False):
    registro, problemas = [], []
    for ano in escopo["anos"]:
        for recurso, cfg in RECURSOS.items():
            if cfg.get("anos_disponiveis") and ano not in cfg["anos_disponiveis"]:
                registro.append({
                    "ano": ano, "recurso": recurso, "status": "indisponivel",
                    "extraidos": [], "itens_zip": 0,
                })
                print(f"   AVISO: {recurso} não publicado pelo TSE em {ano}")
                continue
            nome = cfg["zip"].format(ano=ano)
            url = f"{CDN_TSE}/{cfg['pasta']}/{nome}.zip"
            zip_path = pastas.zips / recurso / f"{nome}.zip"
            print(f"[{ano}] {recurso}")
            try:
                status = baixar(url, zip_path)
                gerados, nomes = extrair_por_uf(
                    zip_path, pastas.raw, ano, cfg["partes"], escopo["ufs"]
                )
                registro.append({
                    "ano": ano, "recurso": recurso, "status": status,
                    "extraidos": [p.name for p in gerados], "itens_zip": len(nomes),
                })
                print(f"   {len(gerados)} arquivos extraídos")
                if apagar_zips:
                    zip_path.unlink(missing_ok=True)
            except FileNotFoundError as exc:
                if cfg.get("opcional"):
                    registro.append({
                        "ano": ano, "recurso": recurso, "status": "indisponivel",
                        "extraidos": [], "itens_zip": 0,
                    })
                    print(f"   AVISO: fonte opcional indisponível ({exc})")
                    continue
                problemas.append(f"{ano}/{recurso}: {exc}")
                print(f"   ERRO: {exc}")
            except Exception as exc:
                problemas.append(f"{ano}/{recurso}: {exc}")
                print(f"   ERRO: {exc}")
    return registro, problemas


def _arquivos(escopo, pastas, parte):
    return [
        destino_raw(pastas.raw, parte, ano, uf)
        for ano in escopo["anos"] for uf in escopo["ufs"]
        if destino_raw(pastas.raw, parte, ano, uf).is_file()
    ]


def carregar_validar(escopo, pastas, registro=None, problemas_download=None):
    pastas.saida.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(pastas.banco))
    # Mantém as dimensões compartilhadas compatíveis com a pipeline Q3.
    criar_tabelas_q3(con)
    candidatos = _arquivos(escopo, pastas, "consulta_cand")
    votos = _arquivos(escopo, pastas, "votacao_candidato_munzona")
    despesas = _arquivos(escopo, pastas, "despesas_contratadas_candidatos")
    esperados = len(escopo["anos"]) * len(escopo["ufs"])
    arquivos = {
        "consulta_cand": len(candidatos),
        "votacao_candidato_munzona": len(votos),
        "despesas_contratadas_candidatos": len(despesas),
        "esperados_por_recurso": esperados,
        "downloads": registro or [],
    }
    carregar(con, candidatos, votos, despesas)
    manifesto = validar(con, escopo, arquivos)
    manifesto["problemas"] = list(problemas_download or []) + manifesto["problemas"]
    manifesto["completo"] = not manifesto["problemas"]
    salvar(manifesto, pastas.manifesto)
    imprimir(manifesto)
    con.close()
    return manifesto


def exportar_dados(pastas):
    if not pastas.banco.is_file() or not pastas.manifesto.is_file():
        raise ValueError("Rode a etapa carregar antes de exportar.")
    import json
    manifesto = json.loads(pastas.manifesto.read_text(encoding="utf-8"))
    if not manifesto.get("completo"):
        raise ValueError("A exportação foi bloqueada porque a validação possui pendências.")
    con = duckdb.connect(str(pastas.banco), read_only=True)
    destino = exportar(con, pastas.saida, manifesto)
    con.close()
    return destino
