"""Genera una escena falsa pero reconocible de la tesela de Rociana.

No es una simulación del acuífero. Es un banco de pruebas:

- interferogramas con rampa atmosférica, ruido y conos de subsidencia estacional
  junto a pozos no registrados;
- parcelas dentro y fuera de una SAR inventada;
- NDVI de campaña alto en el cultivo y bajo en el barbecho;
- pozos registrados (sin cono), pozos cerrados (parte con cono, parte sin él)
  y unos piezómetros que bajan más donde está el cono.

Así se puede ejecutar procesar → medir → score → validar sin credenciales y
ver si los criterios go/no-go responden a una señal que sí está ahí.
Todo lo generado lleva `sintetico=True` y un manifiesto en
`data/raw/MANIFIESTO_SINTETICO.json`.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import Affine
from shapely.geometry import Point, box

from lectura_gunw import fase_desde_desplazamiento_mm
from utilidades import (
    a_geografico,
    a_metrico,
    asegurar_directorio,
    cargar_config,
    centros_pixel,
    fechas_mensuales,
    guardar_json,
    malla_anidada,
    parsear_fecha,
    punto_referencia,
    resolver_aoi,
    ruta_proyecto,
)

log = logging.getLogger("poc.sintetico")


def _bloque(malla: dict, col: int, fila: int, lado_celdas: int, res_malla: float):
    x0 = malla["xmin"] + col * res_malla
    y1 = malla["ymax"] - fila * res_malla
    return box(x0, y1 - lado_celdas * res_malla, x0 + lado_celdas * res_malla, y1)


def _origenes_validos(col_ref: int, fila_ref: int, dcols, dfilas, n_cols: int, n_filas: int, lado: int):
    pares = []
    for dc in dcols:
        for df in dfilas:
            col = col_ref + dc
            fila = fila_ref + df
            if col < 0 or fila < 0 or col + lado > n_cols or fila + lado > n_filas:
                continue
            pares.append((col, fila))
    return pares


def _gdf(registros, geometrias, crs: str) -> gpd.GeoDataFrame:
    marco = gpd.GeoDataFrame(registros, geometry=geometrias, crs=crs)
    return marco.to_crs("EPSG:4326")


def generar(cfg: dict) -> dict:
    """Escribe interferogramas, capas y NDVI sintéticos. Devuelve un resumen."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sint = cfg["sintetico"]
    rng = np.random.default_rng(int(sint["semilla"]))
    aoi = resolver_aoi(cfg)
    res = float(sint["resolucion_m"])
    res_malla = float(cfg["medicion"]["malla_m"])
    malla = malla_anidada(aoi, res, res_malla)
    factor = int(round(res_malla / res))
    n100_cols = malla["cols"] // factor
    n100_rows = malla["rows"] // factor
    lon_ref, lat_ref = punto_referencia(cfg)
    xref, yref = a_metrico(lon_ref, lat_ref, aoi.crs)
    x1d, y1d = centros_pixel(malla)
    xx, yy = np.meshgrid(x1d, y1d)

    coh_base = np.full((malla["rows"], malla["cols"]), 0.60, dtype=np.float64)
    urbano = (xx - xref) ** 2 + (yy - yref) ** 2 <= 350.0**2
    coh_base[urbano] = 0.90
    marisma = yy < (malla["ymin"] + 700.0)
    coh_base[marisma] = 0.25

    col_ref = int(np.floor((xref - malla["xmin"]) / res_malla))
    fila_ref = int(np.floor((malla["ymax"] - yref) / res_malla))
    lado = 2
    filas = [-12, -8, -4, 0, 4, 8, 12]
    oeste = _origenes_validos(col_ref, fila_ref, [-16, -12, -8], filas, n100_cols, n100_rows, lado)
    este = _origenes_validos(col_ref, fila_ref, [8, 12, 16], filas, n100_cols, n100_rows, lado)
    if len(oeste) < 6 or len(este) < 10:
        raise RuntimeError(
            "La tesela se ha quedado pequeña para el mosaico sintético de parcelas. "
            f"Parcelas al oeste: {len(oeste)}, al este: {len(este)}."
        )

    parcelas_reg = []
    parcelas_geom = []
    for i, (col, fila) in enumerate(oeste):
        parcelas_reg.append(
            {"id_parcela": f"L-{i+1:03d}", "zona": "dentro_sar", "sintetico": True}
        )
        parcelas_geom.append(_bloque(malla, col, fila, lado, res_malla))
    n_legal = len(parcelas_reg)
    for i, (col, fila) in enumerate(este):
        parcelas_reg.append(
            {"id_parcela": f"I-{i+1:03d}", "zona": "fuera_sar", "sintetico": True}
        )
        parcelas_geom.append(_bloque(malla, col, fila, lado, res_malla))
    parcelas_m = gpd.GeoDataFrame(parcelas_reg, geometry=parcelas_geom, crs=aoi.crs)
    ilegales = parcelas_m[parcelas_m["zona"] == "fuera_sar"].copy()
    centro_cono = Point(xref + 1200.0, yref)
    ilegales["dist_cluster"] = ilegales.geometry.centroid.distance(centro_cono)
    ilegales = ilegales.sort_values("dist_cluster")
    ids_cono_cerrado = list(ilegales["id_parcela"].iloc[:6])
    ids_cono_activo = list(ilegales["id_parcela"].iloc[6:8])
    ids_cierre_sin_senal = list(ilegales["id_parcela"].iloc[-2:])
    ids_cono = ids_cono_cerrado + ids_cono_activo

    legales = parcelas_m[parcelas_m["zona"] == "dentro_sar"].copy()
    centro_legal = Point(xref - 1200.0, yref)
    legales["dist"] = legales.geometry.centroid.distance(centro_legal)
    legales = legales.sort_values("dist")
    ids_pozo_legal = list(legales["id_parcela"].iloc[:6])

    # Barbechos: una de cada dos parcelas que no llevan cono, para que el NDVI no sea constante.
    ids_barbecho = []
    for i, pid in enumerate(parcelas_m["id_parcela"]):
        if pid in ids_cono or pid in ids_cierre_sin_senal:
            continue
        if i % 2 == 0:
            ids_barbecho.append(pid)

    amplitud = np.full(xx.shape, float(sint["amplitud_fondo_mm"]), dtype=np.float64)
    amplitud += 0.35 * np.sin(2.0 * np.pi * (xx - xref) / 8000.0)
    velocidad = np.full(xx.shape, -1.5, dtype=np.float64)
    sigma = float(sint["sigma_cono_m"])
    amp_cono = float(sint["amplitud_cono_mm"])
    conos_xy = []
    for pid in ids_cono:
        centro = parcelas_m.loc[parcelas_m["id_parcela"] == pid].geometry.iloc[0].centroid
        radio2 = (xx - centro.x) ** 2 + (yy - centro.y) ** 2
        campana = np.exp(-radio2 / (2.0 * sigma**2))
        amplitud += amp_cono * campana
        velocidad += -4.0 * campana
        conos_xy.append((centro.x, centro.y, pid))
    amplitud[urbano] = 0.0
    velocidad[urbano] = 0.0

    inicio = parsear_fecha(sint["fecha_inicio"])
    fechas = fechas_mensuales(inicio, int(sint["n_meses"]))
    serie = _serie_desplazamiento(fechas, amplitud, velocidad)
    retardos = [int(r) for r in sint["retardos_meses"]]
    pares = [(i, i + r) for r in retardos for i in range(len(fechas) - r)]

    directorio = asegurar_directorio(ruta_proyecto(cfg, "interferogramas"))
    # Limpia productos anteriores para no mezclar una corrida vieja con otra.
    for viejo in list(directorio.glob("*.tif")) + list(directorio.glob("*.json")):
        viejo.unlink()
    onda = float(sint["longitud_onda_m"])
    signo = float(cfg["procesado"]["signo_fase"])
    ruido = float(sint["ruido_ifg_mm"])
    meses_riego = set(cfg["validacion"]["meses_riego"])
    transform: Affine = malla["transform"]
    for i, j in pares:
        diferencia = serie[j] - serie[i]
        xn = (xx - xref) / 1000.0
        yn = (yy - yref) / 1000.0
        rampa = rng.normal(0, 0.8) + rng.normal(0, 1.2) * xn + rng.normal(0, 1.2) * yn
        observacion = diferencia + rampa + rng.normal(0.0, ruido, diferencia.shape)
        coh = np.clip(coh_base + rng.normal(0.0, 0.02, coh_base.shape), 0.0, 1.0)
        if fechas[j].month in meses_riego:
            coh = np.clip(coh * 0.97, 0.0, 1.0)
        fase = fase_desde_desplazamiento_mm(observacion, onda, signo)
        nombre = f"NISAR_GUNW_{fechas[i]:%Y%m%d}_{fechas[j]:%Y%m%d}"
        _escribir_tif(directorio / f"{nombre}.tif", fase, coh, transform, aoi.crs)
        (directorio / f"{nombre}.json").write_text(
            json.dumps(
                {
                    "plataforma": "NISAR",
                    "producto": "GUNW",
                    "sintetico": True,
                    "fecha_referencia": fechas[i].isoformat(),
                    "fecha_secundaria": fechas[j].isoformat(),
                    "longitud_onda_m": onda,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    capas = asegurar_directorio(ruta_proyecto(cfg, "capas"))
    _gdf(parcelas_reg, parcelas_geom, aoi.crs).to_file(capas / "parcelas.gpkg", driver="GPKG")

    def puntos_pozos(ids, tipo, extra=None):
        registros, geoms = [], []
        for n, pid in enumerate(ids, start=1):
            centro = parcelas_m.loc[parcelas_m["id_parcela"] == pid].geometry.iloc[0].centroid
            fila = {"id_pozo": f"{tipo[:4].upper()}-{n:03d}", "tipo": tipo, "id_parcela": pid, "sintetico": True}
            if extra:
                fila.update(extra)
            registros.append(fila)
            geoms.append(Point(centro.x, centro.y))
        return _gdf(registros, geoms, aoi.crs)

    puntos_pozos(ids_pozo_legal, "registrado").to_file(capas / "pozos_registrados.gpkg", driver="GPKG")
    puntos_pozos(
        ids_cono_cerrado + ids_cierre_sin_senal,
        "cerrado",
        {"fecha_cierre": "2024-11-01", "fuente": "CHG_sintetico"},
    ).to_file(capas / "pozos_cerrados.gpkg", driver="GPKG")
    puntos_pozos(ids_cono, "documentado_ilegal", {"fuente": "WWF_sintetico"}).to_file(
        capas / "puntos_wwf.gpkg", driver="GPKG"
    )

    sar_geom = box(malla["xmin"] + 50, malla["ymin"] + 50, xref - 500.0, malla["ymax"] - 50)
    _gdf([{"id": "SAR-sintetica", "sintetico": True, "nombre": "Superficie agraria regable (ficticia)"}],
         [sar_geom], aoi.crs).to_file(capas / "sar.gpkg", driver="GPKG")

    _escribir_ndvi(cfg, parcelas_m, fechas, ids_barbecho, rng)
    _escribir_piezometros(cfg, aoi, xref, yref, conos_xy, fechas, rng)

    resumen = {
        "sintetico": True,
        "advertencia": (
            "Datos fabricados. Los pozos, la SAR y los piezómetros no son los de la CHG, "
            "el SIGPAC ni el SIA. Solo sirven para probar el código."
        ),
        "semilla": int(sint["semilla"]),
        "aoi": aoi.nombre,
        "resolucion_m": res,
        "n_fechas": len(fechas),
        "n_interferogramas": len(pares),
        "n_parcelas": int(len(parcelas_m)),
        "n_parcelas_dentro_sar": n_legal,
        "conos_cerrados": ids_cono_cerrado,
        "conos_activos_no_cerrados": ids_cono_activo,
        "cierres_sin_senal_inyectada": ids_cierre_sin_senal,
        "pozos_registrados": ids_pozo_legal,
        "amplitud_cono_mm": amp_cono,
        "sigma_cono_m": sigma,
    }
    guardar_json(ruta_proyecto(cfg, "capas").parent / "MANIFIESTO_SINTETICO.json", resumen)
    log.info(
        "Escena sintética: %d interferogramas, %d parcelas, %d conos.",
        len(pares),
        len(parcelas_m),
        len(ids_cono),
    )
    return resumen


def _serie_desplazamiento(fechas: list[date], amplitud: np.ndarray, velocidad: np.ndarray) -> np.ndarray:
    """d(t) = v·años − A·cos(2π·(doy−135)/365.25). El mínimo cae a mediados de mayo."""
    serie = np.zeros((len(fechas),) + amplitud.shape, dtype=np.float64)
    t0 = fechas[0]
    for k, fecha in enumerate(fechas):
        anios = (fecha - t0).days / 365.25
        doy = fecha.timetuple().tm_yday
        estacional = -amplitud * np.cos(2.0 * np.pi * (doy - 135) / 365.25)
        serie[k] = velocidad * anios + estacional
    return serie


def _escribir_tif(ruta, fase, coherencia, transform, crs: str) -> None:
    pila = np.stack([fase.astype(np.float32), coherencia.astype(np.float32)])
    perfil = {
        "driver": "GTiff",
        "height": fase.shape[0],
        "width": fase.shape[1],
        "count": 2,
        "dtype": "float32",
        "crs": crs,
        "transform": transform,
        "compress": "deflate",
    }
    with rasterio.open(ruta, "w", **perfil) as dst:
        dst.write(pila)
        dst.set_band_description(1, "unwrappedPhase_rad")
        dst.set_band_description(2, "coherence")


def _escribir_ndvi(cfg, parcelas_m, fechas, ids_barbecho, rng) -> None:
    meses = set(cfg["score"]["meses_campana"])
    filas = []
    for pid in parcelas_m["id_parcela"]:
        activo = pid not in ids_barbecho
        for fecha in fechas:
            if fecha.month in meses:
                base = 0.66 if activo else 0.22
            else:
                base = 0.18 if activo else 0.20
            filas.append(
                {
                    "id_parcela": pid,
                    "fecha": fecha.isoformat(),
                    "ndvi": float(np.clip(base + rng.normal(0, 0.02), 0, 1)),
                }
            )
    destino = ruta_proyecto(cfg, "ndvi")
    asegurar_directorio(destino.parent)
    import pandas as pd

    pd.DataFrame(filas).to_csv(destino, index=False)


def _escribir_piezometros(cfg, aoi, xref, yref, conos_xy, fechas, rng) -> None:
    # Dos junto a conos, uno en la zona legal, uno al norte y lejos del cluster.
    if len(conos_xy) < 2:
        return
    sitios = [
        ("PZ-cerca-1", conos_xy[0][0] + 180, conos_xy[0][1] + 80, 2.4),
        ("PZ-cerca-2", conos_xy[1][0] - 120, conos_xy[1][1] + 60, 1.8),
        ("PZ-legal", xref - 1400, yref + 200, 0.35),
        ("PZ-lejos", xref, yref + 2200, 0.25),
    ]
    registros, geoms, niveles = [], [], []
    for pid, x, y, amp in sitios:
        registros.append({"id_piezometro": pid, "sintetico": True, "amplitud_descenso_m": amp})
        geoms.append(Point(x, y))
        for fecha in fechas:
            doy = fecha.timetuple().tm_yday
            # Profundidad mayor (nivel más bajo) en el pico de mayo.
            campana = max(0.0, np.cos(2.0 * np.pi * (doy - 135) / 365.25))
            profundidad = 8.0 + amp * campana + float(rng.normal(0, 0.05))
            niveles.append(
                {"id_piezometro": pid, "fecha": fecha.isoformat(), "profundidad_m": profundidad}
            )
    capas = ruta_proyecto(cfg, "capas")
    _gdf(registros, geoms, aoi.crs).to_file(capas / "piezometros.gpkg", driver="GPKG")
    import pandas as pd

    pd.DataFrame(niveles).to_csv(capas / "piezometros_niveles.csv", index=False)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Genera la escena sintética de la PoC.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    generar(cargar_config(args.config))


if __name__ == "__main__":
    main()
