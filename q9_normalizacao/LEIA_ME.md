# Q9 — normalização e agrupamento das descrições de despesas

## O que foi entregue

- `q9_normalizacao.sql`: instalação independente no DuckDB/MotherDuck.
- `categorias_normalizadas.csv`: todas as 50.000 linhas do arquivo recebido, com descrição original, chave normalizada, rótulo padronizado, grupo sugerido, regras e necessidade de revisão.
- `resumo_exportacao.csv`: resultados por grupo e status somente no arquivo recebido.
- `resumo.json`: contagens e limites da análise.
- `gerar_normalizacao.py`: regras, aliases e gerador reproduzível, apenas biblioteca padrão Python.
- `testar_normalizacao.py`: teste integrado opcional com DuckDB.

## Instalação

1. No editor SQL do MotherDuck, selecione o banco e schema contendo `Despesa_Candidatura(id_despesa, id_candidatura, categoria, valor)`.
2. Abra `q9_normalizacao.sql` e execute o bloco inicial até `COMMIT;`. É necessário ter permissão para criar macro e views no schema selecionado.
3. Execute as consultas que aparecem depois do `COMMIT;`, individualmente.

Não é necessário executar o arquivo anterior de diagnóstico da Q9. A instalação não altera tabelas, não apaga despesas, não muda valores e não executa carga. Cria/substitui somente os cinco objetos `vw_q9_...` e a macro `q9_normalizar_categoria` definidos no SQL. Não foi executada no banco remoto.

## Objetos criados

- `vw_q9_regras_categorias`: regras e grupos analíticos explícitos.
- `vw_q9_aliases_categorias`: equivalências de rótulos, singular/plural e algumas variantes conhecidas.
- `vw_q9_categorias`: dimensão calculada com uma linha por descrição original, normalização e classificação.
- `vw_q9_despesas_normalizadas`: mesma granularidade da tabela de despesas, acrescida da classificação.
- `vw_q9_resumo_categorias`: valores e contagens por grupo e status.
- `q9_normalizar_categoria(texto)`: padroniza caixa, acentos, pontuação e espaços; não remove números de notas, datas ou medidas da descrição original.

Exemplo de inventário:

```sql
SELECT categoria_original, categoria_padronizada,
       grupo_despesa, status_classificacao, requer_revisao
FROM vw_q9_categorias
ORDER BY grupo_despesa, categoria_padronizada, categoria_original;
```

Exemplo de ranking (inclui sugestões não revisadas):

```sql
SELECT grupo_despesa, SUM(valor_contratado) AS valor_contratado
FROM vw_q9_resumo_categorias
GROUP BY grupo_despesa
ORDER BY valor_contratado DESC NULLS LAST;
```

## Normalização não é validação semântica

O campo mistura rótulos e descrições livres. Os grupos são uma proposta analítica, não categorias oficiais ou classificação jurídica do TSE.

- `ALIAS_EXPLICITO`: correspondência definida no dicionário. Não significa validação oficial. Alguns rótulos genéricos continuam com `requer_revisao=true`.
- `REGRA_TEXTUAL_REVISAR`: apenas um grupo foi detectado por expressão regular. Toda essa classificação deve ser conferida.
- `MULTIPLAS_CATEGORIAS`: mais de um grupo detectado. Valor integral preservado em “Mistos — revisar”, sem rateio ou duplicação.
- `SEM_REGRA`: não houve correspondência suficiente. A descrição permanece disponível para revisão.
- `AUSENTE`: descrição vazia ou marcador como `#NULO`. O valor é preservado; falta de descrição não significa valor zero.

Normalizar acentos e pontuação produziu 46.671 chaves preenchidas distintas a partir das 50.000 descrições. Essa redução é textual e não comprova que todos os rótulos de uma mesma chave representam serviços semanticamente idênticos. Números e detalhes continuam na chave; não há remoção geral de medidas, notas fiscais ou datas.

A classificação de publicidade aparece como `eh_publicidade_sugerida` e `modalidade_publicidade_sugerida`. TRUE sugere publicidade sob o conceito descrito pelas regras; FALSE indica despesas fora desse conceito estreito; NULL significa indefinido. Nenhum desses campos substitui revisão metodológica. Mobilização, militância e panfletagem ficam com publicidade indefinida para evitar decidir implicitamente o escopo da pergunta de pesquisa. “Facebook” isoladamente não comprova impulsionamento pago.

Se quiser incluir mobilização na propaganda, revise a regra `MOBILIZACAO` no gerador e regenere o SQL. Alterar uma regra muda propostas; não valida automaticamente descrições mistas ou sem regra.

## Cobertura e valores

A exportação tem exatamente 50.000 linhas e o último valor é R$ 10.671,52. Isso pode indicar um limite de exportação; não foi comprovado que ela inclua toda a base. Estatísticas dos CSVs e JSON referem-se somente a esse arquivo. As views aplicam as regras a todas as descrições presentes no banco selecionado, incluindo descrições novas.

O total recebido, arredondando cada valor exportado a centavos, é R$ 3.300.624.444,11. Isso não é uma afirmação sobre o total de todas as despesas no banco.

No arquivo recebido:

| Status | Descrições |
|---|---:|
| ALIAS_EXPLICITO | 317 |
| REGRA_TEXTUAL_REVISAR | 33.837 |
| MULTIPLAS_CATEGORIAS | 1.805 |
| SEM_REGRA | 14.039 |
| AUSENTE | 2 |

Os valores da tabela de despesas são contratados, não necessariamente pagos. A fonte já contém agregados por candidatura/categoria: registros não equivalem a notas fiscais ou pagamentos. Não some a coluna `candidaturas` entre categorias, pois uma pessoa/candidatura pode aparecer em vários grupos. Recalcule `COUNT(DISTINCT id_candidatura)` no recorte desejado.

A view de despesas preserva o `valor` original. Resumos somam apenas valores finitos convertíveis a DECIMAL(24,2). A conversão não recupera precisão perdida quando a pipeline armazenou DOUBLE. A conferência de totais usa a mesma conversão na fonte e no resultado.

## Desempenho

As expressões são avaliadas por chave distinta, com padrões constantes, antes da junção às despesas. A complexidade de classificação cresce com a quantidade de chaves e regras. Views comuns recalculam resultados; não são materializações. Para produção com muitos acessos, avalie transformar a dimensão em um catálogo persistido e versionado, atualizado pela pipeline, e cachear resumos no backend. Nenhuma alteração estrutural dessas foi feita no projeto.

## Reprodução e teste

Gerar novamente (JSON em lista ou NDJSON):

```bash
python gerar_normalizacao.py /caminho/export.json --saida ./resultado
```

Executar o teste integrado em memória:

```bash
uv run --with duckdb python testar_normalizacao.py /caminho/export.json
```

O teste foi executado com DuckDB 1.5.6. Verificou SQL e Python nas 50.000 descrições exportadas e em casos adicionais, somando 50.003 descrições distintas. Inclui conservação de linhas e valores, ausência de duplicação, ausentes, acentos, aliases, ambiguidades, zero, negativos, infinito, consultas de resumo e reexecução. O teste completo da versão otimizada levou cerca de 13 segundos neste ambiente; não é uma medição do serviço remoto.

O teste demonstra consistência técnica das regras. Não demonstra acurácia semântica validada manualmente, completude da exportação ou correção da carga original. Nenhuma publicação ou consulta autenticada ao MotherDuck foi executada.
