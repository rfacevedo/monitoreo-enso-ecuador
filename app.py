import calendar
import datetime
import html
import json
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import fuentes_datos
from ecuador_perfil import ECUADOR_PERFIL
from modelo_riesgo import CANTONES, PESOS, UMBRALES, ENSO_MAX_AMPLIFICACION, construir_registros

# Se fija 1.105.2: desde 1.113 los workers son módulos ES y el navegador los bloquea
# al cargarse desde un CDN dentro del iframe de Streamlit (el globo queda vacío).
CESIUM_VERSION = "1.105.2"
CESIUM_CDN = f"https://cdn.jsdelivr.net/npm/cesium@{CESIUM_VERSION}/Build/Cesium"

COLORES_ALERTA = {
    "CRÍTICO": "#8B0000",
    "ALTO RIESGO": "#FF4D4D",
    "ALERTA AMARILLA": "#FFCC00",
    "MEDIO (DESLAVE)": "#FFA500",
    "BAJO": "#16A34A",
}


# ==========================================
# 0. FUNCIONES DE SOPORTE
# ==========================================
def estilo_filas_alertas(row):
    """Aplica colores condicionales a las celdas según el nivel de alerta."""
    val_alerta = row['alerta']
    if val_alerta == "CRÍTICO":
        bg_geo = 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
        bg_alerta = 'background-color: #8B0000; color: white; font-weight: bold;'
    elif val_alerta == "ALTO RIESGO":
        bg_geo = 'background-color: #FFEDD5; color: #9A3412; font-weight: bold;'
        bg_alerta = 'background-color: #FF4D4D; color: white; font-weight: bold;'
    elif val_alerta == "ALERTA AMARILLA":
        bg_geo = 'background-color: #FEF9C3; color: #713F12; font-weight: bold;'
        bg_alerta = 'background-color: #FFCC00; color: black; font-weight: bold;'
    elif val_alerta == "MEDIO (DESLAVE)":
        bg_geo = 'background-color: #F3F4F6; color: #374151; font-weight: bold;'
        bg_alerta = 'background-color: #FFA500; color: white; font-weight: bold;'
    elif val_alerta == "BAJO":
        bg_geo = 'background-color: #DCFCE7; color: #166534; font-weight: bold;'
        bg_alerta = 'background-color: #16A34A; color: white; font-weight: bold;'
    else:
        return [''] * 7
    # columnas: fecha, canton, provincia, lluvia_mm, mar_cm, alerta, horizonte
    return ['', bg_geo, bg_geo, '', '', bg_alerta, '']


def sumar_un_mes(fecha):
    """Devuelve la misma fecha un mes después (ajusta el día si el mes siguiente es más corto)."""
    anio = fecha.year + fecha.month // 12
    mes = fecha.month % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return datetime.date(anio, mes, dia)


def fecha_actual_ecuador():
    """Fecha de hoy en hora de Ecuador (el servidor de Streamlit Cloud trabaja en UTC)."""
    try:
        return datetime.datetime.now(ZoneInfo("America/Guayaquil")).date()
    except Exception:
        return datetime.date.today()


# ==========================================
# 1. VISOR CESIUM (2D / 3D)
# ==========================================
# Plantilla HTML plana (sin f-string) para no chocar con las llaves de JS/CSS.
# Sin Cesium ion: ninguna capa necesita token. Topología = OSM, imagen = Esri.
CESIUM_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script>window.CESIUM_BASE_URL = "__CDN__/";</script>
<script src="__CDN__/Cesium.js"></script>
<link href="__CDN__/Widgets/widgets.css" rel="stylesheet">
<style>
  html, body, #cesiumContainer { width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;
    font-family: -apple-system, 'Segoe UI', Arial, sans-serif; background: #0A192F; }
  .toolbar { position: absolute; top: 10px; left: 10px; right: 90px; z-index: 10; display: flex; gap: 10px;
    flex-wrap: wrap; align-items: flex-start; }
  .grupo { display: flex; align-items: center; background: rgba(29,53,87,.95); border-radius: 8px;
    overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.45); }
  .grupo button { border: 0; background: transparent; color: #CBD5E1; padding: 8px 14px;
    font-size: 13px; font-weight: 600; cursor: pointer; }
  .grupo button + button { border-left: 1px solid rgba(255,255,255,.15); }
  .grupo button:hover { background: rgba(255,255,255,.1); }
  .grupo button.activo { background: #2563EB; color: #fff; }
  .grupo label { color: #94A3B8; font-size: 12px; padding: 0 4px 0 12px; }
  .grupo select { border: 0; background: transparent; color: #fff; font-size: 13px; font-weight: 600;
    padding: 8px 10px 8px 4px; cursor: pointer; outline: none; }
  .grupo select option { color: #000; }
  .grupo input[type=date] { border: 0; background: transparent; color: #fff; font-size: 13px;
    font-weight: 600; padding: 7px 10px 7px 4px; outline: none; color-scheme: dark; }
  #estado { color: #fff; font-size: 12px; background: rgba(29,53,87,.92); padding: 6px 10px;
    border-radius: 8px; display: none; }
  .leyenda { position: absolute; bottom: 34px; z-index: 10; background: rgba(29,53,87,.92);
    color: #fff; font-size: 12px; padding: 8px 12px; border-radius: 8px; line-height: 1.7; }
  /* Mapas base apilados: Esri arriba, OSM debajo, del mismo ancho */
  #grpBase { flex-direction: column; align-items: stretch; }
  #grpBase button { text-align: left; }
  #grpBase button + button { border-left: 0; border-top: 1px solid rgba(255,255,255,.15); }
  /* Controles de vista: columna pegada al extremo derecho del visor, bajo el botón de pantalla completa */
  #grpVista { position: absolute; right: 10px; top: 46px; z-index: 10; flex-direction: column; align-items: stretch; }
  #grpVista label { padding: 4px 0 3px; text-align: center; }
  #grpVista button { padding: 5px 0; min-width: 40px; font-size: 14px; }
  .cesium-infoBox { right: 58px !important; }   /* la ficha de información no tapa la columna */
  #grpVista button + button { border-left: 0; border-top: 1px solid rgba(255,255,255,.15); }
  /* Controles del pronóstico mensual (▶ + línea de tiempo), en la barra superior izquierda */
  #boxTiempo { display: none; align-items: center; padding: 0 8px 0 0; }
  #btnPlay { width: 34px; height: 34px; border: 0; background: #2563EB; color: #fff; cursor: pointer;
    font-size: 14px; line-height: 1; padding: 0; margin-right: 8px; }
  #btnPlay:hover { background: #1D4ED8; }
  #slotTimeline { position: relative; width: 340px; height: 27px; }
  #slotTimeline .cesium-viewer-timelineContainer { position: relative !important; left: 0 !important;
    right: auto !important; bottom: auto !important; width: 340px; height: 27px; }
  #leyenda { left: 10px; }
  #leyendaNoaa { right: 10px; display: none; max-width: 230px; }
  .leyenda i { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px;
    border: 1px solid #fff; vertical-align: middle; }
  .leyenda b { display: block; margin-bottom: 2px; }
  .leyenda .sw { display: inline-block; width: 16px; height: 10px; margin-right: 6px; vertical-align: middle; border-radius: 2px; }
  .leyenda small { color: #94A3B8; display: block; line-height: 1.3; margin-top: 4px; }
  #aviso { display: none; position: absolute; inset: 0; z-index: 20; color: #fff; background: #0A192F;
    align-items: center; justify-content: center; text-align: center; padding: 24px; }
</style>
</head>
<body>
<div id="cesiumContainer"></div>
<div id="aviso">Este navegador no admite WebGL, necesario para el visor Cesium.</div>
<div class="toolbar">
  <div class="grupo" id="grpBase">
    <button id="btnEsri" class="activo">Imagen (Esri)</button>
    <button id="btnTopo">Topográfico (OSM)</button>
    <button id="btnOSM">Base (OSM)</button>
  </div>
  <div class="grupo">
    <label for="selCapa">Capa</label>
    <select id="selCapa">
      <option value="none">Ninguna</option>
      <optgroup label="NOAA">
        <option value="lluvia">Lluvia pronosticada (GFS)</option>
        <option value="viento">Viento pronosticado (GFS)</option>
        <option value="nubes">Nubes / vapor de agua (GOES)</option>
        <option value="sst">Temp. superficie del mar (GFS)</option>
      </optgroup>
      <optgroup label="Pronóstico estacional CCSR/IRI">
        <option value="c_pr">CCSR/IRI Precipitación (CFSv2)</option>
        <option value="c_tas">CCSR/IRI Temperatura (CFSv2)</option>
      </optgroup>
      <optgroup label="Satélite MODIS (NASA)">
        <option value="m_tc">MODIS Color real (Terra)</option>
        <option value="m_lst">MODIS Temp. superficie terrestre (día)</option>
        <option value="m_ndvi">MODIS Vegetación NDVI (8 días)</option>
        <option value="m_cf">MODIS Fracción de nubes (día)</option>
      </optgroup>
    </select>
  </div>
  <div class="grupo" id="boxMes" style="display:none">
    <label for="selMes" id="lblMes">Mes</label>
    <select id="selMes"></select>
  </div>
  <div class="grupo" id="boxTiempo">
    <button id="btnPlay" type="button" title="Reproducir" aria-label="Reproducir">&#9654;</button>
    <div id="slotTimeline"></div>
  </div>
  <div class="grupo" id="boxFecha" style="display:none">
    <label for="inpFecha">Fecha</label>
    <input type="date" id="inpFecha">
  </div>
  <div class="grupo"><button id="btnHome">Inicio</button></div>
  <span id="estado"></span>
</div>
<div class="grupo" id="grpVista">
  <label>Vista</label>
  <button id="vInclinar" type="button" title="Inclinar: ver más horizonte" aria-label="Inclinar">&#9650;</button>
  <button id="vEnderezar" type="button" title="Enderezar: ver desde arriba" aria-label="Enderezar">&#9660;</button>
  <button id="vGirarIzq" type="button" title="Girar a la izquierda" aria-label="Girar a la izquierda">&#10226;</button>
  <button id="vGirarDer" type="button" title="Girar a la derecha" aria-label="Girar a la derecha">&#10227;</button>
  <button id="vZoomMas" type="button" title="Acercar" aria-label="Acercar">+</button>
  <button id="vZoomMenos" type="button" title="Alejar" aria-label="Alejar">&minus;</button>
  <button id="vNorte" type="button" title="Norte arriba y vista cenital" aria-label="Norte arriba">N</button>
</div>
<div class="leyenda" id="leyenda"></div>
<div class="leyenda" id="leyendaNoaa"></div>
<script>
(function () {
  const PUNTOS = __PUNTOS__;
  const COLORES = __COLORES__;

  Cesium.Ion.defaultAccessToken = "";

  let viewer;
  try {
    viewer = new Cesium.Viewer('cesiumContainer', {
      baseLayer: false,            // sin imagen por defecto de ion
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,      // solo vista 3D
      scene3DOnly: true,
      navigationHelpButton: false,
      animation: false,
      timeline: true,              // solo se muestra con las capas de pronóstico mensual (CCSR/IRI)
      fullscreenButton: true,
      infoBox: true,
      selectionIndicator: true,
      requestRenderMode: true,     // renderiza solo cuando algo cambia
      maximumRenderTimeChange: Infinity
    });
  } catch (e) {
    document.getElementById('aviso').style.display = 'flex';
    return;
  }

  // La línea de tiempo de Cesium se mueve a la barra superior izquierda (junto al botón ▶)
  const timelineEl = viewer.timeline.container;
  const boxTiempo = document.getElementById('boxTiempo');
  document.getElementById('slotTimeline').appendChild(timelineEl);
  timelineEl.style.display = 'none';

  // ---- Mapas base: Esri (imagen, por defecto) y OSM (topografía) ----
  const capaEsri = viewer.imageryLayers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maximumLevel: 19,
      credit: 'Imagen © Esri, Maxar, Earthstar Geographics'
    }));
  // Topográfico (OSM): OpenTopoMap, mapa topográfico con curvas de nivel hecho con datos de OpenStreetMap
  const capaTopo = viewer.imageryLayers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({
      url: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
      subdomains: ['a', 'b', 'c'],
      maximumLevel: 17,
      credit: 'Topografía © colaboradores de OpenStreetMap, SRTM | © OpenTopoMap (CC-BY-SA)'
    }));
  // Base (OSM): capa estándar de OpenStreetMap
  const capaOSM = viewer.imageryLayers.addImageryProvider(
    new Cesium.OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }));

  // Opacidad de los mapas base: 90 % (deja ver un poco el fondo y resalta las capas encima)
  const OPACIDAD_BASE = 0.9;
  [capaEsri, capaTopo, capaOSM].forEach(function (l) { l.alpha = OPACIDAD_BASE; });

  function setBase(base) {
    capaOSM.show = base === 'osm';
    capaTopo.show = base === 'topo';
    capaEsri.show = base === 'esri';
    document.getElementById('btnOSM').classList.toggle('activo', base === 'osm');
    document.getElementById('btnTopo').classList.toggle('activo', base === 'topo');
    document.getElementById('btnEsri').classList.toggle('activo', base === 'esri');
    viewer.scene.requestRender();
  }

  // ---- Capas NOAA ----
  // WMS directos de NOAA nowCOAST (globales). Lluvia y viento salen del modelo GFS de NOAA.
  const WMS = {
    nubes: { url: 'https://nowcoast.noaa.gov/geoserver/satellite/wms',
             layers: 'global_water_vapor_imagery_mosaic', alpha: 0.65,
             credit: 'NOAA GOES / nowCOAST',
             titulo: 'Hora', span: 3600000, intervalo: 2000,
             etiqueta: function (ms) { const i = new Date(ms).toISOString(); return i.slice(5, 10) + ' ' + i.slice(11, 16) + ' UTC'; },
             leyenda: '<b>Vapor de agua (GOES)</b>Más claro/blanco = más humedad y nubosidad en altura.<small>Satélite NOAA, mosaico global; imágenes de las últimas horas (usa la línea de tiempo).</small>' },
    sst:   { url: 'https://nowcoast.noaa.gov/geoserver/sea_surface_temperature/wms',
             layers: 'global_sea_surface_temperature', alpha: 0.7,
             credit: 'NOAA GFS / nowCOAST',
             titulo: 'Día', span: 86400000, intervalo: 2500,
             etiqueta: function (ms) { return new Date(ms).toISOString().slice(0, 10); },
             leyenda: '<b>Temp. superficie del mar</b>Colores cálidos = agua más caliente (clave para El Niño).<small>Modelo GFS de NOAA, vía nowCOAST; últimos días disponibles (usa la línea de tiempo).</small>' }
  };
  // Una sola capa WMS activa; se recrea con el parámetro TIME al moverse por la línea de tiempo
  let capaWms = null;
  const tiemposWms = {};     // clave -> promesa con la lista de instantes [ms] del servicio
  function quitarWms() {
    if (capaWms) { viewer.imageryLayers.remove(capaWms, true); capaWms = null; }
  }
  function ponerWms(clave, iso) {
    quitarWms();
    const c = WMS[clave];
    const params = { transparent: true, format: 'image/png' };
    if (iso) { params.time = iso; }
    capaWms = viewer.imageryLayers.addImageryProvider(new Cesium.WebMapServiceImageryProvider({
      url: c.url, layers: c.layers, parameters: params, credit: c.credit
    }));
    capaWms.alpha = c.alpha;
    viewer.scene.requestRender();
  }
  // Lee del GetCapabilities los instantes disponibles (dimensión TIME) de la capa
  function cargarTiemposWms(clave) {
    if (tiemposWms[clave]) { return tiemposWms[clave]; }
    const c = WMS[clave];
    tiemposWms[clave] = fetch(c.url + '?service=WMS&version=1.3.0&request=GetCapabilities').then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.text();
    }).then(function (txt) {
      const xml = new DOMParser().parseFromString(txt, 'text/xml');
      const capa = Array.from(xml.getElementsByTagName('Layer')).find(function (l) {
        const n = Array.from(l.children).find(function (h) { return h.tagName === 'Name'; });
        return n && n.textContent === c.layers;
      });
      const dim = capa && Array.from(capa.children).find(function (h) {
        return h.tagName === 'Dimension' && h.getAttribute('name') === 'time';
      });
      if (!dim) { return []; }
      return dim.textContent.split(',').map(function (t) { return Date.parse(t.trim()); })
        .filter(function (v) { return !isNaN(v); }).sort(function (x, y) { return x - y; });
    });
    tiemposWms[clave].catch(function () { delete tiemposWms[clave]; });
    return tiemposWms[clave];
  }

  // Satélite MODIS (Terra) vía NASA GIBS: teselas diarias, se recrean al cambiar la fecha
  const MODIS = {
    m_tc:   { capa: 'MODIS_Terra_CorrectedReflectance_TrueColor', mt: 'GoogleMapsCompatible_Level9', ext: 'jpg', nivel: 9, alpha: 1.0,
              leyenda: '<b>MODIS Color real (Terra)</b>Imagen tal como la ve el satélite: nubes, humo, sedimentos en ríos y costa.' },
    m_lst:  { capa: 'MODIS_Terra_Land_Surface_Temp_Day', mt: 'GoogleMapsCompatible_Level7', ext: 'png', nivel: 7, alpha: 0.75,
              leyenda: '<b>MODIS Temp. superficie terrestre (día)</b>Colores cálidos = suelo más caliente. Los huecos son nubes.' },
    m_ndvi: { capa: 'MODIS_Terra_NDVI_8Day', mt: 'GoogleMapsCompatible_Level9', ext: 'png', nivel: 9, alpha: 0.8,
              leyenda: '<b>MODIS Vegetación NDVI (8 días)</b>Verde intenso = vegetación sana; tonos pardos = suelo seco o sin cubierta.' },
    m_cf:   { capa: 'MODIS_Terra_Cloud_Fraction_Day', mt: 'GoogleMapsCompatible_Level6', ext: 'png', nivel: 6, alpha: 0.75,
              leyenda: '<b>MODIS Fracción de nubes (día)</b>Más opaco/claro = mayor cobertura de nubes.' }
  };
  let capaModis = null;
  const inpFecha = document.getElementById('inpFecha');
  const boxFecha = document.getElementById('boxFecha');
  (function () {
    const hoy = new Date();
    const f = function (dias) {
      return new Date(hoy.getTime() - dias * 86400000).toISOString().slice(0, 10);
    };
    inpFecha.max = f(1);
    inpFecha.value = f(2);   // las capas diarias de GIBS llegan con 1-3 días de retraso
  })();

  function quitarModis() {
    if (capaModis) { viewer.imageryLayers.remove(capaModis, true); capaModis = null; }
  }
  function ponerModis(clave) {
    quitarModis();
    const c = MODIS[clave];
    const url = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/' + c.capa + '/default/' +
      inpFecha.value + '/' + c.mt + '/{z}/{y}/{x}.' + c.ext;
    capaModis = viewer.imageryLayers.addImageryProvider(new Cesium.UrlTemplateImageryProvider({
      url: url, maximumLevel: c.nivel, credit: 'NASA EOSDIS GIBS / MODIS Terra'
    }));
    capaModis.alpha = c.alpha;
    viewer.scene.requestRender();
  }

  // Pronóstico estacional CCSR/IRI (Columbia): media de los 32 miembros del CFSv2 (NOAA/NCEP, NMME),
  // 10 meses de pronóstico, rejilla de 1°. Se lee por OPeNDAP binario (.dods) directo desde el
  // navegador: el servidor de CCSR responde con CORS abierto. Los meses se navegan con la línea de tiempo.
  const CCSR_BASE = 'https://forecast.ccsr.columbia.edu/data/NMME/NOAA-NCEP/CFSv2/early_month_samples/forecast/';
  const CCSR = {
    c_pr:  { v: 'pr',  titulo: 'Precipitación (CFSv2)', unidad: 'mm/día', dec: 1, minimo: 0.2,
             escala: [[0, '#E0F2FE'], [1, '#A6D8F0'], [3, '#4FA3E0'], [6, '#2563EB'], [10, '#7C3AED']] },
    c_tas: { v: 'tas', titulo: 'Temperatura (CFSv2)', unidad: '°C', dec: 0, minimo: -100,
             escala: [[-100, '#3B82F6'], [14, '#22D3EE'], [18, '#22C55E'], [22, '#FACC15'], [26, '#F97316'], [30, '#EF4444']] }
  };
  const NM = 32, NL = 10, NY = 7, NX = 6;          // miembros, meses de pronóstico, lat -5..1, lon -82..-77
  const MESES_ES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
  const fuenteCcsr = new Cesium.CustomDataSource('ccsr');
  viewer.dataSources.add(fuenteCcsr);
  const boxMes = document.getElementById('boxMes');
  const selMes = document.getElementById('selMes');
  let ccsrDatos = null;     // {meses:[ms], emision, pr:[mes][celda], tas:[mes][celda], lats, lons}
  let ccsrMes = null;       // mes elegido (se conserva al cambiar entre precipitación y temperatura)

  function etiquetaMes(ms) {
    const d = new Date(ms);
    return MESES_ES[d.getUTCMonth()] + '-' + d.getUTCFullYear();
  }

  // Lee una respuesta OPeNDAP binaria: texto DDS + "Data:" + datos XDR (big-endian)
  function dods(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.arrayBuffer();
    }).then(function (buf) {
      const b = new Uint8Array(buf);
      const marca = [10, 68, 97, 116, 97, 58, 10];   // salto de línea + "Data:" + salto de línea
      let i = 0;
      while (i < b.length - 7) {
        let igual = true;
        for (let k = 0; k < 7; k++) { if (b[i + k] !== marca[k]) { igual = false; break; } }
        if (igual) { break; }
        i++;
      }
      if (i >= b.length - 7) { throw new Error('Respuesta OPeNDAP inválida'); }
      return new DataView(buf, i + 7);
    });
  }
  function leerInts(dv) {
    const n = dv.getUint32(0), a = [];
    for (let k = 0; k < n; k++) { a.push(dv.getInt32(8 + 4 * k)); }
    return a;
  }
  function leerFloats(dv) {
    const n = dv.getUint32(0), a = new Float32Array(n);
    for (let k = 0; k < n; k++) { a[k] = dv.getFloat32(8 + 4 * k); }
    return a;
  }
  // Media de los miembros: entrada ordenada [miembro][mes][lat][lon]
  function mediaMiembros(f) {
    const celdas = NY * NX, porMiembro = NL * celdas, salida = [];
    for (let l = 0; l < NL; l++) {
      const fila = new Array(celdas).fill(0);
      for (let m = 0; m < NM; m++) {
        for (let j = 0; j < celdas; j++) { fila[j] += f[m * porMiembro + l * celdas + j] / NM; }
      }
      salida.push(fila);
    }
    return salida;
  }

  function cargarCcsr() {
    if (ccsrDatos) { return Promise.resolve(ccsrDatos); }
    // La última emisión es el último índice de S: se lee su tamaño del .dds
    return fetch(CCSR_BASE + 'pr.dds').then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.text();
    }).then(function (dds) {
      const p = dds.indexOf('S = ');
      const nS = parseInt(dds.substring(p + 4), 10);
      if (!(nS > 0)) { throw new Error('No se pudo leer la emisión'); }
      const s = nS - 1;
      const rng = '[' + s + '][0:' + (NM - 1) + '][0:' + (NL - 1) + '][85:91][278:283]';
      return Promise.all([
        dods(CCSR_BASE + 'pr.dods?pr' + rng),
        dods(CCSR_BASE + 'tas.dods?tas' + rng),
        dods(CCSR_BASE + 'pr.dods?target[' + s + '][0:' + (NL - 1) + ']'),
        dods(CCSR_BASE + 'pr.dods?Y[85:91]'),
        dods(CCSR_BASE + 'pr.dods?X[278:283]'),
        dods(CCSR_BASE + 'pr.dods?S[' + s + ']')
      ]);
    }).then(function (r) {
      const lats = leerInts(r[3]), lonsE = leerInts(r[4]);
      if (lats[0] !== -5 || lats[NY - 1] !== 1 || lonsE[0] !== 278) {
        throw new Error('La rejilla del servicio cambió');
      }
      const dia0 = Date.UTC(1960, 0, 1);
      ccsrDatos = {
        meses: leerInts(r[2]).map(function (d) { return dia0 + d * 86400000; }),
        emision: dia0 + leerInts(r[5])[0] * 86400000,
        pr: mediaMiembros(leerFloats(r[0])),
        tas: mediaMiembros(leerFloats(r[1])),
        lats: lats,
        lons: lonsE.map(function (x) { return x > 180 ? x - 360 : x; })
      };
      selMes.innerHTML = '';
      ccsrDatos.meses.forEach(function (ms, i) {
        const o = document.createElement('option');
        o.value = i; o.textContent = etiquetaMes(ms);
        selMes.appendChild(o);
      });
      return ccsrDatos;
    });
  }

  function indiceMesDesdeFecha(ms) {
    let idx = 0;
    ccsrDatos.meses.forEach(function (m, i) { if (m <= ms) { idx = i; } });
    return idx;
  }

  function dibujarCcsr(clave, mes) {
    fuenteCcsr.entities.removeAll();
    const c = CCSR[clave], serie = ccsrDatos[c.v][mes], etq = etiquetaMes(ccsrDatos.meses[mes]);
    ccsrDatos.lats.forEach(function (lat, y) {
      ccsrDatos.lons.forEach(function (lon, x) {
        const val = serie[y * NX + x];
        if (isNaN(val) || val < c.minimo) { return; }
        const col = Cesium.Color.fromCssColorString(colorEscala(c.escala, val));
        fuenteCcsr.entities.add({
          name: c.titulo + ' ' + etq,
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          rectangle: {
            coordinates: Cesium.Rectangle.fromDegrees(lon - 0.5, lat - 0.5, lon + 0.5, lat + 0.5),
            material: col.withAlpha(0.55), height: 0
          },
          label: {
            text: val.toFixed(c.dec) + (clave === 'c_tas' ? '°' : ''),
            font: '600 11px sans-serif', fillColor: Cesium.Color.WHITE,
            outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE, scale: 0.9,
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1500000)
          },
          description: c.titulo + ' · ' + etq + ': ' + val.toFixed(2) + ' ' + c.unidad +
            '<br>Media de ' + NM + ' miembros del CFSv2 (NOAA/NCEP, NMME)' +
            '<br>Punto de rejilla: ' + lat + '°, ' + lon + '°'
        });
      });
    });
    viewer.scene.requestRender();
  }

  function leyendaCcsr(clave) {
    const c = CCSR[clave], e = c.escala;
    let html = '<b>CCSR/IRI · ' + c.titulo + '</b>';
    e.forEach(function (t, i) {
      let txt;
      if (i === 0 && e.length > 1 && clave === 'c_tas') { txt = '< ' + e[1][0]; }
      else if (!e[i + 1]) { txt = '≥ ' + t[0]; }
      else { txt = t[0] + '–' + e[i + 1][0]; }
      html += '<div><span class="sw" style="background:' + t[1] + '"></span>' + txt + ' ' + c.unidad + '</div>';
    });
    html += '<small>Media de 32 miembros del CFSv2 (NOAA/NCEP, NMME), rejilla de 1°. ' +
      'Emisión: ' + etiquetaMes(ccsrDatos.emision) + '. Usa la línea de tiempo o el selector «Mes».</small>' +
      '<small>Graphics provided by the International Research Institute for Climate and Society, ' +
      'Columbia University (CCSR/IRI).</small>';
    return html;
  }

  // ===== Motor de tiempo común: línea de tiempo de Cesium + selector + reproducción ▶/❚❚ =====
  // Lo usan CCSR/IRI (meses), GFS (días), MODIS (días) y los WMS de NOAA (horas / días).
  const btnPlay = document.getElementById('btnPlay');
  const lblTiempo = document.getElementById('lblMes');
  let tiempo = null;        // {titulo, fechas:[ms], idx, span, intervalo, etiqueta(ms), render(i), selector}
  let timerTiempo = null;

  function detenerTiempo() {
    if (timerTiempo) { clearInterval(timerTiempo); timerTiempo = null; }
    btnPlay.innerHTML = '&#9654;';
    btnPlay.title = 'Reproducir';
    btnPlay.setAttribute('aria-label', 'Reproducir');
  }
  function quitarTiempo() {
    detenerTiempo();
    tiempo = null;
    boxMes.style.display = 'none';
    boxTiempo.style.display = 'none';
    timelineEl.style.display = 'none';
  }
  function indiceTiempo(ms) {
    let idx = 0;
    tiempo.fechas.forEach(function (f, i) { if (f <= ms) { idx = i; } });
    return idx;
  }
  function irAIndice(i, desdeTimeline) {
    if (!tiempo) { return; }
    tiempo.idx = i;
    selMes.value = String(i);
    if (!desdeTimeline) {
      viewer.clock.currentTime = Cesium.JulianDate.fromDate(new Date(tiempo.fechas[i] + tiempo.span / 2));
    }
    tiempo.render(i);
    viewer.scene.requestRender();
  }
  function iniciarTiempo(cfg) {
    detenerTiempo();
    tiempo = cfg;
    const n = cfg.fechas.length;
    lblTiempo.textContent = cfg.titulo;
    selMes.innerHTML = '';
    cfg.fechas.forEach(function (ms, i) {
      const o = document.createElement('option');
      o.value = i; o.textContent = cfg.etiqueta(ms);
      selMes.appendChild(o);
    });
    const ini = Cesium.JulianDate.fromDate(new Date(cfg.fechas[0]));
    const fin = Cesium.JulianDate.fromDate(new Date(cfg.fechas[n - 1] + cfg.span));
    viewer.clock.startTime = ini.clone();
    viewer.clock.stopTime = fin.clone();
    viewer.clock.clockRange = Cesium.ClockRange.CLAMPED;
    viewer.clock.shouldAnimate = false;
    boxTiempo.style.display = 'flex';
    timelineEl.style.display = 'block';
    viewer.timeline.zoomTo(ini, fin);
    viewer.timeline.resize();
    boxMes.style.display = cfg.selector === false ? 'none' : 'flex';
    irAIndice(Math.min(Math.max(cfg.idx, 0), n - 1));
  }
  btnPlay.onclick = function () {
    if (timerTiempo) { detenerTiempo(); return; }
    if (!tiempo) { return; }
    btnPlay.innerHTML = '&#10074;&#10074;';
    btnPlay.title = 'Pausar';
    btnPlay.setAttribute('aria-label', 'Pausar');
    timerTiempo = setInterval(function () {
      if (!tiempo) { detenerTiempo(); return; }
      irAIndice((tiempo.idx + 1) % tiempo.fechas.length);   // al llegar al final vuelve al inicio
    }, tiempo.intervalo);
  };
  // Línea de tiempo: al arrastrarla cambia el instante mostrado
  viewer.timeline.addEventListener('settime', function (e) {
    if (!tiempo) { return; }
    const idx = indiceTiempo(Cesium.JulianDate.toDate(e.timeJulian).getTime());
    if (idx !== tiempo.idx) { irAIndice(idx, true); }
    viewer.scene.requestRender();
  }, false);

  function mostrarCcsr(clave) {
    // Mes por defecto: el que contiene la fecha de hoy (o el primero del pronóstico)
    if (ccsrMes === null) { ccsrMes = indiceMesDesdeFecha(Date.now()); }
    leyendaNoaa.innerHTML = leyendaCcsr(clave);
    leyendaNoaa.style.display = 'block';
    iniciarTiempo({
      titulo: 'Mes', fechas: ccsrDatos.meses, idx: ccsrMes, span: 30 * 86400000, intervalo: 2500,
      etiqueta: etiquetaMes,
      render: function (i) { ccsrMes = i; dibujarCcsr(clave, i); }
    });
  }

  // Lluvia / viento: pronóstico diario del GFS (NOAA) en rejilla de 1°, servido por Open-Meteo
  const fuenteGfs = new Cesium.CustomDataSource('gfs');
  viewer.dataSources.add(fuenteGfs);
  const REJ = { latMin: -5, latMax: 1, lonMin: -82, lonMax: -77 };
  let gfs = null;           // [{lat, lon, daily:{...}}]
  let gfsCargando = false;
  const estado = document.getElementById('estado');

  function setEstado(txt) {
    estado.textContent = txt || '';
    estado.style.display = txt ? 'inline-block' : 'none';
  }

  function cargarGfs() {
    if (gfs) { return Promise.resolve(gfs); }
    const lats = [], lons = [];
    for (let la = REJ.latMin; la <= REJ.latMax; la++) {
      for (let lo = REJ.lonMin; lo <= REJ.lonMax; lo++) { lats.push(la); lons.push(lo); }
    }
    const url = 'https://api.open-meteo.com/v1/forecast?latitude=' + lats.join(',') +
      '&longitude=' + lons.join(',') +
      '&daily=precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant' +
      '&models=gfs_global&forecast_days=7&timezone=auto';
    return fetch(url).then(function (r) {
      if (!r.ok) { throw new Error('HTTP ' + r.status); }
      return r.json();
    }).then(function (j) {
      const arr = Array.isArray(j) ? j : [j];
      gfs = arr.map(function (o, i) { return { lat: lats[i], lon: lons[i], daily: o.daily }; });
      return gfs;
    });
  }

  const ESCALA_LLUVIA = [
    [1, '#A6D8F0'], [5, '#4FA3E0'], [15, '#2563EB'], [30, '#7C3AED'], [60, '#C026D3']
  ];
  const ESCALA_VIENTO = [
    [0, '#38BDF8'], [10, '#22C55E'], [20, '#FACC15'], [30, '#F97316'], [45, '#EF4444']
  ];
  function colorEscala(esc, v) {
    let c = esc[0][1];
    for (let i = 0; i < esc.length; i++) { if (v >= esc[i][0]) { c = esc[i][1]; } }
    return c;
  }
  function leyendaEscala(titulo, esc, unidad, nota) {
    return '<b>' + titulo + '</b>' + esc.map(function (e, i) {
      const sig = esc[i + 1] ? '–' + esc[i + 1][0] : '+';
      return '<div><span class="sw" style="background:' + e[1] + '"></span>' + e[0] + sig + ' ' + unidad + '</div>';
    }).join('') + '<small>' + nota + '</small>';
  }

  function dibujarGfs(tipo, dia) {
    fuenteGfs.entities.removeAll();
    gfs.forEach(function (p) {
      const d = p.daily;
      const lluvia = d.precipitation_sum[dia];
      const vel = d.wind_speed_10m_max[dia];
      const dir = d.wind_direction_10m_dominant[dia];
      if (tipo === 'lluvia') {
        if (lluvia === null || lluvia < 1) { return; }
        const col = Cesium.Color.fromCssColorString(colorEscala(ESCALA_LLUVIA, lluvia));
        fuenteGfs.entities.add({
          name: 'Lluvia GFS ' + d.time[dia],
          rectangle: {
            coordinates: Cesium.Rectangle.fromDegrees(p.lon - 0.5, p.lat - 0.5, p.lon + 0.5, p.lat + 0.5),
            material: col.withAlpha(0.55), height: 0
          },
          position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat),
          label: {
            text: Math.round(lluvia) + ' mm', font: '600 11px sans-serif',
            fillColor: Cesium.Color.WHITE, outlineColor: Cesium.Color.BLACK, outlineWidth: 3,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE, scale: 0.9,
            distanceDisplayCondition: new Cesium.DistanceDisplayCondition(0, 1500000)
          },
          description: 'Precipitación acumulada del día: ' + lluvia + ' mm<br>Fecha: ' + d.time[dia] +
            '<br>Punto de rejilla: ' + p.lat + '°, ' + p.lon + '°'
        });
      } else if (tipo === 'viento') {
        if (vel === null) { return; }
        const col = Cesium.Color.fromCssColorString(colorEscala(ESCALA_VIENTO, vel));
        // La dirección meteorológica indica de dónde sopla; la flecha apunta hacia dónde va.
        const rumbo = Cesium.Math.toRadians(dir + 180);
        const largoKm = 25 + Math.min(vel, 50) * 1.4;
        const dLat = largoKm * Math.cos(rumbo) / 111;
        const dLon = largoKm * Math.sin(rumbo) / (111 * Math.cos(Cesium.Math.toRadians(p.lat)));
        fuenteGfs.entities.add({
          name: 'Viento GFS ' + d.time[dia],
          position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat),
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray([p.lon, p.lat, p.lon + dLon, p.lat + dLat]),
            width: 9,
            material: new Cesium.PolylineArrowMaterialProperty(col)
          },
          description: 'Viento máximo del día: ' + vel + ' km/h<br>Sopla desde: ' + Math.round(dir) +
            '°<br>Fecha: ' + d.time[dia] + '<br>Punto de rejilla: ' + p.lat + '°, ' + p.lon + '°'
        });
      }
    });
    viewer.scene.requestRender();
  }

  const leyendaNoaa = document.getElementById('leyendaNoaa');
  const selCapa = document.getElementById('selCapa');
  const fechaIso = function (ms) { return new Date(ms).toISOString().slice(0, 10); };

  function aplicarCapaNoaa() {
    const sel = selCapa.value;
    quitarTiempo();
    quitarWms();
    quitarModis();
    fuenteGfs.entities.removeAll();
    fuenteCcsr.entities.removeAll();
    boxFecha.style.display = 'none';
    setEstado('');
    if (sel === 'none') {
      leyendaNoaa.style.display = 'none';
    } else if (CCSR[sel]) {
      setEstado('Cargando pronóstico CCSR/IRI (CFSv2)…');
      cargarCcsr().then(function () {
        if (selCapa.value !== sel) { return; }
        setEstado('');
        mostrarCcsr(sel);
      }).catch(function (e) {
        setEstado('No se pudo obtener el pronóstico CCSR/IRI (' + e.message + '). Reintenta en unos segundos.');
        ccsrDatos = null;
      });
    } else if (MODIS[sel]) {
      // Línea de tiempo diaria: los últimos 30 días disponibles de GIBS
      boxFecha.style.display = 'flex';
      leyendaNoaa.innerHTML = MODIS[sel].leyenda + '<small>NASA GIBS, satélite Terra. Se actualiza a diario con 1–3 días de retraso. Usa la línea de tiempo o el campo Fecha.</small>';
      leyendaNoaa.style.display = 'block';
      const hoy0 = Date.parse(fechaIso(Date.now()) + 'T00:00:00Z');
      const fechas = [];
      for (let k = 30; k >= 1; k--) { fechas.push(hoy0 - k * 86400000); }
      inpFecha.min = fechaIso(fechas[0]);
      iniciarTiempo({
        titulo: 'Día', selector: false, fechas: fechas, idx: fechas.length - 2, span: 86400000, intervalo: 3000,
        etiqueta: fechaIso,
        render: function (i) { inpFecha.value = fechaIso(fechas[i]); ponerModis(sel); }
      });
    } else if (WMS[sel]) {
      const c = WMS[sel];
      leyendaNoaa.innerHTML = c.leyenda;
      leyendaNoaa.style.display = 'block';
      ponerWms(sel);                      // de inmediato, la imagen más reciente
      setEstado('Leyendo los instantes disponibles de NOAA…');
      cargarTiemposWms(sel).then(function (fechas) {
        if (selCapa.value !== sel) { return; }
        setEstado('');
        if (!fechas.length) { return; }   // sin dimensión de tiempo: se queda la última imagen
        iniciarTiempo({
          titulo: c.titulo, fechas: fechas, idx: fechas.length - 1, span: c.span, intervalo: c.intervalo,
          etiqueta: c.etiqueta,
          render: function (i) { ponerWms(sel, new Date(fechas[i]).toISOString()); }
        });
      }).catch(function () {
        if (selCapa.value === sel) { setEstado('No se pudo leer la línea de tiempo de NOAA; se muestra la última imagen.'); }
      });
    } else {
      // lluvia o viento (GFS, 7 días)
      leyendaNoaa.innerHTML = sel === 'lluvia'
        ? leyendaEscala('Lluvia del día (GFS)', ESCALA_LLUVIA, 'mm', 'Modelo GFS de NOAA, rejilla de 1° (vía Open-Meteo). Sin color = menos de 1 mm. Usa la línea de tiempo.')
        : leyendaEscala('Viento máx. del día (GFS)', ESCALA_VIENTO, 'km/h', 'La flecha apunta hacia donde sopla el viento. Modelo GFS de NOAA, rejilla de 1° (vía Open-Meteo). Usa la línea de tiempo.');
      leyendaNoaa.style.display = 'block';
      setEstado('Cargando pronóstico NOAA GFS…');
      cargarGfs().then(function () {
        if (selCapa.value !== sel) { return; }
        setEstado('');
        const fechas = gfs[0].daily.time.map(function (t) { return Date.parse(t + 'T00:00:00Z'); });
        iniciarTiempo({
          titulo: 'Día', fechas: fechas, idx: 0, span: 86400000, intervalo: 2000,
          etiqueta: fechaIso,
          render: function (i) { dibujarGfs(sel, i); }
        });
      }).catch(function () {
        setEstado('No se pudo obtener el pronóstico GFS. Reintenta en unos segundos.');
        gfs = null;
      });
    }
    viewer.scene.requestRender();
  }

  selCapa.onchange = aplicarCapaNoaa;
  selMes.onchange = function () {
    irAIndice(parseInt(selMes.value, 10));
  };
  inpFecha.onchange = function () {
    const sel = selCapa.value;
    if (!MODIS[sel] || !inpFecha.value) { return; }
    const i = tiempo ? tiempo.fechas.indexOf(Date.parse(inpFecha.value + 'T00:00:00Z')) : -1;
    if (i >= 0) { irAIndice(i); } else { ponerModis(sel); }   // fuera de la ventana: solo cambia la capa
  };

  // ---- Puntos de riesgo ----
  PUNTOS.forEach(function (p) {
    const color = Cesium.Color.fromCssColorString(COLORES[p.alerta] || '#FFA500');
    viewer.entities.add({
      name: p.canton,
      position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat),
      // Área de influencia proporcional al riesgo
      ellipse: {
        semiMajorAxis: 8000 + p.riesgo * 22000,
        semiMinorAxis: 8000 + p.riesgo * 22000,
        material: color.withAlpha(0.28),
        outline: true,
        outlineColor: color,
        height: 0
      },
      point: {
        pixelSize: 16,
        color: color,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      },
      label: {
        text: p.canton + ' (' + Math.round(p.riesgo * 100) + '%)',
        font: '600 13px sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -14),
        disableDepthTestDistance: Number.POSITIVE_INFINITY
      },
      description:
        '<table class="cesium-infoBox-defaultTable"><tbody>' +
        '<tr><th>Provincia</th><td>' + p.provincia + '</td></tr>' +
        '<tr><th>Alerta</th><td>' + p.alerta + '</td></tr>' +
        '<tr><th>Riesgo</th><td>' + Math.round(p.riesgo * 100) + '%</td></tr>' +
        '<tr><th>Lluvia</th><td>+' + p.lluvia_mm + (p.horizonte.indexOf('mes') >= 0 ? ' mm/mes' : ' mm/día') + '</td></tr>' +
        '<tr><th>Nivel del mar</th><td>+' + p.mar_cm + ' cm</td></tr>' +
        '<tr><th>Elevación</th><td>' + p.elevacion + ' m</td></tr>' +
        '<tr><th>Fecha</th><td>' + p.fecha + '</td></tr>' +
        '<tr><th>Pronóstico</th><td>' + p.horizonte + '</td></tr>' +
        '</tbody></table>'
    });
  });

  // ---- Perfil de Ecuador: siempre visible, encima de cualquier mapa base o capa ----
  // Dos líneas pegadas al suelo (halo oscuro + trazo amarillo) para que se vea
  // sobre imagen satelital, OSM y capas semitransparentes. Ningún selector la oculta.
  const PERFIL = __PERFIL__;
  const fuentePerfil = new Cesium.CustomDataSource('perfil-ecuador');
  viewer.dataSources.add(fuentePerfil);
  PERFIL.forEach(function (anillo) {
    const pos = Cesium.Cartesian3.fromDegreesArray(anillo);
    pos.push(pos[0]);   // cierra el contorno
    fuentePerfil.entities.add({
      polyline: { positions: pos, width: 6, clampToGround: true,
                  material: Cesium.Color.BLACK.withAlpha(0.55) }
    });
    fuentePerfil.entities.add({
      name: 'Perfil de Ecuador',
      polyline: { positions: pos, width: 3, clampToGround: true,
                  material: Cesium.Color.fromCssColorString('#FFD60A') }
    });
  });
  // Mantiene el perfil como última fuente de datos (se dibuja sobre las demás)
  viewer.dataSources.raiseToTop(fuentePerfil);

  // ---- Leyenda de alertas ----
  const usadas = Array.from(new Set(PUNTOS.map(function (p) { return p.alerta; })));
  document.getElementById('leyenda').innerHTML = usadas.map(function (a) {
    return '<div><i style="background:' + (COLORES[a] || '#FFA500') + '"></i>' + a + '</div>';
  }).join('') +
    '<div><span style="display:inline-block;width:18px;height:0;border-top:3px solid #FFD60A;' +
    'margin-right:6px;vertical-align:middle"></span>Perfil de Ecuador</div>';

  // ---- Cámara ----
  function irAInicio(duracion) {
    // Vista cenital (de arriba, norte arriba) que encuadra Ecuador continental
    viewer.camera.flyTo({
      destination: Cesium.Rectangle.fromDegrees(-82.5, -5.6, -76.0, 1.8),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
      duration: duracion === undefined ? 1.5 : duracion
    });
  }

  document.getElementById('btnTopo').onclick = function () { setBase('topo'); };
  document.getElementById('btnOSM').onclick = function () { setBase('osm'); };
  document.getElementById('btnEsri').onclick = function () { setBase('esri'); };
  document.getElementById('btnHome').onclick = function () { irAInicio(1.2); };

  // ---- Controles de vista: inclinar, girar, acercar y norte ----
  // Cesium no trae botones de inclinación en su núcleo; se orbita alrededor del punto
  // del terreno que está en el centro de la pantalla.
  const PASO = Cesium.Math.toRadians(10);
  function centroPantalla() {
    const c = viewer.scene.canvas;
    const rayo = viewer.camera.getPickRay(new Cesium.Cartesian2(c.clientWidth / 2, c.clientHeight / 2));
    return rayo ? viewer.scene.globe.pick(rayo, viewer.scene) : undefined;
  }
  function orbitar(dHeading, dPitch) {
    const objetivo = centroPantalla();
    if (!objetivo) { return; }
    const cam = viewer.camera;
    const rango = Cesium.Cartesian3.distance(cam.positionWC, objetivo);
    const pitch = Cesium.Math.clamp(cam.pitch + dPitch, Cesium.Math.toRadians(-90), Cesium.Math.toRadians(-15));
    cam.lookAt(objetivo, new Cesium.HeadingPitchRange(cam.heading + dHeading, pitch, rango));
    cam.lookAtTransform(Cesium.Matrix4.IDENTITY);   // suelta la cámara para que siga libre
    viewer.scene.requestRender();
  }
  function zoomVista(factor) {
    const altura = viewer.camera.positionCartographic.height;
    if (factor > 0) { viewer.camera.zoomIn(altura * factor); } else { viewer.camera.zoomOut(altura * -factor); }
    viewer.scene.requestRender();
  }
  document.getElementById('vInclinar').onclick = function () { orbitar(0, PASO); };
  document.getElementById('vEnderezar').onclick = function () { orbitar(0, -PASO); };
  document.getElementById('vGirarIzq').onclick = function () { orbitar(-PASO, 0); };
  document.getElementById('vGirarDer').onclick = function () { orbitar(PASO, 0); };
  document.getElementById('vZoomMas').onclick = function () { zoomVista(0.35); };
  document.getElementById('vZoomMenos').onclick = function () { zoomVista(-0.35); };
  document.getElementById('vNorte').onclick = function () {
    // Norte arriba y mirando desde arriba, sin mover el centro de la vista
    orbitar(-viewer.camera.heading, Cesium.Math.toRadians(-90) - viewer.camera.pitch);
  };

  // ---- Estado inicial ----
  setBase('esri');
  irAInicio(0);
})();
</script>
</body>
</html>
"""


def render_cesium(df, alto=560):
    puntos = [
        {
            "canton": r["canton"], "provincia": r["provincia"],
            "lat": float(r["lat"]), "lon": float(r["lon"]),
            "riesgo": float(r["riesgo"]), "alerta": r["alerta"],
            "lluvia_mm": float(r["lluvia_mm"]), "mar_cm": float(r["mar_cm"]),
            "elevacion": float(r["elevacion"]), "fecha": r["fecha"].isoformat(),
            "horizonte": r["horizonte"],
        }
        for _, r in df.iterrows()
    ]
    html = (
        CESIUM_HTML_TEMPLATE
        .replace("__CDN__", CESIUM_CDN)
        .replace("__PUNTOS__", json.dumps(puntos, ensure_ascii=False))
        .replace("__COLORES__", json.dumps(COLORES_ALERTA, ensure_ascii=False))
        .replace("__PERFIL__", json.dumps(ECUADOR_PERFIL, separators=(",", ":")))
    )
    components.html(html, height=alto, scrolling=False)


# ==========================================
# 2. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Monitoreo ENSO - Gestión de Riesgos Ecuador",
    layout="wide",
    page_icon="⛈️"
)

st.markdown(
    """
    <style>
    .stApp { background-color: #E5E7EB !important; }
    [data-testid="stSidebar"] { background-color: #1D3557 !important; color: #FFFFFF !important; }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3, [data-testid="stSidebar"] span { color: #FFFFFF !important; }
    [data-testid="stSidebar"] input { color: #000000 !important; font-weight: bold !important; }
    /* Campos de fecha: fondo blanco y texto negro (día, mes, año y separadores),
       sea cual sea el tema claro/oscuro del navegador */
    [data-testid="stSidebar"] [data-testid="stDateInputField"] {
        background-color: #FFFFFF !important;
        border-radius: 6px !important;
    }
    [data-testid="stSidebar"] [data-testid="stDateInputField"],
    [data-testid="stSidebar"] [data-testid="stDateInputField"] *,
    [data-testid="stSidebar"] [data-testid="stDateInputField"] span,
    [data-testid="stSidebar"] [data-testid="stDateInputField"] input {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        font-weight: bold !important;
    }
    [data-testid="stSidebar"] [data-testid="stDateInput"] svg { fill: #000000 !important; color: #000000 !important; }
    [data-testid="stSidebar"] p.titulo-lateral {
        font-size: 20px !important; font-weight: bold !important; line-height: 1.3 !important;
        color: #FFFFFF !important; margin-bottom: 12px !important;
    }
    [data-testid="stSidebar"] .panel-enso { font-size: 13px; line-height: 1.55; }
    [data-testid="stSidebar"] .panel-enso small { color: #CBD5E1; }
    </style>
    """,
    unsafe_allow_html=True
)


# ==========================================
# 3. DATOS EN VIVO (NOAA, INOCAR, CIIFEN) Y MODELO DE RIESGO
# ==========================================
@st.cache_data(ttl=3 * 3600, show_spinner="Descargando datos de NOAA, INOCAR y CIIFEN…")
def cargar_datos_reales():
    """Descarga todas las fuentes en paralelo; se guarda 3 horas. Si falla toda la lluvia no se guarda."""
    datos = fuentes_datos.cargar_todo(CANTONES)
    if all((datos.get(k) or {}).get("_estado") == "error" for k in ("gfs", "cfsv2")):
        raise RuntimeError("No se pudo descargar ningún pronóstico de lluvia (NOAA GFS / CFSv2).")
    return datos


def categoria_oni(valor):
    """Categorías de NOAA para el ONI."""
    if valor >= 2.0:
        return "El Niño muy fuerte"
    if valor >= 1.5:
        return "El Niño fuerte"
    if valor >= 1.0:
        return "El Niño moderado"
    if valor >= 0.5:
        return "El Niño débil"
    if valor <= -0.5:
        return "La Niña"
    return "neutral"


def _punto(fuente):
    estado = (fuente or {}).get("_estado")
    return {"ok": "🟢", "respaldo": "🟡"}.get(estado, "🔴")


def panel_enso_html(datos, indice_enso):
    """Resumen de las fuentes en vivo para la barra lateral (todo el texto externo va escapado)."""
    e = html.escape
    noaa, erfen, ciifen = datos.get("noaa"), datos.get("erfen"), datos.get("ciifen")
    lineas = []
    if (noaa or {}).get("_estado") != "error" and noaa:
        oni, sem = noaa["oni"], noaa["semanal"]
        lineas.append(
            f"{_punto(noaa)} <b>NOAA</b> · ONI {e(oni['trimestre'])}: <b>{oni['anomalia']:+.2f} °C</b> "
            f"({categoria_oni(oni['anomalia'])})<br>&nbsp;&nbsp;&nbsp;Niño 1+2: {sem['nino12']:+.1f} °C · "
            f"Niño 3.4: {sem['nino34']:+.1f} °C (semana del {sem['semana'].strftime('%d-%m-%Y')})")
    else:
        lineas.append("🔴 <b>NOAA</b> · ENSO no disponible")
    if erfen and erfen.get("_estado") != "error":
        mar = erfen.get("nivel_mar_cm")
        local = ", ".join(f"{e(k.title())} +{v:.0f} cm" for k, v in (erfen.get("nivel_mar_local") or {}).items())
        txt = f"{_punto(erfen)} <b>INOCAR · ERFEN {e(str(erfen.get('informe')))}</b> ({e(str(erfen.get('fecha_reunion')))})"
        if mar is not None:
            txt += f"<br>&nbsp;&nbsp;&nbsp;Nivel del mar: más de +{mar:.0f} cm" + (f" ({local})" if local else "")
        d = erfen.get("desbordamientos")
        if d:
            txt += f"<br>&nbsp;&nbsp;&nbsp;Desbordamientos (SNGR): {d['antes']} → {d['ahora']}"
        lineas.append(txt)
    else:
        lineas.append("🔴 <b>INOCAR · ERFEN</b> no disponible")
    if ciifen and ciifen.get("_estado") != "error":
        lineas.append(f"{_punto(ciifen)} <b>CIIFEN</b> · boletín {e(ciifen['boletin'])}:<br>&nbsp;&nbsp;&nbsp;{e(ciifen['estado'])}")
    else:
        lineas.append("🔴 <b>CIIFEN</b> no disponible")
    lluvia = f"{_punto(datos.get('gfs'))} NOAA GFS (16 días) · {_punto(datos.get('cfsv2'))} CFSv2 (10 meses)"
    lineas.append(f"<b>Lluvia</b>: {lluvia}")
    lineas.append(f"<b>Índice ENSO del modelo</b>: {indice_enso:.2f} (refuerza la lluvia hasta +{ENSO_MAX_AMPLIFICACION * 100:.0f} %)")
    try:
        hora = datos["_cargado"].astimezone(ZoneInfo("America/Guayaquil")).strftime("%d-%m-%Y %H:%M")
    except Exception:
        hora = "—"
    lineas.append(f"<small>Datos descargados: {hora} (hora de Ecuador). Se renuevan cada 3 horas.</small>")
    return '<div class="panel-enso">' + "<br>".join(lineas) + "</div>"


try:
    DATOS = cargar_datos_reales()
except Exception as exc:  # noqa: BLE001
    st.error(f"No se pudieron obtener los datos en vivo: {exc} Intenta de nuevo en unos minutos.")
    st.stop()

registros, INDICE_ENSO = construir_registros(DATOS, hoy=fecha_actual_ecuador())
if not registros:
    st.error("Las fuentes respondieron sin datos utilizables. Intenta de nuevo en unos minutos.")
    st.stop()
df_original = pd.DataFrame(registros)

# ==========================================
# 4. INTERFAZ LATERAL (FILTROS)
# ==========================================
st.sidebar.markdown(
    '<p class="titulo-lateral">⛈️ Sistema de Alerta Temprana y Riesgo de Inundación (ENSO)</p>',
    unsafe_allow_html=True,
)
st.sidebar.header("⚙️ Filtros por fechas de inundación")
def _recalcular_proyeccion():
    """Al cambiar la fecha inicial, la proyección vuelve a ser un mes después."""
    st.session_state["fecha_fin"] = sumar_un_mes(st.session_state["fecha_inicio"])


if "fecha_fin" not in st.session_state:
    st.session_state["fecha_fin"] = sumar_un_mes(fecha_actual_ecuador())

fecha_inicio = st.sidebar.date_input(
    "Fecha Inicial", fecha_actual_ecuador(), key="fecha_inicio", on_change=_recalcular_proyeccion
)
fecha_fin = st.sidebar.date_input(
    "Fecha de Proyección", key="fecha_fin",
    help="Se calcula sola: un mes después de la fecha inicial. También puedes cambiarla a mano.",
)
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

st.sidebar.markdown(
    '<p style="margin-top:6px;">Autor: <b>Raúl Acevedo</b><br>'
    '<a href="https://www.linkedin.com/in/raul-acevedo-76360130/" target="_blank" '
    'rel="noopener noreferrer" style="color:#7DD3FC !important;">LinkedIn</a></p>',
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")
st.sidebar.header("🌊 Estado ENSO en vivo")
st.sidebar.markdown(panel_enso_html(DATOS, INDICE_ENSO), unsafe_allow_html=True)
if st.sidebar.button("🔄 Actualizar datos"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Visor Geográfico")
st.sidebar.caption("El cambio de mapa base (Esri / Topográfico / Base OSM) y las capas NOAA (lluvia, viento) y satélite MODIS están dentro del visor.")
st.sidebar.caption(
    "**Fuentes y créditos**  \n"
    "Base: © colaboradores de OpenStreetMap  \n"
    "Topografía: © colaboradores de OpenStreetMap, SRTM | © OpenTopoMap (CC-BY-SA)  \n"
    "Imagen: © Esri, Maxar, Earthstar Geographics  \n"
    "Predicción: NOAA GFS (vía Open-Meteo) y NOAA nowCOAST  \n"
    "ENSO: NOAA CPC (ONI, Niño) · INOCAR (informe ERFEN) · CIIFEN (boletín El Niño/La Niña)  \n"
    "Pronóstico estacional: CCSR/IRI, Columbia Climate School (CFSv2 de NOAA/NCEP)  \n"
    "Satélite: NASA GIBS / MODIS  \n"
    "Perfil de Ecuador: geoBoundaries (CC0)  \n"
    "Visor: CesiumJS"
)

df_filtrado = df_original[
    (df_original['fecha'] >= fecha_inicio) &
    (df_original['fecha'] <= fecha_fin) &
    (df_original['riesgo'] >= umbral_riesgo)
].copy()

if df_filtrado.empty:
    st.info("No hay registros climáticos o alertas que coincidan con los filtros seleccionados.")
    st.stop()

# Para cada cantón se muestra el peor escenario (mayor riesgo) dentro de las fechas elegidas
df_mapa_reciente = (
    df_filtrado.sort_values(['riesgo', 'fecha'], ascending=[False, True])
    .groupby('canton', sort=False).first().reset_index()
)

# ==========================================
# 5. VISOR GEOGRÁFICO PRINCIPAL (CESIUM 2D/3D)
# ==========================================
render_cesium(df_mapa_reciente, alto=560)

NOMBRES_FUENTES = {"noaa": "NOAA (ONI y Niño)", "gfs": "NOAA GFS (lluvia diaria)", "cfsv2": "CFSv2 (lluvia mensual)",
                   "erfen": "INOCAR · ERFEN (nivel del mar)", "ciifen": "CIIFEN (boletín)"}
for clave, nombre in NOMBRES_FUENTES.items():
    estado = (DATOS.get(clave) or {}).get("_estado")
    if estado == "error":
        st.warning(f"Fuente no disponible: {nombre}. El modelo sigue con las demás, sin este dato.")
    elif estado == "respaldo":
        st.info(f"{nombre}: no respondió; se usa el último dato descargado.")
st.caption("El mapa y el gráfico muestran, para cada cantón, el **peor escenario** (mayor riesgo) dentro de las fechas elegidas.")

# ==========================================
# 6. INDICADORES, GRÁFICO Y TABLA
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("Cantones en alerta", len(df_mapa_reciente))
c2.metric("Riesgo máximo", f"{int(df_mapa_reciente['riesgo'].max() * 100)}%")
c3.metric("Lluvia máx. (día o mes)", f"+{df_mapa_reciente['lluvia_mm'].max():.0f} mm")

df_barras = df_mapa_reciente.sort_values('riesgo', ascending=False)
fig = go.Figure(go.Bar(
    x=df_barras['canton'],
    y=df_barras['riesgo'] * 100,
    marker_color=[COLORES_ALERTA.get(a, "#FFA500") for a in df_barras['alerta']],
    text=[f"{int(v * 100)}%" for v in df_barras['riesgo']],
    textposition="outside",
))
fig.update_layout(
    title="Índice de riesgo por cantón (%)",
    yaxis=dict(range=[0, 110]),
    height=360,
    margin=dict(l=20, r=20, t=50, b=20),
    paper_bgcolor="#E5E7EB",
    plot_bgcolor="#F9FAFB",
)
st.plotly_chart(fig, use_container_width=True)

st.subheader("📋 Detalle de alertas")
df_tabla = (
    df_filtrado.sort_values(['fecha', 'riesgo'], ascending=[True, False])
    [['fecha', 'canton', 'provincia', 'lluvia_mm', 'mar_cm', 'alerta', 'horizonte']]
    .reset_index(drop=True)
)
st.dataframe(
    df_tabla.style.apply(estilo_filas_alertas, axis=1),
    use_container_width=True, hide_index=True,
    column_config={
        "fecha": "Fecha", "canton": "Cantón", "provincia": "Provincia",
        "lluvia_mm": st.column_config.NumberColumn("Lluvia (mm, día o mes)", format="%.1f"),
        "mar_cm": st.column_config.NumberColumn("Nivel del mar (+cm)", format="%.0f"),
        "alerta": "Alerta", "horizonte": "Pronóstico",
    },
)

with st.expander("ℹ️ Cómo se calcula el riesgo (modelo indicativo)"):
    wi, wd = PESOS["inundacion"], PESOS["deslave"]
    st.markdown(
        f"""
**El riesgo (0 a 100 %)** de cada cantón combina datos en vivo de tres fuentes:

`riesgo = peso_lluvia · lluvia × (1 + {ENSO_MAX_AMPLIFICACION:.2f} · índice ENSO) + peso_mar · nivel del mar + peso_exposición · exposición`

| Amenaza | Lluvia | Nivel del mar | Exposición |
|---|---|---|---|
| Inundación | {wi['lluvia']:.0%} | {wi['mar']:.0%} | {wi['expo']:.0%} (baja elevación) |
| Deslave | {wd['lluvia']:.0%} | {wd['mar']:.0%} | {wd['expo']:.0%} (pendiente supuesta) |

- **Lluvia:** NOAA GFS por día (16 días) y CFSv2 por mes (hasta 10 meses), comparadas con el **clima propio de cada
  cantón**: 0 = lluvia típica (mediana) y 1 = lluvia extrema (percentil 99 de los días lluviosos; para los meses, el doble del
  exceso que marca el percentil 95 de ese mes del año).
  Así Santa Elena (seca) y Babahoyo (muy lluviosa) no se miden con la misma vara.
- **Nivel del mar:** anomalía publicada en el informe ERFEN de INOCAR, solo para cantones costeros.
- **Índice ENSO:** promedio del ONI (NOAA CPC, saturado en 2 °C) y de la anomalía semanal de Niño 1+2
  (saturada en 4 °C).
- **Alertas:** crítico desde {UMBRALES['critico']:.0%}, alto riesgo desde {UMBRALES['alto']:.0%}, alerta amarilla desde
  {UMBRALES['amarilla']:.0%}; en deslave, «medio» desde {UMBRALES['deslave_medio']:.0%}; por debajo, bajo. Calibrados por frecuencia:
  con ENSO neutro, la alerta amarilla aparece ~11 días al año y «alto riesgo» ~4-5; con las condiciones actuales de El Niño
  esas cifras se duplican y aparece «crítico» en cantones con nivel del mar alto. Sin lluvia, el nivel del mar
  y la exposición nunca pasan de «bajo».

**Importante:** es un modelo sencillo y **no sustituye** los boletines oficiales de INAMHI, SNGR ni del Comité ERFEN.
Los pesos y umbrales (archivo `modelo_riesgo.py`) son una primera calibración y deben ser revisados.
La información de INOCAR y CIIFEN se lee de sus boletines en PDF; si cambian de formato, esa fuente puede
quedar sin datos y la app lo avisará.

Fuentes: [NOAA CPC · ONI]({fuentes_datos.URL_ONI}) · [NOAA CPC · Niño semanal]({fuentes_datos.URL_NINO_SEMANAL}) ·
[INOCAR · informe ERFEN vigente]({fuentes_datos.URL_ERFEN}) · [CIIFEN · boletines El Niño/La Niña]({fuentes_datos.URL_CIIFEN_LISTA}) ·
[NOAA GFS vía Open-Meteo](https://open-meteo.com/en/docs/gfs-api) · [CCSR/IRI · CFSv2]({fuentes_datos.URL_CFSV2})
"""
    )
