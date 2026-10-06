"""Lê o IDHM 2010 das planilhas usadas na branch feat/ajustelocal."""

import csv
import re
import shutil
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SHEET_NS = {"m": NS}


def _coluna_numero(referencia):
    letras = re.match(r"([A-Z]+)", referencia.upper()).group(1)
    numero = 0
    for letra in letras:
        numero = numero * 26 + ord(letra) - ord("A") + 1
    return numero


def _texto_celula(celula, compartilhadas):
    tipo = celula.get("t")
    if tipo == "inlineStr":
        return "".join(no.text or "" for no in celula.findall(".//m:t", SHEET_NS))
    valor = celula.find("m:v", SHEET_NS)
    if valor is None or valor.text is None:
        return ""
    return compartilhadas[int(valor.text)] if tipo == "s" else valor.text


def ler_planilha(caminho):
    """Extrai código IBGE e IDHM, mantendo o ano oficial de referência 2010."""
    with zipfile.ZipFile(caminho) as arquivo:
        compartilhadas = []
        try:
            raiz = ET.fromstring(arquivo.read("xl/sharedStrings.xml"))
            compartilhadas = [
                "".join(no.text or "" for no in item.findall(".//m:t", SHEET_NS))
                for item in raiz.findall("m:si", SHEET_NS)
            ]
        except KeyError:
            pass
        raiz = ET.fromstring(arquivo.read("xl/worksheets/sheet1.xml"))
        linhas = []
        for linha in raiz.findall("m:sheetData/m:row", SHEET_NS):
            valores = {}
            for celula in linha.findall("m:c", SHEET_NS):
                referencia = celula.get("r", "")
                if referencia:
                    valores[_coluna_numero(referencia)] = _texto_celula(celula, compartilhadas).strip()
            linhas.append(valores)
    cabecalho = None
    for indice, linha in enumerate(linhas):
        textos = {valor.lower(): coluna for coluna, valor in linha.items()}
        coluna_id = next((coluna for valor, coluna in textos.items()
                          if "código" in valor or "codigo" in valor), None)
        coluna_idhm = next((coluna for valor, coluna in textos.items() if "idhm" in valor), None)
        if coluna_id and coluna_idhm:
            cabecalho = indice, coluna_id, coluna_idhm
            break
    if cabecalho is None:
        raise ValueError(f"Colunas Código e IDHM não encontradas em {caminho}")
    indice, coluna_id, coluna_idhm = cabecalho
    registros = []
    for linha in linhas[indice + 1:]:
        codigo = linha.get(coluna_id, "").strip()
        valor = linha.get(coluna_idhm, "").strip().replace(",", ".")
        if not re.fullmatch(r"\d{7}", codigo):
            continue
        try:
            idhm = float(valor)
        except ValueError:
            continue
        if 0 <= idhm <= 1:
            registros.append((codigo, 2010, idhm))
    return registros


def preparar_csv_idhm(fontes, planilhas="planilhas", csv_existente="dados_bdr/fontes/idhm.csv"):
    """Usa planilhas locais ou um CSV já preparado; não inventa IDHM ausente."""
    fontes = Path(fontes)
    destino = fontes / "idhm.csv"
    arquivos = sorted(Path(planilhas).glob("*.xlsx"))
    if arquivos:
        registros = {}
        for arquivo in arquivos:
            for codigo, ano, idhm in ler_planilha(arquivo):
                anterior = registros.get(codigo)
                if anterior is not None and anterior[2] != idhm:
                    raise ValueError(f"IDHM conflitante para município {codigo}")
                registros[codigo] = (codigo, ano, idhm)
        if not registros:
            raise ValueError("Planilhas IDHM sem códigos municipais válidos")
        fontes.mkdir(parents=True, exist_ok=True)
        with destino.open("w", encoding="utf-8", newline="") as saida:
            escritor = csv.writer(saida, delimiter=";")
            escritor.writerow(("id_municipio", "ano_referencia", "idhm"))
            escritor.writerows(sorted(registros.values()))
        return destino
    existente = Path(csv_existente)
    if existente.is_file():
        fontes.mkdir(parents=True, exist_ok=True)
        if existente.resolve() != destino.resolve():
            shutil.copyfile(existente, destino)
        return destino
    return None
