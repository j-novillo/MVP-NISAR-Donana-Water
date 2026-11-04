# Comparación NISAR vs Sentinel-1

AOI: `tesela_rociana` · umbral de coherencia: 0.3

## Solape temporal

- ¿Hay solape? **False**
- Motivo: S1 cubre 2022-01-06–2024-09-16; NISAR cubre 2025-10-30–2025-11-23; no hay fechas en común

## Métricas de producto (mismo AOI)

| Métrica | Sentinel-1 | NISAR | Mejora NISAR vs S1 | Definición |
|---|---:|---:|---:|---|
| Coherencia media | 0.3548 | 0.5154 | 45.3 % | 100*(NISAR-S1)/S1  (mayor es mejor) |
| Fracción píxeles usables | 0.5095 | 0.9207 | 80.7 % | 100*(NISAR-S1)/S1  (mayor es mejor) |
| Ruido std zona estable (mm) | 4.7255 | 3.5390 | 25.1 % | 100*(S1-NISAR)/S1  (menor es mejor) |

S1: 8 ifg, 2022-01-06 → 2024-09-16
NISAR: 1 ifg, 2025-10-30 → 2025-11-23

## Exactitud frente a verdad de terreno

### rmse_gnss_los
- Estado: **no_calculable**
- S1 cubre 2022-01-06–2024-09-16; NISAR cubre 2025-10-30–2025-11-23; no hay fechas en común
- no hay series GNSS descargables (NGL tenv3 404; hace falta RINEX de RAP/IGN procesado a ENU/LOS)
- no hay piezometros_niveles.csv (la CHG solo ofrece series por visor web, sin API CSV estable)
- no hay productos EGMS locales (API archive exige login CLMS)

### correlacion_piezometros
- Estado: **no_calculable**
- S1 cubre 2022-01-06–2024-09-16; NISAR cubre 2025-10-30–2025-11-23; no hay fechas en común
- no hay series GNSS descargables (NGL tenv3 404; hace falta RINEX de RAP/IGN procesado a ENU/LOS)
- no hay piezometros_niveles.csv (la CHG solo ofrece series por visor web, sin API CSV estable)
- no hay productos EGMS locales (API archive exige login CLMS)

### rmse_egms
- Estado: **no_calculable**
- S1 cubre 2022-01-06–2024-09-16; NISAR cubre 2025-10-30–2025-11-23; no hay fechas en común
- no hay series GNSS descargables (NGL tenv3 404; hace falta RINEX de RAP/IGN procesado a ENU/LOS)
- no hay piezometros_niveles.csv (la CHG solo ofrece series por visor web, sin API CSV estable)
- no hay productos EGMS locales (API archive exige login CLMS)

## Advertencias

- Las métricas de coherencia/ruido comparan productos sobre el mismo AOI; si no hay solape temporal, NO son una validación coetánea.
- NISAR es banda L (λ≈0.24 m); Sentinel-1 es banda C (λ≈0.055 m).
- No mezclar ambas plataformas en la misma inversión SBAS.
