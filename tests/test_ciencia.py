"""Pruebas de las piezas de la opción A, sin escena completa."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from lectura_gunw import desplazamiento_mm, fase_desde_desplazamiento_mm
from medir import ajuste_estacional, hundimiento_estacional, zscore_anillo
from ndvi_s2 import enmascarar_scl, ndvi
from procesar_insar import (
    construir_matriz_diseno,
    invertir_red,
    preparar_interferograma,
    procesar_observaciones,
    quitar_rampa,
)
from score import calcular_score, normalizar
from sintetico import _serie_desplazamiento
from utilidades import fechas_mensuales


def test_fase_y_desplazamiento_son_inversos():
    original = np.array([-12.0, 0.0, 4.5])
    onda = 0.238403
    signo = -1.0
    recuperado = desplazamiento_mm(fase_desde_desplazamiento_mm(original, onda, signo), onda, signo)
    assert recuperado == pytest.approx(original)


def test_la_rampa_se_va_y_el_pico_se_queda():
    filas, cols = np.indices((20, 30))
    campo = 2.0 + 0.3 * cols - 0.5 * filas
    campo = campo.astype(float)
    campo[10, 15] += 8.0
    salida = quitar_rampa(campo, np.ones(campo.shape, dtype=bool))
    assert salida[0, 0] == pytest.approx(0.0, abs=0.5)
    assert salida[10, 15] > 6.0


def test_inversion_de_una_red_pequena():
    # Desplazamientos verdaderos 0, 1, 3, 6. Observaciones = diferencias.
    pares = np.array([[0, 1], [1, 2], [2, 3], [0, 2], [1, 3]])
    observaciones = np.array([[1.0], [2.0], [3.0], [3.0], [5.0]])
    matriz = construir_matriz_diseno(pares, 4)
    assert np.linalg.matrix_rank(matriz) == 3
    serie = invertir_red(matriz, observaciones, min_ecuaciones=3)
    assert serie[:, 0] == pytest.approx([0, 1, 3, 6])


def test_un_pixel_desconectado_no_se_inventa():
    pares = np.array([[1, 2]])
    # Sin ancla a la fecha 0 el rango no llega a n_fechas-1.
    matriz = construir_matriz_diseno(pares, 3)
    observaciones = np.array([[4.0]])
    serie = invertir_red(matriz, observaciones, min_ecuaciones=1)
    assert np.isnan(serie[:, 0]).all()


def test_ajuste_estacional_recupera_amplitud_y_velocidad():
    fechas = fechas_mensuales(date(2023, 1, 15), 24)
    t = np.array([(f - fechas[0]).days / 365.25 for f in fechas])
    curva = -2.0 * t + 5.0 * np.sin(2 * np.pi * t) + 1.5 * np.cos(2 * np.pi * t) + 0.3
    velocidad, amplitud, velocidad_lineal, _ = ajuste_estacional(fechas, curva.reshape(-1, 1, 1))
    assert velocidad[0, 0] == pytest.approx(-2.0, abs=0.05)
    assert amplitud[0, 0] == pytest.approx(np.hypot(5.0, 1.5), abs=0.05)
    # La recta sola, sin seno, no tiene por qué coincidir: se guarda aparte.
    assert np.isfinite(velocidad_lineal[0, 0])


def test_hundimiento_mayo_noviembre():
    fechas = fechas_mensuales(date(2023, 1, 15), 24)
    amplitud = np.array([[10.0]])
    velocidad = np.array([[0.0]])
    serie = _serie_desplazamiento(fechas, amplitud, velocidad)
    # Mayo está en -A y noviembre en +A, así que noviembre − mayo ≈ 2A.
    hundimiento = hundimiento_estacional(fechas, serie)
    assert hundimiento[0, 0] == pytest.approx(20.0, abs=1.5)


def test_zscore_de_un_pico_local():
    valores = np.zeros((25, 25))
    valores[12, 12] = 10.0
    z, _, _, exceso = zscore_anillo(valores, res_m=100, rmin_m=300, rmax_m=800, min_muestras=10, sigma_suelo=1.0)
    assert z[12, 12] == pytest.approx(10.0)
    assert exceso[12, 12] == pytest.approx(10.0)
    assert abs(z[0, 0]) < 1e-6


def test_formula_de_score_exacta():
    amplitud = normalizar(pd.Series([0.0, 10.0]))
    velocidad = normalizar(pd.Series([0.0, 10.0]))
    ndvi = normalizar(pd.Series([0.2, 0.8]))
    legal = pd.Series([0.0, 1.0])
    salida = calcular_score(amplitud, velocidad, ndvi, legal)
    assert salida["score"].iloc[0] == pytest.approx(0.0)
    assert salida["score"].iloc[1] == pytest.approx(100.0)
    assert salida["p_amplitud"].iloc[1] == pytest.approx(40.0)
    assert salida["p_velocidad"].iloc[1] == pytest.approx(30.0)
    assert salida["p_ndvi"].iloc[1] == pytest.approx(20.0)
    assert salida["p_legal"].iloc[1] == pytest.approx(10.0)


def test_ndvi_y_mascara_de_nube():
    indice = ndvi(np.array([0.1, 0.2]), np.array([0.3, 0.2]))
    assert indice[0] == pytest.approx(0.5)
    enmascarado = enmascarar_scl(indice, np.array([4, 9]))
    assert np.isnan(enmascarado[1])
    assert enmascarado[0] == pytest.approx(0.5)


def test_la_opcion_a_recupera_el_cono_con_rampa_y_ruido():
    rng = np.random.default_rng(1)
    # El cono es estrecho respecto a la escena: si ocupara media imagen, el
    # plano ajustado a "zonas estables" se lo comería en parte.
    filas = cols = 40
    fechas = fechas_mensuales(date(2023, 1, 15), 18)
    yy, xx = np.mgrid[0:filas, 0:cols]
    amplitud = np.full((filas, cols), 1.0)
    velocidad = np.full((filas, cols), -1.0)
    amplitud += 12.0 * np.exp(-((xx - 30) ** 2 + (yy - 22) ** 2) / (2 * 2.5**2))
    amplitud[4:8, 4:8] = 0.0
    velocidad[4:8, 4:8] = 0.0
    serie = _serie_desplazamiento(fechas, amplitud, velocidad)
    pares = [(i, i + 1) for i in range(len(fechas) - 1)] + [(i, i + 3) for i in range(len(fechas) - 3)]
    observaciones, coherencias = [], []
    for i, j in pares:
        campo = serie[j] - serie[i]
        campo = campo + 0.5 + 0.15 * xx - 0.1 * yy + rng.normal(0, 0.4, campo.shape)
        observaciones.append(campo)
        coh = np.full(campo.shape, 0.7)
        coh[:2, :] = 0.2
        coherencias.append(coh)
    cfg = {
        "procesado": {"coherencia_min": 0.4, "coherencia_zona_estable": 0.5, "min_ecuaciones_red": 8},
        "validacion": {"meses_riego": [4, 5, 6]},
    }
    resultado = procesar_observaciones(
        observaciones,
        coherencias,
        [(fechas[i], fechas[j]) for i, j in pares],
        fechas,
        fila_ref=6,
        col_ref=6,
        cfg=cfg,
    )
    hundimiento = hundimiento_estacional(fechas, resultado["serie_mm"])
    verdadero = hundimiento_estacional(fechas, serie - serie[0])
    assert hundimiento[22, 30] == pytest.approx(verdadero[22, 30], abs=2.0)
    assert hundimiento[6, 6] == pytest.approx(0.0, abs=2.0)
    assert np.isnan(hundimiento[0, 0])


def test_componentes_conexas_nulas_se_enmascaran():
    campo = np.ones((4, 4))
    coh = np.full((4, 4), 0.9)
    componentes = np.ones((4, 4))
    componentes[0, 0] = 0
    salida = preparar_interferograma(campo, coh, componentes, 0.4, 0.5, 2, 2)
    assert np.isnan(salida[0, 0])
    assert np.isfinite(salida[3, 3])
