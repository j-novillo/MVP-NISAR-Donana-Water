"""Cruce legal y score de sospecha por parcela.

La spec fija la fórmula, y se aplica tal cual:

    score = 40 * norm(amplitud_estacional)
          + 30 * norm(velocidad_subsidencia)
          + 20 * norm(ndvi_campaña)
          + 10 * (1 si sin_pozo_declarado y fuera_SAR else 0)

`norm` es un mínimo-máximo sobre las parcelas con dato, recortado a [0, 1].
`velocidad_subsidencia` es la parte negativa de la velocidad cambiada de signo
(mm/año de hundimiento; el levantamiento no suma).

El buffer de 500 m alrededor de cada celda con z-score > 2 no entra en la
fórmula: marca qué parcelas caen junto a una anomalía (`en_buffer_anomalia`)
y si en ese entorno hay una captación registrada. El término legal de la
fórmula usa la parcela: sin pozo declarado a menos de 500 m y fuera de la SAR.
"""

from __future__ import annotations

import argparse
import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

from utilidades import asegurar_directorio, cargar_config, ruta_proyecto

log = logging.getLogger("poc.score")


def normalizar(serie: pd.Series) -> pd.Series:
    """Mínimo-máximo a [0, 1]. Si no hay rango, devuelve ceros."""
    valores = serie.astype(float)
    finito = valores[np.isfinite(valores)]
    if finito.empty:
        return pd.Series(np.zeros(len(serie)), index=serie.index, dtype=float)
    lo = float(finito.min())
    hi = float(finito.max())
    if hi - lo < 1e-9:
        return pd.Series(np.zeros(len(serie)), index=serie.index, dtype=float)
    return ((valores - lo) / (hi - lo)).clip(0.0, 1.0)


def calcular_score(
    amplitud_norm: pd.Series,
    velocidad_norm: pd.Series,
    ndvi_norm: pd.Series,
    sin_pozo_y_fuera_sar: pd.Series,
) -> pd.DataFrame:
    """Aplica la fórmula y devuelve el score junto con cada término ponderado."""
    p_amp = 40.0 * amplitud_norm.astype(float)
    p_vel = 30.0 * velocidad_norm.astype(float)
    p_ndvi = 20.0 * ndvi_norm.astype(float)
    p_legal = 10.0 * sin_pozo_y_fuera_sar.astype(float)
    score = p_amp + p_vel + p_ndvi + p_legal
    return pd.DataFrame(
        {
            "p_amplitud": p_amp,
            "p_velocidad": p_vel,
            "p_ndvi": p_ndvi,
            "p_legal": p_legal,
            "score": score,
        }
    )


def _leer_capa(ruta, crs_destino: str) -> gpd.GeoDataFrame | None:
    if not ruta.is_file():
        return None
    capa = gpd.read_file(ruta)
    if capa.empty:
        return capa
    if capa.crs is None:
        capa = capa.set_crs("EPSG:4326")
    return capa.to_crs(crs_destino)


def _ndvi_campana(ruta_csv: Pathlike, meses: list[int]) -> pd.Series:
    if not ruta_csv.is_file():
        return pd.Series(dtype=float)
    tabla = pd.read_csv(ruta_csv)
    if "fecha" not in tabla.columns or "ndvi" not in tabla.columns:
        raise ValueError(f"{ruta_csv} tiene que traer columnas id_parcela, fecha, ndvi")
    tabla["fecha"] = pd.to_datetime(tabla["fecha"])
    campana = tabla[tabla["fecha"].dt.month.isin(meses)]
    return campana.groupby("id_parcela")["ndvi"].mean()


# Alias de tipo para no importar Path solo por la anotación en tiempo de ejecución.
from pathlib import Path

Pathlike = Path


def puntuar(cfg: dict) -> gpd.GeoDataFrame:
    """Cruza la malla con parcelas, pozos, SAR y NDVI, y ordena por score."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    capas_dir = ruta_proyecto(cfg, "capas")
    parcelas = _leer_capa(capas_dir / "parcelas.gpkg", cfg["crs_metrico"])
    if parcelas is None or parcelas.empty:
        raise FileNotFoundError(
            f"Falta {capas_dir / 'parcelas.gpkg'}. "
            "En modo sintético lo genera src/sintetico.py. "
            "En modo real, SIGPAC no tiene una descarga estable: ver docs/02-descarga-de-datos.md."
        )
    if "id_parcela" not in parcelas.columns:
        parcelas["id_parcela"] = [f"P-{i:04d}" for i in range(len(parcelas))]
    parcelas["id_parcela"] = parcelas["id_parcela"].astype(str)

    celdas = gpd.read_parquet(ruta_proyecto(cfg, "resultados"))
    if celdas.crs is None:
        celdas = celdas.set_crs(cfg["crs_metrico"])
    celdas = celdas.to_crs(cfg["crs_metrico"])
    parcelas = parcelas.to_crs(cfg["crs_metrico"])

    puntos = celdas.copy()
    puntos["geometry"] = celdas.geometry.centroid
    unidas = gpd.sjoin(
        puntos,
        parcelas[["id_parcela", "geometry"]],
        predicate="within",
        how="inner",
    )
    agregados = unidas.groupby("id_parcela").agg(
        amplitud_estacional_mm=("amplitud_estacional_mm", "mean"),
        velocidad_mm_anio=("velocidad_mm_anio", "mean"),
        hundimiento_estacional_mm=("hundimiento_estacional_mm", "mean"),
        zscore_max=("zscore", "max"),
        coherencia_media=("coherencia_media", "mean"),
        n_celdas=("id_celda", "count"),
    )

    med = cfg["medicion"]
    score_cfg = cfg["score"]
    buffer_m = float(score_cfg["buffer_m"])
    umbral_z = float(med["z_anomalia"])
    anomalias = celdas[celdas["zscore"] > umbral_z].copy()
    if len(anomalias):
        zona_anomalia = unary_union(list(anomalias.geometry.centroid.buffer(buffer_m)))
        en_buffer = parcelas.geometry.intersects(zona_anomalia)
    else:
        en_buffer = pd.Series(False, index=parcelas.index)

    pozos = _leer_capa(capas_dir / "pozos_registrados.gpkg", cfg["crs_metrico"])
    aviso_pozos = False
    if pozos is None:
        aviso_pozos = True
        sin_pozo = pd.Series(False, index=parcelas.index)
        hay_captacion = pd.Series(pd.NA, index=parcelas.index)
    else:
        if len(pozos):
            # Solo la geometría del pozo: el registro también trae id_parcela y
            # el sjoin le pondría sufijo, y el id de la parcela se perdería.
            buffers = gpd.GeoDataFrame(
                {"id_parcela": parcelas["id_parcela"].astype(str).values},
                geometry=parcelas.geometry.buffer(buffer_m),
                crs=parcelas.crs,
            )
            cruce = gpd.sjoin(pozos[["geometry"]], buffers, predicate="intersects", how="inner")
            con_pozo = set(cruce["id_parcela"].astype(str))
        else:
            con_pozo = set()
        sin_pozo = ~parcelas["id_parcela"].isin(con_pozo)
        hay_captacion = ~sin_pozo

    sar = _leer_capa(capas_dir / "sar.gpkg", cfg["crs_metrico"])
    aviso_sar = False
    if sar is None or sar.empty:
        aviso_sar = True
        dentro_sar = pd.Series(False, index=parcelas.index)
        fuera_sar = pd.Series(False, index=parcelas.index)
    else:
        poligono = unary_union(list(sar.geometry))
        dentro_sar = parcelas.geometry.representative_point().within(poligono)
        fuera_sar = ~dentro_sar

    ndvi = _ndvi_campana(ruta_proyecto(cfg, "ndvi"), list(score_cfg["meses_campana"]))
    ndvi.name = "ndvi_campana"

    salida = parcelas.copy()
    salida = salida.merge(agregados, left_on="id_parcela", right_index=True, how="left")
    salida["en_buffer_anomalia"] = en_buffer.to_numpy()
    salida["sin_pozo_declarado"] = sin_pozo.to_numpy()
    salida["hay_captacion_registrada"] = hay_captacion.to_numpy()
    salida["dentro_sar"] = dentro_sar.to_numpy()
    salida["fuera_sar"] = fuera_sar.to_numpy()
    salida = salida.merge(ndvi, left_on="id_parcela", right_index=True, how="left")
    salida["ndvi_campana"] = salida["ndvi_campana"].astype(float)
    salida["cultivo_activo"] = salida["ndvi_campana"] > float(score_cfg["ndvi_min_cultivo"])
    # Hundimiento: solo la velocidad negativa cuenta como subsidencia.
    salida["velocidad_subsidencia_mm_anio"] = np.clip(-salida["velocidad_mm_anio"], 0, None)

    terminos = calcular_score(
        normalizar(salida["amplitud_estacional_mm"]),
        normalizar(salida["velocidad_subsidencia_mm_anio"]),
        normalizar(salida["ndvi_campana"]),
        (salida["sin_pozo_declarado"] & salida["fuera_sar"]).astype(float),
    )
    for columna in terminos.columns:
        salida[columna] = terminos[columna].to_numpy()
    salida.loc[~np.isfinite(salida["amplitud_estacional_mm"]), "score"] = np.nan
    salida = salida.sort_values("score", ascending=False, na_position="last")
    salida["ranking"] = np.arange(1, len(salida) + 1)
    if aviso_pozos:
        log.warning(
            "No está la capa de pozos registrados: el término legal vale 0 "
            "(ausencia de capa no se interpreta como 'sin pozo')."
        )
    if aviso_sar:
        log.warning(
            "No está el polígono SAR: el término legal vale 0 "
            "(ausencia de capa no se interpreta como 'fuera de SAR')."
        )

    destino = ruta_proyecto(cfg, "parcelas_score")
    asegurar_directorio(destino.parent)
    # El parquet y el GeoPackage se guardan en WGS84 para el visor y para QGIS.
    publicado = salida.to_crs("EPSG:4326")
    publicado.to_parquet(destino)
    publicado.to_file(destino.with_suffix(".gpkg"), driver="GPKG")
    log.info(
        "Score de %d parcelas en %s. Máximo %.1f",
        len(publicado),
        destino,
        float(np.nanmax(publicado["score"].to_numpy())) if len(publicado) else float("nan"),
    )
    return publicado


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Cruce legal y score por parcela.")
    parser.add_argument("--config", default=None)
    parser.add_argument(
        "--sin-validar",
        action="store_true",
        help="No lanza la validación go/no-go al terminar.",
    )
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    puntuar(cfg)
    if not args.sin_validar:
        from validar import evaluar

        evaluar(cfg)


if __name__ == "__main__":
    main()
