"""Modelo indicativo de riesgo de inundación / deslave por cantón.

IMPORTANTE: es un modelo sencillo y transparente para apoyar el monitoreo; NO sustituye los boletines
oficiales de INAMHI, SNGR ni del Comité ERFEN. Los pesos y umbrales de este archivo son una primera
calibración y deben ser revisados y ajustados por el equipo (Mentor: Raúl Acevedo).

Riesgo (0 a 1) = (peso_lluvia · S_lluvia + peso_mar · S_mar + peso_expo · S_expo) · amplificación_ENSO

- S_lluvia: lluvia pronosticada (NOAA GFS por día; CFSv2 por mes) frente a umbrales.
- S_mar: anomalía del nivel del mar (INOCAR / ERFEN) en cantones costeros.
- S_expo: exposición por baja elevación (inundación) o pendiente supuesta (deslave).
- amplificación_ENSO: hasta +25 % según ONI y Niño 1+2 (NOAA CPC).
"""

import datetime

# ----------------------------------------------------------------------------------------------
# Catálogo de cantones (coordenadas y elevaciones aproximadas)
# ----------------------------------------------------------------------------------------------
CANTONES = [
    {"canton": "Babahoyo", "provincia": "Los Ríos", "lat": -1.80, "lon": -79.53, "elevacion": 8.0, "amenaza": "inundacion", "costero": False, "sector_mar": None},
    {"canton": "Guayaquil", "provincia": "Guayas", "lat": -2.20, "lon": -79.89, "elevacion": 4.0, "amenaza": "inundacion", "costero": True, "sector_mar": "guayaquil"},
    {"canton": "Chone", "provincia": "Manabí", "lat": -0.69, "lon": -80.09, "elevacion": 15.0, "amenaza": "inundacion", "costero": False, "sector_mar": None},
    {"canton": "Machala", "provincia": "El Oro", "lat": -3.26, "lon": -79.96, "elevacion": 3.0, "amenaza": "inundacion", "costero": True, "sector_mar": "puerto bolívar"},
    {"canton": "Bucay", "provincia": "Guayas", "lat": -2.20, "lon": -79.13, "elevacion": 320.0, "amenaza": "deslave", "costero": False, "sector_mar": None},
    {"canton": "Esmeraldas", "provincia": "Esmeraldas", "lat": 0.96, "lon": -79.65, "elevacion": 8.0, "amenaza": "inundacion", "costero": True, "sector_mar": "esmeraldas"},
    {"canton": "Santa Elena", "provincia": "Santa Elena", "lat": -2.23, "lon": -80.86, "elevacion": 10.0, "amenaza": "inundacion", "costero": True, "sector_mar": "la libertad"},
    {"canton": "Santo Domingo", "provincia": "Santo Domingo de los Tsáchilas", "lat": -0.25, "lon": -79.18, "elevacion": 655.0, "amenaza": "deslave", "costero": False, "sector_mar": None},
]

# ----------------------------------------------------------------------------------------------
# Parámetros del modelo (ajustables)
# ----------------------------------------------------------------------------------------------
PESOS = {
    "inundacion": {"lluvia": 0.55, "mar": 0.30, "expo": 0.15},
    "deslave": {"lluvia": 0.85, "mar": 0.00, "expo": 0.15},
}
LLUVIA_DIA_MM = 60.0          # un día con 60 mm o más satura S_lluvia (GFS)
LLUVIA_3DIAS_MM = 120.0       # 3 días acumulados con 120 mm o más saturan S_lluvia (GFS)
LLUVIA_MES_MM = 450.0         # un mes con 450 mm o más satura S_lluvia (CFSv2)
MAR_SATURA_CM = 60.0          # anomalía del nivel del mar que satura S_mar
ELEVACION_EXPOSICION_M = 60.0  # por debajo de esta cota hay exposición a inundación (lineal)
PENDIENTE_SUPUESTA = 0.6      # exposición fija de los cantones de deslave (sin datos de pendiente)
ENSO_MAX_AMPLIFICACION = 0.25  # +25 % con ENSO máximo
ONI_SATURA = 2.0              # °C de ONI que saturan el índice ENSO
NINO12_SATURA = 4.0           # °C de anomalía en Niño 1+2 que saturan el índice ENSO

UMBRALES = {"critico": 0.85, "alto": 0.70, "amarilla": 0.50, "deslave_medio": 0.40}


def _tope(x, minimo=0.0, maximo=1.0):
    return max(minimo, min(maximo, x))


def indice_enso(oni, nino12):
    """Índice ENSO 0-1: promedio de ONI (trimestral) y Niño 1+2 (semanal). Sin datos -> 0."""
    partes = []
    if oni is not None:
        partes.append(_tope(oni / ONI_SATURA))
    if nino12 is not None:
        partes.append(_tope(nino12 / NINO12_SATURA))
    return sum(partes) / len(partes) if partes else 0.0


def nivel_alerta(riesgo, amenaza):
    if riesgo >= UMBRALES["critico"]:
        return "CRÍTICO"
    if riesgo >= UMBRALES["alto"]:
        return "ALTO RIESGO"
    if amenaza == "deslave" and riesgo >= UMBRALES["deslave_medio"]:
        return "MEDIO (DESLAVE)"
    if riesgo >= UMBRALES["amarilla"]:
        return "ALERTA AMARILLA"
    return "BAJO"


def anomalia_mar_cm(canton, erfen):
    """Anomalía del nivel del mar (cm) para un cantón costero, a partir del informe ERFEN."""
    if not canton["costero"] or not erfen or erfen.get("_estado") == "error":
        return 0.0
    local = erfen.get("nivel_mar_local") or {}
    sector = canton.get("sector_mar")
    if sector and sector in local:
        return float(local[sector])
    general = erfen.get("nivel_mar_cm")
    return float(general) if general is not None else 0.0


def calcular_riesgo(canton, s_lluvia, mar_cm, enso):
    """Riesgo 0-1 de un cantón para un valor de lluvia ya normalizado (S_lluvia, 0-1)."""
    w = PESOS[canton["amenaza"]]
    s_mar = _tope(mar_cm / MAR_SATURA_CM)
    if canton["amenaza"] == "deslave":
        s_expo = PENDIENTE_SUPUESTA
    else:
        s_expo = _tope((ELEVACION_EXPOSICION_M - canton["elevacion"]) / ELEVACION_EXPOSICION_M)
    base = w["lluvia"] * s_lluvia + w["mar"] * s_mar + w["expo"] * s_expo
    return _tope(base * (1.0 + ENSO_MAX_AMPLIFICACION * enso))


def construir_registros(datos, hoy=None):
    """Convierte las fuentes descargadas en registros por cantón y fecha (diarios GFS + mensuales CFSv2)."""
    hoy = hoy or datetime.date.today()
    noaa = datos.get("noaa") or {}
    oni = (noaa.get("oni") or {}).get("anomalia")
    nino12 = (noaa.get("semanal") or {}).get("nino12")
    erfen = datos.get("erfen")
    enso = indice_enso(oni, nino12)

    gfs = (datos.get("gfs") or {}).get("cantones") or {}
    cfs = (datos.get("cfsv2") or {}).get("cantones") or {}
    registros = []
    for c in CANTONES:
        mar = anomalia_mar_cm(c, erfen)
        diaria = gfs.get(c["canton"], [])
        ultima_gfs = diaria[-1][0] if diaria else None
        mm = [v for _, v in diaria]
        for i, (fecha, dia_mm) in enumerate(diaria):
            acum3 = sum(mm[max(0, i - 2): i + 1])
            s_ll = _tope(max(dia_mm / LLUVIA_DIA_MM, acum3 / LLUVIA_3DIAS_MM))
            r = calcular_riesgo(c, s_ll, mar, enso)
            registros.append(_fila(c, fecha, dia_mm, mar, r, "GFS · día"))
        for ini, mes_mm in cfs.get(c["canton"], []):
            fecha = ini.replace(day=15)
            if ultima_gfs is not None and fecha <= ultima_gfs:
                continue                       # el detalle diario de GFS manda dentro de su horizonte
            if fecha < hoy:
                continue
            s_ll = _tope(mes_mm / LLUVIA_MES_MM)
            r = calcular_riesgo(c, s_ll, mar, enso)
            registros.append(_fila(c, fecha, mes_mm, mar, r, "CFSv2 · mes"))
    return registros, enso


def _fila(c, fecha, lluvia_mm, mar_cm, riesgo, horizonte):
    return {
        "canton": c["canton"], "provincia": c["provincia"], "elevacion": c["elevacion"],
        "lluvia_mm": round(lluvia_mm, 1), "mar_cm": round(mar_cm, 1),
        "riesgo": round(riesgo, 2), "alerta": nivel_alerta(riesgo, c["amenaza"]),
        "lat": c["lat"], "lon": c["lon"], "fecha": fecha, "horizonte": horizonte,
    }
