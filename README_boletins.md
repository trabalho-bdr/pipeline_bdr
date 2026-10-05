# Boletins de urna — RJ e RN, 2022 e 2024

`baixar_boletins.py` baixa os **oito arquivos BUweb oficiais do TSE**: dois anos × duas UFs × dois turnos. A rotina usa apenas a biblioteca padrão do Python (3.10 ou superior), sem exigir DuckDB ou pandas.

```powershell
python baixar_boletins.py
# Equivalente com o recorte explícito:
python baixar_boletins.py --ufs RJ RN --anos 2022 2024 --turnos 1 2
```

Outras opções:

```powershell
python baixar_boletins.py --listar                           # mostra os oito links
python baixar_boletins.py --ufs RN --anos 2024 --turnos 2     # um único recorte
python baixar_boletins.py --sem-download                     # reusa os ZIPs locais
python baixar_boletins.py --dir outra_pasta                  # muda a pasta base
```

Os downloads completos e os CSVs já extraídos são reutilizados. Em caso de erro, a rotina tenta os demais arquivos e termina com código de saída 1, registrando os problemas no manifesto. Execute novamente para completar o recorte. Arquivos parciais não são publicados como CSVs finais.

## Arquivos gerados

```text
dados_bdr/
  zips/boletim_urna/<ano>/bweb_<turno>t_<UF>_<data_publicacao>.zip
  raw/boletim_urna/<ano>/<turno>t/boletim_urna_<ano>_<turno>t_<UF>.csv
  raw/boletim_urna/<ano>/<turno>t/boletim_urna_<ano>_<turno>t_<UF>.json
  saida/boletins_RJ-RN/manifesto.json
```

Os CSVs estão em **UTF-8**, separados por **ponto e vírgula**. Todas as colunas e linhas do CSV original são preservadas; a rotina valida ano, UF e turno de cada linha. Cada JSON registra o link de origem, as colunas, o número de linhas, seções, municípios e os votos por cargo e tipo. O manifesto reúne os arquivos do recorte solicitado na última execução; o campo `completo` confirma se todos foram obtidos.

## Como interpretar

Uma linha do CSV corresponde a uma **opção de voto de um cargo dentro de um BU**, e não ao boletim inteiro. O arquivo identifica município (`CD_MUNICIPIO`), zona (`NR_ZONA`), seção (`NR_SECAO`), eleição (`CD_ELEICAO`), turno (`NR_TURNO`) e UF (`SG_UF`).

Para os resultados, use `CD_CARGO_PERGUNTA`, `DS_CARGO_PERGUNTA`, `NR_VOTAVEL`, `NM_VOTAVEL`, `DS_TIPO_VOTAVEL` e `QT_VOTOS`. Brancos, nulos, votos nominais e de legenda permanecem conforme aparecem na fonte. `NR_VOTAVEL` sozinho não identifica uma candidatura entre anos, municípios e cargos.

**Não some `QT_APTOS`, `QT_COMPARECIMENTO` ou `QT_ABSTENCOES` por linha**: esses valores se repetem para as opções de voto. Considere também `DS_SECOES_AGREGADAS` ao trabalhar com seções agregadas. O manifesto conta as seções identificadas por município, zona e seção nos BUs de cada ano/UF/turno, sem expandir as seções agregadas. Uma seção que registra mais de um `CD_ELEICAO` (eleições federal e estadual em 2022) é contada uma única vez.

Em 2022, os boletins incluem os cargos da eleição geral, inclusive presidente. Em 2024, incluem os cargos municipais; o segundo turno contém apenas os municípios que tiveram essa votação. Não é necessário `--incluir-br` para obter os votos de presidente nesses BUs por UF.

Esta rotina gera os arquivos de boletins. `executar.py` continua responsável pelo modelo relacional existente, baseado em resultados por município/zona; os BUs ainda não são importados para suas tabelas.

## Fontes oficiais

- [TSE — Resultados 2022 — Boletim de Urna](https://dadosabertos.tse.jus.br/dataset/resultados-2022-boletim-de-urna)
- [TSE — Resultados 2024 — Boletim de Urna](https://dadosabertos.tse.jus.br/dataset/resultados-2024-boletim-de-urna)

Os nomes de publicação estão em `bdr/config.py`, em `BOLETINS_TSE`. A pasta BUweb na CDN difere da pasta `odsele` dos demais conjuntos do projeto.

Verificação local:

```powershell
python -m unittest discover -s tests -v
```
