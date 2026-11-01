import datetime
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from ecuador_perfil import ECUADOR_PERFIL

# Se fija 1.105.2: desde 1.113 los workers son módulos ES y el navegador los bloquea
# al cargarse desde un CDN dentro del iframe de Streamlit (el globo queda vacío).
CESIUM_VERSION = "1.105.2"
CESIUM_CDN = f"https://cdn.jsdelivr.net/npm/cesium@{CESIUM_VERSION}/Build/Cesium"

COLORES_ALERTA = {
    "CRÍTICO": "#8B0000",
    "ALTO RIESGO": "#FF4D4D",
    "ALERTA AMARILLA": "#FFCC00",
    "MEDIO (DESLAVE)": "#FFA500",
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
    else:
        return ['', '', '', '', '', '']
    return ['', bg_geo, bg_geo, '', '', bg_alerta]


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
    flex-wrap: wrap; align-items: center; }
  .grupo { display: flex; align-items: center; background: rgba(10,25,47,.92); border-radius: 8px;
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
  #estado { color: #fff; font-size: 12px; background: rgba(10,25,47,.85); padding: 6px 10px;
    border-radius: 8px; display: none; }
  .leyenda { position: absolute; bottom: 34px; z-index: 10; background: rgba(10,25,47,.9);
    color: #fff; font-size: 12px; padding: 8px 12px; border-radius: 8px; line-height: 1.7; }
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
    <button id="btnOSM">Topográfico (OSM)</button>
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
      <optgroup label="Satélite MODIS (NASA)">
        <option value="m_tc">MODIS Color real (Terra)</option>
        <option value="m_lst">MODIS Temp. superficie terrestre (día)</option>
        <option value="m_ndvi">MODIS Vegetación NDVI (8 días)</option>
        <option value="m_cf">MODIS Fracción de nubes (día)</option>
      </optgroup>
    </select>
  </div>
  <div class="grupo" id="boxFecha" style="display:none">
    <label for="inpFecha">Fecha</label>
    <input type="date" id="inpFecha">
  </div>
  <div class="grupo" id="boxDia" style="display:none">
    <label for="selDia">Día</label>
    <select id="selDia"></select>
  </div>
  <div class="grupo"><button id="btnHome">Inicio</button></div>
  <span id="estado"></span>
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
      timeline: false,
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

  // ---- Mapas base: Esri (imagen, por defecto) y OSM (topografía) ----
  const capaEsri = viewer.imageryLayers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maximumLevel: 19,
      credit: 'Imagen © Esri, Maxar, Earthstar Geographics'
    }));
  const capaOSM = viewer.imageryLayers.addImageryProvider(
    new Cesium.OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }));

  function setBase(base) {
    capaOSM.show = base === 'osm';
    capaEsri.show = base === 'esri';
    document.getElementById('btnOSM').classList.toggle('activo', base === 'osm');
    document.getElementById('btnEsri').classList.toggle('activo', base === 'esri');
    viewer.scene.requestRender();
  }

  // ---- Capas NOAA ----
  // WMS directos de NOAA nowCOAST (globales). Lluvia y viento salen del modelo GFS de NOAA.
  const WMS = {
    nubes: { url: 'https://nowcoast.noaa.gov/geoserver/satellite/wms',
             layers: 'global_water_vapor_imagery_mosaic', alpha: 0.65,
             credit: 'NOAA GOES / nowCOAST',
             leyenda: '<b>Vapor de agua (GOES)</b>Más claro/blanco = más humedad y nubosidad en altura.<small>Satélite NOAA, mosaico global casi en tiempo real.</small>' },
    sst:   { url: 'https://nowcoast.noaa.gov/geoserver/sea_surface_temperature/wms',
             layers: 'global_sea_surface_temperature', alpha: 0.7,
             credit: 'NOAA GFS / nowCOAST',
             leyenda: '<b>Temp. superficie del mar</b>Colores cálidos = agua más caliente (clave para El Niño).<small>Modelo GFS de NOAA, vía nowCOAST.</small>' }
  };
  const capasWms = {};
  Object.keys(WMS).forEach(function (k) {
    const c = WMS[k];
    const l = viewer.imageryLayers.addImageryProvider(new Cesium.WebMapServiceImageryProvider({
      url: c.url, layers: c.layers,
      parameters: { transparent: true, format: 'image/png' },
      credit: c.credit
    }));
    l.alpha = c.alpha;
    l.show = false;
    capasWms[k] = l;
  });

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
      const selDia = document.getElementById('selDia');
      selDia.innerHTML = '';
      gfs[0].daily.time.forEach(function (t, i) {
        const o = document.createElement('option');
        o.value = i; o.textContent = (i === 0 ? 'Hoy ' : '') + t;
        selDia.appendChild(o);
      });
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
  const boxDia = document.getElementById('boxDia');
  const selCapa = document.getElementById('selCapa');
  const selDia = document.getElementById('selDia');

  function aplicarCapaNoaa() {
    const sel = selCapa.value;
    Object.keys(capasWms).forEach(function (k) { capasWms[k].show = (k === sel); });
    fuenteGfs.entities.removeAll();
    boxDia.style.display = 'none';
    boxFecha.style.display = 'none';
    quitarModis();
    setEstado('');
    if (sel === 'none') {
      leyendaNoaa.style.display = 'none';
    } else if (MODIS[sel]) {
      boxFecha.style.display = 'flex';
      ponerModis(sel);
      leyendaNoaa.innerHTML = MODIS[sel].leyenda + '<small>NASA GIBS, satélite Terra. Se actualiza a diario con 1–3 días de retraso.</small>';
      leyendaNoaa.style.display = 'block';
    } else if (WMS[sel]) {
      leyendaNoaa.innerHTML = WMS[sel].leyenda;
      leyendaNoaa.style.display = 'block';
    } else {
      // lluvia o viento
      leyendaNoaa.innerHTML = sel === 'lluvia'
        ? leyendaEscala('Lluvia del día (GFS)', ESCALA_LLUVIA, 'mm', 'Modelo GFS de NOAA, rejilla de 1° (vía Open-Meteo). Sin color = menos de 1 mm.')
        : leyendaEscala('Viento máx. del día (GFS)', ESCALA_VIENTO, 'km/h', 'La flecha apunta hacia donde sopla el viento. Modelo GFS de NOAA, rejilla de 1° (vía Open-Meteo).');
      leyendaNoaa.style.display = 'block';
      setEstado('Cargando pronóstico NOAA GFS…');
      cargarGfs().then(function () {
        if (selCapa.value !== sel) { return; }
        boxDia.style.display = 'flex';
        setEstado('');
        dibujarGfs(sel, parseInt(selDia.value || '0', 10));
      }).catch(function () {
        setEstado('No se pudo obtener el pronóstico GFS. Reintenta en unos segundos.');
        gfs = null;
      });
    }
    viewer.scene.requestRender();
  }

  selCapa.onchange = aplicarCapaNoaa;
  inpFecha.onchange = function () {
    if (MODIS[selCapa.value] && inpFecha.value) { ponerModis(selCapa.value); }
  };
  selDia.onchange = function () {
    if (gfs && (selCapa.value === 'lluvia' || selCapa.value === 'viento')) {
      dibujarGfs(selCapa.value, parseInt(selDia.value, 10));
    }
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
        '<tr><th>Lluvia</th><td>+' + p.lluvia_mm + ' mm</td></tr>' +
        '<tr><th>Nivel del mar</th><td>+' + p.mar_cm + ' cm</td></tr>' +
        '<tr><th>Elevación</th><td>' + p.elevacion + ' m</td></tr>' +
        '<tr><th>Fecha</th><td>' + p.fecha + '</td></tr>' +
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
    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(-79.6, -5.6, 560000),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 },
      duration: duracion === undefined ? 1.5 : duracion
    });
  }

  document.getElementById('btnOSM').onclick = function () { setBase('osm'); };
  document.getElementById('btnEsri').onclick = function () { setBase('esri'); };
  document.getElementById('btnHome').onclick = function () { irAInicio(1.2); };

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
    [data-testid="stSidebar"] { background-color: #0A192F !important; color: #FFFFFF !important; }
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
    </style>
    """,
    unsafe_allow_html=True
)


# ==========================================
# 3. BASE DE DATOS DE PRUEBA
# ==========================================
data_points = [
    {"canton": "Babahoyo", "provincia": "Los Ríos", "elevacion": 8.0, "lluvia_mm": 210.5, "mar_cm": 35.0, "riesgo": 0.65, "alerta": "ALERTA AMARILLA", "lat": -1.80, "lon": -79.53, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Guayaquil", "provincia": "Guayas", "elevacion": 4.0, "lluvia_mm": 250.0, "mar_cm": 45.0, "riesgo": 0.95, "alerta": "CRÍTICO", "lat": -2.20, "lon": -79.89, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Chone", "provincia": "Manabí", "elevacion": 15.0, "lluvia_mm": 190.2, "mar_cm": 0.0, "riesgo": 0.60, "alerta": "ALERTA AMARILLA", "lat": -0.69, "lon": -80.09, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Babahoyo", "provincia": "Los Ríos", "elevacion": 8.0, "lluvia_mm": 320.0, "mar_cm": 48.0, "riesgo": 0.92, "alerta": "CRÍTICO", "lat": -1.80, "lon": -79.53, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Guayaquil", "provincia": "Guayas", "elevacion": 4.0, "lluvia_mm": 380.0, "mar_cm": 52.0, "riesgo": 0.98, "alerta": "CRÍTICO", "lat": -2.20, "lon": -79.89, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Chone", "provincia": "Manabí", "elevacion": 15.0, "lluvia_mm": 310.2, "mar_cm": 0.0, "riesgo": 0.85, "alerta": "ALTO RIESGO", "lat": -0.69, "lon": -80.09, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Machala", "provincia": "El Oro", "elevacion": 3.0, "lluvia_mm": 220.4, "mar_cm": 46.0, "riesgo": 0.82, "alerta": "ALTO RIESGO", "lat": -3.26, "lon": -79.96, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Babahoyo", "provincia": "Los Ríos", "elevacion": 8.0, "lluvia_mm": 280.0, "mar_cm": 42.0, "riesgo": 0.85, "alerta": "ALTO RIESGO", "lat": -1.80, "lon": -79.53, "fecha": datetime.date(2027, 1, 15)},
    {"canton": "Guayaquil", "provincia": "Guayas", "elevacion": 4.0, "lluvia_mm": 290.0, "mar_cm": 40.0, "riesgo": 0.88, "alerta": "ALTO RIESGO", "lat": -2.20, "lon": -79.89, "fecha": datetime.date(2027, 1, 15)},
    {"canton": "Bucay", "provincia": "Guayas", "elevacion": 320.0, "lluvia_mm": 350.0, "mar_cm": 0.0, "riesgo": 0.55, "alerta": "MEDIO (DESLAVE)", "lat": -2.20, "lon": -79.13, "fecha": datetime.date(2027, 1, 15)},
    {"canton": "Machala", "provincia": "El Oro", "elevacion": 3.0, "lluvia_mm": 180.4, "mar_cm": 40.0, "riesgo": 0.75, "alerta": "ALTO RIESGO", "lat": -3.26, "lon": -79.96, "fecha": datetime.date(2027, 1, 15)},

    # --- Provincias añadidas: Esmeraldas, Santa Elena y Santo Domingo de los Tsáchilas ---
    # Valores de prueba (ilustrativos), igual que el resto de la tabla; reemplazar por datos reales.
    {"canton": "Esmeraldas", "provincia": "Esmeraldas", "elevacion": 8.0, "lluvia_mm": 230.0, "mar_cm": 30.0, "riesgo": 0.62, "alerta": "ALERTA AMARILLA", "lat": 0.96, "lon": -79.65, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Esmeraldas", "provincia": "Esmeraldas", "elevacion": 8.0, "lluvia_mm": 340.0, "mar_cm": 44.0, "riesgo": 0.87, "alerta": "ALTO RIESGO", "lat": 0.96, "lon": -79.65, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Esmeraldas", "provincia": "Esmeraldas", "elevacion": 8.0, "lluvia_mm": 300.0, "mar_cm": 38.0, "riesgo": 0.78, "alerta": "ALTO RIESGO", "lat": 0.96, "lon": -79.65, "fecha": datetime.date(2027, 1, 15)},
    {"canton": "Santa Elena", "provincia": "Santa Elena", "elevacion": 10.0, "lluvia_mm": 120.0, "mar_cm": 38.0, "riesgo": 0.52, "alerta": "ALERTA AMARILLA", "lat": -2.23, "lon": -80.86, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Santa Elena", "provincia": "Santa Elena", "elevacion": 10.0, "lluvia_mm": 260.0, "mar_cm": 50.0, "riesgo": 0.83, "alerta": "ALTO RIESGO", "lat": -2.23, "lon": -80.86, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Santa Elena", "provincia": "Santa Elena", "elevacion": 10.0, "lluvia_mm": 210.0, "mar_cm": 41.0, "riesgo": 0.72, "alerta": "ALTO RIESGO", "lat": -2.23, "lon": -80.86, "fecha": datetime.date(2027, 1, 15)},
    {"canton": "Santo Domingo", "provincia": "Santo Domingo de los Tsáchilas", "elevacion": 655.0, "lluvia_mm": 240.0, "mar_cm": 0.0, "riesgo": 0.58, "alerta": "ALERTA AMARILLA", "lat": -0.25, "lon": -79.18, "fecha": datetime.date(2026, 11, 15)},
    {"canton": "Santo Domingo", "provincia": "Santo Domingo de los Tsáchilas", "elevacion": 655.0, "lluvia_mm": 340.0, "mar_cm": 0.0, "riesgo": 0.74, "alerta": "ALTO RIESGO", "lat": -0.25, "lon": -79.18, "fecha": datetime.date(2026, 12, 15)},
    {"canton": "Santo Domingo", "provincia": "Santo Domingo de los Tsáchilas", "elevacion": 655.0, "lluvia_mm": 360.0, "mar_cm": 0.0, "riesgo": 0.62, "alerta": "MEDIO (DESLAVE)", "lat": -0.25, "lon": -79.18, "fecha": datetime.date(2027, 1, 15)},
]

df_original = pd.DataFrame(data_points)

# ==========================================
# 4. INTERFAZ LATERAL (FILTROS)
# ==========================================
st.sidebar.markdown(
    '<p class="titulo-lateral">⛈️ Panel de Alerta Temprana y Riesgo de Inundación (ENSO)</p>',
    unsafe_allow_html=True,
)
st.sidebar.header("⚙️ Filtros del Modelo")
fecha_inicio = st.sidebar.date_input("Fecha Inicial", datetime.date(2026, 11, 1))
fecha_fin = st.sidebar.date_input("Fecha de Proyección", datetime.date(2027, 2, 1))
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

st.sidebar.markdown(
    '<p style="margin-top:6px;">Autor: <b>Raúl Acevedo</b><br>'
    '<a href="https://www.linkedin.com/in/raul-acevedo-76360130/" target="_blank" '
    'rel="noopener noreferrer" style="color:#7DD3FC !important;">LinkedIn</a></p>',
    unsafe_allow_html=True,
)

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Visor Cesium")
st.sidebar.caption("El cambio de mapa base (Esri / OSM) y las capas NOAA (lluvia, viento) y satélite MODIS están dentro del visor.")
st.sidebar.caption(
    "**Fuentes y créditos**  \n"
    "Topografía: © colaboradores de OpenStreetMap  \n"
    "Imagen: © Esri, Maxar, Earthstar Geographics  \n"
    "Predicción: NOAA GFS (vía Open-Meteo) y NOAA nowCOAST  \n"
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

df_mapa_reciente = df_filtrado.sort_values('fecha').groupby('canton').last().reset_index()

# ==========================================
# 5. VISOR GEOGRÁFICO PRINCIPAL (CESIUM 2D/3D)
# ==========================================
st.subheader("📍 Visor Geográfico Interactivo (Cesium 3D)")
render_cesium(df_mapa_reciente, alto=560)

# ==========================================
# 6. INDICADORES, GRÁFICO Y TABLA
# ==========================================
c1, c2, c3 = st.columns(3)
c1.metric("Cantones en alerta", len(df_mapa_reciente))
c2.metric("Riesgo máximo", f"{int(df_mapa_reciente['riesgo'].max() * 100)}%")
c3.metric("Lluvia máxima", f"+{df_mapa_reciente['lluvia_mm'].max():.0f} mm")

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
    [['fecha', 'canton', 'provincia', 'lluvia_mm', 'mar_cm', 'alerta']]
    .reset_index(drop=True)
)
st.dataframe(df_tabla.style.apply(estilo_filas_alertas, axis=1), use_container_width=True, hide_index=True)
