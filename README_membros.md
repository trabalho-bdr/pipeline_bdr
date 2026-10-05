# Guia de Execução por Membro — Questão 3

Este guia orienta cada membro da equipe sobre como configurar, testar e executar a pipeline para o seu recorte de **2 UFs** na **Questão 3**.

---

## 1. Divisão das UFs por Membro

Cada membro da equipe é responsável por exatamente 2 estados:

| Membro | UF 1 | UF 2 | Observação |
| :---: | :---: | :---: | :--- |
| **1** | `AC` | `AL` | *(Configurável em `bdr/config.py`)* |
| **2** | `MA` | `SE` | Maranhão e Sergipe |
| **3** | `RJ` | `RN` | Rio de Janeiro e Rio Grande do Norte |
| **4** | `PB` | `PI` | *(Configurável em `bdr/config.py`)* |

> Se necessário ajustar alguma UF, edite o dicionário `MEMBROS` em `bdr/config.py`.

---

## 2. Passo a Passo do Membro

### Passo 1: Obter o projeto e instalar dependências
```bash
git clone <url-do-repositorio>
cd load_BDR-main
uv sync
```
*(Se não estiver utilizando o `uv`, você pode usar `pip install duckdb` em seu ambiente virtual Python 3.10+).*

### Passo 2: Teste rápido de conectividade (1 UF e 2024)
Antes de executar tudo, faça um teste rápido com apenas uma UF e o ano de 2024:
```bash
uv run python executar.py --ufs RJ --anos 2024
```
Este comando baixa os boletins de 2024 da UF, consulta as APIs do IBGE e valida o funcionamento local.

### Passo 3: Executar o seu recorte completo
Para executar o recorte completo das suas duas UFs nos anos de 2022 e 2024:
```bash
uv run python executar.py --membro 3
```
*(Substitua `3` pelo número do seu membro).*

### Passo 4: Conferir o relatório de validação
No final da execução, o terminal imprimirá um resumo com 11 verificações de consistência. Certifique-se de que:
- Inconsistências (comparecimento + abstenção != aptos) = 0
- Municípios dos votos sem IBGE = 0
- Duplicidades na chave de votos = 0
- Votos negativos = 0

### Passo 5: Enviar o pacote para consolidação
O arquivo gerado para entrega estará em:
```text
dados_bdr/saida/membro<N>_para_drive.zip
```
Faça o upload desse arquivo ZIP no Google Drive da equipe.

---

## 3. Comandos Úteis

| Objetivo | Comando |
| :--- | :--- |
| **Execução completa do membro** | `uv run python executar.py --membro 3` |
| **Apenas download dos dados** | `uv run python executar.py --membro 3 --etapas baixar` |
| **Reprocessar sem baixar de novo** | `uv run python executar.py --membro 3 --etapas carregar exportar` |
| **Recorte livre para testes** | `uv run python executar.py --ufs RN --anos 2024` |
| **Consolidação dos 4 membros** | `uv run python juntar.py membro1_para_drive.zip membro2_para_drive.zip membro3_para_drive.zip membro4_para_drive.zip` |

---

## 4. O que é baixado (e o que NÃO é baixado)

Para a Questão 3, a pipeline baixa **estritamente**:
- **Boletins de Urna (TSE):** votos por partido no nível de seção/urna (nominais e de legenda).
- **Comparecimento e Abstenção (TSE):** detalhe oficial de votação, aptos, comparecimento e abstenção por município/zona (`detalhe_votacao_munzona`).
- **De-para TSE <-> IBGE:** correspondência oficial entre códigos de municípios (`municipio_tse_ibge.zip`).
- **IBGE:** Localidades, População (Censo 2022) e PIB Municipal (2022).
- **IDHM:** lido do arquivo local documentado `dados_bdr/fontes/idhm.csv` (referência 2010).

**NÃO são baixados:** `consulta_cand`, `prestacao_contas`, `perfil_eleitorado`, `bens`, `vagas`, etc., economizando tempo e espaço em disco.
