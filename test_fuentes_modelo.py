"""Pruebas sin red de los lectores de fuentes y del modelo de riesgo.

Ejecutar:  python -m unittest test_fuentes_modelo -v
"""
import datetime
import unittest

import fuentes_datos as fd
import modelo_riesgo as mr

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
        self.assertEqual(mr.calcular_riesgo(c, 1.0, 100, 1.0), 1.0)

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

    def test_sin_fuentes_no_rompe(self):
        regs, enso = mr.construir_registros({}, hoy=datetime.date(2026, 11, 1))
        self.assertEqual((regs, enso), ([], 0.0))


if __name__ == "__main__":
    unittest.main()
