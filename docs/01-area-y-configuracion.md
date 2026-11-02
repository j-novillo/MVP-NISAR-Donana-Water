# Área y configuración

## Por qué esta tesela

El acuífero Almonte-Marismas está declarado sobreexplotado. El triángulo de
mayor presión de regadío de fresa fuera de ordenación, según los informes de
WWF y las actuaciones de la Confederación Hidrográfica del Guadalquivir (CHG),
está al norte de la corona forestal de Doñana, entre Rociana del Condado y
Almonte (Huelva). La CHG ha cerrado cientos de captaciones desde 2024; esas
posiciones, si se georreferencian, son la verdad de campo del detector.

La PoC no empieza por los ~18×22 km del sector. Empieza por una tesela de
5×5 km centrada en el casco urbano de Rociana (37,30 N, 6,58 O) para poder
iterar la pila sin mover decenas de gigas. El bbox completo está en la misma
configuración y se activa cambiando una clave.

## `config.yaml`

| Clave | Qué controla |
|---|---|
| `modo` | `sintetico` o `real`. Lo lee `src/download.sh` |
| `aoi.activa` | `tesela_rociana` o `bbox_completo` |
| `referencia` | Píxel que se fuerza a cero en cada interferograma |
| `crs_metrico` | `EPSG:25829` (ETRS89, huso 29) |
| `procesado.coherencia_min` | 0,4. Por debajo, el píxel no entra en la inversión |
| `procesado.coherencia_zona_estable` | 0,5. Píxeles con los que se ajusta la rampa |
| `procesado.signo_fase` | Convenio fase → milímetros. Ver el doc de procesamiento |
| `procesado.plataforma` | `auto`, `NISAR` o `SENTINEL-1`. No se mezclan bandas |
| `medicion.malla_m` | 100 m. Tamaño de la celda de las mediciones |
| `medicion.anillo_min_m` / `anillo_max_m` | 1 y 2 km. Anillo del z-score |
| `medicion.sigma_suelo_mm` | 1 mm. Suelo de la desviación del anillo |
| `score.buffer_m` | 500 m |
| `score.meses_campana` | Octubre a mayo, el NDVI de la spec |
| `validacion.meses_riego` | Abril a junio, la coherencia "en campaña de riego" |
| `sintetico` | Semilla, resolución, fechas y amplitud de los conos falsos |
| `descarga` | Qué colecciones se piden y el tope de productos |
| `rutas` | Todo lo que la tubería lee y escribe |

Las rutas relativas se resuelven desde la raíz del repositorio
(`src/utilidades.py`).

## Rejilla

El origen de la rejilla se encaja hacia fuera al múltiplo de 100 m
(`malla_anidada`). Así los píxeles de 50 m del modo sintético (o los ~80 m de
un GUNW de NISAR, si se remuestrean a un múltiplo) caen enteros dentro de las
celdas de medición. La fila 0 es la más al norte, como en un GeoTIFF.

La tesela nominal de 5 km queda un poco mayor tras el encaje: se prefiere
cubrir el AOI entero a recortar un borde.

## Qué no hace la configuración

No guarda secretos. No elige el signo "correcto" de un producto que no hemos
abierto: `signo_fase` es una hipótesis explícita, revisable.
