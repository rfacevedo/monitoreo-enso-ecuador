import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import datetime
import json

# 1. Configuración de página de Streamlit
st.set_page_config(
    page_title="Monitoreo ENSO - Gestión de Riesgos Ecuador",
    layout="wide",
    page_icon="⛈️"
)

# 2. Inyección de CSS Avanzado (Fondo de página, Filtros en azul oscuro y textos de fechas en negro)
st.markdown(
    """
    <style>
    /* Fondo de la página principal en plomo claro */
    .stApp {
        background-color: #E5E7EB !important;
    }
    
    /* Cambiar el fondo de la barra de filtros a azul oscuro */
    [data-testid="stSidebar"] {
        background-color: #0A192F !important;
        color: #FFFFFF !important;
    }
    [data-testid="stSidebar"] p, [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3, [data-testid="stSidebar"] span {
        color: #FFFFFF !important;
    }
    
    /* Forzar que los textos y números dentro de los inputs de fechas sean negros */
    [data-testid="stSidebar"] input {
        color: #000000 !important;
        font-weight: bold !important;
    }
    
    /* Modificar el título principal a un tamaño mediano */
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

# Renderizar el título principal
st.markdown('<p class="titulo-mediano">⛈️ Panel de Alerta Temprana y Riesgo de Inundación (ENSO)</p>', unsafe_allow_html=True)
st.markdown("### Integración de Métricas NOAA, Copernicus, CIIFEN e INOCAR para el Litoral Ecuatoriano")

# 3. Base de Datos Temporal de Prueba
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

# 4. Barra Lateral: Filtros y Selección de Mapa Base
st.sidebar.header("⚙️ Filtros del Modelo")
fecha_inicio = st.sidebar.date_input("Fecha Inicial", datetime.date(2026, 11, 1))
fecha_fin = st.sidebar.date_input("Fecha de Proyección", datetime.date(2027, 2, 1))
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

st.sidebar.markdown("---")
st.sidebar.header("🗺️ Capas de Mapa Base")
mapa_seleccionado = st.sidebar.selectbox(
    "Selecciona el Mapa Base:",
    ["Normal (OSM)", "Imagen (Satelital)", "Topológico"]
)

# Configuración dinámica del servidor de teselas (Tiles) según la selección
if mapa_seleccionado == "Imagen (Satelital)":
    map_tiles = "https://arcgisonline.com{z}/{y}/{x}"
    map_attr = "Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
elif mapa_seleccionado == "Topológico":
    map_tiles = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
    map_attr = "Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap (CC-BY-SA)"
else:
    map_tiles = "OpenStreetMap"
    map_attr = "OpenStreetMap contributors"

# Aplicar filtros espacio-temporales
df_filtrado = df_original[
    (df_original['fecha'] >= fecha_inicio) & 
    (df_original['fecha'] <= fecha_fin) & 
    (df_original['riesgo'] >= umbral_riesgo)
].copy()

# 5. CUADRO PRINCIPAL (SUPERIOR): MAPA DE ALERTAS DINÁMICO
st.subheader("📍 Mapa de Alertas Georreferenciadas")
m = folium.Map(location=[-1.80, -79.80], zoom_start=7, tiles=map_tiles, attr=map_attr)

if not df_filtrado.empty:
    df_mapa_reciente = df_filtrado.sort_values('fecha').groupby('canton').last().reset_index()
    for idx, row in df_mapa_reciente.iterrows():
        color_alerta = "darkred" if row['alerta'] == "CRÍTICO" else ("red" if row['alerta'] == "ALTO RIESGO" else "orange")
        popup_html = f"""
        <div style='font-family: Arial; width: 180px;'>
            <h5 style='margin:0 0 5px 0;'>{row['canton']}</h5>
            <b>Riesgo:</b> {int(row['riesgo']*100)}%<br>
            <b>Lluvia Anómala:</b> +{row['lluvia_mm']} mm<br>
            <b>Nivel del Mar:</b> +{row['mar_cm']} cm<br>
        </div>
        """
        folium.CircleMarker(
            location=[row['lat'], row['lon']],
            radius=13,
            color=color_alerta,
            fill=True,
            fill_color=color_alerta,
            fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=250)
        ).add_to(m)

st_folium(m, width=1400, height=480, returned_objects=[])

st.markdown("---")

# 6. CUADRO INTERMEDIO: GRÁFICA DE SERIES DE TIEMPO
st.subheader("📈 Evolución Temporal del Riesgo")
if not df_filtrado.empty:
    fig = go.Figure()
    for canton, grupo in df_filtrado.groupby('canton'):
        grupo_ordenado = grupo.sort_values('fecha')
        fig.add_trace(go.Scatter(
            x=grupo_ordenado['fecha'], y=grupo_ordenado['riesgo'],
            mode='lines+markers', name=canton, line=dict(width=3)
        ))
    fig.update_layout(
        xaxis_title="Fecha de Proyección", yaxis_title="Índice de Riesgo",
        yaxis=dict(range=[0, 1.05]), height=380, margin=dict(l=20, r=20, t=10, b=20), hovermode="x unified",
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Sin datos para generar tendencias.")

st.markdown("---")

# 7. CUADRO INFERIOR: TABLA DE DATOS COLOREADA Y BOTÓN DE DESCARGA
tit_col, btn_col = st.columns()

with tit_col:
    st.subheader("📋 Datos Filtrados y Alertas del Modelo")

# Función avanzada de mapeo de estilos corregida estructuralmente
def estilo_filas_alertas(row):
    val_alerta = row['alerta']
    
    if val_alerta == "CRÍTICO":
        bg_geo = 'background-color: #FEE2E2; color: #991B1B; font-weight: bold;'
        bg_alerta = 'background-color: #8B0000; color: white; font-weight: bold;'
    elif val_alerta == "ALTO RIESGO":
        bg_geo = 'background-color: #FFFEF2; color: #9A3412; font-weight: bold;'
        bg_alerta = 'background-color: #FF4D4D; color: white; font-weight: bold;'
    elif val_alerta == "ALERTA AMARILLA":
        bg_geo = 'background-color: #FEF9C3; color: #713F12; font-weight: bold;'
        bg_alerta = 'background-color: #FFCC00; color: black; font-weight: bold;'
    elif val_alerta == "MEDIO (DESLAVE)":
        bg_geo = 'background-color: #FFEDD5; color: #C2410C; font-weight: bold;'
        bg_alerta = 'background-color: #FFA500; color: white; font-weight: bold;'
    else:
        bg_geo = ''
        bg_alerta = ''

    # Retorna los estilos para cada columna en el orden exacto del DataFrame
    return ['', bg_geo, bg_geo, '', '', bg_alerta]

if not df_filtrado.empty:
    with btn_col:
        features = [{"type": "Feature", "properties": {"canton": r['canton'], "alerta": r['alerta']}, "geometry": {"type": "Point", "coordinates": [r['lon'], r['lat']]}} for _, r in df_filtrado.iterrows()]
        st.download_button(
            label="💾 Descargar Capa GeoJSON",
            data=json.dumps({"type": "FeatureCollection", "features": features}, indent=2),
            file_name="alertas_ecuador.geojson", mime="application/geo+json", use_container_width=True
        )

    # Formatear la estructura del DataFrame para visualización
    df_mostrar = df_filtrado[['fecha', 'canton', 'provincia', 'lluvia_mm', 'mar_cm', 'alerta']].copy()
    df_mostrar['fecha'] = df_mostrar['fecha'].astype(str)
    
    # Aplicar estilos condicionales por fila alineados con la tupla devuelta
    df_estilizado = df_mostrar.style.apply(estilo_filas_alertas, axis=1)
    
    st.dataframe(df_estilizado, use_container_width=True, hide_index=True)
else:

