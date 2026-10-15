import { scaleLinear } from "d3-scale";
import { feature } from "topojson-client";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { GraficosLegenda, resumirLegendaPorPartido } from "./GraficosLegenda";
import { Feat, Mapa } from "./Mapa";
import { gerarLinhasMockLegenda, opcoesMockLegenda } from "./mockLegenda";
import { CORES_UF, corPartido } from "./coresEleitorais";

type Cat = { ufs: { cod: string; sigla: string; nome: string }[]; municipios: Record<string, { id: string; nome: string }[]> };
type Reg = Record<string, number | string | null>;
type Dados = { uf: string; ano: number; municipios: Record<string, Reg> };
type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type OpcaoLegenda = { ano: number; cargo: string };
type DadosUfLegenda = { uf: string; linhas: LinhaLegenda[] };
const COBERTOS = ["CE", "MA", "MS", "RJ", "RN", "RS"];
const SEM_MUNICIPIOS: { id: string; nome: string }[] = [];
const CINZA_SEM_REGISTRO = "#2b2b31", ROXO_SEM_VALOR = "#4a3d5c";
const escalaLegenda = scaleLinear<string>().domain([0, 15, 30]).range(["#795671", "#bc4d83", "#f03d94"]).clamp(true);

const json = async <T,>(u: string, signal?: AbortSignal): Promise<T> => {
  const r = await fetch(u, { signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};
const feats = (topo: any): Feat[] => (feature(topo, topo.objects[Object.keys(topo.objects)[0]]) as any).features;
const fmt = (v: unknown, d = 0, suf = "") =>
  typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: d }) + suf : "sem dado";

export function App() {
  const [visao, setVisao] = useState<"mapa" | "painel">("mapa");
  const [analise, setAnalise] = useState<"abstencao" | "legenda">("abstencao");
  const [mostrarMock, setMostrarMock] = useState(false);
  const [cat, setCat] = useState<Cat | null>(null);
  const [ufs, setUfs] = useState<Feat[]>([]);
  const [uf, setUf] = useState<string | null>(null);
  const [mun, setMun] = useState<string | null>(null);
  const [geoMun, setGeoMun] = useState<Record<string, Feat[]>>({});
  const [anos, setAnos] = useState<number[]>([]);
  const [ano, setAno] = useState<number | null>(null);
  const [dados, setDados] = useState<Dados | null>(null);
  const [status, setStatus] = useState<"ok" | "carregando" | "erro" | "api">("ok");
  const [erroGeo, setErroGeo] = useState("");
  const [opcoesLegenda, setOpcoesLegenda] = useState<OpcaoLegenda[]>([]);
  const [anoLegenda, setAnoLegenda] = useState<number | null>(null);
  const [cargo, setCargo] = useState("");
  const [partido, setPartido] = useState("");
  const [linhasLegenda, setLinhasLegenda] = useState<LinhaLegenda[]>([]);
  const [statusLegenda, setStatusLegenda] = useState<"ok" | "carregando" | "erro">("ok");
  const [dadosBrasil, setDadosBrasil] = useState<DadosUfLegenda[]>([]);
  const [statusBrasil, setStatusBrasil] = useState<"ok" | "carregando" | "erro">("ok");
  const cache = useRef(new Map<string, Dados>());

  useEffect(() => {  // base geográfica (estática) e anos disponíveis (API)
    json<Cat>("/geo/catalogo.json").then(setCat).catch(() => setErroGeo("Catálogo de municípios ausente. Rode scripts/preparar_malhas.py."));
    json<any>("/geo/br_ufs.json").then((t) => setUfs(feats(t))).catch(() => setErroGeo("Malha nacional ausente. Rode scripts/preparar_malhas.py."));
    json<{ anos: number[] }>("/api/anos").then((r) => { setAnos(r.anos); setAno(r.anos[r.anos.length - 1] ?? null); })
      .catch(() => setStatus("api"));
    json<{ opcoes: OpcaoLegenda[] }>("/api/legenda/opcoes").then((r) => {
      setOpcoesLegenda(r.opcoes);
      const preferida = r.opcoes.find((o) => o.ano === 2022 && o.cargo === "Deputado Federal") || r.opcoes[0];
      if (preferida) { setAnoLegenda(preferida.ano); setCargo(preferida.cargo); }
    }).catch(() => setStatusLegenda("erro"));
  }, []);

  useEffect(() => {  // malha municipal sob demanda, com cache
    if (!uf || geoMun[uf]) return;
    const ac = new AbortController();
    json<any>(`/geo/${uf}.json`, ac.signal).then((t) => setGeoMun((m) => ({ ...m, [uf]: feats(t) })))
      .catch((e) => e.name !== "AbortError" && setErroGeo(`Malha municipal de ${uf} indisponível.`));
    return () => ac.abort();
  }, [uf]);

  useEffect(() => {  // indicadores: respostas antigas são abortadas e ignoradas
    if (!uf || ano == null) return;
    const chave = `${uf}/${ano}`, hit = cache.current.get(chave);
    if (hit) { setDados(hit); setStatus("ok"); return; }
    const ac = new AbortController();
    setDados(null); setStatus("carregando");
    json<Dados>(`/api/q3/${uf}/${ano}`, ac.signal).then((d) => {
      if (ac.signal.aborted) return;
      cache.current.set(chave, d); setDados(d); setStatus("ok");
    }).catch((e) => e.name !== "AbortError" && setStatus("erro"));
    return () => ac.abort();
  }, [uf, ano]);

  useEffect(() => {
    if (mostrarMock || !uf || anoLegenda == null || !cargo) { setLinhasLegenda([]); return; }
    const ac = new AbortController(); setLinhasLegenda([]); setStatusLegenda("carregando");
    json<{ linhas: LinhaLegenda[] }>(`/api/legenda/${uf}/${anoLegenda}?cargo=${encodeURIComponent(cargo)}`, ac.signal)
      .then((r) => { setLinhasLegenda(r.linhas); setStatusLegenda("ok"); })
      .catch((e) => { if (e.name !== "AbortError") setStatusLegenda("erro"); });
    return () => ac.abort();
  }, [uf, anoLegenda, cargo, mostrarMock]);

  useEffect(() => {
    if (mostrarMock || uf || analise !== "legenda" || anoLegenda == null || !cargo) { setDadosBrasil([]); return; }
    const ac = new AbortController(); setDadosBrasil([]); setStatusBrasil("carregando");
    Promise.all(COBERTOS.map(async (sigla) => ({ uf: sigla, linhas: (await json<{ linhas: LinhaLegenda[] }>(`/api/legenda/${sigla}/${anoLegenda}?cargo=${encodeURIComponent(cargo)}`, ac.signal)).linhas })))
      .then((itens) => { if (!ac.signal.aborted) { setDadosBrasil(itens); setStatusBrasil("ok"); } })
      .catch((e) => { if (e.name !== "AbortError") setStatusBrasil("erro"); });
    return () => ac.abort();
  }, [mostrarMock, uf, analise, anoLegenda, cargo]);

  const siglas = useMemo(() => Object.fromEntries((cat?.ufs ?? []).map((u) => [u.cod, u.sigla])), [cat]);
  const lista = useMemo(() => uf ? cat?.municipios[uf] ?? SEM_MUNICIPIOS : cat ? COBERTOS.flatMap((sigla) => cat.municipios[sigla] ?? []) : SEM_MUNICIPIOS, [cat, uf]);
  const opcoesAtivas = mostrarMock ? opcoesMockLegenda : opcoesLegenda;
  const dadosUf = mostrarMock && anoLegenda != null && cat ? COBERTOS.map((sigla) => ({ uf: sigla, linhas: gerarLinhasMockLegenda(cat.municipios[sigla] ?? SEM_MUNICIPIOS, anoLegenda, cargo) })) : dadosBrasil;
  const linhasFonte = mostrarMock ? uf ? dadosUf.find((item) => item.uf === uf)?.linhas ?? [] : dadosUf.flatMap((item) => item.linhas) : uf ? linhasLegenda : dadosBrasil.flatMap((item) => item.linhas);
  const estadoLinhas = dadosUf.map((item) => {
    const linhas = item.linhas.filter((r) => !partido || r.id_partido === partido);
    const legenda = linhas.reduce((soma, r) => soma + r.votos_legenda, 0);
    const nominais = linhas.reduce((soma, r) => soma + r.votos_nominais, 0);
    return { uf: item.uf, legenda, percentual: legenda + nominais ? 100 * legenda / (legenda + nominais) : 0, temDados: linhas.length > 0 };
  });
  const nomes = useMemo(() => Object.fromEntries(lista.map((m) => [m.id, m.nome])), [lista]);
  const municipiosBusca = useMemo(() => Object.entries(cat?.municipios ?? {}).flatMap(([sigla, municipios]) =>
    municipios.map((item) => ({ ...item, uf: sigla }))), [cat]);
  const ufPorMunicipio = useMemo(() => Object.fromEntries(municipiosBusca.map((item) => [item.id, item.uf])), [municipiosBusca]);
  const selecionarUf = (sigla: string | null) => { setUf(sigla); setMun(null); };
  const selecionarMunicipio = (sigla: string, id: string) => { setUf(sigla); setMun(id); };
  const valido = dados && dados.uf === uf && dados.ano === ano ? dados : null;
  const valores = Object.values(valido?.municipios ?? {}).map((r) => r.abstencao_pct).filter((v): v is number => typeof v === "number");
  const [lo, hi] = [Math.min(...valores), Math.max(...valores)];
  const escala = valores.length ? scaleLinear<string>().domain([lo, hi]).range(["#2f4fbf", "#ff5a4d"]) : null;
  const partidos = [...new Map(linhasFonte.map((r) => [r.id_partido, r.partido])).entries()].sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  const linhasAtivas = linhasFonte.filter((r) => !partido || r.id_partido === partido);
  const historicoMock = useMemo(() => mostrarMock ? opcoesMockLegenda.filter((item) => item.cargo === cargo).map((item) => resumirLegendaPorPartido(item.ano, gerarLinhasMockLegenda(lista, item.ano, cargo).filter((r) => !mun || r.id_municipio === mun))) : undefined, [mostrarMock, lista, cargo, mun]);
  const porMunicipio = linhasAtivas.reduce((acc, r) => {
    const atual = acc.get(r.id_municipio) || { legenda: 0, nominais: 0 };
    atual.legenda += r.votos_legenda; atual.nominais += r.votos_nominais;
    acc.set(r.id_municipio, atual); return acc;
  }, new Map<string, { legenda: number; nominais: number }>());
  const linhasRecorte = linhasAtivas.filter((r) => !mun || r.id_municipio === mun);
  const totalLegenda = linhasRecorte.reduce((s, r) => s + r.votos_legenda, 0);
  const totalNominais = linhasRecorte.reduce((s, r) => s + r.votos_nominais, 0);
  const percentualLegenda = totalLegenda + totalNominais ? 100 * totalLegenda / (totalLegenda + totalNominais) : null;
  const rankingPartidos = [...linhasRecorte.reduce((acc, r) => {
    const atual = acc.get(r.id_partido) || { id: r.id_partido, nome: r.partido, votos: 0 };
    atual.votos += r.votos_legenda; acc.set(r.id_partido, atual); return acc;
  }, new Map<string, { id: string; nome: string; votos: number }>()).values()].sort((a, b) => b.votos - a.votos);
  const percentuaisMunicipios = [...porMunicipio.values()].map((r) => 100 * r.legenda / Math.max(1, r.legenda + r.nominais));
  const cor = (id: string) => {
    if (analise === "legenda") {
      const r = porMunicipio.get(id);
      if (!r) return CINZA_SEM_REGISTRO;
      const share = 100 * r.legenda / Math.max(1, r.legenda + r.nominais);
      return escalaLegenda(share);
    }
    const r = valido?.municipios[id];
    if (!r) return CINZA_SEM_REGISTRO;                          // sem registro eleitoral (ou carregando)
    const v = r.abstencao_pct;
    return typeof v === "number" && escala ? escala(v) : ROXO_SEM_VALOR;  // 0 é cor válida; null é outra
  };
  const corUf = (sigla: string) => {
    const item = estadoLinhas.find((r) => r.uf === sigla);
    return item?.temDados ? escalaLegenda(item.percentual) : undefined;
  };
  const descricaoUf = (sigla: string) => {
    const item = estadoLinhas.find((r) => r.uf === sigla);
    return item?.temDados ? `${sigla} — ${fmt(item.percentual, 1, "%")} de votos de legenda · ${fmt(item.legenda)} votos` : `${sigla} — sem dados disponíveis`;
  };
  const descricaoMun = (id: string) => {
    const registro = porMunicipio.get(id);
    const nome = nomes[id] || id;
    return registro ? `${nome} — ${fmt(100 * registro.legenda / Math.max(1, registro.legenda + registro.nominais), 1, "%")} de votos de legenda · ${fmt(registro.legenda)} votos` : `${nome} — sem dados disponíveis`;
  };
  const sel = mun && valido ? valido.municipios[mun] : undefined;
  const registros = Object.entries(valido?.municipios ?? {});
  const totalEleitorado = registros.reduce((s, [, r]) => s + (typeof r.eleitorado === "number" ? r.eleitorado : 0), 0);
  const totalAbstencoes = registros.reduce((s, [, r]) => s + (typeof r.abstencoes === "number" ? r.abstencoes : 0), 0);
  const taxaGeral = totalEleitorado ? 100 * totalAbstencoes / totalEleitorado : null;
  const ranking = registros.filter(([, r]) => typeof r.abstencao_pct === "number")
    .sort((a, b) => Number(b[1].abstencao_pct) - Number(a[1].abstencao_pct)).slice(0, 8);
  const faixas = [0, 10, 20, 30, 40, 50].map((inicio) => ({
    rotulo: inicio === 50 ? "50%+" : `${inicio}–${inicio + 10}%`,
    valor: valores.filter((v) => v >= inicio && (inicio === 50 || v < inicio + 10)).length,
  }));
  const faixasLegenda = [0, 5, 10, 15, 20, 25].map((inicio) => ({
    rotulo: inicio === 25 ? "25%+" : `${inicio}–${inicio + 5}%`,
    valor: percentuaisMunicipios.filter((v) => v >= inicio && (inicio === 25 || v < inicio + 5)).length,
  }));
  const faixasAtivas = analise === "legenda" ? faixasLegenda : faixas;
  const maxFaixaAtiva = Math.max(1, ...faixasAtivas.map((f) => f.valor));
  const anoAtivo = analise === "legenda" ? anoLegenda : ano;
  const nomeUf = cat?.ufs.find((item) => item.sigla === uf)?.nome || uf || "Brasil";
  const contexto = [nomeUf, mun ? nomes[mun] || mun : null].filter(Boolean).join(" / ");

  return (
    <div class={`layout ${visao === "painel" ? "layout-painel" : "layout-mapa"} ${analise === "legenda" ? "analysis-legenda" : "analysis-abstencao"} ${analise === "legenda" && mostrarMock ? "preview-mock" : ""}`}>
      <header class="app-header">
        <div class="app-header-main">
          <div class="view-heading"><span class="view-kicker">ELEIÇÕES BRASIL / {visao === "mapa" ? "MAPA" : "PAINEL"}{analise === "legenda" && mostrarMock ? " / DADOS SIMULADOS" : ""}</span><strong>{analise === "legenda" ? "Votos por legenda" : "Participação eleitoral"}</strong><span class="view-context">{contexto}</span></div>
          <div class="view-switch" role="group" aria-label="Modo de visualização">
            <button aria-pressed={visao === "mapa"} onClick={() => setVisao("mapa")}>◈ <span>Mapa completo</span></button>
            <button aria-pressed={visao === "painel"} onClick={() => setVisao("painel")}>▦ <span>Painel analítico</span></button>
          </div>
        </div>
        <div class="app-filter-row">
          <div class="analysis-switch" role="group" aria-label="Análise eleitoral">
            <button aria-pressed={analise === "abstencao"} onClick={() => setAnalise("abstencao")}>Abstenção</button>
            <button aria-pressed={analise === "legenda"} onClick={() => setAnalise("legenda")}>Votos por legenda</button>
          </div>
          <label>Estado <select value={uf || ""} onChange={(e) => selecionarUf((e.target as HTMLSelectElement).value || null)}><option value="">Brasil</option>{COBERTOS.map((sigla) => <option value={sigla}>{cat?.ufs.find((item) => item.sigla === sigla)?.nome || sigla} ({sigla})</option>)}</select></label>
          <label>Ano <select value={anoAtivo ?? ""} onChange={(e) => {
            const a = Number((e.target as HTMLSelectElement).value);
            if (analise === "legenda") { setAnoLegenda(a); setPartido(""); if (!opcoesAtivas.some((o) => o.ano === a && o.cargo === cargo)) setCargo(opcoesAtivas.find((o) => o.ano === a)?.cargo || ""); }
            else setAno(a);
          }} disabled={analise === "legenda" ? !opcoesAtivas.length : !anos.length}>
            {(analise === "legenda" ? [...new Set(opcoesAtivas.map((o) => o.ano))] : anos).map((a) => <option key={a} value={a}>{a}</option>)}</select></label>
          {analise === "legenda" && <><label>Cargo <select value={cargo} onChange={(e) => { setCargo((e.target as HTMLSelectElement).value); setPartido(""); }}>{opcoesAtivas.filter((o) => o.ano === anoLegenda).map((o) => <option value={o.cargo}>{o.cargo}</option>)}</select></label>
            <label class="global-party-filter"><span>Partido <small>todos os gráficos</small></span><select value={partido} onChange={(e) => setPartido((e.target as HTMLSelectElement).value)}><option value="">Todos</option>{partidos.map(([id, nome]) => <option value={id}>{nome}</option>)}</select></label></>}
          {analise === "legenda" && <button class="mock-toggle" aria-pressed={mostrarMock} onClick={() => { const ativar = !mostrarMock; setMostrarMock(ativar); setPartido(""); if (ativar) { setUf(uf || "MA"); setMun(null); setAnoLegenda(2022); setCargo("Deputado Federal"); setVisao("painel"); } else { const inicial = opcoesLegenda.find((o) => o.ano === 2022 && o.cargo === "Deputado Federal") || opcoesLegenda[0]; if (inicial) { setAnoLegenda(inicial.ano); setCargo(inicial.cargo); } } }}>{mostrarMock ? "Voltar aos dados reais" : "Usar dados de exemplo"}</button>}
          <button class="clear-filters" onClick={() => {
            selecionarUf(null); setPartido("");
            setAno(anos[anos.length - 1] ?? null);
            const inicial = opcoesAtivas.find((o) => o.ano === 2022 && o.cargo === "Deputado Federal") || opcoesAtivas[0];
            if (inicial) { setAnoLegenda(inicial.ano); setCargo(inicial.cargo); }
          }}>Limpar filtros</button>
        </div>
      </header>
      {visao === "painel" && analise === "legenda" && mostrarMock && <div class="mock-data-banner" role="status">Prévia com dados simulados — todos os indicadores e gráficos abaixo usam o arquivo de mock, não resultados do TSE.</div>}
      {visao === "painel" && <section class={`dash-kpis ${analise === "legenda" && partido ? "three-kpis" : ""}`} aria-label="Resumo eleitoral">
        {analise === "legenda" ? <>
          <article><span>Votos de legenda</span><strong>{(mostrarMock || (uf ? statusLegenda === "ok" : statusBrasil === "ok")) && linhasFonte.length ? fmt(totalLegenda) : "—"}</strong><small>{mun ? nomes[mun] : uf || "Seis UFs disponíveis"}</small><i class="kpi-line pink" /></article>
          <article><span>Participação no recorte</span><strong>{(mostrarMock || (uf ? statusLegenda === "ok" : statusBrasil === "ok")) && linhasFonte.length ? fmt(percentualLegenda, 1, "%") : "—"}</strong><small>Legenda entre votos partidários</small><i class="kpi-line violet" /></article>
          <article><span>Votos nominais</span><strong>{(mostrarMock || (uf ? statusLegenda === "ok" : statusBrasil === "ok")) && linhasFonte.length ? fmt(totalNominais) : "—"}</strong><small>Mesmo cargo e ano</small><i class="kpi-line cyan" /></article>
          {!partido && <article><span>Partido líder</span><strong>{rankingPartidos[0]?.nome || "—"}</strong><small>{rankingPartidos[0] ? `${fmt(rankingPartidos[0].votos)} votos de legenda` : "Sem dados"}</small><i class="kpi-line teal" style={rankingPartidos[0] ? { background: corPartido(rankingPartidos[0].id) } : undefined} /></article>}
        </> : <>
          <article><span>Eleitorado</span><strong>{uf && valido ? fmt(mun ? sel?.eleitorado : totalEleitorado) : "—"}</strong><small>{mun ? nomes[mun] : uf || "Selecione um estado"}</small><i class="kpi-line cyan" /></article>
          <article><span>Abstenções</span><strong>{uf && valido ? fmt(mun ? sel?.abstencoes : totalAbstencoes) : "—"}</strong><small>Pessoas que não votaram</small><i class="kpi-line pink" /></article>
          <article><span>Taxa de abstenção</span><strong>{uf && valido ? fmt(mun ? sel?.abstencao_pct : taxaGeral, 1, "%") : "—"}</strong><small>Participação no recorte</small><i class="kpi-line violet" /></article>
          <article><span>Municípios com dados</span><strong>{uf && valido ? fmt(registros.length) : "—"}</strong><small>{uf ? `Estado: ${uf}` : "Selecione um estado"}</small><i class="kpi-line teal" /></article>
        </>}
      </section>}
      <Mapa ufs={ufs} muns={uf ? geoMun[uf] ?? [] : []} uf={uf} siglas={siglas} cobertos={new Set(COBERTOS)}
        mun={mun} cor={cor} corUf={analise === "legenda" ? corUf : undefined} descricaoUf={analise === "legenda" ? descricaoUf : undefined} descricaoMun={analise === "legenda" ? descricaoMun : undefined} nomes={nomes} municipiosBusca={municipiosBusca} onUf={selecionarUf} onMun={setMun} onMunicipioBusca={selecionarMunicipio} />
      <aside>
        {erroGeo && <p class="aviso erro">{erroGeo}</p>}
        {analise === "abstencao" && status === "api" && <p class="aviso erro">API indisponível: mapa sem indicadores.</p>}
        {analise === "legenda" && !mostrarMock && statusLegenda === "erro" && <p class="aviso erro">Votos por legenda indisponíveis. Verifique a API e o banco.</p>}
        {!uf && <div class="empty-selection"><span>{analise === "legenda" ? "BRASIL · SEIS UFS" : "EXPLORAR O MAPA"}</span><h2>{analise === "legenda" ? "Visão geral" : "Selecione um lugar"}</h2><p>{analise === "legenda" ? "Compare os estados disponíveis no painel ou selecione uma UF no mapa para ver seus municípios." : "Busque um município no mapa, clique em um estado ou use o filtro acima."}</p></div>}
        {!uf && analise === "legenda" && <div class="legenda escala-uf"><strong>Percentual de votos de legenda</strong><div class="barra barra-legenda" /><span>0% → 30% ou mais</span><span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem dados neste recorte</span></div>}
        {!uf && analise === "legenda" && estadoLinhas.length > 0 && <div class="aside-state-compare"><h3>Participação por UF</h3>{estadoLinhas.map((item) => <button key={item.uf} onClick={() => selecionarUf(item.uf)}><span><i class="state-dot" style={{ background: CORES_UF[item.uf] }} />{item.uf}</span><i class="state-track"><b style={{ width: `${Math.min(100, item.percentual / 30 * 100)}%`, background: CORES_UF[item.uf] }} /></i><strong>{fmt(item.percentual, 1, "%")}</strong></button>)}<small>As cores identificam as UFs; no mapa, o rosa indica o percentual.</small></div>}
        {uf && <>
          <div class="aside-heading"><span>RECORTE ATUAL</span><h2>{mun ? nomes[mun] || mun : nomeUf}</h2><p>{mun ? "Detalhes do município selecionado" : "Busque um município diretamente no mapa"}</p></div>
          {analise === "abstencao" && status === "carregando" && <p class="aviso">Carregando indicadores…</p>}
          {analise === "abstencao" && status === "erro" && <p class="aviso erro">Erro ao consultar os indicadores.</p>}
          {analise === "legenda" && !mostrarMock && statusLegenda === "carregando" && <p class="aviso">Carregando votos…</p>}
          {analise === "abstencao" && mun && <section aria-live="polite"><h2>{nomes[mun]} <small>{uf}</small></h2>
            <p>Código IBGE: {mun}</p>
            {!valido ? null : !sel ? <p class="aviso">Sem registro de participação deste município em {ano}.</p> :
              <dl><dt>Abstenção</dt><dd>{fmt(sel.abstencao_pct, 2, "%")}</dd>
                <dt>Eleitorado</dt><dd>{fmt(sel.eleitorado)}</dd>
                <dt>População (2022)</dt><dd>{fmt(sel.populacao)}</dd>
                <dt>PIB per capita (2022)</dt><dd>{fmt(sel.pib_per_capita, 0)}</dd>
                <dt>IDHM (2010)</dt><dd>{fmt(sel.idhm, 3)}</dd></dl>}</section>}
          {analise === "legenda" && mun && <section aria-live="polite"><h2>{nomes[mun]} <small>{uf}</small></h2><p>Código IBGE: {mun}</p>
            <dl><dt>Votos de legenda</dt><dd>{fmt(porMunicipio.get(mun)?.legenda)}</dd><dt>Votos nominais</dt><dd>{fmt(porMunicipio.get(mun)?.nominais)}</dd><dt>Participação</dt><dd>{porMunicipio.has(mun) ? fmt(100 * porMunicipio.get(mun)!.legenda / Math.max(1, porMunicipio.get(mun)!.legenda + porMunicipio.get(mun)!.nominais), 1, "%") : "sem dado"}</dd></dl></section>}
          {analise === "legenda" && (mostrarMock || statusLegenda === "ok") && linhasFonte.length > 0 && <section class="aside-resumo-legenda"><h2>Leitura rápida</h2><p>{fmt(totalLegenda)} votos de legenda · {fmt(percentualLegenda, 1, "%")} do recorte</p><div class="aside-ratio" role="img" aria-label={`${fmt(percentualLegenda, 1, "%")} votos de legenda`}><i style={{ width: `${percentualLegenda ?? 0}%` }} /></div>{!partido && <><h3>Partidos com mais votos</h3>{rankingPartidos.slice(0, 3).map((item) => <div class="aside-partido" key={item.id}><span><i class="party-dot" style={{ background: corPartido(item.id) }} />{item.nome}</span><strong>{fmt(item.votos)}</strong></div>)}</>}</section>}
          {analise === "abstencao" ? <div class="legenda"><strong>Abstenção (%) em {ano} — Q3</strong>
            <div class="barra" /><span>{valores.length ? `${lo.toFixed(1)} → ${hi.toFixed(1)}` : "—"}</span>
            <span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem registro</span>
            <span><i style={{ background: ROXO_SEM_VALOR }} /> registro sem valor</span>
            <span>Valor 0 usa a cor mínima da escala.</span></div> : <div class="legenda"><strong>Votos por legenda (%) em {anoLegenda}</strong>
            <div class="barra barra-legenda" /><span>0% → 30% ou mais</span>
            <span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem registro</span>
            <span>Percentual dos votos de legenda entre votos de legenda e nominais.</span></div>}</>}
      </aside>
      {visao === "painel" && <section class={`dash-charts ${analise === "legenda" && partido ? "single-chart" : ""}`} aria-label="Análises municipais">
        {!(analise === "legenda" && partido) && <article class="dash-chart-card"><h2>{analise === "legenda" ? "Ranking de partidos" : "Taxas mais altas"}</h2><p>{analise === "legenda" ? "Votos de legenda no recorte" : "Municípios do recorte selecionado"}</p>
          {analise === "legenda" ? rankingPartidos.length ? <div class="dash-ranking">{rankingPartidos.slice(0, 8).map((r) => <div class="dash-rank-row" key={r.id}><span><i class="party-dot" style={{ background: corPartido(r.id) }} />{r.nome}</span><i><b style={{ width: `${100 * r.votos / Math.max(1, rankingPartidos[0].votos)}%`, background: corPartido(r.id) }} /></i><strong>{fmt(r.votos)}</strong></div>)}</div> : <div class="dash-empty">Selecione um estado com votos para ver o ranking.</div>
            : ranking.length ? <div class="dash-ranking">{ranking.map(([id, r]) => <button key={id} onClick={() => setMun(id)}><span>{nomes[id] || id}</span><i><b style={{ width: `${Math.min(100, Number(r.abstencao_pct) * 2)}%` }} /></i><strong>{fmt(r.abstencao_pct, 1, "%")}</strong></button>)}</div> : <div class="dash-empty">Selecione um estado com dados para ver o ranking.</div>}</article>}
        <article class="dash-chart-card"><h2>{analise === "legenda" ? "Distribuição dos votos de legenda" : "Distribuição da abstenção"}</h2><p>Quantidade de municípios por faixa percentual</p>{(analise === "legenda" ? percentuaisMunicipios.length : valores.length) ? <div class="dash-distribution">{faixasAtivas.map((f) => <div key={f.rotulo}><span>{f.valor}</span><i style={{ height: `${Math.max(3, 100 * f.valor / maxFaixaAtiva)}%` }} /><small>{f.rotulo}</small></div>)}</div> : <div class="dash-empty">Os dados aparecem após selecionar um estado.</div>}</article>
      </section>}
      {visao === "painel" && analise === "legenda" && !uf && <section class="state-compare dash-chart-card" aria-label="Comparação entre estados disponíveis"><h2>Brasil · comparação entre estados</h2><p>Participação dos votos de legenda entre votos de legenda e nominais · seis UFs disponíveis · {cargo} {anoLegenda}</p>{statusBrasil === "erro" && !mostrarMock ? <div class="dash-empty">Não foi possível consultar os estados. Verifique a conexão com o banco.</div> : !estadoLinhas.length ? <div class="dash-empty">Carregando dados dos estados disponíveis…</div> : <div class="state-compare-list">{estadoLinhas.map((item) => <button key={item.uf} onClick={() => selecionarUf(item.uf)}><strong><i class="state-dot" style={{ background: CORES_UF[item.uf] }} />{cat?.ufs.find((u) => u.sigla === item.uf)?.nome || item.uf}<small>{item.uf}</small></strong><i><b style={{ width: `${Math.min(100, item.percentual / 30 * 100)}%`, background: CORES_UF[item.uf] }} /></i><span>{fmt(item.percentual, 1, "%")}<small>{fmt(item.legenda)} votos de legenda</small></span></button>)}</div>}</section>}
      {visao === "painel" && analise === "legenda" && <GraficosLegenda uf={uf} mun={mun} cargo={cargo} partido={partido} ano={anoLegenda} opcoes={opcoesAtivas} linhas={linhasAtivas} carregando={!mostrarMock && (uf ? statusLegenda !== "ok" : statusBrasil !== "ok")} onMunicipio={selecionarMunicipio} ufPorMunicipio={ufPorMunicipio} ufsDisponiveis={COBERTOS} historicoMock={historicoMock} />}
    </div>
  );
}
