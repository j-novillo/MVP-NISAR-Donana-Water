"""La escena sintética recorre procesar, medir, score, validar y el visor."""

import json
from pathlib import Path

from medir import medir
from procesar_insar import procesar
from score import puntuar
from sintetico import generar
from utilidades import cargar_config
from validar import evaluar
from visor import cargar_capas, grafico_serie, mapa_deformacion, mapa_ndvi


def _cfg(tmp_path: Path) -> dict:
    cfg = cargar_config()
    cfg["modo"] = "sintetico"
    cfg["sintetico"] = dict(cfg["sintetico"])
    # Más grueso que la corrida por defecto para que el test no tarde.
    # La corrida documentada usa los 50 m de config.yaml.
    cfg["sintetico"]["resolucion_m"] = 100
    cfg["sintetico"]["n_meses"] = 18
    base = tmp_path / "data"
    cfg["rutas"] = {
        "interferogramas": str(base / "raw" / "interferogramas"),
        "capas": str(base / "raw" / "capas"),
        "ndvi": str(base / "raw" / "ndvi" / "ndvi_parcelas.csv"),
        "procesado": str(base / "procesado"),
        "resultados": str(base / "resultados.parquet"),
        "parcelas_score": str(base / "parcelas_score.parquet"),
        "geotiff": str(base / "geotiff"),
        "validacion": str(base / "validacion.json"),
        "figuras": str(base / "figuras"),
    }
    return cfg


def test_pipeline_sintetico_supera_el_go(tmp_path: Path):
    cfg = _cfg(tmp_path)
    resumen = generar(cfg)
    assert resumen["sintetico"] is True
    assert (Path(cfg["rutas"]["capas"]) / "pozos_registrados.gpkg").is_file()
    assert (Path(cfg["rutas"]["capas"]).parent / "MANIFIESTO_SINTETICO.json").is_file()

    procesar(cfg)
    medir(cfg)
    puntuar(cfg)
    informe = evaluar(cfg)

    assert informe["alcance"] == "sintetico"
    assert informe["decision_cientifica_donana"] == "pendiente_de_datos_reales"
    por_id = {c["id"]: c for c in informe["criterios"]}
    assert por_id["coherencia"]["resultado"] == "go", por_id["coherencia"]
    assert por_id["senal"]["resultado"] == "go", por_id["senal"]
    assert por_id["legal"]["resultado"] == "go", por_id["legal"]
    assert por_id["pozos_cerrados"]["resultado"] == "go", por_id["pozos_cerrados"]
    recall = por_id["pozos_cerrados"]["valor"]["recall"]
    assert recall >= 0.5
    assert por_id["pozos_cerrados"]["valor"]["total"] == 8
    # Los dos cierres sin cono no deberían detectarse: el recuerdo no es el 100 %.
    assert recall < 1.0
    assert informe["decision_tuberia"] == "go"
    assert informe["apoyo_piezometros"]["coherente_con_anomalias"] is True

    geotiff = Path(cfg["rutas"]["geotiff"])
    for nombre in ("zscore.tif", "amplitud_estacional_mm.tif", "velocidad_mm_anio.tif", "coherencia_media.tif"):
        assert (geotiff / nombre).is_file()

    datos = cargar_capas(cfg)
    assert mapa_deformacion(datos, tmp_path) is not None
    assert mapa_ndvi(datos) is not None
    mejor = datos["parcelas"].sort_values("score", ascending=False).iloc[0]
    assert mejor["fuera_sar"]
    assert mejor["sin_pozo_declarado"]
    figura = grafico_serie(datos, mejor["id_parcela"])
    assert figura is not None
    # La parcela de mayor score tiene que estar en el grupo de los conos, no en la SAR.
    assert str(mejor["id_parcela"]).startswith("I-")

    guardadas = list(Path(cfg["rutas"]["figuras"]).glob("*.png"))
    assert len(guardadas) >= 3
    # El JSON de validación queda escrito para el visor.
    assert json.loads(Path(cfg["rutas"]["validacion"]).read_text(encoding="utf-8"))["decision_tuberia"] == "go"
