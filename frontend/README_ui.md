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

No topo, escolha **Abstenção** ou **Votos por legenda**. O painel preserva a seleção de estado, município e ano ao alternar entre as análises. Para votos por legenda, cargo e partido têm filtros próprios; os indicadores vêm do banco configurado na API.

Na análise de votos por legenda, o mapa apresenta um resumo compacto do recorte. Com **Estado = Brasil**, o painel e o mapa comparam as seis UFs disponíveis (CE, MA, MS, RJ, RN e RS); a comparação não representa as demais UFs. Ao selecionar um estado, o painel mostra ranking de partidos, distribuição percentual dos municípios, proporção entre votos de legenda e nominais, evolução nas eleições disponíveis para o cargo e ranking de municípios. A tabela de municípios seleciona o local no mapa. A busca sobre o mapa cobre os municípios das seis UFs disponíveis.

O preenchimento do mapa representa o percentual de votos de legenda entre votos de legenda e nominais. Na visão Brasil, a escala violeta–rosa se ajusta ao menor e maior percentual das UFs disponíveis no recorte; a legenda mostra os valores, pois diferenças pequenas ficam visualmente mais evidentes. Ao entrar numa UF, a escala se ajusta aos percentuais dos municípios com dados. Áreas sem dados ficam cinzas. Ao passar o mouse, o mapa mostra o percentual e a quantidade de votos.

Na visão Brasil, a comparação entre UFs usa uma cor fixa por estado nos gráficos e na lista lateral, enquanto o mapa usa a escala de intensidade relativa por percentual. Os demais gráficos do painel mostram o agregado das seis UFs: proporção legenda × nominal, evolução por eleição e municípios. Selecionar um município na tabela abre sua UF no mapa.

No filtro **Ano** da barra superior, escolha um ano específico para ver mapa, indicadores e os demais gráficos daquela eleição. Em **Todos os anos**, eles usam a soma dos votos das eleições disponíveis para o mesmo cargo, e os percentuais são calculados com os votos somados. A evolução permanece visível nos dois modos e considera todos os anos disponíveis para o cargo, com uma linha por partido. Em **Escolher anos**, é possível marcar os anos exibidos apenas nesse gráfico quando houver mais de uma eleição. Se o banco tiver somente um ano para o cargo, o painel informa que ainda não há comparação temporal. O filtro **Partido** continua aplicado a todo o painel.

Quando um partido está selecionado, os cartões **Partido líder** e **Ranking de partidos** deixam de aparecer; os demais indicadores e gráficos permanecem no recorte filtrado.

Para conferir o painel sem conexão com o banco, escolha **Votos por legenda** e clique em **Usar dados de exemplo**. Os próprios indicadores, mapa e gráficos do painel passam a consumir valores fictícios gerados em `mockLegenda.ts` a partir dos municípios do catálogo. A faixa de aviso identifica a prévia como simulada; **Voltar aos dados reais** restaura a consulta à API.

---

## Opção Alternativa: Painel Streamlit
O projeto também possui o dashboard nativo em Streamlit:
```bash
uv run streamlit run bdr/app_apuracao.py
```
