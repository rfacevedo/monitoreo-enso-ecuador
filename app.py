import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import datetime
import json
import streamlit.components.v1 as components

# ==========================================
# 0. FUNCIONES DE SOPORTE (ESTILOS COMPILADOS)
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
# 1. CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(
    page_title="Monitoreo ENSO - Gestión de Riesgos Ecuador",
    layout="wide",
    page_icon="⛈️"
)

# Inyección de CSS Avanzado
st.markdown(
    """
    <style>
    .stApp {
        background-color: #E5E7EB !important;
    }
    [data-testid="stSidebar"] {
        background-color: #0A192F !important;
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] input {
        color: #000000 !important;
        font-weight: bold !important;
    }
    .titulo-mediano {
        font-size: 28px !important;
        font-weight: bold !important;
        color: #1E3A8A;
        margin-bottom: 5px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

st.markdown('<p class="titulo-mediano">⛈️ Panel de Alerta Temprana y Riesgo de Inundación (ENSO)</p>', unsafe_allow_html=True)
st.markdown("### Integración de Métricas NOAA, Copernicus, CIIFEN e INOCAR para el Litoral Ecuatoriano")

# ==========================================
# 2. BASE DE DATOS DE PRUEBA
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
    {"canton": "Machala", "provincia": "El Oro", "elevacion": 3.0, "lluvia_mm": 180.4, "mar_cm": 40.0, "riesgo": 0.75, "alerta": "ALTO RIESGO", "lat": -3.26, "lon": -79.96, "fecha": datetime.date(2027, 1, 15)}
]

df_original = pd.DataFrame(data_points)

# ==========================================
# 3. INTERFAZ LATERAL (FILTROS)
# ==========================================
st.sidebar.header("⚙️ Filtros del Modelo")
fecha_inicio = st.sidebar.date_input("Fecha Inicial", datetime.date(2026, 11, 1))
fecha_fin = st.sidebar.date_input("Fecha de Proyección", datetime.date(2027, 2, 1))
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Capas de Mapa Base")
mapa_seleccionado = st.sidebar.selectbox("Selecciona el Mapa Base:", ["Normal (OSM)", "Imagen (Esri Satelital)"])
dimension = st.sidebar.radio("Dimensión Espacial:", ["2D (Plano)", "3D (Relieve Globo)"])

# Filtrado espacio-temporal
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
# 4. VISOR GEOGRÁFICO PRINCIPAL
# ==========================================
st.subheader(f"📍 Visor Geográfico Interactivo - Modo {dimension}")

if dimension == "2D (Plano)":
    if mapa_seleccionado == "Imagen (Esri Satelital)":
        map_tiles = "https://arcgisonline.com{z}/{y}/{x}"
        map_attr = "Esri"
    else:
        map_tiles = "OpenStreetMap"
        map_attr = "OpenStreetMap contributors"
        
    m = folium.Map(location=[-1.80, -79.80], zoom_start=7, tiles=map_tiles, attr=map_attr)
    
    for idx, row in df_mapa_reciente.iterrows():
        color_alerta = "darkred" if row['alerta'] == "CRÍTICO" else ("red" if row['alerta'] == "ALTO RIESGO" else "orange")
        popup_html = f"<div style='font-family:Arial;width:150px;'><b>{row['canton']}</b><br>Riesgo: {int(row['riesgo']*100)}%<br>Lluvia: +{row['lluvia_mm']}mm</div>"
        folium.CircleMarker(
            location=[row['lat'], row['lon']], radius=13, color=color_alerta,
            fill=True, fill_color=color_alerta, fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=250)
        ).add_to(m)
        
    st_folium(m, width=1400, height=480, returned_objects=[])

else:
    if mapa_seleccionado == "Imagen (Esri Satelital)":
        cesium_imagery = "new Cesium.UrlTemplateImageryProvider({ url: 'https://arcgisonline.com{z}/{y}/{x}' })"
    else:
        cesium_imagery = "new Cesium.OpenStreetMapImageryProvider({ url: 'https://openstreetmap.org' })"
        
    js_puntos = ""
    for idx, row in df_mapa_reciente.iterrows():
        color_hex = "#8B0000" if row['alerta'] == "CRÍTICO" else ("#FF4D4D" if row['alerta'] == "ALTO RIESGO" else "#FFA500")
        js_puntos += f"""
        viewer.entities.add({{
            position: Cesium.Cartesian3.fromDegrees({row['lon']}, {row['lat']}, 200),
            point: {{
                pixelSize: 18,
                color: Cesium.Color.fromCssColorString('{color_hex}'),
                outlineColor: Cesium.Color.WHITE,
                outlineWidth: 2,
                disableDepthTestDistance: Number.POSITIVE_INFINITY
            }},
            label: {{
                text: '{row['canton']} ({int(row['riesgo']*100)}%)',
                font: '14px sans-serif',
                fillColor: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -15)
            }}
        }});
        """

    cesium_html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <script src="https://cesium.com"></script>
        <link href="https://cesium.com" rel="stylesheet">
        <style>
            html, body, #cesiumContainer {{ width: 100%; height: 100%; margin: 0; padding: 0; overflow: hidden; }}
        </style>
    </head>
    <body>
        <div id="cesiumContainer"></div>
        <script>
            const viewer = new Cesium.Viewer('cesiumContainer', {{
                terrainProvider: Cesium.createWorldTerrain(),
                imageryProvider: {cesium_imagery},
                baseLayerPicker: false,
                geocoder: false,
                homeButton: false,
                navigationHelpButton: false,
                sceneModePicker: false
            }});
