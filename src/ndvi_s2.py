"""NDVI de campaña a partir de Sentinel-2 L2A ya descargado.

No llama a la red. Recorre los SAFE / ZIP descomprimidos que haya dejado
`descarga_cdse.py`, calcula (B08 − B04) / (B08 + B04) y, si existe la banda
SCL, enmascara nubes, sombra y cirros.

El resultado es el mismo CSV que consume el score:
`id_parcela, fecha, ndvi` en `data/raw/ndvi/ndvi_parcelas.csv`.

Sin parcelas (SIGPAC) el script se detiene: un NDVI medio de todo el AOI no
sirve para el cruce por parcela.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from utilidades import cargar_config, ruta_proyecto

log = logging.getLogger("poc.ndvi")

# SCL de Sentinel-2: se quedan vegetación, suelo, agua y nieve clasificada como no-nube.
# Se tiran sin dato, saturado, sombra, nube media/alta, cirro y nieve/hielo fino si se prefiere
# ser conservador. Aquí se enmascaran las clases de nube y sombra.
SCL_NUBE = {0, 1, 3, 8, 9, 10}


def ndvi(rojo: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """Índice normalizado. NaN donde el denominador es cero."""
    rojo = np.asarray(rojo, dtype=np.float64)
    nir = np.asarray(nir, dtype=np.float64)
    denom = nir + rojo
    salida = np.full(rojo.shape, np.nan, dtype=np.float64)
    usable = np.isfinite(rojo) & np.isfinite(nir) & (np.abs(denom) > 1e-6)
    salida[usable] = (nir[usable] - rojo[usable]) / denom[usable]
    return salida


def enmascarar_scl(valores: np.ndarray, scl: np.ndarray) -> np.ndarray:
    """Pone NaN donde la escena está clasificada como nube, sombra o sin dato."""
    salida = np.array(valores, dtype=np.float64, copy=True)
    salida[np.isin(scl, list(SCL_NUBE))] = np.nan
    return salida


def _fecha_de_nombre(nombre: str) -> date | None:
    # S2A_MSIL2A_20240312T... 
    coincidencia = re.search(r"_(\d{8})T", nombre)
    if not coincidencia:
        return None
    texto = coincidencia.group(1)
    return date(int(texto[:4]), int(texto[4:6]), int(texto[6:8]))


def buscar_par_de_bandas(raiz: Path) -> list[tuple[Path, Path, Path | None, date | None]]:
    """Localiza parejas B04/B08 (y SCL si está) bajo un directorio de productos."""
    rojos = list(raiz.rglob("*B04*.jp2")) + list(raiz.rglob("*B04*.tif"))
    pares = []
    for rojo in rojos:
        nir = Path(str(rojo).replace("B04", "B08"))
        if not nir.is_file():
            continue
        scl_candidatos = list(rojo.parent.glob("*SCL*"))
        scl = scl_candidatos[0] if scl_candidatos else None
        pares.append((rojo, nir, scl, _fecha_de_nombre(rojo.name)))
    return pares


def media_por_parcela(ndvi_raster, transform, crs, parcelas) -> pd.Series:
    """Media del NDVI en cada parcela. Usa el centroide de la parcela muestreado en el raster."""
    import rasterio
    from rasterio.transform import rowcol

    if parcelas.crs is not None and str(parcelas.crs) != str(crs):
        parcelas = parcelas.to_crs(crs)
    medias = {}
    with np.errstate(all="ignore"):
        for _, fila in parcelas.iterrows():
            punto = fila.geometry.representative_point()
            try:
                r, c = rowcol(transform, punto.x, punto.y)
            except Exception:
                continue
            if r < 0 or c < 0 or r >= ndvi_raster.shape[0] or c >= ndvi_raster.shape[1]:
                continue
            # Ventana pequeña alrededor del punto, no un único píxel.
            r0, r1 = max(0, r - 2), min(ndvi_raster.shape[0], r + 3)
            c0, c1 = max(0, c - 2), min(ndvi_raster.shape[1], c + 3)
            ventana = ndvi_raster[r0:r1, c0:c1]
            if np.isfinite(ventana).any():
                medias[fila["id_parcela"]] = float(np.nanmean(ventana))
    return pd.Series(medias, name="ndvi")


def construir_csv(directorio_s2: Path, parcelas_ruta: Path, destino: Path) -> pd.DataFrame:
    """Recorre las escenas y escribe el CSV de NDVI por parcela y fecha."""
    import geopandas as gpd
    import rasterio

    if not parcelas_ruta.is_file():
        raise FileNotFoundError(
            f"No está {parcelas_ruta}. Hace falta el SIGPAC (o la capa sintética) "
            "antes de agregar el NDVI por parcela."
        )
    parcelas = gpd.read_file(parcelas_ruta)
    if "id_parcela" not in parcelas.columns:
        raise ValueError("parcelas.gpkg no tiene columna id_parcela")
    filas = []
    for rojo, nir, scl, fecha in buscar_par_de_bandas(directorio_s2):
        with rasterio.open(rojo) as src_r, rasterio.open(nir) as src_n:
            rojo_a = src_r.read(1).astype(np.float64)
            nir_a = src_n.read(1).astype(np.float64)
            # Reflectancia L2A escala 10000 si los valores vienen en enteros grandes.
            if np.nanmax(rojo_a) > 10:
                rojo_a = rojo_a / 10000.0
                nir_a = nir_a / 10000.0
            indice = ndvi(rojo_a, nir_a)
            if scl is not None:
                with rasterio.open(scl) as src_s:
                    scl_a = src_s.read(1)
                if scl_a.shape == indice.shape:
                    indice = enmascarar_scl(indice, scl_a)
            medias = media_por_parcela(indice, src_r.transform, src_r.crs, parcelas)
        for pid, valor in medias.items():
            filas.append({"id_parcela": pid, "fecha": (fecha or date.today()).isoformat(), "ndvi": valor})
        log.info("%s: %d parcelas con NDVI", rojo.name, len(medias))
    tabla = pd.DataFrame(filas)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tabla.to_csv(destino, index=False)
    return tabla


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="NDVI de Sentinel-2 L2A por parcela.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--escenas", default=None, help="Directorio con SAFE o JP2. Por defecto data/raw/sentinel2_l2a")
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    escenas = Path(args.escenas) if args.escenas else ruta_proyecto(cfg, "interferogramas").parent / "sentinel2_l2a"
    construir_csv(escenas, ruta_proyecto(cfg, "capas") / "parcelas.gpkg", ruta_proyecto(cfg, "ndvi"))


if __name__ == "__main__":
    main()
