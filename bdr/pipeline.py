"""Orquestra as etapas da pipeline da Questão 3: baixar -> carregar -> exportar."""
import json
from pathlib import Path

# pyrefly: ignore [missing-import]
import duckdb

from .boletins import extrair_boletim, planejar
from .config import ARQUIVOS_TSE_Q3, CDN_TSE
from .download import baixar
from .esquema import criar_tabelas
from .exportacao import exportar
from .extracao import destino_raw, extrair_por_uf
from .ibge import baixar_dados_ibge, carregar_dados_socioeconomicos, garantir_de_para_oficial
from .leitura import carregar_arquivo, criar_staging
from .transformacao import montar_tabelas
from .validacao import gerar_manifesto, imprimir_resumo


class Pastas:
    def __init__(self, base, rotulo):
        self.base = Path(base)
        self.zips = self.base / "zips"             # ZIPs de boletins, detalhe e fontes
        self.raw = self.base / "raw"               # CSVs e JSONs brutos extraídos das UFs
        self.fontes = self.base / "fontes"         # De-para e IDHM
        self.saida = self.base / "saida" / rotulo  # Banco, parquet e manifesto
        self.banco = self.saida / f"bdr_{rotulo}.duckdb"


def etapa_baixar(escopo, pastas, apagar_zips=False):
    """Baixa apenas os arquivos necessários para a Questão 3:

    1. De-para oficial TSE <-> IBGE de municípios (municipio_tse_ibge.zip)
    2. Dados socioeconômicos do IBGE (Localidades, População Censo 2022, PIB 2022)
    3. Detalhe da Votação / Comparecimento e Abstenção do TSE (detalhe_votacao_munzona)
    4. Boletins de Urna (TSE) para as UFs do membro nos anos 2022 e 2024 (1º e 2º turnos)
    """
    problemas = []
    ufs = escopo["ufs"]
    anos = escopo["anos"]

    # 1. De-para oficial TSE <-> IBGE
    print("\n[Fonte Oficial] Baixando correspondência município TSE <-> IBGE")
    try:
        csv_de_para = garantir_de_para_oficial(pastas.zips, pastas.fontes)
        print(f"     De-para pronto em {csv_de_para}")
    except Exception as e:
        print(f"     Aviso no de-para oficial: {e}")
        problemas.append(f"de-para oficial: {e}")

    # 2. Dados socioeconômicos do IBGE
    print(f"\n[IBGE] Consultando Localidades, População 2022 e PIB 2022 ({', '.join(ufs)})")
    try:
        arqs_ibge = baixar_dados_ibge(ufs, pastas.raw)
        print(f"     {len(arqs_ibge)} arquivo(s) do IBGE em cache/obtidos")
    except Exception as e:
        print(f"     Aviso nos dados do IBGE: {e}")
        problemas.append(f"IBGE: {e}")

    # 3. Detalhe da Votação / Comparecimento e Abstenção (TSE)
    print(f"\n[TSE] Baixando dados oficiais de Comparecimento e Abstenção ({', '.join(ufs)} | {anos})")
    info_det = ARQUIVOS_TSE_Q3["detalhe_votacao_munzona"]
    for ano in anos:
        nome_zip = info_det["zip"].format(ano=ano)
        url_det = f"{CDN_TSE}/{info_det['pasta']}/{nome_zip}.zip"
        zip_det = pastas.zips / f"{nome_zip}.zip"
        print(f"[{ano}] {nome_zip}.zip")
        try:
            status = baixar(url_det, zip_det)
            print(f"     ZIP: {status}")
            gerados, _ = extrair_por_uf(zip_det, pastas.raw, ano, info_det["partes"], ufs)
            print(f"     Extraídos para {', '.join(ufs)}: {', '.join(p.name for p in gerados) or 'Nenhum'}")
            if apagar_zips:
                zip_det.unlink(missing_ok=True)
        except Exception as e:
            print(f"     Aviso ao baixar comparecimento/abstenção ({ano}): {e}")
            problemas.append(f"detalhe_votacao_munzona {ano}: {e}")

    # 4. Boletins de Urna do TSE
    print(f"\n[TSE] Baixando e extraindo Boletins de Urna ({', '.join(ufs)} | {anos})")
    plano_boletins = planejar(ufs, anos, turnos=[1, 2])
    for recurso in plano_boletins:
        ano, turno, uf, nome = recurso["ano"], recurso["turno"], recurso["uf"], recurso["nome"]
        zip_path = pastas.zips / "boletim_urna" / str(ano) / f"{nome}.zip"
        csv_path = pastas.raw / "boletim_urna" / str(ano) / f"{turno}t" / f"boletim_urna_{ano}_{turno}t_{uf}.csv"
        print(f"[{ano}] {uf} - {turno}º turno")
        try:
            status = baixar(recurso["url"], zip_path)
            print(f"     ZIP: {status}")
            meta = extrair_boletim(zip_path, csv_path, recurso)
            print(f"     {meta['linhas']:,} linhas; {meta['secoes']:,} seções; {meta['municipios']} municípios")
            if apagar_zips:
                zip_path.unlink(missing_ok=True)
        except FileNotFoundError:
            print("     Arquivo não encontrado no portal do TSE")
            problemas.append(f"{nome}.zip não encontrado")
        except Exception as e:
            print(f"     ERRO: {e}")
            problemas.append(f"{ano}/{uf}/{turno}t: {e}")

    return problemas


def etapa_carregar(escopo, pastas, de_para=None):
    """Carrega dados no DuckDB e monta as tabelas do DER para a Questão 3."""
    pastas.saida.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(pastas.banco))
    criar_staging(con)
    criar_tabelas(con)

    registro, avisos = [], []

    # 1. Carrega dados socioeconômicos do IBGE e IDHM
    print("\nCarregando dados socioeconômicos (IBGE e IDHM)")
    carregar_dados_socioeconomicos(con, escopo["ufs"], pastas.raw, pastas.fontes)

    # 2. Carrega Comparecimento e Abstenção (detalhe_votacao_munzona) se disponível
    print("\nCarregando Comparecimento e Abstenção (TSE) em staging")
    for ano in escopo["anos"]:
        for uf in escopo["ufs"]:
            caminho_det = destino_raw(pastas.raw, "detalhe_votacao_munzona", ano, uf)
            if caminho_det.exists():
                linhas, avs = carregar_arquivo(con, "detalhe_votacao_munzona", ano, caminho_det)
                avisos.extend(avs)
                registro.append({"arquivo": "detalhe_votacao_munzona", "ano": ano,
                                 "uf": uf, "nome": caminho_det.name, "linhas": linhas})
                print(f"   {caminho_det.name:<48} {linhas:>12,} linhas")

    # 3. Carrega Boletins de Urna
    print("\nCarregando Boletins de Urna em staging")
    plano_boletins = planejar(escopo["ufs"], escopo["anos"], turnos=[1, 2])
    for recurso in plano_boletins:
        ano, turno, uf = recurso["ano"], recurso["turno"], recurso["uf"]
        csv_path = pastas.raw / "boletim_urna" / str(ano) / f"{turno}t" / f"boletim_urna_{ano}_{turno}t_{uf}.csv"
        if not csv_path.exists():
            aviso = f"faltando: {csv_path.name} (rode a etapa 'baixar')"
            avisos.append(aviso)
            print(f"   {aviso}")
            continue
        linhas, avs = carregar_arquivo(con, "boletim_urna", ano, csv_path)
        avisos.extend(avs)
        registro.append({"arquivo": "boletim_urna", "ano": ano, "turno": turno,
                         "uf": uf, "nome": csv_path.name, "linhas": linhas})
        print(f"   {csv_path.name:<48} {linhas:>12,} linhas")

    # 4. Determina o caminho do de-para
    de_para_caminho = None
    candidatos_de_para = [
        de_para,
        pastas.fontes / "municipio_tse_ibge.csv",
        pastas.base / "de_para_municipio.csv",
    ]
    for c in candidatos_de_para:
        if c and Path(c).exists() and Path(c).stat().st_size > 0:
            de_para_caminho = str(c)
            break

    print("\nMontando tabelas do DER da Questão 3")
    montar_tabelas(con, de_para_caminho)

    manifesto = gerar_manifesto(con, escopo, registro, avisos)
    (pastas.saida / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    imprimir_resumo(manifesto)
    con.close()
    return manifesto


def etapa_exportar(pastas):
    """Exporta as tabelas em Parquet e empacota com o manifesto em um ZIP para o Drive."""
    if not pastas.banco.exists():
        raise SystemExit(f"Banco não encontrado: {pastas.banco}. Rode a etapa 'carregar' antes.")
    con = duckdb.connect(str(pastas.banco), read_only=True)
    manifesto = json.loads((pastas.saida / "manifesto.json").read_text(encoding="utf-8"))
    zip_final = exportar(con, pastas.saida, manifesto)
    con.close()
    return zip_final
