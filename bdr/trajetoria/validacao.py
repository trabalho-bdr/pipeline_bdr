"""Valida cobertura, chaves e vínculos da trajetória eleitoral."""

import json
from datetime import datetime


def validar(con, escopo, arquivos):
    anos = [r[0] for r in con.execute("SELECT DISTINCT ano FROM candidatura ORDER BY ano").fetchall()]
    cobertura = con.execute("""
        SELECT ano, count(*) candidaturas, count(DISTINCT uf) ufs,
               count(DISTINCT id_candidato) candidatos
        FROM candidatura GROUP BY ano ORDER BY ano
    """).fetchall()
    duplicadas = con.execute("""
        SELECT count(*) FROM (
            SELECT id_candidatura FROM candidatura GROUP BY id_candidatura HAVING count(*) > 1
        )
    """).fetchone()[0]
    obrigatorios = con.execute("""
        SELECT count(*) FROM candidatura
        WHERE id_candidato IS NULL OR ano IS NULL OR cd_eleicao IS NULL
           OR cd_cargo IS NULL OR uf IS NULL
    """).fetchone()[0]
    sem_resultado = con.execute("""
        SELECT count(*) FROM candidatura c LEFT JOIN resultado_candidatura r USING (id_candidatura)
        WHERE r.id_candidatura IS NULL
    """).fetchone()[0]
    situacao_ausente = con.execute("""
        SELECT count(*) FROM resultado_candidatura
        WHERE situacao_final IS NULL OR trim(situacao_final) = ''
    """).fetchone()[0]
    votos_negativos = con.execute(
        "SELECT count(*) FROM resultado_candidatura WHERE votos < 0"
    ).fetchone()[0]
    ambiguos = con.execute(
        "SELECT count(*) FROM candidato WHERE identidade_ambigua"
    ).fetchone()[0]
    contagens = {
        t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("candidato", "candidatura", "resultado_candidatura", "cargo")
    }
    problemas = []
    faltantes = sorted(set(escopo["anos"]) - set(anos))
    if faltantes:
        problemas.append("anos sem candidaturas: " + ", ".join(map(str, faltantes)))
    for ano, _, qtd_ufs, _ in cobertura:
        if qtd_ufs < len(escopo["ufs"]):
            problemas.append(f"{ano}: somente {qtd_ufs} de {len(escopo['ufs'])} UFs")
    if duplicadas:
        problemas.append(f"{duplicadas} candidaturas duplicadas")
    if obrigatorios:
        problemas.append(f"{obrigatorios} candidaturas sem vínculo obrigatório")
    if sem_resultado:
        problemas.append(f"{sem_resultado} candidaturas sem resultado")
    if situacao_ausente:
        problemas.append(f"{situacao_ausente} resultados sem situação final")
    if votos_negativos:
        problemas.append(f"{votos_negativos} resultados com votos negativos")
    return {
        "questao": "Q10 - Trajetória eleitoral dos candidatos",
        "rotulo": escopo["rotulo"],
        "ufs": escopo["ufs"],
        "anos": escopo["anos"],
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "tabelas": contagens,
        "cobertura": [
            {"ano": a, "candidaturas": n, "ufs": u, "candidatos": c}
            for a, n, u, c in cobertura
        ],
        "validacoes": {
            "duplicidades": duplicadas,
            "vinculos_obrigatorios_ausentes": obrigatorios,
            "sem_resultado": sem_resultado,
            "situacao_final_ausente": situacao_ausente,
            "votos_negativos": votos_negativos,
            "identidades_ambiguas": ambiguos,
        },
        "arquivos": arquivos,
        "problemas": problemas,
        "completo": not problemas,
    }


def imprimir(manifesto):
    print("\n" + "=" * 64)
    print("VALIDAÇÃO DA TRAJETÓRIA ELEITORAL")
    print("=" * 64)
    for linha in manifesto["cobertura"]:
        print(
            f"{linha['ano']}: {linha['candidaturas']:,} candidaturas | "
            f"{linha['candidatos']:,} candidatos | {linha['ufs']} UFs"
        )
    for tabela, qtd in manifesto["tabelas"].items():
        print(f"{tabela:<26} {qtd:>12,}")
    if manifesto["problemas"]:
        print("\nPENDÊNCIAS:")
        for problema in manifesto["problemas"]:
            print(f"- {problema}")
    else:
        print("\nTodas as validações obrigatórias passaram.")


def salvar(manifesto, caminho):
    caminho.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
