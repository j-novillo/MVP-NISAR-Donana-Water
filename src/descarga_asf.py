"""Búsqueda y descarga en el ASF de la NASA (NISAR GUNW y Sentinel-1).

La búsqueda del catálogo es pública. La descarga exige `EARTHDATA_TOKEN`
(token de portador de Earthdata). El token no se escribe en logs ni en el CSV
de catálogo.

NISAR GUNW es el producto de la opción A. Los GUNW de ARIA (Sentinel-1) son
los interferogramas preprocesados que alargan la serie mientras NISAR sigue
siendo corta. Los SLC de Sentinel-1 solo se piden si `descarga.sentinel1_slc`
está a true: pesan mucho y hacen falta para la opción B, no para la A.
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import pandas as pd

from utilidades import asegurar_directorio, cargar_config, cargar_dotenv, resolver_aoi, ruta_proyecto

log = logging.getLogger("poc.asf")


class CredencialesError(RuntimeError):
    """Falta un secreto que tiene que venir del entorno."""


def sesion_asf():
    """Abre una sesión ASF. Si hay token, lo usa; si no, la sesión vale para buscar."""
    import asf_search as asf

    sesion = asf.ASFSession()
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if token:
        sesion.auth_with_token(token)
    return sesion


def exigir_token() -> str:
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        raise CredencialesError(
            "Falta EARTHDATA_TOKEN para descargar de ASF. "
            "Cree un token en https://urs.earthdata.nasa.gov/ y expórtelo, "
            "o póngalo en .env (vea .env.example). "
            "Para solo listar el catálogo use --listar: no hace falta token."
        )
    return token


def construir_busquedas(cfg: dict) -> list[dict]:
    """Parámetros de `asf.search` para las colecciones activas en la config.

    No llama a la red. Así se puede comprobar el filtro en un test.
    """
    aoi = resolver_aoi(cfg)
    desc = cfg["descarga"]
    wkt = aoi.wkt()
    busquedas = []
    if desc.get("nisar_gunw", True):
        busquedas.append(
            {
                "nombre": "NISAR_GUNW",
                "dataset": "NISAR",
                "processingLevel": "GUNW",
                "intersectsWith": wkt,
                "start": desc.get("nisar_inicio", "2025-10-01"),
                "maxResults": int(desc.get("max_productos", 30)),
            }
        )
    if desc.get("sentinel1_gunw_aria", True):
        busquedas.append(
            {
                "nombre": "ARIA_S1_GUNW",
                "dataset": "ARIA S1 GUNW",
                "processingLevel": "GUNW_STD",
                "intersectsWith": wkt,
                "start": desc.get("sentinel1_inicio", "2022-01-01"),
                "end": desc.get("sentinel1_fin"),
                "maxResults": int(desc.get("max_productos", 30)),
            }
        )
    if desc.get("sentinel1_slc", False):
        for direccion in ("ASCENDING", "DESCENDING"):
            busquedas.append(
                {
                    "nombre": f"S1_SLC_{direccion}",
                    "platform": "SENTINEL-1",
                    "processingLevel": "SLC",
                    "beamMode": "IW",
                    "flightDirection": direccion,
                    "intersectsWith": wkt,
                    "start": desc.get("sentinel1_inicio", "2022-01-01"),
                    "end": desc.get("sentinel1_fin"),
                    "maxResults": int(desc.get("max_productos", 30)),
                }
            )
    return busquedas


def _fila_catalogo(producto, coleccion: str) -> dict:
    props = producto.properties
    return {
        "coleccion": coleccion,
        "scene_name": props.get("sceneName") or props.get("fileID"),
        "plataforma": props.get("platform"),
        "nivel": props.get("processingLevel"),
        "inicio": props.get("startTime"),
        "fin": props.get("stopTime"),
        "url": props.get("url"),
        "traza": props.get("pathNumber"),
        "marco": props.get("frameNumber"),
    }


def buscar(cfg: dict):
    """Ejecuta las búsquedas y devuelve (nombre, resultados ASF)."""
    import asf_search as asf

    salida = []
    for parametros in construir_busquedas(cfg):
        nombre = parametros["nombre"]
        kwargs = {k: v for k, v in parametros.items() if k != "nombre" and v is not None}
        log.info("ASF %s", nombre)
        try:
            resultados = asf.search(**kwargs)
        except Exception as exc:
            log.warning("La búsqueda %s ha fallado: %s", nombre, exc.__class__.__name__)
            resultados = []
        salida.append((nombre, resultados))
        log.info("  %d productos", len(resultados))
    return salida


def guardar_catalogo(grupos, destino: Path) -> pd.DataFrame:
    filas = []
    for nombre, resultados in grupos:
        for producto in resultados:
            filas.append(_fila_catalogo(producto, nombre))
    tabla = pd.DataFrame(filas)
    asegurar_directorio(destino.parent)
    tabla.to_csv(destino, index=False)
    log.info("Catálogo ASF en %s (%d filas)", destino, len(tabla))
    return tabla


def descargar(cfg: dict, grupos) -> None:
    """Descarga los productos encontrados. Exige token."""
    exigir_token()
    sesion = sesion_asf()
    directorio = asegurar_directorio(ruta_proyecto(cfg, "interferogramas"))
    slc_dir = asegurar_directorio(directorio.parent / "sentinel1_slc")
    for nombre, resultados in grupos:
        if not resultados:
            continue
        destino = slc_dir if nombre.startswith("S1_SLC") else directorio
        log.info("Descargando %d productos de %s en %s", len(resultados), nombre, destino)
        resultados.download(path=str(destino), session=sesion)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Busca (y opcionalmente descarga) NISAR y Sentinel-1 en ASF.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--listar", action="store_true", help="Solo escribe el CSV del catálogo, sin descargar.")
    args = parser.parse_args(argv)
    cargar_dotenv()
    cfg = cargar_config(args.config)
    grupos = buscar(cfg)
    catalogo = ruta_proyecto(cfg, "interferogramas").parent / "catalogo_asf.csv"
    guardar_catalogo(grupos, catalogo)
    if not args.listar:
        descargar(cfg, grupos)


if __name__ == "__main__":
    main()
