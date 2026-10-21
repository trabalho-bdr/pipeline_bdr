"""Perfil municipal agregado do TSE e indicadores etários do Censo 2022.

Não há vínculo entre características do eleitor e sua escolha partidária.
"""
import json
import re
from collections import defaultdict
from pathlib import Path

from bdr.download import baixar
from bdr.extracao import extrair_nacional
from bdr.ibge import UF_CODIGOS, _requisicao_json


PERFIL_DDL = """id_municipio VARCHAR NOT NULL, ano INTEGER NOT NULL,
    faixa_etaria VARCHAR NOT NULL, genero VARCHAR NOT NULL,
    grau_instrucao VARCHAR NOT NULL, quantidade_eleitores BIGINT NOT NULL
    CHECK (quantidade_eleitores >= 0), fonte VARCHAR, data_geracao DATE,
    PRIMARY KEY (id_municipio, ano, faixa_etaria, genero, grau_instrucao)"""


def _cache_json(url, caminho):
    caminho = Path(caminho)
    if caminho.is_file():
        return json.loads(caminho.read_text(encoding="utf-8"))
    dados = _requisicao_json(url, timeout=120)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parcial = caminho.with_suffix(".part")
    parcial.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    parcial.replace(caminho)
    return dados


def carregar_perfil(con, arquivos, ano, ufs, fonte):
    """Soma zonas e estado civil; preserva o cruzamento idade × gênero × instrução."""
    con.execute("""CREATE OR REPLACE TEMP TABLE perfil_fonte AS
        SELECT * FROM read_csv(?, delim=';', header=true, all_varchar=true,
                              union_by_name=true)""", [[str(p) for p in arquivos]])
    obrigatorias = {"ANO_ELEICAO", "SG_UF", "CD_MUNICIPIO", "DS_FAIXA_ETARIA",
                    "DS_GENERO", "DS_GRAU_ESCOLARIDADE", "QT_ELEITORES_PERFIL"}
    cols = {r[0].upper() for r in con.execute("DESCRIBE perfil_fonte").fetchall()}
    if obrigatorias - cols:
        raise ValueError(f"Perfil TSE: colunas ausentes: {sorted(obrigatorias - cols)}")
    invalidos = con.execute("""SELECT count(*) FROM perfil_fonte
        WHERE try_cast(ANO_ELEICAO AS INTEGER) IS DISTINCT FROM ?
           OR upper(trim(SG_UF)) NOT IN (SELECT unnest(?))
           OR try_cast(QT_ELEITORES_PERFIL AS BIGINT) IS NULL
           OR try_cast(QT_ELEITORES_PERFIL AS BIGINT) < 0
           OR NOT coalesce(regexp_full_match(trim(CD_MUNICIPIO), '[0-9]{1,5}'), false)
           OR nullif(trim(DS_FAIXA_ETARIA),'') IS NULL
           OR nullif(trim(DS_GENERO),'') IS NULL
           OR nullif(trim(DS_GRAU_ESCOLARIDADE),'') IS NULL""", [ano, list(ufs)]).fetchone()[0]
    if invalidos:
        raise ValueError(f"Perfil TSE: {invalidos} linhas inválidas ou fora do escopo")
    data = "try_strptime(DT_GERACAO, '%d/%m/%Y')::DATE" if "DT_GERACAO" in cols else "NULL::DATE"
    con.execute(f"""INSERT INTO Perfil_Eleitorado_Municipio
        SELECT m.id_municipio, ?, upper(trim(p.DS_FAIXA_ETARIA)),
               upper(trim(p.DS_GENERO)), upper(trim(p.DS_GRAU_ESCOLARIDADE)),
               sum(cast(p.QT_ELEITORES_PERFIL AS BIGINT)), ?, max({data})
        FROM perfil_fonte p JOIN Municipio m
          ON m.cod_tse=lpad(trim(p.CD_MUNICIPIO),5,'0')
         AND m.uf=upper(trim(p.SG_UF))
        GROUP BY 1, 3, 4, 5""", [ano, fonte])


def indicadores_idade(dados):
    """Média ponderada das idades completas; grupo aberto 100+ representado por 100.

    Rejeita séries incompletas em vez de calcular médias com denominador parcial.
    """
    por_municipio = defaultdict(dict)
    for variavel in dados:
        for resultado in variavel["resultados"]:
            classificacoes = {str(c["id"]): c for c in resultado["classificacoes"]}
            categorias = classificacoes["287"]["categoria"]
            rotulo = next(iter(categorias.values()))
            if rotulo == "Total":
                idade = "total"
            elif rotulo == "Menos de 1 ano":
                idade = 0
            elif rotulo == "100 anos ou mais":
                idade = 100
            elif re.fullmatch(r"\d+ anos?", rotulo):
                idade = int(rotulo.split()[0])
            else:
                continue  # nunca somar grupos sobrepostos às idades simples
            for serie in resultado["series"]:
                valor = serie["serie"].get("2022")
                if valor is None or not str(valor).isdigit():
                    raise ValueError(f"Censo 9514: valor ausente em {serie['localidade']['id']}")
                por_municipio[str(serie["localidade"]["id"])][idade] = int(valor)
    linhas = {}
    for municipio, idades in por_municipio.items():
        if set(idades) != set(range(101)) | {"total"}:
            raise ValueError(f"Censo 9514 incompleto: {municipio}")
        total = sum(idades[i] for i in range(101))
        if total != idades["total"] or total <= 0:
            raise ValueError(f"Censo 9514: total inconsistente em {municipio}")
        linhas[municipio] = sum(i * idades[i] for i in range(101)) / total
    return linhas


def enriquecer(con, ufs, anos, cache):
    """Atualiza o DER em transação. Falhas não publicam carga parcial no banco."""
    cache = Path(cache)
    ufs = sorted({u.upper() for u in ufs})
    perfis = []
    for ano in sorted(set(anos)):
        nome = f"perfil_eleitorado_{ano}"
        url = f"https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/{nome}.zip"
        zip_path = cache / "zips" / f"{nome}.zip"
        baixar(url, zip_path)
        arquivos, _ = extrair_nacional(zip_path, cache / "raw", ano,
                                      "perfil_eleitorado", "perfil_eleitorado_{ano}", ufs)
        if len(arquivos) != len(ufs):
            raise ValueError(f"Perfil TSE incompleto para {ano}")
        perfis.append((arquivos, ano, url))
    api = "https://servicodados.ibge.gov.br/api/v3/agregados"
    meta = _cache_json(f"{api}/9514/metadados", cache / "ibge/9514_metadados.json")
    classes = next(c for c in meta["classificacoes"] if c["id"] == 287)
    categorias = [str(c["id"]) for c in classes["categorias"]
                  if c["nome"] in ("Total", "Menos de 1 ano", "100 anos ou mais")
                  or re.fullmatch(r"\d+ anos?", c["nome"])]
    demografia = []
    for uf in ufs:
        local = f"localidades=N6[N3[{UF_CODIGOS[uf]}]]"
        url = (f"{api}/9514/periodos/2022/variaveis/93?{local}"
               f"&classificacao=2[6794]|287[{','.join(categorias)}]|286[113635]")
        medias = indicadores_idade(_cache_json(url, cache / f"ibge/idades_2022_{uf}.json"))
        indicadores = _cache_json(f"{api}/9515/periodos/2022/variaveis/10612|10613?{local}",
                                   cache / f"ibge/indicadores_2022_{uf}.json")
        valores = defaultdict(dict)
        for variavel in indicadores:
            for resultado in variavel["resultados"]:
                for serie in resultado["series"]:
                    valor = serie["serie"]["2022"]
                    valores[str(serie["localidade"]["id"])][str(variavel["id"])] = float(valor)
        for municipio, media in medias.items():
            demografia.append((municipio, media, valores[municipio]["10613"],
                               valores[municipio]["10612"]))
        print(f"Demografia IBGE: {uf}, {len(medias)} municípios", flush=True)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS Perfil_Eleitorado_Municipio ({PERFIL_DDL})")
        con.execute("ALTER TABLE Censo_Municipio ADD COLUMN IF NOT EXISTS idade_media_estimada DOUBLE")
        con.execute("ALTER TABLE Censo_Municipio ADD COLUMN IF NOT EXISTS metodo_idade_media VARCHAR")
        for arquivos, ano, url in perfis:
            con.execute("""DELETE FROM Perfil_Eleitorado_Municipio WHERE ano=?
                AND id_municipio IN (SELECT id_municipio FROM Municipio WHERE uf IN (SELECT unnest(?)))""",
                        [ano, ufs])
            carregar_perfil(con, arquivos, ano, ufs, url)
            faltam = con.execute("""SELECT count(*) FROM Municipio m
                WHERE uf IN (SELECT unnest(?)) AND NOT EXISTS (
                    SELECT 1 FROM Perfil_Eleitorado_Municipio p
                    WHERE p.id_municipio=m.id_municipio AND p.ano=?)""", [ufs, ano]).fetchone()[0]
            if faltam:
                raise ValueError(f"Perfil {ano}: {faltam} municípios sem dados")
        con.execute("CREATE OR REPLACE TEMP TABLE demografia_censo (id VARCHAR, media DOUBLE, mediana DOUBLE, envelhecimento DOUBLE)")
        con.executemany("INSERT INTO demografia_censo VALUES (?,?,?,?)", demografia)
        faltam = con.execute("""SELECT count(*) FROM Municipio m WHERE uf IN (SELECT unnest(?))
            AND NOT EXISTS (SELECT 1 FROM demografia_censo d WHERE d.id=m.id_municipio)""", [ufs]).fetchone()[0]
        if faltam:
            raise ValueError(f"Censo etário: {faltam} municípios sem dados")
        con.execute("""INSERT INTO Censo_Municipio (id_municipio, ano_referencia)
            SELECT d.id, 2022 FROM demografia_censo d JOIN Municipio m ON m.id_municipio=d.id
            ON CONFLICT DO NOTHING""")
        con.execute("""UPDATE Censo_Municipio c SET idade_media_estimada=d.media,
            idade_mediana=d.mediana, indice_envelhecimento=d.envelhecimento,
            metodo_idade_media='SIDRA 9514/2022; média de idades completas; 100+ = 100; menor de 1 = 0'
            FROM demografia_censo d WHERE c.id_municipio=d.id AND c.ano_referencia=2022""")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
