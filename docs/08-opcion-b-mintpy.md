# Opción B: MintPy / SBAS

La spec lo deja dicho: si la opción A no ve la señal, no se abandona el
enfoque. El apilado directo de GUNW pierde sensibilidad cuando queda fase
residual (atmósfera que no era un plano, desenvolvimiento a trozos, pares
cortos). El camino robusto es un SBAS sobre Sentinel-1 SLC, con MintPy, y
usar los GUNW de NISAR como contraste de coherencia en banda L, no como la
única serie.

Esta PoC **no ejecuta** ISCE2 ni MintPy. No están en `environment.yml`.
Instalarlos es otro entorno:

```bash
conda env create -f environment-opcion-b.yml
```

`isce2` y `mintpy` vienen de conda-forge. Es un entorno pesado y no hace falta
para `procesar_insar.py`.

## Pasos, cuando toque

1. Activar SLC en la config (`descarga.sentinel1_slc: true`) y bajar un track
   ascendente y, si se puede, uno descendente, 2022-2026, recortados al AOI.
   El catálogo de ASF sí tiene SLC sobre la tesela; los GUNW de ARIA, no
   (consulta del 2 de noviembre de 2026).
2. Procesar el stack con ISCE2 topsStack, con el DEM (GLO-30; ver la nota del
   catálogo CDSE en `docs/02-descarga-de-datos.md`).
3. Correr MintPy `smallbaselineApp.py` con la plantilla
   `config/mintpy_smallbaselineApp.cfg` (la vuelve a escribir
   `src/opcion_b_mintpy.py`):

   - referencia geográfica en Rociana, 37,30 N, 6,58 O;
   - red por coherencia, umbral 0,4;
   - corrección troposférica PyAPS;
   - derampa lineal;
   - función temporal polinómica de grado 1 (la estacional se ajusta después,
     en `medir.py`, para no cambiar de criterio entre la A y la B).

4. Convertir la salida al formato de la opción A:

```bash
python src/opcion_b_mintpy.py --timeseries ruta/a/timeseries.h5
```

MintPy guarda metros en `timeseries`, fechas en `date` y el affine en
`X_FIRST`, `Y_FIRST`, `X_STEP`, `Y_STEP`. El conversor pasa a milímetros y
escribe `data/procesado/serie_mm.npz` más `metadatos.json`. A partir de ahí,
`medir.py` y `score.py` no saben si la serie vino de un GUNW o de un SBAS.

La coherencia, en esa conversión, se rellena con unos. El criterio de
coherencia **no es válido** hasta sustituirla por la `temporalCoherence` de
MintPy. El log lo dice. No se ha querido dar un go de coherencia gratis.

## Qué mirar para decidir el pivote

- Criterio de señal en no-go o indeterminado, con la coherencia en go: la fase
  coherente no enseña un cono. Puede ser atmósfera residual. Toca SBAS con
  PyAPS antes de concluir que el acuífero no se deforma.
- Coherencia en no-go sobre cultivo en banda C, y NISAR todavía corto: no hay
  un SBAS que recupere fase donde no hay coherencia. Ahí el límite es físico.
- Los dos sensores, cuando los dos existan con serie suficiente, deberían
  señalar los mismos conos en LOS. Si no lo hacen, no se publica el mapa.

## Lo que la plantilla no resuelve

El ángulo de incidencia, la proyección a vertical, el apantallamiento
ionosférico de la banda L y la elección de track. Son decisiones de un
procesado completo, no de esta PoC, y están nombradas para que no parezca que
el conversor las da por hechas.
