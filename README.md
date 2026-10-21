# Pipeline BDR — Questão 3

Fotos oficiais por pessoa: veja [aquisição, retomada, API e implantação](README_fotos.md) e os [resultados da execução](RESULTADO_fotos.md).

Pipeline de extração, transformação, carga (ETL), validação e consolidação de dados eleitorais e socioeconômicos para responder à **Questão 3** do projeto da disciplina de Banco de Dados Relacional (BDR).

---

## 1. Objetivo

> **Questão 3:**  
> *"Como características socioeconômicas dos municípios se relacionam com a distribuição dos votos entre partidos e com a taxa de abstenção?"*

A pipeline permite analisar a relação empírica entre indicadores estruturais dos municípios brasileiros (população, PIB, PIB per capita e IDHM) com a votação partidária e o comportamento do eleitorado (comparecimento e abstenção).

---

## 2. Escopo Temporal e Geográfico

- **Escopo temporal:** Eleições gerais de **2022** e eleições municipais de **2024** (1º e 2º turnos).
- **Escopo por membro:** Cada membro da equipe é responsável por processar e gerar os dados de exatamente **2 Unidades da Federação (UFs)**.

### Divisão dos Membros

| Membro | UF 1 | UF 2 | Descrição |
| :---: | :---: | :---: | :--- |
| **1** | `AC` | `AL` | *(Configurável pelo grupo em `bdr/config.py`)* |
| **2** | `MA` | `SE` | Maranhão e Sergipe |
| **3** | `RJ` | `RN` | Rio de Janeiro e Rio Grande do Norte |
| **4** | `PB` | `PI` | *(Configurável pelo grupo em `bdr/config.py`)* |

> Para alterar a divisão do grupo, edite o dicionário `MEMBROS` em `bdr/config.py`.

---

## 3. Fontes de Dados e Padrões de URL

Para evitar sobrecarga de rede, tempo e disco, a pipeline baixa **exclusivamente** os arquivos indispensáveis para a Questão 3. Não são baixados dados desnecessários (como consulta_cand, prestação de contas, perfil do eleitorado, bens ou vagas).

| Fonte | Descrição | Padrão de URL / Origem |
| :--- | :--- | :--- |
| **TSE — Boletim de Urna (BUweb)** | Votos nominais e de legenda no nível de urna/seção por partido e cargo. | `https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ano}/buweb/bweb_{turno}t_{UF}_{data_pub}.zip` |
| **TSE — Comparecimento e Abstenção (Detalhe da Votação)** | Totais oficiais de eleitorado apto, comparecimento, abstenção, brancos e nulos por município/zona. | `https://cdn.tse.jus.br/estatistica/sead/odsele/detalhe_votacao_munzona/detalhe_votacao_munzona_{ano}.zip` |
| **TSE — Correspondência TSE <-> IBGE** | De-para oficial dos códigos municipais de 5 dígitos do TSE e de 7 dígitos do IBGE. | `https://cdn.tse.jus.br/estatistica/sead/odsele/municipio_tse_ibge/municipio_tse_ibge.zip` |
| **IBGE — Localidades API (v1)** | Cadastro oficial dos municípios por UF, nomes padronizados e macrorregiões geográficas. | `https://servicodados.ibge.gov.br/api/v1/localidades/estados/{UF}/municipios` |
| **IBGE — Censo 2022 (SIDRA 4709)** | População residente apurada no Censo Demográfico 2022. | `https://servicodados.ibge.gov.br/api/v3/agregados/4709/periodos/2022/variaveis/93?localidades=N6[N3[{cod_uf}]]` |
| **IBGE — PIB Municipal (SIDRA 5938)** | PIB a preços correntes de 2022 (convertido de Mil R$ para R$). | `https://servicodados.ibge.gov.br/api/v3/agregados/5938/periodos/2022/variaveis/37?localidades=N6[N3[{cod_uf}]]` |
| **Atlas Brasil / PNUD / IPEA — IDHM** | Índice de Desenvolvimento Humano Municipal (referência histórica de 2010). | `dados_bdr/fontes/idhm.csv` *(arquivo local documentado)* |

---

## 4. Dados Gerados (Tabelas do DER)

A pipeline popula 6 tabelas relacionais em DuckDB e as exporta em formato Parquet:

1. **`municipio`**
   - Chave primária: `cod_tse`
   - Atributos: `cod_tse` (código TSE 5 dígitos), `id_municipio` (código IBGE oficial 7 dígitos), `nome`, `uf`, `regiao`.
2. **`eleicao`**
   - Chave primária: `(ano, cd_eleicao, turno)`
   - Atributos: `ano`, `cd_eleicao`, `turno`, `ds_eleicao`, `dt_eleicao`. Distingue as eleições e turnos sem misturar cargos.
3. **`partido`**
   - Chave primária: `(numero, sigla)`
   - Atributos: `numero`, `sigla`, `nome`.
4. **`votos_partido_municipio`**
   - Chave primária: `(ano, cd_eleicao, cd_cargo, turno, numero_partido, cod_tse_municipio)`
   - Atributos: `ano`, `cd_eleicao`, `cd_cargo`, `cargo`, `turno`, `numero_partido`, `sigla_partido`, `cod_tse_municipio`, `id_municipio`, `votos_nominais`, `votos_legenda`.
   - Granularidade: ano + eleição + cargo + turno + partido + município. Separa rigorosamente votos nominais de votos de legenda.
5. **`participacao_eleitoral`**
   - Chave primária: `(ano, cd_eleicao, turno, cod_tse_municipio)`
   - Atributos: `ano`, `cd_eleicao`, `turno`, `cod_tse_municipio`, `id_municipio`, `eleitorado_apto`, `comparecimento`, `abstencoes`, `taxa_abstencao`.
   - Derivação: `taxa_abstencao = abstencoes / eleitorado_apto`. Os dados são deduplicados por seção/urna antes de agregar para município, evitando qualquer multiplicação indevida.
6. **`censo_municipio`**
   - Chave primária: `(id_municipio, ano_referencia)`
   - Atributos: `id_municipio`, `ano_referencia`, `populacao`, `pib`, `pib_per_capita`, `idhm`.
   - Multi-ano: indicadores de 2022 (população, PIB e PIB per capita) e histórico de 2010 (IDHM) são preservados com seus respectivos `ano_referencia`, sem forçar dados temporais distintos na mesma linha.

---

## 5. Fluxo da Pipeline

```
              FONTES OFICIAIS
       (TSE BUweb, TSE de-para, IBGE, IDHM)
                       │
                       ▼
                    DOWNLOAD
   (apenas o necessário para a Q3, com cache)
                       │
                       ▼
                      RAW
   (dados brutos por UF/ano em UTF-8)
                       │
                       ▼
                    STAGING
   (tabelas stg_* com mapeamento tolerante a layout)
                       │
                       ▼
                  TRANSFORMAÇÃO
   (deduplicação de seção, agregação partidária, de-para)
                       │
                       ▼
               TABELAS NORMALIZADAS
    (municipio, eleicao, partido, votos_partido_municipio,
      participacao_eleitoral, censo_municipio)
                       │
                       ▼
                    VALIDAÇÃO
   (11 verificações obrigatórias de integridade e consistência)
                       │
                       ▼
                    EXPORTAÇÃO
     (Parquet + manifesto.json -> membroN_para_drive.zip)
```

---

## 6. Como Executar (com uv)

### Instalação e sincronização do ambiente:
```bash
uv sync
```

### 1. Teste rápido de uma UF em 2024:
```bash
uv run python executar.py --ufs RJ --anos 2024
```

### 2. Execução completa do recorte de um membro:
```bash
uv run python executar.py --membro 3
```

### 3. Execução apenas de download:
```bash
uv run python executar.py --membro 3 --etapas baixar
```

### 4. Reutilização de arquivos locais (sem novo download):
```bash
uv run python executar.py --membro 3 --etapas carregar exportar
```

### 5. Consolidação de todos os membros:
```bash
uv run python juntar.py \
    dados_bdr/saida/membro1_para_drive.zip \
    dados_bdr/saida/membro2_para_drive.zip \
    dados_bdr/saida/membro3_para_drive.zip \
    dados_bdr/saida/membro4_para_drive.zip \
    --saida dados_bdr/bdr_consolidado.duckdb
```

---

## 7. Como Cada Membro Trabalha

1. **Clonar/Puxar o repositório:**
   ```bash
   git clone <url-do-repositorio> && cd load_BDR-main
   ```
2. **Sincronizar as dependências:**
   ```bash
   uv sync
   ```
3. **Verificar suas 2 UFs:**
   Abra `bdr/config.py` e confirme se o seu número em `MEMBROS` corresponde às suas 2 UFs.
4. **Executar teste inicial:**
   Rode primeiro apenas uma UF e o ano 2024 para validar rede e dependências locais:
   ```bash
   uv run python executar.py --ufs <SUA_UF_1> --anos 2024
   ```
5. **Executar o recorte completo:**
   ```bash
   uv run python executar.py --membro <N>
   ```
6. **Conferir o relatório de validação no terminal:**
   Certifique-se de que não há inconsistências aritméticas, duplicidades ou municípios sem código IBGE.
7. **Enviar o pacote gerado:**
   Suba no Google Drive o arquivo:
   `dados_bdr/saida/membro<N>_para_drive.zip`
8. **Integridade:**
   Não altere manualmente os dados gerados pela pipeline sem documentar.

---

## 8. Enviar o banco local ao MotherDuck

Para processar as seis UFs e, ao final, enviar todas as tabelas ao MotherDuck:

```bash
uv run python executar.py --ufs CE MA MS RJ RN RS --anos 2022 2024 \
  --etapas baixar carregar exportar motherduck \
  --motherduck-db pipeline_bdr_completo
```

Se o token não estiver definido no ambiente, o programa irá solicitá-lo de forma
oculta no terminal. O token não é salvo no código nem no banco local.

Depois de executar a etapa `carregar`, cada membro pode entregar seu ZIP à pessoa responsável pelo banco MotherDuck. Essa pessoa define seu token na sessão do PowerShell e usa **o mesmo nome de banco**, `pipeline_bdr_completo`, ao importar cada banco local:

```powershell
$env:MOTHERDUCK_TOKEN = "seu-token"
uv run python executar.py --membro 3 --etapas motherduck --motherduck-db pipeline_bdr_completo
```

O primeiro envio cria o banco; os seguintes acrescentam os municípios e dados das outras UFs às mesmas seis tabelas. Para importar membros de computadores diferentes, reúna os ZIPs e use o comando de consolidação abaixo. Se uma UF já estiver no banco, o envio individual interrompe para evitar repetição. O campo `uf` está na tabela `municipio`; consulte os votos por UF com `SELECT m.uf, v.* FROM pipeline_bdr_completo.main.votos_partido_municipio v JOIN pipeline_bdr_completo.main.municipio m ON m.cod_tse = v.cod_tse_municipio`. Não coloque o token no código ou no repositório.

Se preferir juntar os quatro ZIPs em um computador antes do envio, coloque-os em `dados_bdr/saida/` e execute:

```powershell
uv run python juntar.py dados_bdr/saida/membro1_para_drive.zip dados_bdr/saida/membro2_para_drive.zip dados_bdr/saida/membro3_para_drive.zip dados_bdr/saida/membro4_para_drive.zip --motherduck-db pipeline_bdr_completo
```

Isso cria `dados_bdr/bdr_consolidado.duckdb` e envia o banco ao MotherDuck. Use um nome remoto novo nesse modo de consolidação.

---

## 9. Formato Esperado para o IDHM Local

Caso o grupo deseje incluir ou atualizar dados municipais de IDHM, utilize o arquivo `dados_bdr/fontes/idhm.csv`:

```csv
id_municipio;ano_referencia;idhm
2408102;2010;0.763
3304557;2010;0.799
```

- **`id_municipio`**: Código IBGE de 7 dígitos do município.
- **`ano_referencia`**: Ano de referência do indicador (usar **2010**).
- **`idhm`**: Valor do índice entre 0 e 1 (aceita ponto ou vírgula decimal).

---

## 10. Limitações Metodológicas

- **Referência histórica do IDHM:** O último IDHM municipal oficial no Brasil refere-se ao Censo 2010. Não se deve criar valores artificiais para 2022 ou 2024. O IDHM deve ser interpretado como indicador estrutural histórico de longo prazo ao compará-lo com as eleições de 2022/2024.
- **Diferenças entre as eleições de 2022 e 2024:** A eleição de 2022 é geral (Presidente, Governador, Senador, Deputados Federais e Estaduais) e a de 2024 é municipal (Prefeito e Vereador). O eleitorado municipal e o comportamento eleitoral refletem naturezas e dinâmicas políticas distintas.
- **Não agregação cega de cargos:** A tabela `votos_partido_municipio` mantém a chave `cd_cargo`, impedindo a soma indevida de votos majoritários e proporcionais ou de cargos distintos.
- **Granularidade do Boletim de Urna:** Como cada linha do BU representa uma opção de voto, campos como `QT_APTOS`, `QT_COMPARECIMENTO` e `QT_ABSTENCOES` se repetem para cada cargo e candidato na urna. A pipeline realiza a deduplicação obrigatória no nível de seção/urna antes de somar para o município.
- **Descompasso temporal entre fontes:** Indicadores socioeconômicos (PIB 2022, População Censo 2022, IDHM 2010) e resultados eleitorais (2022 e 2024) possuem referências temporais próprias, preservadas explicitamente na coluna `ano_referencia`.

---

## 11. Trajetória eleitoral dos candidatos (Questão 10)

A pipeline histórica é independente da Questão 3 e usa `consulta_cand` e
`votacao_candidato_munzona` do TSE entre 2002 e 2024:

```bash
uv run python executar_trajetoria.py \
  --ufs CE MA MS RJ RN RS \
  --anos 2002 2004 2006 2008 2010 2012 2014 2016 2018 2020 2022 2024
```

Os dados temporários ficam em `dados_bdr/q10/`. O banco, o manifesto de validação
e o backup Parquet ficam em `dados_bdr/q10/saida/trajetoria_CE-MA-MS-RJ-RN-RS/`.
Nenhum dado é enviado ao MotherDuck por padrão.

Depois que todas as validações passarem:

```bash
uv run python executar_trajetoria.py \
  --ufs CE MA MS RJ RN RS \
  --anos 2002 2004 2006 2008 2010 2012 2014 2016 2018 2020 2022 2024 \
  --etapas motherduck \
  --motherduck-db pipeline_bdr_completo
```

Se as tabelas históricas já existirem, a substituição exige a opção explícita
`--substituir`. O token é solicitado de forma oculta e nunca é salvo no projeto.

---

## 12. Interface de apuração (Streamlit)

A interface lê diretamente as dez tabelas do DER. Depois de gerar o banco local,
execute na raiz do projeto:

```bash
uv sync
uv run streamlit run bdr/app_apuracao.py
```

Por padrão, o painel consulta `md:pipeline_bdr_der_completo`. Configure
`MOTHERDUCK_TOKEN` no ambiente antes de iniciar o Streamlit ou informe o token
no campo protegido da barra lateral. Se quiser consultar um banco local, informe
o caminho do arquivo `.duckdb` no campo **Banco DER**.

As consultas do painel ficam separadas por questão em `bdr/consultas_q3.sql` e
`bdr/consultas_q10.sql`. Os dois arquivos documentam parâmetros, regras analíticas
e referências temporais. A interface carrega os blocos nomeados desses arquivos;
não mantém SQL embutido no código do Streamlit. Na trajetória eleitoral, a pessoa
é relacionada por `id_candidato` e o painel usa somente o nome civil, sem consultar
ou exibir nome de urna.
