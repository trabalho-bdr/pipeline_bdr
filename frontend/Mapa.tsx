import { geoMercator, geoPath } from "d3-geo";
import { select } from "d3-selection";
import "d3-transition";
import { zoom, zoomIdentity, ZoomBehavior } from "d3-zoom";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";

export type Feat = { type: "Feature"; properties: { codarea: string }; geometry: any };
type Props = {
  ufs: Feat[]; muns: Feat[]; uf: string | null; siglas: Record<string, string>; cobertos: Set<string>;
  mun: string | null; cor: (id: string) => string; nomes: Record<string, string>;
  onUf: (sigla: string) => void; onMun: (id: string) => void;
};

export function Mapa(p: Props) {
  const svg = useRef<SVGSVGElement>(null), g = useRef<SVGGElement>(null);
  const zb = useRef<ZoomBehavior<SVGSVGElement, unknown>>();
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [dica, setDica] = useState("");

  useEffect(() => {  // redimensiona com o contêiner (a área do painel não entra no mapa)
    const ro = new ResizeObserver((e) => {
      const r = e[0].contentRect;
      setSize({ w: Math.max(200, r.width), h: Math.max(200, r.height) });
    });
    ro.observe(svg.current!.parentElement!);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const z = zoom<SVGSVGElement, unknown>().scaleExtent([1, 80])
      .on("zoom", (e) => g.current!.setAttribute("transform", e.transform.toString()));
    zb.current = z;
    select(svg.current!).call(z);
  }, []);

  // A projeção é ajustada ao Brasil; UFs e municípios usam a mesma, então se alinham.
  const path = useMemo(() => geoPath(geoMercator().fitSize([size.w, size.h],
    { type: "FeatureCollection", features: p.ufs } as any)), [size, p.ufs]);
  const dUf = useMemo(() => p.ufs.map((f) => path(f as any) || ""), [path, p.ufs]);
  const dMun = useMemo(() => p.muns.map((f) => path(f as any) || ""), [path, p.muns]);

  const mover = (t: any) => {
    const reduz = matchMedia("(prefers-reduced-motion: reduce)").matches;
    select(svg.current!).transition().duration(reduz ? 0 : 700).call(zb.current!.transform as any, t);
  };
  const enquadrar = () => {
    let t = zoomIdentity;
    const f = p.uf && p.ufs.find((x) => p.siglas[x.properties.codarea] === p.uf);
    if (f) {
      const [[x0, y0], [x1, y1]] = path.bounds(f as any);
      const k = Math.min(60, 0.9 / Math.max((x1 - x0) / size.w, (y1 - y0) / size.h));
      t = zoomIdentity.translate(size.w / 2, size.h / 2).scale(k).translate(-(x0 + x1) / 2, -(y0 + y1) / 2);
    }
    mover(t);
  };
  useEffect(enquadrar, [p.uf, path]);

  const iSel = p.mun ? p.muns.findIndex((f) => f.properties.codarea === p.mun) : -1;
  const comMun = p.muns.length > 0;
  return (
    <div class="mapa">
      <svg ref={svg} role="img" aria-label="Mapa interativo: Brasil, estados e municípios">
        <g ref={g}>
          {p.ufs.map((f, i) => {
            const s = p.siglas[f.properties.codarea], cob = p.cobertos.has(s);
            const oculto = comMun && s === p.uf;
            return <path key={f.properties.codarea} d={dUf[i]} class={`uf ${cob ? "cob" : "fora"}${oculto ? " oculto" : ""}`}
              onClick={() => cob && p.onUf(s)} onMouseEnter={() => setDica(`${s}${cob ? "" : " — fora do recorte"}`)}
              onMouseLeave={() => setDica("")} />;
          })}
          {p.muns.map((f, i) => (
            <path key={f.properties.codarea} d={dMun[i]} class="mun" style={{ fill: p.cor(f.properties.codarea) }}
              onClick={() => p.onMun(f.properties.codarea)}
              onMouseEnter={() => setDica(`${p.nomes[f.properties.codarea] ?? f.properties.codarea} — ${p.uf}`)}
              onMouseLeave={() => setDica("")} />
          ))}
          {iSel >= 0 && <path d={dMun[iSel]} class="mun sel" pointer-events="none" />}
        </g>
      </svg>
      <div class="dica" aria-live="polite">{dica}</div>
      <div class="zoomctl">
        <button aria-label="Aproximar" onClick={() => select(svg.current!).transition().call(zb.current!.scaleBy as any, 1.6)}>+</button>
        <button aria-label="Afastar" onClick={() => select(svg.current!).transition().call(zb.current!.scaleBy as any, 1 / 1.6)}>−</button>
        <button aria-label="Reenquadrar" onClick={enquadrar}>⤢</button>
      </div>
    </div>
  );
}
