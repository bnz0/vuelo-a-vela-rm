# Pronóstico para Vuelo a Vela — POC

Reemplazo del boletín DMC "Pronóstico para Vuelo a Vela", que dependía de la
radiosonda de **Santo Domingo (OMM 85586)** — sin lanzamientos desde ~24-jul-2026
(archivo histórico en U. de Wyoming y NOAA IGRA; la estación de superficie sigue
operando).

En su lugar usa un **sondeo pronosticado** de Open-Meteo para 4 sitios de
parapente de la RM (Vizcachas, Cerro Arqueado, Alto del Naranjo, Morro La Reina),
con selector de **modelo GFS (NCEP) o ICON (DWD)** en la barra superior.

Días: **hoy · +1 · +2**. La pestaña "hoy" es la salida del modelo de la corrida
más reciente (no un análisis observado): sirve para contrastar el pronóstico con
lo volado y calibrar la confianza en cada modelo por sitio.

Cada casilla lleva un ícono **(i)** con qué significa y cómo se calcula
(textos en el diccionario `HELP` de `build.py`).

La tabla de viento/temperatura colorea el viento por intensidad (`wind_sev`, celeste
→ rojo), marca en azul las temperaturas bajo 0 °C, lleva flecha de dirección (apunta
corriente abajo) y va invertida (mayor altura arriba) con la presión en hPa entre
paréntesis. Hay una casilla **"En el despegue"** con T máx/mín y humedad del día.

La curva térmica lleva un **campo continuo de nubosidad** al estilo meteograma:
`cloud_cover` de cada nivel de presión dibujado a su altura geopotencial, con
opacidad = cobertura; barras de lluvia (`precipitation`) y tinte de día
(`sunrise`/`sunset`). La curva, la banda y el terreno se dibujan por encima.

En la columna izquierda, bajo la curva térmica, va la **carta sinóptica de
superficie** del Servicio Meteorológico de la Armada de Chile
(`web.directemar.cl/met/jturno/cartas/carta.jpg`, URL fija que se renueva cada ~6 h).
`fetch_carta()` la descarga a `data/carta.jpg` (original en `data/carta_raw.jpg`),
la recomprime con `sips` si está disponible; `build.py` la incrusta **una sola vez**
como `--carta` en el CSS (`.cimg` la usa de `background-image`) porque el sandbox
bloquea imágenes externas y repetir el data URI por panel infla el HTML. La
explicación va en el tooltip (i) del encabezado de esa caja.

Coordenadas y altitud de despegue en `SITES` (build.py). La altitud del DEM que usa
Open-Meteo (~90 m) subestima despegues en espolones angostos como Vizcachas; ahí el
valor de `SITES` es de conocimiento local, no del DEM.

ICON global no publica capa límite ni índice de levantamiento en Open-Meteo: el
techo con ICON se calcula por el método del índice térmico y el LI queda `n/d`.
Añadir un 3er modelo (ECMWF IFS `ecmwf_ifs025`, etc.) es una línea en `MODELS`.

## Uso

    python3 build.py --fetch   # descarga data/gfs_*.json y reconstruye el HTML
    python3 build.py           # sólo reconstruye con los JSON ya bajados

Salida: `../vuelo-a-vela-dashboard.html` (publicado como Artifact:
https://claude.ai/code/artifact/1ba1147c-c249-4e14-b9d0-53a7b9f962dd ).

## Publicación web (GitHub Pages)

`.github/workflows/pages.yml` corre cada día (~06:30 hora de Chile) y en cada push:
ejecuta `WEB_BUILD=1 OUT_HTML=_site/index.html python3 build.py --fetch` y publica
`_site/` en GitHub Pages. `WEB_BUILD` genera un HTML completo (doctype, viewport) sin el
botón "Actualizar pronóstico", que sólo tiene sentido dentro del Artifact. Si la Armada
bloquea la descarga de la carta, se usa la última `data/carta.jpg` versionada en el repo.
Ojo: GitHub desactiva los workflows programados de repos públicos tras 60 días sin
actividad; basta un commit para reactivarlos.

## Versión diaria (Artifact)

`cron` con `build.py --fetch` cada mañana + re-publicar el Artifact (pasando su URL)
o servir el HTML estático. El Artifact no se refresca solo: el sandbox bloquea
`fetch` externo, por eso los datos van incrustados en tiempo de build.

## Sitios / coordenadas

Editables en `SITES` al inicio de `build.py` (lat, lon, elevación de despegue real).
Ajustar a los despegues exactos que uses.

## Limitaciones

- GFS ~13 km: relieve andino suavizado, sin brisas de valle / convergencias locales.
- `velocidad vertical` = w\* estimado (flujo de calor sensible × profundidad de capa
  límite); `techo` = altura de capa límite; `base` = LCL (Espy). Son estimaciones.
- Confirmar con la DMC (consultas@meteochile.gob.cl) si la suspensión de la sonda es
  temporal o definitiva.
