# Protocolo de comparación NISAR / Sentinel-1

Esto no es el informe de viabilidad. El informe espera los pares Sentinel-1
del solape NISAR, la lectura del GUNW en el box y, si se usa como exactitud,
GNSS proyectado a la línea de visión. Hasta entonces la comparación está
`no_evaluable`. No se inventan porcentajes.

Código: `src/comparacion_protocolo.py`, usado por `src/comparar_nisar_s1.py`.

## Cuándo hay solape

El solape es la intersección de intervalos de pares, no el mínimo y el máximo
de cada pila. Un stack de 2022 a 2026 no solapa un GUNW de noviembre de 2025
si ningún par Sentinel-1 corta esas dos fechas.

## Qué se reporta por separado

En la misma zona y en la misma rejilla:

- cobertura nativa de Sentinel-1 y cobertura nativa de NISAR, cada una con su n;
- máscara común (píxeles finitos en los dos);
- resolución de salida y posting de origen;
- referencia (el casco de Rociana no basta si el signo no está anclado);
- unidades (mm en línea de visión, no vertical, salvo que se diga y se tenga el ángulo);
- azimut e incidencia de cada geometría;
- estación o intervalo común;
- n de pares e incertidumbre.

## La única mejora

```
100 * (err_S1 - err_NISAR) / err_S1
```

Solo si `err_S1 > 0` y la comparabilidad está completa. No se promedian
coherencia, cobertura y dispersión en un solo porcentaje. Si el baseline no
es positivo o falta un requisito, el estado es `no_evaluable` y el porcentaje
es null.

Coherencia y fracción usable pueden guardarse como exploratorias. La
desviación típica espacial en el casco, tras quitar la mediana, es dispersión
espacial. No se llama ruido instrumental si no se ha demostrado que la zona
es estable y que el residuo no tiene estructura. Con 11 o 29 píxeles y épocas
distintas, esa demostración no existe.

## Referencias

| Fuente | Qué es | ¿Entra en el RMSE de exactitud? |
|---|---|---|
| GNSS en ENU, proyectado a LOS con azimut e incidencia | Desplazamiento geodésico | Sí, si el intervalo coincide y el signo está anclado |
| Piezómetro | Nivel de agua, no desplazamiento | No |
| EGMS L2/L3 | Movimiento desde Sentinel-1 | No como verdad independiente de S1 |

## Primer GUNW ya citado

Nombre en los docs del 4 nov 2026:
`NISAR_L2_PR_GUNW_004_015_A_021_006_2000_SH_20251030T053143_…_20251123T053219_…`.
Las fechas del nombre van del 2025-10-30 al 2025-11-23 (24 días). La guía
ASF describe GUNW de vecinos a 12 días y fase desenvuelta en radianes, en
una rejilla de unos 80 m, en UTM o estereográfica polar. La conversión del
repo es `d_mm = signo * (λ / 4π) * fase * 1000`, con λ ≈ 0,238403 m. El
signo −1 no está comprobado contra un control.

Rociana (−6,58°) cae en el huso UTM 29. La guía local mencionó EPSG:32630
para ese producto. Aquí no está el HDF5: no se reafirma el EPSG. Si el
fichero no trae proyección, el lector deja EPSG:25829 y `crs_leido=False`,
y la comparación queda `no_evaluable`. Releer el dataset `projection` en el
box antes de citar huso.

## Legal

La subsidencia no detecta un pozo ni una ilegalidad. Que no esté el
inventario de concesiones no significa que la extracción sea ilegal.

## Comandos (no descargan GB y no lanzan jobs)

```bash
python -m pytest -q
python src/catalogo_s1_solape.py --inicio 2025-10-01 --fin 2025-12-31
python src/preparar_hyp3.py --referencia ID_REF --secundaria ID_SEC
python src/leer_egms.py
python src/comparar_nisar_s1.py
```

El catálogo con `--consultar`, el POST HyP3 con `--enviar` y
`descarga_nisar_chunked.py` se ejecutan en el box, con el secreto ya
autorizado. No forman parte de esta corrida.

La salida nueva del comparador va a `data/comparacion/`, que no se versiona,
para no pisar la instantánea etiquetada de `docs/comparacion-nisar-s1.json`.

## Insumos mínimos para el informe final

Sin esto el informe no se escribe:

1. Pares Sentinel-1 HyP3 (o GUNW equivalentes) cuyo intervalo corte de verdad
   los GUNW NISAR usados, con mapas de desplazamiento o fase, coherencia,
   incidencia y vectores de mirada. Misma zona de la tesela.
2. Los HDF5 NISAR de ese solape, con el EPSG leído del producto (no asumido)
   y el signo de fase contrastado con al menos un control.
3. Para exactitud: serie GNSS ENU de una estación en el AOI o junto a él,
   en las mismas fechas, más azimut e incidencia para pasarla a LOS.
4. Opcional y sin llamarlo verdad independiente: CSV o GeoTIFF EGMS local,
   etiquetado como producto Sentinel-1.
5. Opcional y sin llamarlo desplazamiento: serie de nivel piezométrico.
6. El inventario de concesiones y la SAR solo si el informe habla de legalidad.
   Su ausencia no se interpreta como ilegalidad.

No hace falta, para ese informe, rehacer el modo sintético ni sustituir las
observaciones ya descritas.
