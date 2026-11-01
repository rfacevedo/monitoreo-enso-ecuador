"""Pruebas sin red de los lectores de fuentes y del modelo de riesgo.

Ejecutar:  python -m unittest test_fuentes_modelo -v
"""
import datetime
import tempfile
import unittest
from pathlib import Path

import almacen
import cantones_costa as cc
import fuentes_datos as fd
import modelo_riesgo as mr

# Las pruebas nunca tocan la base real: usan una SQLite temporal
almacen.RUTA = Path(tempfile.mkdtemp()) / "prueba.sqlite"

ERFEN_TEXTO = (
    "COMITÉ NACIONAL PARA EL ESTUDIO REGIONAL DEL FENÓMENO EL NIÑO INFORME TÉCNICO EJECUTIVO ERFEN Nro. 011-2026 "
    "El 22 de octubre de 2026, de manera virtual, se reunieron los representantes. "
    "CONDICIONES OCEANOGRÁFICAS Y BIOLÓGICO-PESQUERAS Las condiciones cálidas continúan fortaleciéndose. Segunda frase. "
    "Alcanzaron aproximadamente +5,2 °C en la región Niño 1+2. "
    "El nivel del mar permanece elevado, con anomalías superiores a 40 cm y valores mayores de 50 cm en el sector de Esmeraldas, consistentes. "
    "Los desbordamientos de cuerpos hídricos a nivel nacional, de 52 en septiembre a 107 en octubre, al corte."
)


class PruebasLectores(unittest.TestCase):
    def test_oni(self):
        r = fd.parsear_oni("SEAS YR TOTAL ANOM\n  DJF 1950  24.72  -1.53\n  JAS 2026  29.12   2.16\n")
        self.assertEqual(r["trimestre"], "JAS 2026")
        self.assertAlmostEqual(r["anomalia"], 2.16)

    def test_nino_semanal(self):
        r = fd.parsear_nino_semanal(" 14OCT2026     26.2 5.2     29.2 4.2     30.0 3.3     29.7 1.1\n 21OCT2026     26.3 5.2     29.4 4.3     30.1 3.4     29.8 1.1\n")
        self.assertEqual(r["semana"], datetime.date(2026, 10, 21))
        self.assertAlmostEqual(r["nino12"], 5.2)
        self.assertAlmostEqual(r["nino34"], 3.4)

    def test_nino_semanal_con_valores_negativos_pegados(self):
        # La Niña: las anomalías negativas van pegadas al valor anterior; la última fila no se puede saltar
        texto = (" Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA\n"
                 " 02SEP1981     20.6-0.1     24.8-0.1     26.5-0.2     28.3-0.3\n"
                 " 11NOV2026     24.1-1.2     25.0-0.9     26.4-1.1     28.0-0.6\n")
        r = fd.parsear_nino_semanal(texto)
        self.assertEqual(r["semana"], datetime.date(2026, 11, 11))
        self.assertAlmostEqual(r["nino12"], -1.2)
        self.assertAlmostEqual(r["nino34"], -1.1)

    def test_erfen(self):
        r = fd.parsear_erfen(ERFEN_TEXTO)
        self.assertEqual(r["informe"], "011-2026")
        self.assertEqual(r["nivel_mar_cm"], 40.0)
        self.assertEqual(r["nivel_mar_local"], {"esmeraldas": 50.0})
        self.assertAlmostEqual(r["nino12"], 5.2)
        self.assertEqual(r["desbordamientos"]["ahora"], 107)

    def test_erfen_sin_datos_falla_claro(self):
        with self.assertRaises(ValueError):
            fd.parsear_erfen("texto sin las cifras esperadas")

    def test_ciifen(self):
        r = fd.parsear_ciifen(
            "• Durante septiembre... Septiembre de 2026: El Niño continúa fortaleciéndose Condiciones climáticas ENOS "
            "El Niño/La Niña en América Latina • El pronóstico para el trimestre noviembre de 2026 a enero de 2027 prevé el "
            "fortalecimiento de El Niño. Se espera que se mantenga hasta el primer trimestre de 2027. • Otro punto")
        self.assertEqual(r["estado"], "El Niño continúa fortaleciéndose")
        self.assertIn("Se espera que", r["perspectiva"])

    def test_ultimo_boletin_ciifen(self):
        html = ('<a href="https://ciifen.org/wp-content/uploads/2026/09/Boletin_ElNino_LaNina_Septiembre_2026.pdf">'
                '<a href="https://ciifen.org/wp-content/uploads/2026/10/Boletin_ElNino_LaNina_Octubre_2026.pdf">')
        self.assertEqual(fd.ultimo_boletin_ciifen(html)[:2], (2026, 10))

    def test_con_respaldo(self):
        self.assertEqual(fd.con_respaldo("prueba", lambda: {"x": 1})["_estado"], "ok")
        r = fd.con_respaldo("prueba", lambda: 1 / 0)          # falla: devuelve el último bueno
        self.assertEqual((r["_estado"], r["x"]), ("respaldo", 1))
        self.assertEqual(fd.con_respaldo("otra", lambda: 1 / 0)["_estado"], "error")


class PruebasAlmacen(unittest.TestCase):
    def setUp(self):
        almacen.RUTA = Path(tempfile.mkdtemp()) / "t.sqlite"
        fd._ULTIMO_BUENO.clear()

    def test_fuente_conserva_fechas_y_clave(self):
        datos = {"emision": datetime.date(2026, 10, 1), "cantones": {"A": [(datetime.date(2026, 11, 1), 3.5)]}, "_estado": "ok"}
        almacen.guardar_fuente("gfs", datos, clave="abc")
        leido, edad = almacen.leer_fuente("gfs", "abc")
        self.assertEqual(leido["emision"], datetime.date(2026, 10, 1))
        self.assertEqual(leido["cantones"]["A"][0], [datetime.date(2026, 11, 1), 3.5])   # tupla -> lista, fecha intacta
        self.assertNotIn("_estado", leido)
        self.assertIsInstance(leido["_descargado"], datetime.datetime)
        self.assertGreaterEqual(edad, 0)
        self.assertEqual(almacen.leer_fuente("gfs", "otra-clave"), (None, None))        # catálogo distinto: no sirve
        self.assertEqual(almacen.leer_fuente("no_existe"), (None, None))

    def test_series_enso(self):
        almacen.guardar_series_enso([(1998, "DJF", 2.2), (2026, "JAS", 2.16)], [("2026-10-21", 5.2, 4.3, 3.4, 1.1)])
        almacen.guardar_series_enso([(2026, "JAS", 2.16)], [("2026-10-21", 5.2, 4.3, 3.4, 1.1)])   # repetir no duplica
        self.assertEqual([f["anio"] for f in almacen.leer_oni(1990)], [1998, 2026])
        self.assertEqual(len(almacen.leer_nino_semanal()), 1)

    def test_historial_riesgo(self):
        d1 = datetime.datetime(2026, 11, 1, 12, tzinfo=datetime.timezone.utc)
        d2 = d1 + datetime.timedelta(hours=3)
        reg = lambda r: [{"canton": "Guayaquil", "fecha": datetime.date(2026, 11, 2), "riesgo": r, "alerta": "BAJO",
                          "lluvia_mm": 1.0, "mar_cm": 0.0, "horizonte": "GFS · día"},
                         {"canton": "Guayaquil", "fecha": datetime.date(2026, 11, 3), "riesgo": r / 2, "alerta": "BAJO",
                          "lluvia_mm": 1.0, "mar_cm": 0.0, "horizonte": "GFS · día"}]
        self.assertTrue(almacen.guardar_riesgo(d1, reg(0.4)))
        self.assertFalse(almacen.guardar_riesgo(d1, reg(0.9)))        # misma descarga: no se repite
        self.assertTrue(almacen.guardar_riesgo(d2, reg(0.6)))
        evo = almacen.leer_evolucion_riesgo()
        self.assertEqual([round(e["riesgo_max"], 2) for e in evo], [0.4, 0.6])
        self.assertEqual(almacen.resumen()["fotos_riesgo"], 2)

    def test_asegurar_series_descarga_solo_si_el_almacen_esta_vacio(self):
        oni = "SEAS YR TOTAL ANOM\n  JAS 2026  29.12   2.16\n"
        nino = " 21OCT2026     26.3 5.2     29.4 4.3     30.1 3.4     29.8 1.1\n"
        pedidos = []

        class R:
            def __init__(self, texto):
                self.text = texto

        original = fd._get
        try:
            fd._get = lambda url, **kw: pedidos.append(url) or R(oni if url == fd.URL_ONI else nino)
            fd.asegurar_series_enso()
            self.assertEqual(len(pedidos), 2)
            self.assertEqual(almacen.resumen()["oni"], 1)
            fd.asegurar_series_enso()                       # ya hay series: no vuelve a descargar
            self.assertEqual(len(pedidos), 2)
        finally:
            fd._get = original

    def test_evolucion_con_marcas_de_tiempo_de_formatos_mixtos(self):
        """Falló en la nube: marcas con y sin microsegundos hacían fallar pd.to_datetime y rompían la página."""
        import pandas as pd
        reg = [{"canton": "Guayaquil", "fecha": datetime.date(2026, 11, 2), "riesgo": 0.5, "alerta": "BAJO",
                "lluvia_mm": 1.0, "mar_cm": 0.0, "horizonte": "GFS · día"}]
        almacen.guardar_riesgo(datetime.datetime(2026, 11, 1, 20, 49, 32, 123456, tzinfo=datetime.timezone.utc), reg)
        almacen.guardar_riesgo(datetime.datetime(2026, 11, 1, 23, 51, 21, tzinfo=datetime.timezone.utc), reg)
        evo = pd.DataFrame(almacen.leer_evolucion_riesgo())
        momentos = pd.to_datetime(evo["descarga_utc"], format="ISO8601", utc=True).dt.tz_convert("America/Guayaquil")
        self.assertEqual(len(momentos), 2)
        self.assertEqual(momentos.iloc[1].hour, 18)                       # 23:51 UTC = 18:51 en Ecuador

    def test_respaldo_desde_sqlite_si_se_pierde_la_memoria(self):
        fd.con_respaldo("erfen_prueba", lambda: {"informe": "011-2026"})
        fd._ULTIMO_BUENO.clear()                                       # reinicio del proceso
        r = fd.con_respaldo("erfen_prueba", lambda: 1 / 0)
        self.assertEqual((r["_estado"], r["informe"]), ("respaldo", "011-2026"))

    def test_arranque_rapido_no_descarga_si_hay_dato_reciente(self):
        llamadas = []
        originales = (fd.obtener_noaa_enso, fd.obtener_gfs, fd.obtener_cfsv2, fd.obtener_erfen, fd.obtener_ciifen)
        try:
            fd.obtener_noaa_enso = lambda: llamadas.append("noaa") or {"oni": {"anomalia": 2.0}, "semanal": {"nino12": 4.0}}
            fd.obtener_gfs = lambda c: llamadas.append("gfs") or {"cantones": {}}
            fd.obtener_cfsv2 = lambda c: llamadas.append("cfs") or {"cantones": {}}
            fd.obtener_erfen = lambda: llamadas.append("erfen") or {"nivel_mar_cm": 40.0}
            fd.obtener_ciifen = lambda: llamadas.append("ciifen") or {"estado": "x"}
            primera = fd.cargar_todo(mr.CANTONES)
            self.assertEqual(sorted(llamadas), ["cfs", "ciifen", "erfen", "gfs", "noaa"])
            llamadas.clear()
            segunda = fd.cargar_todo(mr.CANTONES)                      # todo reciente en SQLite: cero descargas
            self.assertEqual(llamadas, [])
            self.assertEqual(segunda["erfen"]["_origen"], "sqlite")
            self.assertEqual(segunda["erfen"]["nivel_mar_cm"], 40.0)
            fd.cargar_todo(mr.CANTONES, max_edad_s=-1)                 # caducado: vuelve a descargar
            self.assertEqual(len(llamadas), 5)
            self.assertEqual(primera["_cargado"], segunda["_cargado"])   # mismo momento: no se duplica la «foto» del riesgo
        finally:
            (fd.obtener_noaa_enso, fd.obtener_gfs, fd.obtener_cfsv2, fd.obtener_erfen, fd.obtener_ciifen) = originales


class PruebasBuscadorCantones(unittest.TestCase):
    def test_datos_del_buscador(self):
        lista = cc.CANTONES_COSTA
        self.assertEqual(len(lista), 88)
        self.assertEqual({c["p"] for c in lista}, {"Esmeraldas", "Manabí", "Santo Domingo de los Tsáchilas", "Santa Elena",
                                                   "Guayas", "Los Ríos", "El Oro"})
        for c in lista:
            self.assertTrue(c["r"], c["n"])                              # todo cantón tiene contorno
            oeste, sur, este, norte = c["b"]
            self.assertTrue(oeste <= c["c"][0] <= este and sur <= c["c"][1] <= norte, c["n"])
            self.assertTrue(-82 < oeste < este < -78 and -5 < sur < norte < 2, c["n"])      # dentro de la Costa
            for anillo in c["r"]:
                self.assertEqual(len(anillo) % 2, 0)
        self.assertEqual(len({(c["n"], c["p"]) for c in lista}), 88)    # sin duplicados

    def test_cantones_del_modelo_existen_en_el_buscador(self):
        nombres = {c["n"] for c in cc.CANTONES_COSTA}
        alias = {"Bucay": "General Antonio Elizalde (Bucay)"}
        for c in mr.CANTONES:
            self.assertIn(alias.get(c["canton"], c["canton"]), nombres, c["canton"])


class PruebasModelo(unittest.TestCase):
    def cantón(self, nombre):
        return next(c for c in mr.CANTONES if c["canton"] == nombre)

    def test_indice_enso(self):
        self.assertEqual(mr.indice_enso(None, None), 0.0)
        self.assertEqual(mr.indice_enso(2.5, 6.0), 1.0)
        self.assertAlmostEqual(mr.indice_enso(1.0, 2.0), 0.5)

    def test_niveles(self):
        self.assertEqual(mr.nivel_alerta(0.9, "inundacion"), "CRÍTICO")
        self.assertEqual(mr.nivel_alerta(0.75, "inundacion"), "ALTO RIESGO")
        self.assertEqual(mr.nivel_alerta(0.55, "inundacion"), "ALERTA AMARILLA")
        self.assertEqual(mr.nivel_alerta(0.45, "deslave"), "MEDIO (DESLAVE)")
        self.assertEqual(mr.nivel_alerta(0.45, "inundacion"), "BAJO")

    def test_mas_lluvia_mas_riesgo(self):
        c = self.cantón("Guayaquil")
        self.assertLess(mr.calcular_riesgo(c, 0.1, 40, 0.5), mr.calcular_riesgo(c, 0.8, 40, 0.5))

    def test_enso_amplifica_y_tope(self):
        c = self.cantón("Babahoyo")
        self.assertLess(mr.calcular_riesgo(c, 0.4, 0, 0.0), mr.calcular_riesgo(c, 0.4, 0, 1.0))
        peor = mr.calcular_riesgo(c, 1.0, 100, 1.0)      # todo saturado: cerca del máximo y nunca > 1
        self.assertTrue(0.95 <= peor <= 1.0, peor)

    def test_mar_solo_en_costeros(self):
        erfen = {"_estado": "ok", "nivel_mar_cm": 40.0, "nivel_mar_local": {"esmeraldas": 50.0}}
        self.assertEqual(mr.anomalia_mar_cm(self.cantón("Esmeraldas"), erfen), 50.0)
        self.assertEqual(mr.anomalia_mar_cm(self.cantón("Guayaquil"), erfen), 40.0)
        self.assertEqual(mr.anomalia_mar_cm(self.cantón("Babahoyo"), erfen), 0.0)
        self.assertEqual(mr.anomalia_mar_cm(self.cantón("Esmeraldas"), {"_estado": "error"}), 0.0)

    def test_construir_registros(self):
        hoy = datetime.date(2026, 11, 1)
        datos = {
            "noaa": {"oni": {"anomalia": 2.0}, "semanal": {"nino12": 4.0}},
            "erfen": {"_estado": "ok", "nivel_mar_cm": 40.0, "nivel_mar_local": {}},
            "gfs": {"cantones": {c["canton"]: [(hoy + datetime.timedelta(days=i), 10.0) for i in range(16)] for c in mr.CANTONES}},
            "cfsv2": {"cantones": {c["canton"]: [(datetime.date(2026, m, 1), 300.0) for m in (10, 11, 12)] for c in mr.CANTONES}},
        }
        regs, enso = mr.construir_registros(datos, hoy=hoy)
        self.assertEqual(enso, 1.0)
        horizontes = {r["horizonte"] for r in regs}
        self.assertEqual(horizontes, {"GFS · día", "CFSv2 · mes"})
        # solo entra de CFSv2 el mes posterior al horizonte diario (15-dic); 15-oct es pasado y 15-nov cae dentro de GFS
        self.assertEqual({r["fecha"] for r in regs if r["horizonte"] == "CFSv2 · mes"}, {datetime.date(2026, 12, 15)})
        self.assertTrue(all(0.0 <= r["riesgo"] <= 1.0 for r in regs))

    def test_lluvia_local_normaliza_por_canton(self):
        clima = {"cantones": {
            "Guayaquil": {"dia_p50": 6.0, "dia_p99": 90.0, "d3_p50": 18.0, "d3_p99": 170.0,
                          "mes": {"3": {"p50": 100.0, "p95": 400.0}}},
            "Machala": {"dia_p50": 4.0, "dia_p99": 64.0, "d3_p50": 10.0, "d3_p99": 97.0, "mes": {}},
        }}
        gye, mch = self.cantón("Guayaquil"), self.cantón("Machala")
        # 50 mm en un día: más extremo en Machala (zona más seca) que en Guayaquil
        self.assertGreater(mr.s_lluvia_dia(mch, 50, 50, clima), mr.s_lluvia_dia(gye, 50, 50, clima))
        self.assertEqual(mr.s_lluvia_dia(gye, 3, 3, clima), 0.0)          # lluvia típica -> 0
        self.assertEqual(mr.s_lluvia_dia(gye, 120, 120, clima), 1.0)      # por encima del P99 -> 1
        # mediana 100 y P95 400: el P95 vale 0,5 (saturación en 100 + 2·300 = 700 mm)
        self.assertAlmostEqual(mr.s_lluvia_mes(gye, 3, 400, clima), 0.5)
        self.assertEqual(mr.s_lluvia_mes(gye, 3, 700, clima), 1.0)
        self.assertEqual(mr.s_lluvia_mes(gye, 3, 80, clima), 0.0)
        # sin estadística del mes -> umbral de respaldo
        self.assertAlmostEqual(mr.s_lluvia_mes(mch, 3, mr.LLUVIA_MES_MM / 2, clima), 0.5)
        # sin climatología -> umbrales de respaldo
        self.assertAlmostEqual(mr.s_lluvia_dia(gye, mr.LLUVIA_DIA_MM / 2, 0, {}), 0.5)

    def test_sin_lluvia_el_mar_no_dispara_alerta(self):
        # techo con ENSO máximo y mar de 50-60 cm pero sin lluvia: nunca pasa de BAJO
        for c in mr.CANTONES:
            r = mr.calcular_riesgo(c, 0.0, 60.0 if c["costero"] else 0.0, 1.0)
            self.assertEqual(mr.nivel_alerta(r, c["amenaza"]) in ("BAJO",), True, (c["canton"], r))

    def test_sin_fuentes_no_rompe(self):
        regs, enso = mr.construir_registros({}, hoy=datetime.date(2026, 11, 1))
        self.assertEqual((regs, enso), ([], 0.0))


if __name__ == "__main__":
    unittest.main()
