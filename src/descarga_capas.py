"""Capas legales: WFS donde existe, instrucciones donde no.

- Captaciones de la CHG: WFS público de la IDE del Guadalquivir
  (`ggiscloud_root:captaciones_dph`), recortado al AOI. Es el mismo conjunto
  que datos.gob.es distribuye como shapefile de toda la cuenca.
- Piezómetros SIA: se intenta el WFS del geoserver de MITECO. Si no responde
  con geometrías, queda constancia y el paso manual está en la documentación.
- SIGPAC y el polígono SAR no tienen una descarga vectorial estable. El script
  no se los inventa: escribe qué hay que hacer a mano y sigue.

En modo sintético no se llama a este módulo: las capas ficticias las escribe
`sintetico.py`.
"""

from __future__ import annotations

import argparse
import logging
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

import geopandas as gpd
import requests
from shapely.geometry import box

from utilidades import asegurar_directorio, cargar_config, guardar_json, resolver_aoi, ruta_proyecto

log = logging.getLogger("poc.capas")

INSTRUCCIONES = """
Capas que este script no puede garantizar solas
===============================================

SIGPAC (parcelas)
-----------------
El WMS nacional (https://wms.mapa.gob.es/sigpac/wms y
https://sigpac-hubcloud.es/wms) solo dibuja. No devuelve el recinto.

1. Abra el visor SIGPAC: https://sigpac.mapa.gob.es/fega/visor/
   o el de la Junta de Andalucía:
   https://www.juntadeandalucia.es/agriculturaypesca/sigpac/
2. Municipios: Rociana del Condado y Almonte (Huelva, provincia 21).
3. Exporte los recintos del AOI a shapefile o GeoPackage.
4. Guárdelo como data/raw/capas/parcelas.gpkg con una columna id_parcela.
   El score agrupa por ese identificador. Si no está, se inventa uno por fila,
   y entonces el NDVI (data/raw/ndvi/ndvi_parcelas.csv) no podrá unirse.

SAR (superficie agraria regable del Plan Especial de la Corona Forestal)
-------------------------------------------------------------------------
El polígono autorizado sale del Plan Especial de ordenación de las zonas de
regadío al norte de la corona forestal de Doñana (Junta de Andalucía, 2014)
y de sus actualizaciones. No hay un WFS estable.

1. Consiga el plano del plan o la capa que use la CHG / la Junta.
2. Si solo hay PDF, georreferéncielo en QGIS sobre el PNOA y digitalice el
   contorno, o pida la capa a la administración.
3. Guárdelo como data/raw/capas/sar.gpkg (un polígono, CRS conocido).

Pozos cerrados o precintados (verdad de campo)
----------------------------------------------
La CHG ha publicado cifras (del orden de 847 cierres desde 2024, y precintos)
en notas y boletines, no como un shapefile único descargable.

1. Reúna las resoluciones o el listado que facilite la CHG.
2. Georreferencie cada pozo (coordenadas del expediente, o a mano sobre la
   parcela).
3. Guárdelo como data/raw/capas/pozos_cerrados.gpkg con id_pozo y, si se sabe,
   fecha_cierre. Sin esta capa el criterio de recuerdo queda en "indeterminado".

Mapas WWF de regadío fuera de ordenación
----------------------------------------
Los informes de WWF sobre el entorno de Doñana traen cartografía de regadío
no autorizado. Si se consigue en vectorial, guárdela como
data/raw/capas/puntos_wwf.gpkg (puntos o polígonos). El validador la usa como
"documentado", junto a los pozos cerrados. No entra en el score.

Piezómetros (SIA, MITECO)
-------------------------
WMS: https://gis.miteco.gob.es/geoserver/agua/RedPiezometrica/wms
Visor: https://sig.mapama.gob.es/geoportal/
El script intenta el WFS homónimo. Si falla:

1. Localice los puntos de la red en el visor, dentro del AOI.
2. Exporte o copie coordenadas a data/raw/capas/piezometros.gpkg
   (columna id_piezometro).
3. Las series de nivel, en data/raw/capas/piezometros_niveles.csv con columnas
   id_piezometro, fecha, profundidad_m (profundidad del agua, mayor = nivel más bajo).

Nada de esto se versiona: data/raw está en .gitignore.
"""


def construir_url_wfs(base: str, typename: str, bbox: str, version: str = "1.1.0", limite: int = 5000) -> str:
    """URL GetFeature en GeoJSON, recortada por bbox."""
    parametros = {
        "service": "WFS",
        "version": version,
        "request": "GetFeature",
        "typeName": typename,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": bbox,
        "maxFeatures": str(limite),
    }
    separador = "&" if "?" in base else "?"
    return f"{base}{separador}{urlencode(parametros)}"


def _recortar(capa: gpd.GeoDataFrame, aoi) -> gpd.GeoDataFrame:
    if capa.crs is None:
        capa = capa.set_crs("EPSG:4326")
    else:
        capa = capa.to_crs("EPSG:4326")
    ventana = box(aoi.lon_min, aoi.lat_min, aoi.lon_max, aoi.lat_max)
    return capa[capa.geometry.intersects(ventana)].copy()


def descargar_chg(cfg: dict, destino: Path, sesion: requests.Session | None = None) -> dict:
    """Descarga las captaciones autorizadas de la CHG y las recorta al AOI."""
    sesion = sesion or requests.Session()
    aoi = resolver_aoi(cfg)
    remotas = cfg["capas_remotas"]
    url = construir_url_wfs(remotas["chg_wfs"], remotas["chg_typename"], aoi.bbox_wfs())
    try:
        respuesta = sesion.get(url, timeout=180)
        respuesta.raise_for_status()
        capa = gpd.read_file(BytesIO(respuesta.content))
    except Exception as exc:
        return {"ok": False, "fuente": url, "error": f"{exc.__class__.__name__}: {exc}"}
    recorte = _recortar(capa, aoi)
    if "id_pozo" not in recorte.columns:
        # El nombre real del expediente varía. Se conserva un identificador estable por fila.
        recorte["id_pozo"] = [f"CHG-{i:05d}" for i in range(len(recorte))]
    recorte["sintetico"] = False
    asegurar_directorio(destino.parent)
    recorte.to_file(destino, driver="GPKG")
    return {"ok": True, "fuente": url, "n": int(len(recorte)), "destino": str(destino)}


def intentar_piezometros(cfg: dict, destino: Path, sesion: requests.Session | None = None) -> dict:
    """Intenta el WFS de la red piezométrica. No falla el proceso si no responde."""
    sesion = sesion or requests.Session()
    aoi = resolver_aoi(cfg)
    base = cfg["capas_remotas"].get("sia_wfs")
    if not base:
        return {"ok": False, "error": "sin URL de WFS en la config"}
    # El nombre de la capa no es estable. Se pide GetCapabilities y se prueba
    # la primera capa que mencione piezo.
    try:
        caps = sesion.get(base, params={"service": "WFS", "request": "GetCapabilities"}, timeout=60)
        caps.raise_for_status()
        texto = caps.text
    except Exception as exc:
        return {"ok": False, "error": f"GetCapabilities: {exc.__class__.__name__}"}
    import re

    nombres = re.findall(r"<Name>([^<]*[Pp]iezo[^<]*)</Name>", texto)
    if not nombres:
        nombres = re.findall(r"<Name>([^<]+)</Name>", texto)[:3]
    errores = []
    for nombre in nombres:
        url = construir_url_wfs(base, nombre, aoi.bbox_wfs())
        try:
            respuesta = sesion.get(url, timeout=120)
            respuesta.raise_for_status()
            capa = gpd.read_file(BytesIO(respuesta.content))
        except Exception as exc:
            errores.append(f"{nombre}: {exc.__class__.__name__}")
            continue
        if capa.empty:
            continue
        recorte = _recortar(capa, aoi)
        if "id_piezometro" not in recorte.columns:
            recorte["id_piezometro"] = [f"SIA-{i:04d}" for i in range(len(recorte))]
        recorte["sintetico"] = False
        asegurar_directorio(destino.parent)
        recorte.to_file(destino, driver="GPKG")
        return {"ok": True, "capa": nombre, "n": int(len(recorte)), "destino": str(destino)}
    return {"ok": False, "error": "; ".join(errores) or "ninguna capa utilizable", "wms": cfg["capas_remotas"].get("sia_wms")}


def escribir_instrucciones(destino: Path) -> Path:
    asegurar_directorio(destino.parent)
    ruta = destino / "LEEME_CAPAS.txt"
    ruta.write_text(INSTRUCCIONES.strip() + "\n", encoding="utf-8")
    return ruta


def descargar(cfg: dict) -> dict:
    """Intenta CHG y SIA, deja las instrucciones de SIGPAC/SAR/cierres, y no aborta por una capa."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    capas = asegurar_directorio(ruta_proyecto(cfg, "capas"))
    instrucciones = escribir_instrucciones(capas)
    estado = {
        "chg": descargar_chg(cfg, capas / "pozos_registrados.gpkg"),
        "piezometros": intentar_piezometros(cfg, capas / "piezometros.gpkg"),
        "instrucciones": str(instrucciones),
        "pendiente_manual": ["parcelas.gpkg (SIGPAC)", "sar.gpkg", "pozos_cerrados.gpkg", "puntos_wwf.gpkg"],
    }
    guardar_json(capas / "estado_descarga.json", estado)
    for nombre, resultado in estado.items():
        if isinstance(resultado, dict):
            log.info("%s: %s", nombre, "ok" if resultado.get("ok") else resultado.get("error"))
    log.info("Pasos manuales en %s y en docs/02-descarga-de-datos.md", instrucciones)
    return estado


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Descarga capas CHG/SIA y documenta el resto.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    descargar(cargar_config(args.config))


if __name__ == "__main__":
    main()
