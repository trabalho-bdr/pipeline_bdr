import { useEffect, useState } from "preact/hooks";
import { CORES_UF, corPartido } from "./coresEleitorais";

export type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type Opcao = { ano: number; cargo: string };
type SeriePartido = { id: string; nome: string; legenda: number };
export type HistoricoAno = { ano: number; partidos: SeriePartido[] };
type Props = { uf: string | null; mun: string | null; cargo: string; partido: string; ano: number | null; opcoes: Opcao[]; linhas: LinhaLegenda[]; carregando: boolean; somenteEvolucao?: boolean; ocultarEvolucao?: boolean; onMunicipio: (uf: string, id: string) => void; ufPorMunicipio: Record<string, string>; ufsDisponiveis: string[]; historicoMock?: HistoricoAno[] };
export function resumirLegendaPorPartido(ano: number, linhas: LinhaLegenda[]): HistoricoAno {
  const partidos = new Map<string, SeriePartido>();
  for (const item of linhas) {
    const atual = partidos.get(item.id_partido) ?? { id: item.id_partido, nome: item.partido, legenda: 0 };
    atual.legenda += item.votos_legenda;
    partidos.set(item.id_partido, atual);
  }
  return { ano, partidos: [...partidos.values()] };
}
const numero = (valor: number) => valor.toLocaleString("pt-BR");
const percentual = (valor: number) => `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;

export function GraficosLegenda({ uf, mun, cargo, partido, ano, opcoes, linhas, carregando, somenteEvolucao = false, ocultarEvolucao = false, onMunicipio, ufPorMunicipio, ufsDisponiveis, historicoMock }: Props) {
  const [historico, setHistorico] = useState<HistoricoAno[]>([]);
  const [erroHistorico, setErroHistorico] = useState(false);
  const [anosEscolhidos, setAnosEscolhidos] = useState<number[] | null>(null);
  useEffect(() => setAnosEscolhidos(null), [cargo, opcoes]);
  useEffect(() => {
    setHistorico([]); setErroHistorico(false);
    if (!cargo || historicoMock || carregando || ocultarEvolucao) return;
    const anos = [...new Set(opcoes.filter((item) => item.cargo === cargo).map((item) => item.ano))].sort((a, b) => a - b);
    if (!anos.length) { setErroHistorico(true); return; }
    const ac = new AbortController();
    const ufsConsulta = uf ? [uf] : ufsDisponiveis;
    Promise.all(anos.map(async (anoConsulta) => {
      const resultados = await Promise.all(ufsConsulta.map(async (sigla) => {
        const resposta = await fetch(`/api/legenda/${sigla}/${anoConsulta}?cargo=${encodeURIComponent(cargo)}`, { signal: ac.signal });
        if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
        const dados: { linhas: LinhaLegenda[] } = await resposta.json();
        return dados.linhas;
      }));
      const linhasAno = resultados.flat().filter((item) => !mun || item.id_municipio === mun);
      return resumirLegendaPorPartido(anoConsulta, linhasAno);
    })).then((pontos) => { if (!ac.signal.aborted) setHistorico(pontos); })
      .catch(() => { if (!ac.signal.aborted) setErroHistorico(true); });
    return () => ac.abort();
  }, [uf, mun, cargo, opcoes, ufsDisponiveis, historicoMock, carregando, ocultarEvolucao]);

  const recorte = linhas.filter((item) => !mun || item.id_municipio === mun);
  const votosLegenda = recorte.reduce((soma, item) => soma + item.votos_legenda, 0);
  const votosNominais = recorte.reduce((soma, item) => soma + item.votos_nominais, 0);
  const fatia = votosLegenda + votosNominais ? 100 * votosLegenda / (votosLegenda + votosNominais) : 0;
  const municipios = [...linhas.reduce((acc, item) => {
    const atual = acc.get(item.id_municipio) || { id: item.id_municipio, nome: item.municipio, legenda: 0, nominais: 0 };
    atual.legenda += item.votos_legenda; atual.nominais += item.votos_nominais;
    acc.set(item.id_municipio, atual); return acc;
  }, new Map<string, { id: string; nome: string; legenda: number; nominais: number }>()).values()]
    .sort((a, b) => b.legenda - a.legenda).slice(0, 10);
  const anosDisponiveis = [...new Set(opcoes.filter((item) => item.cargo === cargo).map((item) => item.ano))].sort((a, b) => a - b);
  const historicoAtivo = [...(historicoMock ?? historico)].filter((item) => anosEscolhidos === null || anosEscolhidos.includes(item.ano)).sort((a, b) => a.ano - b.ano);
  const partidosHistoricos = [...new Map(historicoAtivo.flatMap((item) => item.partidos.map((p) => [p.id, p.nome] as const))).entries()]
    .filter(([id]) => !partido || id === partido).sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  const max = Math.max(1, ...historicoAtivo.flatMap((item) => item.partidos.filter((p) => !partido || p.id === partido).map((p) => p.legenda)));
  const intervalo = Math.max(1, (historicoAtivo.at(-1)?.ano ?? 0) - (historicoAtivo[0]?.ano ?? 0));
  const series = partidosHistoricos.map(([id, nome]) => ({ id, nome, pontos: historicoAtivo.map((item) => {
    const registro = item.partidos.find((p) => p.id === id);
    return { ano: item.ano, legenda: registro?.legenda ?? null, x: historicoAtivo.length === 1 ? 261 : 42 + (item.ano - historicoAtivo[0].ano) * 438 / intervalo, y: registro ? 165 - registro.legenda / max * 115 : null };
  }) }));
  const totalPontos = series.reduce((soma, serie) => soma + serie.pontos.filter((item) => item.y !== null).length, 0);
  const semDados = carregando || !linhas.length;

  return <section class={`legenda-graficos ${somenteEvolucao ? "temporal-only" : ocultarEvolucao ? "snapshot-only" : ""}`} aria-label="Gráficos de votos por legenda">
    {!somenteEvolucao && <article class="dash-chart-card"><h2>Legenda × voto nominal</h2><p>Composição dos votos no recorte selecionado</p>
      {semDados ? <div class="dash-empty">A proporção aparece quando os dados do recorte carregam.</div> : <div class="legenda-proporcao">
        <div class="legenda-donut" style={{ background: `conic-gradient(var(--legend-accent, #ed4ca2) ${fatia}%, var(--legend-muted, #66728e) ${fatia}% 100%)` }} role="img" aria-label={`${percentual(fatia)} votos de legenda e ${percentual(100 - fatia)} votos nominais`}><div><strong>{percentual(fatia)}</strong><small>de legenda</small></div></div>
        <div class="legenda-proporcao-valores"><div><i class="ponto-legenda" /><span>Legenda<strong>{numero(votosLegenda)}</strong></span></div><div><i class="ponto-nominal" /><span>Nominal<strong>{numero(votosNominais)}</strong></span></div></div>
      </div>}
    </article>}
    {!ocultarEvolucao && <article class="dash-chart-card"><h2>Evolução dos votos de legenda</h2><p>{cargo || "Cargo"} · {mun ? "município" : uf || "seis UFs disponíveis"}{partido ? " · partido selecionado no filtro global" : " · todos os partidos"}</p>
      {!!anosDisponiveis.length && <div class="legenda-year-controls">
        <div class="legenda-year-mode" role="group" aria-label="Anos da evolução">
          <button type="button" aria-pressed={anosEscolhidos === null} onClick={() => setAnosEscolhidos(null)}>Todos os anos</button>
          <button type="button" aria-pressed={anosEscolhidos !== null} onClick={() => setAnosEscolhidos(anosEscolhidos ?? anosDisponiveis)}>Escolher anos</button>
        </div>
        {anosEscolhidos !== null && <div class="legenda-year-choices" aria-label="Eleições incluídas no gráfico">{anosDisponiveis.map((anoOpcao) => <label key={anoOpcao}><input type="checkbox" checked={anosEscolhidos.includes(anoOpcao)} disabled={anosEscolhidos.length === 1 && anosEscolhidos.includes(anoOpcao)} onChange={() => setAnosEscolhidos((atual) => atual === null ? anosDisponiveis : atual.includes(anoOpcao) ? atual.filter((item) => item !== anoOpcao) : [...atual, anoOpcao])} />{anoOpcao}</label>)}</div>}
      </div>}
      {erroHistorico ? <div class="dash-empty">Não foi possível carregar a série histórica.</div> : !historicoAtivo.length ? <div class="dash-empty">Carregando eleições disponíveis…</div> : !totalPontos ? <div class="dash-empty">Sem registros para este recorte nos anos disponíveis.</div> : <>
        <svg class="legenda-trend" viewBox="0 0 520 205" role="img" aria-label={`Votos de legenda por partido de ${historicoAtivo[0].ano} a ${historicoAtivo[historicoAtivo.length - 1].ano}; anos sem registros não são ligados`}>
          {[50, 107, 165].map((y) => <line key={y} x1="42" x2="480" y1={y} y2={y} class="mock-grid-line" />)}
          {ano !== null && historicoAtivo.some((item) => item.ano === ano) && <line x1={historicoAtivo.length === 1 ? 261 : 42 + (ano - historicoAtivo[0].ano) * 438 / intervalo} x2={historicoAtivo.length === 1 ? 261 : 42 + (ano - historicoAtivo[0].ano) * 438 / intervalo} y1="42" y2="170" class="legenda-trend-selected-year" />}
          {series.map((serie) => {
            const segmentos = serie.pontos.reduce<typeof serie.pontos[]>((acumulado, item, indice) => {
              if (item.y === null) return acumulado;
              if (!acumulado.length || serie.pontos[indice - 1]?.y === null) acumulado.push([]);
              acumulado.at(-1)?.push(item);
              return acumulado;
            }, []);
            return <g key={serie.id}>
              {segmentos.filter((segmento) => segmento.length > 1).map((segmento) => <polyline key={segmento[0].ano} points={segmento.map((item) => `${item.x},${item.y}`).join(" ")} fill="none" stroke={corPartido(serie.id)} stroke-width={partido ? "3" : "2"} stroke-linecap="round" stroke-linejoin="round" />)}
              {serie.pontos.filter((item) => item.y !== null).map((item) => <circle key={item.ano} cx={item.x} cy={item.y!} r={partido ? "5" : "3"} fill={corPartido(serie.id)} stroke={item.ano === ano ? "#fff" : "none"} stroke-width="1.5"><title>{`${serie.nome} · ${item.ano}: ${numero(item.legenda!)} votos de legenda`}</title></circle>)}
            </g>;
          })}
          {historicoAtivo.map((item) => <text key={item.ano} x={historicoAtivo.length === 1 ? 261 : 42 + (item.ano - historicoAtivo[0].ano) * 438 / intervalo} y="192" text-anchor="middle" class={item.ano === ano ? "mock-year selected-year" : "mock-year"}>{item.ano}</text>)}
        </svg>
        <div class="legenda-trend-series" aria-label="Cores das séries">{partidosHistoricos.map(([id, nome]) => <span key={id}><i style={{ background: corPartido(id) }} />{nome}</span>)}</div>
      </>}
      {!!historicoAtivo.length && <p class="legenda-trend-nota">Eleições exibidas para o mesmo cargo: {historicoAtivo.map((item) => item.ano).join(", ")}. {ano === null ? "Selecione um ano no topo para ver o retrato dessa eleição." : historicoAtivo.some((item) => item.ano === ano) ? `O ano do painel (${ano}) está destacado.` : `O ano do painel (${ano}) não está entre os anos exibidos.`} {historicoAtivo.length === 1 ? "Há apenas uma eleição exibida; não há tendência temporal." : "Cada partido aparece apenas nos anos com registro; lacunas não são zero."}</p>}
    </article>}
    {!somenteEvolucao && <article class="dash-chart-card legenda-municipios"><h2>Municípios com mais votos de legenda</h2><p>Selecione uma linha para localizar o município no mapa</p>
      {semDados ? <div class="dash-empty">Os municípios aparecem quando os dados do recorte carregam.</div> : <div class="legenda-municipios-tabela"><div class="legenda-municipios-cabecalho"><span>Município</span><span>Votos</span><span>% legenda</span></div>{municipios.map((item) => <button key={item.id} class={mun === item.id ? "selecionado" : ""} onClick={() => { const sigla = ufPorMunicipio[item.id] || uf; if (sigla) onMunicipio(sigla, item.id); }}><span class="municipio-tabela-nome"><span>{item.nome}</span>{!uf && ufPorMunicipio[item.id] && <small class="uf-badge" style={{ color: CORES_UF[ufPorMunicipio[item.id]], borderColor: CORES_UF[ufPorMunicipio[item.id]] }}>{ufPorMunicipio[item.id]}</small>}</span><strong>{numero(item.legenda)}</strong><span>{percentual(100 * item.legenda / Math.max(1, item.legenda + item.nominais))}</span></button>)}</div>}
    </article>}
  </section>;
}
