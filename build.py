# -*- coding: utf-8 -*-
"""
Pronóstico para Vuelo a Vela (POC) — sitios de parapente de la Región Metropolitana.

Sustituye el boletín de la DMC (que dependía de la radiosonda de Santo Domingo 85586,
sin lanzamientos desde ~24-jul-2026) por un sondeo pronosticado de Open-Meteo.
Dos modelos seleccionables: GFS (NCEP) e ICON (DWD).

Uso:
    python3 build.py --fetch     # descarga data/<modelo>_<sitio>.json y reconstruye el HTML
    python3 build.py             # reconstruye el HTML con los JSON ya descargados

Para una versión diaria: cron con `--fetch` cada mañana y luego re-publicar
vuelo-a-vela-dashboard.html como Artifact (o servirlo estático).
"""
import json, math, datetime, html, pathlib, sys, base64, shutil, subprocess, os
from zoneinfo import ZoneInfo
import urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent
DATA = HERE / "data"
OUT = pathlib.Path(os.environ.get("OUT_HTML") or HERE.parent / "vuelo-a-vela-dashboard.html")
WEB = bool(os.environ.get("WEB_BUILD"))   # página web propia (no Artifact): HTML completo, sin botón de actualizar
CL = ZoneInfo("America/Santiago")

# Carta sinóptica de superficie del Servicio Meteorológico de la Armada de Chile.
# Archivo de URL fija que la Armada renueva cada ~6 h; se incrusta como data URI
# porque el sandbox del Artifact bloquea imágenes externas.
CARTA_URL = "https://web.directemar.cl/met/jturno/cartas/carta.jpg"
CARTA_PAGE = "https://meteoarmada.directemar.cl/meteo/cartas-sinopticas/carta-de-superficie-blanco-y-negro"

# clave, nombre, lat, lon, elev_despegue (m, del DEM salvo Vizcachas), nota
SITES = [
    ("vizcachas", "Vizcachas",        -33.594000, -70.505000,  980, "Ladera W · Puente Alto / Camino al Volcán"),
    ("morro",     "Morro La Reina",   -33.465340, -70.482246, 2200, "Precordillera de La Reina · sobre Santiago oriente"),
    ("naranjo",   "Alto del Naranjo", -33.399433, -70.453362, 1890, "Ruta a Cerro Provincia · sube-y-baja largo, sin retirada fácil"),
    ("arqueado",  "Cerro Arqueado",   -33.300809, -70.513277, 1490, "Club de Vuelo Cerro Arqueado · cordón norte de la RM, sobre Chicureo"),
]

# clave, id Open-Meteo, etiqueta, nota corta
MODELS = [
    ("gfs",  "gfs_seamless",  "GFS",  "NCEP · ~13 km"),
    ("icon", "icon_seamless", "ICON", "DWD · ~13 km · capa límite e índice de levantamiento calculados aquí"),
]

LEVELS = [925, 850, 800, 700, 600, 500, 400, 300]
TABLE_ALTS = [1200, 1700, 2200, 2700, 3200, 3700, 4200, 4700]  # m MSL, como el boletin DMC
DRY = 9.8   # °C/km adiabática seca

_BASE = datetime.datetime.now(CL).date()
DAYS = [(_BASE + datetime.timedelta(days=n)).isoformat() for n in (0, 1, 2)]

_PL = ",".join(f"{v}_{L}hPa" for L in LEVELS for v in
               ("temperature", "relative_humidity", "wind_speed", "wind_direction",
                "geopotential_height", "cloud_cover"))
HOURLY = ("temperature_2m,dew_point_2m,relative_humidity_2m,wind_speed_10m,wind_direction_10m,"
          "wind_gusts_10m,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
          "precipitation,shortwave_radiation,cape,lifted_index,convective_inhibition,"
          "boundary_layer_height,pressure_msl,surface_pressure," + _PL)


def _download(url, tries=5):
    """GET con reintentos: desde un runner compartido los timeouts de red son esporádicos."""
    import time
    for n in range(1, tries + 1):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return r.read()
        except Exception as e:
            if n == tries:
                raise
            print(f"  reintento {n}/{tries - 1} tras error: {e}")
            time.sleep(6 * n)


def fetch():
    DATA.mkdir(exist_ok=True)
    for mkey, mid, *_ in MODELS:
        for skey, name, lat, lon, *_ in SITES:
            q = urllib.parse.urlencode({
                "latitude": lat, "longitude": lon, "timezone": "America/Santiago",
                "forecast_days": 3, "models": mid,
                "daily": "temperature_2m_max,sunrise,sunset", "hourly": HOURLY})
            url = "https://api.open-meteo.com/v1/forecast?" + q
            (DATA / f"{mkey}_{skey}.json").write_bytes(_download(url))
            print("fetched", mkey, skey)
    fetch_week()
    fetch_carta()


def fetch_week():
    """Pronóstico de 7 días (GFS) por sitio: sólo nubes, lluvia, temperatura y viento."""
    for skey, name, lat, lon, *_ in SITES:
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "timezone": "America/Santiago",
            "forecast_days": 7, "models": "gfs_seamless",
            "hourly": "temperature_2m,cloud_cover,precipitation,wind_speed_10m,wind_direction_10m,wind_gusts_10m"})
        (DATA / f"week_{skey}.json").write_bytes(_download("https://api.open-meteo.com/v1/forecast?" + q))
        print("fetched week", skey)


def fetch_carta():
    """Baja la carta sinóptica de superficie de la Armada y, si hay `sips`, la recomprime."""
    raw = DATA / "carta_raw.jpg"
    out = DATA / "carta.jpg"
    try:
        req = urllib.request.Request(CARTA_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            raw.write_bytes(r.read())
    except Exception as e:
        print("carta sinóptica no disponible:", e)
        return
    if shutil.which("sips"):
        try:
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "62",
                            str(raw), "--out", str(out)], check=True, capture_output=True)
        except Exception:
            shutil.copy(raw, out)
    else:
        shutil.copy(raw, out)
    print("fetched carta sinóptica", out.stat().st_size, "bytes")


def load(mkey, skey):
    return json.load(open(DATA / f"{mkey}_{skey}.json"))


def kmh_to_kt(v): return v / 1.852

def deg_to_card(d):
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    return dirs[int((d % 360) / 22.5 + 0.5) % 16]

def deg_range(d):
    lo = int(round((d - 10) % 360, -1)) % 360
    return f"{lo:03d}-{(lo + 20) % 360:03d}"

def wind_sev(v):
    """Nivel 0–4 de intensidad / peligrosidad del viento en km/h para el color de la tabla."""
    return 0 if v < 12 else 1 if v < 22 else 2 if v < 32 else 3 if v < 45 else 4

def wind_arrow(d):
    """Flecha que apunta hacia dónde sopla el viento (corriente abajo); d = dirección de procedencia."""
    return (f'<svg class="warr" viewBox="0 0 12 12" aria-hidden="true" '
            f'style="transform:rotate({(d + 180) % 360:.0f}deg)">'
            f'<path d="M6 1.5V10M6 1.5 3.3 5.2M6 1.5 8.7 5.2"/></svg>')

def interp_profile(hourly, i, elev, t2m):
    """Lista (h_msl, T, u, v) ordenada por altura, incluyendo superficie."""
    pts = [(elev, t2m, None, None)]
    for L in LEVELS:
        gh = hourly[f"geopotential_height_{L}hPa"][i]
        T = hourly[f"temperature_{L}hPa"][i]
        sp = hourly[f"wind_speed_{L}hPa"][i]
        wd = hourly[f"wind_direction_{L}hPa"][i]
        if gh is None or T is None or gh <= elev:
            continue
        u = None if sp is None else -sp * math.sin(math.radians(wd))
        v = None if sp is None else -sp * math.cos(math.radians(wd))
        pts.append((gh, T, u, v))
    pts.sort(key=lambda p: p[0])
    return pts

def sample_temp(pts, z):
    for (z0, T0, *_), (z1, T1, *_) in zip(pts, pts[1:]):
        if z0 <= z <= z1:
            f = (z - z0) / (z1 - z0) if z1 != z0 else 0
            return T0 + f * (T1 - T0)
    return pts[0][1] if z < pts[0][0] else pts[-1][1]

def sample_wind(pts, z):
    wpts = [p for p in pts if p[2] is not None]
    if not wpts:
        return 0.0, 0.0
    for (z0, _, u0, v0), (z1, _, u1, v1) in zip(wpts, wpts[1:]):
        if z0 <= z <= z1:
            f = (z - z0) / (z1 - z0) if z1 != z0 else 0
            u, v = u0 + f * (u1 - u0), v0 + f * (v1 - v0)
            return math.hypot(u, v), math.degrees(math.atan2(-u, -v)) % 360
    z0, _, u0, v0 = wpts[0]
    return math.hypot(u0, v0), math.degrees(math.atan2(-u0, -v0)) % 360

def ti_top(pts, t_surf, elev):
    """Tope de convección seca: adiabática seca desde (elev, t_surf) hasta cortar el entorno."""
    z = elev + 50
    while z <= elev + 6000:
        parcel = t_surf - DRY * (z - elev) / 1000.0
        if parcel <= sample_temp(pts, z):
            return z
        z += 40
    return elev + 6000

def day_indices(t, day):
    return [k for k, ts in enumerate(t) if ts.startswith(day) and 8 <= int(ts[11:13]) <= 21]


def analyse(site, day, model):
    skey, name, lat, lon, elev_real, note = site
    mkey, mid, mlabel, mnote = model
    d = load(mkey, skey); h = d["hourly"]; t = h["time"]
    elev = d["elevation"]
    di = day_indices(t, day)
    i18 = t.index(f"{day}T14:00")

    def _hm(s):
        return int(s[11:13]) + int(s[14:16]) / 60.0
    try:
        dd = d["daily"]["time"].index(day)
        sunrise, sunset = _hm(d["daily"]["sunrise"][dd]), _hm(d["daily"]["sunset"][dd])
    except Exception:
        sunrise, sunset = 7.5, 19.0

    tmax = max(h["temperature_2m"][k] for k in di)
    tmin = min(h["temperature_2m"][k] for k in di)
    hour_tmax = int(t[max(di, key=lambda k: h["temperature_2m"][k])][11:13])
    rh_day = [h["relative_humidity_2m"][k] for k in di if h["relative_humidity_2m"][k] is not None]
    rh_lo, rh_hi = (min(rh_day), max(rh_day)) if rh_day else (0, 0)
    rh_mid = h["relative_humidity_2m"][i18]
    td_mid = h["dew_point_2m"][i18]
    qnh = round(h["pressure_msl"][i18])

    pts18 = interp_profile(h, i18, elev, h["temperature_2m"][i18])

    # presión (hPa) por altura: interpolación log-P sobre la altura geopotencial del modelo
    ghp = sorted((h[f"geopotential_height_{L}hPa"][i18], L) for L in LEVELS
                 if h[f"geopotential_height_{L}hPa"][i18] is not None)
    def press_at(z):
        if not ghp:
            return round(1013.25 * (1 - 2.25577e-5 * z) ** 5.25588)
        if z <= ghp[0][0]:
            z0, p0 = ghp[0]; return round(p0 * math.exp((z0 - z) / 7500.0))
        if z >= ghp[-1][0]:
            z0, p0 = ghp[-1]; return round(p0 * math.exp((z0 - z) / 7500.0))
        for (z0, p0), (z1, p1) in zip(ghp, ghp[1:]):
            if z0 <= z <= z1:
                f = (z - z0) / (z1 - z0)
                return round(math.exp(math.log(p0) + f * (math.log(p1) - math.log(p0))))
        return None

    rows = []
    for z in TABLE_ALTS:
        sp, wd = sample_wind(pts18, z)
        T = sample_temp(pts18, z)
        lo = max(0, int(round(sp / 5.0)) * 5)      # viento en km/h, banda de 10
        rows.append({"alt": z, "hpa": press_at(z), "dir": deg_range(wd), "wd": wd,
                     "kmh": f"{lo:02d}-{lo + 10:02d}",
                     "kmh_val": sp, "wsev": wind_sev(sp),
                     "temp": (f"M{abs(round(T)):02d}" if round(T) < 0 else f"{round(T):02d}"),
                     "neg": round(T) < 0})

    blh_native_avail = any(h["boundary_layer_height"][k] is not None for k in di)
    top_src = "capa límite del modelo" if blh_native_avail else "método del índice térmico"

    prof = []
    for k in di:
        hh = int(t[k][11:13])
        t2 = h["temperature_2m"][k]; td = h["dew_point_2m"][k]
        pp = interp_profile(h, k, elev, t2)
        blh_n = h["boundary_layer_height"][k]
        if blh_n is not None and blh_n > 0:
            top = elev + blh_n
        else:
            top = ti_top(pp, t2, elev)
        zi = max(0.0, top - elev)
        lcl = elev + max(0.0, 122 * (t2 - td))
        sw = h["shortwave_radiation"][k] or 0
        Hs = max(0.0, 0.16 * sw - 15)
        wstar = (9.8 / 285.0 * (Hs / (1.2 * 1005.0)) * zi) ** (1/3) if zi > 0 and Hs > 0 else 0.0
        # perfil vertical de nubosidad: cloud_cover en cada nivel de presión, a su altura
        ccol = [(elev + 40, h["cloud_cover_low"][k] or 0)]
        for L in LEVELS:
            gh = h[f"geopotential_height_{L}hPa"][k]
            cc = h[f"cloud_cover_{L}hPa"][k]
            if gh is not None and cc is not None and gh > elev + 40:
                ccol.append((gh, cc))
        ccol.sort()
        prof.append({"h": hh, "top": top, "lcl": lcl, "wstar": wstar,
                     "t2": t2, "sw": sw, "zi": zi, "active": zi >= 350 and sw >= 150,
                     "cl_lo": h["cloud_cover_low"][k] or 0, "cl_mid": h["cloud_cover_mid"][k] or 0,
                     "cl_hi": h["cloud_cover_high"][k] or 0, "ccol": ccol,
                     "pr": h["precipitation"][k] or 0})

    mid_hours = [p for p in prof if 11 <= p["h"] <= 16]
    top_max = max((p["top"] for p in mid_hours), default=elev)
    lcl_min = min((p["lcl"] for p in mid_hours), default=elev + 4000)
    act = [p for p in mid_hours if p["active"]] or mid_hours
    wbar = sum(p["wstar"] for p in act) / len(act) if act else 0
    wmax = max((p["wstar"] for p in mid_hours), default=0)
    netto_bar = max(0.0, 0.8 * wbar - 1.0)

    cumulus = lcl_min < top_max - 80
    ceiling = min(top_max, lcl_min) if cumulus else top_max
    band = max(0, ceiling - elev_real)

    active_hours = [p["h"] for p in prof if p["active"]]
    win = (min(active_hours), max(active_hours) + 1) if active_hours else None

    # viento dentro de la banda volable: del despegue al techo, muestreado cada ~300 m
    z_floor = elev_real
    z_ceil = max(ceiling, elev_real + 400)
    n_s = max(3, int(round((z_ceil - z_floor) / 300)) + 1)
    zs = [z_floor + (z_ceil - z_floor) * k / (n_s - 1) for k in range(n_s)]
    wl = [sample_wind(pts18, z)[0] for z in zs]
    wmean = sum(wl) / len(wl)
    wpk = max(wl)
    wpk_z = zs[wl.index(wpk)]
    band_lo, band_hi = round(z_floor, -2), round(z_ceil, -2)
    def pen_rate(v):
        if v < 15: return "BUENA", "go"
        if v < 25: return "REGULAR", "cau"
        if v < 35: return "MARGINAL", "cau"
        return "MALA", "no"
    pen_ave, pen_max = pen_rate(wmean), pen_rate(wpk)

    # viento y rachas en superficie (10 m) durante la franja de vuelo
    fly = [k for k in di if 10 <= int(t[k][11:13]) <= 19]
    w10 = [h["wind_speed_10m"][k] for k in fly]
    g10 = [h["wind_gusts_10m"][k] for k in fly if h["wind_gusts_10m"][k] is not None]
    w10_bar = sum(w10) / len(w10) if w10 else 0.0
    gust_max = max(max(g10), w10_bar) if g10 else None   # el campo de rachas del GFS a veces < viento medio
    gust_hour = int(t[fly[max(range(len(fly)), key=lambda n: h["wind_gusts_10m"][fly[n]] or 0)]][11:13]) if g10 else None
    gust_factor = (gust_max / max(w10_bar, 1.0)) if gust_max else None
    if gust_max is None:
        surf = ("n/d", None, "el modelo no entrega rachas")
    elif gust_max >= 38 or w10_bar >= 25:
        surf = ("FUERTE", "no", "lanzamiento y aterrizaje comprometidos")
    elif gust_max >= 26 or w10_bar >= 16:
        surf = ("MODERADO", "cau", "exige técnica de despegue y atención en el aterrizaje")
    else:
        surf = ("SUAVE", "go", "condiciones de superficie manejables")

    cape = h["cape"][i18] or 0
    cape_day = max((h["cape"][k] or 0) for k in di)
    li = h["lifted_index"][i18]          # None en ICON (Open-Meteo no lo publica)
    ccmid = max((h["cloud_cover_mid"][k] or 0) for k in di)
    cchigh = max((h["cloud_cover_high"][k] or 0) for k in di)
    if cape_day >= 300 or (li is not None and li <= -3):
        overdev = ("ALTO", "no", "Posibles cumulonimbos / sobredesarrollo en la tarde. Vigilar el crecimiento vertical.")
    elif cape_day >= 120 or (li is not None and li <= -1) or (ccmid >= 55 and cumulus):
        overdev = ("MODERADO", "cau", "Los cúmulos pueden crecer sobre el relieve. Aterrizar si se aplanan las bases o se oscurecen.")
    else:
        overdev = ("BAJO", "go", "Atmósfera estable en niveles medios; sin señales de sobredesarrollo.")

    if cumulus:
        nubes = f"Cúmulos de buen tiempo, base ~{round(lcl_min, -1):.0f} m MSL."
    elif cchigh >= 40:
        nubes = f"Térmica azul; nubosidad alta {round(cchigh)}% que puede recortar la radiación."
    else:
        nubes = "Térmica azul (sin cúmulos que marquen la ascendencia)."

    pmsl = [h["pressure_msl"][k] for k in di]
    dp = pmsl[-1] - pmsl[0]
    sp500, wd500 = sample_wind(pts18, 5600)
    synop = []
    if qnh >= 1018 and abs(dp) <= 1.5:
        synop.append("Dorsal en altura y alta presión en superficie: subsidencia, aire seco e inversión que limita el techo.")
    elif dp <= -2:
        synop.append("Presión en descenso: se aproxima una vaguada; gradiente y nubosidad en aumento hacia el final del período.")
    elif dp >= 2:
        synop.append("Presión en ascenso tras el paso de un sistema: mejora progresiva, aire aún algo inestable y húmedo.")
    else:
        synop.append("Situación sinóptica sin forzamiento marcado.")
    if band < 400:
        synop.append(f"Banda de trabajo estrecha (~{band:.0f} m sobre el despegue): día de vuelo corto y local.")
    elif band < 900:
        synop.append(f"Banda de trabajo moderada (~{band:.0f} m sobre el despegue).")
    else:
        synop.append(f"Buena banda de trabajo (~{band:.0f} m sobre el despegue).")
    if wmean >= 25:
        synop.append("Viento fuerte en cota de vuelo: penetración comprometida para parapente; atención al sotavento del relieve.")
    elif wmean >= 15:
        synop.append("Viento moderado en altura: exige atención a la penetración y a los rotores a sotavento.")
    if wbar < 1.3:
        synop.append("Ascendencias débiles y angostas: conviene esperar las horas centrales y volar ligero.")
    if gust_max is not None and gust_max >= 26:
        gf = f" (factor {gust_factor:.1f})" if gust_factor and gust_factor >= 1.15 else ""
        synop.append(f"Rachas en superficie hasta {round(gust_max)} km/h hacia las {gust_hour:02d}:00{gf}: "
                     f"despegue y aterrizaje exigentes, sobre todo con la térmica activa.")

    score = 0
    score += 2 if wbar >= 2.2 else 1 if wbar >= 1.4 else 0
    score += 2 if band >= 900 else 1 if band >= 400 else 0
    score += 2 if wmean < 15 else 1 if wmean < 25 else 0
    score -= 2 if overdev[1] == "no" else 0
    score -= 2 if surf[1] == "no" else 1 if surf[1] == "cau" else 0
    verdict = ("VOLABLE", "go") if score >= 5 else ("MARGINAL", "cau") if score >= 3 else ("POCO VOLABLE", "no")

    return dict(skey=skey, name=name, note=note, elev_real=elev_real, elev_model=elev,
               mlabel=mlabel, top_src=top_src,
               tmax=tmax, tmin=tmin, hour_tmax=hour_tmax, rh_lo=rh_lo, rh_hi=rh_hi,
               rh_mid=rh_mid, td_mid=td_mid, qnh=qnh, rows=rows, prof=prof,
               top_max=top_max, lcl_min=lcl_min, cumulus=cumulus, ceiling=ceiling, band=band,
               sunrise=sunrise, sunset=sunset,
               wbar=wbar, wmax=wmax, netto_bar=netto_bar, win=win, wmean=wmean,
               wpk=wpk, wpk_z=wpk_z, band_lo=band_lo, band_hi=band_hi,
               pen_ave=pen_ave, pen_max=pen_max, cape=cape, li=li, overdev=overdev,
               w10_bar=w10_bar, gust_max=gust_max, gust_hour=gust_hour, gust_factor=gust_factor, surf=surf,
               nubes=nubes, synop=synop, verdict=verdict)


# ---------- SVG ----------
def svg_chart(a):
    W, H = 560, 366
    ml, mr, mt, mb = 52, 16, 22, 30
    pw, ph = W - ml - mr, H - mt - mb
    hmin, hmax = 8, 20
    zmax = max(5000, math.ceil((a["top_max"] + 600) / 500) * 500)
    def X(hr): return ml + (hr - hmin) / (hmax - hmin) * pw
    def Y(z):  return mt + (1 - z / zmax) * ph
    prof = [p for p in a["prof"] if hmin <= p["h"] <= hmax]
    def path(key):
        return "M" + " L".join(f"{X(p['h']):.1f},{Y(p[key]):.1f}" for p in prof)
    ceil_pts = [(p["h"], min(p["top"], p["lcl"]) if a["cumulus"] else p["top"]) for p in prof]
    band = ""
    if ceil_pts:
        band = ("M" + " L".join(f"{X(hr):.1f},{Y(c):.1f}" for hr, c in ceil_pts)
                + " L" + " L".join(f"{X(hr):.1f},{Y(a['elev_real']):.1f}" for hr, _ in reversed(ceil_pts)) + " Z")
    p = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Curva térmica y nubosidad: altitud vs hora en {a["name"]}">']
    p.append('<defs><linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
             '<stop offset="0" stop-color="var(--sky-hi)"/><stop offset="1" stop-color="var(--sky-lo)"/></linearGradient></defs>')
    p.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="var(--ct-bg)"/>')
    p.append(f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="url(#sky)"/>')

    half = pw / (hmax - hmin) / 2

    # --- día: tinte cálido tenue entre el amanecer y el ocaso ---
    d0, d1 = max(hmin, a["sunrise"]), min(hmax, a["sunset"])
    if d1 > d0:
        p.append(f'<rect x="{X(d0):.1f}" y="{mt}" width="{X(d1)-X(d0):.1f}" height="{ph}" fill="var(--day)"/>')

    # --- campo continuo de nubosidad: cloud_cover del modelo en cada nivel de presión, a su altura ---
    def cc_at(ccol, z):
        if not ccol: return 0.0
        if z <= ccol[0][0]: return ccol[0][1]
        if z >= ccol[-1][0]: return ccol[-1][1]
        for (z0, c0), (z1, c1) in zip(ccol, ccol[1:]):
            if z0 <= z <= z1:
                f = (z - z0) / (z1 - z0) if z1 != z0 else 0
                return c0 + f * (c1 - c0)
        return 0.0
    def cc_op(cc):
        return 0.0 if cc < 6 else round(min(0.56, (cc / 100.0) ** 0.9 * 0.62), 2)
    zstep = max(110, zmax / 42)
    for pt in prof:
        x0 = max(ml, X(pt["h"]) - half); x1 = min(ml + pw, X(pt["h"]) + half); w = x1 - x0
        cur, run0, z = None, 0.0, 0.0
        while z <= zmax + zstep:
            op = cc_op(cc_at(pt["ccol"], min(z + zstep / 2, zmax)))
            if op != cur:
                if cur:
                    p.append(f'<rect x="{x0:.1f}" y="{Y(min(z, zmax)):.1f}" width="{w:.1f}" '
                             f'height="{Y(run0)-Y(min(z, zmax)):.1f}" fill="var(--cloud)" fill-opacity="{cur}"/>')
                cur, run0 = (op if op else None), z
            z += zstep
        # cirrus por encima de la escala del gráfico: franja fina arriba
        if pt["cl_hi"] >= 12:
            p.append(f'<rect x="{x0:.1f}" y="{mt}" width="{w:.1f}" height="13" '
                     f'fill="var(--cloud)" fill-opacity="{cc_op(pt["cl_hi"])}"/>')

    for z in range(0, int(zmax) + 1, 1000):
        p.append(f'<line x1="{ml}" y1="{Y(z):.1f}" x2="{ml+pw}" y2="{Y(z):.1f}" stroke="var(--grid)" stroke-width="1"/>')
        p.append(f'<text x="{ml-8}" y="{Y(z)+3:.1f}" text-anchor="end" class="ct">{z}</text>')
    for hr in range(8, 21, 2):
        p.append(f'<line x1="{X(hr):.1f}" y1="{mt}" x2="{X(hr):.1f}" y2="{mt+ph}" stroke="var(--grid)" stroke-width="1"/>')
        p.append(f'<text x="{X(hr):.1f}" y="{H-10}" text-anchor="middle" class="ct">{hr:02d}</text>')
    p.append(f'<rect x="{ml}" y="{Y(a["elev_real"]):.1f}" width="{pw}" height="{mt+ph-Y(a["elev_real"]):.1f}" fill="var(--terrain)"/>')
    p.append(f'<line x1="{ml}" y1="{Y(a["elev_real"]):.1f}" x2="{ml+pw}" y2="{Y(a["elev_real"]):.1f}" stroke="var(--terrain-edge)" stroke-width="1.5"/>')
    if band:
        p.append(f'<path d="{band}" fill="var(--band)"/>')
    p.append(f'<path d="{path("top")}" fill="none" stroke="var(--top-line)" stroke-width="2.5"/>')
    if a["cumulus"]:
        p.append(f'<path d="{path("lcl")}" fill="none" stroke="var(--lcl-line)" stroke-width="2" stroke-dasharray="5 4"/>')

    # --- precipitación: barras azules desde el terreno hacia arriba ---
    pr_max = max((pt["pr"] for pt in prof), default=0)
    if pr_max >= 0.1:
        base_y = Y(a["elev_real"])
        pr_k = min(ph * 0.42, 60) / max(pr_max, 1.5)
        for pt in prof:
            if pt["pr"] and pt["pr"] >= 0.1:
                bh = min(pt["pr"] * pr_k, ph * 0.5)
                p.append(f'<rect x="{X(pt["h"])-2.2:.1f}" y="{base_y-bh:.1f}" width="4.4" height="{bh:.1f}" '
                         f'fill="var(--precip)"/>')
        p.append(f'<text x="{ml+4}" y="{base_y-4:.1f}" class="ct" fill="var(--precip)">lluvia {pr_max:.1f} mm/h máx</text>')

    p.append(f'<text x="{ml}" y="12" class="cl">Altitud m MSL</text>')
    p.append(f'<text x="{ml+pw}" y="12" text-anchor="end" class="cl">Nubosidad · tono = cobertura</text>')
    p.append(f'<text x="{ml}" y="{H-1}" class="cl">Hora local</text>')
    p.append('</svg>')
    return "".join(p)


def esc(s): return html.escape(str(s))

# qué significa cada casilla y cómo se calcula — texto de los tooltips (i)
HELP = {
 "veredicto": "Síntesis VOLABLE / MARGINAL / POCO VOLABLE a partir de un puntaje: suma por "
   "velocidad vertical (w*), por ancho de la banda de trabajo y por viento suave en cota; "
   "resta por sobredesarrollo alto y por viento de superficie fuerte o muy racheado.",
 "despegue": "Temperatura y humedad del aire a 2 m que el modelo pronostica para el día "
   "seleccionado: máxima / mínima, hora de la máxima, rango de humedad relativa y punto de rocío "
   "al mediodía. Referencia para vestimenta, densidad del aire y margen hasta la saturación.",
 "ventana": "Horas en que la capa límite convectiva supera ~350 m y la radiación solar basta "
   "para disparar térmicas (≳150 W/m²). Fuera de esa franja la ascendencia es marginal o nula.",
 "techo": "Altura máxima estimada de la térmica. Con GFS = altura de la capa límite del modelo; "
   "con ICON = método del índice térmico (adiabática seca desde la temperatura de superficie hasta "
   "cortar el perfil del entorno). Si hay cúmulos se recorta a la base de la nube.",
 "base": "Nivel de condensación por convección — fórmula de Espy: ≈122·(T−Td) m sobre el despegue, "
   "con T y punto de rocío de superficie. «Azul» = la base queda sobre el techo térmico: sin "
   "cúmulos que marquen la ascendencia.",
 "wstar": "w* (escala de velocidad convectiva) promediado en las horas centrales, estimado del "
   "flujo de calor sensible en superficie (derivado de la radiación) y de la profundidad de la "
   "capa límite. «Neto útil» ≈ 0,8·w* − 1 m/s descuenta la tasa de caída del parapente y la "
   "ineficiencia al centrar la térmica.",
 "sup": "Viento medio y racha máxima a 10 m del suelo (campo wind_gusts_10m del modelo) entre las "
   "10 y las 19 h. El factor de racha es racha ÷ media. SUAVE / MODERADO / FUERTE según umbrales "
   "de racha de 26 y 38 km/h (o de media de 16 y 25 km/h).",
 "cota": "Viento del modelo a las 14:00 local dentro de la banda volable —del despegue al techo "
   "estimado, muestreado cada ~300 m e interpolado de los niveles de presión por su altura "
   "geopotencial. El primer número es el promedio de esa banda; el segundo, el máximo, con la "
   "altura donde ocurre. Es el viento que realmente enfrentas volando; determina la penetración.",
 "pen": "Capacidad de avanzar contra el viento. Ambos valores se calculan en la misma banda "
   "volable (despegue → techo): MEDIA = promedio del viento en esa banda, MÁX = el peor tramo. "
   "BUENA <15 · REGULAR 15–25 · MARGINAL 25–35 · MALA >35 km/h. Con parapente, penetrar contra "
   ">30–35 km/h deja poco avance real.",
 "over": "Riesgo de que los cúmulos crezcan a cumulonimbos. ALTO / MODERADO / BAJO según el CAPE "
   "del día, el índice de levantamiento (LI, sólo GFS) y la nubosidad media. Con ICON el LI no "
   "está disponible: se evalúa con CAPE y nubes.",
}

def ttmark(text):
    if not text:
        return ""
    return ('<button type="button" class="tt" aria-label="Qué significa y cómo se calcula">'
            '<span class="tt-i" aria-hidden="true">i</span>'
            f'<span class="tt-box" role="tooltip">{esc(text)}</span></button>')

def tile(label, value, sub="", sev=None, help=""):
    cls = f' data-sev="{sev}"' if sev else ""
    s = f'<div class="tile-s">{esc(sub)}</div>' if sub else ""
    return (f'<div class="tile"{cls}><div class="tile-l">{esc(label)}{ttmark(help)}</div>'
            f'<div class="tile-v">{value}</div>{s}</div>')

def render_site(a, i, j, m, carta_fig=""):
    v, vs = a["verdict"]
    win = f'{a["win"][0]:02d}:00–{a["win"][1]:02d}:00' if a["win"] else "sin ventana"
    base_txt = f'{round(a["lcl_min"], -1):.0f} m' if a["cumulus"] else "azul"
    t_techo = tile("Techo estimado", f'{round(a["ceiling"], -1):.0f} m', f'≈ +{round(a["ceiling"]-a["elev_real"]):.0f} m s/ despegue ({a["top_src"]})', help=HELP["techo"])
    t_ventana = tile("Ventana térmica", win, "capa límite ≥ 350 m y radiación suficiente", help=HELP["ventana"])
    t_despegue = tile("En el despegue",
             f'{a["tmax"]:.0f}<i>/</i>{a["tmin"]:.0f}<span class="u">°C</span>',
             f'máx {a["hour_tmax"]:02d}h · HR {a["rh_lo"]:.0f}–{a["rh_hi"]:.0f}% · rocío {a["td_mid"]:.0f}°',
             help=HELP["despegue"])
    t_sup = tile("Viento superficie",
             (f'{round(a["w10_bar"])}<i>/</i>{round(a["gust_max"])}<span class="u">km/h</span>' if a["gust_max"] is not None
              else 'n/d'),
             ((f'media / racha máx {a["gust_hour"]:02d}h'
               + (f' · factor {a["gust_factor"]:.1f}' if a["gust_factor"] and a["gust_factor"] >= 1.15 else '')
               + f' · {a["surf"][2]}')
              if a["gust_max"] is not None else a["surf"][2]),
             a["surf"][1], help=HELP["sup"])
    t_wstar = tile("Velocidad vertical", f'{a["wbar"]:.1f}<span class="u">m/s</span>', f'máx ~{a["wmax"]:.1f} · neto útil ~{a["netto_bar"]:.1f} m/s', help=HELP["wstar"])
    t_base = tile("Base de nube", base_txt, "cúmulos de buen tiempo" if a["cumulus"] else "sin cúmulos que marquen la térmica", help=HELP["base"])
    t_cota = tile("Viento en la banda", f'{round(a["wmean"])}<i>/</i>{round(a["wpk"])}<span class="u">km/h</span>',
                  f'medio / máx entre {a["band_lo"]:.0f} y {a["band_hi"]:.0f} m MSL (despegue → techo) · pico a ~{round(a["wpk_z"], -2):.0f} m',
                  help=HELP["cota"])
    t_veredicto = tile("Veredicto", esc(v), a["note"], vs, help=HELP["veredicto"])
    tiles = "".join([t_techo, t_ventana, t_despegue, t_sup, t_wstar, t_base, t_cota, t_veredicto])
    trow = "".join(
        f'<tr><td class="alt">{r["alt"]} <i>({r["hpa"]})</i></td>'
        f'<td class="dir">{wind_arrow(r["wd"])}{r["dir"]}</td>'
        f'<td class="w w{r["wsev"]}">{r["kmh"]}</td>'
        f'<td class="tp{" neg" if r["neg"] else ""}">{r["temp"]}</td></tr>'
        for r in reversed(a["rows"]))          # suelo abajo: mayor altura arriba
    synop = "".join(f"<li>{esc(s)}</li>" for s in a["synop"])
    od_w, od_s, od_t = a["overdev"]
    pa_w, pa_s = a["pen_ave"]; px_w, px_s = a["pen_max"]
    li_txt = "n/d" if a["li"] is None else f'{a["li"]}'
    hidden = "" if (i == 0 and j == 0 and m == 0) else " hidden"
    return f'''<section class="site" id="site-{i}-{j}-{m}"{hidden}>
  <div class="tiles">{tiles}</div>
  <div class="grid2">
    <div class="colL">
    <figure class="chart">
      <figcaption>Curva térmica — banda de trabajo (despegue → techo), hora local · modelo {esc(a["mlabel"])}</figcaption>
      {svg_chart(a)}
      <div class="legend">
        <span><i class="sw-band"></i>banda útil</span>
        <span><i class="sw-top"></i>tope de convección</span>
        {'<span><i class="sw-lcl"></i>base de cúmulos</span>' if a["cumulus"] else ''}
        <span><i class="sw-ramp"></i>nubosidad 10→100 % (a su altura)</span>
        <span><i class="sw-precip"></i>lluvia</span>
        <span><i class="sw-day"></i>día</span>
      </div>
    </figure>
    {carta_fig}
    </div>
    <div class="panels">
      <div class="panel">
        <h4>Viento y temperatura pronosticados · 14:00 local (18 UTC)</h4>
        <table class="wt">
          <thead><tr><th>Altitud<br><span>m MSL · hPa</span></th><th>Dirección<br><span>de dónde · ➜ hacia</span></th><th>Viento<br><span>km/h</span></th><th>Temp<br><span>°C</span></th></tr></thead>
          <tbody>{trow}</tbody>
        </table>
        <p class="fine">QNH {a["qnh"]} hPa · T.máx {a["tmax"]:.0f}°C a las {a["hour_tmax"]:02d}:00 · despegue ≈ {a["elev_real"]} m (DEM del modelo {a["elev_model"]:.0f} m) · viento: más naranja = más fuerte · temp subrayada = bajo 0 °C</p>
      </div>
      <div class="panel appr"><h4>Apreciación general</h4><ul>{synop}</ul></div>
    </div>
  </div>
</section>'''


MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
WD = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]


def week_days(skey):
    f = DATA / f"week_{skey}.json"
    if not f.exists():
        return None
    h = json.loads(f.read_text())["hourly"]
    days = {}
    for k, t in enumerate(h["time"]):
        days.setdefault(t[:10], []).append((int(t[11:13]), k))
    out = []
    for d, hs in sorted(days.items()):
        if len(hs) < 20:
            continue
        def g(key, rng=None):
            return [h[key][k] for hr, k in hs if (rng is None or rng[0] <= hr <= rng[1]) and h[key][k] is not None]
        day = g("temperature_2m"); cl = g("cloud_cover", (10, 19)); ws = g("wind_speed_10m", (10, 19))
        gs = g("wind_gusts_10m", (10, 19)); wd = g("wind_direction_10m", (10, 19)); pr = g("precipitation")
        sx = sum(math.sin(math.radians(a)) * w for a, w in zip(wd, ws)); cx = sum(math.cos(math.radians(a)) * w for a, w in zip(wd, ws))
        out.append(dict(date=datetime.date.fromisoformat(d), tmax=max(day), tmin=min(day),
                        cloud=sum(cl) / len(cl), rain=sum(pr), rain_h=sum(1 for x in pr if x >= 0.1),
                        wind=sum(ws) / len(ws), gust=max(gs), wdir=(math.degrees(math.atan2(sx, cx)) % 360)))
    return out[:7]


def _ticks(frac, n=10, cls=""):
    """n marcas; las primeras frac·n encendidas (la última parcial por opacidad)."""
    lit = max(0.0, min(1.0, frac)) * n
    out = []
    for k in range(n):
        v = max(0.0, min(1.0, lit - k))
        out.append(f'<i style="--o:{v:.2f}"></i>')
    return f'<span class="tk {cls}">{"".join(out)}</span>'


def html_week(days):
    """Franja mínima a todo el ancho: por día, máx/mín y tres filas de marcas (nubes, lluvia, viento)."""
    cells = ['<span></span>'] + [""] * 0
    head, cl, rn, wd = ['<span></span>'], ['<span class="lb">nubes</span>'], ['<span class="lb">lluvia</span>'], ['<span class="lb">viento</span>']
    for i, d in enumerate(days):
        tip = esc(f'{WD[d["date"].weekday()]} {d["date"].day:02d}/{d["date"].month:02d} · {d["tmin"]:.0f}–{d["tmax"]:.0f} °C · '
                  f'nubes {d["cloud"]:.0f} % · lluvia {d["rain"]:.1f} mm · viento {d["wind"]:.0f} km/h (racha {d["gust"]:.0f})')
        ang = (d["wdir"] + 180) % 360
        arrow = (f'<svg class="wa" viewBox="-6 -6 12 12" style="transform:rotate({ang:.0f}deg)" aria-hidden="true">'
                 f'<path d="M0,5 V-4 M-3,-1.5 L0,-5 L3,-1.5" fill="none" stroke="currentColor" stroke-width="1.3" '
                 f'stroke-linecap="round" stroke-linejoin="round"/></svg>')
        head.append(f'<div class="wh" title="{tip}"><small>{"hoy" if i==0 else WD[d["date"].weekday()]} {d["date"].day:02d}</small>'
                    f'<b>{d["tmax"]:.0f}<u>°</u></b><em>{d["tmin"]:.0f}°</em>{arrow}</div>')
        cl.append(f'<div title="{tip}">{_ticks(d["cloud"] / 100, cls="cd")}</div>')
        rn.append(f'<div title="{tip}">{_ticks(math.sqrt(d["rain"] / 12) if d["rain"] >= 0.2 else 0, cls="rn")}</div>')
        wd.append(f'<div title="{tip}">{_ticks(d["wind"] / 40, cls="wn" + (" hi" if d["wind"] >= 25 else " mid" if d["wind"] >= 15 else ""))}</div>')
    return '<div class="wg">' + "".join(head + cl + rn + wd) + '</div>'


def main():
    data = {}
    for s in SITES:
        for day in DAYS:
            for m in MODELS:
                data[(s[0], day, m[0])] = analyse(s, day, m)

    first = DATA / f"{MODELS[0][0]}_{SITES[0][0]}.json"
    emitido = datetime.datetime.fromtimestamp(first.stat().st_mtime, CL).strftime("%d-%m-%Y %H:%M")

    tabs = "".join(
        f'<button class="tab" data-k="site" data-v="{i}"{" aria-pressed=\"true\"" if i==0 else ""}>{esc(s[1])}</button>'
        for i, s in enumerate(SITES))
    daybtns = "".join(
        f'<button class="day" data-k="day" data-v="{j}"{" aria-pressed=\"true\"" if j==0 else ""}>'
        f'{("hoy · " if j==0 else "") + WD[datetime.date.fromisoformat(d).weekday()] + datetime.date.fromisoformat(d).strftime(" %d-") + MES[datetime.date.fromisoformat(d).month-1]}</button>'
        for j, d in enumerate(DAYS))
    modbtns = "".join(
        f'<button class="mod" data-k="mod" data-v="{n}"{" aria-pressed=\"true\"" if n==0 else ""} '
        f'title="{esc(md[3])}">{esc(md[2])}</button>' for n, md in enumerate(MODELS))

    carta = DATA / "carta.jpg"
    carta_uri = carta_fig = ""
    if carta.exists():
        carta_uri = "data:image/jpeg;base64," + base64.b64encode(carta.read_bytes()).decode()
        cemit = datetime.datetime.fromtimestamp(carta.stat().st_mtime, CL).strftime("%d-%m-%Y %H:%M")
        chelp = ("Análisis de presión al nivel del mar y frentes del Servicio Meteorológico de la "
                 "Armada de Chile (base GFS/NOAA): el contexto de gran escala tras la curva térmica. "
                 "Dorsal / alta (A) sobre el Pacífico = subsidencia, aire seco e inversión que aplana "
                 "el techo y deja térmica azul. Vaguada / baja (B) y sistemas frontales acercándose = "
                 f"gradiente, viento y nubosidad en aumento. Instantánea del {cemit}; la Armada la "
                 "renueva cada ~6 h. Fuente: meteoarmada.directemar.cl.")
        carta_fig = (f'<figure class="carta-fig">'
                     f'<figcaption>Carta sinóptica de superficie · Armada de Chile{ttmark(chelp)}</figcaption>'
                     f'<div class="cimg" role="img" aria-label="Carta sinóptica de superficie del '
                     f'Servicio Meteorológico de la Armada de Chile, {cemit}"></div>'
                     f'<div class="cf-src">{cemit} · <a href="{CARTA_PAGE}">meteoarmada.directemar.cl</a></div>'
                     f'</figure>')

    wk_help = ("Nubes: cobertura diurna (10–19 h), 10 marcas = 100 %. Lluvia: mm del día, lleno desde 12 mm. "
               "Viento: media 10–19 h, lleno = 40 km/h; la flecha indica hacia dónde sopla. Cifras: máxima / mínima en °C. "
               "Pronóstico GFS en superficie: la confianza baja desde el día 4–5.")
    weeks = ""
    for i, s_ in enumerate(SITES):
        wd = week_days(s_[0])
        if wd:
            weeks += (f'<section class="wk" data-site="{i}"><h4>Próximos 7 días · {esc(s_[1])}{ttmark(wk_help)}</h4>'
                      f'<div class="wk-sc">{html_week(wd)}</div></section>')

    panels = ""
    for i, s in enumerate(SITES):
        for j, day in enumerate(DAYS):
            for n, md in enumerate(MODELS):
                panels += render_site(data[(s[0], day, md[0])], i, j, n, carta_fig)

    upd_btn = '' if WEB else '<button type="button" id="btnUpdate" class="btn-upd">Actualizar pronóstico</button>'
    upd_dlg = '' if WEB else f'''<dialog id="dlgUpdate" class="upd-dlg">
  <form method="dialog">
    <h3>Actualizar pronóstico</h3>
    <p>Esta página es una <b>foto</b> de la corrida emitida el <b>{emitido}</b>. El sandbox del Artifact bloquea peticiones externas: no puede traer datos nuevos por sí sola, hay que pedírselo a Claude en esta conversación.</p>
    <p>Pegá este mensaje en el chat:</p>
    <textarea id="updMsg" readonly rows="3">Actualiza el pronóstico de vuelo a vela: corré python3 build.py --fetch en Pronostico_exp/vuelo-a-vela/ y volvé a publicar el mismo Artifact (misma URL).</textarea>
    <p id="updCopied" class="upd-copied" hidden>Copiado ✓</p>
    <div class="upd-actions">
      <button type="button" id="updCopy" class="btn-upd">Copiar mensaje</button>
      <button value="close">Cerrar</button>
    </div>
  </form>
</dialog>
'''
    web_head = ('<!doctype html><html lang="es"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<style>[hidden]{display:none!important}body{font-size:14px}</style>') if WEB else ''
    foot_lim = ('Este panel es una <b>foto</b> de una corrida; se regenera solo una vez al día (~06:30 hora de Chile).' if WEB else
                'Este panel es una <b>foto</b> de una corrida; no se actualiza solo (el sandbox del Artifact bloquea peticiones externas, por eso los datos van incrustados).')
    foot_daily = '' if WEB else ('<h4>Para una versión diaria</h4>\n  <p><code>python3 build.py --fetch</code> en <code>Pronostico_exp/vuelo-a-vela/</code> vía <code>cron</code> cada mañana y re-publicar el Artifact. Conviene además pedir a la DMC (<code>consultas@meteochile.gob.cl</code>) o al Club de Planeadores confirmación de si la suspensión de la radiosonda es temporal.</p>')
    tpl = f'''{web_head}<title>Pronóstico para Vuelo a Vela RM</title>
<meta name="description" content="Sondeo de modelo (GFS / ICON) para sitios de parapente de la Región Metropolitana, en reemplazo del boletín DMC sin radiosonda.">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;800&family=DM+Mono:wght@400;500&display=swap">
<style>
/* Cartel de bloques planos: crema, naranja quemado, salvia y mostaza con filete de tinta,
   esquinas casi rectas y punteado de imprenta. Sin tema oscuro — todos los colores explícitos. */
:root{{
  color-scheme:light;
  --bg:#e5e1d4; --card:#ece8dc; --ink:#1c1c1a; --ink-dim:#5b594f;
  --line:#1c1c1a; --line-soft:#1c1c1a2e; --accent:#1c1c1a;
  --or:#e8703a; --sage:#f2f5f6; --mus:#e8c547; --cream:#ece8dc;
  --go:#2a5b4a; --cau:#8a6a00; --no:#b3401a;
  --ct-bg:#efebe0; --ct-ink:#4b4a42;
  --sky-hi:#f2f5f6; --sky-lo:#efebe0; --grid:#1c1c1a1f; --terrain:#c2b498; --terrain-edge:#1c1c1a;
  --band:#e8703a66; --top-line:#1c1c1a; --lcl-line:#5b594f; --cloud:#3b4046; --day:#e8c54733; --precip:#2a5b63;
  --w0:#e8703a12; --w1:#e8703a2a; --w2:#e8703a47; --w3:#e8703a6b; --w4:#e8703a9c; --cold:#1f4f5a;
  --mono:'DM Mono',ui-monospace,Menlo,monospace;
  --sans:'Archivo','Helvetica Neue',Arial,sans-serif; --disp:'Archivo','Helvetica Neue',Arial,sans-serif;
}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.5;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1080px;margin:0 auto;padding:26px 20px 60px}}
header.mast{{border-bottom:2px solid var(--ink);padding-bottom:14px}}
.eyebrow{{font-family:var(--disp);text-transform:uppercase;letter-spacing:.16em;font-size:11px;color:var(--accent);font-weight:700}}
h1{{font-family:var(--disp);font-weight:700;font-size:clamp(1.5rem,4vw,2.15rem);margin:.15em 0 .1em;letter-spacing:-.01em;text-wrap:balance}}
.sub{{color:var(--ink-dim);font-size:.9rem;max-width:62ch}}
.meta{{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;font-family:var(--mono);font-size:12px;color:var(--ink-dim)}}
.meta b{{color:var(--ink);font-weight:600}}
.controls{{display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;margin:18px 0 4px;position:sticky;top:0;background:var(--bg);padding:9px 0;z-index:5;border-bottom:1px solid var(--line-soft)}}
.tabs,.days,.mods{{display:flex;flex-wrap:wrap;gap:4px}}
.grp-l{{font-family:var(--disp);font-size:9px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink-dim);align-self:center;font-weight:700}}
.mods{{margin-left:auto}}
button{{font-family:var(--disp);font-weight:600;font-size:13px;letter-spacing:.02em;padding:7px 12px;border:1px solid var(--line);background:transparent;color:var(--ink-dim);border-radius:2px;cursor:pointer}}
button.day,button.mod{{font-family:var(--mono);font-size:12px;padding:6px 10px}}
.tab[aria-pressed="true"]{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.day[aria-pressed="true"],.mod[aria-pressed="true"]{{border-color:var(--accent);color:var(--accent)}}
button:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);margin:18px 0}}
@media(max-width:900px){{.tiles{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:640px){{.tiles{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:400px){{.tiles{{grid-template-columns:1fr}}}}
.tile{{background:var(--card);padding:11px 13px;position:relative}}
.tile[data-sev]::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px}}
.tile[data-sev="go"]::before{{background:var(--go)}}
.tile[data-sev="cau"]::before{{background:var(--cau)}}
.tile[data-sev="no"]::before{{background:var(--no)}}
.tile-l{{font-family:var(--disp);text-transform:uppercase;letter-spacing:.09em;font-size:10px;color:var(--ink-dim);font-weight:600;position:relative}}
.tile-v{{font-family:var(--mono);font-size:1.16rem;font-weight:600;margin:2px 0 1px;font-variant-numeric:tabular-nums;overflow-wrap:anywhere;line-height:1.25}}
.tile-v .u{{font-size:.62em;color:var(--ink-dim);margin-left:2px}}
.tile-v i{{color:var(--ink-dim);font-style:normal;margin:0 1px}}
.tile-s{{font-size:11px;color:var(--ink-dim);line-height:1.35}}
button.tt{{all:unset;display:inline-flex;vertical-align:middle;margin-left:4px;cursor:help}}
.tt-i{{font-family:var(--mono);font-size:8.5px;font-weight:600;line-height:1;width:12px;height:12px;border:1px solid var(--ink-dim);border-radius:50%;display:flex;align-items:center;justify-content:center;color:var(--ink-dim);text-transform:none;opacity:.7}}
button.tt:hover .tt-i,button.tt:focus-visible .tt-i{{border-color:var(--accent);color:var(--accent);opacity:1}}
.tt-box{{position:absolute;left:10px;right:10px;top:calc(100% + 6px);z-index:50;background:var(--ink);color:var(--bg);font-family:var(--sans);font-weight:400;font-size:11.5px;line-height:1.5;letter-spacing:normal;text-transform:none;text-align:left;padding:9px 11px;border-radius:4px;box-shadow:0 10px 30px rgba(0,0,0,.32);opacity:0;visibility:hidden;transition:opacity .12s ease}}
button.tt:hover .tt-box,button.tt:focus .tt-box,button.tt:focus-visible .tt-box{{opacity:1;visibility:visible}}
.row3>div,.wk h4{{position:relative}}
.wk .tt-box{{left:0;right:auto;width:min(340px,80vw)}}
.row3 .tt-box{{left:auto;right:0;width:min(250px,72vw)}}
.grid2{{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:20px;align-items:start}}
@media(max-width:820px){{.grid2{{grid-template-columns:1fr}}}}
.colL{{display:flex;flex-direction:column;gap:20px;min-width:0}}
.chart{{margin:0;border:1px solid var(--line);background:var(--card);padding:12px}}
.chart figcaption{{font-size:11.5px;color:var(--ink-dim);margin-bottom:8px}}
.chart svg{{display:block;border:1px solid var(--line-soft);border-radius:2px;overflow:hidden}}
.carta-fig{{margin:0;border:1px solid var(--line);background:var(--card);padding:12px}}
.carta-fig figcaption{{position:relative;font-family:var(--disp);font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-dim);font-weight:600;margin-bottom:8px;display:flex;align-items:center}}
.cimg{{width:100%;aspect-ratio:5/4;background:#fff center/contain no-repeat;border:1px solid var(--line-soft)}}
.cf-src{{font-size:10.5px;color:var(--ink-dim);margin-top:6px;font-family:var(--mono)}}
.cf-src a{{color:var(--accent)}}
.ct{{fill:var(--ct-ink);font-family:var(--mono);font-size:9px}}
.cl{{fill:var(--ct-ink);font-family:var(--disp);font-size:9px;text-transform:uppercase;letter-spacing:.08em}}
.legend{{display:flex;flex-wrap:wrap;gap:12px;margin-top:9px;font-size:11px;color:var(--ink-dim)}}
.legend i{{display:inline-block;width:16px;height:10px;vertical-align:-1px;margin-right:5px}}
.sw-band{{background:var(--band)}} .sw-top{{background:var(--top-line)}}
.sw-lcl{{border-top:2px dashed var(--lcl-line)}}
.sw-ramp{{background:linear-gradient(90deg,transparent,var(--cloud))}}
.sw-precip{{background:var(--precip)!important;width:5px!important}}
.sw-day{{background:var(--day)}}
.panels{{display:flex;flex-direction:column;gap:14px}}
.panel{{border:1px solid var(--line);background:var(--card);padding:13px 15px}}
.panel h4{{font-family:var(--disp);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin:0 0 8px;color:var(--ink-dim);font-weight:600}}
table.wt{{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:13px;font-variant-numeric:tabular-nums}}
table.wt th{{font-family:var(--disp);font-size:9.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--ink-dim);font-weight:600;text-align:right;padding:0 6px 6px;border-bottom:1px solid var(--line)}}
table.wt th span{{font-weight:400;opacity:.7}}
table.wt th:first-child{{text-align:left}}
table.wt td{{text-align:right;padding:3.5px 6px;border-bottom:1px solid var(--line-soft)}}
table.wt td.alt{{text-align:left;color:var(--accent);font-weight:600;white-space:nowrap}}
table.wt td.alt i{{font-style:normal;color:var(--ink-dim);font-weight:400;font-size:.82em}}
table.wt td.dir{{text-align:right;white-space:nowrap}}
table.wt td.w0{{background:var(--w0)}} table.wt td.w1{{background:var(--w1)}} table.wt td.w2{{background:var(--w2)}}
table.wt td.w3{{background:var(--w3)}} table.wt td.w4{{background:var(--w4);font-weight:600}}
table.wt td.neg{{color:var(--cold);font-weight:600}}
.warr{{width:11px;height:11px;display:inline-block;vertical-align:-1px;margin-right:4px;fill:none;stroke:var(--ink-dim);stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}}
table.wt tr:last-child td{{border-bottom:none}}
.fine{{font-size:11px;color:var(--ink-dim);margin:8px 0 0;font-family:var(--mono)}}
.row3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}}
@media(max-width:520px){{.row3{{grid-template-columns:1fr}}}}
.row3 .k{{display:block;font-family:var(--disp);font-size:9.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim);font-weight:600}}
.bignum{{display:block;font-family:var(--mono);font-size:1.5rem;font-weight:600;margin:2px 0}}
.bignum i{{color:var(--ink-dim);font-style:normal;margin:0 2px}}
.sup{{font-size:.7em;opacity:.7}}
.pill{{display:inline-block;font-family:var(--mono);font-size:11px;font-weight:600;padding:2px 7px;border:1px solid var(--line);border-radius:2px;margin:3px 4px 0 0}}
.pill[data-sev="go"]{{color:var(--go);border-color:var(--go)}}
.pill[data-sev="cau"]{{color:var(--cau);border-color:var(--cau)}}
.pill[data-sev="no"]{{color:var(--no);border-color:var(--no)}}
.wk{{border-top:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--card);padding:10px 14px 12px;margin:12px 0 0}}
.wk h4{{font-family:var(--disp);font-size:10px;text-transform:uppercase;letter-spacing:.12em;margin:0 0 8px;color:var(--ink-dim);font-weight:600}}
.wg{{display:grid;grid-template-columns:44px repeat(7,minmax(0,1fr));column-gap:14px;row-gap:9px;align-items:center;font-family:var(--mono)}}
.wg .lb{{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink-dim)}}
.wh{{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 6px;border-left:1px solid var(--ink);padding-left:7px;margin-bottom:2px}}
.wh small{{flex:1 0 100%;font-size:10px;color:var(--ink-dim);text-transform:uppercase;letter-spacing:.06em}}
.wh b{{font-size:1.5rem;font-weight:500;line-height:1.1;color:var(--ink);font-variant-numeric:tabular-nums}}
.wh b u{{text-decoration:none;font-size:.6em;color:var(--ink-dim)}}
.wh em{{font-style:normal;font-size:11px;color:var(--ink-dim)}}
.tk{{display:flex;gap:2px;flex:1}}
.tk i{{flex:1;height:14px;background:var(--line-soft);position:relative}}
.tk i::after{{content:"";position:absolute;inset:0;background:var(--ink);opacity:var(--o)}}
.tk.rn i::after{{background:var(--precip)}}
.wa{{width:12px;height:12px;flex:none;margin-left:auto;align-self:center;color:var(--ink-dim)}}
@media(max-width:560px){{.wg{{grid-template-columns:34px repeat(7,minmax(0,1fr));column-gap:6px}}.tk{{gap:1px}}.wh b{{font-size:1rem}}.wh em{{display:none}}.wa{{width:9px;height:9px}}.wh{{padding-left:4px}}}}
.appr ul{{margin:0;padding-left:18px;font-size:13px}}
.appr li{{margin:4px 0}}
.btn-upd{{font-family:var(--mono);font-size:11px;font-weight:600;padding:3px 9px;border:1px solid var(--accent);color:var(--accent);background:transparent;border-radius:2px;cursor:pointer;letter-spacing:.02em}}
.btn-upd:hover{{background:var(--accent);color:var(--card)}}
dialog.upd-dlg{{border:1px solid var(--line);border-radius:4px;padding:0;max-width:440px;width:92vw;color:var(--ink);background:var(--card);box-shadow:0 20px 50px rgba(0,0,0,.28)}}
dialog.upd-dlg::backdrop{{background:rgba(20,26,20,.45)}}
dialog.upd-dlg form{{padding:18px 20px 16px}}
dialog.upd-dlg h3{{font-family:var(--disp);font-size:15px;margin:0 0 8px;letter-spacing:-.01em}}
dialog.upd-dlg p{{font-size:12.5px;color:var(--ink-dim);margin:0 0 10px;line-height:1.5}}
dialog.upd-dlg textarea{{width:100%;font-family:var(--mono);font-size:11.5px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:2px;padding:8px;resize:vertical;line-height:1.4}}
.upd-actions{{display:flex;gap:8px;margin-top:12px;justify-content:flex-end}}
.upd-actions button{{font-size:12px;padding:6px 12px}}
.upd-copied{{color:var(--go)!important;font-weight:600;text-align:right;margin:8px 0 0!important}}
{f'.cimg{{background-image:url("{carta_uri}")}}' if carta_uri else ''}
footer{{margin-top:36px;border-top:1px solid var(--line);padding-top:16px;font-size:12px;color:var(--ink-dim)}}
footer h4{{font-family:var(--disp);font-size:11px;text-transform:uppercase;letter-spacing:.09em;margin:14px 0 5px;color:var(--ink)}}
footer code{{font-family:var(--mono);font-size:11px;background:var(--card);padding:1px 4px;border:1px solid var(--line-soft)}}
footer a{{color:var(--accent)}}
/* --- piel cartel --- */
body{{font-weight:400}}
header.mast{{border-bottom:2px solid var(--ink);padding-bottom:16px}}
.eyebrow{{display:inline-block;background:var(--or);color:var(--ink);padding:3px 9px;font-weight:600;letter-spacing:.12em;border:1.5px solid var(--ink)}}
h1{{font-weight:800;text-transform:uppercase;font-size:clamp(1.8rem,5.2vw,3.2rem);letter-spacing:-.025em;line-height:.96;margin:.35em 0 .3em;max-width:30ch}}
.sub{{font-size:.95rem;color:var(--ink);max-width:none}}
.topinfo{{display:flex;flex-wrap:wrap;align-items:center;gap:6px 22px;font-family:var(--mono);font-size:12px;color:var(--ink-dim);padding-bottom:12px;margin-bottom:10px;border-bottom:1px solid var(--line-soft)}}
.topinfo b{{font-weight:500;color:var(--ink)}}
.topinfo .btn-upd{{margin-left:auto}}
.meta{{background:var(--mus);border:1.5px solid var(--ink);border-radius:2px;padding:9px 16px;margin-top:16px;gap:6px 22px;align-items:center;color:var(--ink)}}
.meta b{{font-weight:500}}
.controls{{border-bottom:none;padding:12px 0 8px}}
.grp-l{{font-weight:600;color:var(--ink)}}
button{{border-radius:2px;font-weight:600;padding:7px 14px;border:1.5px solid var(--ink);color:var(--ink)}}
button.day,button.mod{{padding:6px 11px}}
button:hover{{background:var(--mus)}}
.day[aria-pressed="true"],.mod[aria-pressed="true"],.tab[aria-pressed="true"]{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.btn-upd{{font-weight:500;padding:3px 11px;background:var(--cream);color:var(--ink);border-color:var(--ink)}}
.btn-upd:hover{{background:var(--ink);color:var(--bg)}}
.tiles{{gap:2px;background:var(--ink);border:2px solid var(--ink);border-radius:2px}}
.tile{{padding:14px 16px;background:var(--cream)}}
.tile-l{{font-weight:600;letter-spacing:.09em;color:var(--ink)}}
.tile-v{{font-weight:500;font-size:1.35rem}}
.tile-v .u,.tile-v i,.tile-s{{color:var(--ink)}} .tile-s{{opacity:.75}}
.tile[data-sev]::before{{left:0;top:14px;bottom:14px;width:3px;background:var(--ink)}}
.tile[data-sev="cau"]::before{{background:repeating-linear-gradient(var(--ink) 0 3px,transparent 3px 6px)}}
.tile[data-sev="no"]::before{{width:7px}}
.tile[data-sev="no"] .tile-v{{font-weight:800}}
.tt-box{{border-radius:2px}}
.chart,.carta-fig,.panel,.wk{{border:2px solid var(--ink);border-radius:2px;background:var(--cream)}}
.chart,.carta-fig{{padding:16px}}
.panel{{padding:16px 20px}}
.panel h4,.wk h4,.chart figcaption,.carta-fig figcaption{{font-weight:800;text-transform:uppercase;letter-spacing:.07em;color:var(--ink)}}
.chart figcaption{{font-size:11.5px;font-weight:600;text-transform:none;letter-spacing:0}}
.panels>.panel:nth-child(1){{background:var(--sage)}}
.panels>.panel.appr{{background:var(--ink);color:#fff}}
.panel.appr h4{{color:#fff}}
.carta-fig{{background:var(--sage)}}
.wk{{padding:18px 20px 20px;background:var(--sage)}}
.chart svg{{border:1.5px solid var(--ink);border-radius:0}}
.cimg{{background-color:#efebe0;border:1.5px solid var(--ink);border-radius:0;filter:grayscale(1) contrast(1.05)}}
.cf-src,.fine,.row3 .k{{color:var(--ink)}}
.pill{{border-radius:2px;padding:2px 9px;font-weight:600;color:var(--ink);border:1.5px solid var(--ink);background:var(--cream)}}
.pill[data-sev]{{color:var(--ink)}}
.pill[data-sev="go"]{{background:var(--sage)}}
.pill[data-sev="cau"]{{background:var(--mus)}}
.pill[data-sev="no"]{{background:var(--or)}}
table.wt th{{color:var(--ink);border-bottom:2px solid var(--ink)}}
table.wt td{{border-bottom:1px solid var(--line-soft)}}
table.wt td.alt{{color:var(--ink)}}
table.wt td.neg{{text-decoration:underline;text-underline-offset:3px}}
.wh{{border-left:2px solid var(--ink)}}
.wh small{{color:var(--ink);font-weight:600}}
.wh b{{font-family:var(--mono)}}
.wg .lb{{color:var(--ink);font-weight:600}}
.tk i{{background:#1c1c1a1f}}
.tk.rn i{{height:8px}}
.tk.cd i::after{{background:#2f6fb0}}
.tk.rn i::after{{background:#2f8a5a}}
.tk.wn i::after{{background:#e0a800}}
dialog.upd-dlg{{border:2px solid var(--ink);border-radius:2px;box-shadow:none;background:var(--mus)}}
dialog.upd-dlg p{{color:var(--ink)}}
dialog.upd-dlg textarea{{border-radius:2px;background:var(--cream);border-color:var(--ink)}}
.upd-copied{{color:var(--ink)!important}}
footer{{border-top:2px solid var(--ink)}}
footer a,.cf-src a{{color:var(--ink);text-decoration:underline;text-underline-offset:2px}}
footer code{{border-radius:2px;background:var(--cream);border-color:var(--ink)}}
.eyebrow,.sub{{position:relative}}
@media (prefers-reduced-motion:reduce){{*{{transition:none!important}}}}
</style>

<div class="wrap">
<header class="mast">
  <div class="topinfo">
    <span>Emitido <b>{emitido}</b></span>
    <span>Fuente <b>Open-Meteo · GFS (NCEP) / ICON (DWD)</b></span>
    {upd_btn}
  </div>
  <h1>Pronóstico para Vuelo a Vela — Región Metropolitana</h1>
  <p class="sub">Sondeo derivado de modelo numérico para cuatro sitios de parapente, en el formato del boletín que la Dirección Meteorológica de Chile emitía con la radiosonda de Santo Domingo. Modelo <b>GFS</b> o <b>ICON</b> a elección.</p>
</header>

{weeks}

{upd_dlg}

<div class="controls">
  <span class="grp-l">Sitio</span><div class="tabs">{tabs}</div>
  <span class="grp-l">Día</span><div class="days">{daybtns}</div>
  <span class="grp-l">Modelo</span><div class="mods">{modbtns}</div>
</div>

{panels}

<footer>
  <h4>Modelos</h4>
  <p><b>GFS</b> (NCEP, ~13 km) trae capa límite convectiva e índice de levantamiento (LI) nativos. <b>ICON</b> (DWD, ~13 km global) no publica esos campos en Open-Meteo: el techo se calcula aquí por el <b>método del índice térmico</b> (adiabática seca desde la superficie hasta cortar el perfil del entorno) y el LI se marca <b>n/d</b> — el riesgo de sobredesarrollo con ICON se evalúa sólo con CAPE y nubosidad media. Muchos pilotos encuentran ICON mejor en la cordillera de Santiago porque resuelve mejor la inversión de subsidencia; conviene contrastar los dos. Añadir un tercer modelo (p. ej. ECMWF IFS, <code>ecmwf_ifs025</code>) es una línea en <code>MODELS</code>.</p>
  <h4>Método</h4>
  <p>Perfil vertical horario del modelo (temperatura, humedad, viento y altura geopotencial en 925→300 hPa) más radiación y CAPE, vía Open-Meteo. <b>Techo</b> = altura de la capa límite; <b>base de nube</b> = nivel de condensación por convección (Espy); <b>velocidad vertical</b> = w* estimado del flujo de calor sensible y la profundidad de la capa límite; <b>ascenso neto útil</b> ≈ 0,8·w* − 1 m/s; <b>penetración</b> según el viento medio entre 1500 y 3500 m; <b>viento en superficie</b> = viento y rachas a 10 m del modelo (<code>wind_gusts_10m</code>) en la franja 10–19 h, con el factor de racha (racha ÷ media). Son estimaciones, no observaciones.</p>
  <p>La pestaña <b>hoy</b> es la salida del modelo para la corrida más reciente (no un análisis con datos observados): sirve para contrastar el pronóstico con lo que efectivamente viste en el aire y calibrar cuánto fiarte de cada modelo en cada sitio.</p>
  <h4>Limitaciones</h4>
  <p>~13 km + interpolación suaviza el relieve andino: la elevación del modelo no coincide con el despegue real y las brisas de valle, convergencias y efecto foehn locales no se resuelven. {foot_lim}</p>
  {foot_daily}
  <h4>Fuentes</h4>
  <p>Pronóstico: <a href="https://open-meteo.com/">Open-Meteo</a> (GFS/NCEP, ICON/DWD). Carta sinóptica de superficie: <a href="{CARTA_PAGE}">Servicio Meteorológico de la Armada de Chile</a> (directemar). Archivo histórico del sondeo 85586: <a href="https://weather.uwyo.edu/">U. de Wyoming</a>, <a href="https://www.ncei.noaa.gov/products/weather-balloon/integrated-global-radiosonde-archive">NOAA IGRA v2</a>. Formato de referencia: boletín "Pronóstico para Vuelo a Vela" de la <a href="https://www.meteochile.gob.cl/">DMC</a>.</p>
</footer>
</div>

<script>
(function(){{
  var wrap=document.querySelector('.wrap'), sel={{site:'0',day:'0',mod:'0'}};
  function apply(){{
    wrap.querySelectorAll('.wk').forEach(function(el){{ el.hidden = el.dataset.site!==sel.site; }});
    wrap.querySelectorAll('.site').forEach(function(el){{
      el.hidden = el.id!=='site-'+sel.site+'-'+sel.day+'-'+sel.mod;
    }});
  }}
  wrap.querySelectorAll('button[data-k]').forEach(function(b){{
    b.addEventListener('click',function(){{
      var k=b.dataset.k;
      wrap.querySelectorAll('button[data-k="'+k+'"]').forEach(function(x){{x.removeAttribute('aria-pressed')}});
      b.setAttribute('aria-pressed','true'); sel[k]=b.dataset.v; apply();
    }});
  }});
  apply();

  var dlg=document.getElementById('dlgUpdate'), btnU=document.getElementById('btnUpdate');
  if(btnU && dlg && typeof dlg.showModal==='function'){{
    btnU.addEventListener('click',function(){{ dlg.showModal(); }});
    var updCopy=document.getElementById('updCopy'), updMsg=document.getElementById('updMsg'), updCopied=document.getElementById('updCopied');
    updCopy.addEventListener('click',function(){{
      updMsg.focus(); updMsg.select();
      function ok(){{ updCopied.hidden=false; setTimeout(function(){{ updCopied.hidden=true; }},2000); }}
      if(navigator.clipboard && navigator.clipboard.writeText){{
        navigator.clipboard.writeText(updMsg.value).then(ok).catch(function(){{ try{{ document.execCommand('copy'); ok(); }}catch(e){{}} }});
      }} else {{
        try{{ document.execCommand('copy'); ok(); }}catch(e){{}}
      }}
    }});
  }} else if(btnU){{
    btnU.hidden = true;
  }}
}})();
</script>'''
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(tpl, encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size, "bytes")
    for (sk, day, mk), a in data.items():
        print(f"{sk:10} {day} {mk:4} {a['verdict'][0]:12} band {round(a['band']):4}  "
              f"w* {a['wbar']:.1f}  wind {round(a['wmean']):2}  cu {a['cumulus']}  win {a['win']}  LI {a['li']}")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch()
    main()
