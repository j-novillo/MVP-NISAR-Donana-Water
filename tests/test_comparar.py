"""Tests del comparador NISAR vs S1 (fórmulas, sin red)."""
from comparar_nisar_s1 import _mejora, _solape, MetricasProducto


def test_mejora_mayor_mejor():
    out = _mejora(0.4, 0.5, mayor_mejor=True)
    assert out["estado"] == "ok"
    assert abs(out["mejora_pct"] - 25.0) < 1e-9


def test_mejora_menor_mejor():
    out = _mejora(4.0, 3.0, mayor_mejor=False)
    assert out["estado"] == "ok"
    assert abs(out["mejora_pct"] - 25.0) < 1e-9


def test_mejora_sin_datos():
    out = _mejora(None, 1.0, mayor_mejor=True)
    assert out["estado"] == "no_calculable"
    assert out["mejora_pct"] is None


def test_solape_ausente():
    a = MetricasProducto("S1", 1, "2022-01-01", "2024-01-01", None, None, None, None, 0, 0, [])
    b = MetricasProducto("NISAR", 1, "2025-10-01", "2026-01-01", None, None, None, None, 0, 0, [])
    s = _solape(a, b)
    assert s["hay_solape"] is False


def test_solape_presente():
    a = MetricasProducto("S1", 1, "2025-10-01", "2026-06-01", None, None, None, None, 0, 0, [])
    b = MetricasProducto("NISAR", 1, "2025-11-01", "2026-02-01", None, None, None, None, 0, 0, [])
    s = _solape(a, b)
    assert s["hay_solape"] is True
    assert s["inicio"] == "2025-11-01"
    assert s["fin"] == "2026-02-01"
