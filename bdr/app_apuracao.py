"""Painel interativo — Eleições BDR (Q3 socioeconômico + Q10 trajetória).

Rodar (na raiz do projeto):
    uv sync
    $env:MOTHERDUCK_TOKEN = "seu-token"     # PowerShell
    uv run streamlit run bdr/app_apuracao.py
"""
import json
import os
import urllib.request
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bdr.consultas_apuracao import consulta

st.set_page_config(page_title="Apuração BDR", layout="wide")

UFS = {  # sigla: (código IBGE, nome, região)
    "CE": ("23", "Ceará", "Nordeste"),
    "MA": ("21", "Maranhão", "Nordeste"),
    "MS": ("50", "Mato Grosso do Sul", "Centro-Oeste"),
    "RJ": ("33", "Rio de Janeiro", "Sudeste"),
    "RN": ("24", "Rio Grande do Norte", "Nordeste"),
    "RS": ("43", "Rio Grande do Sul", "Sul"),
}
COD2UF = {v[0]: k for k, v in UFS.items()}
AZUL, VERMELHO, FUNDO = "#3b5bdb", "#e03131", "#0e0e10"
BANCO_DER_PADRAO = "md:pipeline_bdr_der_completo_v2"

st.markdown(f"""<style>
.stApp {{background:{FUNDO}; color:#eee}}
h1,h2,h3 {{font-family: Georgia, serif; font-weight:400}}
[data-testid=stMetricValue] {{font-family: Georgia, serif; font-size:2.2rem}}
.card {{background:#17171a; border:1px solid #2a2a2e; border-radius:14px; padding:14px 18px}}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- dados
@st.cache_resource
def conectar(alvo: str):
    if alvo.startswith("md:"):
        return duckdb.connect(alvo)
    caminho = Path(alvo).expanduser()
    if not caminho.is_file():
        raise FileNotFoundError(f"Banco DER não encontrado: {caminho}")
    return duckdb.connect(str(caminho), read_only=True)


@st.cache_data(show_spinner="Carregando mapa do Brasil…")
def malha():
    caminho_local = os.path.join(os.path.dirname(__file__), "malha_brasil.json")
    if os.path.exists(caminho_local):
        with open(caminho_local, "r", encoding="utf-8") as f:
            return json.load(f)
    url = "https://raw.githubusercontent.com/giuliano-macedo/geodata-br-states/master/geojson/br_states.json"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def sql(con, q, params=None):
    return con.execute(q, params or []).df()


@st.cache_data(show_spinner="Consultando…")
def base_q3(alvo, uf, ano):
    return sql(conectar(alvo), consulta("q3_municipios"), [ano, uf])


@st.cache_data
def cargos_q3(alvo, uf, ano, turno):
    return sql(conectar(alvo), consulta("q3_cargos"), [uf, ano, turno])["cargo"].tolist()


@st.cache_data(show_spinner="Somando votos por partido…")
def votos_q3(alvo, uf, ano, turno, cargo):
    return sql(
        conectar(alvo),
        consulta("q3_votos_por_perfil"),
        [ano, uf, turno, cargo],
    )


@st.cache_data(show_spinner="Carregando candidaturas…")
def candidaturas_q10(alvo, uf):
    return sql(conectar(alvo), consulta("q10_trajetorias"), [uf])


def painel_demografia(alvo, uf, ano, turno, cargo):
    con = conectar(alvo)
    tabelas = {r[0].lower() for r in con.execute("SHOW TABLES").fetchall()}
    if "perfil_eleitorado_municipio" not in tabelas:
        st.info("Perfil demográfico ainda não carregado neste banco. Consulte o banco DER enriquecido.")
        return
    st.caption("Associações entre municípios. O voto é secreto: estes dados não identificam o partido votado por idade ou gênero. Jovens: 16 a 24 anos. Perfil do eleitorado no ano selecionado; censo: 2022.")
    d = sql(con, consulta("q3_demografia_partidos"), [ano, uf, turno, cargo])
    p = sql(con, consulta("q3_perfil_eleitorado"), [ano, uf])
    if p.empty or d.empty:
        st.info("Sem perfil do eleitorado ou votos para este recorte.")
        return
    opcoes = p[["id_municipio", "municipio"]].drop_duplicates().set_index("id_municipio")["municipio"].to_dict()
    municipio = st.selectbox("Município · eleitorado e votação", opcoes, format_func=opcoes.get)
    local = p[p.id_municipio == municipio]
    idade, genero, escolaridade = st.tabs(["Faixa etária", "Gênero", "Escolaridade"])
    for aba, campo in [(idade, "faixa_etaria"), (genero, "genero"), (escolaridade, "grau_instrucao")]:
        with aba:
            resumo = local.groupby(campo, as_index=False)["quantidade_eleitores"].sum()
            st.plotly_chart(px.bar(resumo, x=campo, y="quantidade_eleitores"), use_container_width=True)
    st.caption("Quantidades de eleitores cadastrados; não medem comparecimento dos grupos.")
    st.dataframe(d[d.id_municipio == municipio], hide_index=True, use_container_width=True)
    indicadores = {"jovens_16_24_pct": "Jovens no eleitorado (%)",
                   "feminino_pct": "Gênero feminino no eleitorado (%)",
                   "analfabetos_pct": "Eleitorado analfabeto (%)",
                   "superior_completo_pct": "Eleitorado com superior completo (%)",
                   "idade_media_estimada": "Idade média estimada da população (2022)",
                   "idade_mediana": "Idade mediana da população (2022)"}
    eixo = st.selectbox("Composição municipal", indicadores, format_func=indicadores.get)
    medida = st.selectbox("Votação partidária", ["votos_pct", "legenda_pct"],
                          format_func=lambda x: {"votos_pct": "Votos nominais + legenda (%)", "legenda_pct": "Votos de legenda (%)"}[x])
    partidos = d[["id_partido", "partido"]].drop_duplicates().set_index("id_partido")["partido"].to_dict()
    partido = st.selectbox("Partido · associação municipal", partidos, format_func=partidos.get)
    recorte = d[d.id_partido == partido].dropna(subset=[eixo, medida])
    st.plotly_chart(px.scatter(recorte, x=eixo, y=medida, hover_name="municipio",
                              labels={eixo: indicadores[eixo], medida: "Participação nos votos (%)"}),
                    use_container_width=True)
    r = recorte[eixo].corr(recorte[medida]) if len(recorte) >= 3 else float("nan")
    st.caption(f"Pearson: {r:.3f} · {len(recorte)} municípios com votação registrada para o partido. Associação descritiva; não demonstra causalidade ou preferência individual." if pd.notna(r) else "Correlação indisponível: poucos municípios, ausência de legenda ou indicador sem variação.")
    st.caption("Média estimada: idades completas do Censo 2022, representando o grupo aberto 100+ por 100 anos. Escolaridade refere-se ao eleitorado cadastrado, não à população inteira.")


# ---------------------------------------------------------------- mapa
def mapa(selecionada):
    geo = malha()
    todas = [f["properties"]["SIGLA"] for f in geo["features"]]
    outras = [s for s in todas if s not in UFS]
    ativos = list(UFS.keys())

    fig = go.Figure()
    # Outros estados do Brasil (fundo sutil e escuro)
    fig.add_trace(go.Choropleth(
        geojson=geo,
        featureidkey="properties.SIGLA",
        locations=outras,
        z=[0] * len(outras),
        colorscale=[[0, "#19191d"], [1, "#19191d"]],
        showscale=False,
        marker_line_color="#2b2b33",
        marker_line_width=0.8,
        hoverinfo="text",
        text=[f["properties"]["Estado"] for f in geo["features"] if f["properties"]["SIGLA"] in outras],
        name="Outros",
    ))
    # 6 estados ativos do trabalho (destacados e interativos)
    fig.add_trace(go.Choropleth(
        geojson=geo,
        featureidkey="properties.SIGLA",
        locations=ativos,
        z=[1 if s == selecionada else 0 for s in ativos],
        colorscale=[[0, "#2c46a6"], [1, VERMELHO]],
        showscale=False,
        marker_line_color="#ffffff",
        marker_line_width=1.6,
        text=[f"<b>{s} — {UFS[s][1]}</b><br>Região: {UFS[s][2]}<br><i>Clique para selecionar</i>" for s in ativos],
        hoverinfo="text",
        name="Estados Ativos",
    ))
    fig.update_geos(
        fitbounds="locations",
        visible=False,
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        height=580,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        dragmode=False,
        clickmode="event+select",
    )
    return fig


# ---------------------------------------------------------------- UI
with st.sidebar:
    st.header("Conexão")
    alvo = st.text_input("Banco DER (MotherDuck ou arquivo .duckdb)", BANCO_DER_PADRAO)
    if alvo.startswith("md:") and not os.environ.get("MOTHERDUCK_TOKEN"):
        token = st.text_input("MOTHERDUCK_TOKEN", type="password")
        if token:
            os.environ["MOTHERDUCK_TOKEN"] = token
    questao = st.radio("Questão", ["Q3 · Perfil do município", "Q10 · Trajetória eleitoral"])

st.title("Apuração BDR")
st.caption("Clique em um dos 6 estados ativos do mapa (ou use o seletor ao lado).")

if "uf" not in st.session_state:
    st.session_state.uf = "RJ"

col_mapa, col_det = st.columns([5, 7], gap="large")
with col_mapa:
    ev = st.plotly_chart(mapa(st.session_state.uf), on_select="rerun", selection_mode="points",
                         use_container_width=True, key="mapa")
    pts = (ev or {}).get("selection", {}).get("points", [])
    if pts:
        loc = str(pts[0].get("location"))
        clicado = loc if loc in UFS else COD2UF.get(loc)
        if clicado:
            st.session_state.uf = clicado
    st.session_state.uf = st.radio("Estado", list(UFS), index=list(UFS).index(st.session_state.uf),
                                   horizontal=True, format_func=lambda u: u)

uf = st.session_state.uf

with col_det:
    st.subheader(f"{UFS[uf][1]} · {UFS[uf][2]}")
    if alvo.startswith("md:") and not os.environ.get("MOTHERDUCK_TOKEN"):
        st.info("Informe MOTHERDUCK_TOKEN na barra lateral para consultar o DER.")
        st.stop()
    try:
        if questao.startswith("Q3"):
            c1, c2 = st.columns(2)
            ano = c1.selectbox("Ano", [2018, 2020, 2022, 2024], index=3)
            turno = 1  # O DER preserva participação eleitoral apenas do primeiro turno.
            cargos = cargos_q3(alvo, uf, ano, turno)
            cargo = c2.selectbox("Cargo", cargos) if cargos else None
            df = base_q3(alvo, uf, ano)
            if df.empty or not cargo:
                st.warning("Sem dados para esse recorte.")
                st.stop()
            st.caption(
                "Primeiro turno · PIB e população: 2022 · IDHM: 2010. "
                "Mais rico/pobre: mediana do PIB per capita da UF; "
                "pequeno/grande: corte de 100 mil habitantes."
            )

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Municípios", f"{len(df):,}".replace(",", "."))
            m2.metric("Eleitores", f"{int(df['eleitorado'].sum()):,}".replace(",", "."))
            eleitorado_total = df["eleitorado"].sum()
            abstencao_total = 100 * df["abstencoes"].sum() / eleitorado_total if eleitorado_total else 0
            m3.metric("Abstenção", f"{abstencao_total:.1f}%".replace(".", ","))
            m4.metric("IDHM médio", f"{df['idhm'].mean():.3f}".replace(".", ","))

            aba1, aba2, aba3, aba4 = st.tabs(["Abstenção × indicador", "Partidos × perfil", "Dados completos", "Idade, gênero e escolaridade"])
            with aba4:
                painel_demografia(alvo, uf, ano, turno, cargo)
            with aba1:
                indicadores = {"pib_per_capita": "PIB per capita", "idhm": "IDHM (2010)",
                               "populacao": "População", "eleitorado": "Eleitores"}
                eixo = st.selectbox("Indicador", indicadores, format_func=indicadores.get)
                f = px.scatter(df, x=eixo, y="abstencao_pct", color="perfil_renda", size="eleitorado",
                               hover_name="municipio", log_x=eixo != "idhm", trendline=None,
                               color_discrete_map={"Mais rico": AZUL, "Mais pobre": VERMELHO},
                               labels={"abstencao_pct": "Abstenção (%)", eixo: indicadores[eixo],
                                       "perfil_renda": "Perfil de renda"})
                f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(f, use_container_width=True)
                correlacao = df["abstencao_pct"].corr(df[eixo])
                st.caption(f"Correlação (Pearson) entre abstenção e {indicadores[eixo]}: "
                           f"{correlacao:.2f}" if pd.notna(correlacao) else
                           "Correlação indisponível para este recorte.")
            with aba2:
                v = votos_q3(alvo, uf, ano, turno, cargo)
                if v.empty:
                    st.info("Sem votos partidários para esse cargo.")
                else:
                    g = v.dropna(subset=["perfil_porte", "perfil_renda"]).groupby(
                        ["perfil_porte", "perfil_renda", "partido"], observed=True
                    )["votos"].sum().reset_index()
                    g["pct"] = 100 * g["votos"] / g.groupby(
                        ["perfil_porte", "perfil_renda"], observed=True
                    )["votos"].transform("sum")
                    f = px.bar(g, x="pct", y="partido", color="partido", orientation="h",
                               facet_col="perfil_porte", facet_row="perfil_renda",
                               labels={"pct": "% dos votos do perfil (todos os partidos)",
                                       "perfil_porte": "Porte", "perfil_renda": "Renda"})
                    f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                                    showlegend=False, height=max(520, 24 * v["partido"].nunique()))
                    st.plotly_chart(f, use_container_width=True)
                    st.caption("Percentuais calculados dentro de cada combinação de renda e porte.")
            with aba3:
                st.subheader("Municípios e abstenção")
                st.dataframe(df, use_container_width=True, hide_index=True)
                st.subheader("Votos por município e partido")
                st.dataframe(v, use_container_width=True, hide_index=True)

        else:  # Q10
            d = candidaturas_q10(alvo, uf)
            if d.empty:
                st.warning("Sem candidaturas para esse estado.")
                st.stop()
            d["municipio"] = d["municipio"].fillna("Não se aplica / não informado")
            d["resultado"] = d["resultado"].fillna("Não informado")
            trajetorias = d.groupby("id_candidato").agg(
                nome_civil=("nome_civil", "first"),
                primeiro_ano=("ano", "min"),
                ultimo_ano=("ano", "max"),
                pleitos=("ano", "nunique"),
                candidaturas=("ano", "size"),
                partidos=("partido", "nunique"),
                cargos=("cargo", "nunique"),
                ufs=("uf", "nunique"),
            ).reset_index()
            c1, c2 = st.columns(2)
            c1.metric("Candidatos únicos", f"{d['id_candidato'].nunique():,}".replace(",", "."))
            c2.metric("Eleitos (candidaturas)", f"{int(d['eleito'].sum()):,}".replace(",", "."))

            aba1, aba2 = st.tabs(["Visão geral", "Trajetória individual"])
            with aba1:
                por_ano = d.groupby("ano").agg(candidatos=("id_candidato", "nunique"),
                                               candidaturas=("id_candidato", "size"),
                                               eleitos=("eleito", "sum")).reset_index()
                f2 = px.line(por_ano, x="ano", y=["candidatos", "eleitos"], markers=True)
                f2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                                 xaxis_title="Ano", yaxis_title="Pessoas / candidaturas")
                st.plotly_chart(f2, use_container_width=True)
                st.caption("A mesma pessoa é identificada por id_candidato em todos os anos e UFs.")
                st.subheader("Resumo por candidato")
                st.dataframe(trajetorias, use_container_width=True, hide_index=True)
            with aba2:
                termo = st.text_input("Buscar por nome civil ou ID do candidato")
                if termo:
                    achados = trajetorias[
                        trajetorias["nome_civil"].str.contains(termo, case=False, na=False, regex=False)
                        | trajetorias["id_candidato"].str.contains(termo, case=False, na=False, regex=False)
                    ]
                    ids = achados.set_index("id_candidato")["nome_civil"]
                    if ids.empty:
                        st.info("Nenhum candidato encontrado.")
                    else:
                        escolha = st.selectbox(
                            "Candidato (identificado por ID)",
                            ids.index,
                            format_func=lambda i: f"{ids[i]} · {i[:8]}",
                        )
                        c = d[d["id_candidato"] == escolha].sort_values("ano")
                        f = px.scatter(c, x="ano", y="ordem_cargo", color="partido", symbol="eleito",
                                       hover_data=["turno", "cargo", "municipio", "uf", "votos", "resultado"], size_max=16,
                                       symbol_map={True: "star", False: "circle-open"})
                        f.update_traces(marker_size=16)
                        f.update_xaxes(dtick=2)
                        f.update_layout(
                            template="plotly_dark",
                            paper_bgcolor="rgba(0,0,0,0)",
                            yaxis=dict(
                                tickmode="array",
                                tickvals=[1, 2, 3, 4, 5, 6, 7],
                                ticktext=[
                                    "1 · Vereador",
                                    "2 · Prefeito",
                                    "3 · Dep. Estadual",
                                    "4 · Dep. Federal",
                                    "5 · Senador",
                                    "6 · Governador",
                                    "7 · Presidente",
                                ],
                                range=[0.5, 7.5],
                                title="Nível do cargo (ordem hierárquica)"
                            )
                        )
                        st.plotly_chart(f, use_container_width=True)
                        st.dataframe(c[["id_candidato", "nome_civil", "ano", "turno", "cargo",
                                        "partido", "municipio", "uf", "patrimonio", "gastos_campanha_total",
                                        "votos", "resultado", "eleito"]],
                                     use_container_width=True, hide_index=True)
                else:
                    st.info("Busque pelo nome civil ou ID para ver cada candidatura na linha do tempo.")
    except Exception as e:  # conexão, tabela ausente, rede…
        st.error(f"Erro: {e}")
