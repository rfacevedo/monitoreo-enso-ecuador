import datetime
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

CESIUM_VERSION = "1.114.0"
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
<script src="__CDN__/Cesium.js"></script>
<link href="__CDN__/Widgets/widgets.css" rel="stylesheet">
<style>
  html, body, #cesiumContainer { width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden;
    font-family: -apple-system, 'Segoe UI', Arial, sans-serif; background: #0A192F; }
  .toolbar { position: absolute; top: 10px; left: 10px; z-index: 10; display: flex; gap: 10px; flex-wrap: wrap; }
  .grupo { display: flex; background: rgba(10,25,47,.92); border-radius: 8px; overflow: hidden;
    box-shadow: 0 2px 8px rgba(0,0,0,.45); }
  .grupo button { border: 0; background: transparent; color: #CBD5E1; padding: 8px 16px;
    font-size: 13px; font-weight: 600; cursor: pointer; }
  .grupo button + button { border-left: 1px solid rgba(255,255,255,.15); }
  .grupo button:hover { background: rgba(255,255,255,.1); }
  .grupo button.activo { background: #2563EB; color: #fff; }
  .leyenda { position: absolute; bottom: 34px; left: 10px; z-index: 10; background: rgba(10,25,47,.9);
    color: #fff; font-size: 12px; padding: 8px 12px; border-radius: 8px; line-height: 1.7; }
  .leyenda i { display: inline-block; width: 11px; height: 11px; border-radius: 50%; margin-right: 6px;
    border: 1px solid #fff; vertical-align: middle; }
  #aviso { display: none; position: absolute; inset: 0; z-index: 20; color: #fff; background: #0A192F;
    align-items: center; justify-content: center; text-align: center; padding: 24px; }
</style>
</head>
<body>
<div id="cesiumContainer"></div>
<div id="aviso">Este navegador no admite WebGL, necesario para el visor Cesium.</div>
<div class="toolbar">
  <div class="grupo" id="grpDim">
    <button id="btn2D">2D</button>
    <button id="btn3D" class="activo">3D</button>
  </div>
  <div class="grupo" id="grpBase">
    <button id="btnOSM" class="activo">Topográfico (OSM)</button>
    <button id="btnEsri">Imagen (Esri)</button>
  </div>
  <div class="grupo"><button id="btnHome">Inicio</button></div>
</div>
<div class="leyenda" id="leyenda"></div>
<script>
(function () {
  const PUNTOS = __PUNTOS__;
  const COLORES = __COLORES__;
  const MODO_INICIAL = "__MODO__";
  const BASE_INICIAL = "__BASE__";

  Cesium.Ion.defaultAccessToken = "";

  let viewer;
  try {
    viewer = new Cesium.Viewer('cesiumContainer', {
      baseLayer: false,            // sin imagen por defecto de ion
      baseLayerPicker: false,
      geocoder: false,
      homeButton: false,
      sceneModePicker: false,      // el botón 2D/3D propio lo reemplaza
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

  // ---- Mapas base: OSM (topología) y Esri (imagen) ----
  const capaOSM = viewer.imageryLayers.addImageryProvider(
    new Cesium.OpenStreetMapImageryProvider({ url: 'https://tile.openstreetmap.org/' }));
  const capaEsri = viewer.imageryLayers.addImageryProvider(
    new Cesium.UrlTemplateImageryProvider({
      url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      maximumLevel: 19,
      credit: 'Imagen © Esri, Maxar, Earthstar Geographics'
    }));

  function setBase(base) {
    capaOSM.show = base === 'osm';
    capaEsri.show = base === 'esri';
    document.getElementById('btnOSM').classList.toggle('activo', base === 'osm');
    document.getElementById('btnEsri').classList.toggle('activo', base === 'esri');
    viewer.scene.requestRender();
  }

  // ---- Puntos de riesgo ----
  PUNTOS.forEach(function (p) {
    const color = Cesium.Color.fromCssColorString(COLORES[p.alerta] || '#FFA500');
    viewer.entities.add({
      name: p.canton,
      position: Cesium.Cartesian3.fromDegrees(p.lon, p.lat),
      // Área de influencia proporcional al riesgo (se dibuja pegada al suelo en 2D y 3D)
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

  // ---- Leyenda ----
  const usadas = Array.from(new Set(PUNTOS.map(function (p) { return p.alerta; })));
  document.getElementById('leyenda').innerHTML = usadas.map(function (a) {
    return '<div><i style="background:' + (COLORES[a] || '#FFA500') + '"></i>' + a + '</div>';
  }).join('');

  // ---- Cámara ----
  const RECT_ECUADOR = Cesium.Rectangle.fromDegrees(-82.0, -5.2, -77.0, 1.2);

  function irAInicio(duracion) {
    const d = duracion === undefined ? 1.5 : duracion;
    if (viewer.scene.mode === Cesium.SceneMode.SCENE3D) {
      viewer.camera.flyTo({
        destination: Cesium.Cartesian3.fromDegrees(-79.6, -5.6, 560000),
        orientation: { heading: 0, pitch: Cesium.Math.toRadians(-48), roll: 0 },
        duration: d
      });
    } else {
      viewer.camera.flyTo({ destination: RECT_ECUADOR, duration: d });
    }
  }

  // ---- Botón 2D / 3D ----
  function setDimension(dim) {
    const destino = dim === '2d' ? Cesium.SceneMode.SCENE2D : Cesium.SceneMode.SCENE3D;
    if (viewer.scene.mode !== destino) {
      if (dim === '2d') { viewer.scene.morphTo2D(1.2); } else { viewer.scene.morphTo3D(1.2); }
    }
    document.getElementById('btn2D').classList.toggle('activo', dim === '2d');
    document.getElementById('btn3D').classList.toggle('activo', dim === '3d');
  }
  viewer.scene.morphComplete.addEventListener(function () {
    irAInicio(0.8);
    viewer.scene.requestRender();
  });

  document.getElementById('btn2D').onclick = function () { setDimension('2d'); };
  document.getElementById('btn3D').onclick = function () { setDimension('3d'); };
  document.getElementById('btnOSM').onclick = function () { setBase('osm'); };
  document.getElementById('btnEsri').onclick = function () { setBase('esri'); };
  document.getElementById('btnHome').onclick = function () { irAInicio(1.2); };

  // ---- Estado inicial ----
  setBase(BASE_INICIAL);
  if (MODO_INICIAL === '2d') {
    viewer.scene.morphTo2D(0);
    document.getElementById('btn2D').classList.add('activo');
    document.getElementById('btn3D').classList.remove('activo');
  } else {
    irAInicio(0);
  }
})();
</script>
</body>
</html>
"""


def render_cesium(df, base="osm", modo="3d", alto=560):
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
        .replace("__MODO__", modo)
        .replace("__BASE__", base)
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
    .titulo-mediano { font-size: 28px !important; font-weight: bold !important; color: #1E3A8A; margin-bottom: 5px; }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<p class="titulo-mediano">⛈️ Panel de Alerta Temprana y Riesgo de Inundación (ENSO)</p>', unsafe_allow_html=True)
st.markdown("### Integración de Métricas NOAA, Copernicus, CIIFEN e INOCAR para el Litoral Ecuatoriano")

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
]

df_original = pd.DataFrame(data_points)

# ==========================================
# 4. INTERFAZ LATERAL (FILTROS)
# ==========================================
st.sidebar.header("⚙️ Filtros del Modelo")
fecha_inicio = st.sidebar.date_input("Fecha Inicial", datetime.date(2026, 11, 1))
fecha_fin = st.sidebar.date_input("Fecha de Proyección", datetime.date(2027, 2, 1))
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Visor Cesium")
st.sidebar.caption("El botón 2D/3D y el cambio de mapa base (OSM / Esri) están dentro del visor.")

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
st.subheader("📍 Visor Geográfico Interactivo (Cesium · 2D / 3D)")
render_cesium(df_mapa_reciente, base="osm", modo="3d", alto=560)
st.caption("Topografía: © colaboradores de OpenStreetMap · Imagen: © Esri, Maxar, Earthstar Geographics · Visor: CesiumJS")

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
