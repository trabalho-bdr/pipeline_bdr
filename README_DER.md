# DER completo: eleições, candidaturas e gastos

Este fluxo gera `dados_bdr/saida/pipeline_bdr_der_completo.duckdb` a partir das
fontes oficiais. O período histórico é 2002, 2004, ..., 2024 e o recorte padrão
é `CE MA MS RJ RN RS`.

## Fontes

- `consulta_cand`: todas as candidaturas publicadas por eleição, UF, cargo e turno.
- `votacao_candidato_munzona`: votos nominais por candidatura.
- Prestação de contas: o catálogo oficial do TSE é consultado em
  `https://dadosabertos.tse.jus.br/dataset/prestacao-de-contas-eleitorais-{ano}`.
  O recurso de **prestação de contas de candidatos** é preferido; os arquivos
  de `despesas_contratadas_candidatos` alimentam `Despesa_Candidatura` e
  `gastos_campanha_total`.

Quando um ano não possui publicação de prestação de contas, candidaturas e
resultados continuam sendo carregados e o aviso aparece no terminal e no
manifesto. Nenhum gasto é inventado.

## Organização dos arquivos

```text
dados_bdr/
  trabalho_der/
    q10_brutos/
      zips/<recurso>/
      raw/<recurso>/<recurso>_<ano>/<recurso>_<ano>_<UF>.csv
    q3_brutos/
  saida/
    pipeline_bdr_der_completo.duckdb
```

Os ZIPs e CSVs são cacheáveis e podem ser reaproveitados. O banco operacional
é apagado ao final para evitar que uma carga parcial seja confundida com o DER.

## Execução

Para baixar somente as despesas contratadas, sem carregar candidaturas, votos ou
criar banco DuckDB:

```powershell
uv run python baixar_despesas.py --ufs CE MA MS RJ RN RS --anos 2018 2020 2022 2024
```

Os CSVs ficam em `dados_bdr/trabalho_der/q10_brutos/raw/despesas_contratadas_candidatos/`.
Esse comando aceita somente anos até 2024; as despesas de 2026 não são baixadas.

Teste primeiro um ano e uma UF:

```powershell
uv run python executar_der.py --executar-completo --ufs RJ --q10-anos 2022 2024
```

Carga histórica completa do recorte padrão:

```powershell
uv run python executar_der.py --executar-completo
```

Para outro recorte, informe as UFs explicitamente. Para conferir o resultado:

```powershell
uv run python -c "import duckdb; c=duckdb.connect('dados_bdr/saida/pipeline_bdr_der_completo.duckdb', read_only=True); print(c.sql('select ano, count(*) from Candidatura group by ano order by ano')); print(c.sql('select count(*) from Despesa_Candidatura'))"
```

As tabelas principais são `Eleicao`, `Candidato`, `Candidatura`,
`Resultado_Candidatura`, `Despesa_Candidatura`, `Cargo`,
`Votos_Partido_Municipio` e `Participacao_Eleitoral`.