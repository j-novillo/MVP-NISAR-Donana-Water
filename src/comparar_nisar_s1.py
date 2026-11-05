#!/usr/bin/env python3
"""Compara NISAR GUNW frente a Sentinel-1 sobre el mismo AOI.

La única mejora que este módulo puede marcar como evaluable es

    100 * (err_S1 - err_NISAR) / err_S1

y solo si el error existe, el baseline de S1 es > 0 y la comparabilidad
del protocolo está completa (solape de pares, máscara común, CRS leído,
signo anclado, incidencia, n, incertidumbre). Si falta algo, el estado es
`no_evaluable` y el porcentaje es null.

Coherencia, fracción usable y la dispersión espacial urbana se conservan
como cifras exploratorias, sin porcentaje. El nivel piezométrico no es
desplazamiento. EGMS proviene de Sentinel-1 y no es verdad independiente.
El RMSE de exactitud, cuando llegue a ser evaluable, es el GNSS en LOS.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np
from rasterio.warp import Resampling, reproject
from rasterio.transform import from_bounds

from comparacion_protocolo import (
    ADVERTENCIA_DISPERSION,
    ADVERTENCIA_EGMS,
    ADVERTENCIA_GNSS,
    ADVERTENCIA_LEGAL,
    ADVERTENCIA_PIEZO,
    ESTADO_NO,
    exploratorio,
    mejora_error,
    motivo_comparabilidad,
    nota_primer_gunw,
    papel_referencia,
    solape_de_pares,
    checklist_comparabilidad,
)
from lectura_gunw import (
    cargar_interferograma,
    desplazamiento_mm,
    listar_interferogramas,
)
from utilidades import (
    asegurar_directorio,
    a_metrico,
    cargar_config,
    guardar_json,
    resolver_aoi,
    ruta_proyecto,
)

log = logging.getLogger("poc.comparar")

ONDA_S1 = 0.05546576
ONDA_NISAR = 0.238403


@dataclass
class MetricasProducto:
    plataforma: str
    n_interferogramas: int
    fechas_min: str | None
    fechas_max: str | None
    coherencia_media: float | None
    coherencia_mediana: float | None
    fraccion_usable: float | None
    ruido_std_mm_zona_estable: float | None
    n_pixeles_aoi: int
    n_pixeles_zona_estable: int
    notas: list[str]
    intervalos: list | None = None
    crs_leidos: list | None = None
    dispersion_espacial_urbana_mm: float | None = None


def _es_nisar(ruta: Path) -> bool:
    return ruta.name.upper().startswith("NISAR") or "NISAR" in ruta.name.upper()


def _es_s1(ruta: Path) -> bool:
    n = ruta.name.upper()
    return n.startswith("S1") or "SENTINEL" in n or "HYP3" in n


def _onda(ruta: Path, cfg_onda: float) -> float:
    if _es_nisar(ruta):
        return ONDA_NISAR
    if _es_s1(ruta):
        return ONDA_S1
    return cfg_onda


def _clip_aoi(fase, coh, transform, crs, aoi, resolucion_m: float = 80.0):
    """Recorta/reproyecta un par fase+coh al bbox métrico del AOI."""
    dst_crs = aoi.crs
    width = max(2, int(np.ceil((aoi.xmax - aoi.xmin) / resolucion_m)))
    height = max(2, int(np.ceil((aoi.ymax - aoi.ymin) / resolucion_m)))
    dst_transform = from_bounds(aoi.xmin, aoi.ymin, aoi.xmax, aoi.ymax, width, height)
    fase_out = np.full((height, width), np.nan, dtype=np.float64)
    coh_out = np.full((height, width), np.nan, dtype=np.float64)
    reproject(
        source=np.asarray(fase, dtype=np.float64),
        destination=fase_out,
        src_transform=transform,
        src_crs=crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    reproject(
        source=np.asarray(coh, dtype=np.float64),
        destination=coh_out,
        src_transform=transform,
        src_crs=crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.bilinear,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )
    return fase_out, coh_out, dst_transform


def _mascara_urbana(shape, transform, ref_x, ref_y, radio_m: float = 250.0):
    """Disco alrededor del punto de referencia (casco urbano)."""
    filas, cols = np.indices(shape)
    xs = transform.c + (cols + 0.5) * transform.a
    ys = transform.f + (filas + 0.5) * transform.e
    dist = np.hypot(xs - ref_x, ys - ref_y)
    return dist <= radio_m


def _metricas_lista(
    rutas: list[Path],
    etiqueta: str,
    cfg: dict,
    aoi,
    umbral_coh: float,
) -> MetricasProducto:
    notas: list[str] = []
    if not rutas:
        return MetricasProducto(
            plataforma=etiqueta,
            n_interferogramas=0,
            fechas_min=None,
            fechas_max=None,
            coherencia_media=None,
            coherencia_mediana=None,
            fraccion_usable=None,
            ruido_std_mm_zona_estable=None,
            n_pixeles_aoi=0,
            n_pixeles_zona_estable=0,
            notas=["sin productos"],
        )

    signo = float(cfg["procesado"]["signo_fase"])
    ref_xy = a_metrico(cfg["referencia"]["lon"], cfg["referencia"]["lat"], cfg["crs_metrico"])

    cohs = []
    ruidos = []
    fechas = []
    intervalos = []
    crs_leidos = []
    n_pix = 0
    n_est = 0

    for ruta in rutas:
        try:
            ifg = cargar_interferograma(ruta, _onda(ruta, float(cfg["procesado"]["longitud_onda_m"])))
        except Exception as exc:
            notas.append(f"{ruta.name}: {exc.__class__.__name__}: {exc}")
            continue
        # Asegura onda correcta aunque el sidecar falte
        onda = _onda(ruta, ifg.longitud_onda_m)
        fase, coh, transform = ifg.fase_rad, ifg.coherencia, ifg.transform
        fase_c, coh_c, transform_c = _clip_aoi(fase, coh, transform, ifg.crs, aoi)
        finito = np.isfinite(coh_c)
        if not finito.any():
            notas.append(f"{ruta.name}: AOI vacío tras el recorte")
            continue
        cohs.append(coh_c[finito])
        n_pix = int(finito.sum())
        disp = desplazamiento_mm(fase_c, onda, signo)
        urbana = _mascara_urbana(disp.shape, transform_c, ref_xy[0], ref_xy[1])
        estable = urbana & finito & (coh_c >= umbral_coh) & np.isfinite(disp)
        n_est = int(estable.sum())
        if n_est >= 5:
            local = disp[estable]
            # Dispersión espacial, no ruido instrumental.
            ruidos.append(float(np.nanstd(local - np.nanmedian(local))))
        fechas.append(ifg.fecha_referencia)
        fechas.append(ifg.fecha_secundaria)
        intervalos.append([ifg.fecha_referencia.isoformat(), ifg.fecha_secundaria.isoformat()])
        crs_leidos.append(bool(getattr(ifg, "crs_leido", False)))

    if not cohs:
        return MetricasProducto(
            plataforma=etiqueta,
            n_interferogramas=len(rutas),
            fechas_min=None,
            fechas_max=None,
            coherencia_media=None,
            coherencia_mediana=None,
            fraccion_usable=None,
            ruido_std_mm_zona_estable=None,
            n_pixeles_aoi=0,
            n_pixeles_zona_estable=0,
            notas=notas or ["ningún interferograma usable en el AOI"],
            intervalos=intervalos,
            crs_leidos=crs_leidos,
        )

    stack = np.concatenate(cohs)
    if ruidos:
        notas.append(ADVERTENCIA_DISPERSION)
    return MetricasProducto(
        plataforma=etiqueta,
        n_interferogramas=len(rutas),
        fechas_min=str(min(fechas)) if fechas else None,
        fechas_max=str(max(fechas)) if fechas else None,
        coherencia_media=float(np.nanmean(stack)),
        coherencia_mediana=float(np.nanmedian(stack)),
        fraccion_usable=float(np.mean(stack >= umbral_coh)),
        ruido_std_mm_zona_estable=float(np.nanmean(ruidos)) if ruidos else None,
        n_pixeles_aoi=n_pix,
        n_pixeles_zona_estable=n_est,
        notas=notas,
        intervalos=intervalos,
        crs_leidos=crs_leidos,
        dispersion_espacial_urbana_mm=float(np.nanmean(ruidos)) if ruidos else None,
    )


def _mejora(valor_s1, valor_nisar, mayor_mejor: bool = False, comparable: bool = False) -> dict:
    """Compatibilidad de tests. La mejora evaluable solo existe para un error.

    `mayor_mejor=True` (coherencia, fracción) no es un error: queda no_evaluable
    aunque los dos valores existan. `mayor_mejor=False` usa
    100*(err_S1-err_NISAR)/err_S1 y exige `comparable`.
    """
    if mayor_mejor:
        out = exploratorio(valor_s1, valor_nisar, "cifra exploratoria; no es un error")
        out["estado"] = ESTADO_NO
        return out
    return mejora_error(valor_s1, valor_nisar, comparable=comparable)


def _rango_fechas(metricas: MetricasProducto) -> tuple[date | None, date | None]:
    if not metricas.fechas_min or not metricas.fechas_max:
        return None, None
    return date.fromisoformat(metricas.fechas_min), date.fromisoformat(metricas.fechas_max)


def _intervalos(metricas: MetricasProducto) -> list[tuple[date, date]]:
    pares = []
    for item in metricas.intervalos or []:
        if not item or len(item) != 2 or not item[0] or not item[1]:
            continue
        a = date.fromisoformat(str(item[0])[:10])
        b = date.fromisoformat(str(item[1])[:10])
        pares.append((min(a, b), max(a, b)))
    return pares


def _solape(a: MetricasProducto, b: MetricasProducto) -> dict:
    """Solape entre pares. El recubrimiento min–max no cuenta como solape."""
    resultado = solape_de_pares(_intervalos(a), _intervalos(b))
    a0, a1 = _rango_fechas(a)
    b0, b1 = _rango_fechas(b)
    resultado["recubrimiento_s1"] = [str(a0), str(a1)] if a0 and a1 else None
    resultado["recubrimiento_nisar"] = [str(b0), str(b1)] if b0 and b1 else None
    if not resultado["hay_solape"] and a0 and b0 and not (a.intervalos or b.intervalos):
        resultado["motivo"] = (
            "solo hay recubrimiento min–max, no intervalos de par; "
            "eso no es solape"
        )
    elif not resultado["hay_solape"] and a0 and b0:
        resultado["motivo"] = (
            f"S1 cubre {a0}–{a1}; NISAR cubre {b0}–{b1}; "
            "ningún par se cruza"
        )
    return resultado


def _buscar_verdad_terreno(cfg: dict) -> dict:
    """Inventario honesto de lo que hay (o no) para exactitud."""
    capas = ruta_proyecto(cfg, "capas")
    gnss_dir = Path(cfg.get("rutas", {}).get("gnss", RAIZ_GNSS(cfg)))
    egms_dir = Path(cfg.get("rutas", {}).get("egms", RAIZ_EGMS(cfg)))
    piezo_pts = capas / "piezometros.gpkg"
    piezo_niv = capas / "piezometros_niveles.csv"
    gnss_series = list(gnss_dir.glob("*.tenv3")) + list(gnss_dir.glob("*.tenv")) + list(gnss_dir.glob("*.csv"))
    # Excluir el catálogo de estaciones
    gnss_series = [p for p in gnss_series if "estacion" not in p.name.lower()]
    egms = list(egms_dir.glob("*.tif")) + list(egms_dir.glob("*.csv")) + list(egms_dir.glob("*.zip"))
    return {
        "piezometros_puntos": piezo_pts.is_file(),
        "piezometros_niveles_csv": piezo_niv.is_file(),
        "gnss_series": [str(p) for p in gnss_series],
        "egms_productos": [str(p) for p in egms],
        "gnss_catalogo": str(gnss_dir / "estaciones_cercanas.csv")
        if (gnss_dir / "estaciones_cercanas.csv").is_file()
        else None,
    }


def RAIZ_GNSS(cfg) -> Path:
    return ruta_proyecto(cfg, "interferogramas").parent / "gnss"


def RAIZ_EGMS(cfg) -> Path:
    return ruta_proyecto(cfg, "interferogramas").parent / "egms"


def bloque_referencia(nombre: str, motivos_extra: list[str]) -> dict:
    clave = {
        "rmse_gnss_los": "gnss_los",
        "correlacion_piezometros": "piezometria",
        "rmse_egms": "egms",
    }[nombre]
    papel = papel_referencia(clave)
    return {
        "estado": ESTADO_NO,
        "mejora_pct": None,
        "definicion": FORMULA if papel["puede_entrar_en_rmse"] else None,
        "papel": papel,
        "motivos": [papel["texto"], *motivos_extra],
    }


FORMULA = "100*(err_S1-err_NISAR)/err_S1"


def exactitud_no_calculable(solape: dict, verdad: dict, checklist: dict) -> dict:
    motivos = []
    if not solape.get("hay_solape"):
        motivos.append(solape.get("motivo", "sin solape de pares S1–NISAR"))
    if checklist and not checklist.get("comparable"):
        motivos.append(motivo_comparabilidad(checklist))
    if not verdad["gnss_series"]:
        motivos.append(
            "no hay series GNSS en LOS (hace falta ENU más azimut e incidencia; "
            "el catálogo de estaciones no es una serie)"
        )
    if not verdad["piezometros_niveles_csv"]:
        motivos.append("no hay serie de niveles; aunque la hubiera, no mide desplazamiento")
    if not verdad["egms_productos"]:
        motivos.append("no hay producto EGMS local; aunque lo hubiera, no es independiente de S1")
    return {
        "rmse_gnss_los": bloque_referencia("rmse_gnss_los", motivos),
        "correlacion_piezometros": bloque_referencia("correlacion_piezometros", motivos),
        "rmse_egms": bloque_referencia("rmse_egms", motivos),
    }


def comparar(cfg: dict) -> dict:
    aoi = resolver_aoi(cfg)
    umbral = float(cfg["procesado"]["coherencia_min"])
    carpeta = ruta_proyecto(cfg, "interferogramas")
    todos = listar_interferogramas(carpeta)
    nisar = [p for p in todos if _es_nisar(p)]
    s1 = [p for p in todos if _es_s1(p) and p.suffix.lower() in {".tif", ".tiff"}]
    # Evita los GeoTIFF sintéticos vacíos si coexistieran con HyP3 reales:
    # se quedan todos los S1_*.tif presentes.

    m_s1 = _metricas_lista(s1, "SENTINEL-1", cfg, aoi, umbral)
    m_nisar = _metricas_lista(nisar, "NISAR", cfg, aoi, umbral)
    solape = _solape(m_s1, m_nisar)
    verdad = _buscar_verdad_terreno(cfg)
    signo_anclado = bool(cfg.get("comparacion", {}).get("signo_fase_anclado", False))
    checklist = checklist_comparabilidad(
        hay_solape=bool(solape.get("hay_solape")),
        misma_zona=True,
        mascara_comun=False,
        resolucion_comparable=False,
        referencia_comun=True,
        unidades_los_mm=True,
        los_incidencia_registrada=False,
        estacion_o_intervalo_comun=bool(solape.get("hay_solape")),
        n_s1=m_s1.n_interferogramas,
        n_nisar=m_nisar.n_interferogramas,
        incertidumbre_reportada=False,
        crs_leido_s1=bool(m_s1.crs_leidos) and all(m_s1.crs_leidos),
        crs_leido_nisar=bool(m_nisar.crs_leidos) and all(m_nisar.crs_leidos),
        signo_fase_anclado=signo_anclado,
    )
    motivo = motivo_comparabilidad(checklist)
    mejoras = {
        "coherencia_media": exploratorio(
            m_s1.coherencia_media,
            m_nisar.coherencia_media,
            "coherencia media exploratoria; no es un error",
        ),
        "fraccion_usable": exploratorio(
            m_s1.fraccion_usable,
            m_nisar.fraccion_usable,
            "fracción usable exploratoria, en la cobertura nativa de cada sensor",
        ),
        "dispersion_espacial_urbana_mm": exploratorio(
            m_s1.dispersion_espacial_urbana_mm,
            m_nisar.dispersion_espacial_urbana_mm,
            ADVERTENCIA_DISPERSION,
        ),
        "rmse_gnss_los": mejora_error(None, None, comparable=checklist["comparable"], motivo_comparabilidad=motivo),
    }
    exactitud = exactitud_no_calculable(solape, verdad, checklist)

    resumen = {
        "estado_comparacion": "evaluable" if checklist["comparable"] else ESTADO_NO,
        "porcentaje_global": None,
        "aoi": aoi.nombre,
        "umbral_coherencia": umbral,
        "solape_temporal": solape,
        "comparabilidad": checklist,
        "sentinel1": asdict(m_s1),
        "nisar": asdict(m_nisar),
        "exploratorio": mejoras,
        "mejora_producto_calidad": {
            clave: {"estado": ESTADO_NO, "mejora_pct": None, "motivo": bloque.get("motivo")}
            for clave, bloque in mejoras.items()
        },
        "mejora_exactitud_vs_verdad": exactitud,
        "verdad_terreno_disponible": verdad,
        "primer_gunw_documentado": nota_primer_gunw(),
        "advertencias": [
            ADVERTENCIA_LEGAL,
            ADVERTENCIA_DISPERSION,
            ADVERTENCIA_PIEZO,
            ADVERTENCIA_EGMS,
            ADVERTENCIA_GNSS,
            "NISAR es banda L (λ≈0,24 m); Sentinel-1 es banda C (λ≈0,055 m). No se invierten juntas.",
            "No hay un porcentaje único de mejora.",
        ],
    }
    return resumen


def _markdown(resumen: dict) -> str:
    s1 = resumen["sentinel1"]
    ni = resumen["nisar"]
    sol = resumen["solape_temporal"]
    lineas = [
        "# Comparación NISAR vs Sentinel-1",
        "",
        f"Estado: **{resumen.get('estado_comparacion', ESTADO_NO)}**. "
        "No hay porcentaje global.",
        "",
        f"AOI: `{resumen['aoi']}` · umbral de coherencia: {resumen['umbral_coherencia']}",
        "",
        "## Solape temporal de pares",
        "",
        f"- ¿Hay solape de pares? **{sol.get('hay_solape')}**",
    ]
    if sol.get("hay_solape"):
        lineas.append(
            f"- Pares que se cruzan: S1 {sol.get('n_pares_s1_en_solape')}, "
            f"NISAR {sol.get('n_pares_nisar_en_solape')}"
        )
    else:
        lineas.append(f"- Motivo: {sol.get('motivo')}")
    lineas += [
        "",
        "## Cifras exploratorias (sin porcentaje de mejora)",
        "",
        "| Métrica | Sentinel-1 | NISAR | Mejora |",
        "|---|---:|---:|---|",
    ]
    etiquetas = [
        ("coherencia_media", "Coherencia media"),
        ("fraccion_usable", "Fracción usable (cobertura nativa)"),
        ("dispersion_espacial_urbana_mm", "Dispersión espacial urbana (mm)"),
    ]
    expl = resumen.get("exploratorio", {})
    for clave, nombre in etiquetas:
        bloque = expl.get(clave, {})
        lineas.append(
            f"| {nombre} | {_fmt(bloque.get('valor_s1'))} | {_fmt(bloque.get('valor_nisar'))} | no_evaluable |"
        )
    lineas += [
        "",
        f"S1: {s1.get('n_interferogramas')} ifg, {s1.get('fechas_min')} → {s1.get('fechas_max')}",
        f"NISAR: {ni.get('n_interferogramas')} ifg, {ni.get('fechas_min')} → {ni.get('fechas_max')}",
        "",
        "## Exactitud frente a verdad de terreno",
        "",
    ]
    for nombre, bloque in resumen["mejora_exactitud_vs_verdad"].items():
        if not isinstance(bloque, dict):
            continue
        lineas.append(f"### {nombre}")
        lineas.append(f"- Estado: **{bloque.get('estado')}**")
        if bloque.get("mejora_pct") is not None:
            lineas.append(f"- Mejora: {bloque['mejora_pct']:.1f} %")
        for m in bloque.get("motivos", []):
            lineas.append(f"- {m}")
        lineas.append("")
    lineas += ["## Advertencias", ""]
    for a in resumen.get("advertencias", []):
        lineas.append(f"- {a}")
    lineas.append("")
    return "\n".join(lineas)


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--salida-json",
        default="data/comparacion/comparacion-nisar-s1.json",
        help="No pisa docs/comparacion-nisar-s1.json (instantánea ya etiquetada).",
    )
    parser.add_argument(
        "--salida-md",
        default="data/comparacion/comparacion-nisar-s1.md",
    )
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    resumen = comparar(cfg)
    raiz = Path(__file__).resolve().parents[1]
    out_json = raiz / args.salida_json
    out_md = raiz / args.salida_md
    asegurar_directorio(out_json.parent)
    guardar_json(out_json, resumen)
    out_md.write_text(_markdown(resumen), encoding="utf-8")
    log.info("JSON → %s", out_json)
    log.info("MD   → %s", out_md)
    log.info("Estado: %s", resumen["estado_comparacion"])
    for k, v in resumen["mejora_exactitud_vs_verdad"].items():
        if isinstance(v, dict):
            log.info("%s: %s", k, v.get("estado"))


if __name__ == "__main__":
    main()
