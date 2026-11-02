"""Opción A: apilar GUNW y reconstruir la serie de deformación.

Por interferograma:
1. Pasa la fase desenvuelta a milímetros en la línea de visión.
2. Enmascara la coherencia por debajo de 0.4 (y las componentes conexas nulas).
3. Quita una rampa plana ajustada a las zonas estables (coherencia alta).
4. Resta el valor del punto de referencia (casco urbano de Rociana).

Con la red de pares ya referenciada, invierte por mínimos cuadrados el
desplazamiento de cada píxel en cada fecha. La primera fecha queda fija en
cero: los interferogramas solo observan diferencias.

La opción B (MintPy / SBAS sobre SLC) está descrita en
`docs/08-opcion-b-mintpy.md` y tiene un conversor en `src/opcion_b_mintpy.py`.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

import numpy as np
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject

from lectura_gunw import (
    cargar_interferograma,
    desplazamiento_mm,
    listar_interferogramas,
)
from utilidades import (
    afin_a_lista,
    asegurar_directorio,
    cargar_config,
    guardar_json,
    indices_xy,
    punto_referencia,
    resolver_aoi,
    ruta_proyecto,
    a_metrico,
)

log = logging.getLogger("poc.insar")


def quitar_rampa(campo: np.ndarray, mascara: np.ndarray, min_puntos: int = 30) -> np.ndarray:
    """Resta el plano a + b·columna + c·fila ajustado donde `mascara` es cierta.

    El plano cabe en una rampa atmosférica de gran escala. Un cono de unos
    cientos de metros, que es la señal que se busca, no es una plano y se queda.
    """
    salida = np.array(campo, dtype=np.float64, copy=True)
    finito = np.isfinite(salida)
    usar = mascara & finito
    if int(usar.sum()) < min_puntos:
        usar = finito
    if int(usar.sum()) < max(10, min_puntos // 3):
        return salida
    filas, cols = np.indices(salida.shape)
    diseno = np.column_stack(
        [np.ones(int(usar.sum())), cols[usar].astype(np.float64), filas[usar].astype(np.float64)]
    )
    coef, *_ = np.linalg.lstsq(diseno, salida[usar], rcond=None)
    plano = coef[0] + coef[1] * cols + coef[2] * filas
    salida[finito] = salida[finito] - plano[finito]
    return salida


def restar_referencia(campo: np.ndarray, fila: int, col: int, radio_busqueda: int = 5) -> np.ndarray:
    """Resta el píxel de referencia. Si está enmascarado, usa el vecino finito más cercano."""
    salida = np.array(campo, dtype=np.float64, copy=True)
    fila = int(np.clip(fila, 0, salida.shape[0] - 1))
    col = int(np.clip(col, 0, salida.shape[1] - 1))
    if not np.isfinite(salida[fila, col]):
        encontrado = None
        for radio in range(1, radio_busqueda + 1):
            r0, r1 = max(0, fila - radio), min(salida.shape[0], fila + radio + 1)
            c0, c1 = max(0, col - radio), min(salida.shape[1], col + radio + 1)
            ventana = salida[r0:r1, c0:c1]
            if np.isfinite(ventana).any():
                yy, xx = np.where(np.isfinite(ventana))
                dist = (yy - (fila - r0)) ** 2 + (xx - (col - c0)) ** 2
                k = int(np.argmin(dist))
                encontrado = ventana[yy[k], xx[k]]
                break
        if encontrado is None:
            return np.full_like(salida, np.nan)
        valor = float(encontrado)
    else:
        valor = float(salida[fila, col])
    return salida - valor


def construir_matriz_diseno(indices_pares: np.ndarray, n_fechas: int) -> np.ndarray:
    """Matriz de la red: cada fila es d(j) - d(i) = observación.

    La fecha 0 no es incógnita (vale 0). `indices_pares` tiene forma (n_pares, 2).
    """
    n_pares = indices_pares.shape[0]
    matriz = np.zeros((n_pares, n_fechas - 1), dtype=np.float64)
    for k, (i, j) in enumerate(indices_pares):
        i = int(i)
        j = int(j)
        if i > 0:
            matriz[k, i - 1] -= 1.0
        if j > 0:
            matriz[k, j - 1] += 1.0
    return matriz


def invertir_red(matriz: np.ndarray, observaciones: np.ndarray, min_ecuaciones: int) -> np.ndarray:
    """Invierte la red píxel a píxel.

    `observaciones` tiene forma (n_interferogramas, n_pixeles) y puede traer NaN
    donde la coherencia no llegó al umbral. Devuelve (n_fechas, n_pixeles),
    con la fecha 0 en cero. Si la red de un píxel no tiene rango completo,
    ese píxel se deja en NaN en vez de inventar una solución de norma mínima
    en una componente desconectada.
    """
    n_ifg, n_incognitas = matriz.shape
    n_fechas = n_incognitas + 1
    n_pix = observaciones.shape[1]
    serie = np.full((n_fechas, n_pix), np.nan, dtype=np.float64)
    valida = np.isfinite(observaciones)
    todos = valida.all(axis=0)
    # Una red que no ancla todas las fechas (rango < n_fechas-1) no se resuelve
    # en bloque: lstsq devolvería una solución de norma mínima sin significado.
    rango_completo = np.linalg.matrix_rank(matriz, tol=1e-8) == n_incognitas
    if todos.any() and rango_completo:
        coef, *_ = np.linalg.lstsq(matriz, observaciones[:, todos], rcond=None)
        serie[1:, todos] = coef
        serie[0, todos] = 0.0
    elif not rango_completo:
        todos = np.zeros(n_pix, dtype=bool)

    n_validas = valida.sum(axis=0)
    parciales = (~todos) & (n_validas >= max(min_ecuaciones, n_fechas - 1))
    for p in np.flatnonzero(parciales):
        mascara = valida[:, p]
        sub = matriz[mascara]
        if np.linalg.matrix_rank(sub, tol=1e-6) < n_incognitas:
            continue
        coef, *_ = np.linalg.lstsq(sub, observaciones[mascara, p], rcond=None)
        serie[1:, p] = coef
        serie[0, p] = 0.0
    return serie


def preparar_interferograma(
    desplazamiento: np.ndarray,
    coherencia: np.ndarray,
    componentes: np.ndarray | None,
    umbral_coherencia: float,
    umbral_estable: float,
    fila_ref: int,
    col_ref: int,
) -> np.ndarray:
    """Máscara, rampa y referencia para un solo par. Devuelve mm ya referenciados."""
    campo = np.array(desplazamiento, dtype=np.float64, copy=True)
    coh = np.asarray(coherencia, dtype=np.float64)
    if componentes is not None:
        # Componente 0: el desenvolvimiento no es fiable en ese píxel.
        campo = np.where(np.asarray(componentes) > 0, campo, np.nan)
    valido = np.isfinite(campo) & np.isfinite(coh) & (coh >= umbral_coherencia)
    campo = np.where(valido, campo, np.nan)
    estable = valido & (coh >= umbral_estable)
    campo = quitar_rampa(campo, estable)
    return restar_referencia(campo, fila_ref, col_ref)


def _remuestrear(array: np.ndarray, origen: Affine, crs_origen: str, destino_malla: dict) -> np.ndarray:
    """Lleva un raster a la rejilla común del stack. NaN donde no hay dato."""
    destino = np.full((destino_malla["rows"], destino_malla["cols"]), np.nan, dtype=np.float64)
    # reproject no trata NaN como nodata de forma fiable: se usa un hueco numérico.
    hueco = -1.0e32
    origen_lleno = np.where(np.isfinite(array), array, hueco).astype(np.float64)
    reproject(
        origen_lleno,
        destino,
        src_transform=origen,
        src_crs=crs_origen,
        dst_transform=destino_malla["transform"],
        dst_crs=destino_malla["crs"],
        resampling=Resampling.bilinear,
        src_nodata=hueco,
        dst_nodata=np.nan,
    )
    return destino


def _misma_rejilla(transform: Affine, crs: str, malla: dict, forma: tuple[int, int]) -> bool:
    if str(crs) != str(malla["crs"]):
        return False
    if forma != (malla["rows"], malla["cols"]):
        return False
    ref = malla["transform"]
    return all(abs(float(a) - float(b)) < 1e-3 for a, b in zip(transform, ref))


def _elegir_plataforma(productos, preferida: str) -> str:
    if preferida and preferida.lower() != "auto":
        return preferida
    cuentas: dict[str, int] = {}
    for producto in productos:
        cuentas[producto.plataforma] = cuentas.get(producto.plataforma, 0) + 1
    if not cuentas:
        raise RuntimeError("No hay interferogramas")
    return max(cuentas, key=cuentas.get)


def procesar_observaciones(
    desplazamientos: list[np.ndarray],
    coherencias: list[np.ndarray],
    pares: list[tuple[date, date]],
    fechas: list[date],
    fila_ref: int,
    col_ref: int,
    cfg: dict,
    componentes: list[np.ndarray | None] | None = None,
) -> dict:
    """Núcleo de la opción A, ya en milímetros y en una rejilla común.

    Pensado para poder probarlo sin archivos: el modo sintético y los GUNW
    reales llegan aquí después de la lectura.
    """
    proc = cfg["procesado"]
    umbral = float(proc["coherencia_min"])
    umbral_estable = float(proc["coherencia_zona_estable"])
    min_ec = int(proc.get("min_ecuaciones_red", 8))
    n = len(desplazamientos)
    if componentes is None:
        componentes = [None] * n

    preparados = []
    coh_guardar = []
    for k in range(n):
        preparado = preparar_interferograma(
            desplazamientos[k],
            coherencias[k],
            componentes[k],
            umbral,
            umbral_estable,
            fila_ref,
            col_ref,
        )
        preparados.append(preparado)
        coh_guardar.append(np.asarray(coherencias[k], dtype=np.float64))

    indice = {f: i for i, f in enumerate(fechas)}
    indices_pares = np.array(
        [[indice[a], indice[b]] for a, b in pares], dtype=np.int32
    )
    matriz = construir_matriz_diseno(indices_pares, len(fechas))
    forma = preparados[0].shape
    obs = np.stack([p.reshape(-1) for p in preparados], axis=0)
    serie_plana = invertir_red(matriz, obs, min_ecuaciones=min_ec)
    serie = serie_plana.reshape((len(fechas),) + forma)

    coherencias_apiladas = np.stack(coh_guardar, axis=0)
    meses_riego = set(cfg.get("validacion", {}).get("meses_riego", [4, 5, 6]))
    campana = np.array([b.month in meses_riego for _, b in pares], dtype=bool)
    with np.errstate(all="ignore"):
        coherencia_media = np.nanmean(coherencias_apiladas, axis=0)
        if campana.any():
            coherencia_campana = np.nanmean(coherencias_apiladas[campana], axis=0)
        else:
            coherencia_campana = coherencia_media.copy()
    return {
        "serie_mm": serie,
        "fechas": fechas,
        "coherencia_media": coherencia_media,
        "coherencia_campana": coherencia_campana,
        "matriz": matriz,
        "n_interferogramas": n,
    }


def _malla_desde_transform(transform: Affine, crs: str, rows: int, cols: int) -> dict:
    return {
        "xmin": float(transform.c),
        "ymax": float(transform.f),
        "res": float(transform.a),
        "rows": rows,
        "cols": cols,
        "transform": transform,
        "crs": crs,
        "ymin": float(transform.f + transform.e * rows),
        "xmax": float(transform.c + transform.a * cols),
    }


def procesar(cfg: dict) -> dict:
    """Lee los GUNW del directorio configurado y escribe la serie temporal."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    directorio = ruta_proyecto(cfg, "interferogramas")
    rutas = listar_interferogramas(directorio)
    if not rutas:
        raise FileNotFoundError(
            f"No hay interferogramas en {directorio}. "
            "Ejecute `bash src/download.sh` (modo sintético o real)."
        )
    onda = float(cfg["procesado"]["longitud_onda_m"])
    signo = float(cfg["procesado"]["signo_fase"])
    productos = [cargar_interferograma(ruta, onda) for ruta in rutas]
    plataforma = _elegir_plataforma(productos, cfg["procesado"].get("plataforma", "auto"))
    productos = [p for p in productos if p.plataforma == plataforma]
    if not productos:
        raise RuntimeError(f"No quedan interferogramas de la plataforma {plataforma}")
    log.info(
        "Plataforma %s: %d interferogramas (no se mezclan bandas en la misma inversión)",
        plataforma,
        len(productos),
    )

    base = productos[0]
    malla = _malla_desde_transform(base.transform, base.crs, *base.fase_rad.shape)
    aoi = resolver_aoi(cfg)
    lon_ref, lat_ref = punto_referencia(cfg)
    x_ref, y_ref = a_metrico(lon_ref, lat_ref, aoi.crs)
    # La referencia se indexa en la rejilla del stack. Si el producto ya viene
    # en otro CRS métrico equivalente, se usan sus propias coordenadas de ejes.
    if str(base.crs) != str(aoi.crs):
        x_ref, y_ref = a_metrico(lon_ref, lat_ref, str(base.crs))
    fila_ref, col_ref = indices_xy(base.transform, x_ref, y_ref)

    desplazamientos = []
    coherencias = []
    componentes = []
    pares = []
    for producto in productos:
        mm = desplazamiento_mm(producto.fase_rad, producto.longitud_onda_m, signo)
        coh = producto.coherencia
        cc = producto.componentes
        if not _misma_rejilla(producto.transform, producto.crs, malla, mm.shape):
            log.info("Remuestreo %s a la rejilla del primer producto", producto.ruta.name)
            mm = _remuestrear(mm, producto.transform, producto.crs, malla)
            coh = _remuestrear(coh, producto.transform, producto.crs, malla)
            if cc is not None:
                cc = _remuestrear(cc.astype(np.float64), producto.transform, producto.crs, malla)
        desplazamientos.append(mm)
        coherencias.append(coh)
        componentes.append(None if cc is None else np.rint(cc))
        pares.append((producto.fecha_referencia, producto.fecha_secundaria))

    fechas = sorted({f for par in pares for f in par})
    resultado = procesar_observaciones(
        desplazamientos,
        coherencias,
        pares,
        fechas,
        fila_ref,
        col_ref,
        cfg,
        componentes,
    )
    destino = asegurar_directorio(ruta_proyecto(cfg, "procesado"))
    np.savez_compressed(
        destino / "serie_mm.npz",
        serie_mm=resultado["serie_mm"],
        fechas=np.array([f.isoformat() for f in fechas]),
        coherencia_media=resultado["coherencia_media"],
        coherencia_campana=resultado["coherencia_campana"],
    )
    meta = {
        "plataforma": plataforma,
        "n_interferogramas": resultado["n_interferogramas"],
        "n_fechas": len(fechas),
        "fechas": [f.isoformat() for f in fechas],
        "crs": str(base.crs),
        "transform": afin_a_lista(base.transform),
        "shape": list(base.fase_rad.shape),
        "fila_referencia": int(fila_ref),
        "columna_referencia": int(col_ref),
        "signo_fase": signo,
        "longitud_onda_m": onda,
        "umbral_coherencia": float(cfg["procesado"]["coherencia_min"]),
        "modo": cfg.get("modo", "real"),
        "aoi": aoi.nombre,
    }
    guardar_json(destino / "metadatos.json", meta)
    validos = np.isfinite(resultado["serie_mm"][-1])
    log.info(
        "Serie escrita en %s (%d fechas, %d píxeles con solución)",
        destino / "serie_mm.npz",
        len(fechas),
        int(validos.sum()),
    )
    return meta


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Apila GUNW y reconstruye la deformación (opción A).")
    parser.add_argument("--config", default=None, help="Ruta alternativa a config.yaml")
    args = parser.parse_args(argv)
    procesar(cargar_config(args.config))


if __name__ == "__main__":
    main()
