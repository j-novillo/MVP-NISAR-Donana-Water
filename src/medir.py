"""Mediciones sobre la serie de deformación, agregadas a una malla de 100 m.

Por celda:
- velocidad (mm/año) del término lineal de un ajuste conjunto con un seno anual;
- amplitud estacional (mm) de ese seno;
- hundimiento estacional (mm): cuánto más baja está la superficie en mayo que
  en noviembre, promediado entre los años disponibles;
- z-score de ese hundimiento contra el anillo de 1-2 km (la tendencia regional
  del acuífero se va con el anillo; quedan los conos locales);
- coherencia media.

La velocidad que entra en el score es la del ajuste conjunto (recta + seno +
coseno). También se guarda la recta sola, sin términos estacionales, para
poder compararla: en una serie que no cubre años enteros la recta sola se
contamina con el ciclo de la fresa.
"""

from __future__ import annotations

import argparse
import json
import logging
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.transform import Affine
from shapely.geometry import box

from utilidades import (
    a_geografico,
    asegurar_directorio,
    cargar_config,
    indice_fecha_cercana,
    lista_a_afin,
    parsear_fecha,
    ruta_proyecto,
)

log = logging.getLogger("poc.medir")


def agregar_bloques(arr: np.ndarray, factor: int) -> np.ndarray:
    """Media de bloques. La última dimensión espacial se recorta al múltiplo exacto."""
    if factor < 1:
        raise ValueError("El factor de agregación tiene que ser >= 1")
    if factor == 1:
        return arr
    if arr.ndim == 2:
        filas, cols = arr.shape
        nf, nc = filas // factor, cols // factor
        rec = arr[: nf * factor, : nc * factor]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            return np.nanmean(rec.reshape(nf, factor, nc, factor), axis=(1, 3))
    if arr.ndim == 3:
        tiempos, filas, cols = arr.shape
        nf, nc = filas // factor, cols // factor
        rec = arr[:, : nf * factor, : nc * factor]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            return np.nanmean(rec.reshape(tiempos, nf, factor, nc, factor), axis=(2, 4))
    raise ValueError(f"No sé agregar un array de dimensión {arr.ndim}")


def ajuste_estacional(fechas, serie: np.ndarray, min_fechas: int = 8):
    """Ajusta c + v·t + A·sin(2πt) + B·cos(2πt), con t en años desde la primera fecha.

    `serie` es (n_fechas, ...) y puede contener NaN. Devuelve velocidad (mm/año),
    amplitud (mm) = sqrt(A²+B²), velocidad de la recta sola, y los cuatro
    coeficientes en la forma aplanada de los píxeles.
    """
    fechas = [parsear_fecha(f) for f in fechas]
    t0 = fechas[0]
    t = np.array([(f - t0).days / 365.25 for f in fechas], dtype=np.float64)
    angulo = 2.0 * np.pi * t
    diseno = np.column_stack([np.ones_like(t), t, np.sin(angulo), np.cos(angulo)])
    forma = serie.shape
    y = np.asarray(serie, dtype=np.float64).reshape(forma[0], -1)
    n_pix = y.shape[1]
    coef = np.full((4, n_pix), np.nan, dtype=np.float64)
    coef_lineal = np.full((2, n_pix), np.nan, dtype=np.float64)
    completos = np.isfinite(y).all(axis=0) & (np.isfinite(y).sum(axis=0) >= min_fechas)
    if completos.any():
        sol, *_ = np.linalg.lstsq(diseno, y[:, completos], rcond=None)
        coef[:, completos] = sol
        sol_l, *_ = np.linalg.lstsq(diseno[:, :2], y[:, completos], rcond=None)
        coef_lineal[:, completos] = sol_l
    # Píxeles con algún hueco temporal: se resuelven aparte, sin vectorizar.
    parciales = (~completos) & (np.isfinite(y).sum(axis=0) >= min_fechas)
    for p in np.flatnonzero(parciales):
        mascara = np.isfinite(y[:, p])
        sol, *_ = np.linalg.lstsq(diseno[mascara], y[mascara, p], rcond=None)
        coef[:, p] = sol
        sol_l, *_ = np.linalg.lstsq(diseno[mascara, :2], y[mascara, p], rcond=None)
        coef_lineal[:, p] = sol_l
    velocidad = coef[1].reshape(forma[1:])
    amplitud = np.hypot(coef[2], coef[3]).reshape(forma[1:])
    velocidad_lineal = coef_lineal[1].reshape(forma[1:])
    return velocidad, amplitud, velocidad_lineal, coef


def hundimiento_estacional(fechas, serie: np.ndarray, tolerancia_dias: int = 70) -> np.ndarray:
    """Milímetros que la superficie recupera de mayo a noviembre.

    Positivo = mayo más bajo que noviembre (el pico de bombeo y el rebote de
    otoño). Se promedia entre los años que tengan las dos fechas.

    Con stacks trimestrales (p.ej. HyP3 a ~120 días) no hay escena en noviembre:
    se acepta la más cercana a 15-nov dentro de `tolerancia_dias` (por defecto 70,
    que cubre escenas de septiembre).
    """
    fechas = [parsear_fecha(f) for f in fechas]
    strokes = []
    for anio in sorted({f.year for f in fechas}):
        i_may = indice_fecha_cercana(fechas, parsear_fecha(f"{anio}-05-15"), tolerancia_dias)
        i_nov = indice_fecha_cercana(fechas, parsear_fecha(f"{anio}-11-15"), tolerancia_dias)
        if i_may is None or i_nov is None:
            continue
        if i_may == i_nov:
            continue
        strokes.append(serie[i_nov] - serie[i_may])
    if not strokes:
        return np.full(serie.shape[1:], np.nan)
    pila = np.stack(strokes, axis=0)
    # Un píxel sin ninguna fecha válida deja una rodaja vacía: no es un error.
    with np.errstate(invalid="ignore"):
        cuenta = np.sum(np.isfinite(pila), axis=0)
        suma = np.nansum(pila, axis=0)
    salida = np.full(cuenta.shape, np.nan, dtype=np.float64)
    buenos = cuenta > 0
    salida[buenos] = suma[buenos] / cuenta[buenos]
    return salida


def _desplazar(arr: np.ndarray, di: int, dj: int, relleno: float) -> np.ndarray:
    """out[fila, col] = arr[fila+di, col+dj], o `relleno` si se sale."""
    salida = np.full(arr.shape, relleno, dtype=np.float64)
    filas, cols = arr.shape
    r0 = max(0, -di)
    r1 = min(filas, filas - di)
    c0 = max(0, -dj)
    c1 = min(cols, cols - dj)
    if r1 <= r0 or c1 <= c0:
        return salida
    salida[r0:r1, c0:c1] = arr[r0 + di : r0 + di + (r1 - r0), c0 + dj : c0 + dj + (c1 - c0)]
    return salida


def zscore_anillo(
    valores: np.ndarray,
    res_m: float,
    rmin_m: float,
    rmax_m: float,
    min_muestras: int = 30,
    sigma_suelo: float = 1.0,
):
    """Z-score de cada celda respecto al anillo [rmin, rmax].

    La desviación del anillo no baja de `sigma_suelo` (mm). Así un campo casi
    plano no fabrica anomalías por una diferencia de décimas.
    """
    filas, cols = valores.shape
    radio = int(np.ceil(rmax_m / res_m))
    valido = np.isfinite(valores)
    v = np.where(valido, valores, 0.0)
    v2 = np.where(valido, np.asarray(valores, dtype=np.float64) ** 2, 0.0)
    suma = np.zeros((filas, cols), dtype=np.float64)
    suma2 = np.zeros((filas, cols), dtype=np.float64)
    cuenta = np.zeros((filas, cols), dtype=np.float64)
    for di in range(-radio, radio + 1):
        for dj in range(-radio, radio + 1):
            if di == 0 and dj == 0:
                continue
            dist = res_m * float(np.hypot(di, dj))
            if dist < rmin_m or dist > rmax_m:
                continue
            suma += _desplazar(v, di, dj, 0.0)
            suma2 += _desplazar(v2, di, dj, 0.0)
            cuenta += _desplazar(valido.astype(np.float64), di, dj, 0.0)
    media = np.full((filas, cols), np.nan)
    std = np.full((filas, cols), np.nan)
    ok = cuenta >= min_muestras
    media[ok] = suma[ok] / cuenta[ok]
    numer = suma2[ok] - (suma[ok] ** 2) / cuenta[ok]
    var = np.maximum(numer / (cuenta[ok] - 1.0), 0.0)
    std[ok] = np.sqrt(var)
    z = np.full((filas, cols), np.nan)
    exceso = np.full((filas, cols), np.nan)
    ambos = ok & valido
    denom = np.maximum(std, sigma_suelo)
    z[ambos] = (valores[ambos] - media[ambos]) / denom[ambos]
    exceso[ambos] = valores[ambos] - media[ambos]
    return z, media, std, exceso


def _fraccion_coherente(coherencia: np.ndarray, umbral: float) -> float:
    finito = np.isfinite(coherencia)
    if not finito.any():
        return float("nan")
    return float(np.mean(coherencia[finito] > umbral))


def exportar_geotiff(ruta, array: np.ndarray, transform: Affine, crs: str, nodata: float = -9999.0) -> None:
    """Escribe un GeoTIFF float32 listo para abrirlo en QGIS sobre el PNOA."""
    import rasterio

    asegurar_directorio(ruta.parent)
    datos = np.array(array, dtype=np.float32, copy=True)
    datos[~np.isfinite(datos)] = nodata
    perfil = {
        "driver": "GTiff",
        "height": datos.shape[0],
        "width": datos.shape[1],
        "count": 1,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
    }
    with rasterio.open(ruta, "w", **perfil) as dst:
        dst.write(datos, 1)
        dst.set_band_description(1, ruta.stem)


def medir_desde_serie(
    serie: np.ndarray,
    fechas,
    coherencia_media: np.ndarray,
    coherencia_campana: np.ndarray,
    transform: Affine,
    crs: str,
    cfg: dict,
) -> gpd.GeoDataFrame:
    """Agrega a la malla, mide y devuelve una capa de celdas."""
    med = cfg["medicion"]
    res_nativa = float(transform.a)
    res_malla = float(med["malla_m"])
    factor = int(round(res_malla / res_nativa))
    if factor < 1 or abs(factor * res_nativa - res_malla) > 1e-3:
        raise ValueError(
            f"La malla de {res_malla} m no es múltiplo de la resolución nativa {res_nativa} m"
        )
    serie_m = agregar_bloques(serie, factor)
    coh_m = agregar_bloques(coherencia_media, factor)
    coh_c = agregar_bloques(coherencia_campana, factor)
    velocidad, amplitud, velocidad_lineal, _ = ajuste_estacional(
        fechas, serie_m, min_fechas=int(med["min_fechas_ajuste"])
    )
    hundimiento = hundimiento_estacional(fechas, serie_m)
    z, media_anillo, std_anillo, exceso = zscore_anillo(
        hundimiento,
        res_m=res_malla,
        rmin_m=float(med["anillo_min_m"]),
        rmax_m=float(med["anillo_max_m"]),
        min_muestras=int(med["min_muestras_anillo"]),
        sigma_suelo=float(med["sigma_suelo_mm"]),
    )
    filas, cols = hundimiento.shape
    xmin = float(transform.c)
    ymax = float(transform.f)
    registros = []
    geometrias = []
    for i in range(filas):
        for j in range(cols):
            x0 = xmin + j * res_malla
            x1 = x0 + res_malla
            y1 = ymax - i * res_malla
            y0 = y1 - res_malla
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            lon, lat = a_geografico(cx, cy, crs)
            registros.append(
                {
                    "id_celda": f"c_{i:04d}_{j:04d}",
                    "fila": i,
                    "columna": j,
                    "x_utm": cx,
                    "y_utm": cy,
                    "lon": lon,
                    "lat": lat,
                    "velocidad_mm_anio": velocidad[i, j],
                    "velocidad_lineal_mm_anio": velocidad_lineal[i, j],
                    "amplitud_estacional_mm": amplitud[i, j],
                    "hundimiento_estacional_mm": hundimiento[i, j],
                    "zscore": z[i, j],
                    "media_anillo_mm": media_anillo[i, j],
                    "std_anillo_mm": std_anillo[i, j],
                    "exceso_mm": exceso[i, j],
                    "coherencia_media": coh_m[i, j],
                    "coherencia_campana": coh_c[i, j],
                    "desplazamiento_final_mm": serie_m[-1, i, j],
                }
            )
            geometrias.append(box(x0, y0, x1, y1))
    tabla = gpd.GeoDataFrame(registros, geometry=geometrias, crs=crs)
    # Metadatos de la malla para el visor y los GeoTIFF, colgados del attrs del frame.
    tabla.attrs["rejilla"] = {
        "filas": filas,
        "columnas": cols,
        "res_m": res_malla,
        "transform": [res_malla, 0.0, xmin, 0.0, -res_malla, ymax],
        "crs": crs,
        "fraccion_coherencia_campana_nativa": _fraccion_coherente(
            coherencia_campana, float(cfg["procesado"]["coherencia_min"])
        ),
        "fraccion_coherencia_media_nativa": _fraccion_coherente(
            coherencia_media, float(cfg["procesado"]["coherencia_min"])
        ),
    }
    tabla.attrs["serie_malla"] = serie_m
    tabla.attrs["fechas"] = [parsear_fecha(f).isoformat() for f in fechas]
    return tabla


def _escribir_geotiffs(tabla: gpd.GeoDataFrame, cfg: dict) -> None:
    rejilla = tabla.attrs["rejilla"]
    transform = Affine(*rejilla["transform"])
    crs = rejilla["crs"]
    filas, cols = rejilla["filas"], rejilla["columnas"]
    destino = asegurar_directorio(ruta_proyecto(cfg, "geotiff"))
    campos = {
        "zscore": "zscore",
        "amplitud_estacional_mm": "amplitud_estacional_mm",
        "velocidad_mm_anio": "velocidad_mm_anio",
        "hundimiento_estacional_mm": "hundimiento_estacional_mm",
        "coherencia_media": "coherencia_media",
    }
    for nombre, columna in campos.items():
        plano = np.full((filas, cols), np.nan, dtype=np.float32)
        plano[tabla["fila"].to_numpy(), tabla["columna"].to_numpy()] = tabla[columna].to_numpy()
        exportar_geotiff(destino / f"{nombre}.tif", plano, transform, crs)


def medir(cfg: dict) -> gpd.GeoDataFrame:
    """Lee la serie de `procesar_insar` y escribe `data/resultados.parquet`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    procesado = ruta_proyecto(cfg, "procesado")
    npz = np.load(procesado / "serie_mm.npz")
    meta = json.loads((procesado / "metadatos.json").read_text(encoding="utf-8"))
    transform = lista_a_afin(meta["transform"])
    tabla = medir_desde_serie(
        npz["serie_mm"],
        list(npz["fechas"]),
        npz["coherencia_media"],
        npz["coherencia_campana"],
        transform,
        meta["crs"],
        cfg,
    )
    serie_malla = tabla.attrs.pop("serie_malla")
    fechas = tabla.attrs["fechas"]
    rejilla = tabla.attrs["rejilla"]
    np.savez_compressed(
        procesado / "serie_malla100.npz",
        serie_mm=serie_malla,
        fechas=np.array(fechas),
        filas=rejilla["filas"],
        columnas=rejilla["columnas"],
    )
    (procesado / "rejilla.json").write_text(
        json.dumps(rejilla, indent=2), encoding="utf-8"
    )
    _escribir_geotiffs(tabla, cfg)
    salida = ruta_proyecto(cfg, "resultados")
    asegurar_directorio(salida.parent)
    # attrs no viaja en el parquet; la rejilla ya está en rejilla.json.
    tabla.to_parquet(salida)
    n_anom = int(np.nansum(tabla["zscore"].to_numpy() > float(cfg["medicion"]["z_anomalia"])))
    log.info(
        "Mediciones en %s (%d celdas, %d con z > %.1f). GeoTIFF en %s",
        salida,
        len(tabla),
        n_anom,
        float(cfg["medicion"]["z_anomalia"]),
        ruta_proyecto(cfg, "geotiff"),
    )
    return tabla


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Velocidad, amplitud estacional y z-score.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    medir(cargar_config(args.config))


if __name__ == "__main__":
    main()
