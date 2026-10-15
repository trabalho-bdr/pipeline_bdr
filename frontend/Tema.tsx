import { createContext, type ComponentChildren } from "preact";
import { useContext, useEffect, useLayoutEffect, useState } from "preact/hooks";

type Tema = "dark" | "light";
const chave = "bdr-tema";
const ContextoTema = createContext<{ tema: Tema; alternar: () => void }>({ tema: "dark", alternar: () => {} });

export function ProvedorTema({ children }: { children: ComponentChildren }) {
  const [tema, setTema] = useState<Tema>(() => document.documentElement.dataset.theme === "light" ? "light" : "dark");
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = tema;
    try { localStorage.setItem(chave, tema); } catch { /* Continua funcionando com armazenamento bloqueado. */ }
  }, [tema]);
  useEffect(() => {
    const sincronizar = (e: StorageEvent) => {
      if (e.key === chave || e.key === null) setTema(e.newValue === "light" ? "light" : "dark");
    };
    window.addEventListener("storage", sincronizar);
    return () => window.removeEventListener("storage", sincronizar);
  }, []);
  return <ContextoTema.Provider value={{ tema, alternar: () => setTema((atual) => atual === "dark" ? "light" : "dark") }}>{children}</ContextoTema.Provider>;
}

export function AlternarTema() {
  const { tema, alternar } = useContext(ContextoTema);
  const claro = tema === "light";
  return <button type="button" class="theme-toggle" role="switch" aria-label="Modo claro" aria-checked={claro}
    title={`Ativar modo ${claro ? "escuro" : "claro"}`} onClick={alternar}>
    <span class="theme-toggle-thumb" aria-hidden="true">
      {claro ? <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round">
        <circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
      </svg> : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
        <path d="M19.5 15.2A8 8 0 0 1 8.8 4.5a8 8 0 1 0 10.7 10.7Z" /><path d="m17 3 .7 2.3L20 6l-2.3.7L17 9l-.7-2.3L14 6l2.3-.7Z" />
      </svg>}
    </span><span class="theme-toggle-label" aria-hidden="true">{claro ? "Claro" : "Escuro"}</span>
  </button>;
}
