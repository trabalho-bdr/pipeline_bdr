"""Exporta as tabelas históricas em Parquet reconstruível."""

import json
from pathlib import Path

from .esquema import TABELAS_TRAJETORIA


def exportar(con, pasta, manifesto):
    pasta = Path(pasta)
    parquet = pasta / "parquet"
    parquet.mkdir(parents=True, exist_ok=True)
    tabelas = list(TABELAS_TRAJETORIA) + ["eleicao", "partido", "municipio"]
    existentes = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    for tabela in tabelas:
        if tabela not in existentes:
            continue
        destino = (parquet / f"{tabela}.parquet").as_posix().replace("'", "''")
        con.execute(f"COPY {tabela} TO '{destino}' (FORMAT parquet, COMPRESSION zstd)")
    (pasta / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return parquet
