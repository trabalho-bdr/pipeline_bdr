/** Cores de interface para séries, sem representar cores oficiais. */
export const CORES_UF: Record<string, string> = {
  CE: "#59a6c8",
  MA: "#e064a2",
  MS: "#a18adb",
  RJ: "#d9936d",
  RN: "#62b9a7",
  RS: "#b0b76d",
};

const CORES_PARTIDO = [
  "#f03d94", "#65a9d7", "#d89a64", "#a68ce0", "#6abda6", "#d47486",
  "#8faf68", "#d2b66a", "#7c9be4", "#bd81b8", "#76b8bd", "#c78d74",
];
const PARTIDOS_EXEMPLO: Record<string, number> = { PL: 0, PT: 1, MDB: 2, PP: 3, "UNIÃO": 4, PSD: 5, PSB: 6 };

export function corPartido(id: string): string {
  const conhecido = PARTIDOS_EXEMPLO[id];
  if (conhecido !== undefined) return CORES_PARTIDO[conhecido];
  let hash = 0;
  for (const caractere of id) hash = (hash * 31 + caractere.charCodeAt(0)) >>> 0;
  return CORES_PARTIDO[hash % CORES_PARTIDO.length];
}
