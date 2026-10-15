# DER completo: eleições, candidaturas e gastos

Este fluxo gera `dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb` a partir das
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
    pipeline_bdr_der_completo_v2.duckdb
```

Os ZIPs e CSVs são cacheáveis e podem ser reaproveitados. O banco operacional
é apagado ao final para evitar que uma carga parcial seja confundida com o DER.

## Execução

### Patrimônio dos candidatos

Para baixar os bens declarados no TSE entre 2018 e 2024:

```powershell
uv run python baixar_patrimonio.py --ufs CE MA MS RJ RN RS --anos 2018 2020 2022 2024
```

O resultado fica em `dados_bdr/saida/patrimonio_candidatos_2018_2024.duckdb`,
na tabela `Patrimonio_Candidato`. A fonte é a coleção `bem_candidato` do TSE;
cada linha representa um bem declarado e contém o valor, tipo, descrição,
eleição, UF e `SQ_CANDIDATO`.

### Publicar somente os gastos

Depois que o DER local tiver sido gerado, publique apenas a tabela
`Despesa_Candidatura`:

```powershell
$env:MOTHERDUCK_TOKEN = "SEU_TOKEN"
uv run python publicar_despesas.py --motherduck-db pipeline_bdr_despesas
```

Para substituir uma tabela já existente:

```powershell
uv run python publicar_despesas.py --motherduck-db pipeline_bdr_despesas --substituir
```

O comando aborta se a tabela local estiver vazia.

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
uv run python -c "import duckdb; c=duckdb.connect('dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb', read_only=True); print(c.sql('select ano, count(*) from Candidatura group by ano order by ano')); print(c.sql('select count(*) from Despesa_Candidatura'))"
```

As tabelas principais são `Eleicao`, `Candidato`, `Candidatura`,
`Resultado_Candidatura`, `Despesa_Candidatura`, `Cargo`,
`Votos_Partido_Municipio` e `Participacao_Eleitoral`.

## Despesas vazias no MotherDuck

`--publicar-teste` cria a carga inicial e interrompe se as tabelas já existem.
Quando o banco local já contém despesas e a tabela remota está vazia ou incompleta,
configure `MOTHERDUCK_TOKEN` no ambiente e execute, na pasta deste projeto:

```powershell
uv run python executar_der.py --atualizar-despesas
```

O comando usa `dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb`, envia somente
despesas ausentes e recalcula `Candidatura.gastos_campanha_total` para as candidaturas
envolvidas. A operação ocorre em uma transação; candidaturas ausentes ou despesas
com o mesmo ID e dados divergentes interrompem a atualização. Repetir o comando
não duplica despesas. Não é necessário baixar os arquivos novamente.

Para publicar as 11 tabelas em `pipeline_bdr_der_completo_v2` pela primeira vez:

```powershell
uv run python executar_der.py --publicar-teste --usuario-motherduck camillylarissa05
```

O comando confere as contagens de todas as tabelas após a publicação. A autenticação
usa `MOTHERDUCK_TOKEN`/`motherduck_token` quando configurado; caso contrário, abre o
login no navegador. `--usuario-motherduck` interrompe o envio se a conta autenticada
for diferente da informada. Confira também o usuário do notebook com
`SELECT current_user();` antes de comparar bancos com o mesmo nome.

O terminal informa o usuário da conexão e a contagem no destino antes da operação.
Após o commit, o banco local é desanexado e a contagem é conferida novamente em
`pipeline_bdr_der_completo_v2.main.Despesa_Candidatura`. Todas as consultas de destino
usam esse banco explicitamente. Se o terminal e o notebook exibirem contagens
diferentes, confira a conta/organização do token e do navegador e execute uma nova
consulta no notebook (resultados já exibidos não são prova de uma nova execução).

Confira no MotherDuck:

```sql
SELECT count(*) AS total
FROM pipeline_bdr_der_completo_v2.main.Despesa_Candidatura;
```
