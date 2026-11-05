# Referencias de validación y comparación NISAR vs S1

Fecha: 2026-11-04 (Europe/Madrid). Rama `cursor/poc-donana-insar-8c15`.

## Datos obtenidos en esta corrida

| Recurso | Estado | Detalle |
|---|---|---|
| NISAR GUNW #1 (2025-10-30 → 2025-11-23) | **OK** (~2.2 GB `.h5`) | Procesado con `--plataforma NISAR --salida data/procesado_nisar` |
| NISAR GUNW #2 (2025-12-05 → 2025-12-17) | en descarga / reintento | El `.part` previo se corrompió por dos descargas concurrentes; el script ahora verifica el tamaño |
| Sentinel-1 HyP3 | 8 ifg (2022-01 → 2024-09) | Ya convertidos a `S1_GUNW_*.tif` |
| Piezómetros MITECO (puntos) | **71** en bbox ampliado | `data/raw/capas/piezometros.gpkg` vía WFS |
| Piezómetros CHG (puntos) | **53** | `data/raw/capas/piezometros_chg.gpkg` |
| Series de nivel piezométrico | **no automático** | Solo visor CHG; ver `LEEME_SERIES_TEMPORALES.txt` |
| EGMS L2b/L3 | **no automático** | API archive exige login CLMS |
| GNSS catálogo NGL | **11 estaciones** cercanas | `docs/datos-referencia/estaciones_gnss_cercanas.csv` |
| GNSS series (tenv3) | **404** en NGL | Usar RINEX RAP/IGN |
| ARIA S1 GUNW 2025-10+ | **0** productos | No hay ifg S1 listos en el solape NISAR |
| HyP3 jobs | seis en curso en el box, no se lanzan desde aquí | `HyP3(token=EARTHDATA_TOKEN)` autentica; no hace falta usuario/clave |

## Comparación NISAR vs Sentinel-1

Estado: **no_evaluable**. No hay porcentaje de mejora.

Las medias de coherencia (0,355 frente a 0,515), la fracción usable (0,510
frente a 0,921) y la dispersión espacial urbana (4,73 mm frente a 3,54 mm)
se calcularon el 4 nov 2026 sobre épocas distintas (S1 2022–2024, 8 pares;
NISAR un par de 24 días en oct–nov 2025). Se conservan como descripción de
aquella corrida en el JSON, con el porcentaje retirado. No son exactitud, y
la dispersión urbana no es ruido instrumental.

La exactitud sigue sin porcentaje. El piezómetro no mide desplazamiento.
EGMS, cuando se descargue por la API oficial de CLMS, sigue siendo Sentinel-1.
El RMSE evaluable es GNSS proyectado a LOS. El protocolo está en
`docs/14-protocolo-comparacion.md`.

## Cómo repetirlo

Ver `docs/11-guia-ejecucion-local.md`.
