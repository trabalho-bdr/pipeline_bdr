# Relatório Real de Aquisição e Integração das Fotos Oficiais dos Candidatos

## 1. Síntese Executiva

A aquisição e integração das fotografias oficiais de candidatos do Tribunal Superior Eleitoral (TSE) para o recorte geográfico definido (**CE, MA, MS, RJ, RN e RS**) foi concluída com sucesso para todos os anos que possuem fotografias disponibilizadas oficialmente pelo TSE (2004 a 2026).

O processo seguiu estritamente as diretrizes de governança eleitoral: o banco DER permaneceu aberto exclusivamente em modo somente leitura (`read_only=True`), sem nenhuma alteração no MotherDuck ou nas tabelas da pipeline de dados eleitorais.

### Comparativo de Continuidade

| Métrica | Registro Anterior (Codex) | Estado Atual Final | Variação |
| :--- | :--- | :--- | :--- |
| **Pessoas Catalogadas (Escopo)** | 382.866 | **382.866** | Cobertura total das 6 UFs |
| **Fotos Principais Disponíveis** | 96.533 | **298.894** | **+202.361 (+209,6%)** |
| **Arquivos Físicos Validados em Disco** | ~120.000 | **302.805** | **+182.805 (+152,3%)** |
| **Chaves de Foto com Bloqueio Ambíguo** | 74 | **74** | Preservadas rigorosamente |
| **Uso de Foto Anterior (Fallback)** | Não relatado | **21** | Foto mais antiga válida utilizada |
| **Lotes Concluídos (Fotos)** | 2026, 2024, 2022 | **2004 a 2026 (todos os anos com fotos)** | Conclusão ampla |
| **Lote 2002** | Pendente | **Pacote Indisponível no TSE** | 0 recursos de fotos no Portal TSE |

---

## 2. Distribuição das Fotos Principais por Ano de Origem

A seleção prioriza a candidatura mais recente identificada de cada pessoa com imagem válida, inclusive candidaturas de 2026:

| Ano da Candidatura da Foto | Quantidade de Pessoas Atendidas | % do Total de Fotos Disponíveis |
| :---: | :---: | :---: |
| **2026** | 3.594 | 1,20% |
| **2024** | 89.059 | 29,80% |
| **2022** | 3.879 | 1,30% |
| **2020** | 78.318 | 26,20% |
| **2018** | 3.698 | 1,24% |
| **2016** | 58.701 | 19,64% |
| **2014** | 3.243 | 1,09% |
| **2012** | 55.993 | 18,73% |
| **2010** | 2.409 | 0,81% |
| **Total** | **298.894** | **100,0%** |

*Nota: Pessoas que concorreram em anos mais recentes dispensaram o download redundante de imagens históricas de 2008, 2006 ou 2004, preservando armazenamento e banda.*

---

## 3. Auditoria de Identidade e Bloqueio de Ambiguidades

Foram auditadas e mantidas bloqueadas exatamente **74 chaves físicas distintas de fotos** que apresentavam risco de atribuição indevida:

1. **Ano 2004 (57 chaves)**: Em 2004, a numeração sequencial de candidatos não era unificada em nível estadual pelo TSE, mas atribuída por município. Assim, candidatos diferentes de municípios distintos compartilhavam o mesmo sequencial numérico na mesma UF (ex.: `RJ10_div.jpg`), impossibilitando identificar univocamente a pessoa retratada.
2. **Ano 2012 (17 chaves)**: Em 2012, eleições suplementares posteriores (ex.: suplementares de 2013 e 2015 em CE, RN e RS) reutilizaram os mesmos sequenciais de candidaturas ordinárias de 2012 para pessoas distintas. Como o TSE disponibiliza um único arquivo para o sequencial (ex.: `CE60000001085_div.jpg`), a associação foi bloqueada com `CHAVE_FOTO_AMBIGUA`.

Nenhuma associação foi forçada por aproximação de nome, partido ou número de urna.

---

## 4. Estado da Cobertura por Ano e UF

* **2026, 2024, 2022, 2020, 2018, 2016, 2014, 2012, 2010, 2008, 2006, 2004**: Todas as 6 UFs (CE, MA, MS, RJ, RN, RS) com status `ok`.
* **2002**: O conjunto oficial `candidatos-2002` no Portal de Dados Abertos do TSE possui apenas arquivos de cadastro eleitoral (CSV), com zero recursos de fotos publicados. O sistema registrou auditavelmente `status = pacote_indisponivel` (`FileNotFoundError: Pacote de fotos não publicado no catálogo`).

---

## 5. Correções Realizadas

1. **Concorrência e Locks no SQLite (`OperationalError: database is locked`)**:
   - Adicionada função `comitar()` com backoff exponencial e retentativas em `bdr/fotos/aquisicao.py`.
   - Implementado mecanismo de retry com 10 tentativas para `gravar_imagem` e registros de cobertura.
   - Aumentado o `timeout` de 60s para 120s e o `busy_timeout` de 60000ms para 120000ms em `bdr/fotos/catalogo.py`.
2. **Estabilidade de Operação**:
   - Limpeza de arquivos parciais `.part` residuais e liberação do lock.
   - Garantida a execução com `--workers 2` com taxa zero de falhas em concorrência.

---

## 6. Verificação de Integração e Frontend

* **API**: Testados os endpoints `/api/candidatos/{id_candidato}/foto`, `/api/q9/candidatos`, `/api/q9/despesas` e `/api/q9/evolucao`.
  - Servindo imagens válidas com `Content-Type: image/jpeg` ou `image/png`, `Cache-Control: public, max-age=3600` e `ETag` SHA-256.
  - Retornando HTTP 404 sem cache para pessoas sem foto ou com associação bloqueada.
  - Exibição correta do ano da foto na Q9, inclusive quando mais recente que a eleição analisada (ex.: candidato em 2018 exibindo foto de 2026 ou 2024).
* **Testes Automatizados**:
  - `python -m unittest tests/test_fotos.py`: 31 testes executados, 100% aprovados.
  - `npm run test:q9`: 3 testes aprovados.
  - `npm run test:cores`: 5 testes aprovados.
  - `npm run build`: Build do TypeScript/Vite concluído sem erros.
