#!/usr/bin/env python3
"""Compara NISAR GUNW frente a Sentinel-1 (HyP3) sobre el mismo AOI.

Métricas (todas se calculan solo si hay datos suficientes; si falta algo se
declara explícitamente `no_calculable` con el motivo):

1. Coherencia media y fracción de píxeles usables (coh >= umbral) en el AOI.
2. Ruido: desviación típica del desplazamiento LOS (mm) en una zona urbana
   de referencia (casco de Rociana) tras quitar la mediana local.
3. Exactitud frente a verdad de terreno, solo si hay solape temporal:
   - RMSE frente a GNSS proyectado a LOS (si existen series en data/raw/gnss/).
   - Correlación con cambios de nivel piezométrico (si existe
     data/raw/capas/piezometros_niveles.csv).
   - RMSE frente a EGMS Ortho (si hay GeoTIFF/CSV en data/raw/egms/).

Porcentaje de mejora de NISAR respecto a S1 (cuando ambas cifras existen):

    mejora_% = 100 * (metric_S1 - metric_NISAR) / metric_S1

para métricas "menor es mejor" (ruido, RMSE). Para coherencia y fracción
usable ("mayor es mejor"):

    mejora_% = 100 * (metric_NISAR - metric_S1) / metric_S1

No inventa solapes ni verdades de terreno: si NISAR y S1 no comparten fechas,
las métricas de exactitud quedan `no_calculable`.
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
            ruidos.append(float(np.nanstd(local - np.nanmedian(local))))
        fechas.append(ifg.fecha_referencia)
        fechas.append(ifg.fecha_secundaria)

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
        )

    stack = np.concatenate(cohs)
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
    )


def _mejora(valor_s1, valor_nisar, mayor_mejor: bool) -> dict:
    if valor_s1 is None or valor_nisar is None:
        return {
            "mejora_pct": None,
            "definicion": None,
            "estado": "no_calculable",
            "motivo": "falta métrica en S1 o NISAR",
        }
    if valor_s1 == 0:
        return {
            "mejora_pct": None,
            "definicion": None,
            "estado": "no_calculable",
            "motivo": "denominador S1 = 0",
        }
    if mayor_mejor:
        mejora = 100.0 * (valor_nisar - valor_s1) / valor_s1
        definicion = "100*(NISAR-S1)/S1  (mayor es mejor)"
    else:
        mejora = 100.0 * (valor_s1 - valor_nisar) / valor_s1
        definicion = "100*(S1-NISAR)/S1  (menor es mejor)"
    return {
        "mejora_pct": float(mejora),
        "definicion": definicion,
        "valor_s1": float(valor_s1),
        "valor_nisar": float(valor_nisar),
        "estado": "ok",
    }


def _rango_fechas(metricas: MetricasProducto) -> tuple[date | None, date | None]:
    if not metricas.fechas_min or not metricas.fechas_max:
        return None, None
    return date.fromisoformat(metricas.fechas_min), date.fromisoformat(metricas.fechas_max)


def _solape(a: MetricasProducto, b: MetricasProducto) -> dict:
    a0, a1 = _rango_fechas(a)
    b0, b1 = _rango_fechas(b)
    if None in (a0, a1, b0, b1):
        return {"hay_solape": False, "motivo": "faltan fechas en S1 o NISAR"}
    ini = max(a0, b0)
    fin = min(a1, b1)
    if ini <= fin:
        return {
            "hay_solape": True,
            "inicio": str(ini),
            "fin": str(fin),
            "dias": (fin - ini).days + 1,
        }
    return {
        "hay_solape": False,
        "motivo": (
            f"S1 cubre {a0}–{a1}; NISAR cubre {b0}–{b1}; "
            "no hay fechas en común"
        ),
        "s1": [str(a0), str(a1)],
        "nisar": [str(b0), str(b1)],
    }


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


def exactitud_no_calculable(solape: dict, verdad: dict) -> dict:
    motivos = []
    if not solape.get("hay_solape"):
        motivos.append(solape.get("motivo", "sin solape temporal S1–NISAR"))
    if not verdad["gnss_series"]:
        motivos.append(
            "no hay series GNSS descargables (NGL tenv3 404; hace falta RINEX "
            "de RAP/IGN procesado a ENU/LOS)"
        )
    if not verdad["piezometros_niveles_csv"]:
        motivos.append(
            "no hay piezometros_niveles.csv (la CHG solo ofrece series por "
            "visor web, sin API CSV estable)"
        )
    if not verdad["egms_productos"]:
        motivos.append(
            "no hay productos EGMS locales (API archive exige login CLMS)"
        )
    return {
        "rmse_gnss_los": {
            "estado": "no_calculable",
            "mejora_pct": None,
            "motivos": motivos,
        },
        "correlacion_piezometros": {
            "estado": "no_calculable",
            "mejora_pct": None,
            "motivos": motivos,
        },
        "rmse_egms": {
            "estado": "no_calculable",
            "mejora_pct": None,
            "motivos": motivos,
        },
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

    mejoras = {
        "coherencia_media": _mejora(m_s1.coherencia_media, m_nisar.coherencia_media, mayor_mejor=True),
        "fraccion_usable": _mejora(m_s1.fraccion_usable, m_nisar.fraccion_usable, mayor_mejor=True),
        "ruido_std_mm_zona_estable": _mejora(
            m_s1.ruido_std_mm_zona_estable,
            m_nisar.ruido_std_mm_zona_estable,
            mayor_mejor=False,
        ),
    }
    exactitud = exactitud_no_calculable(solape, verdad)
    if solape.get("hay_solape") and (verdad["gnss_series"] or verdad["piezometros_niveles_csv"] or verdad["egms_productos"]):
        # Reservado: cuando existan series coetáneas se calcularán aquí.
        # No se rellena con cifras inventadas.
        exactitud["nota"] = (
            "Hay solape y alguna verdad de terreno en disco; amplíe este "
            "bloque con RMSE/correlación reales antes de citar un %."
        )

    resumen = {
        "aoi": aoi.nombre,
        "umbral_coherencia": umbral,
        "solape_temporal": solape,
        "sentinel1": asdict(m_s1),
        "nisar": asdict(m_nisar),
        "mejora_producto_calidad": mejoras,
        "mejora_exactitud_vs_verdad": exactitud,
        "verdad_terreno_disponible": verdad,
        "advertencias": [
            "Las métricas de coherencia/ruido comparan productos sobre el mismo "
            "AOI; si no hay solape temporal, NO son una validación coetánea.",
            "NISAR es banda L (λ≈0.24 m); Sentinel-1 es banda C (λ≈0.055 m).",
            "No mezclar ambas plataformas en la misma inversión SBAS.",
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
        f"AOI: `{resumen['aoi']}` · umbral de coherencia: {resumen['umbral_coherencia']}",
        "",
        "## Solape temporal",
        "",
        f"- ¿Hay solape? **{sol.get('hay_solape')}**",
    ]
    if sol.get("hay_solape"):
        lineas.append(f"- Ventana: {sol['inicio']} → {sol['fin']} ({sol['dias']} días)")
    else:
        lineas.append(f"- Motivo: {sol.get('motivo')}")
    lineas += [
        "",
        "## Métricas de producto (mismo AOI)",
        "",
        "| Métrica | Sentinel-1 | NISAR | Mejora NISAR vs S1 | Definición |",
        "|---|---:|---:|---:|---|",
    ]
    etiquetas = [
        ("coherencia_media", "Coherencia media", True),
        ("fraccion_usable", "Fracción píxeles usables", True),
        ("ruido_std_mm_zona_estable", "Ruido std zona estable (mm)", False),
    ]
    mej = resumen["mejora_producto_calidad"]
    for clave, nombre, _ in etiquetas:
        v_s1 = s1.get(clave)
        v_ni = ni.get(clave)
        m = mej.get(clave, {})
        pct = m.get("mejora_pct")
        pct_txt = f"{pct:.1f} %" if isinstance(pct, (int, float)) else "no calculable"
        defn = m.get("definicion") or m.get("motivo") or "—"
        lineas.append(
            f"| {nombre} | {_fmt(v_s1)} | {_fmt(v_ni)} | {pct_txt} | {defn} |"
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
        default="docs/comparacion-nisar-s1.json",
        help="Ruta relativa a la raíz del repo",
    )
    parser.add_argument(
        "--salida-md",
        default="docs/12-comparacion-nisar-s1.md",
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
    for k, v in resumen["mejora_producto_calidad"].items():
        log.info("%s: %s", k, v.get("mejora_pct") if v.get("estado") == "ok" else v.get("motivo"))


if __name__ == "__main__":
    main()
