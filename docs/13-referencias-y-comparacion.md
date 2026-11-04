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
| HyP3 jobs 2025-10+ | pendiente de usuario/clave Earthdata | El token Bearer no autentica HyP3 |

## Mejora NISAR vs Sentinel-1 (producto, mismo AOI)

Definiciones en `src/comparar_nisar_s1.py` y tabla en `docs/12-comparacion-nisar-s1.md`.

| Métrica | S1 | NISAR | Mejora | Definición |
|---|---:|---:|---:|---|
| Coherencia media | 0.355 | 0.515 | **+45.3 %** | `100*(NISAR−S1)/S1` |
| Fracción usable (coh≥0.3) | 0.510 | 0.921 | **+80.7 %** | igual |
| Ruido std zona urbana (mm) | 4.73 | 3.54 | **+25.1 %** | `100*(S1−NISAR)/S1` |

### Exactitud vs verdad de terreno

**No calculable** (sin porcentaje):

1. No hay solape temporal S1 (hasta 2024-09) ↔ NISAR (desde 2025-10).
2. No hay series GNSS descargables ni `piezometros_niveles.csv` ni EGMS local.

Para obtener el % de exactitud hace falta: HyP3 S1 en oct 2025+, más GNSS procesado a LOS y/o series piezométricas exportadas del visor CHG, y/o EGMS con cuenta CLMS.

## Cómo repetirlo

Ver `docs/11-guia-ejecucion-local.md`.
