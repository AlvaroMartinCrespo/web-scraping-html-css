#!/usr/bin/env python3
"""
Descarga una pagina web RENDERIZADA (React, Vue, Next, Angular, etc.) usando
un navegador headless (Playwright), y guarda el HTML final, el CSS (enlazado
e inyectado dinamicamente), fuentes e imagenes referenciadas.

Uso:
    python scrape_page_js.py https://ejemplo.com [carpeta_salida]

Requisitos:
    pip install playwright beautifulsoup4 requests
    playwright install chromium

Notas:
    - Respeta el robots.txt / terminos de uso del sitio que scrapees, y no
      abuses con peticiones masivas.
    - Algunos sitios detectan y bloquean navegadores headless (Cloudflare,
      captchas, etc.). Para esos no hay solucion sencilla.
    - Es una herramienta de referencia/inspiracion personal, no un clonador
      para republicar el sitio como propio.
"""

import sys
import os
import re
import hashlib
from urllib.parse import urldefrag, urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL_RE = re.compile(r"url\((['\"]?)(.*?)\1\)")
SRCSET_RE = re.compile(r"(?:data:[^\s]+|[^\s,]+)(?:\s+\d+(?:\.\d+)?[wx])?")


def sanitize_filename(url, default_ext=""):
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "archivo"
    if not os.path.splitext(name)[1] and default_ext:
        name += default_ext
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    stem, ext = os.path.splitext(name)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    return f"{stem}_{digest}{ext}"


def get_content(url, session, network_cache):
    cache_key = urldefrag(url).url
    if cache_key in network_cache:
        return network_cache[cache_key]

    resp = session.get(url, timeout=15)
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "")


def download_file(url, dest_path, session, network_cache):
    try:
        content, _ = get_content(url, session, network_cache)
        with open(dest_path, "wb") as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"  ! No se pudo descargar {url}: {e}")
        return False


def process_css_content(css_text, css_url, assets_dir, session, network_cache, rel_prefix):
    """Busca url(...) dentro del CSS (fuentes, imagenes de fondo) y las descarga."""
    def replace(match):
        quote, ref = match.groups()
        ref = ref.strip()
        if ref.startswith("data:"):
            return match.group(0)
        asset_url = urljoin(css_url, ref)
        filename = sanitize_filename(asset_url)
        local_path = os.path.join(assets_dir, filename)
        if download_file(asset_url, local_path, session, network_cache):
            return f"url({rel_prefix}{filename})"
        return match.group(0)
    return URL_RE.sub(replace, css_text)


def rewrite_srcset(srcset, base_url, img_dir, session, network_cache):
    """Descarga y reescribe los candidatos URL de un atributo srcset."""
    rewritten = []
    for match in SRCSET_RE.finditer(srcset):
        candidate = match.group(0).strip()
        parts = candidate.rsplit(maxsplit=1)
        descriptor = parts[1] if len(parts) == 2 and re.fullmatch(r"\d+(?:\.\d+)?[wx]", parts[1]) else ""
        ref = parts[0] if descriptor else candidate
        if ref.startswith("data:"):
            rewritten.append(candidate)
            continue

        asset_url = urljoin(base_url, ref)
        filename = sanitize_filename(asset_url, ".img")
        local_path = os.path.join(img_dir, filename)
        if download_file(asset_url, local_path, session, network_cache):
            local_ref = f"img/{filename}"
            rewritten.append(f"{local_ref} {descriptor}".rstrip())
        else:
            rewritten.append(candidate)
    return ", ".join(rewritten)


def scrape_page(url, output_dir="sitio_descargado", max_scroll_passes=30, wait_ms=750):
    os.makedirs(output_dir, exist_ok=True)
    css_dir = os.path.join(output_dir, "css")
    img_dir = os.path.join(output_dir, "img")
    assets_dir = os.path.join(output_dir, "assets")
    for d in (css_dir, img_dir, assets_dir):
        os.makedirs(d, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; InspirationScraper/2.0)"})
    network_cache = {}

    print(f"Abriendo {url} en navegador headless...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def capture_response(response):
            if response.request.resource_type not in {"stylesheet", "image", "font", "media"}:
                return
            try:
                content_length = int(response.headers.get("content-length", "0"))
                if content_length and content_length > 25 * 1024 * 1024:
                    return
                network_cache[urldefrag(response.url).url] = (
                    response.body(),
                    response.headers.get("content-type", ""),
                )
            except Exception:
                pass

        page.on("response", capture_response)
        page.goto(url, wait_until="networkidle", timeout=30000)

        # Continua hasta que la pagina deje de crecer durante tres pasadas.
        stable_passes = 0
        previous_height = 0
        for _ in range(max_scroll_passes):
            current_height = page.evaluate("document.documentElement.scrollHeight")
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(wait_ms)
            new_height = page.evaluate("document.documentElement.scrollHeight")
            stable_passes = stable_passes + 1 if new_height == current_height == previous_height else 0
            previous_height = new_height
            if stable_passes >= 3:
                break
        page.wait_for_load_state("networkidle", timeout=10000)

        html = page.content()

        # Backup: hojas de estilo tal como las ve el motor del navegador,
        # por si algun framework las inyecta sin dejarlas como texto en el DOM
        computed_stylesheets = page.evaluate(
            """
            () => Array.from(document.styleSheets).map(sheet => {
                try {
                    return Array.from(sheet.cssRules).map(r => r.cssText).join('\\n');
                } catch (e) {
                    return null; // hoja cross-origin bloqueada por CORS
                }
            }).filter(Boolean)
            """
        )

        for cookie in page.context.cookies():
            session.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain"),
                path=cookie.get("path", "/"),
            )

        browser.close()

    soup = BeautifulSoup(html, "html.parser")

    # --- CSS enlazado (<link rel="stylesheet">) ---
    for link in soup.find_all("link", rel="stylesheet"):
        href = link.get("href")
        if not href:
            continue
        css_url = urljoin(url, href)
        filename = sanitize_filename(css_url, ".css")
        local_path = os.path.join(css_dir, filename)
        print(f"  Descargando CSS: {css_url}")
        try:
            content, content_type = get_content(css_url, session, network_cache)
            charset_match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
            encoding = charset_match.group(1).strip('"\'') if charset_match else "utf-8"
            css_text = content.decode(encoding, errors="replace")
            css_text = process_css_content(
                css_text, css_url, assets_dir, session, network_cache, "../assets/"
            )
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(css_text)
            link["href"] = f"css/{filename}"
        except Exception as e:
            print(f"  ! Fallo con {css_url}: {e}")

    # --- Imagenes normales, perezosas y variantes responsivas (srcset) ---
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if src and not src.startswith("data:"):
            img_url = urljoin(url, src)
            filename = sanitize_filename(img_url, ".img")
            local_path = os.path.join(img_dir, filename)
            if download_file(img_url, local_path, session, network_cache):
                img["src"] = f"img/{filename}"

    for element in soup.find_all(["img", "source"]):
        srcset = element.get("srcset") or element.get("data-srcset")
        if srcset:
            element["srcset"] = rewrite_srcset(srcset, url, img_dir, session, network_cache)

    # --- CSS computado por el navegador (red de seguridad para CSS-in-JS) ---
    if computed_stylesheets:
        extra_css_path = os.path.join(css_dir, "_computed_styles.css")
        with open(extra_css_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(computed_stylesheets))
        print(f"  Guardado CSS computado adicional en {extra_css_path}")

    html_path = os.path.join(output_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    print(f"\nListo. Archivos guardados en: {output_dir}/")
    print(f"   - {html_path}")
    print(f"   - {css_dir}/ (incluye _computed_styles.css si aplica)")
    print(f"   - {img_dir}/")
    print(f"   - {assets_dir}/ (fuentes e imagenes referenciadas desde CSS)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scrape_page_js.py <url> [carpeta_salida]")
        sys.exit(1)
    target_url = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "sitio_descargado"
    scrape_page(target_url, out_dir)
