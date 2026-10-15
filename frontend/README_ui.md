# Interface de mapa (Brasil → estado → município)

Camadas: `web/` (Preact + TS + Vite + D3), `api/` (FastAPI, somente leitura), `scripts/preparar_malhas.py` (malhas IBGE).
A API reutiliza `bdr/consultas_apuracao.py` (`q3_municipios`) e não executa a pipeline.

## Views de votos por legenda

O SQL em `bdr/legenda_views.sql` cria o detalhe por município e partido, o agregado por UF e a série temporal por partido. As views consideram primeiro turno, as seis UFs disponíveis e apenas Deputado Federal, Deputado Estadual e Vereador. A API usa a view municipal quando ela existe; antes da instalação, consulta as tabelas originais.

Na raiz do projeto, inspecione o banco sem alterá-lo e depois instale as views:

```powershell
uv run python -m bdr.instalar_legenda_views
uv run python -m bdr.instalar_legenda_views --apply
```

O script solicita o token do MotherDuck com entrada oculta quando `MOTHERDUCK_TOKEN` não está definido no terminal. Para outro banco, passe `--database md:nome_do_banco`. A instalação compara os totais por ano, cargo e UF com as tabelas de origem e desfaz a transação se houver divergência. Reinicie a API após instalar as views.

## Patrimônio e sucesso eleitoral (Q2)

Botão **Patrimônio** na barra de análises, no mesmo desenho de mapa das outras. Filtros: estado, **ano**
(2018, 2020, 2022 e 2024), cargo e **indicador do mapa** (patrimônio mediano dos candidatos, dos eleitos ou a razão
eleitos ÷ não eleitos). O mapa pinta os **municípios** do estado escolhido (prefeito e vereador) ou as **UFs**
(Brasil inteiro, e todos os cargos estaduais: deputados, senador e governador, que não têm município).

API (`frontend/q2.py`, SQL de entrega em `bdr/consultas_q2.sql`):

* `GET /api/q2/opcoes`: pares (ano, cargo) que existem no banco.
* `GET /api/q2/municipios?ano=2024&cargo=VEREADOR`: um valor por município e por UF (alimenta o mapa).
* `GET /api/q2/patrimonio?ano=2024&cargo=VEREADOR&uf=RN&municipio=2400109`: cartões, decis e comparativo
  do recorte (`uf` e `municipio` são opcionais).

Regras: sucesso = resultado começando com `ELEITO`; insucesso = `NÃO ELEITO` e `SUPLENTE`; `#NULO` e `2º TURNO`
ficam de fora (a tela informa quantos). Cada candidatura conta uma vez, pelo último turno, e a comparação é sempre
dentro de um ano e de um cargo. Se o banco não tiver `Candidatura.patrimonio` para o recorte, a tela mostra um
aviso com cobertura 0%. O botão **Usar dados de exemplo** mostra a interface com dados fictícios
(`mockPatrimonio.ts`, mesmo contrato da API); para retirá-lo, veja o comentário `// MOCK` em `PainelPatrimonio.tsx`.

## Instalação e execução

### 1. Preparar as malhas do IBGE (já executado e validado)
```bash
uv run python frontend/preparar_malhas.py
```
*(Gera os arquivos TopoJSON e catalogo em `frontend/public/geo/`)*

### 2. Iniciar a API (FastAPI)
Na raiz do repositório:
```bash
uv run uvicorn frontend.main:app --port 8000
```
> A API procura primeiro `dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb` e `pipeline_bdr_der/dados_bdr/saida/pipeline_bdr_der_completo_v3.duckdb`. Sem arquivo local, conecta a `md:pipeline_bdr_der_completo_v3` no MotherDuck. No mesmo terminal em que vai iniciar a API, configure seu token: `$env:MOTHERDUCK_TOKEN="seu-token"`. Use `$env:BDR_BANCO="md:pipeline_bdr_der_completo_v3"` para indicar o banco explicitamente. Reinicie a API após mudar essas variáveis. O token deve ficar apenas no servidor; o Vite acessa os dados pela API.

### 3. Iniciar a Interface Web (Preact + Vite)
Em outro terminal:
```bash
cd frontend
npm install
npm run dev
```
Acesse no navegador: **http://localhost:5173**

No topo, escolha **Abstenção** ou **Votos por legenda**. O painel preserva a seleção de estado, município e ano ao alternar entre as análises. Para votos por legenda, cargo e partido têm filtros próprios; os indicadores vêm do banco configurado na API.

Na análise de votos por legenda, o mapa apresenta um resumo compacto do recorte. Com **Estado = Brasil**, o painel e o mapa cobrem as seis UFs disponíveis (CE, MA, MS, RJ, RN e RS); o recorte não representa as demais UFs. Ao selecionar um estado, o painel mostra os votos por partido, a distribuição percentual dos municípios, a evolução nas eleições disponíveis para o cargo e a lista de municípios. A tabela de municípios seleciona o local no mapa. A busca sobre o mapa cobre os municípios das seis UFs disponíveis.

No modo percentual, o mapa representa votos de legenda divididos pela soma de votos de legenda e nominais. Na visão Brasil, a escala se ajusta às UFs disponíveis; dentro de uma UF, usa os percentis 10, 50 e 90 dos municípios para revelar diferenças sem deixar valores extremos dominar a escala. Áreas sem dados ficam cinzas. O tooltip mostra o percentual e os votos.

O mapa oferece dois modos: **Partido mais votado**, que colore cada município pelo partido com mais votos de legenda, e **% votos de legenda**, que colore pelo percentual de legenda entre votos de legenda e nominais. No modo partidário, a sigla e os votos aparecem ao passar o mouse; a caixa de legenda sobre o mapa aparece apenas no modo percentual. O ranking de partidos fica abaixo do mapa.

No filtro **Ano**, os anos disponíveis dependem do cargo. Em **Todos os anos**, os indicadores e demais gráficos somam os votos das eleições disponíveis para o mesmo cargo; os percentuais usam os votos somados. A comparação histórica permanece visível em ambos os modos e compara a participação de cada partido nos votos de legenda dos dois anos do cargo, em pontos percentuais. Partidos sem registro em ambos os anos ficam fora da comparação; a ausência não equivale a zero. Em **Evolução por partido**, é possível selecionar linhas específicas; cinco aparecem inicialmente. O filtro **Município** também pode ser usado fora do mapa.

Quando um partido está selecionado, os indicadores, o ranking, o mapa e a tabela municipal refletem o partido; a comparação histórica destaca sua linha ou barra quando há registros comparáveis.

Para conferir o painel sem conexão com o banco, escolha **Votos por legenda** e clique em **Usar dados de exemplo**. Os próprios indicadores, mapa e gráficos do painel passam a consumir valores fictícios gerados em `mockLegenda.ts` a partir dos municípios do catálogo. A faixa de aviso identifica a prévia como simulada; **Voltar aos dados reais** restaura a consulta à API.

---

## Opção Alternativa: Painel Streamlit
O projeto também possui o dashboard nativo em Streamlit:
```bash
uv run streamlit run bdr/app_apuracao.py
```
