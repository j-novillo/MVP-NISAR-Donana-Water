"""Lectura local de EGMS y consulta oficial, sin descargar.

EGMS (European Ground Motion Service) sale de Sentinel-1. No es verdad de
terreno independiente de S1 y no entra en el RMSE de exactitud.

La API de archivo documentada es:
https://egms.land.copernicus.eu/insar-api/archive
Autenticación CLMS (clave de servicio → JWT → token corto). El bbox máximo
oficial es 5°. Este módulo solo construye el JSON de búsqueda. No llama a
la API salvo `--consultar`, que aquí no se usa en el agente cloud.

Leer un CSV L2 ya descargado:

    python src/leer_egms.py --csv data/raw/egms/producto.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from utilidades import RAIZ, guardar_json, resolver_aoi, cargar_config

API_ARCHIVO = "https://egms.land.copernicus.eu/insar-api/archive"


def consulta_archivo(lon_min: float, lat_min: float, lon_max: float, lat_max: float, release: str = "2020-2025") -> dict:
    """Cuerpo JSON de búsqueda. No se envía."""
    if (lon_max - lon_min) > 5 or (lat_max - lat_min) > 5:
        raise ValueError("El bbox EGMS no puede superar 5° por lado")
    return {
        "levels": ["L2B", "L3"],
        "releases": [release],
        "bbox": [[lon_min, lat_min], [lon_max, lat_max]],
    }


def resumir_csv_local(ruta: Path) -> dict:
    """Describe un CSV ya en disco. No calcula un porcentaje contra NISAR."""
    tabla = pd.read_csv(ruta)
    columnas = set(tabla.columns)
    velocidad = None
    for candidata in ("mean_velocity", "velocity", "mean_velocity_mm_year"):
        if candidata in columnas:
            velocidad = float(tabla[candidata].median())
            break
    return {
        "estado": "exploratorio",
        "n_filas": int(len(tabla)),
        "columnas": sorted(columnas),
        "mediana_velocidad_si_viene_en_el_csv": velocidad,
        "independiente_de_sentinel1": False,
        "puede_entrar_en_rmse": False,
        "nota": (
            "EGMS L2 está en mm a lo largo de la línea de visión de Sentinel-1 "
            "(o en componentes este/vertical en L3). No es GNSS."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--csv", default=None, help="CSV EGMS ya descargado. No se baja aquí.")
    parser.add_argument("--release", default="2020-2025")
    parser.add_argument("--salida", default="data/egms/consulta.json")
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    aoi = resolver_aoi(cfg)
    consulta = consulta_archivo(aoi.lon_min, aoi.lat_min, aoi.lon_max, aoi.lat_max, args.release)
    payload = {
        "api": API_ARCHIVO,
        "consultado": False,
        "consulta": consulta,
        "lectura_local": None,
    }
    if args.csv:
        payload["lectura_local"] = resumir_csv_local(Path(args.csv))
    destino = RAIZ / args.salida
    guardar_json(destino, payload)
    print(json.dumps({"consultado": False, "salida": str(destino)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
