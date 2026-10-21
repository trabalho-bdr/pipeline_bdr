"""Download dos ZIPs do TSE, com cache e novas tentativas."""
import http.client
import time
import urllib.error
import urllib.request
import uuid

from .config import CDN_TSE


def url_tse(pasta, nome_zip):
    return f"{CDN_TSE}/{pasta}/{nome_zip}.zip"


def baixar(url, destino, tentativas=3, *, timeout=120, max_bytes=None,
           atualizar=False, validar=None):
    """Baixa url em destino. Devolve 'cache' ou 'baixado'. 404 vira FileNotFoundError."""
    if destino.exists() and destino.stat().st_size > 0 and not atualizar:
        if validar:
            validar(destino)
        return "cache"
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_name(destino.name + "." + uuid.uuid4().hex + ".part")
    erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp, open(parcial, "wb") as saida:
                total = int(resp.headers.get("Content-Length") or 0)
                if max_bytes and total > max_bytes:
                    raise ValueError("Pacote excede o limite de download")
                feito = 0
                ultimo_aviso = time.monotonic()
                while bloco := resp.read(1 << 20):
                    saida.write(bloco)
                    feito += len(bloco)
                    if max_bytes and feito > max_bytes:
                        raise ValueError("Pacote excede o limite de download")
                    agora = time.monotonic()
                    if total and (agora - ultimo_aviso >= 1 or feito == total):
                        print(f"\r     {feito / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="", flush=True)
                        ultimo_aviso = agora
                if total and feito != total:
                    raise ConnectionError(f"Download incompleto: {feito} de {total} bytes")
            print()
            if validar:
                validar(parcial)
            parcial.replace(destino)
            return "baixado"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(url) from e
            erro = e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as e:
            erro = e
        finally:
            parcial.unlink(missing_ok=True)
        print(f"     tentativa {tentativa} falhou: {erro}")
        if tentativa < tentativas:
            time.sleep(5 * tentativa)
    raise RuntimeError(f"Falha ao baixar {url}: {erro}")
