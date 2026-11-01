"""Conexión automática a las fuentes de datos: NOAA, INOCAR (ERFEN) y CIIFEN.

Todas las funciones ``obtener_*`` hacen peticiones web y lanzan una excepción si fallan;
``con_respaldo`` conserva el último dato bueno (en memoria y en SQLite, ver ``almacen.py``) para no dejar
la app sin información cuando una fuente se cae, y ``cargar_todo`` reutiliza lo guardado si es reciente. Las funciones ``parsear_*`` son puras (texto -> datos) para poder probarlas
sin red.

Fuentes (verificadas desde el servidor):
- NOAA CPC: ONI mensual y temperaturas del mar Niño semanales (archivos de texto).
- NOAA GFS vía Open-Meteo: lluvia diaria por cantón (16 días).
- CCSR/IRI (modelo CFSv2 de NOAA/NCEP): lluvia mensual por cantón (OPeNDAP binario).
- INOCAR: Informe técnico ejecutivo ERFEN vigente (PDF con dirección fija).
- CIIFEN: boletín mensual «El Niño/La Niña en América Latina» (PDF).
"""

import datetime
import hashlib
import io
import re
import struct
from concurrent.futures import ThreadPoolExecutor

import requests

import almacen

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


def con_respaldo(nombre, funcion, clave=None):
    """Ejecuta la función y guarda el resultado (memoria y SQLite). Si falla, devuelve el último dato bueno
    —de memoria o, si se perdió, de SQLite— marcado como «respaldo»; si no hay ninguno, un error."""
    try:
        dato = funcion()
        momento = datetime.datetime.now(datetime.timezone.utc)
        _ULTIMO_BUENO[nombre] = dict(dato)
        try:
            almacen.guardar_fuente(nombre, dato, clave, momento)
        except Exception:  # noqa: BLE001 - el almacén es una ayuda: nunca debe romper la descarga
            pass
        dato["_estado"] = "ok"
        dato["_descargado"] = momento
        return dato
    except Exception as exc:  # noqa: BLE001 - cualquier fallo de red o de formato
        previo = _ULTIMO_BUENO.get(nombre)
        if previo is None:
            try:
                previo, _ = almacen.leer_fuente(nombre, clave)
            except Exception:  # noqa: BLE001
                previo = None
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
    """Última semana: SST y anomalía de Niño 1+2, 3, 3.4 y 4.

    El archivo es de ancho fijo y los valores negativos van pegados al anterior (``20.6-0.1``),
    por eso se extraen con una expresión que no exige espacios entre números.
    """
    fila = re.compile(r"^\s*(\d{2}[A-Z]{3}\d{4})\s+((?:-?\d+\.\d\s*){8})\s*$")
    ultima = None
    for linea in texto.splitlines():
        m = fila.match(linea)
        if m:
            ultima = m
    if not ultima:
        raise ValueError("Niño semanal: sin filas")
    v = [float(x) for x in re.findall(r"-?\d+\.\d", ultima.group(2))]
    fecha = datetime.datetime.strptime(ultima.group(1).title(), "%d%b%Y").date()
    return {"semana": fecha, "nino12": v[1], "nino3": v[3], "nino34": v[5], "nino4": v[7], "url": URL_NINO_SEMANAL}


def parsear_oni_serie(texto):
    """Todas las filas del ONI: ``(año, trimestre, anomalía)``."""
    filas = []
    for linea in texto.splitlines():
        m = re.match(r"^\s*([A-Z]{3})\s+(\d{4})\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)\s*$", linea)
        if m:
            filas.append((int(m.group(2)), m.group(1), float(m.group(4))))
    return filas


def parsear_nino_serie(texto):
    """Todas las semanas: ``(fecha ISO, nino12, nino3, nino34, nino4)`` (anomalías en °C)."""
    fila = re.compile(r"^\s*(\d{2}[A-Z]{3}\d{4})\s+((?:-?\d+\.\d\s*){8})\s*$")
    filas = []
    for linea in texto.splitlines():
        m = fila.match(linea)
        if m:
            v = [float(x) for x in re.findall(r"-?\d+\.\d", m.group(2))]
            fecha = datetime.datetime.strptime(m.group(1).title(), "%d%b%Y").date()
            filas.append((fecha.isoformat(), v[1], v[3], v[5], v[7]))
    return filas


def asegurar_series_enso():
    """Si el almacén no tiene las series completas del ONI y del Niño (p. ej. tras reiniciar el servidor, o si los
    datos vienen de una caché anterior), las descarga y las guarda. Son dos archivos de texto pequeños."""
    estado = almacen.resumen()
    if estado["oni"] == 0 or estado["nino_semanal"] == 0:
        almacen.guardar_series_enso(parsear_oni_serie(_get(URL_ONI).text),
                                    parsear_nino_serie(_get(URL_NINO_SEMANAL).text))


def obtener_noaa_enso():
    texto_oni, texto_nino = _get(URL_ONI).text, _get(URL_NINO_SEMANAL).text
    oni, semanal = parsear_oni(texto_oni), parsear_nino_semanal(texto_nino)
    try:                                   # series completas para los gráficos históricos
        almacen.guardar_series_enso(parsear_oni_serie(texto_oni), parsear_nino_serie(texto_nino))
    except Exception:  # noqa: BLE001
        pass
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
def _clave_cantones(cantones):
    """Huella del catálogo de cantones: si cambia, lo guardado de GFS/CFSv2 ya no sirve."""
    texto = "|".join(f"{c['canton']}:{c['lat']}:{c['lon']}" for c in cantones)
    return hashlib.sha1(texto.encode()).hexdigest()[:12]


def cargar_todo(cantones, max_edad_s=3 * 3600):
    """Obtiene todas las fuentes en paralelo.

    Arranque rápido: si SQLite tiene el dato de una fuente con menos de ``max_edad_s`` segundos, se usa sin
    descargar (``_origen`` = «sqlite»). Si no, se descarga; y si la descarga falla se usa el último dato bueno.
    """
    clave = _clave_cantones(cantones)
    tareas = {
        "noaa": (lambda: obtener_noaa_enso(), None),
        "gfs": (lambda: obtener_gfs(cantones), clave),
        "cfsv2": (lambda: obtener_cfsv2(cantones), clave),
        "erfen": (lambda: obtener_erfen(), None),
        "ciifen": (lambda: obtener_ciifen(), None),
    }

    def una(nombre, funcion, k):
        try:
            guardado, edad = almacen.leer_fuente(nombre, k)
        except Exception:  # noqa: BLE001
            guardado, edad = None, None
        if guardado is not None and edad is not None and edad < max_edad_s:
            guardado.update({"_estado": "ok", "_origen": "sqlite", "_edad_s": edad})   # «_descargado» ya viene del almacén
            _ULTIMO_BUENO[nombre] = {k2: v for k2, v in guardado.items() if not k2.startswith("_")}
            return guardado
        dato = con_respaldo(nombre, funcion, k)
        dato.setdefault("_edad_s", 0.0)
        dato.setdefault("_descargado", datetime.datetime.now(datetime.timezone.utc))
        return dato

    with ThreadPoolExecutor(max_workers=5) as pool:
        futuros = {n: pool.submit(una, n, f, k) for n, (f, k) in tareas.items()}
        resultados = {n: f.result() for n, f in futuros.items()}
    # Momento de la descarga más antigua (con arranque rápido es el original, no el de ahora): así la «foto» del
    # riesgo no se repite cada vez que arranca un proceso
    momentos = [r["_descargado"] for r in resultados.values() if r.get("_descargado")]
    resultados["_cargado"] = min(momentos).replace(microsecond=0) if momentos else datetime.datetime.now(datetime.timezone.utc)
    return resultados
