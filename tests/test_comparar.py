"""Tests del protocolo de comparación. Sin red y sin cifras de la corrida real."""

from datetime import date

import numpy as np

from comparacion_protocolo import (
    checklist_comparabilidad,
    crs_declarado_no_se_invalida_por_huso_de_trabajo,
    enu_a_los,
    exploratorio,
    intervalos_se_solapan,
    los_directamente_comparable,
    mascara_comun,
    mejora_error,
    papel_referencia,
    solape_de_pares,
)
from lectura_gunw import longitud_onda_desde_frecuencia
from comparar_nisar_s1 import MetricasProducto, _mejora, _solape
from catalogo_s1_solape import parametros_slc
from descarga_nisar_chunked import alinear_reanudacion
from leer_egms import consulta_archivo
from preparar_hyp3 import cuerpo_jobs, preparar_insar_gamma


def test_mejora_de_error_solo_si_comparable_y_baseline_positivo():
    out = mejora_error(4.0, 3.0, comparable=True)
    assert out["estado"] == "evaluable"
    assert abs(out["mejora_pct"] - 25.0) < 1e-9
    assert out["definicion"] == "100*(err_S1-err_NISAR)/err_S1"


def test_mejora_no_evaluable_sin_comparabilidad_aunque_haya_numeros():
    out = mejora_error(4.0, 3.0, comparable=False, motivo_comparabilidad="sin solape")
    assert out["estado"] == "no_evaluable"
    assert out["mejora_pct"] is None


def test_mejora_no_evaluable_si_baseline_no_es_positivo():
    out = mejora_error(0.0, -1.0, comparable=True)
    assert out["estado"] == "no_evaluable"
    assert out["mejora_pct"] is None


def test_coherencia_no_es_un_error():
    out = _mejora(0.35, 0.52, mayor_mejor=True)
    assert out["estado"] == "no_evaluable"
    assert out["mejora_pct"] is None


def test_exploratorio_no_lleva_porcentaje():
    out = exploratorio(0.35, 0.52, "coherencia")
    assert out["estado"] == "exploratorio"
    assert out["mejora_pct"] is None


def test_solape_de_pares_no_usa_el_min_max():
    # El recubrimiento 2022–2026 solaparía 2025 en un min–max; los pares no.
    s1 = [(date(2022, 1, 6), date(2022, 5, 6)), (date(2024, 5, 19), date(2024, 9, 16))]
    nisar = [(date(2025, 10, 30), date(2025, 11, 23))]
    assert intervalos_se_solapan(date(2022, 1, 1), date(2026, 1, 1), date(2025, 11, 1), date(2025, 11, 20))
    s = solape_de_pares(s1, nisar)
    assert s["hay_solape"] is False


def test_solape_de_un_par_que_si_corta():
    s1 = [(date(2025, 10, 1), date(2025, 12, 1))]
    nisar = [(date(2025, 10, 30), date(2025, 11, 23))]
    s = solape_de_pares(s1, nisar)
    assert s["hay_solape"] is True
    assert s["n_pares_s1_en_solape"] == 1
    assert s["pares"][0]["inicio"] == "2025-10-30"


def test_solape_del_comparador_exige_intervalos():
    a = MetricasProducto("S1", 1, "2025-10-01", "2026-06-01", None, None, None, None, 0, 0, [])
    b = MetricasProducto("NISAR", 1, "2025-11-01", "2026-02-01", None, None, None, None, 0, 0, [])
    assert _solape(a, b)["hay_solape"] is False
    a.intervalos = [["2025-10-01", "2026-06-01"]]
    b.intervalos = [["2025-11-01", "2026-02-01"]]
    assert _solape(a, b)["hay_solape"] is True


def test_checklist_falla_si_n_de_nisar_es_uno():
    c = checklist_comparabilidad(
        hay_solape=True,
        misma_zona=True,
        mascara_comun=True,
        resolucion_comparable=True,
        referencia_comun=True,
        unidades_los_mm=True,
        los_incidencia_registrada=True,
        los_misma_direccion_o_proyeccion=True,
        estacion_o_intervalo_comun=True,
        n_s1=8,
        n_nisar=1,
        incertidumbre_reportada=True,
        crs_leido_s1=True,
        crs_leido_nisar=True,
        signo_fase_anclado=True,
    )
    assert c["comparable"] is False
    assert "n_suficiente" in c["faltan"]


def test_piezometria_y_egms_no_entran_en_el_rmse():
    assert papel_referencia("piezometria")["puede_entrar_en_rmse"] is False
    assert papel_referencia("piezometria")["mide_desplazamiento"] is False
    assert papel_referencia("egms")["independiente_de_s1"] is False
    assert papel_referencia("gnss_los")["puede_entrar_en_rmse"] is True


def test_enu_a_los_vertical_puro():
    # Incidencia 0: solo la componente vertical, positiva hacia el satélite (arriba).
    assert abs(enu_a_los(0.0, 0.0, 0.01, 0.0, 0.0) - 0.01) < 1e-9


def test_mascara_comun_separa_la_cobertura_nativa():
    s1 = np.array([[0.2, np.nan], [0.8, 0.9]])
    nisar = np.array([[0.6, 0.7], [0.8, np.nan]])
    out = mascara_comun(s1, nisar, 0.3)
    assert out["n_pixeles_comunes"] == 2
    assert out["nativa_s1"]["n_pixeles_finitos"] == 3
    assert out["nativa_nisar"]["n_pixeles_finitos"] == 3


def test_consulta_s1_no_descarga():
    params = parametros_slc("POLYGON((0 0,1 0,1 1,0 1,0 0))", "2025-10-01", "2025-12-31", "ASCENDING")
    assert params["processingLevel"] == "SLC"
    assert params["start"] == "2025-10-01"
    assert "url" not in params


def test_job_hyp3_es_el_cuerpo_oficial_y_no_se_envia():
    job = preparar_insar_gamma("REF", "SEC", "nombre")
    cuerpo = cuerpo_jobs([job])
    assert cuerpo["jobs"][0]["job_type"] == "INSAR_GAMMA"
    assert cuerpo["jobs"][0]["job_parameters"]["granules"] == ["REF", "SEC"]
    assert cuerpo["jobs"][0]["job_parameters"]["include_inc_map"] is True


def test_consulta_egms_rechaza_un_bbox_ilegal_y_no_llama_a_la_red():
    q = consulta_archivo(-6.61, 37.27, -6.55, 37.33)
    assert q["levels"] == ["L2B", "L3"]
    assert q["bbox"] == [[-6.61, 37.27], [-6.55, 37.33]]
    try:
        consulta_archivo(0, 0, 6, 1)
    except ValueError:
        pass
    else:
        raise AssertionError("un bbox de más de 5° debería rechazarse")


def test_lambda_observada_no_es_el_hardcode_antiguo():
    onda = longitud_onda_desde_frecuencia(1.229e9)
    assert abs(onda - 0.24393202441008952) < 1e-12
    assert abs(onda - 0.238403) > 0.001


def test_left_y_right_no_son_la_misma_los_aunque_ambos_asciendan():
    out = los_directamente_comparable("Left", "Ascending", "Right", "Ascending")
    assert out["comparable"] is False
    mismo = los_directamente_comparable("Right", "Ascending", "Right", "Ascending")
    assert mismo["comparable"] is True


def test_epsg_32630_no_se_invalida_por_el_huso_29():
    assert crs_declarado_no_se_invalida_por_huso_de_trabajo(32630, True) is True
    assert crs_declarado_no_se_invalida_por_huso_de_trabajo(32630, False) is False


def test_reanudacion_nisar_no_se_pasa_del_total():
    assert alinear_reanudacion(100, 5000) == 0
    assert alinear_reanudacion(1_048_576 + 10, 5_000_000) == 1_048_576
    assert alinear_reanudacion(3_000_000, 2_000_000) == 2_000_000
