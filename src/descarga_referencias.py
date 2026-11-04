#!/usr/bin/env python3
"""Descarga referencias de validación alrededor del AOI de Doñana.

Obtiene lo que es genuinamente descargable por HTTP/WFS y documenta el resto:

- Piezómetros MITECO (SIA) y CHG: geometrías WFS → GeoPackage.
- Captaciones CHG (ya cubiertas también por descarga_capas).
- Catálogo GNSS cercano (Nevada Geodetic Lab DataHoldings): coordenadas.
- EGMS: la API archive exige login CLMS; aquí solo se deja el esqueleto y
  un LEEME con el procedimiento.
- Series piezométricas temporales y series GNSS tenv3: NO hay endpoint
  público estable a día de hoy; se documenta la vía manual.
"""
from __future__ import annotations

import argparse
import csv
import logging
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import requests
from shapely.geometry import box

from utilidades import asegurar_directorio, cargar_config, guardar_json, resolver_aoi, ruta_proyecto

log = logging.getLogger("poc.referencias")

LEEME_EGMS = """EGMS (European Ground Motion Service)
=====================================

La API machine-to-machine está en:
  https://egms.land.copernicus.eu/insar-api/archive

Requiere cuenta en Copernicus Land Monitoring Service (CLMS) y un token de
API. Sin autenticación responde 401/\"Please log in\".

Pasos manuales:
1. Crear cuenta en https://land.copernicus.eu/ y aceptar las condiciones EGMS.
2. Generar el API token CLMS (documentación oficial de autenticación CLMS).
3. Buscar productos L2b (Basic/Calibrated) o L3 Ortho (ORTHO-UP / ORTHO-EAST)
   con bbox del AOI (máx. 5° de lado), p. ej. release 2020_2024.
4. Descargar los ZIP y dejarlos en data/raw/egms/.
5. Volver a ejecutar src/comparar_nisar_s1.py.

Visor: https://egms.land.copernicus.eu/
"""

LEEME_SERIES = """Series temporales que este script NO puede bajar solo
=====================================================

Piezómetros (niveles)
---------------------
- Visor CHG redes de control:
  https://idechg.chguadalquivir.es/geochg/areas/water-networks
  (Red de piezómetros → punto → parámetro → rango ≤ 12 años → gráfico).
- No hay API CSV pública documentada. Exportar a mano y guardar como
  data/raw/capas/piezometros_niveles.csv con columnas:
  id_piezometro,fecha,profundidad_m

GNSS (desplazamiento)
---------------------
- Catálogo de estaciones cercanas: data/raw/gnss/estaciones_cercanas.csv
  (generado desde NGL DataHoldings).
- Series NGL tenv3: a 2026-11 los URL
  https://geodesy.unr.edu/gps_timeseries/tenv3/IGS14/<CODE>.tenv3
  devolvían 404 para HUEL/HUE1/HULV/SEV1/LEBR.
- Alternativa: RINEX de la RAP (Junta de Andalucía) o ERGNSS (IGN) y
  procesar a ENU (p. ej. con PRIDE PPP-AR / GipsyX / RTKLIB) y proyectar a LOS.
  RAP: https://www.juntadeandalucia.es/institutodeestadisticaycartografia/rap/descarga-rinex
  IGN: https://datos-geodesia.ign.es/ERGNSS/
"""


def _get_json(sesion: requests.Session, url: str) -> dict | None:
    try:
        r = sesion.get(url, timeout=180)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        log.warning("Fallo %s: %s", url[:80], exc.__class__.__name__)
        return None


def descargar_piezometros_miteco(aoi, destino: Path, sesion: requests.Session) -> dict:
    """WFS que sí responde con geometrías (probado 2026-11-04)."""
    # Ampliar un poco el bbox para tener vecinos útiles.
    bbox = f"{aoi.lon_min - 0.2},{aoi.lat_min - 0.3},{aoi.lon_max + 0.2},{aoi.lat_max + 0.2},EPSG:4326"
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "RedPiezometrica",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox,
        "maxFeatures": "5000",
    }
    base = "https://gis.miteco.gob.es/geoserver/agua/RedPiezometrica/wfs"
    url = f"{base}?{urlencode(params)}"
    data = _get_json(sesion, url)
    if not data or not data.get("features"):
        return {"ok": False, "fuente": url, "error": "sin features"}
    gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")
    if "id_piezometro" not in gdf.columns:
        col = "pie_cod_eu" if "pie_cod_eu" in gdf.columns else "pie_nombre"
        gdf["id_piezometro"] = gdf[col].astype(str) if col in gdf.columns else [f"SIA-{i:04d}" for i in range(len(gdf))]
    gdf["sintetico"] = False
    asegurar_directorio(destino.parent)
    gdf.to_file(destino, driver="GPKG")
    return {"ok": True, "n": int(len(gdf)), "destino": str(destino), "fuente": url}


def descargar_piezometros_chg(aoi, destino: Path, sesion: requests.Session) -> dict:
    bbox = f"{aoi.lon_min - 0.2},{aoi.lat_min - 0.3},{aoi.lon_max + 0.2},{aoi.lat_max + 0.2},EPSG:4326"
    params = {
        "service": "WFS",
        "version": "1.1.0",
        "request": "GetFeature",
        "typeName": "ggiscloud_root:piezometros",
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox,
        "maxFeatures": "5000",
    }
    base = "https://idechg.chguadalquivir.es/geoserver/ggiscloud_root/ows"
    url = f"{base}?{urlencode(params)}"
    data = _get_json(sesion, url)
    if not data or not data.get("features"):
        return {"ok": False, "fuente": url, "error": "sin features"}
    gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:4326")
    if "id_piezometro" not in gdf.columns:
        col = "cod_estsub" if "cod_estsub" in gdf.columns else "id"
        gdf["id_piezometro"] = gdf[col].astype(str)
    gdf["sintetico"] = False
    asegurar_directorio(destino.parent)
    gdf.to_file(destino, driver="GPKG")
    return {"ok": True, "n": int(len(gdf)), "destino": str(destino), "fuente": url}


def catalogo_gnss_ngl(destino: Path, lat0=36.5, lat1=37.8, lon0=-7.5, lon1=-5.5) -> dict:
    """Filtra DataHoldings de NGL a un recuadro alrededor de Doñana."""
    url = "https://geodesy.unr.edu/NGLStationPages/DataHoldings.txt"
    try:
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        texto = r.text
    except Exception as exc:
        return {"ok": False, "error": f"{exc.__class__.__name__}: {exc}", "fuente": url}
    filas = []
    for line in texto.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        code = parts[0]
        try:
            lat = float(parts[1])
            lon = float(parts[2])
        except ValueError:
            continue
        if lon > 180:
            lon -= 360
        if lat0 <= lat <= lat1 and lon0 <= lon <= lon1:
            filas.append(
                {
                    "code": code,
                    "lat": lat,
                    "lon": lon,
                    "height_m": parts[3],
                    "start": parts[7],
                    "end": parts[8] if len(parts) > 8 else "",
                    "source": "NGL DataHoldings",
                }
            )
    asegurar_directorio(destino.parent)
    with destino.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["code", "lat", "lon", "height_m", "start", "end", "source"])
        writer.writeheader()
        writer.writerows(filas)
    return {"ok": True, "n": len(filas), "destino": str(destino), "fuente": url}


def escribir_leemes(base: Path) -> None:
    (base / "egms").mkdir(parents=True, exist_ok=True)
    (base / "gnss").mkdir(parents=True, exist_ok=True)
    (base / "egms" / "LEEME_EGMS.txt").write_text(LEEME_EGMS, encoding="utf-8")
    (base / "LEEME_SERIES_TEMPORALES.txt").write_text(LEEME_SERIES, encoding="utf-8")


def descargar(cfg: dict) -> dict:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    aoi = resolver_aoi(cfg)
    capas = asegurar_directorio(ruta_proyecto(cfg, "capas"))
    raw = capas.parent
    escribir_leemes(raw)
    sesion = requests.Session()
    sesion.headers["User-Agent"] = "MVP-NISAR-Donana-Water/referencias"
    estado = {
        "piezometros_miteco": descargar_piezometros_miteco(aoi, capas / "piezometros.gpkg", sesion),
        "piezometros_chg": descargar_piezometros_chg(aoi, capas / "piezometros_chg.gpkg", sesion),
        "gnss_catalogo": catalogo_gnss_ngl(raw / "gnss" / "estaciones_cercanas.csv"),
        "egms": {
            "ok": False,
            "error": "requiere login CLMS; ver data/raw/egms/LEEME_EGMS.txt",
        },
        "series_temporales": {
            "ok": False,
            "error": "ver data/raw/LEEME_SERIES_TEMPORALES.txt",
        },
    }
    guardar_json(capas / "estado_referencias.json", estado)
    for k, v in estado.items():
        log.info("%s: %s", k, "ok" if v.get("ok") else v.get("error"))
    return estado


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    descargar(cargar_config(args.config))


if __name__ == "__main__":
    main()
