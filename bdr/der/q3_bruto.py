"""Carga operacional Q3 diretamente dos ZIPs BUweb e das fontes IBGE/TSE."""

import csv
import io
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

import duckdb

from bdr.boletins import planejar
from bdr.download import baixar
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


def _carregar_bu(con, zip_path, recurso):
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
    if not secoes or not votos:
        raise ValueError(f"BUweb sem participação ou votos: {uf}/{ano}")
    con.executemany("INSERT INTO municipio VALUES (?,NULL,?,?,NULL) ON CONFLICT DO NOTHING",
                    [(cod, nome, uf) for cod, nome in municipios.items()])
    con.executemany("INSERT INTO partido VALUES (?,?,?) ON CONFLICT DO NOTHING",
                    [(n, sigla, nome) for (n, sigla), nome in partidos.items()])
    con.executemany("""INSERT INTO eleicao VALUES (?,?,1,?,try_strptime(?,'%d/%m/%Y')::DATE)
                    ON CONFLICT DO NOTHING""",
                    [(ano, evento, nome, data) for evento, (nome, data) in eleicoes.items()])
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
        for recurso in planejar(ufs, anos, turnos=[1]):
            zip_path = trabalho / "zips" / f"{recurso['nome']}.zip"
            baixar(recurso["url"], zip_path)
            _carregar_bu(con, zip_path, recurso)
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
                   i.pib/nullif(i.populacao,0),NULL
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
