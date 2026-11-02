"""Contratos de los clientes de descarga: no tocan la red."""

import json
from datetime import date
from pathlib import Path

import h5py
import numpy as np
import pytest
import requests

from descarga_asf import CredencialesError, construir_busquedas, exigir_token
from descarga_capas import construir_url_wfs
from descarga_cdse import ClienteCDSE, filtros_productos
from lectura_gunw import cargar_interferograma
from utilidades import cargar_config


def test_busqueda_asf_incluye_nisar_y_no_slc_por_defecto():
    cfg = cargar_config()
    nombres = [b["nombre"] for b in construir_busquedas(cfg)]
    assert "NISAR_GUNW" in nombres
    assert "ARIA_S1_GUNW" in nombres
    assert not any(n.startswith("S1_SLC") for n in nombres)
    nisar = next(b for b in construir_busquedas(cfg) if b["nombre"] == "NISAR_GUNW")
    assert nisar["processingLevel"] == "GUNW"
    assert nisar["start"] == "2025-10-01"
    assert "POLYGON" in nisar["intersectsWith"]


def test_descarga_asf_exige_token(monkeypatch):
    monkeypatch.delenv("EARTHDATA_TOKEN", raising=False)
    with pytest.raises(CredencialesError):
        exigir_token()


def test_filtros_cdse_llevan_el_aoi_y_el_dem():
    cfg = cargar_config()
    nombres = [nombre for nombre, _ in filtros_productos(cfg)]
    assert "SENTINEL-2_L2A" in nombres
    assert "COP-DEM_GLO-30" in nombres
    assert "SENTINEL-1_SLC" not in nombres
    filtro_s2 = dict(filtros_productos(cfg))["SENTINEL-2_L2A"]
    assert "S2MSI2A" in filtro_s2
    assert "cloudCover" in filtro_s2
    assert "POLYGON" in filtro_s2


def test_el_cliente_cdse_renueva_sin_reenviar_la_clave(monkeypatch):
    monkeypatch.setenv("CDSE_USERNAME", "usuario")
    monkeypatch.setenv("CDSE_PASSWORD", "secreto")
    monkeypatch.delenv("CDSE_ACCESS_TOKEN", raising=False)
    grants = []

    class Respuesta:
        status_code = 200

        def __init__(self, cuerpo):
            self._cuerpo = cuerpo

        def raise_for_status(self):
            return None

        def json(self):
            return self._cuerpo

    cuerpos = [
        {"access_token": "token-1", "refresh_token": "refresh-1", "expires_in": 600},
        {"access_token": "token-2", "refresh_token": "refresh-2", "expires_in": 600},
    ]

    def falso_post(url, data=None, timeout=None):
        grants.append(data["grant_type"])
        if data["grant_type"] == "password":
            assert data["password"] == "secreto"
        else:
            assert "password" not in data
        return Respuesta(cuerpos.pop(0))

    monkeypatch.setattr(requests.Session, "post", lambda self, url, data=None, timeout=None: falso_post(url, data, timeout))
    cliente = ClienteCDSE()
    assert cliente.token() == "token-1"
    assert grants == ["password"]
    cliente._expira = 0
    assert cliente.token() == "token-2"
    assert grants == ["password", "refresh_token"]


def test_cdse_sin_credenciales(monkeypatch):
    monkeypatch.delenv("CDSE_USERNAME", raising=False)
    monkeypatch.delenv("CDSE_PASSWORD", raising=False)
    monkeypatch.delenv("CDSE_ACCESS_TOKEN", raising=False)
    with pytest.raises(Exception):
        ClienteCDSE().token()


def test_url_wfs_de_la_chg():
    url = construir_url_wfs(
        "https://idechg.chguadalquivir.es/geoserver/ggiscloud_root/ows",
        "ggiscloud_root:captaciones_dph",
        "-6.7,37.2,-6.5,37.4,EPSG:4326",
    )
    assert "GetFeature" in url
    assert "captaciones_dph" in url
    assert "application%2Fjson" in url or "application/json" in url


def test_lectura_de_gunw_hdf5(tmp_path: Path):
    ruta = tmp_path / "NISAR_GUNW_20240115T120000_20240115T120012_20240215T120000_20240215T120012.h5"
    fase = np.full((4, 5), 0.2, dtype=np.float32)
    coh = np.full((4, 5), 0.8, dtype=np.float32)
    with h5py.File(ruta, "w") as handle:
        base = "science/LSAR/GUNW/grids/frequencyA"
        handle.create_dataset(f"{base}/unwrappedInterferogram/HH/unwrappedPhase", data=fase)
        handle.create_dataset(f"{base}/unwrappedInterferogram/HH/coherenceMagnitude", data=coh)
        handle.create_dataset(f"{base}/xCoordinates", data=np.arange(5) * 80.0)
        handle.create_dataset(f"{base}/yCoordinates", data=4_200_000.0 - np.arange(4) * 80.0)
    producto = cargar_interferograma(ruta, 0.238403)
    assert producto.fase_rad.shape == (4, 5)
    assert producto.coherencia[0, 0] == pytest.approx(0.8)
    assert producto.fecha_referencia == date(2024, 1, 15)
    assert producto.fecha_secundaria == date(2024, 2, 15)
    assert producto.plataforma == "DESCONOCIDA"
    # El eje Y decrece: el píxel (0, 0) es el más al norte.
    assert producto.transform.e < 0


def test_el_sidecar_manda_sobre_el_nombre(tmp_path: Path):
    import rasterio
    from rasterio.transform import from_origin

    tif = tmp_path / "par.tif"
    transform = from_origin(700000, 4200000, 50, 50)
    with rasterio.open(
        tif,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=2,
        dtype="float32",
        crs="EPSG:25829",
        transform=transform,
    ) as dst:
        dst.write(np.zeros((2, 3, 3), dtype=np.float32))
    tif.with_suffix(".json").write_text(
        json.dumps(
            {
                "plataforma": "NISAR",
                "fecha_referencia": "2024-05-15",
                "fecha_secundaria": "2024-06-15",
                "longitud_onda_m": 0.24,
            }
        ),
        encoding="utf-8",
    )
    producto = cargar_interferograma(tif, 0.2)
    assert producto.plataforma == "NISAR"
    assert producto.fecha_referencia == date(2024, 5, 15)
    assert producto.longitud_onda_m == pytest.approx(0.24)
    assert producto.crs.startswith("EPSG:25829")
