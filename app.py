from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from scrape_page_js import scrape_page
from url_security import UnsafeUrlError, validate_public_url


BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", BASE_DIR / "downloads"))
SITE_URL = os.getenv("SITE_URL", "http://localhost:8000").rstrip("/")
GOOGLE_SITE_VERIFICATION = os.getenv("GOOGLE_SITE_VERIFICATION", "")
JOB_TTL_SECONDS = 60 * 60
MAX_REQUESTS_PER_HOUR = 5


@dataclass
class Job:
    job_id: str
    status: str = "queued"
    message: str = "En cola..."
    zip_path: Path | None = None
    created_at: float = 0


class JobRequest(BaseModel):
    url: str = Field(min_length=10, max_length=2048)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()
request_times: dict[str, deque[float]] = defaultdict(deque)
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="zipweb")


def cleanup_expired_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    with jobs_lock:
        expired = [job_id for job_id, job in jobs.items() if job.created_at < cutoff]
        for job_id in expired:
            jobs.pop(job_id, None)
            shutil.rmtree(DOWNLOAD_DIR / job_id, ignore_errors=True)


def update_job(job_id: str, **changes) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            for field, value in changes.items():
                setattr(job, field, value)


def build_archive(job_id: str, url: str) -> None:
    job_dir = DOWNLOAD_DIR / job_id
    site_dir = job_dir / "sitio"

    try:
        update_job(job_id, status="working", message="Iniciando navegador...")
        scrape_page(url, str(site_dir), progress=lambda message: update_job(job_id, message=message))
        update_job(job_id, message="Creando el archivo ZIP...")
        zip_path = Path(shutil.make_archive(str(job_dir / "pagina-web"), "zip", root_dir=site_dir))
        shutil.rmtree(site_dir, ignore_errors=True)
        update_job(job_id, status="ready", message="Tu descarga esta lista.", zip_path=zip_path)
    except Exception:
        shutil.rmtree(site_dir, ignore_errors=True)
        update_job(
            job_id,
            status="failed",
            message="No se pudo descargar esa pagina. Puede estar protegida o haber agotado el tiempo.",
        )


def enforce_rate_limit(client_ip: str) -> None:
    now = time.time()
    window = request_times[client_ip]
    while window and window[0] < now - 3600:
        window.popleft()
    if len(window) >= MAX_REQUESTS_PER_HOUR:
        raise HTTPException(status_code=429, detail="Has alcanzado el limite de 5 descargas por hora.")
    window.append(now)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_expired_jobs()
    yield


app = FastAPI(title="ZipWeb", docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Language"] = "es-ES"
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    elif request.url.path.startswith("/api/") or request.url.path == "/health":
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
    elif request.url.path in {"/robots.txt", "/sitemap.xml", "/manifest.webmanifest", "/llms.txt"}:
        response.headers["Cache-Control"] = "public, max-age=3600, stale-while-revalidate=86400"
    elif request.url.path == "/":
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"
    return response


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {"site_url": SITE_URL, "google_site_verification": GOOGLE_SITE_VERIFICATION},
    )


@app.post("/api/jobs", status_code=202)
async def create_job(payload: JobRequest, request: Request):
    try:
        url = validate_public_url(payload.url)
    except UnsafeUrlError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    cleanup_expired_jobs()
    enforce_rate_limit(request.client.host if request.client else "unknown")

    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = Job(job_id=job_id, created_at=time.time())
    executor.submit(build_archive, job_id, url)
    return {"job_id": job_id, "status": "queued"}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str):
    cleanup_expired_jobs()
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Trabajo no encontrado.")
        return {"job_id": job.job_id, "status": job.status, "message": job.message}


@app.get("/api/jobs/{job_id}/download")
async def download_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
        if not job or job.status != "ready" or not job.zip_path:
            raise HTTPException(status_code=404, detail="La descarga no esta disponible.")
        zip_path = job.zip_path
    return FileResponse(zip_path, media_type="application/zip", filename="pagina-web.zip")


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    return f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml\n"


@app.get("/sitemap.xml")
async def sitemap():
    last_modified = datetime.fromtimestamp(
        (BASE_DIR / "templates" / "index.html").stat().st_mtime,
        tz=timezone.utc,
    ).date().isoformat()
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{SITE_URL}/</loc><lastmod>{last_modified}</lastmod>"
        "<changefreq>monthly</changefreq><priority>1.0</priority></url>"
        "</urlset>"
    )
    return Response(xml, media_type="application/xml; charset=utf-8")


@app.get("/manifest.webmanifest")
async def manifest():
    return Response(
        content=(
            '{"name":"ZipWeb - Descargar paginas web en ZIP",'
            '"short_name":"ZipWeb",'
            '"description":"Convierte paginas web publicas en archivos ZIP editables.",'
            '"start_url":"/","scope":"/","display":"standalone",'
            '"background_color":"#f5f2eb","theme_color":"#f15a3b",'
            '"lang":"es-ES","icons":['
            '{"src":"/static/favicon.svg","sizes":"any","type":"image/svg+xml","purpose":"any"}]}'
        ),
        media_type="application/manifest+json",
    )


@app.get("/llms.txt", response_class=PlainTextResponse)
async def llms_txt():
    return (
        "# ZipWeb\n\n"
        "> Herramienta gratuita para convertir una pagina web publica en un archivo ZIP editable.\n\n"
        "ZipWeb renderiza la URL con un navegador y recopila el HTML final, estilos CSS, imagenes y fuentes. "
        "Esta pensada para desarrollo, aprendizaje, copias autorizadas y trabajo local.\n\n"
        "## Paginas\n\n"
        f"- [ZipWeb]({SITE_URL}/): formulario para crear el archivo ZIP.\n"
        f"- [Sitemap]({SITE_URL}/sitemap.xml): indice de paginas publicas.\n\n"
        "## Uso responsable\n\n"
        "Solo debe utilizarse sobre contenido propio, de dominio publico o con permiso. "
        "No evita autenticaciones, captchas ni protecciones del sitio de origen.\n\n"
        "## Autor\n\n"
        "Creado por [Alvaro Martin Crespo](https://devalvaro.vercel.app/). "
        "Perfiles: [X](https://x.com/ReactAlvaro), "
        "[GitHub](https://github.com/AlvaroMartinCrespo) y "
        "[LinkedIn](https://www.linkedin.com/in/alvaromartincrespo/).\n"
    )


@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
async def health():
    return "ok"