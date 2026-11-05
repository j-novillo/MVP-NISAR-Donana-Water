"""Figuras de control: mapas de la malla y una serie temporal de ejemplo.

Salen en `data/figuras/` (gitignorado) y, si se llama `copiar_a_docs`, también
en `docs/figuras/` para el README. Matplotlib en backend Agg, sin ventana.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from medir import ajuste_estacional
from utilidades import asegurar_directorio, parsear_fecha, ruta_proyecto


def _plano(tabla, columna: str, filas: int, cols: int) -> np.ndarray:
    plano = np.full((filas, cols), np.nan)
    plano[tabla["fila"].to_numpy(), tabla["columna"].to_numpy()] = tabla[columna].to_numpy()
    return plano


def guardar_figuras(cfg: dict, celdas, parcelas, informe: dict) -> list[Path]:
    """Dibuja z-score, amplitud, serie de la parcela de mayor score y el semáforo."""
    destino = asegurar_directorio(ruta_proyecto(cfg, "figuras"))
    if "fila" not in celdas.columns:
        return []
    filas = int(celdas["fila"].max()) + 1
    cols = int(celdas["columna"].max()) + 1
    rutas = []
    rutas.append(_mapa(destino / "zscore.png", _plano(celdas, "zscore", filas, cols),
                       "Z-score del hundimiento estacional", "RdBu_r", -4, 4))
    rutas.append(_mapa(destino / "amplitud_estacional.png",
                       _plano(celdas, "amplitud_estacional_mm", filas, cols),
                       "Amplitud estacional (mm)", "YlOrRd", None, None))
    serie_png = _serie_parcela(cfg, destino / "serie_parcela.png", parcelas)
    if serie_png:
        rutas.append(serie_png)
    rutas.append(_semaforo(destino / "go_nogo.png", informe))
    return rutas


def _mapa(ruta: Path, plano: np.ndarray, titulo: str, cmap: str, vmin, vmax) -> Path:
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    imagen = ax.imshow(plano, cmap=cmap, vmin=vmin, vmax=vmax, origin="upper")
    fig.colorbar(imagen, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title(titulo)
    ax.set_xlabel("columna (100 m)")
    ax.set_ylabel("fila (100 m, norte arriba)")
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)
    return ruta


def _serie_parcela(cfg: dict, ruta: Path, parcelas) -> Path | None:
    npz_ruta = ruta_proyecto(cfg, "procesado") / "serie_malla100.npz"
    if parcelas is None or parcelas.empty or not npz_ruta.is_file():
        return None
    if "score" not in parcelas.columns or parcelas["score"].isna().all():
        return None
    npz = np.load(npz_ruta)
    fechas = [parsear_fecha(f) for f in npz["fechas"]]
    serie = npz["serie_mm"]
    # La parcela de mayor score y, si existe, una dentro de la SAR para comparar.
    mejor = parcelas.sort_values("score", ascending=False).iloc[0]
    dentro = parcelas[parcelas.get("dentro_sar", False) == True] if "dentro_sar" in parcelas.columns else parcelas.iloc[0:0]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for etiqueta, fila_parcela, color in (
        (f"mayor score ({mejor['id_parcela']})", mejor, "#b2182b"),
        ("dentro de SAR", dentro.sort_values("score").iloc[0] if len(dentro) else None, "#2166ac"),
    ):
        if fila_parcela is None:
            continue
        curva = _curva_parcela(cfg, fila_parcela, serie, fechas, celdas_crs=parcelas.crs)
        if curva is None:
            continue
        ax.plot(fechas, curva, color=color, label=etiqueta, lw=1.8)
        v, a, _, coef = ajuste_estacional(fechas, curva.reshape(-1, 1), min_fechas=6)
        del v, a
        if np.isfinite(coef).all():
            t = np.array([(f - fechas[0]).days / 365.25 for f in fechas])
            ajuste = coef[0, 0] + coef[1, 0] * t + coef[2, 0] * np.sin(2 * np.pi * t) + coef[3, 0] * np.cos(2 * np.pi * t)
            ax.plot(fechas, ajuste, color=color, ls="--", lw=1.0, alpha=0.8)
    _sombrear_campana(ax, fechas)
    ax.axhline(0, color="0.5", lw=0.6)
    ax.set_ylabel("Desplazamiento LOS (mm)")
    ax.set_title("Serie en la parcela (positivo = hacia el satélite)")
    ax.legend(loc="best", fontsize=8)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)
    return ruta


def _curva_parcela(cfg, parcela, serie, fechas, celdas_crs):
    """Media de las celdas de 100 m cuyo centro cae en la parcela."""
    import geopandas as gpd
    from shapely.geometry import box

    celdas = gpd.read_parquet(ruta_proyecto(cfg, "resultados"))
    if celdas.crs != celdas_crs:
        celdas = celdas.to_crs(celdas_crs)
    geom = parcela.geometry
    dentro = celdas[celdas.geometry.centroid.within(geom)]
    if dentro.empty:
        return None
    curvas = serie[:, dentro["fila"].to_numpy(), dentro["columna"].to_numpy()]
    with np.errstate(all="ignore"):
        return np.nanmean(curvas, axis=1)


def _sombrear_campana(ax, fechas):
    """Sombrea octubre-junio, la campaña de fresa, en cada año de la serie."""
    if not fechas:
        return
    anios = range(fechas[0].year - 1, fechas[-1].year + 1)
    from datetime import date

    for anio in anios:
        inicio = date(anio, 10, 1)
        fin = date(anio + 1, 6, 30)
        ax.axvspan(inicio, fin, color="#fee08b", alpha=0.35, lw=0)


def _semaforo(ruta: Path, informe: dict) -> Path:
    criterios = informe.get("criterios", [])
    colores = {"go": "#1a9850", "no-go": "#d73027", "indeterminado": "#fee08b"}
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    nombres = [c["titulo"] for c in criterios]
    vals = [1] * len(criterios)
    cols = [colores.get(c["resultado"], "0.7") for c in criterios]
    ax.barh(nombres[::-1], vals[::-1], color=cols[::-1])
    for i, criterio in enumerate(criterios[::-1]):
        ax.text(0.02, i, criterio["resultado"], va="center", fontsize=9, color="black")
    ax.set_xlim(0, 1)
    ax.set_xticks([])
    ax.set_title(f"Decisión de la tubería: {informe.get('decision_tuberia', '?')} ({informe.get('alcance', '')})")
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)
    return ruta


def copiar_a_docs(cfg: dict, destino: Path | None = None) -> None:
    """Copia las figuras de control a docs/figuras para el README."""
    import shutil

    origen = ruta_proyecto(cfg, "figuras")
    destino = destino or (Path(__file__).resolve().parents[1] / "docs" / "figuras")
    asegurar_directorio(destino)
    for png in origen.glob("*.png"):
        shutil.copyfile(png, destino / png.name)
