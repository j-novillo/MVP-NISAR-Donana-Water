"""Reglas de los pares controlados. No recomputa los rásteres del box."""

from datetime import date

import pytest

from pares_controlados import (
    diferencia_absoluta_coherencia,
    exigir_ids_unicos,
    id_ventana,
    letra_de_satelite_no_es_orbita,
    orbita_desde_los,
    par_fuera_de_nisar_2025,
    porcentaje_relativo_exploratorio,
)


def test_asc_y_desc_de_la_misma_fecha_no_comparten_id():
    fechas_n = ("20251030", "20251123")
    fechas_s = ("20251029", "20251122")
    a = id_ventana(fechas_n, fechas_s, "Ascending/Right")
    b = id_ventana(fechas_n, fechas_s, "Descending/Right")
    assert a != b
    exigir_ids_unicos([a, b])


def test_el_id_del_box_sin_geometria_choca():
    plano = "NISAR_20251030_20251123__S1_20251029_20251122"
    with pytest.raises(ValueError):
        exigir_ids_unicos([plano, plano])


def test_la_letra_del_satelite_no_es_la_orbita():
    assert letra_de_satelite_no_es_orbita("S1AA_20251029T182645_20251122T182644")
    assert letra_de_satelite_no_es_orbita("S1CC_20251029T063440_20251122T063439")
    assert letra_de_satelite_no_es_orbita("S1DD_20261020T062623_20261101T062623")


def test_orbita_desde_el_vector_los_observado():
    # Vectores del paquete del 5 nov 2026, componente hacia el satélite.
    nisar_left = (0.6853090524673462, 0.2069024294614792, 0.6982427137387441)
    s1_asc_right = (-0.6540950685850881, -0.11305273766822059, 0.7479162568549893)
    s1_desc_right = (0.502138698290467, -0.0976159688876801, 0.8592600860577503)
    assert orbita_desde_los(nisar_left, "Left") == "Ascending"
    assert orbita_desde_los(s1_asc_right, "Right") == "Ascending"
    assert orbita_desde_los(s1_desc_right, "Right") == "Descending"


def test_diferencia_absoluta_de_los_tres_casos_publicados():
    # Cifras del CSV del box. No se promedian.
    casos = [
        (0.5264055132865906, 0.7113759542395502, -0.18497044095295967),
        (0.5340821743011475, 0.45634491037502845, 0.07773726392611902),
        (0.6597662568092346, 0.8914983434047384, -0.23173208659550382),
    ]
    deltas = []
    for nisar, s1, publicado in casos:
        delta = diferencia_absoluta_coherencia(nisar, s1)
        assert delta == pytest.approx(publicado)
        deltas.append(delta)
    assert any(d < 0 for d in deltas) and any(d > 0 for d in deltas)
    rel = porcentaje_relativo_exploratorio(casos[0][0], casos[0][1])
    assert rel == pytest.approx(-26.001784267601533)
    assert rel is not None


def test_el_descendente_de_2026_no_entra_en_nisar_2025():
    assert par_fuera_de_nisar_2025(date(2026, 10, 20), date(2026, 11, 1)) is True
    assert par_fuera_de_nisar_2025(date(2025, 10, 29), date(2025, 11, 22)) is False
