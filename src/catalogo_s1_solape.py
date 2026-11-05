"""Catálogo Sentinel-1 en la ventana de un GUNW NISAR. No descarga.

Construye la búsqueda pública de ASF (CMR) para SLC IW que corten el AOI
entre dos fechas. Por defecto solo escribe el filtro. `--consultar` llama
a `asf_search` y guarda un CSV de metadatos. No pide escenas ni lanza HyP3.

Uso en el box, no en un agente que no deba tocar la red:

    python src/catalogo_s1_solape.py --inicio 2025-10-01 --fin 2025-12-31
    python src/catalogo_s1_solape.py --inicio 2025-10-01 --fin 2025-12-31 --consultar
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from utilidades import RAIZ, cargar_config, guardar_json, resolver_aoi


def parametros_slc(wkt: str, inicio: str, fin: str, direccion: str | None = None) -> dict:
    """Parámetros de asf.search para Sentinel-1 SLC IW. Sin red."""
    params = {
        "dataset": "SENTINEL-1",
        "processingLevel": "SLC",
        "beamMode": "IW",
        "intersectsWith": wkt,
        "start": inicio,
        "end": fin,
    }
    if direccion:
        params["flightDirection"] = direccion
    return params


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    parser.add_argument("--inicio", required=True, help="YYYY-MM-DD, inicio de la ventana NISAR")
    parser.add_argument("--fin", required=True, help="YYYY-MM-DD, fin de la ventana NISAR")
    parser.add_argument("--direccion", choices=["ASCENDING", "DESCENDING"], default=None)
    parser.add_argument(
        "--consultar",
        action="store_true",
        help="Llama al catálogo CMR. No descarga productos.",
    )
    parser.add_argument(
        "--salida",
        default="data/catalogo/s1_solape_nisar.json",
    )
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    aoi = resolver_aoi(cfg)
    params = parametros_slc(aoi.wkt(), args.inicio, args.fin, args.direccion)
    destino = RAIZ / args.salida
    payload = {
        "aoi": aoi.nombre,
        "consulta": params,
        "consultado": False,
        "n": None,
        "nota": "Solo metadatos. No lanza HyP3 ni descarga SLC.",
    }
    if args.consultar:
        import asf_search as asf

        resultados = asf.search(**params)
        filas = []
        for producto in resultados:
            props = producto.properties
            filas.append(
                {
                    "scene_name": props.get("sceneName") or props.get("fileID"),
                    "inicio": props.get("startTime"),
                    "fin": props.get("stopTime"),
                    "orbita": props.get("pathNumber"),
                    "direccion": props.get("flightDirection"),
                }
            )
        csv_path = destino.with_suffix(".csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        import pandas as pd

        pd.DataFrame(filas).to_csv(csv_path, index=False)
        payload["consultado"] = True
        payload["n"] = len(filas)
        payload["csv"] = str(csv_path)
    guardar_json(destino, payload)
    print(json.dumps({"n": payload["n"], "salida": str(destino)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
