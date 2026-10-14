import { useEffect, useState } from "preact/hooks";
import { CORES_UF } from "./coresEleitorais";

export type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type Opcao = { ano: number; cargo: string };
type Props = { uf: string | null; mun: string | null; cargo: string; partido: string; ano: number | null; opcoes: Opcao[]; linhas: LinhaLegenda[]; carregando: boolean; onMunicipio: (uf: string, id: string) => void; ufPorMunicipio: Record<string, string>; ufsDisponiveis: string[]; historicoMock?: Ponto[]; corSerie?: string };
type Ponto = { ano: number; legenda: number | null };
const numero = (valor: number) => valor.toLocaleString("pt-BR");
const percentual = (valor: number) => `${valor.toLocaleString("pt-BR", { maximumFractionDigits: 1 })}%`;

export function GraficosLegenda({ uf, mun, cargo, partido, ano, opcoes, linhas, carregando, onMunicipio, ufPorMunicipio, ufsDisponiveis, historicoMock, corSerie }: Props) {
  const [historico, setHistorico] = useState<Ponto[]>([]);
  const [erroHistorico, setErroHistorico] = useState(false);
  useEffect(() => {
    setHistorico([]); setErroHistorico(false);
    if (!cargo || historicoMock || carregando) return;
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
      const linhasAno = resultados.flat().filter((item) => (!mun || item.id_municipio === mun) && (!partido || item.id_partido === partido));
      return { ano: anoConsulta, legenda: linhasAno.length ? linhasAno.reduce((soma, item) => soma + item.votos_legenda, 0) : null };
    })).then((pontos) => { if (!ac.signal.aborted) setHistorico(pontos); })
      .catch(() => { if (!ac.signal.aborted) setErroHistorico(true); });
    return () => ac.abort();
  }, [uf, mun, cargo, partido, opcoes, ufsDisponiveis, historicoMock, carregando]);

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
  const serie = [...(historicoMock ?? historico)].sort((a, b) => a.ano - b.ano);
  const max = Math.max(1, ...serie.map((item) => item.legenda ?? 0));
  const intervalo = Math.max(1, (serie.at(-1)?.ano ?? 0) - (serie[0]?.ano ?? 0));
  const pontos = serie.map((item) => ({ ...item, x: serie.length === 1 ? 261 : 42 + (item.ano - serie[0].ano) * 438 / intervalo, y: item.legenda === null ? null : 165 - item.legenda / max * 115 }));
  const pontosValidos = pontos.filter((item) => item.y !== null);
  const segmentos = pontos.reduce<typeof pontos[]>((acumulado, item, indice) => {
    if (item.y === null) return acumulado;
    if (!acumulado.length || pontos[indice - 1]?.y === null) acumulado.push([]);
    acumulado.at(-1)?.push(item);
    return acumulado;
  }, []);
  const semDados = carregando || !linhas.length;

  return <section class="legenda-graficos" aria-label="Gráficos de votos por legenda">
    <article class="dash-chart-card"><h2>Legenda × voto nominal</h2><p>Composição dos votos no recorte selecionado</p>
      {semDados ? <div class="dash-empty">A proporção aparece quando os dados do recorte carregam.</div> : <div class="legenda-proporcao">
        <div class="legenda-donut" style={{ background: `conic-gradient(var(--legend-accent, #ed4ca2) ${fatia}%, var(--legend-muted, #66728e) ${fatia}% 100%)` }} role="img" aria-label={`${percentual(fatia)} votos de legenda e ${percentual(100 - fatia)} votos nominais`}><div><strong>{percentual(fatia)}</strong><small>de legenda</small></div></div>
        <div class="legenda-proporcao-valores"><div><i class="ponto-legenda" /><span>Legenda<strong>{numero(votosLegenda)}</strong></span></div><div><i class="ponto-nominal" /><span>Nominal<strong>{numero(votosNominais)}</strong></span></div></div>
      </div>}
    </article>
    <article class="dash-chart-card"><h2>Evolução dos votos de legenda</h2><p>{cargo || "Cargo"} · {mun ? "município" : uf || "seis UFs disponíveis"}{partido ? " · partido selecionado no filtro global" : ""}</p>
      {erroHistorico ? <div class="dash-empty">Não foi possível carregar a série histórica.</div> : !pontos.length ? <div class="dash-empty">Carregando eleições disponíveis…</div> : !pontosValidos.length ? <div class="dash-empty">Sem registros para este recorte nos anos disponíveis.</div> : <svg class="legenda-trend" viewBox="0 0 520 205" role="img" aria-label={`Votos de legenda de ${pontos[0].ano} a ${pontos[pontos.length - 1].ano}; anos sem registros não são ligados`}>
        {[50, 107, 165].map((y) => <line key={y} x1="42" x2="480" y1={y} y2={y} class="mock-grid-line" />)}
        {segmentos.filter((segmento) => segmento.length > 1).map((segmento) => <polyline key={segmento[0].ano} points={segmento.map((item) => `${item.x},${item.y}`).join(" ")} fill="none" stroke={corSerie || "var(--legend-accent, #ed4ca2)"} stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />)}
        {pontos.map((item) => <g key={item.ano}>{item.y !== null && <><circle cx={item.x} cy={item.y} r="5" fill={corSerie || "var(--legend-accent, #ed4ca2)"} stroke={item.ano === ano ? "#fff" : "none"} stroke-width="2" /><text x={item.x} y={item.y - 12} text-anchor="middle" class="mock-value">{numero(item.legenda!)}</text></>}<text x={item.x} y="192" text-anchor="middle" class="mock-year">{item.ano}</text></g>)}
      </svg>}
      {!!serie.length && <p class="legenda-trend-nota">Mesmo cargo nos anos disponíveis: {serie.map((item) => item.ano).join(", ")}. {pontosValidos.length === 1 ? "Há apenas uma eleição com registro para este recorte." : serie.some((item) => item.legenda === null) ? "Anos sem registros não são tratados como zero." : "A posição horizontal respeita o intervalo entre os anos."}</p>}
    </article>
    <article class="dash-chart-card legenda-municipios"><h2>Municípios com mais votos de legenda</h2><p>Selecione uma linha para localizar o município no mapa</p>
      {semDados ? <div class="dash-empty">Os municípios aparecem quando os dados do recorte carregam.</div> : <div class="legenda-municipios-tabela"><div class="legenda-municipios-cabecalho"><span>Município</span><span>Votos</span><span>% legenda</span></div>{municipios.map((item) => <button key={item.id} class={mun === item.id ? "selecionado" : ""} onClick={() => { const sigla = ufPorMunicipio[item.id] || uf; if (sigla) onMunicipio(sigla, item.id); }}><span class="municipio-tabela-nome"><span>{item.nome}</span>{!uf && ufPorMunicipio[item.id] && <small class="uf-badge" style={{ color: CORES_UF[ufPorMunicipio[item.id]], borderColor: CORES_UF[ufPorMunicipio[item.id]] }}>{ufPorMunicipio[item.id]}</small>}</span><strong>{numero(item.legenda)}</strong><span>{percentual(100 * item.legenda / Math.max(1, item.legenda + item.nominais))}</span></button>)}</div>}
    </article>
  </section>;
}
