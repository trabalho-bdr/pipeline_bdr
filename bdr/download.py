"""Download dos ZIPs do TSE, com cache e novas tentativas."""
import http.client
import time
import urllib.error
import urllib.request

from .config import CDN_TSE


def url_tse(pasta, nome_zip):
    return f"{CDN_TSE}/{pasta}/{nome_zip}.zip"


def baixar(url, destino, tentativas=3):
    """Baixa url em destino. Devolve 'cache' ou 'baixado'. 404 vira FileNotFoundError."""
    if destino.exists() and destino.stat().st_size > 0:
        return "cache"
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(".part")
    erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as resp, open(parcial, "wb") as saida:
                total = int(resp.headers.get("Content-Length") or 0)
                feito = 0
                ultimo_aviso = time.monotonic()
                while bloco := resp.read(1 << 20):
                    saida.write(bloco)
                    feito += len(bloco)
                    agora = time.monotonic()
                    if total and (agora - ultimo_aviso >= 1 or feito == total):
                        print(f"\r     {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
                        ultimo_aviso = agora
                if total and feito != total:
                    raise ConnectionError(f"Download incompleto: {feito} de {total} bytes")
            print()
            parcial.replace(destino)
            return "baixado"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(url) from e
            erro = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as e:
            erro = e
        print(f"     tentativa {tentativa} falhou: {erro}")
        if tentativa < tentativas:
            time.sleep(5 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")
