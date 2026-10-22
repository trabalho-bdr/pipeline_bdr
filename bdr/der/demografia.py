"""Perfil municipal agregado do TSE e indicadores etários do Censo 2022.

Não há vínculo entre características do eleitor e sua escolha partidária.
"""
import json
import re
import time
import urllib.error
from collections import defaultdict
from pathlib import Path

from bdr.download import baixar
from bdr.extracao import extrair_nacional, extrair_por_uf
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
    for tentativa in range(1, 5):
        try:
            dados = _requisicao_json(url, timeout=120)
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError) as erro:
            if isinstance(erro, urllib.error.HTTPError) and erro.code not in {
                408, 429, 500, 502, 503, 504
            }:
                raise
            if tentativa == 4:
                raise RuntimeError(
                    f"IBGE: falha após 4 tentativas ao obter {caminho.name}: {erro}. "
                    "Os arquivos em cache foram preservados; execute novamente com --retomar."
                ) from erro
            espera = 2 ** tentativa
            print(f"IBGE: {caminho.name}, tentativa {tentativa}/4 falhou: {erro}. "
                  f"Nova tentativa em {espera}s.", flush=True)
            time.sleep(espera)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    parcial = caminho.with_suffix(".part")
    parcial.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    parcial.replace(caminho)
    return dados


def _fonte_opcional(funcao, *args, avisos, rotulo, **kwargs):
    """Indisponibilidade externa não impede a carga das outras fontes."""
    try:
        return funcao(*args, **kwargs)
    except (urllib.error.URLError, TimeoutError, ConnectionError,
            FileNotFoundError, RuntimeError) as erro:
        aviso = f"{rotulo}: fonte indisponível; dados anteriores preservados. {erro}"
        avisos.append(aviso)
        print(f"Aviso: {aviso}", flush=True)
        return None


def _projecao_perfil(colunas):
    """Normaliza nomes observados nos CSVs oficiais, sem inferir valores ausentes."""
    aliases = {
        "ANO_ELEICAO": ("ANO_ELEICAO", "AA_ELEICAO"),
        "SG_UF": ("SG_UF",),
        "CD_MUNICIPIO": ("CD_MUNICIPIO",),
        "DS_FAIXA_ETARIA": ("DS_FAIXA_ETARIA",),
        "DS_GENERO": ("DS_GENERO",),
        "DS_GRAU_ESCOLARIDADE": ("DS_GRAU_ESCOLARIDADE",),
        "QT_ELEITORES_PERFIL": ("QT_ELEITORES_PERFIL", "QT_ELEITORES"),
        "DT_GERACAO": ("DT_GERACAO",),
    }
    por_nome = {c.strip().lstrip('\ufeff').upper(): c for c in colunas}
    selecoes = []
    faltantes = []
    for campo, nomes in aliases.items():
        encontrados = [por_nome[n] for n in nomes if n in por_nome]
        if not encontrados:
            if campo != "DT_GERACAO":
                faltantes.append(f"{campo} (aceita {', '.join(nomes)})")
            expr = "NULL::VARCHAR"
        else:
            expressoes = ['nullif(trim("' + c.replace('"', '""') + '"), \'\')'
                          for c in encontrados]
            expr = f"coalesce({', '.join(expressoes)})" if len(expressoes) > 1 else expressoes[0]
        selecoes.append(f'{expr} AS "{campo}"')
    if faltantes:
        raise ValueError(f"Perfil TSE: colunas ausentes: {faltantes}. Cabeçalho encontrado: {list(colunas)}")
    return ', '.join(selecoes)


def carregar_perfil(con, arquivos, ano, ufs, fonte, substituir=False):
    """Soma zonas e estado civil; preserva o cruzamento idade × gênero × instrução."""
    con.execute("""CREATE OR REPLACE TEMP TABLE perfil_bruto AS
        SELECT * FROM read_csv(?, delim=';', header=true, all_varchar=true,
                              union_by_name=true)""", [[str(p) for p in arquivos]])
    cols = [r[0] for r in con.execute("DESCRIBE perfil_bruto").fetchall()]
    try:
        projecao = _projecao_perfil(cols)
    except ValueError as erro:
        raise ValueError(f"{erro}. Ano: {ano}; arquivos: {[str(p) for p in arquivos]}") from erro
    con.execute(f"CREATE OR REPLACE TEMP TABLE perfil_fonte AS SELECT {projecao} FROM perfil_bruto")
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
    if substituir:
        con.execute("""DELETE FROM Perfil_Eleitorado_Municipio WHERE ano=?
            AND id_municipio IN (SELECT m.id_municipio FROM Municipio m
                JOIN perfil_fonte p ON m.cod_tse=lpad(trim(p.CD_MUNICIPIO),5,'0')
                AND m.uf=upper(trim(p.SG_UF)))""", [ano])
    data = "try_strptime(DT_GERACAO, '%d/%m/%Y')::DATE"
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
                if isinstance(valor, str):
                    valor = valor.strip()
                if valor == "-":  # convenção SIDRA: zero absoluto
                    valor = "0"
                if valor is None or not str(valor).isdigit():
                    raise ValueError(
                        f"Censo 9514: valor ausente ou inválido em {serie['localidade']['id']} "
                        f"(idade: {rotulo}; valor: {valor!r})")
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


def _converter_idades_sidra(dados, municipios):
    """Converte a resposta tabular da API SIDRA para a validação etária existente."""
    if not isinstance(dados, list) or not dados:
        raise ValueError("SIDRA 9514: resposta sem dados")
    resultados = {}
    for linha in dados:
        if linha.get('D1C') == 'Município (Código)':
            continue  # primeira linha contém os títulos das colunas
        if (linha.get('NC') != '6' or linha.get('D1C') not in municipios
            or linha.get('D2C') != '93' or linha.get('D3C') != '2022'
            or linha.get('D4C') != '6794' or linha.get('D6C') != '113635'):
            raise ValueError(f"SIDRA 9514: linha fora do recorte solicitado: {linha}")
        categoria = linha['D5C']
        resultado = resultados.setdefault(categoria, {
            'classificacoes': [{'id': '287', 'categoria': {categoria: linha['D5N']}}],
            'series': []})
        resultado['series'].append({'localidade': {'id': linha['D1C']},
                                    'serie': {'2022': linha['V']}})
    return [{'id': '93', 'resultados': list(resultados.values())}]


def _medias_sidra(uf, municipios, categorias, cache, avisos):
    """Mesma tabela 9514, outra API oficial, em lotes de até 50 municípios."""
    medias = {}
    for inicio in range(0, len(municipios), 50):
        lote = municipios[inicio:inicio + 50]
        url = (f"https://apisidra.ibge.gov.br/values/t/9514/n6/{','.join(lote)}"
               f"/v/93/p/2022/c2/6794/c287/{','.join(categorias)}/c286/113635")
        dados = _fonte_opcional(_cache_json, url,
            Path(cache) / 'sidra' / f'idades_2022_{uf}_{inicio // 50:03d}.json',
            avisos=avisos, rotulo=f'SIDRA idades 2022/{uf} lote {inicio // 50 + 1}')
        if dados is not None:
            validas = indicadores_idade(_converter_idades_sidra(dados, set(lote)))
            if set(validas) != set(lote):
                raise ValueError(f'SIDRA 9514: municípios ausentes no lote de {uf}')
            medias.update(validas)
    return medias


def enriquecer(con, ufs, anos, cache):
    """Atualiza o DER em transação. Falhas não publicam carga parcial no banco."""
    cache = Path(cache)
    ufs = sorted({u.upper() for u in ufs})
    if not ufs or set(ufs) - UF_CODIGOS.keys():
        raise ValueError("Informe UFs brasileiras válidas")
    avisos = []
    if not anos:
        raise ValueError("Informe pelo menos um ano")
    perfis = []
    for ano in sorted(set(anos)):
        nome = f"perfil_eleitorado_{ano}"
        url = f"https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/{nome}.zip"
        zip_path = cache / "zips" / f"{nome}.zip"
        if _fonte_opcional(baixar, url, zip_path, avisos=avisos,
                           rotulo=f"Perfil TSE {ano}") is None:
            continue
        arquivos, _ = extrair_por_uf(zip_path, cache / "raw", ano,
            {"perfil_eleitorado": "perfil_eleitorado_{ano}_{uf}"}, ufs)
        if not arquivos:
            arquivos, _ = extrair_nacional(zip_path, cache / "raw", ano,
                "perfil_eleitorado", "perfil_eleitorado_{ano}", ufs)
        if len(arquivos) != len(ufs):
            aviso = f"Perfil TSE {ano}: arquivos de {len(arquivos)}/{len(ufs)} UFs disponíveis"
            avisos.append(aviso)
            print(f"Aviso: {aviso}", flush=True)
        if arquivos:
            perfis.append((arquivos, ano, url))
    api = "https://servicodados.ibge.gov.br/api/v3/agregados"
    meta = _fonte_opcional(_cache_json, f"{api}/9514/metadados",
        cache / "ibge/9514_metadados.json", avisos=avisos, rotulo="Metadados IBGE 9514")
    classes = next(c for c in meta["classificacoes"] if c["id"] == 287) if meta else {"categorias": []}
    categorias = [str(c["id"]) for c in classes["categorias"]
                  if c["nome"] in ("Total", "Menos de 1 ano", "100 anos ou mais")
                  or re.fullmatch(r"\d+ anos?", c["nome"])]
    demografia = []
    for uf in ufs:
        local = f"localidades=N6[N3[{UF_CODIGOS[uf]}]]"
        url = (f"{api}/9514/periodos/2022/variaveis/93?{local}"
               f"&classificacao=2[6794]|287[{','.join(categorias)}]|286[113635]")
        # Cache da rota alternativa evita repetir uma consulta primária já falha.
        tem_sidra = any((cache / 'sidra').glob(f'idades_2022_{uf}_*.json'))
        dados_idades = _fonte_opcional(_cache_json, url, cache / f"ibge/idades_2022_{uf}.json",
            avisos=avisos, rotulo=f"IBGE idades 2022/{uf}") if categorias and not tem_sidra else None
        medias = indicadores_idade(dados_idades) if dados_idades is not None else {}
        if dados_idades is None and categorias:
            municipios = [r[0] for r in con.execute(
                'SELECT id_municipio FROM Municipio WHERE uf=? AND id_municipio IS NOT NULL ORDER BY id_municipio',
                [uf]).fetchall()]
            medias = _medias_sidra(uf, municipios, categorias, cache, avisos)
        indicadores = _fonte_opcional(_cache_json,
            f"{api}/9515/periodos/2022/variaveis/10612|10613?{local}",
            cache / f"ibge/indicadores_2022_{uf}.json", avisos=avisos,
            rotulo=f"IBGE indicadores 2022/{uf}")
        valores = defaultdict(dict)
        for variavel in indicadores or []:
            for resultado in variavel["resultados"]:
                for serie in resultado["series"]:
                    valor = serie["serie"]["2022"]
                    valores[str(serie["localidade"]["id"])][str(variavel["id"])] = float(valor)
        for municipio in medias.keys() | valores.keys():
            demografia.append((municipio, medias.get(municipio), valores[municipio].get("10613"),
                               valores[municipio].get("10612")))
        print(f"Demografia IBGE: {uf}, média em {len(medias)} municípios; "
              f"indicadores em {len(valores)} municípios", flush=True)
    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(f"CREATE TABLE IF NOT EXISTS Perfil_Eleitorado_Municipio ({PERFIL_DDL})")
        con.execute("ALTER TABLE Censo_Municipio ADD COLUMN IF NOT EXISTS idade_media_estimada DOUBLE")
        con.execute("ALTER TABLE Censo_Municipio ADD COLUMN IF NOT EXISTS metodo_idade_media VARCHAR")
        for arquivos, ano, url in perfis:
            carregar_perfil(con, arquivos, ano, ufs, url, substituir=True)
            faltam = con.execute("""SELECT count(*) FROM Municipio m
                WHERE uf IN (SELECT unnest(?)) AND NOT EXISTS (
                    SELECT 1 FROM Perfil_Eleitorado_Municipio p
                    WHERE p.id_municipio=m.id_municipio AND p.ano=?)""", [ufs, ano]).fetchone()[0]
            if faltam:
                aviso = f"Perfil {ano}: {faltam} municípios sem dados; carga dos disponíveis mantida"
                avisos.append(aviso)
                print(f"Aviso: {aviso}", flush=True)
        con.execute("CREATE OR REPLACE TEMP TABLE demografia_censo (id VARCHAR, media DOUBLE, mediana DOUBLE, envelhecimento DOUBLE)")
        if demografia:
            con.executemany("INSERT INTO demografia_censo VALUES (?,?,?,?)", demografia)
        faltam = con.execute("""SELECT count(*) FROM Municipio m WHERE uf IN (SELECT unnest(?))
            AND NOT EXISTS (SELECT 1 FROM demografia_censo d WHERE d.id=m.id_municipio)""", [ufs]).fetchone()[0]
        if faltam:
            aviso = f"Censo etário: {faltam} municípios sem novos dados; valores anteriores preservados"
            avisos.append(aviso)
            print(f"Aviso: {aviso}", flush=True)
        con.execute("""INSERT INTO Censo_Municipio (id_municipio, ano_referencia)
            SELECT d.id, 2022 FROM demografia_censo d JOIN Municipio m ON m.id_municipio=d.id
            ON CONFLICT DO NOTHING""")
        con.execute("""UPDATE Censo_Municipio c SET idade_media_estimada=coalesce(d.media,c.idade_media_estimada),
            idade_mediana=coalesce(d.mediana,c.idade_mediana),
            indice_envelhecimento=coalesce(d.envelhecimento,c.indice_envelhecimento),
            metodo_idade_media=CASE WHEN d.media IS NOT NULL THEN
                'SIDRA 9514/2022; média de idades completas; 100+ = 100; menor de 1 = 0'
                ELSE c.metodo_idade_media END
            FROM demografia_censo d WHERE c.id_municipio=d.id AND c.ano_referencia=2022""")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "avisos_ultima_carga.json").write_text(
        json.dumps({"ufs": ufs, "anos_solicitados": sorted(set(anos)),
                    "anos_perfil_disponiveis": [ano for _, ano, _ in perfis],
                    "avisos": avisos}, ensure_ascii=False, indent=2), encoding="utf-8")
