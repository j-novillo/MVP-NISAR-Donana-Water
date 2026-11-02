"""Utilidades compartidas: configuración, AOI, fechas y rejilla.

Todo el pipeline lee `config.yaml`. Las rutas son relativas a la raíz del
repositorio salvo que sean absolutas. Las credenciales no se leen aquí:
solo las usan los módulos de descarga, y siempre desde el entorno.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from pyproj import Transformer
from rasterio.transform import Affine

RAIZ = Path(__file__).resolve().parents[1]


@dataclass
class Aoi:
    """Recuadro de trabajo en geográficas y en el CRS métrico del proyecto."""

    nombre: str
    descripcion: str
    lon_min: float
    lon_max: float
    lat_min: float
    lat_max: float
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    crs: str
    centro_lon: float
    centro_lat: float
    centro_x: float
    centro_y: float

    def wkt(self) -> str:
        """Polígono WGS84, eje X = longitud, en el orden que piden ASF y OData."""
        x0, y0, x1, y1 = self.lon_min, self.lat_min, self.lon_max, self.lat_max
        return (
            f"POLYGON(({x0} {y0}, {x1} {y0}, {x1} {y1}, {x0} {y1}, {x0} {y0}))"
        )

    def bbox_wfs(self) -> str:
        """BBox WFS 1.1/2.0 en orden lon,lat con CRS explícito."""
        return (
            f"{self.lon_min},{self.lat_min},{self.lon_max},{self.lat_max},EPSG:4326"
        )


def cargar_dotenv(ruta: Path | None = None) -> None:
    """Carga un `.env` local sin pisar variables ya definidas.

    No es un parser completo: ignora comentarios y comillas simples. No registra
    los valores en el log.
    """
    ruta = ruta or (RAIZ / ".env")
    if not ruta.is_file():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        if clave:
            os.environ.setdefault(clave, valor)


def cargar_config(ruta: str | Path | None = None) -> dict:
    """Lee el YAML de configuración y resuelve rutas respecto a la raíz."""
    path = Path(ruta) if ruta else RAIZ / "config.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"No se encuentra la configuración: {path}")
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    cfg["_config_path"] = str(path)
    return cfg


def ruta_proyecto(cfg: dict, clave: str) -> Path:
    """Devuelve una ruta de `cfg['rutas']` como Path absoluto."""
    bruto = Path(cfg["rutas"][clave])
    if not bruto.is_absolute():
        bruto = RAIZ / bruto
    return bruto


def asegurar_directorio(ruta: Path) -> Path:
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


@lru_cache(maxsize=8)
def _transformador(crs_destino: str) -> Transformer:
    """Un Transformer reutilizable. Crearlo en cada punto cuesta decenas de ms."""
    return Transformer.from_crs("EPSG:4326", str(crs_destino), always_xy=True)


@lru_cache(maxsize=8)
def _transformador_inverso(crs_origen: str) -> Transformer:
    return Transformer.from_crs(str(crs_origen), "EPSG:4326", always_xy=True)


def a_metrico(lon: float, lat: float, crs: str) -> tuple[float, float]:
    x, y = _transformador(crs).transform(lon, lat)
    return float(x), float(y)


def a_geografico(x: float, y: float, crs: str) -> tuple[float, float]:
    lon, lat = _transformador_inverso(crs).transform(x, y)
    return float(lon), float(lat)


def resolver_aoi(cfg: dict) -> Aoi:
    """Construye el AOI activo (tesela de Rociana o bbox completo)."""
    crs = cfg.get("crs_metrico", "EPSG:25829")
    activa = cfg["aoi"]["activa"]
    if activa not in cfg["aoi"]:
        raise KeyError(
            f"aoi.activa='{activa}' no está definida. "
            "Use tesela_rociana o bbox_completo."
        )
    bloque = cfg["aoi"][activa]
    if activa == "tesela_rociana":
        clon, clat = float(bloque["centro_lon"]), float(bloque["centro_lat"])
        lado = float(bloque["lado_km"]) * 1000.0
        cx, cy = a_metrico(clon, clat, crs)
        xmin, xmax = cx - lado / 2.0, cx + lado / 2.0
        ymin, ymax = cy - lado / 2.0, cy + lado / 2.0
        esquinas = [
            a_geografico(xmin, ymin, crs),
            a_geografico(xmin, ymax, crs),
            a_geografico(xmax, ymin, crs),
            a_geografico(xmax, ymax, crs),
        ]
        lons = [p[0] for p in esquinas]
        lats = [p[1] for p in esquinas]
        lon_min, lon_max = min(lons), max(lons)
        lat_min, lat_max = min(lats), max(lats)
        centro_lon, centro_lat = clon, clat
        centro_x, centro_y = cx, cy
    elif activa == "bbox_completo":
        lon_min = float(bloque["lon_min"])
        lon_max = float(bloque["lon_max"])
        lat_min = float(bloque["lat_min"])
        lat_max = float(bloque["lat_max"])
        xs, ys = [], []
        for lon, lat in (
            (lon_min, lat_min),
            (lon_min, lat_max),
            (lon_max, lat_min),
            (lon_max, lat_max),
        ):
            x, y = a_metrico(lon, lat, crs)
            xs.append(x)
            ys.append(y)
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        centro_lon = (lon_min + lon_max) / 2.0
        centro_lat = (lat_min + lat_max) / 2.0
        centro_x, centro_y = a_metrico(centro_lon, centro_lat, crs)
    else:
        raise KeyError(f"No sé construir el AOI '{activa}'")

    ref = cfg.get("referencia", {})
    # El centro de la tesela de Rociana es el punto de referencia por defecto.
    if activa == "tesela_rociana" and "lon" not in ref:
        pass
    return Aoi(
        nombre=activa,
        descripcion=str(bloque.get("descripcion", activa)),
        lon_min=lon_min,
        lon_max=lon_max,
        lat_min=lat_min,
        lat_max=lat_max,
        xmin=xmin,
        ymin=ymin,
        xmax=xmax,
        ymax=ymax,
        crs=crs,
        centro_lon=centro_lon,
        centro_lat=centro_lat,
        centro_x=centro_x,
        centro_y=centro_y,
    )


def punto_referencia(cfg: dict) -> tuple[float, float]:
    """Longitud y latitud del píxel estable (casco urbano de Rociana)."""
    ref = cfg["referencia"]
    return float(ref["lon"]), float(ref["lat"])


def malla_anidada(aoi: Aoi, res_m: float, res_malla_m: float) -> dict:
    """Origen de la rejilla alineado con la malla de medición.

    Se encaja hacia fuera al múltiplo de `res_malla_m` para que los píxeles
    nativos quepan enteros dentro de las celdas de 100 m.
    """
    xmin = np.floor(aoi.xmin / res_malla_m) * res_malla_m
    ymax = np.ceil(aoi.ymax / res_malla_m) * res_malla_m
    xmax = np.ceil(aoi.xmax / res_malla_m) * res_malla_m
    ymin = np.floor(aoi.ymin / res_malla_m) * res_malla_m
    # Si el borde no cae en un número entero de píxeles, se amplía una fila/columna.
    ancho = xmax - xmin
    alto = ymax - ymin
    cols = int(np.ceil(ancho / res_m - 1e-6))
    rows = int(np.ceil(alto / res_m - 1e-6))
    xmax = xmin + cols * res_m
    ymin = ymax - rows * res_m
    transform = Affine(res_m, 0.0, xmin, 0.0, -res_m, ymax)
    return {
        "xmin": float(xmin),
        "ymin": float(ymin),
        "xmax": float(xmax),
        "ymax": float(ymax),
        "res": float(res_m),
        "rows": int(rows),
        "cols": int(cols),
        "transform": transform,
        "crs": aoi.crs,
    }


def indices_xy(transform: Affine, x: float, y: float) -> tuple[int, int]:
    """Fila y columna (fila 0 = norte) del punto métrico más cercano al centro del píxel."""
    # Transform inverso: columna = (x - c) / a ; fila = (y - f) / e
    col = int(np.floor((x - transform.c) / transform.a))
    fila = int(np.floor((y - transform.f) / transform.e))
    return fila, col


def centros_pixel(malla: dict) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas X e Y del centro de cada píxel. X crece con la columna, Y decrece con la fila."""
    res = malla["res"]
    cols = np.arange(malla["cols"])
    filas = np.arange(malla["rows"])
    x = malla["xmin"] + (cols + 0.5) * res
    y = malla["ymax"] - (filas + 0.5) * res
    return x, y


def fechas_mensuales(inicio: date, n_meses: int) -> list[date]:
    """Día fijo del mes de `inicio`, repetido `n_meses` veces."""
    fechas = []
    for k in range(n_meses):
        mes0 = inicio.month - 1 + k
        anio = inicio.year + mes0 // 12
        mes = mes0 % 12 + 1
        fechas.append(date(anio, mes, inicio.day))
    return fechas


def parsear_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor)[:10]
    return date.fromisoformat(texto)


def indice_fecha_cercana(
    fechas: list[date], objetivo: date, tolerancia_dias: int = 20
) -> int | None:
    """Índice de la fecha más cercana a `objetivo`, o None si se pasa la tolerancia."""
    if not fechas:
        return None
    deltas = [abs((f - objetivo).days) for f in fechas]
    k = int(np.argmin(deltas))
    if deltas[k] <= tolerancia_dias:
        return k
    return None


def guardar_json(ruta: Path, payload: dict) -> None:
    asegurar_directorio(ruta.parent)
    ruta.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def afin_a_lista(transform: Affine) -> list[float]:
    return [float(transform.a), float(transform.b), float(transform.c),
            float(transform.d), float(transform.e), float(transform.f)]


def lista_a_afin(valores) -> Affine:
    return Affine(*valores)
