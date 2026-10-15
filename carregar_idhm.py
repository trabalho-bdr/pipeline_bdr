#!/usr/bin/env python3
"""Importa o IDHM das planilhas XLSX para o CSV de fontes e um banco DuckDB."""
import argparse
import csv
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
SHEET_NS = {"m": NS}


def coluna_numero(referencia):
    letras = re.match(r"([A-Z]+)", referencia.upper()).group(1)
    numero = 0
    for letra in letras:
        numero = numero * 26 + ord(letra) - ord("A") + 1
    return numero


def texto_celula(celula, compartilhadas):
    tipo = celula.get("t")
    if tipo == "inlineStr":
        return "".join(no.text or "" for no in celula.findall(".//m:t", SHEET_NS))
    valor = celula.find("m:v", SHEET_NS)
    if valor is None or valor.text is None:
        return ""
    if tipo == "s":
        return compartilhadas[int(valor.text)]
    return valor.text


def ler_planilha(caminho):
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
                    valores[coluna_numero(referencia)] = texto_celula(celula, compartilhadas).strip()
            linhas.append(valores)

    cabecalho = None
    for indice, linha in enumerate(linhas):
        textos = {valor.lower(): coluna for coluna, valor in linha.items()}
        coluna_id = next((coluna for valor, coluna in textos.items() if "código" in valor or "codigo" in valor), None)
        coluna_idhm = next((coluna for valor, coluna in textos.items() if "idhm" in valor), None)
        if coluna_id and coluna_idhm:
            cabecalho = (indice, coluna_id, coluna_idhm)
            break
    if cabecalho is None:
        raise ValueError(f"Não encontrei as colunas Código e IDHM em {caminho}")

    indice_cabecalho, coluna_id, coluna_idhm = cabecalho
    registros = []
    for linha in linhas[indice_cabecalho + 1 :]:
        id_municipio = linha.get(coluna_id, "").strip()
        valor = linha.get(coluna_idhm, "").strip().replace(",", ".")
        if not re.fullmatch(r"\d{7}", id_municipio) or valor in {"", "-", "...", ".."}:
            continue
        try:
            idhm = float(valor)
        except ValueError:
            continue
        if 0 <= idhm <= 1:
            registros.append((id_municipio, 2010, idhm))
    return registros


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--planilhas", default="planilhas", help="pasta com os arquivos .xlsx")
    parser.add_argument("--fontes", default="dados_bdr/fontes", help="pasta para o idhm.csv")
    parser.add_argument(
        "--banco",
        default="dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb",
        help="arquivo DuckDB de destino (padrão: DER completo)",
    )
    args = parser.parse_args()

    arquivos = sorted(Path(args.planilhas).glob("*.xlsx"))
    if not arquivos:
        raise SystemExit(f"Nenhuma planilha XLSX encontrada em {args.planilhas}")

    registros_por_id = {}
    for arquivo in arquivos:
        registros = ler_planilha(arquivo)
        for registro in registros:
            registros_por_id[registro[0]] = registro
        print(f"{arquivo.name}: {len(registros):,} municípios com IDHM")

    registros = sorted(registros_por_id.values())
    fontes = Path(args.fontes)
    fontes.mkdir(parents=True, exist_ok=True)
    csv_destino = fontes / "idhm.csv"
    with csv_destino.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(["id_municipio", "ano_referencia", "idhm"])
        escritor.writerows(registros)
    print(f"CSV gerado: {csv_destino} ({len(registros):,} registros)")

    import duckdb

    banco = Path(args.banco)
    if not banco.exists():
        raise SystemExit(f"Banco DuckDB não encontrado: {banco}")
    con = duckdb.connect(str(banco))
    try:
        con.execute("""
            CREATE TEMP TABLE novos_idhm (
                id_municipio VARCHAR,
                ano_referencia INTEGER,
                idhm DOUBLE
            )
        """)
        con.executemany("INSERT INTO novos_idhm VALUES (?, ?, ?)", registros)
        tabelas = {r[0].lower(): r[0] for r in con.execute("SHOW TABLES").fetchall()}
        nome_tabela = tabelas.get("censo_municipio")
        if not nome_tabela:
            raise RuntimeError("A tabela censo_municipio/Censo_Municipio não existe no banco")
        tabela = '"' + nome_tabela.replace('"', '""') + '"'
        con.execute(f"""
            UPDATE {tabela} AS c
            SET idhm = n.idhm
            FROM novos_idhm AS n
            WHERE c.id_municipio = n.id_municipio
        """)
        total, preenchidos, sem_municipio = con.execute("""
            SELECT
                count(*),
                count(idhm),
                count(*) FILTER (WHERE id_municipio NOT IN (SELECT id_municipio FROM municipio))
            FROM """ + tabela + """
        """).fetchone()
        con.commit()
    finally:
        con.close()

    print(f"Banco atualizado: {banco}")
    print(f"IDHM municipal: {preenchidos:,}/{total:,} registros; códigos fora de municipio: {sem_municipio:,}")


if __name__ == "__main__":
    main()
