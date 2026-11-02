"""Cliente del Copernicus Data Space Ecosystem (catálogo OData y descarga).

El catálogo se consulta sin credenciales. La descarga necesita un token.

Preferir `CDSE_USERNAME` y `CDSE_PASSWORD`: el access token caduca en unos
10-30 minutos y este cliente lo renueva solo (grant de contraseña la primera
vez, grant de refresh después). `CDSE_ACCESS_TOKEN` se acepta como alternativa,
pero cuando caduca no hay forma de renovarlo y la descarga falla con un 401.

No se registran usuario, contraseña ni token.
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from pathlib import Path
from urllib.parse import quote

import requests

from utilidades import cargar_config, cargar_dotenv, resolver_aoi, ruta_proyecto, asegurar_directorio

log = logging.getLogger("poc.cdse")

URL_TOKEN = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
URL_CATALOGO = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
URL_DESCARGA = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({})/$value"


class CredencialesError(RuntimeError):
    """Faltan las variables de Copernicus o el token ha caducado."""


class ClienteCDSE:
    """Access token con renovación.

    El reloj de caducidad se adelanta dos minutos para no usar un token a
    punto de morir a mitad de una descarga.
    """

    def __init__(self, sesion: requests.Session | None = None):
        self.usuario = os.environ.get("CDSE_USERNAME", "").strip()
        self.clave = os.environ.get("CDSE_PASSWORD", "").strip()
        self._token = os.environ.get("CDSE_ACCESS_TOKEN", "").strip() or None
        self._refresh = None
        self._expira = time.time() + 60 if self._token else 0.0
        self._sesion = sesion or requests.Session()
        self._token_fijo = bool(self._token) and not (self.usuario and self.clave)

    def token(self) -> str:
        if self.usuario and self.clave:
            if time.time() >= self._expira - 120 or not self._token:
                self._renovar()
            return self._token
        if self._token:
            return self._token
        raise CredencialesError(
            "Faltan credenciales de Copernicus. Defina CDSE_USERNAME y CDSE_PASSWORD "
            "(recomendado: el token se renueva solo) o CDSE_ACCESS_TOKEN. "
            "Vea .env.example. La búsqueda del catálogo (--listar) no las necesita."
        )

    def _renovar(self) -> None:
        if self._refresh:
            datos = {
                "client_id": "cdse-public",
                "grant_type": "refresh_token",
                "refresh_token": self._refresh,
            }
        else:
            datos = {
                "client_id": "cdse-public",
                "grant_type": "password",
                "username": self.usuario,
                "password": self.clave,
            }
        try:
            respuesta = self._sesion.post(URL_TOKEN, data=datos, timeout=60)
            respuesta.raise_for_status()
        except requests.RequestException as exc:
            # No incluir el cuerpo: puede hacer eco de las credenciales.
            raise CredencialesError(
                f"Copernicus ha rechazado la petición de token (HTTP {getattr(exc.response, 'status_code', '?')}). "
                "Revise CDSE_USERNAME y CDSE_PASSWORD."
            ) from exc
        cuerpo = respuesta.json()
        self._token = cuerpo["access_token"]
        self._refresh = cuerpo.get("refresh_token", self._refresh)
        self._expira = time.time() + float(cuerpo.get("expires_in", 600))

    def cabeceras(self) -> dict:
        return {"Authorization": f"Bearer {self.token()}"}


def poligono_odata(wkt: str) -> str:
    """Adapta el WKT del AOI al literal geography de OData."""
    return f"geography'SRID=4326;{wkt}'"


def filtros_productos(cfg: dict) -> list[tuple[str, str]]:
    """Pares (nombre, filtro OData) de las colecciones pedidas en la config."""
    aoi = resolver_aoi(cfg)
    area = poligono_odata(aoi.wkt())
    desc = cfg["descarga"]
    filtros = []
    if desc.get("sentinel1_slc", False):
        inicio = desc.get("sentinel1_inicio", "2022-01-01")
        fin = desc.get("sentinel1_fin", "2026-12-31")
        filtros.append(
            (
                "SENTINEL-1_SLC",
                (
                    "Collection/Name eq 'SENTINEL-1' and "
                    "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
                    "and att/OData.CSC.StringAttribute/Value eq 'SLC') and "
                    f"OData.CSC.Intersects(area={area}) and "
                    f"ContentDate/Start gt {inicio}T00:00:00.000Z and "
                    f"ContentDate/Start lt {fin}T00:00:00.000Z"
                ),
            )
        )
    if desc.get("sentinel2_l2a", True):
        inicio = desc.get("sentinel2_inicio", "2022-01-01")
        nubes = float(desc.get("sentinel2_nubes_max", 20))
        filtros.append(
            (
                "SENTINEL-2_L2A",
                (
                    "Collection/Name eq 'SENTINEL-2' and "
                    "Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' "
                    "and att/OData.CSC.StringAttribute/Value eq 'S2MSI2A') and "
                    "Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' "
                    f"and att/OData.CSC.DoubleAttribute/Value lt {nubes}) and "
                    f"OData.CSC.Intersects(area={area}) and "
                    f"ContentDate/Start gt {inicio}T00:00:00.000Z"
                ),
            )
        )
    if desc.get("dem_glo30", True):
        # GLO-30 en la instancia DGED. El nombre del producto contiene GLO-30.
        filtros.append(
            (
                "COP-DEM_GLO-30",
                (
                    "Collection/Name eq 'COP-DEM' and contains(Name,'GLO-30') and "
                    f"OData.CSC.Intersects(area={area})"
                ),
            )
        )
    return filtros


def buscar(cfg: dict, sesion: requests.Session | None = None) -> list[dict]:
    """Lista productos del catálogo, sin descargarlos."""
    sesion = sesion or requests.Session()
    tope = int(cfg["descarga"].get("max_productos", 30))
    filas = []
    for nombre, filtro in filtros_productos(cfg):
        url = f"{URL_CATALOGO}?$filter={quote(filtro)}&$top={tope}&$orderby=ContentDate/Start desc"
        log.info("CDSE %s", nombre)
        try:
            respuesta = sesion.get(url, timeout=120)
            respuesta.raise_for_status()
            productos = respuesta.json().get("value", [])
        except requests.RequestException as exc:
            log.warning("Catálogo %s no disponible: %s", nombre, exc.__class__.__name__)
            productos = []
        log.info("  %d productos", len(productos))
        for producto in productos:
            filas.append(
                {
                    "coleccion": nombre,
                    "id": producto.get("Id"),
                    "nombre": producto.get("Name"),
                    "inicio": (producto.get("ContentDate") or {}).get("Start"),
                    "fin": (producto.get("ContentDate") or {}).get("End"),
                    "tamano": producto.get("ContentLength"),
                }
            )
    return filas


def descargar_producto(cliente: ClienteCDSE, producto_id: str, destino: Path) -> None:
    """Descarga un producto. Ante un 401 renueva el token una vez y reintenta."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    url = URL_DESCARGA.format(producto_id)
    for intento in (1, 2):
        with cliente._sesion.get(url, headers=cliente.cabeceras(), stream=True, timeout=300) as resp:
            if resp.status_code == 401 and intento == 1 and not cliente._token_fijo:
                cliente._expira = 0
                cliente._token = None
                continue
            if resp.status_code == 401:
                raise CredencialesError(
                    "Copernicus ha respondido 401. Si usa CDSE_ACCESS_TOKEN, ha caducado: "
                    "pase a CDSE_USERNAME y CDSE_PASSWORD para que se renueve solo."
                )
            resp.raise_for_status()
            with destino.open("wb") as fh:
                for trozo in resp.iter_content(chunk_size=1024 * 1024):
                    if trozo:
                        fh.write(trozo)
            return


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Busca y descarga Sentinel-1/2 y el DEM GLO-30 en Copernicus.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--listar", action="store_true")
    args = parser.parse_args(argv)
    cargar_dotenv()
    cfg = cargar_config(args.config)
    import pandas as pd

    filas = buscar(cfg)
    destino_csv = ruta_proyecto(cfg, "interferogramas").parent / "catalogo_cdse.csv"
    asegurar_directorio(destino_csv.parent)
    pd.DataFrame(filas).to_csv(destino_csv, index=False)
    log.info("Catálogo CDSE en %s (%d filas)", destino_csv, len(filas))
    if args.listar:
        return
    cliente = ClienteCDSE()
    # Fuerza la comprobación de credenciales antes de empezar a bajar.
    cliente.token()
    base = {
        "SENTINEL-1_SLC": ruta_proyecto(cfg, "interferogramas").parent / "sentinel1_slc",
        "SENTINEL-2_L2A": ruta_proyecto(cfg, "interferogramas").parent / "sentinel2_l2a",
        "COP-DEM_GLO-30": ruta_proyecto(cfg, "interferogramas").parent / "dem",
    }
    for fila in filas:
        carpeta = asegurar_directorio(base[fila["coleccion"]])
        nombre = fila["nombre"] or fila["id"]
        destino = carpeta / f"{nombre}.zip"
        if destino.exists() and destino.stat().st_size > 0:
            log.info("Ya existe %s", destino.name)
            continue
        log.info("Descargando %s", nombre)
        descargar_producto(cliente, fila["id"], destino)


if __name__ == "__main__":
    main()
