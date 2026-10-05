"""Extrai de um ZIP nacional do TSE só o que interessa ao membro, já convertido para UTF-8.

Saída padronizada: raw/<parte>/<parte>_<ano>/<parte>_<ano>_<UF>.csv
"""
import csv
import io
import re
import shutil
import zipfile
from pathlib import Path


def destino_raw(raiz, parte, ano, uf):
    return Path(raiz) / parte / f"{parte}_{ano}" / f"{parte}_{ano}_{uf}.csv"


def _nomes(z):
    return [Path(i.filename).name for i in z.infolist() if not i.is_dir()]


def _filtrar_consolidado(z, info, destinos, coluna_uf="SG_UF"):
    """Lê um consolidado (ex.: *_BRASIL.csv) em streaming e grava um CSV por UF só com as
    linhas daquela UF. Só cria o arquivo se houver pelo menos uma linha."""
    abertos, escritores = {}, {}
    with z.open(info) as bruto:
        leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""),
                            delimiter=";", quotechar='"')
        cabecalho = next(leitor)
        try:
            idx = [c.strip().upper() for c in cabecalho].index(coluna_uf)
        except ValueError:
            return []
        for linha in leitor:
            if len(linha) <= idx:
                continue
            uf = linha[idx].strip().upper()
            if uf not in destinos:
                continue
            if uf not in escritores:
                destinos[uf].parent.mkdir(parents=True, exist_ok=True)
                abertos[uf] = open(destinos[uf].with_suffix(".part"), "w", encoding="utf-8", newline="")
                escritores[uf] = csv.writer(abertos[uf], delimiter=";", quoting=csv.QUOTE_ALL,
                                            lineterminator="\n")
                escritores[uf].writerow(cabecalho)
            escritores[uf].writerow(linha)
    criados = []
    for uf, f in abertos.items():
        f.close()
        destinos[uf].with_suffix(".part").replace(destinos[uf])
        criados.append(destinos[uf])
    return criados


def extrair_por_uf(zip_path, raiz, ano, partes, siglas):
    """CSVs por UF dentro do ZIP (ex.: receitas_candidatos_2020_MG.csv).

    O padrão é ancorado: 'receitas_candidatos_2020_MG' não casa com
    'receitas_candidatos_doador_originario_2020_MG', e '_BR' não casa com '_BRASIL'.
    Devolve (arquivos gerados, nomes existentes no ZIP).
    """
    regras = []
    for parte, modelo in partes.items():
        for uf in siglas:
            nome = modelo.format(ano=ano, uf=uf)
            regras.append((re.compile(rf"^{re.escape(nome)}\.(csv|txt)$", re.IGNORECASE), parte, uf))
    gerados = []
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            nome = Path(info.filename).name
            for padrao, parte, uf in regras:
                if info.is_dir() or not padrao.match(nome):
                    continue
                destino = destino_raw(raiz, parte, ano, uf)
                if not (destino.exists() and destino.stat().st_size > 0):
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(info) as bruto, open(destino, "w", encoding="utf-8", newline="") as saida:
                        shutil.copyfileobj(io.TextIOWrapper(bruto, encoding="latin-1", newline=""),
                                           saida, 1 << 20)
                gerados.append(destino)

        # Plano B: UF sem arquivo próprio no ZIP (ex.: '_BR' do presidente em 2022) -> procura as
        # linhas dela no consolidado '_BRASIL' do mesmo arquivo.
        faltantes = {}
        for parte in partes:
            for uf in siglas:
                destino = destino_raw(raiz, parte, ano, uf)
                if not (destino.exists() and destino.stat().st_size > 0):
                    faltantes.setdefault(parte, {})[uf] = destino
        for parte, destinos in faltantes.items():
            consolidado = re.compile(
                rf"^{re.escape(partes[parte].format(ano=ano, uf='BRASIL'))}\.(csv|txt)$", re.IGNORECASE)
            info = next((i for i in z.infolist()
                         if not i.is_dir() and consolidado.match(Path(i.filename).name)), None)
            if info is not None:
                print(f"     sem arquivo próprio de {', '.join(destinos)}; filtrando {Path(info.filename).name}")
                gerados += _filtrar_consolidado(z, info, destinos)
        return gerados, _nomes(z)


def extrair_nacional(zip_path, raiz, ano, parte, modelo, siglas, coluna_uf="SG_UF"):
    """CSV único para o Brasil (ex.: perfil_eleitorado_2020.csv): lê em streaming e grava
    um arquivo por UF só com as linhas daquela UF. Devolve (arquivos gerados, nomes no ZIP)."""
    destinos = {uf: destino_raw(raiz, parte, ano, uf) for uf in siglas}
    alvo = re.compile(rf"^{re.escape(modelo.format(ano=ano))}\.(csv|txt)$", re.IGNORECASE)
    with zipfile.ZipFile(zip_path) as z:
        nomes = _nomes(z)
        if all(d.exists() and d.stat().st_size > 0 for d in destinos.values()):
            return list(destinos.values()), nomes
        info = next((i for i in z.infolist() if alvo.match(Path(i.filename).name)), None)
        if info is None:
            return [], nomes

        with z.open(info) as bruto:
            leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""),
                                delimiter=";", quotechar='"')
            cabecalho = next(leitor)
            idx = [c.strip().upper() for c in cabecalho].index(coluna_uf)
            arquivos, escritores = {}, {}
            for uf, destino in destinos.items():
                destino.parent.mkdir(parents=True, exist_ok=True)
                arquivos[uf] = open(destino.with_suffix(".part"), "w", encoding="utf-8", newline="")
                escritores[uf] = csv.writer(arquivos[uf], delimiter=";", quoting=csv.QUOTE_ALL,
                                            lineterminator="\n")
                escritores[uf].writerow(cabecalho)
            lidas = 0
            for linha in leitor:
                lidas += 1
                esc = escritores.get(linha[idx].strip().upper()) if len(linha) > idx else None
                if esc:
                    esc.writerow(linha)
                if lidas % 2_000_000 == 0:
                    print(f"\r     {lidas / 1e6:,.0f} milhões de linhas lidas", end="", flush=True)
            print(f"\r     {lidas:,} linhas lidas no arquivo nacional")
            for uf, f in arquivos.items():
                f.close()
                destinos[uf].with_suffix(".part").replace(destinos[uf])
        return list(destinos.values()), nomes