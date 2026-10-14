import { scaleLinear } from "d3-scale";
import { feature } from "topojson-client";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { Feat, Mapa } from "./Mapa";

type Cat = { ufs: { cod: string; sigla: string; nome: string }[]; municipios: Record<string, { id: string; nome: string }[]> };
type Reg = Record<string, number | string | null>;
type Dados = { uf: string; ano: number; municipios: Record<string, Reg> };
const COBERTOS = ["CE", "MA", "MS", "RJ", "RN", "RS"];
const CINZA_SEM_REGISTRO = "#2b2b31", ROXO_SEM_VALOR = "#4a3d5c";

const norm = (s: string) => s.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
const json = async <T,>(u: string, signal?: AbortSignal): Promise<T> => {
  const r = await fetch(u, { signal });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
};
const feats = (topo: any): Feat[] => (feature(topo, topo.objects[Object.keys(topo.objects)[0]]) as any).features;
const fmt = (v: unknown, d = 0, suf = "") =>
  typeof v === "number" ? v.toLocaleString("pt-BR", { maximumFractionDigits: d }) + suf : "sem dado";

export function App() {
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
  const [busca, setBusca] = useState("");
  const cache = useRef(new Map<string, Dados>());

  useEffect(() => {  // base geográfica (estática) e anos disponíveis (API)
    json<Cat>("/geo/catalogo.json").then(setCat).catch(() => setErroGeo("Catálogo de municípios ausente. Rode scripts/preparar_malhas.py."));
    json<any>("/geo/br_ufs.json").then((t) => setUfs(feats(t))).catch(() => setErroGeo("Malha nacional ausente. Rode scripts/preparar_malhas.py."));
    json<{ anos: number[] }>("/api/anos").then((r) => { setAnos(r.anos); setAno(r.anos[r.anos.length - 1] ?? null); })
      .catch(() => setStatus("api"));
  }, []);

  useEffect(() => {  // malha municipal sob demanda, com cache; troca de UF limpa o município
    setMun(null); setBusca("");
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

  const siglas = useMemo(() => Object.fromEntries((cat?.ufs ?? []).map((u) => [u.cod, u.sigla])), [cat]);
  const lista = uf && cat ? cat.municipios[uf] ?? [] : [];
  const nomes = useMemo(() => Object.fromEntries(lista.map((m) => [m.id, m.nome])), [lista]);
  const valido = dados && dados.uf === uf && dados.ano === ano ? dados : null;
  const valores = Object.values(valido?.municipios ?? {}).map((r) => r.abstencao_pct).filter((v): v is number => typeof v === "number");
  const [lo, hi] = [Math.min(...valores), Math.max(...valores)];
  const escala = valores.length ? scaleLinear<string>().domain([lo, hi]).range(["#2f4fbf", "#ff5a4d"]) : null;
  const cor = (id: string) => {
    const r = valido?.municipios[id];
    if (!r) return CINZA_SEM_REGISTRO;                          // sem registro eleitoral (ou carregando)
    const v = r.abstencao_pct;
    return typeof v === "number" && escala ? escala(v) : ROXO_SEM_VALOR;  // 0 é cor válida; null é outra
  };
  const sel = mun && valido ? valido.municipios[mun] : undefined;
  const achados = lista.filter((m) => norm(m.nome).includes(norm(busca))).slice(0, 60);

  return (
    <div class="layout">
      <header>
        <nav aria-label="Navegação geográfica">
          <button onClick={() => { setUf(null); }}>Brasil</button>
          {uf && <> › <button onClick={() => setMun(null)}>{cat?.ufs.find((u) => u.sigla === uf)?.nome}</button></>}
          {mun && <> › <strong>{nomes[mun]}</strong></>}
        </nav>
        <label>Ano <select value={ano ?? ""} onChange={(e) => setAno(Number((e.target as HTMLSelectElement).value))} disabled={!anos.length}>
          {anos.map((a) => <option key={a} value={a}>{a}</option>)}</select></label>
      </header>
      <Mapa ufs={ufs} muns={uf ? geoMun[uf] ?? [] : []} uf={uf} siglas={siglas} cobertos={new Set(COBERTOS)}
        mun={mun} cor={cor} nomes={nomes} onUf={setUf} onMun={setMun} />
      <aside>
        {erroGeo && <p class="aviso erro">{erroGeo}</p>}
        {status === "api" && <p class="aviso erro">API indisponível: mapa sem indicadores.</p>}
        {!uf && <><h2>Estados do recorte</h2><p>As demais UFs estão fora do recorte do projeto.</p>
          <div class="botoes">{COBERTOS.map((s) => <button key={s} onClick={() => setUf(s)}>{s}</button>)}</div></>}
        {uf && <>
          <input type="search" placeholder="Buscar município…" aria-label="Buscar município" value={busca}
            onInput={(e) => setBusca((e.target as HTMLInputElement).value)} />
          <ul class="lista">{achados.map((m) => <li key={m.id}><button aria-pressed={m.id === mun} onClick={() => setMun(m.id)}>{m.nome}</button></li>)}</ul>
          {status === "carregando" && <p class="aviso">Carregando indicadores…</p>}
          {status === "erro" && <p class="aviso erro">Erro ao consultar os indicadores.</p>}
          {mun && <section aria-live="polite"><h2>{nomes[mun]} <small>{uf}</small></h2>
            <p>Código IBGE: {mun}</p>
            {!valido ? null : !sel ? <p class="aviso">Sem registro de participação deste município em {ano}.</p> :
              <dl><dt>Abstenção</dt><dd>{fmt(sel.abstencao_pct, 2, "%")}</dd>
                <dt>Eleitorado</dt><dd>{fmt(sel.eleitorado)}</dd>
                <dt>População (2022)</dt><dd>{fmt(sel.populacao)}</dd>
                <dt>PIB per capita (2022)</dt><dd>{fmt(sel.pib_per_capita, 0)}</dd>
                <dt>IDHM (2010)</dt><dd>{fmt(sel.idhm, 3)}</dd></dl>}</section>}
          <div class="legenda"><strong>Abstenção (%) em {ano} — Q3</strong>
            <div class="barra" /><span>{valores.length ? `${lo.toFixed(1)} → ${hi.toFixed(1)}` : "—"}</span>
            <span><i style={{ background: CINZA_SEM_REGISTRO }} /> sem registro</span>
            <span><i style={{ background: ROXO_SEM_VALOR }} /> registro sem valor</span>
            <span>Valor 0 usa a cor mínima da escala.</span></div></>}
      </aside>
    </div>
  );
}
