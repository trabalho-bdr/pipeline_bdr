/** Paleta única dos partidos em mapas, rankings e séries. */
export const CORES_UF: Record<string, string> = {
  CE: "#59a6c8",
  MA: "#e064a2",
  MS: "#a18adb",
  RJ: "#d9936d",
  RN: "#62b9a7",
  RS: "#b0b76d",
};

const coresAtribuidas = new Map<string, string>([["PT", "hsl(350 52% 54%)"], ["PL", "hsl(220 49% 57%)"]]);
const coresUsadas = new Set(coresAtribuidas.values());

export function corPartido(partido: string): string {
  const sigla = partido.trim().toUpperCase();
  if (sigla === "13") return corPartido("PT");
  if (sigla === "22") return corPartido("PL");
  const atribuida = coresAtribuidas.get(sigla);
  if (atribuida) return atribuida;
  let hash = 0;
  for (const caractere of sigla) hash = (hash * 31 + caractere.charCodeAt(0)) >>> 0;
  let tentativa = 0;
  let cor: string;
  do {
    const indice = hash + tentativa++;
    cor = `hsl(${indice % 360} ${40 + Math.floor(indice / 360) % 13}% ${55 + Math.floor(indice / 4680) % 12}%)`;
  } while (coresUsadas.has(cor));
  coresAtribuidas.set(sigla, cor);
  coresUsadas.add(cor);
  return cor;
}
