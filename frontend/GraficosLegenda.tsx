import { useEffect, useState } from "preact/hooks";
import { CORES_UF, corPartido } from "./coresEleitorais";

export type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type Opcao = { ano: number; cargo: string };
type SeriePartido = { id: string; nome: string; legenda: number };
export type HistoricoAno = { ano: number; partidos: SeriePartido[] };
type Props = { uf: string | null; mun: string | null; cargo: string; partido: string; onPartido: (id: string) => void; opcoes: Opcao[]; linhas: LinhaLegenda[]; carregando: boolean; onMunicipio: (uf: string, id: string) => void; ufPorMunicipio: Record<string, string>; ufsDisponiveis: string[]; historicoMock?: HistoricoAno[]; historicoExterno?: HistoricoAno[]; erroHistoricoExterno?: boolean };
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

export function GraficosLegenda({ uf, mun, cargo, partido, onPartido, opcoes, linhas, carregando, onMunicipio, ufPorMunicipio, ufsDisponiveis, historicoMock, historicoExterno, erroHistoricoExterno = false }: Props) {
  const [historico, setHistorico] = useState<HistoricoAno[]>([]);
  const [erroHistorico, setErroHistorico] = useState(false);
  const [anosEscolhidos, setAnosEscolhidos] = useState<number[] | null>(null);
  const [focoPartido, setFocoPartido] = useState<string | null>(null);
  useEffect(() => setAnosEscolhidos(null), [cargo, opcoes]);
  useEffect(() => {
    setHistorico([]); setErroHistorico(false);
    if (!cargo || historicoMock || historicoExterno || carregando) return;
    const anos = [...new Set(opcoes.filter((item) => item.cargo === cargo).map((item) => item.ano))].sort((a, b) => a - b);
    if (!anos.length) { setErroHistorico(true); return; }
    if (anos.length === 1) { setHistorico([{ ano: anos[0], partidos: [] }]); return; }
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
  }, [uf, mun, cargo, opcoes, ufsDisponiveis, historicoMock, historicoExterno, carregando]);

  const recorte = linhas.filter((item) => !mun || item.id_municipio === mun);
  const votosLegenda = recorte.reduce((soma, item) => soma + item.votos_legenda, 0);
  const votosNominais = recorte.reduce((soma, item) => soma + item.votos_nominais, 0);
  const fatia = votosLegenda + votosNominais ? 100 * votosLegenda / (votosLegenda + votosNominais) : 0;
  const municipios = [...linhas.reduce((acc, item) => {
    const atual = acc.get(item.id_municipio) || { id: item.id_municipio, nome: item.municipio, legenda: 0, nominais: 0 };
    atual.legenda += item.votos_legenda; atual.nominais += item.votos_nominais;
    acc.set(item.id_municipio, atual); return acc;
  }, new Map<string, { id: string; nome: string; legenda: number; nominais: number }>()).values()]
    .sort((a, b) => b.legenda - a.legenda || a.nome.localeCompare(b.nome, "pt-BR"))
    .map((item, indice) => ({ ...item, posicao: indice + 1 }));
  const municipioSelecionado = municipios.find((item) => item.id === mun);
  const municipiosExibidos = municipios.slice(0, 10);
  if (municipioSelecionado && municipioSelecionado.posicao > 10) municipiosExibidos.push(municipioSelecionado);
  const anosDisponiveis = [...new Set(opcoes.filter((item) => item.cargo === cargo).map((item) => item.ano))].sort((a, b) => a - b);
  const historicoAtivo = [...(historicoMock ?? historicoExterno ?? historico)].filter((item) => anosEscolhidos === null || anosEscolhidos.includes(item.ano)).sort((a, b) => a.ano - b.ano);
  const partidosHistoricos = [...new Map(historicoAtivo.flatMap((item) => item.partidos.map((p) => [p.id, p.nome] as const))).entries()]
    .filter(([id]) => !partido || id === partido).sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  const partidoEmDestaque = partido || focoPartido;
  const max = Math.max(1, ...historicoAtivo.flatMap((item) => item.partidos.filter((p) => !partido || p.id === partido).map((p) => p.legenda)));
  const intervalo = Math.max(1, (historicoAtivo.at(-1)?.ano ?? 0) - (historicoAtivo[0]?.ano ?? 0));
  const series = partidosHistoricos.map(([id, nome]) => ({ id, nome, pontos: historicoAtivo.map((item) => {
    const registro = item.partidos.find((p) => p.id === id);
    return { ano: item.ano, legenda: registro?.legenda ?? null, x: historicoAtivo.length === 1 ? 261 : 42 + (item.ano - historicoAtivo[0].ano) * 438 / intervalo, y: registro ? 165 - registro.legenda / max * 115 : null };
  }) }));
  const totalPontos = series.reduce((soma, serie) => soma + serie.pontos.filter((item) => item.y !== null).length, 0);
  const semDados = carregando || !linhas.length;

  return <section class="legenda-graficos" aria-label="Gráficos de votos por legenda">
    <article class="dash-chart-card"><h2>Legenda × voto nominal</h2><p>Composição dos votos no recorte selecionado</p>
      {semDados ? <div class="dash-empty">A proporção aparece quando os dados do recorte carregam.</div> : <div class="legenda-proporcao">
        <div class="legenda-proporcao-destaque"><strong>{percentual(fatia)}</strong><span>dos votos deste recorte foram votos de legenda</span></div>
        <div class="legenda-composicao-barra" role="img" aria-label={`${percentual(fatia)} votos de legenda e ${percentual(100 - fatia)} votos nominais`}><i style={{ width: `${fatia}%` }} /><i style={{ width: `${100 - fatia}%` }} /></div>
        <div class="legenda-proporcao-valores"><div><i class="ponto-legenda" /><span>Legenda<strong>{numero(votosLegenda)} <small>· {percentual(fatia)}</small></strong></span></div><div><i class="ponto-nominal" /><span>Nominal<strong>{numero(votosNominais)} <small>· {percentual(100 - fatia)}</small></strong></span></div></div>
      </div>}
    </article>
    <article class="dash-chart-card legenda-evolution"><h2>Evolução dos votos de legenda</h2><p>{cargo || "Cargo"} · {mun ? "município" : uf || "seis UFs disponíveis"}{partido ? " · partido selecionado no filtro global" : " · todos os partidos"}</p>
      {anosDisponiveis.length > 1 && <div class="legenda-year-controls">
        <div class="legenda-year-mode" role="group" aria-label="Anos da evolução">
          <button type="button" aria-pressed={anosEscolhidos === null} onClick={() => setAnosEscolhidos(null)}>Todos os anos</button>
          <button type="button" aria-pressed={anosEscolhidos !== null} onClick={() => setAnosEscolhidos(anosEscolhidos ?? anosDisponiveis)}>Escolher anos</button>
        </div>
        {anosEscolhidos !== null && <div class="legenda-year-choices" aria-label="Eleições incluídas no gráfico">{anosDisponiveis.map((anoOpcao) => <label key={anoOpcao}><input type="checkbox" checked={anosEscolhidos.includes(anoOpcao)} disabled={anosEscolhidos.length === 1 && anosEscolhidos.includes(anoOpcao)} onChange={() => setAnosEscolhidos((atual) => atual === null ? anosDisponiveis : atual.includes(anoOpcao) ? atual.filter((item) => item !== anoOpcao) : [...atual, anoOpcao])} />{anoOpcao}</label>)}</div>}
      </div>}
      {erroHistorico || erroHistoricoExterno ? <div class="dash-empty">Não foi possível carregar a série histórica.</div> : carregando || !historicoAtivo.length ? <div class="dash-empty">Carregando eleições disponíveis…</div> : historicoAtivo.length === 1 ? <div class="dash-empty">Há dados apenas para {historicoAtivo[0].ano} neste cargo. A evolução aparecerá quando houver outra eleição disponível.</div> : !totalPontos ? <div class="dash-empty">Sem registros para este recorte nos anos disponíveis.</div> : <>
        <svg class="legenda-trend" viewBox="0 0 520 205" role="img" aria-label={`Votos de legenda por partido de ${historicoAtivo[0].ano} a ${historicoAtivo[historicoAtivo.length - 1].ano}; anos sem registros não são ligados`}>
          {[50, 107, 165].map((y) => <line key={y} x1="42" x2="480" y1={y} y2={y} class="mock-grid-line" />)}
          {series.map((serie) => {
            const segmentos = serie.pontos.reduce<typeof serie.pontos[]>((acumulado, item, indice) => {
              if (item.y === null) return acumulado;
              if (!acumulado.length || serie.pontos[indice - 1]?.y === null) acumulado.push([]);
              acumulado.at(-1)?.push(item);
              return acumulado;
            }, []);
            return <g key={serie.id} opacity={partidoEmDestaque && serie.id !== partidoEmDestaque ? 0.14 : 1}>
              {segmentos.filter((segmento) => segmento.length > 1).map((segmento) => <polyline key={segmento[0].ano} points={segmento.map((item) => `${item.x},${item.y}`).join(" ")} fill="none" stroke={corPartido(serie.id)} stroke-width={partidoEmDestaque === serie.id ? "3" : "2"} stroke-linecap="round" stroke-linejoin="round" />)}
              {serie.pontos.filter((item) => item.y !== null).map((item) => <circle key={item.ano} cx={item.x} cy={item.y!} r={partidoEmDestaque === serie.id ? "5" : "3"} fill={corPartido(serie.id)}><title>{`${serie.nome} · ${item.ano}: ${numero(item.legenda!)} votos de legenda`}</title></circle>)}
            </g>;
          })}
          {historicoAtivo.map((item) => <text key={item.ano} x={historicoAtivo.length === 1 ? 261 : 42 + (item.ano - historicoAtivo[0].ano) * 438 / intervalo} y="192" text-anchor="middle" class="mock-year">{item.ano}</text>)}
        </svg>
        <div class="legenda-trend-legend"><small>Selecione um partido para filtrar o painel</small>{partido && <button type="button" class="legenda-trend-clear" onClick={() => onPartido("")}>Mostrar todos</button>}</div>
        <div class="legenda-trend-series" aria-label="Partidos da evolução">{partidosHistoricos.map(([id, nome]) => <button type="button" key={id} aria-label={`Filtrar painel pelo partido ${nome}`} aria-pressed={partido === id} onMouseEnter={() => setFocoPartido(id)} onMouseLeave={() => setFocoPartido(null)} onFocus={() => setFocoPartido(id)} onBlur={() => setFocoPartido(null)} onClick={() => onPartido(id)}><i style={{ background: corPartido(id) }} />{nome}</button>)}</div>
      </>}
    </article>
    <article class="dash-chart-card legenda-municipios"><h2>Municípios com mais votos de legenda</h2><p>Ranking por quantidade de votos · selecione um município para vê-lo no mapa</p>
      {semDados ? <div class="dash-empty">Os municípios aparecem quando os dados do recorte carregam.</div> : <>
        {municipioSelecionado && <div class="legenda-posicao-municipio" role="status"><span>Posição de {municipioSelecionado.nome}</span><strong>{municipioSelecionado.posicao}º <small>de {municipios.length}</small></strong><span>{numero(municipioSelecionado.legenda)} votos de legenda</span></div>}
        <div class="legenda-municipios-tabela"><div class="legenda-municipios-cabecalho"><span>Município</span><span>Votos</span><span>% legenda</span></div>{municipiosExibidos.map((item) => <button key={item.id} class={`${mun === item.id ? "selecionado" : ""} ${item.posicao > 10 ? "fora-do-topo" : ""}`} aria-current={mun === item.id ? "true" : undefined} onClick={() => { const sigla = ufPorMunicipio[item.id] || uf; if (sigla) onMunicipio(sigla, item.id); }}><span class="municipio-tabela-nome"><b class="municipio-posicao">{item.posicao}º</b><span>{item.nome}</span>{!uf && ufPorMunicipio[item.id] && <small class="uf-badge" style={{ color: CORES_UF[ufPorMunicipio[item.id]], borderColor: CORES_UF[ufPorMunicipio[item.id]] }}>{ufPorMunicipio[item.id]}</small>}</span><strong>{numero(item.legenda)}</strong><span>{percentual(100 * item.legenda / Math.max(1, item.legenda + item.nominais))}</span></button>)}</div>
      </>}
    </article>
  </section>;
}
