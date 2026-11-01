"""Modelo indicativo de riesgo de inundación / deslave por cantón.

IMPORTANTE: es un modelo sencillo y transparente para apoyar el monitoreo; NO sustituye los boletines
oficiales de INAMHI, SNGR ni del Comité ERFEN. Los pesos y umbrales de este archivo son una primera
calibración y deben ser revisados y ajustados por el equipo (Mentor: Raúl Acevedo).

Riesgo (0 a 1) = peso_lluvia · min(1, S_lluvia · amplificación_ENSO) + peso_mar · S_mar + peso_expo · S_expo

- S_lluvia: lluvia pronosticada (NOAA GFS por día; CFSv2 por mes) frente al clima PROPIO de cada cantón
  (``climatologia.json``, generado con ``generar_climatologia.py``): 0 = lluvia típica, 1 = extrema.
- S_mar: anomalía del nivel del mar (INOCAR / ERFEN) en cantones costeros.
- S_expo: exposición por baja elevación (inundación) o pendiente supuesta (deslave).
- amplificación_ENSO: hasta +15 % sobre la lluvia según ONI y Niño 1+2 (NOAA CPC). Solo afecta a la lluvia: sin lluvia el
  nivel del mar y la exposición nunca llevan el riesgo más allá de «bajo».
"""

import datetime
import json
from pathlib import Path

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
    # Principio de diseño: una lluvia extrema por sí sola (S_lluvia = 1) lleva a «alto riesgo»; «crítico» exige además un
    # agravante (nivel del mar alto en inundación). Sin datos de suelo/pendiente, el deslave no pasa de «alto riesgo».
    "inundacion": {"lluvia": 0.60, "mar": 0.25, "expo": 0.15},
    "deslave": {"lluvia": 0.70, "mar": 0.00, "expo": 0.20},
}
# Umbrales de respaldo (se usan solo si falta climatologia.json o la estadística de un cantón)
LLUVIA_DIA_MM = 60.0          # un día con 60 mm o más satura S_lluvia (GFS)
LLUVIA_3DIAS_MM = 120.0       # 3 días acumulados con 120 mm o más saturan S_lluvia (GFS)
LLUVIA_MES_MM = 450.0         # un mes con 450 mm o más satura S_lluvia (CFSv2)
# CFSv2 mensual: 0 = mediana del mismo mes del año; el percentil 95 del archivo vale 0,5 y se llega a 1 cuando el exceso sobre
# la mediana es el doble del que marca el percentil 95 (con satura-en-P95 todos los meses de un evento fuerte quedaban en 1).
MES_FACTOR_SATURACION = 2.0
MAR_SATURA_CM = 60.0          # anomalía del nivel del mar que satura S_mar
ELEVACION_EXPOSICION_M = 60.0  # por debajo de esta cota hay exposición a inundación (lineal)
PENDIENTE_SUPUESTA = 0.6      # exposición fija de los cantones de deslave (sin datos de pendiente)
# El pronóstico de lluvia ya incluye la señal de El Niño; el factor ENSO solo añade un margen por la
# incertidumbre y la persistencia del evento (el CFSv2 mensual, al ser media de miembros, suaviza extremos).
ENSO_MAX_AMPLIFICACION = 0.15
ONI_SATURA = 2.0              # °C de ONI que saturan el índice ENSO
NINO12_SATURA = 4.0           # °C de anomalía en Niño 1+2 que saturan el índice ENSO

# Umbrales de alerta. Calibrados por frecuencia con el clima GFS de 2022-2025 y los pesos de arriba: con ENSO neutro
# (sin anomalía del mar) el riesgo llega a «alerta amarilla» ~11 días al año y a «alto riesgo» ~4-5 días al año
# (agrupando cantones) y «crítico» no ocurre sin un agravante; con las condiciones actuales de El Niño esas cifras
# se duplican (~21 y ~9 días) y aparece «crítico» (~3) en cantones con nivel del mar alto. Sin lluvia, el nivel del
# mar y la exposición por sí solos no pasan de «bajo» (techo ~0,39 < 0,50).
UMBRALES = {"critico": 0.85, "alto": 0.70, "amarilla": 0.50, "deslave_medio": 0.40}


def _cargar_climatologia():
    """Estadísticas locales de lluvia por cantón (si el archivo no existe, el modelo usa los umbrales de respaldo)."""
    try:
        with open(Path(__file__).with_name("climatologia.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CLIMATOLOGIA = _cargar_climatologia()


def _tope(x, minimo=0.0, maximo=1.0):
    return max(minimo, min(maximo, x))


def _normalizar(valor, bajo, alto):
    """0 en ``bajo`` (lluvia típica) y 1 en ``alto`` (lluvia extrema), lineal entre ambos."""
    return _tope((valor - bajo) / (alto - bajo)) if alto > bajo else 0.0


def s_lluvia_dia(canton, dia_mm, acum3_mm, clima=None):
    """S_lluvia (0-1) de un día GFS: el mayor entre la lluvia del día y la acumulada en 3 días, frente al clima local."""
    est = (CLIMATOLOGIA if clima is None else clima).get("cantones", {}).get(canton["canton"])
    if est:
        return max(_normalizar(dia_mm, est["dia_p50"], est["dia_p99"]),
                   _normalizar(acum3_mm, est["d3_p50"], est["d3_p99"]))
    return _tope(max(dia_mm / LLUVIA_DIA_MM, acum3_mm / LLUVIA_3DIAS_MM))


def s_lluvia_mes(canton, mes, mes_mm, clima=None):
    """S_lluvia (0-1) de un mes CFSv2 frente a la mediana y el percentil 95 del mismo mes del año en ese cantón (ver MES_FACTOR_SATURACION)."""
    est = ((CLIMATOLOGIA if clima is None else clima).get("cantones", {}).get(canton["canton"]) or {}).get("mes", {}).get(str(mes))
    if est:
        return _normalizar(mes_mm, est["p50"], est["p50"] + MES_FACTOR_SATURACION * (est["p95"] - est["p50"]))
    return _tope(mes_mm / LLUVIA_MES_MM)


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
    s_ll = _tope(s_lluvia * (1.0 + ENSO_MAX_AMPLIFICACION * enso))
    return _tope(w["lluvia"] * s_ll + w["mar"] * s_mar + w["expo"] * s_expo)


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
            s_ll = s_lluvia_dia(c, dia_mm, acum3)
            r = calcular_riesgo(c, s_ll, mar, enso)
            registros.append(_fila(c, fecha, dia_mm, mar, r, "GFS · día"))
        for ini, mes_mm in cfs.get(c["canton"], []):
            fecha = ini.replace(day=15)
            if ultima_gfs is not None and fecha <= ultima_gfs:
                continue                       # el detalle diario de GFS manda dentro de su horizonte
            if fecha < hoy:
                continue
            s_ll = s_lluvia_mes(c, ini.month, mes_mm)
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
