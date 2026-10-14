# Interface de mapa (Brasil → estado → município)

Camadas: `web/` (Preact + TS + Vite + D3), `api/` (FastAPI, somente leitura), `scripts/preparar_malhas.py` (malhas IBGE).
A API reutiliza `bdr/consultas_apuracao.py` (`q3_municipios`) e não executa a pipeline.

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
> Por padrão, a API busca o banco local em `pipeline_bdr_der/dados_bdr/saida/pipeline_bdr_der.duckdb` (ou `dados_bdr/saida/pipeline_bdr_der_completo.duckdb`). Para MotherDuck:
> `$env:BDR_BANCO="md:pipeline_bdr_der_completo"; $env:MOTHERDUCK_TOKEN="..."`

### 3. Iniciar a Interface Web (Preact + Vite)
Em outro terminal:
```bash
cd frontend
npm install
npm run dev
```
Acesse no navegador: **http://localhost:5173**

---

## Opção Alternativa: Painel Streamlit
O projeto também possui o dashboard nativo em Streamlit:
```bash
uv run streamlit run bdr/app_apuracao.py
```
