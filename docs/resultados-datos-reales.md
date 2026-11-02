# Resultados con datos reales — tesela Rociana 5×5 km

**Fecha del informe**: 2026-11-02 (Europe/Madrid)  
**Rama**: `cursor/poc-donana-insar-8c15`  
**Modo**: `real` (no sintético)

## Resumen ejecutivo / go–no-go

| Criterio | Resultado | Valor |
|---|---|---|
| Coherencia InSAR en campaña | **go** | 40.4 % píxeles con coh media > 0.3 en abr–jun |
| Señal de subsidencia local | **indeterminado** | mediana exceso en anomalías = 3.12 mm (go≥5 / no-go<2); 12 celdas z>2; agrupación 83 % |
| Discriminación legal | **indeterminado** | Faltan `pozos_registrados.gpkg` y `sar.gpkg` |
| Validación pozos cerrados | **indeterminado** | Sin capa CHG de cierres |
| **Decisión tubería** | **indeterminado** | |
| **Decisión científica Doñana** | **indeterminado** | |

La coherencia C-banda supera el umbral go, pero el exceso local (~3.1 mm) queda en banda gris (2–5 mm). Sin capas legales no hay cruce pozo/SAR. **No hay go ni no-go científico.**

## Datos usados

### Sentinel-1 HyP3 INSAR_GAMMA (stack principal)

- **8 interferogramas** (~4 meses de baseline, 80 m) → GeoTIFF AOI `S1_GUNW_*.tif` (66×66).
- Fechas red: 2022-01-06, 2022-05-06, 2022-09-03, 2023-01-01, 2023-05-01, 2023-09-10, 2024-01-20, 2024-05-19, 2024-09-16.
- Plataforma `SENTINEL-1`; λ = 0,05546576 m; `signo_fase = -1.0` (**sin anclar a control urbano**).
- EGMS no disponible (token CLMS); ARIA S1 GUNW ausente en AOI.

### NISAR GUNW (ASF) — pendiente de cierre

- Catálogo 36; subconjunto PoC 4. Descarga Range 1 MiB (`src/descarga_nisar_chunked.py`) por IncompleteRead de CloudFront.
- Al cerrar el informe: **0 `.h5` completo(s)**; partial `NISAR_L2_PR_GUNW_004_015_A_021_006_2000_SH_20251030T053143_20251030T053218_20251123T053144_20251123T053219_X05010_N_F_J_001.part` ≈ **2141 MB / ~2340 MB**.
- NISAR solo (oct 2025–oct 2026, hueco ene–may 2026) **no cubre** el ciclo estacional → S1 es la medición. No se mezcla L y C en la misma inversión.

### Sentinel-2 NDVI (CDSE Process API)

- 58 mensuales 2022-01…2026-10; media AOI 0.335.
- `ndvi_parcelas.csv`: 2622 parcelas × 58 fechas.
- Usuario CDSE: `jorgenovillo2005@gmail.com`. JWT en `CDSE_PASSWORD` inválido → `CDSE_ACCESS_TOKEN` mientras duró.

### Capas

- `parcelas.gpkg` = malla sintética ~110 m (no SIGPAC). Sin pozos/SAR/cierres/piezómetros → legal y validación indeterminados (ausencia ≠ “sin pozo”).

## Procesado opción A

1. `procesar_insar`: 8 ifg → 9 fechas, **499** píxeles (coh≥0,3; `min_ecuaciones_red=6`).
2. `medir`: malla **80 m**; anillo **400–1500 m**, `min_muestras_anillo=10` (1–2 km dejaba z=NaN en tesela 5×5).
3. `hundimiento_estacional`: tolerancia **70 d** (Sep como proxy de Nov en stacks trimestrales).
4. Score máx **50.9**/100 (término legal=0).
5. Figuras en `docs/figuras/`.

### Números

- Amplitud estacional: mediana 2.69 mm; p90 3.96; máx 6.31.
- Hundimiento estacional: mediana 14.84 mm (campo ~homogéneo).
- Velocidad: mediana 28.0 mm/a — **sesgo espacial uniforme** (atmósfera/baseline/referencia); no interpretar como subsidencia real.
- Z-score finitos 458; **12 con z>2**; 27 con z<-2.
- Exceso en z>2: mediana 3.12 mm.

## `signo_fase`

Convención `-1.0` sin GNSS/punto duro. Voltear el signo cambia velocidad/hundimiento absolutos; el z-score local (anillo) conserva magnitud. Falta anclar antes de un go científico.

## Figuras

`zscore.png`, `amplitud_estacional.png`, `serie_parcela.png`, `go_nogo.png`, `ndvi_mensual_aoi.png`, `hyp3_s1_*_color_phase.png` en `docs/figuras/`.

## Bugs reales y parches

1. CloudFront IncompleteRead en NISAR → Range 1–2 MiB.
2. `asf_search.auth_with_token` fallaba con token válido para Bearer HTTP.
3. `CDSE_PASSWORD` era JWT; usuario corregido a `jorgenovillo2005@gmail.com`.
4. `convertir_hyp3`: `import rasterio.warp` local → UnboundLocalError; AOI clip + tiled.
5. `hundimiento_estacional` tol. 20 d → NaN total; tol. 70 d.
6. Malla 100 m no múltiplo de 80 m HyP3 → 80 m.
7. Anillo 1–2 km + máscara dispersa → z=NaN; anillo 400–1500 m (documentado ≠ spec original).

## Lectura honesta

- **Tubería**: OK de punta a punta con S1+NDVI reales y parcelas sintéticas.
- **Científico**: **indeterminado** (señal gris ~3 mm; sin legal; signo sin anclar; baselines ~120 d).
- **Pendiente**: terminar ≥1 GUNW NISAR (~2141/2340 MB); SIGPAC+SAR+pozos CHG; pares S1 12–24 d o EGMS; control de signo en Rociana.

## Reproducibilidad

```bash
source /workspace/.secrets_env   # solo env; nunca en git
cd MVP-NISAR-Donana-Water
PYTHONPATH=src python src/convertir_hyp3.py
PYTHONPATH=src python src/procesar_insar.py
PYTHONPATH=src python src/medir.py
PYTHONPATH=src python src/score.py
PYTHONPATH=src python src/validar.py
```
