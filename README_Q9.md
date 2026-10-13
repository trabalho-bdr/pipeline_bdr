# Questão 9 — Publicidade e Propaganda Eleitoral no DER

Este documento descreve a integração da **Questão 9 (Q9)** à pipeline de Banco de Dados Relacional (BDR).

---

## 1. Pergunta de Pesquisa

> **Questão 9:**  
> *"Em quais tipos de publicidade e propaganda eleitoral os candidatos concentram seus gastos de campanha?"*

A implementação permite analisar detalhadamente:
- A categoria original da despesa informada pelo TSE (`DS_ORIGEM_DESPESA`).
- O grupo analítico de publicidade (`DIGITAL`, `IMPRESSOS`, `AUDIOVISUAL`, `SONORA`, `EVENTOS`, `OUTROS`).
- Valores absolutos (nominais em R$) e percentuais relativos dos gastos.
- Desagregações por candidatura, cargo, partido, Unidade Federativa e ano eleitoral.
- Preservação do detalhamento individual das despesas contratadas sem aglutinação arbitrária.

---

## 2. Recorte Temporal e Geográfico

- **Anos:** 2018, 2020, 2022 e 2024.
- **Estados (UFs):** CE, MA, MS, RJ, RN e RS.
- **Configuração:** O escopo temporal e geográfico da Q9 é desacoplado do escopo de Q3 e Q10, podendo ser configurado diretamente via argumentos da CLI (`--q9-anos` e `--q9-ufs`).

---

## 3. Fontes de Dados e Padrões de URL

A investigação nos servidores oficiais do TSE revelou a estrutura real dos arquivos de prestação de contas de candidatos:

| Recurso | Padrão de URL Oficial | Arquivos Internos |
| :--- | :--- | :--- |
| **Prestação de Contas Candidatos (Principal)** | `https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/prestacao_de_contas_eleitorais_candidatos_{ano}.zip` | `despesas_contratadas_candidatos_{ano}_{UF}.csv` |
| **Despesas Contratadas (Fallback)** | `https://cdn.tse.jus.br/estatistica/sead/odsele/despesas_contratadas_candidatos/despesas_contratadas_candidatos_{ano}.zip` | `despesas_contratadas_candidatos_{ano}_{UF}.csv` |

> **Nota:** A URL legada `despesas_contratadas_candidatos_{ano}.zip` retorna código HTTP 404 para anos recentes no CDN do TSE, enquanto `prestacao_de_contas_eleitorais_candidatos_{ano}.zip` está 100% ativa e disponível para 2018 (~302 MB), 2020 (~1.25 GB), 2022 (~548 MB) e 2024 (~1.35 GB). O módulo `bdr/der/q9_bruto.py` gerencia o download com cache local em `dados_bdr/trabalho_der/q9_brutos/zips/`.

---

## 4. Normalização de Cabeçalhos e Aliases (2018 a 2024)

Entre 2018 e 2024, foram identificadas variações na nomenclatura dos campos da prestação de contas. A pipeline suporta todas as variações mapeadas:

| Campo Padronizado | Aliases Suportados no TSE |
| :--- | :--- |
| `ano` | `AA_ELEICAO`, `ANO_ELEICAO`, `ANO` |
| `turno` | `ST_TURNO`, `NR_TURNO`, `NUM_TURNO` |
| `tipo_prestacao_contas` | `TP_PRESTACAO_CONTAS`, `TIPO_PRESTACAO_CONTAS`, `DS_TP_PRESTACAO_CONTAS` |
| `dt_prestacao_contas` | `DT_PRESTACAO_CONTAS`, `DATA_PRESTACAO_CONTAS` |
| `cd_eleicao` | `CD_ELEICAO`, `CODIGO_ELEICAO` |
| `uf` | `SG_UF`, `SIGLA_UF` |
| `sq_candidato` | `SQ_CANDIDATO`, `SEQUENCIAL_CANDIDATO` |
| `sq_despesa` | `SQ_DESPESA`, `SEQUENCIAL_DESPESA`, `ID_DESPESA` |
| `dt_despesa` | `DT_DESPESA`, `DATA_DESPESA` |
| `origem_despesa` | `DS_ORIGEM_DESPESA`, `DESCRICAO_ORIGEM_DESPESA`, `DS_TIPO_DESPESA` |
| `descricao_despesa` | `DS_DESPESA`, `DESCRICAO_DESPESA` |
| `valor_contratado` | `VR_DESPESA_CONTRATADA`, `VALOR_DESPESA_CONTRATADA` |

Valores monetários são convertidos a partir da pontuação decimal brasileira para `DECIMAL(18,2)`. Valores em branco ou ausentes são preservados como `NULL` (não convertidos compulsoriamente em 0.00).

---

## 5. Modelagem Relacional no DER

Duas novas entidades principais e uma tabela de auditoria foram incorporadas ao DER:

```
  ┌─────────────────┐       1:N       ┌────────────────────────┐       N:1       ┌──────────────────────┐
  │   Candidatura   │ ◄───────────────┤    Despesa_Campanha    ├───────────────► │  Categoria_Despesa   │
  └─────────────────┘                 └────────────────────────┘                 └──────────────────────┘
                                                  │
                                                  │ (despesas não vinculadas)
                                                  ▼
                                      ┌────────────────────────┐
                                      │   Despesa_Rejeitada    │
                                      └────────────────────────┘
```

### 5.1. `Categoria_Despesa`
- `id_categoria_despesa VARCHAR PRIMARY KEY` — Hash MD5 determinístico da categoria normalizada (`CATEGORIA|<NOME>`).
- `origem_despesa VARCHAR UNIQUE` — Categoria original textual informada na prestação de contas do TSE.
- `grupo_publicidade VARCHAR` — Agrupamento analítico (`IMPRESSOS`, `DIGITAL`, `AUDIOVISUAL`, `SONORA`, `EVENTOS`, `OUTROS`, `NAO_PUBLICIDADE`, `NAO_CLASSIFICADO`).
- `eh_publicidade BOOLEAN` — Indicador booleano que discrimina se a despesa é voltada à publicidade eleitoral ou a despesas operacionais/administrativas.

### 5.2. `Despesa_Campanha`
- `id_despesa VARCHAR PRIMARY KEY` — Hash MD5 determinístico composto por `ano`, `sq_candidato`, `sq_despesa` (ou hash do registro).
- `id_candidatura VARCHAR NOT NULL REFERENCES Candidatura(id_candidatura)`.
- `id_categoria_despesa VARCHAR NOT NULL REFERENCES Categoria_Despesa(id_categoria_despesa)`.
- `ano INTEGER`, `uf VARCHAR`, `cd_eleicao VARCHAR`, `sq_candidato VARCHAR`, `sequencial_despesa_tse VARCHAR`, `turno SMALLINT`.
- `data_despesa DATE`, `descricao_despesa VARCHAR`, `valor_contratado DECIMAL(18,2)`, `tipo_prestacao_contas VARCHAR`.

### 5.3. `Despesa_Rejeitada` (Auditoria)
- Registra despesas cuja correspondência com a candidatura não foi inequívoca (motivos: `CANDIDATO_NAO_ENCONTRADO` ou `CORRESPONDENCIA_AMBIGUA`).

---

## 6. Regras de Classificação e De-Para

O módulo `bdr/der/q9_classificacao.py` implementa o mapeamento explícito e auditável:

| Categoria TSE (`origem_despesa`) | Grupo Analítico | `eh_publicidade` |
| :--- | :--- | :---: |
| Publicidade por materiais impressos | `IMPRESSOS` | `True` |
| Publicidade por adesivos | `IMPRESSOS` | `True` |
| Publicidade por jornais e revistas | `IMPRESSOS` | `True` |
| Despesa com Impulsionamento de Conteúdos | `DIGITAL` | `True` |
| Impulsionamento de conteúdos | `DIGITAL` | `True` |
| Criação e inclusão de páginas na internet | `DIGITAL` | `True` |
| Produção de programas de rádio, televisão ou vídeo | `AUDIOVISUAL` | `True` |
| Produção de jingles, vinhetas e slogans | `SONORA` | `True` |
| Publicidade por carros de som | `SONORA` | `True` |
| Eventos de promoção da candidatura / Comícios | `EVENTOS` | `True` |
| Combustíveis e lubrificantes | `NAO_PUBLICIDADE` | `False` |
| Despesas com pessoal | `NAO_PUBLICIDADE` | `False` |
| Atividades de militância e mobilização de rua | `NAO_PUBLICIDADE` | `False` |
| Serviços advocatícios / contábeis / terceiros | `NAO_PUBLICIDADE` | `False` |
| Encargos financeiros e taxas bancárias | `NAO_PUBLICIDADE` | `False` |
| Locação de veículos e bens móveis/imóveis | `NAO_PUBLICIDADE` | `False` |

---

## 7. Estratégia de Deduplicação e Vínculo com Candidaturas

1. **Deduplicação de Despesas:**  
   Em caso de duplicidade do identificador oficial `sq_despesa` para o mesmo candidato (frequente entre prestações parciais e finais), a pipeline prioriza a prestação `Final`, seguida por `Retificadora` e por data mais recente de prestação de contas, impedindo a sobrecontagem de valores.

2. **Vínculo Unívoco com Candidaturas:**  
   - Candidatos com exatamente 1 candidatura no banco têm correspondência direta por `(ano, sq_candidato)`.
   - Candidatos que disputaram o **segundo turno** possuem duas candidaturas em `Candidatura`. A despesa é desambiguada comparando o `turno` declarado na despesa com o `turno` da candidatura.
   - Casos com turno nulo ou ambíguo que coincidam com mais de uma candidatura são desviados para `Despesa_Rejeitada` com `CORRESPONDENCIA_AMBIGUA`, garantindo que **nenhuma despesa seja duplicada ou vinculada arbitrariamente**.

3. **Compatibilidade com `Candidatura.publicidade_propaganda`:**  
   O atributo pré-existente `publicidade_propaganda` na tabela `Candidatura` é atualizado a partir da soma estrita de `Despesa_Campanha` onde `eh_publicidade = true`, mantendo 100% de compatibilidade com consultas e painéis de Q10.

---

## 8. Como Executar

### 8.1. Execução Completa (Q3 + Q10 + Q9)

Executa de ponta a ponta desde os dados brutos e gera o banco final consolidado:

```powershell
uv run python executar_der.py --executar-completo
```

Com parâmetros opcionais de recorte:

```powershell
uv run python executar_der.py --executar-completo --q9-anos 2018 2020 2022 2024 --q9-ufs CE MA MS RJ RN RS
```

### 8.2. Executar Somente a Questão 9

Executa exclusivamente a carga e vinculação de despesas sobre um banco DER já construído, de maneira idempotente e sem tocar nas tabelas das demais questões:

```powershell
uv run python executar_der.py --somente-q9
```

### 8.3. Publicar Incrementalmente no MotherDuck

Publica apenas as tabelas `Categoria_Despesa`, `Despesa_Campanha` e `Despesa_Rejeitada` em um banco remoto já existente, validando a integridade das chaves estrangeiras com a tabela `Candidatura` remota:

```powershell
uv run python executar_der.py --publicar-q9 --banco-remoto pipeline_bdr_der_completo
```

### 8.4. Executar os Testes Automatizados

```powershell
uv run pytest
```

---

## 9. Consultas Analíticas (`bdr/consultas_q9.sql`)

O arquivo `bdr/consultas_q9.sql` contém 8 consultas analíticas desenvolvidas para responder à Pergunta 9:
1. `q9_gastos_por_categoria_original`: Totais nominais por categoria oficial TSE.
2. `q9_gastos_por_grupo_analitico`: Totais e percentuais por grupo (`DIGITAL`, `IMPRESSOS`, etc.).
3. `q9_participacao_percentual_categorias`: Participação de cada categoria no total de publicidade.
4. `q9_evolucao_modalidades_por_ano`: Comparativo temporal de modalidades (2018 a 2024).
5. `q9_distribuicao_modalidades_por_uf`: Distribuição regional por Estado (CE, MA, MS, RJ, RN, RS).
6. `q9_gastos_candidato_cargo_partido`: Análise de concentração por candidato, cargo e legenda.
7. `q9_concentracao_financeira`: Ranking e percentual acumulado das principais categorias.
8. `q9_nao_classificados_e_pendencias`: Relatório de auditoria de pendências e registros rejeitados.
