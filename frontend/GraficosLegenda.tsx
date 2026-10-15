import { useEffect, useState } from "preact/hooks";
import { coresUf, corPartido as corDoPartido } from "./coresEleitorais";
import { useTema } from "./Tema";

export type LinhaLegenda = { id_municipio: string; municipio: string; id_partido: string; partido: string; votos_legenda: number; votos_nominais: number };
type Opcao = { ano: number; cargo: string };
type SeriePartido = { id: string; nome: string; legenda: number };
export type HistoricoAno = { ano: number; partidos: SeriePartido[] };
type Props = { uf: string | null; mun: string | null; cargo: string; partidoGlobal: string; opcoes: Opcao[]; linhas: LinhaLegenda[]; carregando: boolean; onMunicipio: (uf: string, id: string) => void; ufPorMunicipio: Record<string, string>; ufsDisponiveis: string[]; todosAnos: boolean; historicoMock?: HistoricoAno[]; historicoExterno?: HistoricoAno[]; erroHistoricoExterno?: boolean; faixaSelecionada?: number | null };
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
const normalizarBusca = (valor: string) => valor.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase("pt-BR");
const TAMANHO_PAGINA = 10;

export function GraficosLegenda({ uf, mun, cargo, partidoGlobal, opcoes, linhas, carregando, onMunicipio, ufPorMunicipio, ufsDisponiveis, todosAnos, historicoMock, historicoExterno, erroHistoricoExterno = false, faixaSelecionada = null }: Props) {
  const { tema } = useTema();
  const CORES_UF = coresUf(tema);
  const corPartido = (sigla: string) => corDoPartido(sigla, tema);
  const [historico, setHistorico] = useState<HistoricoAno[]>([]);
  const [erroHistorico, setErroHistorico] = useState(false);
  const [buscaMunicipio, setBuscaMunicipio] = useState("");
  const [paginaMunicipios, setPaginaMunicipios] = useState(1);
  const [escalaSerie, setEscalaSerie] = useState<"participacao" | "votos">("participacao");
  const [visaoHistorica, setVisaoHistorica] = useState<"variacao" | "linhas">("variacao");
  const [mostrarTodasVariacoes, setMostrarTodasVariacoes] = useState(false);
  const [partidosComparados, setPartidosComparados] = useState<string[]>([]);
  const [ordemMunicipios, setOrdemMunicipios] = useState<"votos" | "participacao">("votos");
  useEffect(() => { setBuscaMunicipio(""); setPaginaMunicipios(1); }, [uf, cargo, partidoGlobal]);
  useEffect(() => setPartidosComparados([]), [cargo, uf, mun]);
  useEffect(() => {
    setHistorico([]); setErroHistorico(false);
    if (!todosAnos || !cargo || historicoMock || historicoExterno || carregando) return;
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
  }, [todosAnos, uf, mun, cargo, opcoes, ufsDisponiveis, historicoMock, historicoExterno, carregando]);

  const municipios = [...linhas.reduce((acc, item) => {
    const atual = acc.get(item.id_municipio) || { id: item.id_municipio, nome: item.municipio, legenda: 0, nominais: 0, partidos: new Map<string, number>() };
    atual.legenda += item.votos_legenda; atual.nominais += item.votos_nominais;
    atual.partidos.set(item.partido, (atual.partidos.get(item.partido) ?? 0) + item.votos_legenda);
    acc.set(item.id_municipio, atual); return acc;
  }, new Map<string, { id: string; nome: string; legenda: number; nominais: number; partidos: Map<string, number> }>()).values()]
    .map((item) => ({ ...item, participacao: 100 * item.legenda / Math.max(1, item.legenda + item.nominais), partidoLider: [...item.partidos].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "pt-BR"))[0]?.[0] ?? "—" }))
    .sort((a, b) => ordemMunicipios === "votos" ? b.legenda - a.legenda || a.nome.localeCompare(b.nome, "pt-BR") : b.participacao - a.participacao || a.nome.localeCompare(b.nome, "pt-BR"))
    .map((item, indice) => ({ ...item, posicao: indice + 1 }));
  const municipioSelecionado = municipios.find((item) => item.id === mun);
  const termoMunicipio = normalizarBusca(buscaMunicipio.trim());
  const municipiosFiltrados = municipios.filter((item) => (!termoMunicipio || normalizarBusca(item.nome).includes(termoMunicipio)) && (faixaSelecionada === null || (item.participacao >= faixaSelecionada && (faixaSelecionada === 25 || item.participacao < faixaSelecionada + 5))));
  const totalPaginasMunicipios = Math.max(1, Math.ceil(municipiosFiltrados.length / TAMANHO_PAGINA));
  const paginaAtualMunicipios = Math.min(paginaMunicipios, totalPaginasMunicipios);
  const municipiosExibidos = municipiosFiltrados.slice((paginaAtualMunicipios - 1) * TAMANHO_PAGINA, paginaAtualMunicipios * TAMANHO_PAGINA);
  useEffect(() => {
    if (mun && !termoMunicipio) {
      const indice = municipios.findIndex((item) => item.id === mun);
      if (indice >= 0) setPaginaMunicipios(Math.floor(indice / TAMANHO_PAGINA) + 1);
    }
  }, [mun, municipioSelecionado?.posicao, termoMunicipio]);
  const historicoAtivo = [...(historicoMock ?? historicoExterno ?? historico)].sort((a, b) => a.ano - b.ano);
  const todosPartidosHistoricos = [...new Map(historicoAtivo.flatMap((item) => item.partidos.map((p) => [p.id, p.nome] as const))).entries()]
    .sort((a, b) => a[1].localeCompare(b[1], "pt-BR"));
  const totaisPorAno = new Map(historicoAtivo.map((item) => [item.ano, item.partidos.reduce((soma, partido) => soma + partido.legenda, 0)]));
  const seriesHistoricas = todosPartidosHistoricos.map(([id, nome]) => {
    const pontos = historicoAtivo.map((item) => {
      const votos = item.partidos.find((p) => p.id === id)?.legenda;
      return { ano: item.ano, legenda: votos === undefined ? null : escalaSerie === "participacao" ? 100 * votos / Math.max(1, totaisPorAno.get(item.ano) ?? 0) : votos, votos };
    });
    const segmentos = pontos.reduce<{ ano: number; legenda: number }[][]>((grupos, item, indice) => {
      if (item.legenda === null) return grupos;
      if (!grupos.length || pontos[indice - 1].legenda === null) grupos.push([]);
      grupos.at(-1)!.push({ ano: item.ano, legenda: item.legenda });
      return grupos;
    }, []);
    return { id, nome, pontos: pontos.filter((item): item is { ano: number; legenda: number; votos: number } => item.legenda !== null), segmentos };
  });
  const [anoAnterior, anoPosterior] = [historicoAtivo[0], historicoAtivo.at(-1)];
  const variacoes = anoAnterior && anoPosterior && anoAnterior.ano !== anoPosterior.ano
    ? todosPartidosHistoricos.map(([id, nome]) => {
      const anterior = anoAnterior.partidos.find((item) => item.id === id);
      const posterior = anoPosterior.partidos.find((item) => item.id === id);
      if (!anterior || !posterior) return null;
      const participacaoAnterior = 100 * anterior.legenda / Math.max(1, totaisPorAno.get(anoAnterior.ano) ?? 0);
      const participacaoPosterior = 100 * posterior.legenda / Math.max(1, totaisPorAno.get(anoPosterior.ano) ?? 0);
      return { id, nome, anterior: participacaoAnterior, posterior: participacaoPosterior, diferenca: participacaoPosterior - participacaoAnterior };
    }).filter((item): item is { id: string; nome: string; anterior: number; posterior: number; diferenca: number } => item !== null)
      .sort((a, b) => Math.abs(b.diferenca) - Math.abs(a.diferenca)) : [];
  const variacoesVisiveis = mostrarTodasVariacoes ? variacoes : [...variacoes.slice(0, 10), ...variacoes.filter((item, indice) => indice >= 10 && item.id === partidoGlobal)];
  const maiorVariacao = Math.max(0.1, ...variacoes.map((item) => Math.abs(item.diferenca)));
  const partidosIniciais = [...seriesHistoricas].sort((a, b) => (b.pontos.at(-1)?.legenda ?? 0) - (a.pontos.at(-1)?.legenda ?? 0)).slice(0, 5).map((item) => item.id);
  const idsComparados = partidosComparados.length ? partidosComparados : partidoGlobal && seriesHistoricas.some((serie) => serie.id === partidoGlobal) ? [partidoGlobal] : partidosIniciais;
  const seriesComparadas = seriesHistoricas.filter((serie) => idsComparados.includes(serie.id));
  const valoresComparados = seriesComparadas.flatMap((serie) => serie.pontos.map((ponto) => ponto.legenda));
  const valoresHistoricos = seriesHistoricas.flatMap((serie) => serie.pontos.map((ponto) => ponto.legenda));
  const maximo = Math.max(0, ...(visaoHistorica === "linhas" ? valoresComparados : valoresHistoricos));
  const piso = 0, teto = maximo || 1;
  const rotuloValor = (valor: number) => escalaSerie === "participacao" ? percentual(valor) : numero(Math.round(valor));
  const xHistorico = (ano: number) => 72 + 456 * (ano - historicoAtivo[0].ano) / Math.max(1, historicoAtivo.at(-1)!.ano - historicoAtivo[0].ano);
  const yHistorico = (valor: number) => 165 - 120 * (valor - piso) / Math.max(1, teto - piso);
  const semDados = carregando || !linhas.length;

  return <section class="legenda-graficos" aria-label="Gráficos de votos por legenda">
    {todosAnos && <article class="dash-chart-card legenda-evolution"><div class="legenda-evolution-head"><div><span>SÉRIE HISTÓRICA</span><h2>Participação partidária entre eleições</h2><p>{cargo || "Cargo"} · {mun ? "município" : uf || "seis UFs disponíveis"}</p></div></div>
      <div class="legenda-history-controls" role="group" aria-label="Visualização histórica"><button type="button" aria-pressed={visaoHistorica === "variacao"} onClick={() => setVisaoHistorica("variacao")}>Variação da participação</button><button type="button" aria-pressed={visaoHistorica === "linhas"} onClick={() => setVisaoHistorica("linhas")}>Evolução por partido</button></div>
      {erroHistorico || erroHistoricoExterno ? <div class="dash-empty">Não foi possível carregar a série histórica.</div> : !historicoAtivo.length ? <div class="dash-empty">Carregando eleições disponíveis…</div> : !seriesHistoricas.length ? <div class="dash-empty">Não há registros de partidos para este recorte.</div> : visaoHistorica === "variacao" ? variacoes.length ? <>
        <p class="legenda-history-description">Cada percentual é a parte do partido no total de votos de legenda daquele ano. A barra mostra a diferença entre os dois percentuais.</p>
        <div class="legenda-variation-key"><span><i class="subiu" /> Ganhou participação</span><span><i class="caiu" /> Perdeu participação</span><span>Centro = sem mudança</span></div>
        <div class="legenda-variation-head"><span>Partido</span><span>Participação: {anoAnterior.ano} → {anoPosterior.ano}</span><span>Variação</span></div>
        <div class="legenda-variation-list">{variacoesVisiveis.map((item) => <div class={`legenda-variation-row ${partidoGlobal === item.id ? "selecionado" : ""}`} key={item.id} title={`${item.nome}: ${anoAnterior.ano} ${percentual(item.anterior)} → ${anoPosterior.ano} ${percentual(item.posterior)}; variação de ${item.diferenca > 0 ? "+" : ""}${percentual(item.diferenca)} pontos percentuais`}><strong>{item.nome}</strong><span class="legenda-variation-years">{percentual(item.anterior)} → {percentual(item.posterior)}</span><div class="legenda-variation-track"><i class={item.diferenca > 0.05 ? "subiu" : item.diferenca < -0.05 ? "caiu" : "estavel"} style={{ left: item.diferenca < 0 ? `${50 - 48 * Math.abs(item.diferenca) / maiorVariacao}%` : "50%", width: `${Math.max(1, 48 * Math.abs(item.diferenca) / maiorVariacao)}%` }} /></div><span class="legenda-variation-delta">{item.diferenca > 0 ? "+" : ""}{percentual(item.diferenca)} pontos</span></div>)}</div>
        <small class="legenda-evolution-note">Exemplo: 10% em {anoAnterior.ano} e 14% em {anoPosterior.ano} significa aumento de 4 pontos percentuais. Não significa aumento de 4% no número de votos.</small>
        {variacoes.length > 10 && <button type="button" class="legenda-show-more" onClick={() => setMostrarTodasVariacoes(!mostrarTodasVariacoes)}>{mostrarTodasVariacoes ? "Mostrar 10 principais" : `Ver todos os ${variacoes.length} partidos`}</button>}
      </> : <div class="dash-empty">A comparação exige dois anos distintos e registro do mesmo partido em ambos. Ausência de registro não é zero voto.</div> : <>
        <div class="legenda-line-options"><label>Escala<select value={escalaSerie} onChange={(e) => setEscalaSerie((e.target as HTMLSelectElement).value as "participacao" | "votos")}><option value="participacao">% dos votos de legenda no ano</option><option value="votos">Votos absolutos</option></select></label><div class="legenda-party-options" aria-label="Partidos comparados">{seriesHistoricas.map((serie) => <label key={serie.id}><input type="checkbox" checked={idsComparados.includes(serie.id)} onChange={() => setPartidosComparados((atuais) => { const selecionados = atuais.length ? atuais : idsComparados; return selecionados.includes(serie.id) ? selecionados.filter((id) => id !== serie.id) : [...selecionados, serie.id]; })} /><i style={{ background: corPartido(serie.nome) }} />{serie.nome}</label>)}</div></div>
        <svg class="legenda-trend" viewBox="0 0 600 220" role="img" aria-label={`Votos de legenda de todos os partidos entre ${historicoAtivo[0].ano} e ${historicoAtivo.at(-1)!.ano}`}>
          {[piso, (piso + teto) / 2, teto].map((valor) => <g key={valor}><line x1="72" x2="528" y1={yHistorico(valor)} y2={yHistorico(valor)} class="mock-grid-line" /><text x="62" y={yHistorico(valor) + 4} text-anchor="end" class="legenda-trend-tick">{rotuloValor(valor)}</text></g>)}
          {seriesComparadas.map((serie) => <g key={serie.id}><title>{serie.nome}</title>{serie.segmentos.filter((segmento) => segmento.length > 1).map((segmento) => <polyline key={segmento[0].ano} points={segmento.map((item) => `${xHistorico(item.ano)},${yHistorico(item.legenda)}`).join(" ")} fill="none" stroke={corPartido(serie.nome)} stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />)}{serie.pontos.map((item) => <circle key={item.ano} cx={xHistorico(item.ano)} cy={yHistorico(item.legenda)} r="4" fill={corPartido(serie.nome)}><title>{serie.nome} · {item.ano}: {numero(item.votos ?? 0)} votos · {percentual(100 * (item.votos ?? 0) / Math.max(1, totaisPorAno.get(item.ano) ?? 0))} do total</title></circle>)}</g>)}
          {historicoAtivo.map((item) => <text key={item.ano} x={xHistorico(item.ano)} y="205" text-anchor="middle" class="legenda-trend-year">{item.ano}</text>)}
        </svg><small class="legenda-evolution-note">{escalaSerie === "participacao" ? "Cada ponto mostra a parcela do partido entre os votos de legenda registrados naquele ano e recorte. " : "Cada ponto mostra o total de votos de legenda do partido. "}Anos sem registro aparecem como lacunas, não como zero voto.</small>
      </>}
    </article>}
    <article class="dash-chart-card legenda-municipios"><div class="legenda-municipios-intro"><div><span>RECORTE MUNICIPAL</span><h2>Votos de legenda por município</h2><p>Selecione um município para localizá-lo no mapa.</p></div><div class="legenda-municipios-filtros"><strong>{numero(municipiosFiltrados.length)}{termoMunicipio || faixaSelecionada !== null ? ` de ${numero(municipios.length)}` : ""} municípios</strong><input id="busca-municipios-legenda" type="search" value={buscaMunicipio} placeholder="Buscar município" aria-label="Buscar município" onInput={(e) => { setBuscaMunicipio((e.target as HTMLInputElement).value); setPaginaMunicipios(1); }} /><select value={ordemMunicipios} aria-label="Ordenar municípios" onChange={(e) => { setOrdemMunicipios((e.target as HTMLSelectElement).value as "votos" | "participacao"); setPaginaMunicipios(1); }}><option value="votos">Mais votos</option><option value="participacao">Maior participação</option></select></div></div>
      {semDados ? <div class="dash-empty">Os municípios aparecem quando os dados do recorte carregam.</div> : <>
        {municipioSelecionado && <div class="legenda-posicao-municipio" role="status"><span>Município selecionado <strong>{municipioSelecionado.nome}</strong></span><span><b>{municipioSelecionado.posicao}º</b> de {municipios.length} · {numero(municipioSelecionado.legenda)} votos</span></div>}
        {municipiosFiltrados.length ? <><div class="legenda-municipios-tabela" aria-label="Municípios por votos de legenda"><div class="legenda-municipios-cabecalho"><span>Posição · Município</span><span>Votos</span><span>Participação</span><span>Partido líder</span></div>{municipiosExibidos.map((item) => <button key={item.id} class={mun === item.id ? "selecionado" : ""} aria-label={`${item.posicao}º, ${item.nome}, ${numero(item.legenda)} votos de legenda, ${percentual(item.participacao)}, líder ${item.partidoLider}`} aria-current={mun === item.id ? "true" : undefined} onClick={() => { const sigla = ufPorMunicipio[item.id] || uf; if (sigla) onMunicipio(sigla, item.id); }}><span class="municipio-tabela-nome"><b class="municipio-posicao">{item.posicao}º</b><span>{item.nome}</span>{!uf && ufPorMunicipio[item.id] && <small class="uf-badge" style={{ color: CORES_UF[ufPorMunicipio[item.id]], borderColor: CORES_UF[ufPorMunicipio[item.id]] }}>{ufPorMunicipio[item.id]}</small>}</span><strong>{numero(item.legenda)}</strong><span>{percentual(item.participacao)}</span><span>{item.partidoLider}</span></button>)}</div><nav class="legenda-municipios-paginacao" aria-label="Páginas de municípios"><span>{numero((paginaAtualMunicipios - 1) * TAMANHO_PAGINA + 1)}–{numero(Math.min(paginaAtualMunicipios * TAMANHO_PAGINA, municipiosFiltrados.length))} de {numero(municipiosFiltrados.length)} · página {paginaAtualMunicipios} de {totalPaginasMunicipios}</span><div><button type="button" disabled={paginaAtualMunicipios === 1} onClick={() => setPaginaMunicipios(paginaAtualMunicipios - 1)}>Anterior</button><button type="button" disabled={paginaAtualMunicipios === totalPaginasMunicipios} onClick={() => setPaginaMunicipios(paginaAtualMunicipios + 1)}>Próxima</button></div></nav></> : <div class="dash-empty">Nenhum município encontrado. Tente outro nome ou limpe a faixa selecionada.</div>}
      </>}
    </article>
  </section>;
}
