# ZipWeb

Mini aplicacion web que renderiza una URL publica con Chromium y entrega su HTML, CSS, imagenes y fuentes en un ZIP.

## Puesta en marcha

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
uvicorn app:app --reload
```

Abre `http://localhost:8000`. Para publicar el sitio, define la URL canonica:

```bash
SITE_URL=https://tu-dominio.com uvicorn app:app --host 0.0.0.0 --port 8000
```

Para verificar el dominio en Google Search Console, define tambien el contenido de la meta etiqueta que proporciona Google:

```bash
GOOGLE_SITE_VERIFICATION=tu_codigo_de_google
```

## Produccion

- Ejecuta la aplicacion detras de HTTPS y un proxy inverso.
- Mantiene como maximo dos descargas simultaneas y cinco solicitudes por IP y hora. Para varias instancias, sustituye el estado en memoria por Redis y una cola de trabajos.
- Los trabajos y archivos se guardan en almacenamiento efimero del servidor y no se recuperan desde la interfaz al recargar la pagina.
- La validacion bloquea esquemas no HTTP, credenciales y destinos privados. Mantén Chromium y las dependencias actualizados.
- Configura almacenamiento efimero y limites de CPU, memoria y disco en el proveedor de alojamiento.

## Despliegue en Vercel

El frontend y las rutas SEO pueden ejecutarse en Vercel, pero el proceso de descarga actual no es adecuado para sus funciones serverless: abre Chromium, continua trabajando despues de responder, mantiene los trabajos en memoria y genera el ZIP en disco local. La funcion puede detenerse antes de terminar y otra instancia no conocera el trabajo iniciado.

Para conservar la aplicacion tal como esta, despliegala en un servicio con procesos persistentes y soporte para Chromium, como Render, Railway o Fly.io, y configura `SITE_URL` con el dominio publico. Otra opcion es alojar el frontend en Vercel y mover las rutas `/api/jobs` a ese backend. Para ejecutarlo todo en Vercel habria que sustituir Chromium local por un navegador remoto, usar una cola y guardar los resultados en almacenamiento externo.

El usuario debe tener derechos o autorizacion sobre el contenido descargado y respetar `robots.txt`, terminos de uso y propiedad intelectual del sitio de origen.