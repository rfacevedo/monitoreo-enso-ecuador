import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
import datetime
import json

st.set_page_config(page_title="Monitoreo ENSO - Ecuador", layout="wide", page_icon="⛈️")
st.title("⛈️ Panel de Alerta Temprana y Riesgo de Inundación (ENSO)")
st.markdown("### Integración de Métricas NOAA, Copernicus, CIIFEN e INOCAR para el Litoral Ecuatoriano")

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

st.sidebar.header("Filtros del Modelo Predictivo")
fecha_inicio = st.sidebar.date_input("Fecha Inicial", datetime.date(2026, 11, 1))
fecha_fin = st.sidebar.date_input("Fecha de Proyección", datetime.date(2027, 2, 1))
umbral_riesgo = st.sidebar.slider("Índice de Riesgo Mínimo", 0.0, 1.0, 0.40)

df_filtrado = df_original[(df_original['fecha'] >= fecha_inicio) & (df_original['fecha'] <= fecha_fin) & (df_original['riesgo'] >= umbral_riesgo)]

col1, col2 = st.columns(2)
with col1:
    st.subheader("📍 Mapa de Alertas Georreferenciadas (Leaflet.js)")
    m = folium.Map(location=[-1.80, -79.80], zoom_start=7, tiles="CartoDB positron")
    if not df_filtrado.empty:
        df_mapa_reciente = df_filtrado.sort_values('fecha').groupby('canton').last().reset_index()
        for idx, row in df_mapa_reciente.iterrows():
            color_alerta = "red" if row['alerta'] in ["CRÍTICO", "ALTO RIESGO"] else "orange"
            popup_html = f"<div style='font-family: Arial; width: 160px;'><b>{row['canton']}</b><br>Riesgo: {int(row['riesgo']*100)}%<br>Lluvia: +{row['lluvia_mm']} mm</div>"
            folium.CircleMarker(location=[row['lat'], row['lon']], radius=12, color=color_alerta, fill=True, fill_color=color_alerta, fill_opacity=0.6, popup=folium.Popup(popup_html, max_width=250)).add_to(m)
    st_folium(m, width="100%", height=450, returned_objects=[])

with col2:
    st.subheader("📈 Evolución Temporal del Riesgo")
    if not df_filtrado.empty:
        fig = go.Figure()
        for canton, grupo in df_filtrado.groupby('canton'):
            grupo_ordenado = grupo.sort_values('fecha')
            fig.add_trace(go.Scatter(x=grupo_ordenado['fecha'], y=grupo_ordenado['riesgo'], mode='lines+markers', name=canton))
        fig.update_layout(xaxis_title="Fecha", yaxis_title="Riesgo", yaxis=dict(range=[0, 1.05]), margin=dict(l=20, r=20, t=10, b=20), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Sin datos.")

st.markdown("---")
c1, c2 = st.columns()
with c1: st.subheader("📋 Datos Filtrados")
with c2:
    if not df_filtrado.empty:
        features = [{"type": "Feature", "properties": {"canton": r['canton'], "riesgo": r['riesgo'], "alerta": r['alerta']}, "geometry": {"type": "Point", "coordinates": [r['lon'], r['lat']]}} for _, r in df_filtrado.iterrows()]
        st.download_button(label="💾 Descargar Capa GeoJSON", data=json.dumps({"type": "FeatureCollection", "features": features}, indent=2), file_name="alertas.geojson", mime="application/geo+json", use_container_width=True)

st.dataframe(df_filtrado[['fecha', 'canton', 'provincia', 'lluvia_mm', 'mar_cm', 'riesgo', 'alerta']], use_container_width=True)
