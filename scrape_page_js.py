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
from typing import Callable
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from url_security import UnsafeUrlError, validate_public_url

URL_RE = re.compile(r"url\((['\"]?)(.*?)\1\)")
ProgressCallback = Callable[[str], None]


class PublicOnlySession(requests.Session):
    def send(self, request, **kwargs):
        validate_public_url(request.url)
        return super().send(request, **kwargs)


def sanitize_filename(url, default_ext=""):
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or "archivo"
    if not os.path.splitext(name)[1] and default_ext:
        name += default_ext
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name


def download_file(url, dest_path, session):
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception as e:
        print(f"  ! No se pudo descargar {url}: {e}")
        return False


def process_css_content(css_text, css_url, assets_dir, session, rel_prefix):
    """Busca url(...) dentro del CSS (fuentes, imagenes de fondo) y las descarga."""
    def replace(match):
        quote, ref = match.groups()
        ref = ref.strip()
        if ref.startswith("data:"):
            return match.group(0)
        asset_url = urljoin(css_url, ref)
        filename = sanitize_filename(asset_url)
        local_path = os.path.join(assets_dir, filename)
        if download_file(asset_url, local_path, session):
            return f"url({rel_prefix}{filename})"
        return match.group(0)
    return URL_RE.sub(replace, css_text)


def scrape_page(
    url,
    output_dir="sitio_descargado",
    scroll_passes=6,
    wait_ms=1500,
    progress: ProgressCallback = print,
):
    url = validate_public_url(url)
    os.makedirs(output_dir, exist_ok=True)
    css_dir = os.path.join(output_dir, "css")
    img_dir = os.path.join(output_dir, "img")
    assets_dir = os.path.join(output_dir, "assets")
    for d in (css_dir, img_dir, assets_dir):
        os.makedirs(d, exist_ok=True)

    session = PublicOnlySession()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; InspirationScraper/2.0)"})

    progress("Abriendo la pagina en un navegador seguro...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        def guard_request(route):
            try:
                request_url = route.request.url
                if urlparse(request_url).scheme in {"http", "https"}:
                    validate_public_url(request_url)
                route.continue_()
            except UnsafeUrlError:
                route.abort("blockedbyclient")

        page.route("**/*", guard_request)
        page.goto(url, wait_until="networkidle", timeout=30000)

        # Scroll progresivo para disparar carga perezosa de imagenes/contenido
        for _ in range(scroll_passes):
            page.evaluate("window.scrollBy(0, window.innerHeight)")
            page.wait_for_timeout(wait_ms // scroll_passes)
        page.wait_for_timeout(wait_ms)

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
        progress(f"Descargando estilos: {urlparse(css_url).netloc}")
        try:
            resp = session.get(css_url, timeout=15)
            resp.raise_for_status()
            css_text = process_css_content(resp.text, css_url, assets_dir, session, "../assets/")
            with open(local_path, "w", encoding="utf-8") as f:
                f.write(css_text)
            link["href"] = f"css/{filename}"
        except Exception as e:
            print(f"  ! Fallo con {css_url}: {e}")

    # --- Imagenes normales + las cargadas de forma perezosa (data-src) ---
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue
        img_url = urljoin(url, src)
        filename = sanitize_filename(img_url, ".img")
        local_path = os.path.join(img_dir, filename)
        if download_file(img_url, local_path, session):
            img["src"] = f"img/{filename}"

    # --- CSS computado por el navegador (red de seguridad para CSS-in-JS) ---
    if computed_stylesheets:
        extra_css_path = os.path.join(css_dir, "_computed_styles.css")
        with open(extra_css_path, "w", encoding="utf-8") as f:
            f.write("\n\n".join(computed_stylesheets))
        progress("Guardando estilos generados por la pagina...")

    html_path = os.path.join(output_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(str(soup))

    progress("Pagina preparada para comprimir.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scrape_page_js.py <url> [carpeta_salida]")
        sys.exit(1)
    target_url = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else "sitio_descargado"
    scrape_page(target_url, out_dir)
