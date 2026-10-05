"""Painel interativo — Eleições BDR (Q3 socioeconômico + Q10 trajetória).

Rodar (na raiz do projeto):
    uv add streamlit plotly pandas
    $env:MOTHERDUCK_TOKEN = "seu-token"     # PowerShell
    uv run streamlit run app_apuracao.py
"""
import json
import os
import urllib.request

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

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

st.markdown(f"""<style>
.stApp {{background:{FUNDO}; color:#eee}}
h1,h2,h3 {{font-family: Georgia, serif; font-weight:400}}
[data-testid=stMetricValue] {{font-family: Georgia, serif; font-size:2.2rem}}
.card {{background:#17171a; border:1px solid #2a2a2e; border-radius:14px; padding:14px 18px}}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------- dados
@st.cache_resource
def conectar(alvo: str):
    return duckdb.connect(alvo)


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
def base_q3(alvo, uf, ano, turno):
    con = conectar(alvo)
    return sql(con, """
        SELECT m.cod_tse, m.nome, m.id_municipio,
               max(p.eleitorado_apto) AS eleitorado, max(p.abstencoes) AS abst,
               any_value(c.populacao) AS populacao,
               any_value(c.pib_per_capita) AS pib_pc, any_value(c.idhm) AS idhm
        FROM municipio m
        JOIN participacao_eleitoral p ON p.cod_tse_municipio = m.cod_tse
             AND p.ano = ? AND p.turno = ?
        LEFT JOIN (
            SELECT id_municipio,
                   max(populacao)      FILTER (WHERE ano_referencia = 2022) AS populacao,
                   max(pib_per_capita) FILTER (WHERE ano_referencia = 2022) AS pib_per_capita,
                   max(idhm)           FILTER (WHERE ano_referencia = 2010) AS idhm
            FROM censo_municipio GROUP BY 1) c ON c.id_municipio = m.id_municipio
        WHERE m.uf = ?
        GROUP BY m.cod_tse, m.nome, m.id_municipio""", [ano, turno, uf])


@st.cache_data
def cargos_q3(alvo, uf, ano, turno):
    return sql(conectar(alvo), """
        SELECT DISTINCT v.cargo FROM votos_partido_municipio v
        JOIN municipio m ON m.cod_tse = v.cod_tse_municipio
        WHERE m.uf = ? AND v.ano = ? AND v.turno = ? ORDER BY 1""", [uf, ano, turno])["cargo"].tolist()


@st.cache_data(show_spinner="Somando votos por partido…")
def votos_q3(alvo, uf, ano, turno, cargo):
    return sql(conectar(alvo), """
        SELECT v.cod_tse_municipio AS cod_tse, v.sigla_partido AS partido,
               sum(v.votos_nominais + coalesce(v.votos_legenda, 0)) AS votos
        FROM votos_partido_municipio v JOIN municipio m ON m.cod_tse = v.cod_tse_municipio
        WHERE m.uf = ? AND v.ano = ? AND v.turno = ? AND v.cargo = ?
        GROUP BY 1, 2""", [uf, ano, turno, cargo])


@st.cache_data(show_spinner="Carregando candidaturas…")
def candidaturas_q10(alvo, uf):
    return sql(conectar(alvo), """
        SELECT ca.id_candidato, c.nome_urna, ca.ano, cg.nome AS cargo,
               cg.ordem_hierarquica AS ordem, ca.sigla_partido AS partido,
               coalesce(r.eleito, false) AS eleito, r.votos
        FROM candidatura ca
        JOIN candidato c USING (id_candidato)
        JOIN cargo cg USING (cd_cargo)
        LEFT JOIN resultado_candidatura r USING (id_candidatura)
        WHERE ca.uf = ?""", [uf])


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
    alvo = st.text_input("Banco (MotherDuck ou arquivo .duckdb)", "md:pipeline_bdr_completo")
    if alvo.startswith("md:") and not os.environ.get("MOTHERDUCK_TOKEN"):
        os.environ["MOTHERDUCK_TOKEN"] = st.text_input("MOTHERDUCK_TOKEN", type="password")
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
    try:
        if questao.startswith("Q3"):
            c1, c2, c3 = st.columns(3)
            ano = c1.selectbox("Ano", [2022, 2024], index=1)
            turno = c2.selectbox("Turno", [1, 2])
            cargos = cargos_q3(alvo, uf, ano, turno)
            cargo = c3.selectbox("Cargo", cargos) if cargos else None
            df = base_q3(alvo, uf, ano, turno)
            if df.empty or not cargo:
                st.warning("Sem dados para esse recorte.")
                st.stop()

            df["abstencao_pct"] = 100 * df["abst"] / df["eleitorado"]
            df["porte"] = pd.cut(df["populacao"], [0, 20_000, 100_000, float("inf")],
                                 labels=["Pequeno (<20 mil)", "Médio (20–100 mil)", "Grande (>100 mil)"])
            mediana = df["pib_pc"].median()
            df["renda"] = (df["pib_pc"] >= mediana).map({True: "Mais rico", False: "Mais pobre"})
            df.loc[df["pib_pc"].isna(), "renda"] = None
            df["perfil"] = df["renda"].astype(str) + " · " + df["porte"].astype(str)

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Municípios", f"{len(df):,}".replace(",", "."))
            m2.metric("Eleitores", f"{int(df['eleitorado'].sum()):,}".replace(",", "."))
            m3.metric("Abstenção", f"{100 * df['abst'].sum() / df['eleitorado'].sum():.1f}%".replace(".", ","))
            m4.metric("IDHM médio", f"{df['idhm'].mean():.3f}".replace(".", ","))

            aba1, aba2, aba3 = st.tabs(["Abstenção × indicador", "Partidos × perfil", "Tabela"])
            with aba1:
                eixo = st.selectbox("Indicador", {"pib_pc": "PIB per capita", "idhm": "IDHM (2010)",
                                                  "populacao": "População", "eleitorado": "Eleitores"}.keys(),
                                    format_func=lambda k: {"pib_pc": "PIB per capita", "idhm": "IDHM (2010)",
                                                           "populacao": "População", "eleitorado": "Eleitores"}[k])
                f = px.scatter(df, x=eixo, y="abstencao_pct", color="renda", size="eleitorado",
                               hover_name="nome", log_x=eixo != "idhm", trendline=None,
                               color_discrete_map={"Mais rico": AZUL, "Mais pobre": VERMELHO},
                               labels={"abstencao_pct": "Abstenção (%)"})
                f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(f, use_container_width=True)
                st.caption(f"Correlação (Pearson) abstenção × {eixo}: "
                           f"{df['abstencao_pct'].corr(df[eixo]):.2f}")
            with aba2:
                v = votos_q3(alvo, uf, ano, turno, cargo).merge(df[["cod_tse", "perfil", "renda", "porte"]], on="cod_tse")
                top = v.groupby("partido")["votos"].sum().nlargest(8).index
                g = v[v["partido"].isin(top)].groupby(["porte", "renda", "partido"], observed=True)["votos"].sum().reset_index()
                g["pct"] = 100 * g["votos"] / g.groupby(["porte", "renda"], observed=True)["votos"].transform("sum")
                f = px.bar(g, x="pct", y="partido", color="partido", orientation="h",
                           facet_col="porte", facet_row="renda", labels={"pct": "% dos votos (top 8 partidos)"})
                f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", showlegend=False, height=520)
                st.plotly_chart(f, use_container_width=True)
            with aba3:
                st.dataframe(df.drop(columns=["cod_tse"]), use_container_width=True, hide_index=True)

        else:  # Q10
            d = candidaturas_q10(alvo, uf)
            if d.empty:
                st.warning("Sem candidaturas para esse estado.")
                st.stop()
            d["serie"] = d["ano"].map(lambda a: "Municipal" if a % 4 == 0 else "Geral")

            def classificar(anos):
                anos = sorted(set(anos))
                if len(anos) == 1:
                    return "Candidatura única"
                return "Contínua" if all(b - a == 4 for a, b in zip(anos, anos[1:])) else "Com interrupção e retorno"

            t = d.groupby(["id_candidato", "serie"])["ano"].apply(classificar).reset_index(name="padrao")
            c1, c2 = st.columns(2)
            c1.metric("Candidatos únicos", f"{d['id_candidato'].nunique():,}".replace(",", "."))
            c2.metric("Eleitos (candidaturas)", f"{int(d['eleito'].sum()):,}".replace(",", "."))

            aba1, aba2 = st.tabs(["Padrões de carreira", "Buscar candidato"])
            with aba1:
                p = t.groupby(["serie", "padrao"]).size().reset_index(name="n")
                f = px.bar(p, x="serie", y="n", color="padrao", barmode="stack",
                           labels={"n": "Candidatos", "serie": "Ciclo eleitoral"})
                f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(f, use_container_width=True)
                por_ano = d.groupby("ano").agg(candidatos=("id_candidato", "nunique"),
                                               eleitos=("eleito", "sum")).reset_index()
                f2 = px.line(por_ano, x="ano", y=["candidatos", "eleitos"], markers=True)
                f2.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(f2, use_container_width=True)
            with aba2:
                termo = st.text_input("Nome de urna contém…")
                if termo:
                    achados = d[d["nome_urna"].str.contains(termo, case=False, na=False)]
                    ids = achados.groupby("id_candidato")["nome_urna"].first()
                    if ids.empty:
                        st.info("Nenhum candidato encontrado.")
                    else:
                        escolha = st.selectbox("Candidato", ids.index, format_func=lambda i: ids[i])
                        c = d[d["id_candidato"] == escolha].sort_values("ano")
                        f = px.scatter(c, x="ano", y="ordem", color="partido", symbol="eleito",
                                       hover_data=["cargo", "votos"], size_max=14,
                                       symbol_map={True: "star", False: "circle-open"})
                        f.update_traces(marker_size=14)
                        f.update_xaxes(dtick=2)
                        f.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)",
                                        yaxis_title="Nível do cargo (ordem hierárquica)")
                        st.plotly_chart(f, use_container_width=True)
                        st.dataframe(c[["ano", "cargo", "partido", "votos", "eleito"]],
                                     use_container_width=True, hide_index=True)
    except Exception as e:  # conexão, tabela ausente, rede…
        st.error(f"Erro: {e}")
