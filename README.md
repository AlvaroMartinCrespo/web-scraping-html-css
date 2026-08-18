# Descargador de paginas web renderizadas

Script de Python que abre una pagina web en Chromium mediante Playwright, espera a que JavaScript genere el contenido, fuerza la carga perezosa mediante scroll y guarda una copia local del HTML, CSS, imagenes, fuentes y otros recursos asociados.

Resulta util para estudiar la estructura y el aspecto de una pagina publica construida con React, Vue, Next.js, Angular u otros frameworks que renderizan contenido en el navegador.

> [!IMPORTANT]
> El script captura una sola URL. No sigue enlaces, no descarga un sitio completo y no reproduce necesariamente toda su funcionalidad interactiva.

## Caracteristicas

- Renderiza JavaScript en un navegador Chromium real.
- Espera a que la actividad de red se estabilice.
- Hace scroll hasta que la altura de la pagina deja de crecer.
- Captura CSS, imagenes, fuentes y contenido multimedia desde la red del navegador.
- Usa `requests` como respaldo cuando un recurso no fue capturado por Playwright.
- Descarga imagenes normales, diferidas y responsivas mediante `src`, `data-src`, `srcset` y `data-srcset`.
- Descarga recursos declarados mediante `url(...)` dentro del CSS.
- Conserva CSS generado o inyectado dinamicamente por JavaScript.
- Genera nombres de archivo unicos y deterministas para evitar sobrescrituras.
- Transfiere las cookies de Playwright a la sesion de descarga.

## Requisitos

- Python 3.8 o posterior.
- Chromium instalado mediante Playwright.

Instala las dependencias:

```bash
python3 -m pip install playwright beautifulsoup4 requests
python3 -m playwright install chromium
```

## Uso

```bash
python3 scrape_page_js.py <url> [carpeta_salida]
```

Ejemplo con la carpeta predeterminada `sitio_descargado`:

```bash
python3 scrape_page_js.py https://ejemplo.com
```

Ejemplo indicando otra carpeta:

```bash
python3 scrape_page_js.py https://ejemplo.com copia_ejemplo
```

Al terminar, abre el archivo `index.html` generado en un navegador para inspeccionar la captura.

## Estructura de salida

```text
sitio_descargado/
├── index.html
├── css/
│   ├── hojas_de_estilo_<hash>.css
│   └── _computed_styles.css
├── img/
│   └── imagenes_<hash>.*
└── assets/
    └── fuentes_y_fondos_<hash>.*
```

| Ruta | Contenido |
| --- | --- |
| `index.html` | DOM final obtenido despues de renderizar y hacer scroll. |
| `css/` | Hojas de estilo enlazadas y CSS accesible desde el navegador. |
| `img/` | Imagenes encontradas en `src`, `data-src` y `srcset`. |
| `assets/` | Fuentes, fondos y otros archivos referenciados desde CSS. |

`_computed_styles.css` funciona como copia de seguridad del CSS visible para el motor del navegador. El script lo guarda, pero no lo enlaza automaticamente desde `index.html`.

## Como funciona

### 1. Preparacion

La funcion `scrape_page()` crea las carpetas de salida y una sesion de `requests`. Tambien inicializa `network_cache`, donde se almacenan recursos obtenidos directamente por Chromium.

### 2. Renderizado con Playwright

Playwright abre la URL con un viewport de 1440 x 900 pixeles. El evento `response` observa las respuestas de red y conserva estos tipos de recursos:

- Hojas de estilo.
- Imagenes.
- Fuentes.
- Audio y video.

Los recursos mayores de 25 MB, cuando el servidor informa su tamano, no se guardan en memoria.

### 3. Scroll hasta estabilizacion

Algunas paginas solo cargan contenido cuando el usuario llega al final. El script baja hasta el fondo, espera 750 ms y vuelve a medir la altura total.

El proceso termina cuando la altura permanece igual durante tres comprobaciones consecutivas o al alcanzar 30 pasadas. Este limite evita bucles infinitos en feeds que siempre generan contenido nuevo.

Los valores pueden ajustarse al llamar a la funcion directamente:

```python
from scrape_page_js import scrape_page

scrape_page(
    "https://ejemplo.com",
    output_dir="copia_ejemplo",
    max_scroll_passes=50,
    wait_ms=1000,
)
```

### 4. Captura del DOM y CSS dinamico

`page.content()` obtiene el HTML final que existe despues de ejecutar JavaScript y completar el scroll.

El script tambien recorre `document.styleSheets` para guardar reglas insertadas por bibliotecas CSS-in-JS. Una hoja externa puede no ser accesible desde JavaScript debido a las restricciones CORS; en ese caso se omite de esta captura adicional.

### 5. Cookies y descarga de recursos

Las cookies creadas durante la navegacion se copian a la sesion de `requests`. Cuando se necesita un archivo, `get_content()` sigue este orden:

1. Busca la URL en `network_cache`.
2. Si no existe, realiza una peticion HTTP con `requests`.

Esto permite reutilizar exactamente muchos de los recursos entregados al navegador y reduce descargas duplicadas.

### 6. Procesamiento del CSS

`process_css_content()` busca expresiones `url(...)`, resuelve rutas relativas contra la URL de la hoja de estilo, descarga el recurso y sustituye la referencia remota por una ruta local dentro de `assets/`.

Las URLs `data:` se mantienen sin cambios porque su contenido ya esta incrustado en el CSS.

### 7. Imagenes responsivas

`rewrite_srcset()` procesa los candidatos de `srcset`, incluidas densidades como `1x` y `2x`, o anchos como `480w` y `1280w`. Cada imagen se descarga y su URL se sustituye por una ruta local.

Por ejemplo:

```html
<img srcset="small.jpg 1x, large.jpg 2x">
```

se convierte conceptualmente en:

```html
<img srcset="img/small_<hash>.jpg 1x, img/large_<hash>.jpg 2x">
```

### 8. Nombres unicos

`sanitize_filename()` limpia caracteres incompatibles y agrega los primeros 12 caracteres de un hash SHA-256 calculado a partir de la URL completa.

Por ejemplo, dos servidores pueden tener un archivo llamado `logo.png`, pero producir nombres locales distintos:

```text
logo_a4c38f90d221.png
logo_8b17f3072ca1.png
```

La misma URL siempre genera el mismo nombre, mientras que URLs distintas no se sobrescriben entre si en condiciones normales.

## Funciones principales

| Funcion | Responsabilidad |
| --- | --- |
| `sanitize_filename()` | Genera un nombre local valido y unico a partir de una URL. |
| `get_content()` | Obtiene bytes desde la cache del navegador o mediante HTTP. |
| `download_file()` | Guarda un recurso y controla errores de descarga. |
| `process_css_content()` | Descarga y reescribe referencias `url(...)` del CSS. |
| `rewrite_srcset()` | Descarga y reescribe candidatos de imagenes responsivas. |
| `scrape_page()` | Coordina navegador, scroll, captura, procesamiento y escritura. |

## Limitaciones

No existe una captura universal que funcione igual en todas las paginas. Este script puede producir resultados incompletos cuando existen:

- CAPTCHA, Cloudflare u otras protecciones contra automatizacion.
- Contenido que requiere autenticacion o interaccion manual.
- Botones, pestanas, carruseles o modales que deben pulsarse para cargar datos.
- WebSockets, streaming o peticiones que nunca permiten alcanzar `networkidle`.
- Shadow DOM o contenido dentro de `iframe`.
- Recursos protegidos mediante DRM o URLs temporales.
- Service workers y logica que solo funciona bajo el dominio original.
- Aplicaciones cuya interactividad depende de bundles JavaScript no descargados.

La copia resultante es principalmente una representacion estatica del estado visible de la pagina. Los formularios, menus, rutas internas y otras interacciones pueden no funcionar sin el servidor original.

## Solucion de problemas

### Falta contenido al final

Aumenta `max_scroll_passes` o `wait_ms`. Algunas paginas tardan mas en insertar nuevos elementos despues del scroll.

### La navegacion supera el tiempo limite

La pagina puede mantener conexiones o peticiones activas de forma permanente. El script usa `networkidle`, por lo que ese comportamiento puede provocar un timeout.

### Una imagen no aparece localmente

Comprueba la salida de la terminal. El servidor puede exigir cabeceras adicionales, bloquear `requests`, entregar una URL temporal o cargar el recurso solamente tras una interaccion.

### El estilo no coincide completamente

Revisa `css/_computed_styles.css`. Ese archivo contiene reglas adicionales, pero no se incorpora automaticamente a `index.html`. Tambien pueden faltar estilos inaccesibles por CORS o dependientes de JavaScript.

## Uso responsable

Respeta siempre:

- El archivo `robots.txt` del sitio.
- Sus terminos de uso y restricciones de acceso.
- Los derechos de autor y licencias del contenido.
- Los datos personales y la privacidad de terceros.
- Limites razonables de frecuencia y volumen de peticiones.

Este proyecto esta pensado para aprendizaje, pruebas y referencia personal. No debe utilizarse para evadir controles de acceso ni para republicar contenido ajeno sin autorizacion.
