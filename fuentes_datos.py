"""Conexión automática a las fuentes de datos: NOAA, INOCAR (ERFEN) y CIIFEN.

Todas las funciones ``obtener_*`` hacen peticiones web y lanzan una excepción si fallan;
``con_respaldo`` conserva el último dato bueno para no dejar la app sin información cuando
una fuente se cae. Las funciones ``parsear_*`` son puras (texto -> datos) para poder probarlas
sin red.

Fuentes (verificadas desde el servidor):
- NOAA CPC: ONI mensual y temperaturas del mar Niño semanales (archivos de texto).
- NOAA GFS vía Open-Meteo: lluvia diaria por cantón (16 días).
- CCSR/IRI (modelo CFSv2 de NOAA/NCEP): lluvia mensual por cantón (OPeNDAP binario).
- INOCAR: Informe técnico ejecutivo ERFEN vigente (PDF con dirección fija).
- CIIFEN: boletín mensual «El Niño/La Niña en América Latina» (PDF).
"""

import datetime
import io
import re
import struct
from concurrent.futures import ThreadPoolExecutor

import requests

UA = {"User-Agent": "Mozilla/5.0 (monitoreo-enso-ecuador; GeoCiencias)"}
TIMEOUT = 40

URL_ONI = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
URL_NINO_SEMANAL = "https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for"
URL_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
URL_CFSV2 = "https://forecast.ccsr.columbia.edu/data/NMME/NOAA-NCEP/CFSv2/early_month_samples/forecast/"
URL_ERFEN = "https://www.inocar.mil.ec/boletin/ERFEN/actual/boletin_ERFEN.pdf"
URL_CIIFEN_LISTA = "https://ciifen.org/el-nino-la-nina-ciifen/"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

_ULTIMO_BUENO = {}


# ----------------------------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------------------------
def _get(url, **kw):
    r = requests.get(url, headers=UA, timeout=kw.pop("timeout", TIMEOUT), **kw)
    r.raise_for_status()
    return r


def con_respaldo(nombre, funcion):
    """Ejecuta la función; si falla devuelve el último dato bueno (o None) marcándolo como desactualizado."""
    try:
        dato = funcion()
        dato["_estado"] = "ok"
        _ULTIMO_BUENO[nombre] = dato
        return dato
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de red o de formato
        previo = _ULTIMO_BUENO.get(nombre)
        if previo is not None:
            previo = dict(previo)
            previo["_estado"] = "respaldo"
            previo["_error"] = str(exc)[:120]
            return previo
        return {"_estado": "error", "_error": str(exc)[:120]}


def _normalizar(texto):
    return re.sub(r"\s+", " ", texto.replace("­", "")).strip()


def _texto_pdf(contenido, paginas=None):
    from pypdf import PdfReader

    lector = PdfReader(io.BytesIO(contenido))
    hojas = lector.pages if paginas is None else lector.pages[:paginas]
    return _normalizar(" ".join((h.extract_text() or "") for h in hojas))


# ----------------------------------------------------------------------------------------------
# NOAA CPC: ONI y Niño semanal
# ----------------------------------------------------------------------------------------------
def parsear_oni(texto):
    """Última fila del ONI: ``  JAS 2026  29.12   2.16`` -> trimestre y anomalía (°C)."""
    ultima = None
    for linea in texto.splitlines():
        m = re.match(r"^\s*([A-Z]{3})\s+(\d{4})\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", linea)
        if m:
            ultima = m
    if not ultima:
        raise ValueError("ONI: sin filas")
    return {"trimestre": f"{ultima.group(1)} {ultima.group(2)}", "anomalia": float(ultima.group(4)),
            "url": URL_ONI}


def parsear_nino_semanal(texto):
    """Última semana: SST y anomalía de Niño 1+2, 3, 3.4 y 4."""
    patron = re.compile(r"^\s*(\d{2}[A-Z]{3}\d{4})" + r"\s+(-?\d+\.\d+)" * 8 + r"\s*$")
    ultima = None
    for linea in texto.splitlines():
        m = patron.match(linea)
        if m:
            ultima = m
    if not ultima:
        raise ValueError("Niño semanal: sin filas")
    v = [float(x) for x in ultima.groups()[1:]]
    fecha = datetime.datetime.strptime(ultima.group(1).title(), "%d%b%Y").date()
    return {"semana": fecha, "nino12": v[1], "nino3": v[3], "nino34": v[5], "nino4": v[7], "url": URL_NINO_SEMANAL}


def obtener_noaa_enso():
    oni = parsear_oni(_get(URL_ONI).text)
    semanal = parsear_nino_semanal(_get(URL_NINO_SEMANAL).text)
    return {"oni": oni, "semanal": semanal}


# ----------------------------------------------------------------------------------------------
# NOAA GFS (vía Open-Meteo): lluvia diaria por cantón
# ----------------------------------------------------------------------------------------------
def obtener_gfs(cantones, dias=16):
    """Lluvia diaria (mm) de los próximos ``dias`` días para cada cantón (diccionario por nombre)."""
    params = {
        "latitude": ",".join(str(c["lat"]) for c in cantones),
        "longitude": ",".join(str(c["lon"]) for c in cantones),
        "daily": "precipitation_sum", "models": "gfs_global",
        "forecast_days": dias, "timezone": "America/Guayaquil",
    }
    j = _get(URL_OPEN_METEO, params=params).json()
    j = j if isinstance(j, list) else [j]
    if len(j) != len(cantones):
        raise ValueError("GFS: respuesta incompleta")
    salida = {}
    for c, o in zip(cantones, j):
        fechas = [datetime.date.fromisoformat(t) for t in o["daily"]["time"]]
        mm = [0.0 if v is None else float(v) for v in o["daily"]["precipitation_sum"]]
        salida[c["canton"]] = list(zip(fechas, mm))
    return {"cantones": salida, "url": "https://open-meteo.com/en/docs/gfs-api"}


# ----------------------------------------------------------------------------------------------
# CCSR/IRI (CFSv2): lluvia mensual por cantón, lectura OPeNDAP binaria (.dods)
# ----------------------------------------------------------------------------------------------
def _dods(url):
    """Devuelve (DataView-like bytes de datos). Formato: texto DDS + '\\nData:\\n' + XDR big-endian."""
    b = _get(url, timeout=90).content
    i = b.find(b"\nData:\n")
    if i < 0:
        raise ValueError("Respuesta OPeNDAP inválida")
    return b[i + 7:]


def _floats(datos):
    n = struct.unpack(">I", datos[:4])[0]
    return struct.unpack(">%df" % n, datos[8:8 + 4 * n])


def _ints(datos):
    n = struct.unpack(">I", datos[:4])[0]
    return struct.unpack(">%di" % n, datos[8:8 + 4 * n])


def obtener_cfsv2(cantones):
    """Lluvia mensual (mm/mes) de los próximos 10 meses para cada cantón (media de 32 miembros)."""
    NM, NL, NY, NX = 32, 10, 7, 6          # miembros, meses, lat -5..1, lon -82..-77 (rejilla de 1°)
    dds = _get(URL_CFSV2 + "pr.dds").text
    pos = dds.index("S = ")
    n_s = int(re.match(r"\d+", dds[pos + 4:]).group(0))
    s = n_s - 1
    rng = f"[{s}][0:{NM - 1}][0:{NL - 1}][85:91][278:283]"
    pr = _floats(_dods(f"{URL_CFSV2}pr.dods?pr{rng}"))
    dias = _ints(_dods(f"{URL_CFSV2}pr.dods?target[{s}][0:{NL - 1}]"))
    lats = _ints(_dods(f"{URL_CFSV2}pr.dods?Y[85:91]"))
    lons = _ints(_dods(f"{URL_CFSV2}pr.dods?X[278:283]"))
    emision = _ints(_dods(f"{URL_CFSV2}pr.dods?S[{s}]"))[0]
    if lats[0] != -5 or lats[-1] != 1 or lons[0] != 278:
        raise ValueError("La rejilla del servicio CFSv2 cambió")
    base = datetime.date(1960, 1, 1)
    meses = [base + datetime.timedelta(days=d) for d in dias]
    celdas = NY * NX
    por_miembro = NL * celdas
    media = [[0.0] * celdas for _ in range(NL)]
    for m in range(NM):
        for l in range(NL):
            fila = media[l]
            off = m * por_miembro + l * celdas
            for j in range(celdas):
                fila[j] += pr[off + j] / NM
    salida = {}
    for c in cantones:
        iy = min(max(round(c["lat"]) + 5, 0), NY - 1)
        ix = min(max(round(c["lon"]) + 82, 0), NX - 1)
        serie = []
        for l in range(NL):
            ini = meses[l]
            sig = (ini.replace(day=28) + datetime.timedelta(days=4)).replace(day=1)
            dias_mes = (sig - ini).days
            serie.append((ini, max(media[l][iy * NX + ix], 0.0) * dias_mes))   # mm/día -> mm/mes
        salida[c["canton"]] = serie
    return {"cantones": salida, "emision": base + datetime.timedelta(days=emision), "url": URL_CFSV2}


# ----------------------------------------------------------------------------------------------
# INOCAR: informe técnico ejecutivo ERFEN (PDF)
# ----------------------------------------------------------------------------------------------
def _num(txt):
    return float(txt.replace(",", "."))


def parsear_erfen(texto):
    """Extrae del texto del informe ERFEN las cifras que usa el modelo. Lo que no se encuentre queda en None."""
    t = _normalizar(texto)
    out = {"informe": None, "fecha_reunion": None, "nivel_mar_cm": None, "nivel_mar_local": {},
           "nino12": None, "desbordamientos": None, "resumen": None}
    m = re.search(r"ERFEN\s+Nro\.?\s*([\d\-]+)", t)
    if m:
        out["informe"] = m.group(1)
    m = re.search(r"El\s+(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})", t, re.I)
    if m:
        out["fecha_reunion"] = m.group(1)
    m = re.search(r"nivel del mar[^.]{0,80}?anomal[ií]as\s+superiores\s+a\s+(\d+)\s*cm", t, re.I)
    if m:
        out["nivel_mar_cm"] = float(m.group(1))
    for valor, sector in re.findall(r"(?:valores\s+)?mayores\s+de\s+(\d+)\s*cm\s+en\s+el\s+sector\s+de\s+([A-ZÁÉÍÓÚa-záéíóúñ]+)", t, re.I):
        out["nivel_mar_local"][sector.lower()] = float(valor)
    m = re.search(r"\+?\s*(\d+[,.]\d+)\s*°C\s+en\s+la\s+regi[oó]n\s+Niño\s*1\s*\+\s*2", t, re.I)
    if m:
        out["nino12"] = _num(m.group(1))
    m = re.search(r"desbordamientos[^.]{0,120}?de\s+(\d+)\s+en\s+([a-záéíóú]+)\s+a\s+(\d+)\s+en\s+([a-záéíóú]+)", t, re.I)
    if m:
        out["desbordamientos"] = {"antes": int(m.group(1)), "mes_antes": m.group(2),
                                  "ahora": int(m.group(3)), "mes_ahora": m.group(4)}
    m = re.search(r"CONDICIONES OCEANOGR[ÁA]FICAS Y BIOL[ÓO]GICO-PESQUERAS\s+(.+?\.)\s+[A-ZÁÉÍÓÚ]", t)
    if m:
        out["resumen"] = m.group(1)[:260]
    if out["nivel_mar_cm"] is None and not out["nivel_mar_local"]:
        raise ValueError("ERFEN: no se encontró la anomalía del nivel del mar")
    return out


def obtener_erfen():
    contenido = _get(URL_ERFEN, timeout=60).content
    datos = parsear_erfen(_texto_pdf(contenido))
    datos["url"] = URL_ERFEN
    return datos


# ----------------------------------------------------------------------------------------------
# CIIFEN: boletín mensual El Niño / La Niña (PDF)
# ----------------------------------------------------------------------------------------------
def ultimo_boletin_ciifen(html):
    """Del listado de CIIFEN, el PDF más reciente: ``(año, mes, url)``."""
    enlaces = re.findall(r"https://ciifen\.org/wp-content/uploads/(\d{4})/(\d{2})/(Boletin_ElNino_LaNina_[^\"'<> ]+?\.pdf)", html)
    if not enlaces:
        raise ValueError("CIIFEN: sin boletines")
    anio, mes, nombre = max(enlaces, key=lambda e: (int(e[0]), int(e[1])))
    return int(anio), int(mes), f"https://ciifen.org/wp-content/uploads/{anio}/{mes}/{nombre}"


def parsear_ciifen(texto):
    """Estado del evento (titular del boletín) y perspectiva del trimestre próximo."""
    t = _normalizar(texto)
    out = {"estado": None, "perspectiva": None, "periodo": None}
    meses = "|".join(m.capitalize() for m in MESES)
    # El titular viene como «Septiembre de 2026: El Niño continúa fortaleciéndose» y el texto extraído
    # a veces lo pega con los rótulos de la diapositiva siguiente: se corta ahí.
    m = re.search(rf"({meses})\s+de\s+(\d{{4}}):\s*(.+?)(?=\s+Condiciones\s|\s+El Niño/La Niña en|\s*[•·]|$)", t)
    if m:
        out["periodo"] = f"{m.group(1)} {m.group(2)}"
        out["estado"] = m.group(3).strip()[:140]
    m = re.search(r"(El pronóstico para el trimestre[^•·]{10,260}?\.)(\s+Se espera que[^•·]{5,160}?\.)?", t)
    if m:
        out["perspectiva"] = (m.group(1) + (m.group(2) or "")).strip()[:300]
    if not out["estado"]:
        raise ValueError("CIIFEN: no se encontró el estado del evento")
    return out


def obtener_ciifen():
    anio, mes, url = ultimo_boletin_ciifen(_get(URL_CIIFEN_LISTA).text)
    texto = _texto_pdf(_get(url, timeout=90).content, paginas=3)
    datos = parsear_ciifen(texto)
    datos.update({"boletin": f"{MESES[mes - 1].capitalize()} {anio}", "url": url})
    return datos


# ----------------------------------------------------------------------------------------------
# Carga conjunta (en paralelo)
# ----------------------------------------------------------------------------------------------
def cargar_todo(cantones):
    """Descarga todas las fuentes en paralelo. Cada una devuelve su dato, el último bueno o un error."""
    tareas = {
        "noaa": lambda: obtener_noaa_enso(),
        "gfs": lambda: obtener_gfs(cantones),
        "cfsv2": lambda: obtener_cfsv2(cantones),
        "erfen": lambda: obtener_erfen(),
        "ciifen": lambda: obtener_ciifen(),
    }
    with ThreadPoolExecutor(max_workers=5) as pool:
        futuros = {n: pool.submit(con_respaldo, n, f) for n, f in tareas.items()}
        resultados = {n: f.result() for n, f in futuros.items()}
    resultados["_cargado"] = datetime.datetime.now(datetime.timezone.utc)
    return resultados
