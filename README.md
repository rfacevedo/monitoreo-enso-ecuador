# Monitoreo ENSO Ecuador

Sistema de alerta temprana y riesgo de inundación por el Fenómeno de El Niño (ENSO) en el litoral ecuatoriano.
Proyecto GeoCiencias — Mentor: Raúl Acevedo.

## Qué hace
- **Visor geográfico 3D (CesiumJS)** con mapas base (Esri, OpenTopoMap, OSM), perfil de Ecuador y capas con línea
  de tiempo: NOAA (GFS lluvia/viento, GOES, temperatura del mar), NASA MODIS y pronóstico estacional CCSR/IRI.
- **Datos en vivo, descargados automáticamente** (se renuevan cada 3 horas):

| Fuente | Qué se usa | Archivo |
|---|---|---|
| NOAA CPC | ONI y temperaturas del mar Niño 1+2, 3, 3.4 y 4 | `fuentes_datos.py` |
| NOAA GFS (vía Open-Meteo) | Lluvia diaria por cantón, 16 días | `fuentes_datos.py` |
| CCSR/IRI (CFSv2 de NOAA) | Lluvia mensual por cantón, 10 meses | `fuentes_datos.py` |
| INOCAR | Informe técnico ejecutivo ERFEN vigente (PDF): nivel del mar, desbordamientos | `fuentes_datos.py` |
| CIIFEN | Boletín mensual «El Niño/La Niña en América Latina» (PDF) | `fuentes_datos.py` |

- **Modelo de riesgo por cantón** (`modelo_riesgo.py`): combina lluvia, nivel del mar y exposición, amplificados por
  el estado ENSO. Es un modelo **indicativo**: no sustituye los boletines oficiales (INAMHI, SNGR, ERFEN). Sus pesos y
  umbrales son una primera calibración y deben ser revisados.

## Archivos
- `app.py` — interfaz Streamlit y visor Cesium.
- `fuentes_datos.py` — lectores de las fuentes (con respaldo del último dato bueno si una fuente falla).
- `modelo_riesgo.py` — catálogo de cantones, parámetros y cálculo del riesgo.
- `ecuador_perfil.py` — contorno de Ecuador (geoBoundaries, CC0).
- `test_fuentes_modelo.py` — pruebas sin red: `python -m unittest test_fuentes_modelo -v`.

## Ejecutar
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notas
- Cesium se fija en la versión 1.105.2 (las posteriores no cargan sus workers dentro del iframe de Streamlit).
- INOCAR y CIIFEN no ofrecen API: se leen de sus PDF; si cambian el formato esa fuente puede quedar sin datos y la
  app lo avisa.
