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

- **Modelo de riesgo por cantón** (`modelo_riesgo.py`): combina lluvia, nivel del mar y exposición; el estado ENSO
  refuerza la lluvia hasta un 15 %. Es un modelo **indicativo**: no sustituye los boletines oficiales (INAMHI, SNGR, ERFEN).
- **Calibración** (`climatologia.json`, generado con `generar_climatologia.py`): la lluvia se compara con el **clima propio
  de cada cantón y de cada producto** (GFS archivado 2022-2025 para los días; CFSv2 archivado 2011-2026 para los meses),
  no con un umbral único. Los umbrales de alerta se fijaron por frecuencia: con ENSO neutro, ~11 días/año de alerta amarilla
  y ~4-5 de alto riesgo; sin lluvia, el nivel del mar y la exposición no pasan de «bajo». Los pesos no se han contrastado con
  daños reales (no hay registros de impacto): pendiente de revisión con INAMHI/SNGR.

## Archivos
- `app.py` — interfaz Streamlit y visor Cesium.
- `fuentes_datos.py` — lectores de las fuentes (con respaldo del último dato bueno si una fuente falla).
- `modelo_riesgo.py` — catálogo de cantones, parámetros y cálculo del riesgo.
- `almacen.py` — almacén local en **SQLite** (biblioteca estándar): caché de las fuentes (arranque en ~1 s en lugar de ~16 s,
  y respaldo si una fuente se cae), series del ENSO (ONI desde 1950, Niño semanal desde 1981) e historial del riesgo.
  Ojo: en Streamlit Cloud los archivos locales se borran al reiniciar la app, así que el historial del riesgo es temporal
  (las series del ENSO se vuelven a descargar completas). Para un histórico permanente habría que guardar los datos fuera
  de la app (archivos en el repositorio o una base externa).
- `climatologia.json` — estadísticas locales de lluvia (se regenera con `python generar_climatologia.py`, ~30 min).
- `ecuador_perfil.py` — contorno de Ecuador (geoBoundaries, CC0).
- `generar_susceptibilidad.py` — genera la capa de **susceptibilidad estructural a inundación** (`susceptibilidad_inundacion.tif/.png/.json`)
  con el Copernicus DEM GLO-30 (altura, relieve local, pendiente y cercanía al mar/estuario; requiere `rasterio`, `scipy`, `Pillow`).
  Es terreno, no pronóstico: indica *dónde* se inunda con más facilidad; el modelo por cantón dice *cuándo*. Adaptada del
  análisis ponderado de `geotif.py`, reemplazando los ráster simulados por datos reales. Indicativa, sin validar con inundaciones reales.
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
