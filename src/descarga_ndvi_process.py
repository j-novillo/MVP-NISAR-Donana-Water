"""NDVI mensual recortado vía Sentinel Hub Process API (CDSE).

Evita bajar los SAFE L2A completos (~1 GB/escena). Pide solo NDVI del AOI
con mosaico leastCC por mes. Requiere CDSE_USERNAME+CDSE_PASSWORD (renovable)
o CDSE_ACCESS_TOKEN (caduca en minutos).

Escribe GeoTIFF en data/raw/ndvi/mensual/ y un CSV AOI agregado.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import time
from calendar import monthrange
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from utilidades import cargar_config, cargar_dotenv, resolver_aoi, ruta_proyecto, asegurar_directorio

log = logging.getLogger("poc.ndvi_process")

URL_TOKEN = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
URL_PROCESS = "https://sh.dataspace.copernicus.eu/api/v1/process"

EVALSCRIPT = """//VERSION=3
function setup(){return{input:[{bands:["B04","B08","SCL","dataMask"]}],
output:[{id:"default",bands:1,sampleType:"FLOAT32"}]}}
function evaluatePixel(s){
  if(!s.dataMask) return [NaN];
  if(s.SCL==0||s.SCL==1||s.SCL==3||s.SCL==8||s.SCL==9||s.SCL==10) return [NaN];
  let d=s.B08+s.B04; if(!d) return [NaN];
  return [(s.B08-s.B04)/d];
}
"""


def token_cdse() -> str:
    user = os.environ.get("CDSE_USERNAME", "").strip()
    pwd = os.environ.get("CDSE_PASSWORD", "").strip()
    fixed = os.environ.get("CDSE_ACCESS_TOKEN", "").strip()
    if user and pwd and not (pwd.count(".") == 2 and len(pwd) > 200):
        r = requests.post(
            URL_TOKEN,
            data={"client_id": "cdse-public", "grant_type": "password", "username": user, "password": pwd},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["access_token"]
    if fixed:
        payload = json.loads(base64.urlsafe_b64decode(fixed.split(".")[1] + "=="))
        if payload.get("exp", 0) < time.time() + 30:
            raise RuntimeError("CDSE_ACCESS_TOKEN caducado. Use usuario/contraseña.")
        return fixed
    raise RuntimeError("Faltan CDSE_USERNAME/CDSE_PASSWORD o CDSE_ACCESS_TOKEN")


def descargar_mes(tok: str, aoi, y: int, m: int, destino: Path, res: float = 0.0001) -> bool:
    last = monthrange(y, m)[1]
    body = {
        "input": {
            "bounds": {
                "bbox": [aoi.lon_min, aoi.lat_min, aoi.lon_max, aoi.lat_max],
                "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{y:04d}-{m:02d}-01T00:00:00Z",
                        "to": f"{y:04d}-{m:02d}-{last:02d}T23:59:59Z",
                    },
                    "maxCloudCoverage": 80,
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {"resx": res, "resy": res, "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": EVALSCRIPT,
    }
    r = requests.post(
        URL_PROCESS,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Accept": "image/tiff"},
        data=json.dumps(body),
        timeout=180,
    )
    if r.status_code != 200 or len(r.content) < 500:
        log.warning("%04d-%02d HTTP %s", y, m, r.status_code)
        return False
    destino.write_bytes(r.content)
    return True


def main(argv=None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--inicio", default="2022-01")
    parser.add_argument("--fin", default="2026-10")
    args = parser.parse_args(argv)
    cargar_dotenv()
    cfg = cargar_config(args.config)
    aoi = resolver_aoi(cfg)
    out = asegurar_directorio(ruta_proyecto(cfg, "interferogramas").parent / "ndvi" / "mensual")
    tok = token_cdse()
    y0, m0 = map(int, args.inicio.split("-"))
    y1, m1 = map(int, args.fin.split("-"))
    y, m = y0, m0
    ok = 0
    while (y, m) <= (y1, m1):
        dest = out / f"ndvi_{y:04d}-{m:02d}.tif"
        if dest.exists() and dest.stat().st_size > 1000:
            log.info("skip %s", dest.name)
            ok += 1
        else:
            if descargar_mes(tok, aoi, y, m, dest):
                log.info("ok %s", dest.name)
                ok += 1
        m += 1
        if m > 12:
            m = 1
            y += 1
    log.info("meses ok=%d", ok)


if __name__ == "__main__":
    main()
