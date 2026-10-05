"""Download e extração dos CSVs BUweb (Boletins de Urna) do TSE."""
import csv
import io
import json
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .config import BOLETINS_TSE, CDN_BOLETINS_TSE
from .download import baixar


def planejar(ufs, anos, turnos=None):
    """Monta a lista de recursos de boletins a baixar/extrair para as UFs e anos pedidos."""
    ufs = sorted(set(uf.upper() for uf in ufs))
    anos = sorted(set(anos))
    turnos = sorted(set(turnos or [1, 2]))
    if not ufs or not anos or not turnos:
        raise ValueError("Informe ao menos uma UF, um ano e um turno.")
    plano = []
    for ano in anos:
        for turno in turnos:
            if (ano, turno) not in BOLETINS_TSE:
                raise ValueError(f"Ano/turno não configurado: {ano}/{turno}.")
            for uf in ufs:
                nome = f"bweb_{turno}t_{uf}_{BOLETINS_TSE[ano, turno]}"
                plano.append({
                    "ano": ano,
                    "uf": uf,
                    "turno": turno,
                    "nome": nome,
                    "url": f"{CDN_BOLETINS_TSE}/eleicoes{ano}/buweb/{nome}.zip",
                    "fonte": f"https://dadosabertos.tse.jus.br/dataset/resultados-{ano}-boletim-de-urna",
                })
    return plano


def _gravar_json(destino, dados):
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".json.part")
    parcial.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    parcial.replace(destino)


def extrair_boletim(zip_path, destino, recurso):
    """Valida o recorte e extrai o CSV do Boletim de Urna em UTF-8.

    Uma linha no BU representa uma opção votável de um cargo na seção/urna.
    Aptos, comparecimento e abstenções se repetem para cada opção e não devem ser
    somados diretamente por linha sem deduplicação da seção.
    """
    destino = Path(destino)
    meta_path = destino.with_suffix(".json")
    if destino.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("url") == recurso.get("url") and meta.get("bytes_csv") == destino.stat().st_size:
                return meta
        except (ValueError, KeyError):
            pass

    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".csv.part")
    obrigatorias = (
        "ANO_ELEICAO", "NR_TURNO", "SG_UF", "CD_ELEICAO", "CD_MUNICIPIO",
        "NR_ZONA", "NR_SECAO", "CD_CARGO_PERGUNTA", "DS_CARGO_PERGUNTA",
        "DS_TIPO_VOTAVEL", "QT_VOTOS",
    )
    secoes, municipios, votos = set(), set(), Counter()
    linhas = 0
    try:
        with zipfile.ZipFile(zip_path) as z:
            alvos = [i for i in z.infolist() if not i.is_dir()
                     and Path(i.filename).name.lower() == f"{recurso['nome']}.csv".lower()]
            if len(alvos) != 1:
                raise ValueError(f"Esperado um CSV {recurso['nome']}.csv em {zip_path}.")
            with z.open(alvos[0]) as bruto, open(parcial, "w", encoding="utf-8", newline="") as saida:
                leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1", newline=""), delimiter=";")
                cabecalho = next(leitor, [])
                indices = {c.strip().upper(): i for i, c in enumerate(cabecalho)}
                faltantes = set(obrigatorias) - indices.keys()
                if faltantes:
                    raise ValueError(f"Colunas ausentes no BU: {', '.join(sorted(faltantes))}")
                escritor = csv.writer(saida, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
                escritor.writerow(cabecalho)
                chave_secao = [indices[c] for c in ("CD_MUNICIPIO", "NR_ZONA", "NR_SECAO")]
                for linha in leitor:
                    if len(linha) != len(cabecalho):
                        raise ValueError(f"Linha {leitor.line_num}: quantidade de campos inválida.")
                    if (int(linha[indices["ANO_ELEICAO"]]) != recurso["ano"]
                            or int(linha[indices["NR_TURNO"]]) != recurso["turno"]
                            or linha[indices["SG_UF"]].upper() != recurso["uf"]):
                        raise ValueError(f"Linha {leitor.line_num}: dados fora do recorte solicitado.")
                    qt_votos = int(linha[indices["QT_VOTOS"]])
                    if qt_votos < 0:
                        raise ValueError(f"Linha {leitor.line_num}: quantidade de votos negativa.")
                    escritor.writerow(linha)
                    linhas += 1
                    secoes.add(tuple(linha[i] for i in chave_secao))
                    municipios.add(linha[indices["CD_MUNICIPIO"]])
                    votos[(linha[indices["CD_CARGO_PERGUNTA"]],
                           linha[indices["DS_CARGO_PERGUNTA"]],
                           linha[indices["DS_TIPO_VOTAVEL"]])] += qt_votos
                    if linhas % 500_000 == 0:
                        print(f"     {linhas:,} linhas processadas", flush=True)
        if not linhas:
            raise ValueError("O boletim está vazio.")
        parcial.replace(destino)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise

    meta = dict(recurso, csv=str(destino), bytes_csv=destino.stat().st_size,
                linhas=linhas, secoes=len(secoes), municipios=len(municipios),
                colunas=cabecalho, encoding="utf-8", separador=";",
                votos_por_cargo_tipo=[{"codigo_cargo": cd, "cargo": cargo,
                                      "tipo_voto": tipo, "votos": total}
                                     for (cd, cargo, tipo), total in sorted(votos.items())])
    _gravar_json(meta_path, meta)
    return meta


def obter_boletins(plano, base="dados_bdr", sem_download=False):
    """Executa o download e a extração da lista de boletins do plano."""
    base = Path(base)
    rotulo = "boletins_" + "-".join(sorted({r["uf"] for r in plano}))
    manifesto_path = base / "saida" / rotulo / "manifesto.json"
    manifesto = {"gerado_em": datetime.now(timezone.utc).isoformat(),
                 "arquivos": [], "problemas": [], "completo": False}
    for recurso in plano:
        ano, turno, uf, nome = (recurso[c] for c in ("ano", "turno", "uf", "nome"))
        zip_path = base / "zips" / "boletim_urna" / str(ano) / f"{nome}.zip"
        csv_path = base / "raw" / "boletim_urna" / str(ano) / f"{turno}t" / f"boletim_urna_{ano}_{turno}t_{uf}.csv"
        print(f"[{ano}] {uf} - {turno}º turno", flush=True)
        try:
            if sem_download:
                if not zip_path.exists():
                    raise FileNotFoundError(f"ZIP em cache não encontrado: {zip_path}")
            else:
                print(f"     ZIP: {baixar(recurso['url'], zip_path)}", flush=True)
            meta = extrair_boletim(zip_path, csv_path, recurso)
            manifesto["arquivos"].append(meta)
            print(f"     {meta['linhas']:,} linhas; {meta['secoes']:,} seções; "
                  f"{meta['municipios']} municípios\n     {csv_path}", flush=True)
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, EOFError) as e:
            erro = f"{ano}/{uf}/{turno}t: {e}"
            manifesto["problemas"].append(erro)
            print(f"     ERRO: {erro}", flush=True)
        _gravar_json(manifesto_path, manifesto)
    manifesto["completo"] = len(manifesto["arquivos"]) == len(plano) and not manifesto["problemas"]
    _gravar_json(manifesto_path, manifesto)
    return manifesto_path, manifesto
