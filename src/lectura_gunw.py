"""Lectura de interferogramas geocodificados (GUNW).

La opción A parte de fase ya desenvuelta. Este módulo no desenvuelve nada:
lee el producto y lo traduce a desplazamiento en milímetros en la línea de
visión.

Formatos:
- GeoTIFF de dos bandas (fase en radianes, coherencia), con un JSON al lado.
  Es el formato del modo sintético y el que abre `rioxarray`.
- HDF5 de NISAR GUNW o de ARIA Sentinel-1 GUNW. Se intenta abrir el
  subdataset con rioxarray (driver HDF5 de GDAL) y, si el driver no está,
  se lee con h5py y se construye la georreferencia a partir de los ejes.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import numpy as np
import rioxarray
from rasterio.transform import Affine

from utilidades import parsear_fecha

log = logging.getLogger("poc.lectura")

# Rutas conocidas, de más específica a más genérica. El lector también
# recorre el archivo por si el producto usa otra polarización o frecuencia.
RUTAS_FASE = (
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/unwrappedPhase",
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/VV/unwrappedPhase",
    "science/grids/data/unwrappedPhase",
)
RUTAS_COHERENCIA = (
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/coherenceMagnitude",
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/VV/coherenceMagnitude",
    "science/grids/data/coherence",
)
RUTAS_COMPONENTES = (
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/HH/connectedComponents",
    "science/LSAR/GUNW/grids/frequencyA/unwrappedInterferogram/VV/connectedComponents",
    "science/grids/data/connectedComponents",
)


@dataclass
class Interferograma:
    """Un par ya geocodificado, en la rejilla nativa del archivo."""

    ruta: Path
    plataforma: str
    fecha_referencia: date
    fecha_secundaria: date
    longitud_onda_m: float
    fase_rad: np.ndarray
    coherencia: np.ndarray
    componentes: np.ndarray | None
    transform: Affine
    crs: str


def desplazamiento_mm(fase_rad: np.ndarray, longitud_onda_m: float, signo: float) -> np.ndarray:
    """Pasa fase desenvuelta (radianes) a desplazamiento LOS en milímetros.

    Con signo -1, un aumento de distancia al satélite (subsidencia, en una
    geometría casi vertical) sale negativo. El convenio real del producto
    hay que verificarlo: está expuesto en la configuración (`signo_fase`).
    """
    metros = signo * (longitud_onda_m / (4.0 * np.pi)) * np.asarray(fase_rad, dtype=np.float64)
    return metros * 1000.0


def fase_desde_desplazamiento_mm(
    desplazamiento_mm_: np.ndarray, longitud_onda_m: float, signo: float
) -> np.ndarray:
    """Inversa de `desplazamiento_mm`, usada al fabricar el modo sintético."""
    metros = np.asarray(desplazamiento_mm_, dtype=np.float64) / 1000.0
    return metros / (signo * (longitud_onda_m / (4.0 * np.pi)))


def _fechas_desde_nombre(nombre: str) -> tuple[date, date] | None:
    """Saca las dos épocas del nombre del gránulo.

    NISAR mete cuatro sellos (inicio/fin de referencia y de secundaria).
    ARIA y el modo sintético meten dos fechas YYYYMMDD.
    """
    sellos = re.findall(r"(\d{8})T\d{6}", nombre)
    if len(sellos) >= 3:
        return _yyyymmdd(sellos[0]), _yyyymmdd(sellos[2])
    if len(sellos) == 2:
        return _yyyymmdd(sellos[0]), _yyyymmdd(sellos[1])
    planos = re.findall(r"(?<!\d)(\d{8})(?!\d)", nombre)
    if len(planos) >= 2:
        return _yyyymmdd(planos[0]), _yyyymmdd(planos[1])
    return None


def _yyyymmdd(texto: str) -> date:
    return datetime.strptime(texto, "%Y%m%d").date()


def _leer_sidecar(ruta: Path) -> dict:
    candidato = ruta.with_suffix(".json")
    if candidato.is_file():
        return json.loads(candidato.read_text(encoding="utf-8"))
    return {}


def _metadatos(ruta: Path, cfg_onda: float) -> tuple[str, date, date, float]:
    lado = _leer_sidecar(ruta)
    plataforma = str(lado.get("plataforma", "DESCONOCIDA"))
    onda = float(lado.get("longitud_onda_m", cfg_onda))
    if "fecha_referencia" in lado and "fecha_secundaria" in lado:
        return (
            plataforma,
            parsear_fecha(lado["fecha_referencia"]),
            parsear_fecha(lado["fecha_secundaria"]),
            onda,
        )
    parseadas = _fechas_desde_nombre(ruta.name)
    if parseadas is None:
        raise ValueError(
            f"No puedo sacar las dos fechas de {ruta.name}. "
            "Añada un JSON homónimo con fecha_referencia y fecha_secundaria."
        )
    return plataforma, parseadas[0], parseadas[1], onda


def leer_geotiff(ruta: Path) -> tuple[np.ndarray, np.ndarray, Affine, str]:
    """Abre un GeoTIFF de fase/coherencia con rioxarray."""
    da = rioxarray.open_rasterio(ruta, masked=True)
    try:
        if "band" not in da.dims:
            raise ValueError(f"{ruta} no tiene dimensión de banda")
        fase = np.asarray(da.sel(band=1).values, dtype=np.float64)
        coherencia = np.asarray(da.sel(band=2).values, dtype=np.float64)
        transform = da.rio.transform()
        crs = da.rio.crs
        if crs is None:
            raise ValueError(f"{ruta} no trae CRS")
        return fase, coherencia, transform, str(crs)
    finally:
        da.close()


def _buscar_dataset(handle, rutas: tuple[str, ...], sufijo: str):
    """Devuelve el primer dataset que exista, o uno cuyo path termine en `sufijo`."""
    for ruta in rutas:
        if ruta in handle:
            return handle[ruta]
    encontrado = []

    def visitar(nombre, obj):
        if hasattr(obj, "shape") and nombre.lower().endswith(sufijo.lower()):
            encontrado.append(obj)

    handle.visititems(visitar)
    return encontrado[0] if encontrado else None


def _afin_desde_ejes(x: np.ndarray, y: np.ndarray) -> Affine:
    """Affine norte-arriba a partir de ejes 1D de centros de píxel."""
    x = np.asarray(x, dtype=np.float64).reshape(-1)
    y = np.asarray(y, dtype=np.float64).reshape(-1)
    if x.size < 2 or y.size < 2:
        raise ValueError("Ejes de coordenadas demasiado cortos para construir la rejilla")
    dx = float(np.median(np.diff(x)))
    dy = float(np.median(np.diff(y)))
    # Centros -> esquina superior izquierda del píxel (0, 0).
    x0 = float(x[0] - dx / 2.0)
    if dy < 0:
        y0 = float(y[0] - dy / 2.0)
        return Affine(dx, 0.0, x0, 0.0, dy, y0)
    # Eje Y creciente hacia el norte pero almacenado al revés: se invierte.
    y0 = float(y[-1] + dy / 2.0)
    return Affine(abs(dx), 0.0, x0 if dx > 0 else float(x[-1] - abs(dx) / 2.0), 0.0, -abs(dy), y0)


def leer_hdf5(ruta: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, Affine, str]:
    """Lee un GUNW HDF5 (NISAR o ARIA).

    Primero intenta rioxarray sobre el subdataset de fase. GDAL no siempre
    trae el driver HDF5, así que h5py es el camino que de verdad se prueba.
    """
    import h5py

    with h5py.File(ruta, "r") as handle:
        ds_fase = _buscar_dataset(handle, RUTAS_FASE, "unwrappedPhase")
        ds_coh = _buscar_dataset(handle, RUTAS_COHERENCIA, "coherenceMagnitude")
        if ds_fase is None or ds_coh is None:
            # ARIA nombra la coherencia simplemente "coherence".
            ds_coh = ds_coh or _buscar_dataset(handle, RUTAS_COHERENCIA, "coherence")
        if ds_fase is None or ds_coh is None:
            raise ValueError(f"No encuentro fase desenvuelta y coherencia en {ruta}")
        fase = np.asarray(ds_fase[...], dtype=np.float64)
        coherencia = np.asarray(ds_coh[...], dtype=np.float64)
        ds_cc = _buscar_dataset(handle, RUTAS_COMPONENTES, "connectedComponents")
        componentes = np.asarray(ds_cc[...]) if ds_cc is not None else None
        transform, crs = _georreferencia_hdf5(handle, fase.shape)
    fase = _a_2d(fase)
    coherencia = _a_2d(coherencia)
    if componentes is not None:
        componentes = _a_2d(componentes)
    return fase, coherencia, componentes, transform, crs


def _a_2d(arr: np.ndarray) -> np.ndarray:
    arr = np.squeeze(arr)
    if arr.ndim != 2:
        raise ValueError(f"Esperaba un raster 2D y llegó forma {arr.shape}")
    return arr


def _georreferencia_hdf5(handle, forma: tuple) -> tuple[Affine, str]:
    """Intenta ejes NISAR (metros) y, si no, lon/lat de ARIA."""
    candidatos_x = (
        "science/LSAR/GUNW/grids/frequencyA/xCoordinates",
        "science/LSAR/GUNW/grids/frequencyA/xCoordinatesM",
        "science/grids/data/xCoordinates",
    )
    candidatos_y = (
        "science/LSAR/GUNW/grids/frequencyA/yCoordinates",
        "science/LSAR/GUNW/grids/frequencyA/yCoordinatesM",
        "science/grids/data/yCoordinates",
    )
    dx = _buscar_dataset(handle, candidatos_x, "xCoordinates")
    dy = _buscar_dataset(handle, candidatos_y, "yCoordinates")
    if dx is not None and dy is not None:
        crs = _crs_hdf5(handle) or "EPSG:25829"
        return _afin_desde_ejes(dx[...], dy[...]), crs

    lon = _buscar_dataset(handle, ("science/grids/data/longitude",), "longitude")
    lat = _buscar_dataset(handle, ("science/grids/data/latitude",), "latitude")
    if lon is not None and lat is not None:
        lon_a = np.asarray(lon[...], dtype=np.float64)
        lat_a = np.asarray(lat[...], dtype=np.float64)
        if lon_a.ndim == 2:
            eje_x = lon_a[lon_a.shape[0] // 2]
            eje_y = lat_a[:, lat_a.shape[1] // 2]
        else:
            eje_x, eje_y = lon_a, lat_a
        return _afin_desde_ejes(eje_x, eje_y), "EPSG:4326"
    raise ValueError(
        "El HDF5 no trae ejes x/y ni lon/lat. No puedo georreferenciar el GUNW."
    )


def _crs_hdf5(handle) -> str | None:
    for clave in (
        "science/LSAR/GUNW/grids/frequencyA/projection",
        "science/LSAR/GUNW/metadata/radarGrid",
    ):
        if clave in handle:
            attrs = dict(handle[clave].attrs)
            for nombre in ("epsg", "EPSG", "spatial_epsg"):
                if nombre in attrs:
                    return f"EPSG:{int(attrs[nombre])}"
    return None


def cargar_interferograma(ruta: Path, longitud_onda_defecto: float) -> Interferograma:
    """Carga un GUNW en GeoTIFF o HDF5."""
    plataforma, fref, fsec, onda = _metadatos(ruta, longitud_onda_defecto)
    sufijo = ruta.suffix.lower()
    componentes = None
    if sufijo in {".tif", ".tiff"}:
        fase, coherencia, transform, crs = leer_geotiff(ruta)
    elif sufijo in {".h5", ".hdf5"}:
        fase, coherencia, componentes, transform, crs = leer_hdf5(ruta)
    else:
        raise ValueError(f"Extensión no soportada: {ruta}")
    if fase.shape != coherencia.shape:
        raise ValueError(f"Fase y coherencia no coinciden en {ruta.name}")
    return Interferograma(
        ruta=ruta,
        plataforma=plataforma,
        fecha_referencia=fref,
        fecha_secundaria=fsec,
        longitud_onda_m=onda,
        fase_rad=fase,
        coherencia=coherencia,
        componentes=componentes,
        transform=transform,
        crs=crs,
    )


def listar_interferogramas(directorio: Path) -> list[Path]:
    """Archivos de interferograma, ordenados por nombre."""
    if not directorio.is_dir():
        return []
    encontrados = []
    for patron in ("*.tif", "*.tiff", "*.h5", "*.hdf5"):
        encontrados.extend(directorio.glob(patron))
    return sorted(encontrados)
