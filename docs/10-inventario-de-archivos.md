# Inventario de archivos

Rutas relativas a la raíz del repositorio.

## Configuración y entorno

| Archivo | Papel |
|---|---|
| `config.yaml` | AOI, umbrales, rutas, modo sintético o real |
| `environment.yml` | Entorno conda `poc-donana` (opción A) |
| `environment-opcion-b.yml` | Entorno aparte con MintPy e ISCE2 |
| `requirements.txt` | Lo mismo que el entorno A, instalable con pip |
| `.env.example` | Nombres de las variables. Sin valores |
| `.gitignore` | Deja fuera `.env`, `data/raw`, rásteres y parquet generados |
| `config/mintpy_smallbaselineApp.cfg` | Plantilla SBAS. No se ejecuta sola |
| `pytest.ini` | `pythonpath = src` |
| `.github/workflows/tests.yml` | `pytest` en Python 3.12 |

## Scripts

| Archivo | Entrada | Salida |
|---|---|---|
| `src/download.sh` | `config.yaml`, y en modo real el entorno | Escena sintética, o catálogos y productos |
| `ejecutar_sintetico.sh` | La config por defecto | Toda la tubería sintética, validación incluida |
| `src/sintetico.py` | `config.yaml` | Interferogramas, capas, NDVI, piezómetros, manifiesto |
| `src/descarga_asf.py` | AOI, `EARTHDATA_TOKEN` solo si se descarga | `data/raw/catalogo_asf.csv` y, si no es `--listar`, los productos |
| `src/descarga_cdse.py` | AOI, usuario/clave CDSE solo si se descarga | `data/raw/catalogo_cdse.csv` y los ZIP |
| `src/descarga_capas.py` | WFS de la CHG y del SIA | `pozos_registrados.gpkg` si el WFS responde, `LEEME_CAPAS.txt`, `estado_descarga.json` |
| `src/ndvi_s2.py` | JP2 de Sentinel-2 y `parcelas.gpkg` | `data/raw/ndvi/ndvi_parcelas.csv` |
| `src/lectura_gunw.py` | GeoTIFF o HDF5 | Objeto en memoria (fase, coherencia, fechas, affine) |
| `src/procesar_insar.py` | Interferogramas | `data/procesado/serie_mm.npz`, `metadatos.json` |
| `src/medir.py` | La serie | `data/resultados.parquet`, `serie_malla100.npz`, `data/geotiff/*.tif` |
| `src/score.py` | Malla, parcelas, pozos, SAR, NDVI | `data/parcelas_score.parquet` y `.gpkg`. Llama al validador |
| `src/validar.py` | Malla, score, cierres, WWF, piezómetros | `data/validacion.json`, figuras |
| `src/figuras.py` | Malla y score | PNG de control |
| `src/visor.py` | Todo lo anterior | Aplicación Streamlit |
| `src/opcion_b_mintpy.py` | Un `timeseries.h5` opcional | Plantilla MintPy y, si se le pasa el HDF5, la serie en el formato de la opción A |
| `src/utilidades.py` | `config.yaml` | AOI, rejilla, fechas, rutas. Lo usan los demás |
| `src/comparar_nisar_s1.py` | GUNW NISAR + S1 en el AOI | `docs/comparacion-nisar-s1.json`, `docs/12-comparacion-nisar-s1.md` |
| `src/descarga_referencias.py` | WFS piezómetros, NGL holdings | `piezometros*.gpkg`, catálogo GNSS, LEEMEs EGMS/series |
| `src/descarga_nisar_chunked.py` | CSV subset + `EARTHDATA_TOKEN` | `data/raw/interferogramas/NISAR_*.h5` (reanudable) |
| `src/convertir_hyp3.py` | Zips HyP3 | GeoTIFF S1 de 2 bandas + JSON |
| `src/descarga_ndvi_process.py` | CDSE Process API | NDVI mensuales / por parcela |

## Documentación añadida (mejora / comparación)

| Archivo | Contenido |
|---|---|
| `docs/11-guia-ejecucion-local.md` | Cuentas, URLs, comandos para correr todo en un PC |
| `docs/12-comparacion-nisar-s1.md` | Por qué las cifras de 2026-11-04 no son una mejora |
| `docs/13-referencias-y-comparacion.md` | Estado de GNSS, EGMS y piezómetros |
| `docs/14-protocolo-comparacion.md` | Protocolo; no es el informe final |
| `docs/comparacion-nisar-s1.json` | Instantánea reetiquetada; porcentajes en null |
| `docs/datos-referencia/` | Catálogo GNSS y recuento de capas WFS, no series |
| `src/comparacion_protocolo.py` | Fórmula de error, solape de pares, máscara común, ENU→LOS |
| `src/catalogo_s1_solape.py` | Filtro ASF de SLC en la ventana NISAR; `--consultar` es opt-in |
| `src/preparar_hyp3.py` | JSON oficial INSAR_GAMMA; `--enviar` solo en el box |
| `src/leer_egms.py` | Consulta EGMS o lectura de un CSV local; no descarga |

## Tests

| Archivo | Qué fija |
|---|---|
| `tests/test_ciencia.py` | Fase↔mm, rampa, inversión, seno, hundimiento mayo-noviembre, z-score, fórmula del score, NDVI, recuperación de un cono con rampa y ruido |
| `tests/test_descargas.py` | Filtros ASF y CDSE, renovación del token sin reenviar la clave, URL WFS, lectura de un HDF5 tipo NISAR y de un GeoTIFF con sidecar |
| `tests/test_comparar.py` | Mejora de error solo si es comparable; solape de pares; papeles de GNSS, piezómetro y EGMS |
| `tests/test_pipeline.py` | Escena sintética reducida (100 m, 18 meses) de punta a punta, go en los cuatro criterios, recuerdo entre 50 % y 100 %, GeoTIFF, mapas del visor |

La corrida documentada en el README usa la config por defecto (50 m, 24 meses),
no la versión reducida del test.

## Datos que se generan y no se versionan

| Ruta | Contenido |
|---|---|
| `data/raw/interferogramas/` | GUNW reales o GeoTIFF sintéticos, con un JSON de metadatos al lado |
| `data/raw/capas/` | Parcelas, SAR, pozos, piezómetros |
| `data/raw/ndvi/ndvi_parcelas.csv` | NDVI por parcela y fecha |
| `data/raw/MANIFIESTO_SINTETICO.json` | Semilla, ids de los conos y la advertencia de que es falso |
| `data/raw/catalogo_asf.csv`, `catalogo_cdse.csv` | Listados de búsqueda |
| `data/procesado/` | Serie temporal y metadatos |
| `data/resultados.parquet` | Malla de 100 m |
| `data/parcelas_score.parquet`, `.gpkg` | Ranking |
| `data/geotiff/` | Rásteres para QGIS |
| `data/validacion.json` | Go / no-go |
| `data/figuras/` | PNG de la última validación |

`docs/figuras/` sí se versiona: es la ilustración de la corrida de referencia.

## Formato del interferograma sintético

GeoTIFF, dos bandas float32: fase desenvuelta en radianes, coherencia.
Nombre `NISAR_GUNW_YYYYMMDD_YYYYMMDD.tif`. El JSON homónimo trae plataforma,
fechas y longitud de onda. Lo abre `rioxarray`. El lector de HDF5 cubre las
rutas de NISAR (`…/unwrappedInterferogram/HH/unwrappedPhase` y
`coherenceMagnitude`) y la de ARIA (`science/grids/data/unwrappedPhase`), y
busca por sufijo si el producto usa otra polarización.
