"""Puente hacia la opción B (MintPy / SBAS), sin ejecutar MintPy.

La opción A apila GUNW ya desenvueltos. Si la amplitud estacional se queda
por debajo del ruido, la spec pide no abandonar el enfoque: pasar a un SBAS
completo sobre Sentinel-1 SLC (ISCE2 + MintPy) y usar los GUNW de NISAR como
contraste de coherencia en banda L.

Este módulo:
- escribe una plantilla de `smallbaselineApp.cfg`;
- si alguien ya ha corrido MintPy, convierte `timeseries.h5` al NPZ que lee
  `medir.py`, para no reimplementar el score.

No importa mintpy. El entorno con MintPy e ISCE2 está en
`environment-opcion-b.yml` y los pasos, en `docs/08-opcion-b-mintpy.md`.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from utilidades import RAIZ, afin_a_lista, asegurar_directorio, cargar_config, guardar_json, ruta_proyecto

log = logging.getLogger("poc.mintpy")

PLANTILLA_CFG = """## Plantilla smallbaselineApp.cfg para la tesela de Rociana.
## Las rutas son las que deja ISCE2 topsStack. Ajustarlas al directorio real.
mintpy.load.processor        = isce
mintpy.load.unwFile          = ../isce/merged/interferograms/*/filt_fine.unw
mintpy.load.corFile          = ../isce/merged/interferograms/*/filt_fine.cor
mintpy.load.connCompFile     = ../isce/merged/interferograms/*/filt_fine.unw.conncomp
mintpy.load.demFile          = ../isce/merged/geom_reference/hgt.rdr
mintpy.reference.lalo        = 37.30, -6.58
mintpy.network.coherenceBased = yes
mintpy.network.minCoherence  = 0.4
mintpy.troposphericDelay.method = pyaps
mintpy.deramp                = linear
mintpy.timeFunc              = polynomial 1
"""


def escribir_plantilla(destino: Path | None = None) -> Path:
    destino = destino or (RAIZ / "config" / "mintpy_smallbaselineApp.cfg")
    asegurar_directorio(destino.parent)
    destino.write_text(PLANTILLA_CFG, encoding="utf-8")
    return destino


def convertir_timeseries(ruta_h5: Path, directorio_salida: Path, cfg: dict) -> Path:
    """Pasa un timeseries.h5 de MintPy al NPZ de la opción A.

    MintPy guarda el desplazamiento en metros, con atributos X_FIRST, Y_FIRST,
    X_STEP, Y_STEP y las fechas en el dataset `date`.
    """
    import h5py
    from rasterio.transform import Affine

    with h5py.File(ruta_h5, "r") as handle:
        serie_m = np.asarray(handle["timeseries"][...], dtype=np.float64)
        fechas_raw = handle["date"][...]
        atributos = {k: _texto(v) for k, v in handle.attrs.items()}
    fechas = []
    for valor in fechas_raw:
        texto = _texto(valor)
        fechas.append(f"{texto[0:4]}-{texto[4:6]}-{texto[6:8]}")
    x0 = float(atributos["X_FIRST"])
    y0 = float(atributos["Y_FIRST"])
    dx = float(atributos["X_STEP"])
    dy = float(atributos["Y_STEP"])
    transform = Affine(dx, 0.0, x0, 0.0, dy, y0)
    # La coherencia temporal, si viene en un HDF5 hermano, no es obligatoria:
    # sin ella el criterio de coherencia quedará indeterminado y hay que mirarlo en MintPy.
    coherencia = np.ones(serie_m.shape[1:], dtype=np.float64)
    temporal = atributos.get("temporalCoherence")
    del temporal
    asegurar_directorio(directorio_salida)
    np.savez_compressed(
        directorio_salida / "serie_mm.npz",
        serie_mm=serie_m * 1000.0,
        fechas=np.array(fechas),
        coherencia_media=coherencia,
        coherencia_campana=coherencia,
    )
    guardar_json(
        directorio_salida / "metadatos.json",
        {
            "plataforma": "SENTINEL-1",
            "n_fechas": len(fechas),
            "fechas": fechas,
            "crs": cfg.get("crs_metrico", "EPSG:25829"),
            "transform": afin_a_lista(transform),
            "shape": list(serie_m.shape[1:]),
            "fila_referencia": int(atributos.get("REF_Y", 0) or 0),
            "columna_referencia": int(atributos.get("REF_X", 0) or 0),
            "signo_fase": 1.0,
            "longitud_onda_m": 0.05546576,
            "umbral_coherencia": float(cfg["procesado"]["coherencia_min"]),
            "modo": "mintpy",
            "aoi": cfg["aoi"]["activa"],
            "origen": str(ruta_h5),
        },
    )
    log.info(
        "Serie MintPy convertida. La coherencia se ha rellenado con 1: "
        "el criterio de coherencia no es válido hasta sustituirla por temporalCoherence.h5."
    )
    return directorio_salida / "serie_mm.npz"


def _texto(valor) -> str:
    if isinstance(valor, bytes):
        return valor.decode()
    if isinstance(valor, np.ndarray):
        if valor.shape == ():
            return _texto(valor.item())
        if valor.size and isinstance(valor.flat[0], bytes):
            return valor.flat[0].decode()
    return str(valor)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Plantilla MintPy y conversor de timeseries.h5.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--timeseries", default=None, help="Ruta a un timeseries.h5 ya calculado por MintPy.")
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    plantilla = escribir_plantilla()
    log.info("Plantilla escrita en %s", plantilla)
    if args.timeseries:
        convertir_timeseries(Path(args.timeseries), ruta_proyecto(cfg, "procesado"), cfg)
    else:
        log.info(
            "No se ha pasado --timeseries. MintPy no se ejecuta desde aquí. "
            "Pasos en docs/08-opcion-b-mintpy.md."
        )


if __name__ == "__main__":
    main()
