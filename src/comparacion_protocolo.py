"""Reglas de la comparación NISAR frente a Sentinel-1.

Una cifra solo entra como mejora si es un error (RMSE u otro residuo
acordado), el baseline de Sentinel-1 es > 0 y la comparabilidad está
completa. La fórmula, y solo esa, es:

    100 * (err_S1 - err_NISAR) / err_S1

No hay un porcentaje global. Coherencia, fracción usable y la desviación
espacial en el casco urbano no son ese error: se conservan como métricas
exploratorias y su mejora queda `no_evaluable`.

La subsidencia no identifica un pozo ni una extracción ilegal. Que falte el
inventario de concesiones no equivale a ilegalidad.
"""

from __future__ import annotations

from datetime import date

import numpy as np

ESTADO_NO = "no_evaluable"
ESTADO_SI = "evaluable"

FORMULA_ERROR = "100*(err_S1-err_NISAR)/err_S1"

# Qué tiene que cumplirse para poder citar una mejora de error.
REQUISITOS = (
    "solape_temporal_de_pares",
    "misma_zona",
    "mascara_comun",
    "resolucion_comparable",
    "referencia_comun",
    "unidades_los_mm",
    "los_incidencia_registrada",
    "los_misma_direccion_o_proyeccion",
    "estacion_o_intervalo_comun",
    "n_suficiente",
    "incertidumbre_reportada",
    "crs_leido_en_ambos",
    "signo_fase_anclado",
)

ADVERTENCIA_LEGAL = (
    "La subsidencia, sola, no detecta un pozo ni demuestra una extracción "
    "ilegal. La ausencia del inventario de concesiones no equivale a ilegalidad: "
    "solo indica que el cruce administrativo no se ha podido hacer."
)

ADVERTENCIA_PIEZO = (
    "El nivel piezométrico no es desplazamiento del terreno. No entra en el "
    "RMSE ni en el porcentaje de mejora."
)

ADVERTENCIA_EGMS = (
    "EGMS se deriva de Sentinel-1. No es verdad de terreno independiente de S1. "
    "Sirve como producto externo de la misma banda C, no como RMSE de exactitud."
)

ADVERTENCIA_GNSS = (
    "El RMSE comparable es el de GNSS proyectado a la línea de visión "
    "(este, norte, arriba, azimut e incidencia). Sin esa proyección el "
    "residuo no es evaluable."
)

ADVERTENCIA_DISPERSION = (
    "La desviación típica espacial en el casco urbano, tras quitar la mediana, "
    "es dispersión espacial. No es ruido instrumental salvo que se demuestre "
    "que la zona es estable y que el residuo no tiene estructura."
)


def mejora_error(
    err_s1: float | None,
    err_nisar: float | None,
    *,
    comparable: bool,
    motivo_comparabilidad: str = "",
) -> dict:
    """Única mejora admitida. `comparable` ya incluye solape y el resto de requisitos."""
    base = {
        "definicion": FORMULA_ERROR,
        "valor_s1": None if err_s1 is None else float(err_s1),
        "valor_nisar": None if err_nisar is None else float(err_nisar),
        "mejora_pct": None,
    }
    if not comparable:
        base["estado"] = ESTADO_NO
        base["motivo"] = motivo_comparabilidad or "comparabilidad incompleta"
        return base
    if err_s1 is None or err_nisar is None or not np.isfinite(err_s1) or not np.isfinite(err_nisar):
        base["estado"] = ESTADO_NO
        base["motivo"] = "falta el error en S1 o en NISAR"
        return base
    if err_s1 <= 0:
        base["estado"] = ESTADO_NO
        base["motivo"] = "baseline de error de S1 no es > 0"
        return base
    base["estado"] = ESTADO_SI
    base["mejora_pct"] = float(100.0 * (err_s1 - err_nisar) / err_s1)
    base["motivo"] = ""
    return base


def exploratorio(valor_s1, valor_nisar, definicion: str) -> dict:
    """Cifra descriptiva. Nunca lleva porcentaje de mejora."""
    return {
        "estado": "exploratorio",
        "mejora_pct": None,
        "definicion": definicion,
        "valor_s1": None if valor_s1 is None else float(valor_s1),
        "valor_nisar": None if valor_nisar is None else float(valor_nisar),
        "motivo": "no es la métrica de error; no se calcula 100*(err_S1-err_NISAR)/err_S1",
    }


def intervalos_se_solapan(a0: date, a1: date, b0: date, b1: date) -> bool:
    """Intersección de dos intervalos cerrados de fechas de adquisición."""
    if a1 < a0 or b1 < b0:
        return False
    return max(a0, b0) <= min(a1, b1)


def solape_de_pares(pares_s1: list[tuple[date, date]], pares_nisar: list[tuple[date, date]]) -> dict:
    """Solape real entre pares, no entre el mínimo y el máximo de cada pila.

    Un stack S1 de 2022 a 2026 no 'solapa' un GUNW de noviembre de 2025 si
    ningún par S1 corta esas dos fechas.
    """
    if not pares_s1 or not pares_nisar:
        return {
            "hay_solape": False,
            "n_pares_s1_en_solape": 0,
            "n_pares_nisar_en_solape": 0,
            "pares": [],
            "motivo": "falta algún par S1 o NISAR",
        }
    cruces = []
    s1_usados = set()
    nisar_usados = set()
    for i, (a0, a1) in enumerate(pares_s1):
        for j, (b0, b1) in enumerate(pares_nisar):
            if intervalos_se_solapan(a0, a1, b0, b1):
                ini = max(a0, b0)
                fin = min(a1, b1)
                cruces.append(
                    {
                        "s1": [a0.isoformat(), a1.isoformat()],
                        "nisar": [b0.isoformat(), b1.isoformat()],
                        "inicio": ini.isoformat(),
                        "fin": fin.isoformat(),
                        "dias": (fin - ini).days + 1,
                    }
                )
                s1_usados.add(i)
                nisar_usados.add(j)
    if not cruces:
        return {
            "hay_solape": False,
            "n_pares_s1_en_solape": 0,
            "n_pares_nisar_en_solape": 0,
            "pares": [],
            "motivo": "ningún intervalo de par S1 corta un intervalo de par NISAR",
        }
    return {
        "hay_solape": True,
        "n_pares_s1_en_solape": len(s1_usados),
        "n_pares_nisar_en_solape": len(nisar_usados),
        "pares": cruces,
        "motivo": "",
    }


def checklist_comparabilidad(
    *,
    hay_solape: bool,
    misma_zona: bool,
    mascara_comun: bool,
    resolucion_comparable: bool,
    referencia_comun: bool,
    unidades_los_mm: bool,
    los_incidencia_registrada: bool,
    los_misma_direccion_o_proyeccion: bool,
    estacion_o_intervalo_comun: bool,
    n_s1: int,
    n_nisar: int,
    incertidumbre_reportada: bool,
    crs_leido_s1: bool,
    crs_leido_nisar: bool,
    signo_fase_anclado: bool,
    n_minimo: int = 3,
) -> dict:
    """Cada requisito es booleano. Uno solo en falso deja la mejora no evaluable."""
    flags = {
        "solape_temporal_de_pares": bool(hay_solape),
        "misma_zona": bool(misma_zona),
        "mascara_comun": bool(mascara_comun),
        "resolucion_comparable": bool(resolucion_comparable),
        "referencia_comun": bool(referencia_comun),
        "unidades_los_mm": bool(unidades_los_mm),
        "los_incidencia_registrada": bool(los_incidencia_registrada),
        "los_misma_direccion_o_proyeccion": bool(los_misma_direccion_o_proyeccion),
        "estacion_o_intervalo_comun": bool(estacion_o_intervalo_comun),
        "n_suficiente": n_s1 >= n_minimo and n_nisar >= n_minimo,
        "incertidumbre_reportada": bool(incertidumbre_reportada),
        "crs_leido_en_ambos": bool(crs_leido_s1 and crs_leido_nisar),
        "signo_fase_anclado": bool(signo_fase_anclado),
    }
    faltan = [k for k in REQUISITOS if not flags[k]]
    return {
        "requisitos": flags,
        "comparable": not faltan,
        "faltan": faltan,
        "n_s1": int(n_s1),
        "n_nisar": int(n_nisar),
        "n_minimo_por_sensor": n_minimo,
    }


def motivo_comparabilidad(checklist: dict) -> str:
    if checklist["comparable"]:
        return ""
    return "comparabilidad incompleta: " + ", ".join(checklist["faltan"])


def estadisticas_mascara(coherencia: np.ndarray, umbral: float) -> dict:
    """Cobertura nativa de un sensor sobre su propia rejilla. No es la máscara común."""
    finito = np.isfinite(coherencia)
    n = int(finito.sum())
    if n == 0:
        return {
            "n_pixeles_finitos": 0,
            "coherencia_media": None,
            "fraccion_usable": None,
        }
    vals = coherencia[finito]
    return {
        "n_pixeles_finitos": n,
        "coherencia_media": float(np.mean(vals)),
        "fraccion_usable": float(np.mean(vals >= umbral)),
    }


def mascara_comun(
    coh_s1: np.ndarray,
    coh_nisar: np.ndarray,
    umbral: float,
) -> dict:
    """Misma rejilla. La intersección es la máscara común; cada sensor conserva la suya."""
    if coh_s1.shape != coh_nisar.shape:
        return {
            "estado": ESTADO_NO,
            "motivo": "las rejillas no coinciden; no hay máscara común",
            "nativa_s1": estadisticas_mascara(coh_s1, umbral),
            "nativa_nisar": estadisticas_mascara(coh_nisar, umbral),
        }
    ambos = np.isfinite(coh_s1) & np.isfinite(coh_nisar)
    n = int(ambos.sum())
    if n == 0:
        return {
            "estado": ESTADO_NO,
            "motivo": "la intersección de píxeles finitos está vacía",
            "n_pixeles_comunes": 0,
            "nativa_s1": estadisticas_mascara(coh_s1, umbral),
            "nativa_nisar": estadisticas_mascara(coh_nisar, umbral),
        }
    return {
        "estado": "calculada",
        "motivo": "",
        "n_pixeles_comunes": n,
        "coherencia_media_s1": float(np.mean(coh_s1[ambos])),
        "coherencia_media_nisar": float(np.mean(coh_nisar[ambos])),
        "fraccion_usable_s1": float(np.mean(coh_s1[ambos] >= umbral)),
        "fraccion_usable_nisar": float(np.mean(coh_nisar[ambos] >= umbral)),
        "nativa_s1": estadisticas_mascara(coh_s1, umbral),
        "nativa_nisar": estadisticas_mascara(coh_nisar, umbral),
    }


def enu_a_los(este_m: float, norte_m: float, arriba_m: float, azimut_deg: float, incidencia_deg: float) -> float:
    """Proyecta un desplazamiento ENU (m) a la línea de visión (m), positivo hacia el satélite.

    azimut: sentido de la trayectoria, grados desde el norte hacia el este.
    incidencia: ángulo entre la vertical y la línea de visión, en grados.
    Sin estos dos ángulos el RMSE GNSS no es evaluable.
    """
    az = np.deg2rad(azimut_deg)
    inc = np.deg2rad(incidencia_deg)
    # Vector unitario del satélite hacia el suelo (range), luego se invierte
    # para que positivo sea hacia el satélite.
    este = np.sin(inc) * np.cos(az)
    norte = np.sin(inc) * (-np.sin(az))
    arriba = -np.cos(inc)
    hacia_suelo = este * este_m + norte * norte_m + arriba * arriba_m
    return float(-hacia_suelo)


def papel_referencia(nombre: str) -> dict:
    """Qué puede y qué no puede demostrar cada fuente."""
    papeles = {
        "gnss_los": {
            "mide_desplazamiento": True,
            "independiente_de_s1": True,
            "puede_entrar_en_rmse": True,
            "texto": ADVERTENCIA_GNSS,
        },
        "piezometria": {
            "mide_desplazamiento": False,
            "independiente_de_s1": True,
            "puede_entrar_en_rmse": False,
            "texto": ADVERTENCIA_PIEZO,
        },
        "egms": {
            "mide_desplazamiento": True,
            "independiente_de_s1": False,
            "puede_entrar_en_rmse": False,
            "texto": ADVERTENCIA_EGMS,
        },
    }
    if nombre not in papeles:
        raise KeyError(nombre)
    return papeles[nombre]


def lado_mira_s1(look_leido: str | None) -> tuple[str, str]:
    """Sentinel-1 IW mira a la derecha por diseño de la misión.

    Si el producto trae el lado, manda el producto. Si no, se anota como
    hecho de misión, no como un campo leído del fichero.
    """
    if look_leido:
        return look_leido, "producto"
    return "Right", "mision"


def los_directamente_comparable(
    look_a: str | None,
    pasa_a: str | None,
    look_b: str | None,
    pasa_b: str | None,
    proyeccion_comun: bool = False,
) -> dict:
    """Ascendente con ascendente no es la misma LOS si un sensor mira a la izquierda y el otro a la derecha.

    NISAR, en los dos GUNW observados, es Ascending/Left. Sentinel-1 IW es right-looking.
    Sin una proyección a un marco común (vertical o ENU) con incidencia y azimut
    de cada geometría, los desplazamientos no se comparan.
    """
    if proyeccion_comun:
        return {
            "comparable": True,
            "motivo": "hay una proyección explícita a un marco común",
        }
    if not look_a or not look_b or not pasa_a or not pasa_b:
        return {
            "comparable": False,
            "motivo": "falta lookDirection u orbitPassDirection en alguno de los dos sensores",
        }
    if look_a.lower() == look_b.lower() and pasa_a.lower() == pasa_b.lower():
        return {"comparable": True, "motivo": "mismo sentido de órbita y mismo lado de mira"}
    return {
        "comparable": False,
        "motivo": (
            f"{pasa_a}/{look_a} y {pasa_b}/{look_b} no comparten la línea de visión. "
            "No se comparan desplazamientos como si fueran la misma dirección."
        ),
    }


def crs_declarado_no_se_invalida_por_huso_de_trabajo(epsg_producto: int | None, leido: bool) -> bool:
    """Un GUNW en EPSG:32630 es utilizable aunque el AOI caiga en el huso 29.

    Se lee el CRS declarado y se reproyecta. Solo es inválido si el fichero
    no trae EPSG.
    """
    return bool(leido and epsg_producto and int(epsg_producto) > 0)


def nota_primer_gunw() -> dict:
    """Metadatos observados de los dos GUNW completos. El signo no se reafirma."""
    return {
        "productos": [
            {
                "nombre": (
                    "NISAR_L2_PR_GUNW_004_015_A_021_006_2000_SH_"
                    "20251030T053143_20251030T053218_"
                    "20251123T053144_20251123T053219_X05010_N_F_J_001"
                ),
                "fechas": ["2025-10-30", "2025-11-23"],
                "separacion_dias": 24,
            },
            {
                "nombre": (
                    "NISAR_L2_PR_GUNW_007_015_A_021_008_2000_SH_"
                    "20251205T053144_20251205T053219_"
                    "20251217T053145_20251217T053220_X05010_N_F_J_001"
                ),
                "fechas": ["2025-12-05", "2025-12-17"],
                "separacion_dias": 12,
            },
        ],
        "fase": (
            "El atributo units de unwrappedPhase en los dos ficheros es radians. "
            "La conversión es d_mm = signo * (λ / 4π) * fase * 1000, con λ = c / 1,229e9 "
            "= 0,2439320244 m. El signo −1 de la configuración sigue sin anclar."
        ),
        "crs": (
            "Los dos HDF5 observados declaran EPSG:32630. Rociana (−6,58°) cae en "
            "el huso 29, y eso no invalida el producto: se lee 32630 y se reproyecta "
            "al CRS de trabajo. El fallback EPSG:25829 solo aparece si el fichero "
            "no trae proyección; en ese caso crs_leido queda en false."
        ),
        "mirada": (
            "Ambos productos declaran Ascending y Left. Sentinel-1 IW mira a la "
            "derecha. Ascendente con ascendente no es la misma línea de visión."
        ),
        "incidencia_aprox_deg": (
            "Aproximación en el punto de referencia, cota 0: 45,72° (30 oct) y "
            "45,71° (5 dic). El dataset incidenceAngle es una rejilla, no ese escalar."
        ),
        "longitud_onda_m": 0.24393202441008952,
        "frecuencia_hz": 1_229_000_000.0,
        "fase_unidades": "radians",
        "posting_m": 80,
        "baseline": (
            "30 oct–23 nov 2025 son 24 días; 5–17 dic 2025 son 12 días. "
            "No se tratan los dos como el vecino nominal de 12 días."
        ),
        "signo_fase": "el valor −1 de la config sigue sin anclar; no se reafirma",
        "estado_frente_a_s1_2022_2024": ESTADO_NO,
        "calidad_nativa": "docs/datos-referencia/nisar_gunw_observado.json",
    }
