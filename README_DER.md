# DER completo: eleições, candidaturas e gastos

Este fluxo gera `dados_bdr/saida/pipeline_bdr_der_completo_v2.duckdb` a partir das
fontes oficiais. O período histórico é 2002, 2004, ..., 2024 e o recorte padrão
é `CE MA MS RJ RN RS`.

Para gerar **um novo banco completo**, incluindo votos partidários e patrimônio
de 2018, 2020, 2022 e 2024, execute na raiz do projeto:

```powershell
uv run python executar_der.py --executar-completo --ufs CE MA MS RJ RN RS --q3-anos 2018 2020 2022 2024 --q10-anos 2002 2004 2006 2008 2010 2012 2014 2016 2018 2020 2022 2024 --saida dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb
```

Esse comando executa Q3, Q10, patrimônio e a montagem das 12 tabelas no mesmo
arquivo final. Não é necessário executar os scripts de download separadamente.
O caminho `v3` preserva o banco `v2` já existente. A saída é local; a publicação
no MotherDuck continua sendo uma ação separada.

Os votos nominais e de legenda vêm de `votacao_partido_munzona_{ano}.zip` nos
quatro anos. `votos_nominais` usa `QT_VOTOS_NOMINAIS_VALIDOS` e `votos_legenda`
usa `QT_TOTAL_VOTOS_LEG_VALIDOS`: legenda direta **mais** nominais convertidos
em legenda. Os votos anulados e anulados sub judice não entram nessas colunas.
Os valores são agregados por eleição, cargo, turno, partido e município, somando
as zonas e mantendo separados os anos e os turnos. Os BUweb de 2022/2024 continuam
alimentando a participação eleitoral de primeiro turno; seus votos não são
somados novamente aos da votação partidária.

Os bens vêm de `bem_candidato_{ano}.zip`, são preservados individualmente em
`Patrimonio_Candidato` e somados em `Candidatura.patrimonio`. A associação usa
ano, UF, código da eleição e sequencial. Para o segundo turno, a declaração é
reutilizada apenas se houver uma única eleição de origem para o sequencial.
Sem declaração correspondente, o patrimônio permanece `NULL`, não zero.
Os downloads são nacionais, mas só as UFs pedidas são carregadas. Não são criados
bancos finais separados por ano ou por patrimônio.

## Retomada e acompanhamento

Para retomar uma execução que já chegou a `Q10 transformando candidaturas, votos e despesas...`,
encerre o processo anterior com `Ctrl+C` e aguarde sua saída. Depois execute:

```powershell
uv run python executar_der.py --executar-completo --retomar-q10
```

Repita os mesmos valores de `--ufs`, `--q3-anos` e `--q10-anos` usados na carga
original, caso tenha personalizado o recorte. `executar_der2.py` também aceita
essa opção e usa o mesmo padrão de anos para Q3.

A retomada reutiliza Q3, verifica o staging completo de Q10 e refaz somente a
transformação e a construção do DER. A etapa de patrimônio reaproveita os ZIPs/CSVs
em cache ou baixa os que faltarem. Bancos Q3 anteriores à correção dos votos são
recusados: nesse caso execute sem `--retomar-q10`.
Uma carga interrompida antes de completar o staging é recusada. A transformação
usa uma transação: em caso de erro, suas alterações são revertidas. O staging
fica preservado até o banco final ser construído com sucesso; só então os bancos
operacionais são removidos. O banco final anterior é preservado até a substituição
pelo novo arquivo pronto.

Cada consulta da transformação mostra início e duração em segundos. As candidaturas
são normalizadas antes dos cruzamentos, cada CPF distinto é validado uma vez e os
cruzamentos de despesas separam os casos com e sem código de eleição.

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

A carga completa acima já inclui os bens de 2018 a 2024. O comando abaixo é
opcional e independente, somente para quem deseja um banco separado de bens:

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
uv run python -c "import duckdb; c=duckdb.connect('dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb', read_only=True); print(c.sql('select e.ano, sum(v.votos_nominais), sum(v.votos_legenda) from Votos_Partido_Municipio v join Eleicao e using(id_eleicao) group by e.ano order by e.ano')); print(c.sql('select ano, count(*), sum(valor_bem) from Patrimonio_Candidato group by ano order by ano'))"
```

As tabelas principais são `Eleicao`, `Candidato`, `Candidatura`,
`Resultado_Candidatura`, `Despesa_Candidatura`, `Cargo`,
`Votos_Partido_Municipio`, `Patrimonio_Candidato` e `Participacao_Eleitoral`.

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

Para publicar as 12 tabelas em `pipeline_bdr_der_completo_v2` pela primeira vez:

```powershell
uv run python executar_der.py --publicar-teste --usuario-motherduck camillylarissa05
```

Para publicar o arquivo `v3` com outro nome no MotherDuck:

```powershell
$env:MOTHERDUCK_TOKEN = "SEU_TOKEN"
uv run python executar_der.py --publicar-teste --saida dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb --motherduck-db pipeline_bdr_der_completo_v3
```

`--saida` escolhe o arquivo local; `--motherduck-db` escolhe o nome remoto.
Se o destino já contiver tabelas do DER, a publicação interrompe sem substituí-las.

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
