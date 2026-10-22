# Perfil do eleitorado e votação municipal

A inspeção da pipeline anterior encontrou votos municipais por partido, população,
PIB e IDHM, mas não o perfil do eleitorado. `Censo_Municipio.idade_mediana` e
`indice_envelhecimento` recebiam `NULL` na transformação do DER.

O fluxo DER (`executar_der.py` e `executar_der2.py`) agora inclui o enriquecimento
antes de concluir o banco. O fluxo antigo `executar.py`, que gera o esquema Q3
operacional, permanece independente; o painel consulta o DER.

## Dados acrescentados

O perfil vem do CDN oficial do TSE:
`https://cdn.tse.jus.br/estatistica/sead/odsele/perfil_eleitorado/perfil_eleitorado_{ano}.zip`.
Os cabeçalhos dos arquivos baixados de 2018/2020 usam `ANO_ELEICAO` e
`QT_ELEITORES_PERFIL`; os de 2022/2024 usam `AA_ELEICAO` e `QT_ELEITORES`.
A leitura normaliza ambos antes da validação e agregação. Nenhum ano ou total
é preenchido artificialmente para compensar uma coluna ausente.

- `Perfil_Eleitorado_Municipio`: município IBGE, ano eleitoral, faixa etária,
  gênero, escolaridade, quantidade, URL da fonte e data de geração. Zonas,
  estado civil e outras dimensões da fonte são somados; o cruzamento entre idade,
  gênero e escolaridade é preservado. Não misturar arquivos nacionais com suas
  cópias por UF, pois representam o mesmo eleitorado.
- `Censo_Municipio`, referência 2022: idade mediana e índice de envelhecimento
  oficiais da tabela SIDRA 9515; `idade_media_estimada`, calculada pela tabela
  9514, e `metodo_idade_media`.
- Consultas `q3_perfil_eleitorado` e `q3_demografia_partidos` no arquivo
  `bdr/consultas_q3.sql`. O join agrega o perfil antes de combiná-lo com os votos,
  evitando multiplicar a votação pelo número de faixas ou gêneros.
- Aba **Idade, gênero e escolaridade** no painel Streamlit: perfil de cada
  município, votação partidária e correlação municipal de Pearson.

A média estimada pondera idades completas de 0 a 99 anos e representa o grupo
aberto de 100 anos ou mais por 100. Não é uma média exata de microdados nem a
idade média do eleitorado. A mediana é outro indicador, obtido diretamente do
IBGE. Séries incompletas ou totais inconsistentes interrompem a carga.

## Reutilizar um DER local

```powershell
uv run python enriquecer_demografia.py --origem dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb --saida dados_bdr/saida/pipeline_bdr_der_demografia.duckdb
```

O comando preserva o original e só cria o nome final depois de concluir a carga.
Se houver falha, reutilize a cópia parcial com o mesmo comando e `--retomar`.
Os downloads ficam em `dados_bdr/demografia/`. A cobertura é conferida para todos
os municípios e anos solicitados. Fontes indisponíveis geram aviso e a carga segue
com os dados disponíveis. Dados inválidos ainda desfazem a transação.
Para consultar o resultado, informe o caminho de saída no campo **Banco DER**
do Streamlit. A publicação no MotherDuck é uma etapa separada.

Se `executar_der.py` terminou a Q10 e falhou somente no enriquecimento, use o DER
parcial já construído como origem para evitar refazer candidatos e despesas:

```powershell
uv run python enriquecer_demografia.py --origem dados_bdr/saida/pipeline_bdr_der_completo_v2.parcial.duckdb --saida dados_bdr/saida/pipeline_bdr_der_completo_v2_demografia.duckdb
```

O símbolo `-` nas contagens do SIDRA representa zero e é tratado como tal. Valores
ausentes ou suprimidos continuam interrompendo o cálculo, com município, idade e
valor original na mensagem de erro.

Erros temporários da API (como HTTP 500) são repetidos até quatro vezes, com
esperas progressivas. Se persistirem, a fonte é ignorada nesta execução e o banco
é concluído com os demais dados. Anos sem arquivo TSE também são ignorados.
Média, mediana e envelhecimento são buscados independentemente: a ausência de
uma tabela não impede aproveitar a outra. Indicadores novos ausentes ficam NULL,
e valores já carregados são preservados. O censo mantém a referência 2022;
não se copiam indicadores para preencher anos ausentes.

Confira `dados_bdr/demografia/avisos_ultima_carga.json` para os anos de perfil
disponíveis e as fontes que falharam. Para retomar uma execução interrompida,
use `--retomar` com os mesmos caminhos; não é necessário refazer a Q10.

## Como responder às perguntas

**Como a composição etária, especialmente os jovens, se relaciona com padrões
político-partidários?** Compare, no mesmo ano, cargo, turno e eleição, a proporção
municipal de eleitores de **16 a 24 anos** com a participação de cada partido nos
votos válidos. Esse corte respeita as faixas publicadas pelo TSE. O painel permite
alternar entre votos nominais + legenda e somente legenda, com denominadores
próprios. Para cargos sem votos de legenda, esse percentual fica ausente.

A correlação descreve se municípios com maior presença juvenil tendem a registrar
maior ou menor votação para o partido. Não identifica o voto dos jovens e não
demonstra causalidade. A amostra do gráfico inclui municípios onde o partido tem
votação registrada; ausência de linha não é imputada como zero. Informe o número
de municípios, ano, UF, cargo, turno e medida de votação ao relatar resultados.
Eleitores cadastrados não medem comparecimento de jovens às urnas.

**Quais características educacionais ou demográficas podem ser analisadas?**
O perfil permite examinar escolaridade, idade e gênero do eleitorado cadastrado
por município, incluindo seus cruzamentos. As consultas calculam percentuais de
analfabetos e de pessoas com superior completo; as demais escolaridades permanecem
na tabela detalhada. A idade média estimada, mediana, envelhecimento e população
descrevem a população residente em 2022. Escolaridade do eleitorado não deve ser
apresentada como escolaridade de toda a população; esse último objeto exigiria
uma fonte censitária educacional adicional.

Categorias não informadas são preservadas no total do eleitorado. Perfil ausente
fica `NULL`, nunca zero. Indicadores censitários de 2022, inclusive ao comparar
com eleições anteriores, são contexto de referência e não medições daquele ano
eleitoral. IDHM permanece com referência 2010 na análise.

Não é possível responder “em qual partido cada idade ou gênero votou” com essas
bases. O voto é secreto. Não são gerados votos estimados por grupo nem distribuída
a votação proporcionalmente à composição do eleitorado.

## Fontes

Se a API de Agregados falhar para a tabela 9514, a pipeline tenta automaticamente
a API oficial alternativa `https://apisidra.ibge.gov.br/values/t/9514/...`, com os
mesmos filtros de 2022, sexo total, idades simples e declaração total. A consulta
é dividida em lotes de até 50 municípios, salvos em `dados_bdr/demografia/sidra/`.
As contagens são submetidas à mesma conferência de cobertura e soma das idades.
É a mesma fonte censitária por outra rota de acesso. Não há substituição por
média do eleitorado ou por dados de outro ano.

- [TSE: eleitorado 2024](https://dadosabertos.tse.jus.br/dataset/eleitorado-2024),
  com arquivos equivalentes por ano em `perfil_eleitorado_{ano}.zip`.
- [TSE: estatísticas do eleitorado](https://www.tse.jus.br/eleicoes/estatisticas/estatisticas-de-eleitorado).
- [IBGE SIDRA 9514: população por idade e sexo](https://sidra.ibge.gov.br/tabela/9514).
- [IBGE SIDRA 9515: mediana e envelhecimento](https://sidra.ibge.gov.br/tabela/9515).
- [TSE: voto secreto](https://www.tse.jus.br/comunicacao/noticias/2024/Maio/glossario-eleitoral-explica-o-conceito-de-voto-secreto).
