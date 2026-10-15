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
> A API usa um banco DER local quando ele existe. Sem arquivo local, conecta automaticamente a `md:pipeline_bdr_der_completo` no MotherDuck. No mesmo terminal em que vai iniciar a API, configure seu token: `$env:MOTHERDUCK_TOKEN="seu-token"`. Também é possível definir `$env:BDR_BANCO="md:pipeline_bdr_der_completo"` para forçar o banco online. Reinicie a API após mudar essas variáveis. O token deve ficar apenas no servidor; o Vite acessa os dados pela API.

### 3. Iniciar a Interface Web (Preact + Vite)
Em outro terminal:
```bash
cd frontend
npm install
npm run dev
```
Acesse no navegador: **http://localhost:5173**

No topo, escolha **Abstenção** ou **Votos por legenda** e alterne entre **Mapa completo** e **Painel**. As duas visualizações preservam a seleção de estado, município e ano. Para votos por legenda, cargo e partido têm filtros próprios; os indicadores vêm do banco configurado na API.

Na análise de votos por legenda, o mapa apresenta um resumo compacto do recorte. Com **Estado = Brasil**, o painel e o mapa comparam as seis UFs disponíveis (CE, MA, MS, RJ, RN e RS); a comparação não representa as demais UFs. Ao selecionar um estado, o painel mostra ranking de partidos, distribuição percentual dos municípios, proporção entre votos de legenda e nominais, evolução nas eleições disponíveis para o cargo e ranking de municípios. A tabela de municípios seleciona o local no mapa. A busca sobre o mapa cobre os municípios das seis UFs disponíveis.

O preenchimento rosa do mapa representa o percentual de votos de legenda entre votos de legenda e nominais, de 0% a 30% ou mais. A escala vale para UFs na visão Brasil e para municípios após selecionar uma UF; áreas sem dados ficam cinzas. Ao passar o mouse, o mapa mostra o percentual e a quantidade de votos do recorte.

Na visão Brasil, a comparação entre UFs usa uma cor fixa por estado nos gráficos e na lista lateral, enquanto o mapa mantém a escala rosa por percentual. Os demais gráficos do painel mostram o agregado das seis UFs: proporção legenda × nominal, evolução por eleição e municípios. Selecionar um município na tabela abre sua UF no mapa.

O filtro **Partido** fica na barra superior e se aplica a todo o painel, inclusive ao gráfico **Evolução dos votos de legenda**. Com **Todos**, o gráfico apresenta uma linha por partido, com cores identificadas na legenda; ao escolher um partido, mostra apenas sua série. O ano da barra superior define o retrato dos indicadores e fica destacado na evolução, que mostra todas as eleições disponíveis para o mesmo cargo. Os pontos respeitam a distância entre os anos; quando um partido não tem registro em determinado ano, a série apresenta uma lacuna.

Quando um partido está selecionado, os cartões **Partido líder** e **Ranking de partidos** deixam de aparecer; os demais indicadores e gráficos permanecem no recorte filtrado.

Para conferir o painel sem conexão com o banco, escolha **Votos por legenda** e clique em **Usar dados de exemplo**. Os próprios indicadores, mapa e gráficos do painel passam a consumir valores fictícios gerados em `mockLegenda.ts` a partir dos municípios do catálogo. A faixa de aviso identifica a prévia como simulada; **Voltar aos dados reais** restaura a consulta à API.

---

## Opção Alternativa: Painel Streamlit
O projeto também possui o dashboard nativo em Streamlit:
```bash
uv run streamlit run bdr/app_apuracao.py
```
