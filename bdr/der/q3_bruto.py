"""Carga operacional Q3 diretamente dos ZIPs BUweb e das fontes IBGE/TSE."""

import csv
import io
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import duckdb

from bdr.boletins import planejar
from bdr.download import baixar
from bdr.extracao import extrair_por_uf
from bdr.esquema import criar_tabelas
from bdr.ibge import baixar_dados_ibge, carregar_dados_socioeconomicos, garantir_de_para_oficial
from bdr.transformacao import _aplicar_de_para
from .idhm import preparar_csv_idhm


def _numero(valor):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return 0


def _valor(linha, colunas, nome):
    indice = colunas.get(nome)
    return linha[indice].strip() if indice is not None and indice < len(linha) else ""


def _lit(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def _ident(valor):
    return '"' + str(valor).replace('"', '""') + '"'


def _campo(colunas, *nomes, padrao="NULL"):
    for nome in nomes:
        if nome in colunas:
            return f"nullif(trim({_ident(colunas[nome])}), '')"
    return padrao


def _carregar_votacao_partido(con, caminho, ano_esperado=None, ufs_esperadas=None):
    """Votos válidos oficiais de 2018–2024; legenda inclui nominais convertidos."""
    fonte = f"read_csv({_lit(Path(caminho).resolve().as_posix())}, delim=';', quote='\"', escape='\"', header=true, all_varchar=true)"
    colunas = {r[0].upper(): r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {fonte}").fetchall()}
    obrigatorias = {"ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_ELEICAO",
                   "CD_CARGO", "CD_MUNICIPIO", "NR_PARTIDO", "SG_PARTIDO"}
    if obrigatorias - colunas.keys():
        raise ValueError(f"Colunas de votação ausentes: {sorted(obrigatorias - colunas.keys())}")
    if not ({"QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS"} & colunas.keys()):
        raise ValueError(f"Coluna de votos nominais ausente em {caminho}")
    if not ({"QT_TOTAL_VOTOS_LEG_VALIDOS", "QT_VOTOS_LEGENDA_VALIDOS", "QT_VOTOS_LEGENDA"} & colunas.keys()):
        raise ValueError(f"Coluna de votos de legenda ausente em {caminho}")
    ano = _campo(colunas, "ANO_ELEICAO", "AA_ELEICAO")
    turno = _campo(colunas, "NR_TURNO", "NUM_TURNO", padrao="'1'")
    uf = _campo(colunas, "SG_UF", "SIGLA_UF")
    eleicao = _campo(colunas, "CD_ELEICAO", "CODIGO_ELEICAO")
    cargo = _campo(colunas, "CD_CARGO", "CODIGO_CARGO")
    nome_cargo = _campo(colunas, "DS_CARGO", "DESCRICAO_CARGO")
    municipio = _campo(colunas, "CD_MUNICIPIO", "CODIGO_MUNICIPIO", "SG_UE")
    nome_municipio = _campo(colunas, "NM_MUNICIPIO", "NOME_MUNICIPIO")
    partido = _campo(colunas, "NR_PARTIDO", "NUMERO_PARTIDO")
    sigla = _campo(colunas, "SG_PARTIDO", "SIGLA_PARTIDO")
    nome_partido = _campo(colunas, "NM_PARTIDO", "NOME_PARTIDO")
    nominais = _campo(colunas, "QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS")
    if "QT_TOTAL_VOTOS_LEG_VALIDOS" in colunas:
        legenda = _campo(colunas, "QT_TOTAL_VOTOS_LEG_VALIDOS")
    else:
        diretos = _campo(colunas, "QT_VOTOS_LEGENDA_VALIDOS", "QT_VOTOS_LEGENDA")
        convertidos = _campo(colunas, "QT_VOTOS_NOM_CONVR_LEG_VALIDOS",
                             "QT_VOTOS_NOMINAIS_CONVR_LEG", padrao="'0'")
        legenda = f"(try_cast({diretos} AS BIGINT) + try_cast({convertidos} AS BIGINT))"
    invalidos = con.execute(f"""SELECT count(*) FROM {fonte}
        WHERE try_cast({nominais} AS BIGINT) IS NULL OR try_cast({nominais} AS BIGINT)<0
           OR try_cast({legenda} AS BIGINT) IS NULL OR try_cast({legenda} AS BIGINT)<0""").fetchone()[0]
    if invalidos:
        raise ValueError(f"{invalidos} linhas com votos inválidos em {caminho}")
    if ano_esperado is not None:
        recorte = con.execute(f"SELECT DISTINCT try_cast({ano} AS INTEGER), upper({uf}) FROM {fonte}").fetchall()
        if not recorte or any(a != ano_esperado or u not in ufs_esperadas for a, u in recorte):
            raise ValueError(f"Votação fora do recorte em {caminho}")
    con.execute(f"""
        INSERT INTO municipio (cod_tse, id_municipio, nome, uf, regiao)
        SELECT lpad(trim({municipio}), 5, '0'), NULL, max({nome_municipio}), max(upper({uf})), NULL
        FROM {fonte}
        WHERE regexp_matches(trim({municipio}), '^[0-9]+$')
        GROUP BY 1
        ON CONFLICT DO NOTHING
    """)
    con.execute(f"""
        INSERT INTO partido (numero, sigla, nome)
        SELECT try_cast({partido} AS INTEGER), upper({sigla}), max({nome_partido})
        FROM {fonte}
        WHERE try_cast({partido} AS INTEGER) > 0 AND {sigla} IS NOT NULL
        GROUP BY 1, 2
        ON CONFLICT DO NOTHING
    """)
    con.execute(f"""
        INSERT INTO eleicao (ano, cd_eleicao, turno, ds_eleicao, dt_eleicao)
        SELECT try_cast({ano} AS INTEGER), {eleicao}, try_cast({turno} AS SMALLINT),
               max({_campo(colunas, 'DS_ELEICAO', 'DESCRICAO_ELEICAO')}),
               min(coalesce(try_strptime({_campo(colunas, 'DT_ELEICAO', 'DATA_ELEICAO')}, '%d/%m/%Y')::DATE,
                            try_strptime({_campo(colunas, 'DT_ELEICAO', 'DATA_ELEICAO')}, '%Y-%m-%d')::DATE))
        FROM {fonte}
        GROUP BY 1, 2, 3
        ON CONFLICT DO NOTHING
    """)
    con.execute(f"""
        INSERT INTO votos_partido_municipio
        SELECT try_cast({ano} AS INTEGER), {eleicao}, {cargo}, max({nome_cargo}),
               try_cast({turno} AS SMALLINT), try_cast({partido} AS INTEGER), upper({sigla}),
               lpad(trim({municipio}), 5, '0'), NULL,
               sum(coalesce(try_cast({nominais} AS BIGINT), 0)),
               sum(coalesce(try_cast({legenda} AS BIGINT), 0))
        FROM {fonte}
        WHERE try_cast({partido} AS INTEGER) > 0
          AND regexp_matches(trim({municipio}), '^[0-9]+$')
        GROUP BY 1, 2, 3, 5, 6, 7, 8
    """)


def _carregar_bu(con, zip_path, recurso, carregar_votos=True):
    ano, uf = recurso["ano"], recurso["uf"]
    eventos_voto = {2022: {"544", "546"}, 2024: {"619"}}[ano]
    evento_participacao = {2022: "544", 2024: "619"}[ano]
    secoes = {}
    votos = defaultdict(lambda: [0, 0])
    municipios, partidos, eleicoes = {}, {}, {}
    linhas = 0
    with ZipFile(zip_path) as zip_file:
        membros = [m for m in zip_file.infolist()
                   if Path(m.filename).name.lower() == f"{recurso['nome']}.csv".lower()]
        if len(membros) != 1:
            raise ValueError(f"CSV BUweb esperado não encontrado em {zip_path}")
        with zip_file.open(membros[0]) as arquivo:
            leitor = csv.reader(io.TextIOWrapper(arquivo, encoding="latin-1", newline=""), delimiter=";")
            cabecalho = [x.strip().upper() for x in next(leitor)]
            colunas = {nome: i for i, nome in enumerate(cabecalho)}
            obrigatorias = {"ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_ELEICAO",
                           "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "QT_APTOS",
                           "QT_COMPARECIMENTO", "QT_ABSTENCOES", "CD_CARGO_PERGUNTA",
                           "NR_PARTIDO", "CD_TIPO_VOTAVEL", "QT_VOTOS"}
            if obrigatorias - colunas.keys():
                raise ValueError(f"Colunas BUweb ausentes: {sorted(obrigatorias - colunas.keys())}")
            for linha in leitor:
                linhas += 1
                if (_valor(linha, colunas, "ANO_ELEICAO") != str(ano)
                    or _valor(linha, colunas, "NR_TURNO") != "1"
                    or _valor(linha, colunas, "SG_UF").upper() != uf):
                    raise ValueError(f"BUweb fora do escopo em {zip_path}: linha {linhas}")
                evento = _valor(linha, colunas, "CD_ELEICAO")
                if evento not in eventos_voto:
                    continue
                cod_mun = _valor(linha, colunas, "CD_MUNICIPIO").zfill(5)
                if not cod_mun.isdigit():
                    continue
                municipios[cod_mun] = _valor(linha, colunas, "NM_MUNICIPIO") or municipios.get(cod_mun)
                eleicoes[evento] = (_valor(linha, colunas, "DS_ELEICAO"),
                                     _valor(linha, colunas, "DT_PLEITO"))
                if evento == evento_participacao:
                    chave_secao = (cod_mun, _valor(linha, colunas, "NR_ZONA"),
                                   _valor(linha, colunas, "NR_SECAO"))
                    atual = (_numero(_valor(linha, colunas, "QT_APTOS")),
                             _numero(_valor(linha, colunas, "QT_COMPARECIMENTO")),
                             _numero(_valor(linha, colunas, "QT_ABSTENCOES")))
                    anterior = secoes.get(chave_secao, (0, 0, 0))
                    secoes[chave_secao] = tuple(max(a, b) for a, b in zip(anterior, atual))
                if not carregar_votos:
                    continue
                partido = _valor(linha, colunas, "NR_PARTIDO")
                sigla = _valor(linha, colunas, "SG_PARTIDO").upper()
                if not partido.isdigit() or int(partido) <= 0 or not sigla:
                    continue
                numero = int(partido)
                partidos[(numero, sigla)] = _valor(linha, colunas, "NM_PARTIDO")
                cargo = _valor(linha, colunas, "CD_CARGO_PERGUNTA")
                nome_cargo = _valor(linha, colunas, "DS_CARGO_PERGUNTA")
                chave = (ano, evento, cargo, nome_cargo, 1, numero, sigla, cod_mun)
                tipo = _valor(linha, colunas, "CD_TIPO_VOTAVEL")
                if tipo == "1":
                    votos[chave][0] += _numero(_valor(linha, colunas, "QT_VOTOS"))
                elif tipo == "4":
                    votos[chave][1] += _numero(_valor(linha, colunas, "QT_VOTOS"))
    if not secoes or (carregar_votos and not votos):
        raise ValueError(f"BUweb sem participação ou votos: {uf}/{ano}")
    con.executemany("INSERT INTO municipio VALUES (?,NULL,?,?,NULL) ON CONFLICT DO NOTHING",
                    [(cod, nome, uf) for cod, nome in municipios.items()])
    if carregar_votos:
        con.executemany("INSERT INTO partido VALUES (?,?,?) ON CONFLICT DO NOTHING",
                        [(n, sigla, nome) for (n, sigla), nome in partidos.items()])
    con.executemany("""INSERT INTO eleicao VALUES (?,?,1,?,try_strptime(?,'%d/%m/%Y')::DATE)
                    ON CONFLICT DO NOTHING""",
                    [(ano, evento, nome, data) for evento, (nome, data) in eleicoes.items()])
    if carregar_votos:
        con.executemany("""INSERT INTO votos_partido_municipio
                        VALUES (?,?,?,?,?,?,?,?,NULL,?,?)""",
                        [(*chave, *total) for chave, total in votos.items()])
    por_municipio = defaultdict(lambda: [0, 0, 0])
    for (cod, _zona, _secao), valores in secoes.items():
        totais = por_municipio[cod]
        for i in range(3):
            totais[i] += valores[i]
    con.executemany("""INSERT INTO participacao_eleitoral VALUES
                    (?,?,1,?,NULL,?,?,?,?)""",
                    [(ano, evento_participacao, cod, aptos, comp, abst,
                      abst / aptos if aptos else None)
                     for cod, (aptos, comp, abst) in por_municipio.items()])
    print(f"Q3 {uf}/{ano}: {linhas:,} linhas BUweb processadas", flush=True)


def processar(ufs, anos, banco, trabalho, planilhas_idhm="planilhas",
             csv_idhm="dados_bdr/fontes/idhm.csv"):
    banco, trabalho = Path(banco), Path(trabalho)
    banco.parent.mkdir(parents=True, exist_ok=True)
    if banco.exists():
        raise FileExistsError(f"Banco operacional já existe: {banco}")
    trabalho.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(banco))
    try:
        criar_tabelas(con)
        if not anos or set(anos) - {2018, 2020, 2022, 2024}:
            raise ValueError("Q3 aceita somente 2018, 2020, 2022 e 2024")
        for ano in sorted(set(anos)):
            nome_zip = f"votacao_partido_munzona_{ano}"
            zip_path = trabalho / "zips" / f"{nome_zip}.zip"
            url = f"https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_partido_munzona/{nome_zip}.zip"
            baixar(url, zip_path)
            partes = {"votacao_partido_munzona": f"votacao_partido_munzona_{{ano}}_{{uf}}"}
            arquivos, _ = extrair_por_uf(zip_path, trabalho / "raw", ano, partes, ufs)
            esperados = {f"{nome_zip}_{uf}.csv".lower() for uf in ufs}
            if {Path(a).name.lower() for a in arquivos} != esperados:
                raise ValueError(f"Arquivos de votação incompletos para {ano}")
            for arquivo in arquivos:
                _carregar_votacao_partido(con, arquivo, ano, ufs)
            print(f"Q3 {ano}: votos válidos nominais e de legenda carregados", flush=True)
            zip_path.unlink()
        con.execute("""CREATE TABLE metadados_votacao AS
            SELECT 'votacao_partido_munzona:validos_com_convertidos:v1' fonte""")
        anos_bu = [ano for ano in anos if ano in (2022, 2024)]
        if anos_bu:
            for recurso in planejar(ufs, anos_bu, turnos=[1]):
                zip_path = trabalho / "zips" / f"{recurso['nome']}.zip"
                baixar(recurso["url"], zip_path)
                _carregar_bu(con, zip_path, recurso, carregar_votos=False)
                zip_path.unlink()  # ZIP temporário já processado com sucesso
        raw = trabalho / "raw"
        fontes = trabalho / "fontes"
        baixar_dados_ibge(ufs, raw)
        de_para = garantir_de_para_oficial(trabalho / "zips", fontes)
        idhm = preparar_csv_idhm(fontes, planilhas_idhm, csv_idhm)
        if idhm is None:
            print("IDHM: planilhas/CSV local ausente; campo ficará NULL", flush=True)
        carregar_dados_socioeconomicos(con, ufs, raw, fontes)
        _aplicar_de_para(con, de_para)
        con.execute("""UPDATE municipio m SET nome=coalesce(i.nome,m.nome), regiao=i.regiao
            FROM stg_ibge_municipio i WHERE m.id_municipio=i.id_municipio""")
        for tabela in ("votos_partido_municipio", "participacao_eleitoral"):
            con.execute(f"""UPDATE {tabela} t SET id_municipio=m.id_municipio
                FROM municipio m WHERE t.cod_tse_municipio=m.cod_tse""")
        sem = con.execute("SELECT count(*) FROM municipio WHERE id_municipio IS NULL").fetchone()[0]
        if sem:
            raise ValueError(f"{sem} municípios sem correspondência TSE-IBGE")
        con.execute("""INSERT INTO censo_municipio
            SELECT i.id_municipio,2022,i.populacao,i.pib,
                 i.pib/nullif(i.populacao,0),
                 (SELECT max(h.idhm) FROM stg_idhm h
                  WHERE h.id_municipio=i.id_municipio)
            FROM stg_ibge_censo i JOIN municipio m USING(id_municipio)""")
        if idhm is not None:
            con.execute("""INSERT INTO censo_municipio
                SELECT h.id_municipio,2010,NULL,NULL,NULL,max(h.idhm)
                FROM stg_idhm h JOIN municipio m USING(id_municipio)
                WHERE h.idhm BETWEEN 0 AND 1
                GROUP BY h.id_municipio""")
        zip_de_para = trabalho / "zips" / "municipio_tse_ibge.zip"
        if zip_de_para.is_file():
            zip_de_para.unlink()
    finally:
        con.close()
    return banco
