"""Convierte productos HyP3 INSAR_GAMMA a GeoTIFF de 2 bandas + JSON.

El zip de HyP3 trae fase desenvuelta y coherencia (y, si se pidió,
mapas de desplazamiento). Este script deja en `data/raw/interferogramas/`
un GeoTIFF compatible con `lectura_gunw.leer_geotiff` y un sidecar JSON
con plataforma SENTINEL-1, fechas y longitud de onda C-banda.

No descarga: opera sobre los zip ya bajados en `data/raw/hyp3_s1/`.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio
from rasterio.windows import from_bounds, transform as window_transform
from rasterio.transform import Affine

from utilidades import cargar_config, ruta_proyecto, asegurar_directorio, resolver_aoi

log = logging.getLogger("poc.hyp3")

# Longitud de onda Sentinel-1 C-banda (m).
ONDA_S1 = 0.05546576


def _fechas_desde_nombre(nombre: str) -> tuple[str, str] | None:
    # S1AA_20240519T182656_20240916T182655_...
    m = re.findall(r"(20\d{6})T\d{6}", nombre)
    if len(m) >= 2:
        return m[0], m[1]
    return None


def _buscar_en_zip(z: zipfile.ZipFile, *sufijos: str) -> str | None:
    nombres = z.namelist()
    for suf in sufijos:
        for n in nombres:
            if n.lower().endswith(suf.lower()) and not n.endswith("/"):
                return n
    return None


def convertir_zip(ruta_zip: Path, destino_dir: Path, bbox_4326: tuple[float,float,float,float] | None = None) -> Path | None:
    """Extrae fase+coherencia a un GeoTIFF de 2 bandas. Devuelve la ruta o None."""
    with zipfile.ZipFile(ruta_zip, "r") as z:
        unw = _buscar_en_zip(z, "_unw_phase.tif", "unw_phase.tif")
        corr = _buscar_en_zip(z, "_corr.tif", "corr.tif")
        if unw is None or corr is None:
            log.warning("%s: no encuentro unw_phase/corr", ruta_zip.name)
            return None
        fechas = _fechas_desde_nombre(ruta_zip.name) or _fechas_desde_nombre(unw)
        if not fechas:
            log.warning("%s: no puedo sacar fechas", ruta_zip.name)
            return None
        fref, fsec = fechas
        with z.open(unw) as fh_u, rasterio.MemoryFile(fh_u.read()) as mem_u:
            with mem_u.open() as src_u:
                fase = src_u.read(1).astype(np.float64)
                transform = src_u.transform
                crs = src_u.crs
                profile = src_u.profile
        with z.open(corr) as fh_c, rasterio.MemoryFile(fh_c.read()) as mem_c:
            with mem_c.open() as src_c:
                coh = src_c.read(1).astype(np.float64)
        if fase.shape != coh.shape:
            log.warning("%s: formas distintas fase/coh", ruta_zip.name)
            return None
        # Coherencia HyP3 a veces viene 0-255
        if np.nanmax(coh) > 1.5:
            coh = coh / 255.0
        # Recorte al AOI si se pasa bbox lon/lat (HyP3 suele estar en UTM).
        if bbox_4326 is not None and crs is not None:
            from pyproj import Transformer
            lon0,lat0,lon1,lat1=bbox_4326
            # reproyectar esquinas del AOI al CRS del producto
            tf=Transformer.from_crs("EPSG:4326", crs, always_xy=True)
            xs,ys=zip(*(tf.transform(x,y) for x,y in [(lon0,lat0),(lon1,lat0),(lon1,lat1),(lon0,lat1)]))
            win=from_bounds(min(xs), min(ys), max(xs), max(ys), transform=transform)
            # re-read with window for exact alignment
            row_off=max(0,int(win.row_off)); col_off=max(0,int(win.col_off))
            h=min(fase.shape[0]-row_off, max(1,int(win.height)+1))
            w=min(fase.shape[1]-col_off, max(1,int(win.width)+1))
            fase=fase[row_off:row_off+h, col_off:col_off+w]
            coh=coh[row_off:row_off+h, col_off:col_off+w]
            from rasterio.windows import Window
            transform=window_transform(Window(col_off,row_off,w,h), transform)
            profile.update(height=fase.shape[0], width=fase.shape[1], transform=transform)
        out = destino_dir / f"S1_GUNW_{fref}_{fsec}.tif"
        profile.update(count=2, dtype="float32", compress="deflate", tiled=True,
                        blockxsize=min(512, fase.shape[1]), blockysize=min(512, fase.shape[0]))
        # block sizes must be multiples of 16 for some drivers; fall back if needed
        try:
            bx=max(16, (profile["blockxsize"]//16)*16)
            by=max(16, (profile["blockysize"]//16)*16)
            profile.update(blockxsize=bx, blockysize=by)
        except Exception:
            profile.pop("blockxsize", None); profile.pop("blockysize", None); profile["tiled"]=False
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(fase.astype(np.float32), 1)
            dst.write(coh.astype(np.float32), 2)
        sidecar = {
            "plataforma": "SENTINEL-1",
            "fecha_referencia": datetime.strptime(fref, "%Y%m%d").date().isoformat(),
            "fecha_secundaria": datetime.strptime(fsec, "%Y%m%d").date().isoformat(),
            "longitud_onda_m": ONDA_S1,
            "origen": "hyp3_insar_gamma",
            "zip": ruta_zip.name,
        }
        out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
        log.info("Escrito %s", out.name)
        return out


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Convierte zips HyP3 a GeoTIFF GUNW.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--entrada", default=None, help="Directorio con zips HyP3")
    args = parser.parse_args(argv)
    cfg = cargar_config(args.config)
    entrada = Path(args.entrada) if args.entrada else ruta_proyecto(cfg, "interferogramas").parent / "hyp3_s1"
    destino = asegurar_directorio(ruta_proyecto(cfg, "interferogramas"))
    zips = sorted(entrada.glob("*.zip"))
    if not zips:
        log.warning("No hay zips en %s", entrada)
        return
    aoi = resolver_aoi(cfg)
    bbox = (aoi.lon_min, aoi.lat_min, aoi.lon_max, aoi.lat_max)
    for z in zips:
        convertir_zip(z, destino, bbox_4326=bbox)


if __name__ == "__main__":
    main()
