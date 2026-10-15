import { scaleLinear } from "d3-scale";
import { feature } from "topojson-client";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { GraficosLegenda, HistoricoAno, resumirLegendaPorPartido } from "./GraficosLegenda";
import { Feat, Mapa } from "./Mapa";
import { gerarLinhasMockLegenda, opcoesMockLegenda } from "./mockLegenda";
import { CORES_UF, corPartido } from "./coresEleitorais";
import { PainelPublicidade } from "./PainelQ9";

type Cat = { ufs: { cod: string; sigla: string; nome: string }[]; municipios: Record<string, { id: string; nome: string }[]> };
type Reg = Record<string, number | string | null>;
type Dados = { uf: string; ano: number; municipios: Record<string, Reg> };
type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type OpcaoLegenda = { ano: number; cargo: string };
type DadosUfLegenda = { uf: string; linhas: LinhaLegenda[] };
type DadosAnoUfLegenda = DadosUfLegenda & { ano: number };
const COBERTOS = ["CE", "MA", "MS", "RJ", "RN", "RS"];
const SEM_MUNICIPIOS: { id: string; nome: string }[] = [];
const SEM_OPCOES_LEGENDA: OpcaoLegenda[] = [];
const CINZA_SEM_REGISTRO = "#2b2b31", ROXO_SEM_VALOR = "#4a3d5c";
const CORES_INTENSIDADE_UF = ["#735a9e", "#b54c9d", "#ff68a8"];

const json = async <T,>(u: string, signal?: AbortSignal): Promise<T> => {
  const r = await fetch(u, { signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};
const feats = (topo: any): Feat[] => (feature(topo, topo.objects[Object.keys(topo.objects)[0]]) as any).features;
const fmt = (v: unknown, d = 0, suf = "") =>
  typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: d }) + suf : "sem dado";
const somarLinhasLegenda = (linhas: LinhaLegenda[]): LinhaLegenda[] => {
  const agrupadas = new Map<string, LinhaLegenda>();
  for (const item of linhas) {
    const chave = `${item.id_municipio}/${item.id_partido}`;
    const atual = agrupadas.get(chave);
    if (atual) {
      atual.votos_legenda += item.votos_legenda;
      atual.votos_nominais += item.votos_nominais;
    } else agrupadas.set(chave, { ...item });
  }
  return [...agrupadas.values()];
};

export function App() {
  const [analise, setAnalise] = useState<"abstencao" | "legenda" | "publicidade">("abstencao");
  const [todosAnosLegenda, setTodosAnosLegenda] = useState(false);
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
  const [dadosHistoricos, setDadosHistoricos] = useState<DadosAnoUfLegenda[]>([]);
  const [statusHistorico, setStatusHistorico] = useState<"ok" | "carregando" | "erro">("ok");
  const [chaveHistorico, setChaveHistorico] = useState("");
  const chaveHistoricoAtual = `${cargo}|${uf ?? "BR"}|${opcoesLegenda.filter((item) => item.cargo === cargo).map((item) => item.ano).join(",")}`;
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
    if (mostrarMock || todosAnosLegenda || !uf || anoLegenda == null || !cargo) { setLinhasLegenda([]); return; }
    const ac = new AbortController(); setLinhasLegenda([]); setStatusLegenda("carregando");
    json<{ linhas: LinhaLegenda[] }>(`/api/legenda/${uf}/${anoLegenda}?cargo=${encodeURIComponent(cargo)}`, ac.signal)
      .then((r) => { setLinhasLegenda(r.linhas); setStatusLegenda("ok"); })
      .catch((e) => { if (e.name !== "AbortError") setStatusLegenda("erro"); });
    return () => ac.abort();
  }, [uf, anoLegenda, cargo, mostrarMock, todosAnosLegenda]);

  useEffect(() => {
    if (mostrarMock || todosAnosLegenda || uf || analise !== "legenda" || anoLegenda == null || !cargo) { setDadosBrasil([]); return; }
    const ac = new AbortController(); setDadosBrasil([]); setStatusBrasil("carregando");
    Promise.all(COBERTOS.map(async (sigla) => ({ uf: sigla, linhas: (await json<{ linhas: LinhaLegenda[] }>(`/api/legenda/${sigla}/${anoLegenda}?cargo=${encodeURIComponent(cargo)}`, ac.signal)).linhas })))
      .then((itens) => { if (!ac.signal.aborted) { setDadosBrasil(itens); setStatusBrasil("ok"); } })
      .catch((e) => { if (e.name !== "AbortError") setStatusBrasil("erro"); });
    return () => ac.abort();
  }, [mostrarMock, todosAnosLegenda, uf, analise, anoLegenda, cargo]);

  useEffect(() => {
    if (!todosAnosLegenda || mostrarMock || analise !== "legenda" || !cargo) { setDadosHistoricos([]); return; }
    const anosCargo = [...new Set(opcoesLegenda.filter((item) => item.cargo === cargo).map((item) => item.ano))];
    if (!anosCargo.length) { setChaveHistorico(chaveHistoricoAtual); setDadosHistoricos([]); setStatusHistorico("erro"); return; }
    const ac = new AbortController();
    setChaveHistorico(chaveHistoricoAtual); setDadosHistoricos([]); setStatusHistorico("carregando");
    const ufsConsulta = uf ? [uf] : COBERTOS;
    Promise.all(anosCargo.flatMap((anoConsulta) => ufsConsulta.map(async (sigla) => ({
      ano: anoConsulta,
      uf: sigla,
      linhas: (await json<{ linhas: LinhaLegenda[] }>(`/api/legenda/${sigla}/${anoConsulta}?cargo=${encodeURIComponent(cargo)}`, ac.signal)).linhas,
    })))).then((itens) => { if (!ac.signal.aborted) { setDadosHistoricos(itens); setStatusHistorico("ok"); } })
      .catch((e) => { if (e.name !== "AbortError") setStatusHistorico("erro"); });
    return () => ac.abort();
  }, [todosAnosLegenda, mostrarMock, analise, cargo, uf, opcoesLegenda, chaveHistoricoAtual]);

  const siglas = useMemo(() => Object.fromEntries((cat?.ufs ?? []).map((u) => [u.cod, u.sigla])), [cat]);
  const lista = useMemo(() => uf ? cat?.municipios[uf] ?? SEM_MUNICIPIOS : cat ? COBERTOS.flatMap((sigla) => cat.municipios[sigla] ?? []) : SEM_MUNICIPIOS, [cat, uf]);
  const opcoesAtivas = opcoesLegenda.length ? opcoesLegenda : mostrarMock ? opcoesMockLegenda : SEM_OPCOES_LEGENDA;
  const anosCargo = [...new Set(opcoesAtivas.filter((item) => item.cargo === cargo).map((item) => item.ano))].sort((a, b) => a - b);
  const periodoLegenda = todosAnosLegenda && anosCargo.length > 1 ? `soma de ${anosCargo.join(", ")}` : `${anosCargo[0] ?? anoLegenda ?? "—"}`;
  const dadosHistoricosMock = useMemo((): DadosAnoUfLegenda[] => {
    if (!mostrarMock || !cat || !todosAnosLegenda) return [];
    return opcoesAtivas.filter((item) => item.cargo === cargo).flatMap((item) => COBERTOS.map((sigla) => ({
      ano: item.ano, uf: sigla, linhas: gerarLinhasMockLegenda(cat.municipios[sigla] ?? SEM_MUNICIPIOS, item.ano, cargo),
    })));
  }, [mostrarMock, cat, todosAnosLegenda, cargo, opcoesAtivas]);
  const dadosHistoricosAtivos = mostrarMock ? dadosHistoricosMock : chaveHistorico === chaveHistoricoAtual ? dadosHistoricos : [];
  const dadosUf = todosAnosLegenda
    ? dadosHistoricosAtivos.length ? (uf ? [uf] : COBERTOS).map((sigla) => ({ uf: sigla, linhas: somarLinhasLegenda(dadosHistoricosAtivos.filter((item) => item.uf === sigla).flatMap((item) => item.linhas)) })) : []
    : mostrarMock && anoLegenda != null && cat ? COBERTOS.map((sigla) => ({ uf: sigla, linhas: gerarLinhasMockLegenda(cat.municipios[sigla] ?? SEM_MUNICIPIOS, anoLegenda, cargo) })) : dadosBrasil;
  const linhasFonte = mostrarMock || todosAnosLegenda ? uf ? dadosUf.find((item) => item.uf === uf)?.linhas ?? [] : dadosUf.flatMap((item) => item.linhas) : uf ? linhasLegenda : dadosBrasil.flatMap((item) => item.linhas);
  const estadoLinhas = dadosUf.map((item) => {
    const linhas = item.linhas.filter((r) => !partido || r.id_partido === partido);
    const legenda = linhas.reduce((soma, r) => soma + r.votos_legenda, 0);
    const nominais = linhas.reduce((soma, r) => soma + r.votos_nominais, 0);
    return { uf: item.uf, legenda, percentual: legenda + nominais ? 100 * legenda / (legenda + nominais) : 0, temDados: legenda + nominais > 0 };
  });
  const percentuaisUf = estadoLinhas.filter((item) => item.temDados).map((item) => item.percentual);
  const totalLegendaUfs = estadoLinhas.reduce((soma, item) => soma + item.legenda, 0);
  const menorUf = Math.min(...percentuaisUf), maiorUf = Math.max(...percentuaisUf);
  const escalaIntensidadeUf = percentuaisUf.length ? scaleLinear<string>()
    .domain(menorUf === maiorUf ? [menorUf - 1, menorUf, menorUf + 1] : [menorUf, (menorUf + maiorUf) / 2, maiorUf])
    .range(CORES_INTENSIDADE_UF).clamp(true) : null;
  const larguraComparativaUf = (percentual: number) => maiorUf - menorUf < 0.1 ? 60 : 20 + 80 * (percentual - menorUf) / (maiorUf - menorUf);
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
  const historicoMock = useMemo(() => mostrarMock ? opcoesAtivas.filter((item) => item.cargo === cargo).map((item) => resumirLegendaPorPartido(item.ano, gerarLinhasMockLegenda(lista, item.ano, cargo).filter((r) => !mun || r.id_municipio === mun))) : undefined, [mostrarMock, lista, cargo, mun, opcoesAtivas]);
  const historicoExterno: HistoricoAno[] | undefined = todosAnosLegenda && !mostrarMock
    ? anosCargo.map((anoConsulta) => resumirLegendaPorPartido(anoConsulta, dadosHistoricosAtivos.filter((item) => item.ano === anoConsulta).flatMap((item) => item.linhas).filter((item) => !mun || item.id_municipio === mun)))
    : undefined;
  const dadosProntosLegenda = mostrarMock ? !!cat : todosAnosLegenda ? statusHistorico === "ok" && chaveHistorico === chaveHistoricoAtual && dadosHistoricosAtivos.length > 0 : uf ? statusLegenda === "ok" : statusBrasil === "ok";
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
  const percentuaisMunicipios = [...porMunicipio.values()].filter((r) => r.legenda + r.nominais > 0).map((r) => 100 * r.legenda / (r.legenda + r.nominais));
  const votosLegendaEstado = uf ? [...porMunicipio.values()].reduce((soma, r) => soma + r.legenda, 0) : 0;
  const votosNominaisEstado = uf ? [...porMunicipio.values()].reduce((soma, r) => soma + r.nominais, 0) : 0;
  const participacaoEstado = votosLegendaEstado + votosNominaisEstado > 0 ? 100 * votosLegendaEstado / (votosLegendaEstado + votosNominaisEstado) : null;
  const municipiosPorParticipacao = uf ? [...porMunicipio.entries()]
    .filter(([, r]) => r.legenda + r.nominais > 0)
    .map(([id, r]) => ({ id, percentual: 100 * r.legenda / (r.legenda + r.nominais), legenda: r.legenda }))
    .sort((a, b) => b.percentual - a.percentual || b.legenda - a.legenda) : [];
  const acimaMediaEstado = participacaoEstado === null ? 0 : municipiosPorParticipacao.filter((item) => item.percentual > participacaoEstado).length;
  const menorMunicipio = Math.min(...percentuaisMunicipios), maiorMunicipio = Math.max(...percentuaisMunicipios);
  const escalaIntensidadeMunicipio = percentuaisMunicipios.length ? scaleLinear<string>()
    .domain(menorMunicipio === maiorMunicipio ? [menorMunicipio - 1, menorMunicipio, menorMunicipio + 1] : [menorMunicipio, (menorMunicipio + maiorMunicipio) / 2, maiorMunicipio])
    .range(CORES_INTENSIDADE_UF).clamp(true) : null;
  const cor = (id: string) => {
    if (analise === "legenda") {
      const r = porMunicipio.get(id);
      if (!r || r.legenda + r.nominais === 0) return CINZA_SEM_REGISTRO;
      const share = 100 * r.legenda / (r.legenda + r.nominais);
      return escalaIntensidadeMunicipio?.(share) ?? CINZA_SEM_REGISTRO;
    }
    const r = valido?.municipios[id];
    if (!r) return CINZA_SEM_REGISTRO;                          // sem registro eleitoral (ou carregando)
    const v = r.abstencao_pct;
    return typeof v === "number" && escala ? escala(v) : ROXO_SEM_VALOR;  // 0 é cor válida; null é outra
  };
  const corUf = (sigla: string) => {
    const item = estadoLinhas.find((r) => r.uf === sigla);
    return item?.temDados ? escalaIntensidadeUf?.(item.percentual) : undefined;
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

  if (analise === "publicidade") return <PainelPublicidade onAnalise={setAnalise} ufInicial={uf} />;

  const legendaMapa = analise === "abstencao" ? <div class="legenda"><strong>Abstenção (%) em {ano} · Q3</strong>
    <div class="barra" /><span>{valores.length ? `${lo.toFixed(1)} → ${hi.toFixed(1)}` : "Aguardando dados"}</span>
    <span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem registro</span>
    <span><i style={{ background: ROXO_SEM_VALOR }} /> registro sem valor</span></div>
    : !uf ? <div class="legenda"><strong>Intensidade de votos de legenda</strong>
      <div class="barra" style={{ background: `linear-gradient(90deg, ${CORES_INTENSIDADE_UF.join(", ")})` }} />
      <span>{percentuaisUf.length ? `${fmt(menorUf, 1, "%")} → ${fmt(maiorUf, 1, "%")}` : "Aguardando dados das UFs"}</span>
      <span>Escala relativa entre as UFs neste recorte.</span>
      <span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem dados neste recorte</span></div>
    : <div class="legenda"><strong>Votos de legenda (%)</strong>
      <div class="barra" style={{ background: `linear-gradient(90deg, ${CORES_INTENSIDADE_UF.join(", ")})` }} />
      <span>{percentuaisMunicipios.length ? `${fmt(menorMunicipio, 1, "%")} → ${fmt(maiorMunicipio, 1, "%")}` : "Aguardando dados dos municípios"}</span>
      <span>Cores relativas aos municípios · <i style={{ background: CINZA_SEM_REGISTRO }} /> sem dados</span></div>;

  return (
    <div class={`layout layout-painel ${analise === "legenda" ? "analysis-legenda" : "analysis-abstencao"} ${analise === "legenda" && mun ? "municipio-selecionado" : ""} ${analise === "legenda" && mostrarMock ? "preview-mock" : ""}`}>
      <header class="app-header">
        <div class="app-header-main">
          <div class="view-heading"><span class="view-kicker">ELEIÇÕES BRASIL / PAINEL{analise === "legenda" && mostrarMock ? " / DADOS SIMULADOS" : ""}</span><strong>{analise === "legenda" ? "Votos por legenda" : "Participação eleitoral"}</strong><div class="view-context" aria-live="polite"><span>{mun ? `${nomes[mun] || mun} · ${nomeUf} (${uf})` : uf ? `${nomeUf} (${uf})` : analise === "legenda" ? "Brasil · UFs disponíveis" : "Brasil"}</span>{analise === "legenda" && mun && <button type="button" onClick={() => setMun(null)}>← Voltar ao estado</button>}</div></div>
        </div>
        <div class="app-filter-row">
          <div class="analysis-switch" role="group" aria-label="Análise eleitoral">
            <button aria-pressed={analise === "abstencao"} onClick={() => setAnalise("abstencao")}>Abstenção</button>
            <button aria-pressed={analise === "legenda"} onClick={() => setAnalise("legenda")}>Votos por legenda</button>
            <button aria-pressed={false} onClick={() => setAnalise("publicidade")}>Publicidade</button>
          </div>
          <label>Estado <select value={uf || ""} onChange={(e) => selecionarUf((e.target as HTMLSelectElement).value || null)}><option value="">Brasil</option>{COBERTOS.map((sigla) => <option value={sigla}>{cat?.ufs.find((item) => item.sigla === sigla)?.nome || sigla} ({sigla})</option>)}</select></label>
          <label>Ano <select value={analise === "legenda" && todosAnosLegenda ? "todos" : anoAtivo ?? ""} onChange={(e) => {
            const valor = (e.target as HTMLSelectElement).value;
            if (analise === "legenda" && valor === "todos") { setTodosAnosLegenda(true); setPartido(""); return; }
            const a = Number(valor);
            if (analise === "legenda") { setTodosAnosLegenda(false); setAnoLegenda(a); setPartido(""); if (!opcoesAtivas.some((o) => o.ano === a && o.cargo === cargo)) setCargo(opcoesAtivas.find((o) => o.ano === a)?.cargo || ""); }
            else setAno(a);
          }} disabled={analise === "legenda" ? !opcoesAtivas.length : !anos.length}>
            {analise === "legenda" && <option value="todos">Todos os anos</option>}
            {(analise === "legenda" ? [...new Set(opcoesAtivas.map((o) => o.ano))].sort((a, b) => b - a) : anos).map((a) => <option key={a} value={a}>{a}</option>)}</select></label>
          {analise === "legenda" && <><label>Cargo <select value={cargo} disabled={!opcoesAtivas.length} onChange={(e) => { setCargo((e.target as HTMLSelectElement).value); setPartido(""); }}>{(todosAnosLegenda ? [...new Map(opcoesAtivas.map((o) => [o.cargo, o])).values()] : opcoesAtivas.filter((o) => o.ano === anoLegenda)).sort((a, b) => a.cargo.localeCompare(b.cargo, "pt-BR")).map((o) => <option key={`${o.ano}-${o.cargo}`} value={o.cargo}>{o.cargo}</option>)}</select></label>
            <label class="global-party-filter"><span>Partido <small>todos os gráficos</small></span><select value={partido} onChange={(e) => setPartido((e.target as HTMLSelectElement).value)}><option value="">Todos</option>{partidos.map(([id, nome]) => <option value={id}>{nome}</option>)}</select></label></>}
          {analise === "legenda" && <button class="mock-toggle" aria-pressed={mostrarMock} onClick={() => {
            const proximasOpcoes = mostrarMock ? opcoesLegenda : opcoesLegenda.length ? opcoesLegenda : opcoesMockLegenda;
            if (!(todosAnosLegenda ? proximasOpcoes.some((o) => o.cargo === cargo) : proximasOpcoes.some((o) => o.ano === anoLegenda && o.cargo === cargo))) {
              const inicial = proximasOpcoes.find((o) => o.ano === 2022 && o.cargo === "Deputado Federal") || proximasOpcoes[0];
              setAnoLegenda(inicial?.ano ?? null); setCargo(inicial?.cargo ?? "");
            }
            setMostrarMock(!mostrarMock); setPartido("");
          }}>{mostrarMock ? "Voltar aos dados reais" : "Usar dados de exemplo"}</button>}
          <button class="clear-filters" onClick={() => {
            selecionarUf(null); setPartido(""); setTodosAnosLegenda(false);
            setAno(anos[anos.length - 1] ?? null);
            const inicial = opcoesAtivas.find((o) => o.ano === 2022 && o.cargo === "Deputado Federal") || opcoesAtivas[0];
            setAnoLegenda(inicial?.ano ?? null); setCargo(inicial?.cargo ?? "");
          }}>Limpar filtros</button>
        </div>
      </header>
      {analise === "legenda" && mun && (erroGeo || (!mostrarMock && (todosAnosLegenda ? statusHistorico === "erro" : statusLegenda === "erro"))) && <div class="panel-status" role="alert">{erroGeo || "Não foi possível consultar os votos deste município. Verifique a API e o banco."}</div>}
      {analise === "legenda" && mostrarMock && <div class="mock-data-banner" role="status">Prévia com dados simulados — os indicadores e gráficos usam o arquivo de mock, não resultados do TSE.</div>}
      <section class={`dash-kpis ${analise === "legenda" ? "three-kpis" : ""}`} aria-label="Resumo eleitoral">
        {analise === "legenda" ? <>
          <article><span>Votos de legenda</span><strong>{dadosProntosLegenda && linhasFonte.length ? fmt(totalLegenda) : "—"}</strong><small>{todosAnosLegenda ? periodoLegenda : mun ? "Neste município" : uf ? "Neste estado" : "Nas UFs disponíveis"}</small><i class="kpi-line pink" /></article>
          <article><span>Participação no recorte</span><strong>{dadosProntosLegenda && linhasFonte.length ? fmt(percentualLegenda, 1, "%") : "—"}</strong><small>{mun && participacaoEstado !== null && percentualLegenda !== null ? `${nomeUf}: ${fmt(participacaoEstado, 1, "%")} · município ${percentualLegenda > participacaoEstado ? "acima" : percentualLegenda < participacaoEstado ? "abaixo" : "igual"}` : "Entre votos para partidos ou candidatos"}</small><i class="kpi-line violet" /></article>
          <article><span>Votos nominais</span><strong>{dadosProntosLegenda && linhasFonte.length ? fmt(totalNominais) : "—"}</strong><small>{todosAnosLegenda ? anosCargo.length > 1 ? "Mesmo cargo · soma dos anos" : `Mesmo cargo · ${periodoLegenda}` : "Mesmo cargo e ano"}</small><i class="kpi-line cyan" /></article>
        </> : <>
          <article><span>Eleitorado</span><strong>{uf && valido ? fmt(mun ? sel?.eleitorado : totalEleitorado) : "—"}</strong><small>{mun ? nomes[mun] : uf || "Selecione um estado"}</small><i class="kpi-line cyan" /></article>
          <article><span>Abstenções</span><strong>{uf && valido ? fmt(mun ? sel?.abstencoes : totalAbstencoes) : "—"}</strong><small>Pessoas que não votaram</small><i class="kpi-line pink" /></article>
          <article><span>Taxa de abstenção</span><strong>{uf && valido ? fmt(mun ? sel?.abstencao_pct : taxaGeral, 1, "%") : "—"}</strong><small>Participação no recorte</small><i class="kpi-line violet" /></article>
          <article><span>Municípios com dados</span><strong>{uf && valido ? fmt(registros.length) : "—"}</strong><small>{uf ? `Estado: ${uf}` : "Selecione um estado"}</small><i class="kpi-line teal" /></article>
        </>}
      </section>
      <Mapa ufs={ufs} muns={uf ? geoMun[uf] ?? [] : []} uf={uf} siglas={siglas} cobertos={new Set(COBERTOS)}
        mun={mun} cor={cor} corUf={analise === "legenda" ? corUf : undefined} descricaoUf={analise === "legenda" ? descricaoUf : undefined} descricaoMun={analise === "legenda" ? descricaoMun : undefined} nomes={nomes} municipiosBusca={municipiosBusca} onUf={selecionarUf} onMun={setMun} onMunicipioBusca={selecionarMunicipio} legendaMapa={legendaMapa} />
      {!(analise === "legenda" && mun) && <aside>
        {erroGeo && <p class="aviso erro">{erroGeo}</p>}
        {analise === "abstencao" && status === "api" && <p class="aviso erro">API indisponível: mapa sem indicadores.</p>}
        {analise === "legenda" && uf && !todosAnosLegenda && !mostrarMock && statusLegenda === "erro" && <p class="aviso erro">Votos por legenda indisponíveis. Verifique a API e o banco.</p>}
        {analise === "legenda" && !uf && !todosAnosLegenda && !mostrarMock && statusBrasil === "erro" && <p class="aviso erro">Não foi possível consultar os dados das UFs. Verifique a API e o banco.</p>}
        {analise === "legenda" && todosAnosLegenda && !mostrarMock && chaveHistorico === chaveHistoricoAtual && statusHistorico === "erro" && <p class="aviso erro">Não foi possível consultar todos os anos disponíveis.</p>}
        {!uf && analise !== "legenda" && <div class="empty-selection"><span>EXPLORAR O MAPA</span><h2>Selecione um lugar</h2><p>Busque um município no mapa, clique em um estado ou use o filtro acima.</p></div>}
        {!uf && analise === "legenda" && estadoLinhas.length > 0 && <div class="aside-state-compare"><h3>Participação por UF</h3><p class="aside-state-total"><span>Votos de legenda · {percentuaisUf.length} UFs</span><strong>{percentuaisUf.length ? fmt(totalLegendaUfs) : "—"}</strong></p>{estadoLinhas.map((item) => <button key={item.uf} onClick={() => selecionarUf(item.uf)} aria-label={`Ver ${item.uf}: ${item.temDados ? `${fmt(item.percentual, 1, "%")}, ${fmt(item.legenda)} votos de legenda` : "sem dados"}`}><span><i class="state-dot" style={{ background: CORES_UF[item.uf] }} />{item.uf}</span><i class="state-track"><b style={{ width: `${item.temDados ? larguraComparativaUf(item.percentual) : 0}%`, background: CORES_UF[item.uf] }} /></i><span class="aside-state-values"><strong>{item.temDados ? fmt(item.percentual, 1, "%") : "—"}</strong><small>{item.temDados ? `${fmt(item.legenda)} votos` : "Sem dados"}</small></span></button>)}<small>Barras relativas à faixa observada · cores identificam as UFs.</small></div>}
        {analise === "legenda" && uf && <section class="aside-context-insights" aria-label="Comparação dos municípios"><h2>Comparação dos municípios</h2>
          {dadosProntosLegenda && municipiosPorParticipacao.length ? <>
            <div class="insight-above"><span>Municípios acima do percentual estadual</span><strong>{acimaMediaEstado} <small>de {municipiosPorParticipacao.length}</small></strong><i role="img" aria-label={`${acimaMediaEstado} de ${municipiosPorParticipacao.length} municípios acima do percentual estadual`}><b style={{ width: `${100 * acimaMediaEstado / municipiosPorParticipacao.length}%` }} /></i><small>Média estadual: {fmt(participacaoEstado, 1, "%")} dos votos foram de legenda.</small></div>
            <div class="insight-extremes"><h3>Maior participação</h3>{municipiosPorParticipacao.slice(0, 2).map((item) => <button type="button" key={item.id} onClick={() => setMun(item.id)}><span>{nomes[item.id] || item.id}</span><strong>{fmt(item.percentual, 1, "%")}</strong></button>)}
              <h3>Menor participação</h3>{[...municipiosPorParticipacao].reverse().slice(0, 2).map((item) => <button type="button" key={item.id} onClick={() => setMun(item.id)}><span>{nomes[item.id] || item.id}</span><strong>{fmt(item.percentual, 1, "%")}</strong></button>)}</div>
          </> : <p class="insight-empty">Os dados de comparação aparecerão após a consulta.</p>}
          <button type="button" class="insight-back" onClick={() => selecionarUf(null)}>← Voltar para o Brasil</button>
        </section>}
        {uf && <>
          {analise === "abstencao" && status === "carregando" && <p class="aviso">Carregando indicadores…</p>}
          {analise === "abstencao" && status === "erro" && <p class="aviso erro">Erro ao consultar os indicadores.</p>}
          {analise === "legenda" && !mostrarMock && (todosAnosLegenda ? statusHistorico : statusLegenda) === "carregando" && <p class="aviso">Carregando votos…</p>}
          {analise === "abstencao" && mun && <section aria-live="polite" aria-label="Indicadores do município"><p>Código IBGE: {mun}</p>
            {!valido ? null : !sel ? <p class="aviso">Sem registro de participação deste município em {ano}.</p> :
              <dl><dt>Abstenção</dt><dd>{fmt(sel.abstencao_pct, 2, "%")}</dd>
                <dt>Eleitorado</dt><dd>{fmt(sel.eleitorado)}</dd>
                <dt>População (2022)</dt><dd>{fmt(sel.populacao)}</dd>
                <dt>PIB per capita (2022)</dt><dd>{fmt(sel.pib_per_capita, 0)}</dd>
                <dt>IDHM (2010)</dt><dd>{fmt(sel.idhm, 3)}</dd></dl>}</section>}
        </>}
      </aside>}
      <section class={`dash-charts ${analise === "legenda" && partido ? "single-chart" : ""}`} aria-label="Análises municipais">
        {!(analise === "legenda" && partido) && <article class="dash-chart-card"><h2>{analise === "legenda" ? "Ranking de partidos" : "Taxas mais altas"}</h2><p>{analise === "legenda" ? `${rankingPartidos.length} partidos no recorte · role para ver todos` : "Municípios do recorte selecionado"}</p>
          {analise === "legenda" ? rankingPartidos.length ? <div class="dash-ranking dash-ranking-partidos" tabIndex={0} aria-label="Todos os partidos ordenados por votos de legenda">{rankingPartidos.map((r) => <div class="dash-rank-row" key={r.id}><span><i class="party-dot" style={{ background: corPartido(r.id) }} />{r.nome}</span><i><b style={{ width: `${100 * r.votos / Math.max(1, rankingPartidos[0].votos)}%`, background: corPartido(r.id) }} /></i><strong>{fmt(r.votos)}</strong></div>)}</div> : <div class="dash-empty">Selecione um estado com votos para ver o ranking.</div>
            : ranking.length ? <div class="dash-ranking">{ranking.map(([id, r]) => <button key={id} onClick={() => setMun(id)}><span>{nomes[id] || id}</span><i><b style={{ width: `${Math.min(100, Number(r.abstencao_pct) * 2)}%` }} /></i><strong>{fmt(r.abstencao_pct, 1, "%")}</strong></button>)}</div> : <div class="dash-empty">Selecione um estado com dados para ver o ranking.</div>}</article>}
        <article class="dash-chart-card"><h2>{analise === "legenda" ? "Distribuição dos votos de legenda" : "Distribuição da abstenção"}</h2><p>Quantidade de municípios por faixa percentual</p>{(analise === "legenda" ? percentuaisMunicipios.length : valores.length) ? analise === "legenda" ? <div class="dash-distribution-horizontal">{faixasAtivas.map((f) => <div class="dash-distribution-row" key={f.rotulo}><span>{f.rotulo}</span><i><b style={{ width: `${100 * f.valor / maxFaixaAtiva}%` }} /></i><strong>{fmt(f.valor)}</strong></div>)}</div> : <div class="dash-distribution">{faixasAtivas.map((f) => <div key={f.rotulo}><span>{f.valor}</span><i style={{ height: `${Math.max(3, 100 * f.valor / maxFaixaAtiva)}%` }} /><small>{f.rotulo}</small></div>)}</div> : <div class="dash-empty">Os dados aparecem após selecionar um estado.</div>}</article>
      </section>
      {analise === "legenda" && <GraficosLegenda uf={uf} mun={mun} cargo={cargo} partido={partido} onPartido={setPartido} opcoes={opcoesAtivas} linhas={linhasAtivas} carregando={!dadosProntosLegenda} onMunicipio={selecionarMunicipio} ufPorMunicipio={ufPorMunicipio} ufsDisponiveis={COBERTOS} historicoMock={historicoMock} historicoExterno={historicoExterno} erroHistoricoExterno={todosAnosLegenda && chaveHistorico === chaveHistoricoAtual && statusHistorico === "erro"} />}
    </div>
  );
}
