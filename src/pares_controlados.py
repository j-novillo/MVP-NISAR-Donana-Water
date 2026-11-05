"""Reglas de la comparación por ventana. No lee rásteres ni inventa porcentajes.

El script del box (`analisis_datos.py`, 5 nov 2026) comparó cada par en su
soporte común y dejó `accuracy_improvement_pct` en null. Dos fallos de ese
script no cambian las cifras ya medidas, pero no deben repetirse:

- el `window_id` no incluye la geometría, así que el ascendente y el
  descendente del 29 oct–22 nov comparten identificador;
- la órbita se deduce de la letra del satélite (`S1AA`, `S1CC`…). Esa letra
  es el satélite de referencia y el secundario, no el sentido de la órbita.

La órbita, si no viene en metadatos, se lee del signo de la componente este
del vector LOS hacia el satélite, conocido el lado de mira. Sentinel-1 IW
mira a la derecha; NISAR, en los productos observados, a la izquierda.
"""

from __future__ import annotations

from datetime import date


def id_ventana(fechas_nisar: tuple[str, str], fechas_s1: tuple[str, str], geometria_s1: str) -> str:
    """Identificador único. La geometría entra porque las fechas solas no bastan."""
    geo = geometria_s1.replace("/", "").replace(" ", "")
    return (
        f"NISAR_{fechas_nisar[0]}_{fechas_nisar[1]}"
        f"__S1_{fechas_s1[0]}_{fechas_s1[1]}__{geo}"
    )


def letra_de_satelite_no_es_orbita(stem: str) -> bool:
    """S1AA / S1CC / S1DD nombran plataformas, no ascendente ni descendente."""
    return len(stem) >= 4 and stem.startswith("S1") and stem[2:4].isalpha()


def orbita_desde_los(los_enu: tuple[float, float, float], lado_mira: str) -> str:
    """Sentido de la órbita a partir del vector hacia el satélite.

    Mira a la derecha y componente este negativa: el satélite está al oeste
    del blanco y la pasada es ascendente (vuelo hacia el norte). Mira a la
    izquierda invierte ese signo. No usa el nombre del fichero.
    """
    este = float(los_enu[0])
    lado = lado_mira.lower()
    if lado.startswith("r"):
        return "Ascending" if este < 0 else "Descending"
    if lado.startswith("l"):
        return "Ascending" if este > 0 else "Descending"
    raise ValueError(f"lado de mira no reconocido: {lado_mira}")


def diferencia_absoluta_coherencia(coh_nisar: float, coh_s1: float) -> float:
    """Diferencia en el soporte común. Negativa: NISAR más bajo que S1.

    Es calidad exploratoria de un par. No es exactitud ni un porcentaje.
    """
    return float(coh_nisar) - float(coh_s1)


def porcentaje_relativo_exploratorio(coh_nisar: float, coh_s1: float) -> float | None:
    """100*(NISAR−S1)/S1 solo como etiqueta exploratoria. No es el RMSE."""
    if coh_s1 is None or coh_s1 <= 0:
        return None
    return 100.0 * (float(coh_nisar) - float(coh_s1)) / float(coh_s1)


def exigir_ids_unicos(identificadores: list[str]) -> None:
    if len(identificadores) != len(set(identificadores)):
        raise ValueError(
            "hay ventanas con el mismo identificador; no se pueden citar como casos distintos"
        )


def par_fuera_de_nisar_2025(inicio: date, fin: date) -> bool:
    """El descendente 20 oct–1 nov 2026 no se compara con los GUNW de 2025."""
    return inicio.year >= 2026 or fin.year >= 2026
