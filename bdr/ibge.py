"""Módulo de integração com APIs do IBGE e de-para oficial TSE-IBGE para a Questão 3.

Fontes utilizadas:
- IBGE Localidades API (v1): lista oficial de municípios por UF com código IBGE de 7 dígitos e macrorregião.
- IBGE SIDRA Agregados (v3), Tabela 4709: População residente no Censo Demográfico 2022.
- IBGE SIDRA Agregados (v3), Tabela 5938 (variável 37): PIB a preços correntes (2022).
- TSE Portal de Dados Abertos: tabela de correspondência oficial município TSE <-> IBGE (municipio_tse_ibge.zip).
- Atlas Brasil / PNUD / IPEA: IDHM 2010 (leitura de arquivo local dados_bdr/fontes/idhm.csv).
"""
import csv
import gzip
import io
import json
import urllib.request
import zipfile
from pathlib import Path

from .download import baixar

URL_DE_PARA_TSE = "https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip"
URL_IBGE_LOCALIDADES = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
URL_IBGE_POPULACAO = "https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/variaveis/93?localidades=N6[N3[{uf_code}]]"
URL_IBGE_PIB = "https://servicodados.ibge.gov.br/api/v3/agregados/5938/periodos/2022/variaveis/37?localidades=N6[N3[{uf_code}]]"

UF_CODIGOS = {
    "RO": 11, "AC": 12, "AM": 13, "RR": 14, "PA": 15, "AP": 16, "TO": 17,
    "MA": 21, "PI": 22, "CE": 23, "RN": 24, "PB": 25, "PE": 26, "AL": 27,
    "SE": 28, "BA": 29, "MG": 31, "ES": 32, "RJ": 33, "SP": 35, "PR": 41,
    "SC": 42, "RS": 43, "MS": 50, "MT": 51, "GO": 52, "DF": 53,
}


def _requisicao_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        bruto = resp.read()
        if bruto[:2] == b"\x1f\x8b":
            bruto = gzip.decompress(bruto)
        return json.loads(bruto.decode("utf-8"))


def garantir_de_para_oficial(pasta_zips, pasta_fontes):
    """Baixa o zip oficial de correspondência TSE <-> IBGE e extrai o CSV."""
    pasta_fontes = Path(pasta_fontes)
    pasta_fontes.mkdir(parents=True, exist_ok=True)
    csv_destino = pasta_fontes / "municipio_tse_ibge.csv"
    if csv_destino.exists() and csv_destino.stat().st_size > 0:
        return csv_destino

    pasta_zips = Path(pasta_zips)
    pasta_zips.mkdir(parents=True, exist_ok=True)
    zip_path = pasta_zips / "municipio_tse_ibge.zip"
    baixar(URL_DE_PARA_TSE, zip_path)

    with zipfile.ZipFile(zip_path) as z:
        alvo = next((i for i in z.infolist() if i.filename.lower().endswith(".csv")), None)
        if not alvo:
            raise FileNotFoundError("CSV não encontrado dentro de municipio_tse_ibge.zip")
        with z.open(alvo) as f_in, open(csv_destino, "w", encoding="utf-8", newline="\n") as f_out:
            texto = io.TextIOWrapper(f_in, encoding="latin-1")
            for linha in texto:
                l = linha.strip()
                if l:
                    f_out.write(l + "\n")

    return csv_destino


def baixar_dados_ibge(ufs, pasta_raw):
    """Baixa e armazena em cache os JSONs de Localidades, População e PIB das UFs."""
    pasta_ibge = Path(pasta_raw) / "ibge"
    pasta_ibge.mkdir(parents=True, exist_ok=True)

    arquivos = []
    for uf in ufs:
        uf = uf.upper()
        if uf not in UF_CODIGOS:
            continue
        cod_uf = UF_CODIGOS[uf]

        # 1. Localidades (Municípios, mesorregião, macrorregião)
        arq_loc = pasta_ibge / f"municipios_{uf}.json"
        if not (arq_loc.exists() and arq_loc.stat().st_size > 0):
            try:
                dados = _requisicao_json(URL_IBGE_LOCALIDADES.format(uf=uf))
                arq_loc.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
                arquivos.append(arq_loc)
            except Exception as e:
                print(f"     Aviso ao obter localidades IBGE para {uf}: {e}")
        else:
            arquivos.append(arq_loc)

        # 2. População Censo 2022 (Tabela 4709)
        arq_pop = pasta_ibge / f"populacao_2022_{uf}.json"
        if not (arq_pop.exists() and arq_pop.stat().st_size > 0):
            try:
                dados = _requisicao_json(URL_IBGE_POPULACAO.format(uf_code=cod_uf))
                arq_pop.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
                arquivos.append(arq_pop)
            except Exception as e:
                print(f"     Aviso ao obter população IBGE para {uf}: {e}")
        else:
            arquivos.append(arq_pop)

        # 3. PIB 2022 (Tabela 5938, variável 37)
        arq_pib = pasta_ibge / f"pib_2022_{uf}.json"
        if not (arq_pib.exists() and arq_pib.stat().st_size > 0):
            try:
                dados = _requisicao_json(URL_IBGE_PIB.format(uf_code=cod_uf))
                arq_pib.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
                arquivos.append(arq_pib)
            except Exception as e:
                print(f"     Aviso ao obter PIB IBGE para {uf}: {e}")
        else:
            arquivos.append(arq_pib)

    return arquivos


def carregar_dados_socioeconomicos(con, ufs, pasta_raw, pasta_fontes):
    """Lê os dados locais de IBGE e IDHM e alimenta as tabelas stg_ibge_* e censo_municipio."""
    pasta_ibge = Path(pasta_raw) / "ibge"
    pasta_fontes = Path(pasta_fontes)

    # Tabela intermediária para localidades IBGE
    con.execute("DROP TABLE IF EXISTS stg_ibge_municipio")
    con.execute("""
        CREATE TABLE stg_ibge_municipio (
            id_municipio VARCHAR PRIMARY KEY,
            nome VARCHAR,
            uf VARCHAR,
            regiao VARCHAR
        )
    """)

    # Tabela intermediária para Censo / PIB (ano 2022)
    con.execute("DROP TABLE IF EXISTS stg_ibge_censo")
    con.execute("""
        CREATE TABLE stg_ibge_censo (
            id_municipio VARCHAR PRIMARY KEY,
            populacao BIGINT,
            pib DECIMAL(18,2)
        )
    """)

    # 1. Carrega municípios das localidades
    municipios_map = {}
    for uf in ufs:
        arq_loc = pasta_ibge / f"municipios_{uf}.json"
        if arq_loc.exists():
            try:
                dados = json.loads(arq_loc.read_text(encoding="utf-8"))
                for item in dados:
                    id_mun = str(item.get("id"))
                    nome = item.get("nome")
                    regiao = item.get("microrregiao", {}).get("mesorregiao", {}).get("UF", {}).get("regiao", {}).get("nome")
                    municipios_map[id_mun] = (nome, uf, regiao)
            except Exception as e:
                print(f"     Aviso ao ler {arq_loc.name}: {e}")

    for id_mun, (nome, uf, regiao) in municipios_map.items():
        con.execute(
            "INSERT INTO stg_ibge_municipio VALUES (?, ?, ?, ?)",
            [id_mun, nome, uf, regiao]
        )

    # 2. Carrega População 2022
    pop_map = {}
    for uf in ufs:
        arq_pop = pasta_ibge / f"populacao_2022_{uf}.json"
        if arq_pop.exists():
            try:
                dados = json.loads(arq_pop.read_text(encoding="utf-8"))
                if dados and "resultados" in dados[0]:
                    series = dados[0]["resultados"][0].get("series", [])
                    for s in series:
                        id_mun = str(s.get("localidade", {}).get("id"))
                        val = s.get("serie", {}).get("2022")
                        if val and val not in ("-", "...", ".."):
                            try:
                                pop_map[id_mun] = int(val)
                            except ValueError:
                                pass
            except Exception as e:
                print(f"     Aviso ao ler {arq_pop.name}: {e}")

    # 3. Carrega PIB 2022 (convertendo de Mil R$ para R$)
    pib_map = {}
    for uf in ufs:
        arq_pib = pasta_ibge / f"pib_2022_{uf}.json"
        if arq_pib.exists():
            try:
                dados = json.loads(arq_pib.read_text(encoding="utf-8"))
                if dados and "resultados" in dados[0]:
                    series = dados[0]["resultados"][0].get("series", [])
                    for s in series:
                        id_mun = str(s.get("localidade", {}).get("id"))
                        val = s.get("serie", {}).get("2022")
                        if val and val not in ("-", "...", ".."):
                            try:
                                # PIB está em Mil Reais; multiplica por 1000 para armazenar em R$
                                pib_map[id_mun] = float(val) * 1000.0
                            except ValueError:
                                pass
            except Exception as e:
                print(f"     Aviso ao ler {arq_pib.name}: {e}")

    todos_ids = set(pop_map.keys()) | set(pib_map.keys()) | set(municipios_map.keys())
    for id_mun in todos_ids:
        con.execute(
            "INSERT INTO stg_ibge_censo VALUES (?, ?, ?)",
            [id_mun, pop_map.get(id_mun), pib_map.get(id_mun)]
        )

    # 4. Carrega IDHM se o CSV existir
    con.execute("DROP TABLE IF EXISTS stg_idhm")
    con.execute("""
        CREATE TABLE stg_idhm (
            id_municipio VARCHAR,
            ano_referencia INTEGER,
            idhm DOUBLE
        )
    """)
    arq_idhm = pasta_fontes / "idhm.csv"
    if arq_idhm.exists():
        try:
            with open(arq_idhm, encoding="utf-8") as f:
                primeira = f.readline()
                delim = ";" if ";" in primeira else ","
            rel = con.execute(f"SELECT * FROM read_csv('{arq_idhm.as_posix()}', delim='{delim}', all_varchar=true) LIMIT 0")
            cols = {d[0].lower(): d[0] for d in rel.description}
            col_id = next((cols[c] for c in ("id_municipio", "cod_ibge", "codigo_ibge", "cod_municipio_ibge") if c in cols), None)
            col_idhm = next((cols[c] for c in ("idhm", "idhm_2010", "valor_idhm") if c in cols), None)
            col_ano = next((cols[c] for c in ("ano_referencia", "ano") if c in cols), None)
            if col_id and col_idhm:
                ano_expr = f'TRY_CAST("{col_ano}" AS INTEGER)' if col_ano else "2010"
                con.execute(f"""
                    INSERT INTO stg_idhm
                    SELECT
                        trim("{col_id}"),
                        coalesce({ano_expr}, 2010),
                        TRY_CAST(replace("{col_idhm}", ',', '.') AS DOUBLE)
                    FROM read_csv('{arq_idhm.as_posix()}', delim='{delim}', all_varchar=true)
                    WHERE trim("{col_id}") IS NOT NULL
                """)
        except Exception as e:
            print(f"     Aviso ao carregar IDHM de {arq_idhm}: {e}")
