"""Exporta as tabelas do membro em Parquet + manifesto e empacota num ZIP para o Drive."""
import json
import shutil
from pathlib import Path

from .esquema import TABELAS


def exportar(con, pasta_saida, manifesto):
    pasta_saida = Path(pasta_saida)
    pasta_pq = pasta_saida / "parquet"
    if pasta_pq.exists():
        shutil.rmtree(pasta_pq)
    pasta_pq.mkdir(parents=True)
    for tabela in TABELAS:
        destino = (pasta_pq / f"{tabela}.parquet").as_posix().replace("'", "''")
        con.execute(f"COPY {tabela} TO '{destino}' (FORMAT parquet)")
    (pasta_saida / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # O ZIP leva só parquet + manifesto (o .duckdb fica local; é reconstruível).
    tmp = pasta_saida / "_pacote"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(pasta_pq, tmp / "parquet")
    shutil.copy(pasta_saida / "manifesto.json", tmp / "manifesto.json")
    zip_final = shutil.make_archive(str(pasta_saida.parent / f"{manifesto['rotulo']}_para_drive"),
                                    "zip", root_dir=tmp)
    shutil.rmtree(tmp)
    return Path(zip_final)
