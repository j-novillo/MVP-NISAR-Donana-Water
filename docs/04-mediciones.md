# Mediciones

Script: `src/medir.py`. Entrada: la serie de `procesar_insar.py`.
Salida principal: `data/resultados.parquet`, una celda de 100 m por fila.
También escribe `data/geotiff/*.tif` y `data/procesado/serie_malla100.npz`.

La spec pide agregar a 100 m antes de medir. El cono de un pozo no es un
píxel de 50 u 80 m, y promediar reduce el ruido de la fase sin borrar una
señal de unos cientos de metros. El factor de agregación es
`malla_m / resolución_nativa` y tiene que ser entero. La media ignora los NaN;
un bloque entero sin dato sigue en NaN (la marisma sintética, abajo del todo
de los mapas).

## Velocidad

Se ajusta, en cada celda, el modelo

```
d(t) = c + v·t + A·sin(2πt) + B·cos(2πt)
```

con t en años desde la primera fecha. `v` es `velocidad_mm_anio` (mm/año).
Negativo = la superficie se aleja del satélite con el tiempo = subsidencia en
el convenio por defecto.

La spec dice "regresión lineal" y, aparte, "ajuste de seno anual". Hacer las
dos cosas por separado sesga las dos: una recta a través de un ciclo que no
cubre años enteros se queda con parte del seno, y un seno a través de una
tendencia se queda con parte de la recta. El ajuste conjunto es la regresión
lineal con dos columnas más. La recta sola, sin seno, se guarda en
`velocidad_lineal_mm_anio` para poder compararla, y no entra en el score.

Hace falta un mínimo de fechas (`medicion.min_fechas_ajuste`, 8). Con los
36 GUNW reales de un solo verano, este ajuste es débil: el seno anual y la
recta se confunden. Es una razón de fondo para no fiar el criterio de señal
solo a NISAR 2026.

## Amplitud estacional

```
amplitud = sqrt(A² + B²)
```

en milímetros. Es la semi-amplitud del ciclo anual. El bombeo de la fresa, si
la hipótesis es cierta, hunde el terreno entre abril y junio (el pico de
extracción) y deja que recupere en otoño, cuando para el riego. Un ciclo de
un año con esa fase es la firma; una tendencia lineal monótona puede ser el
acuífero entero, la tectónica o una deriva del procesamiento, y el anillo se
encarga de no contarla como pozo.

## Hundimiento estacional

Para cada año que tenga una fecha cerca del 15 de mayo y otra cerca del 15 de
noviembre:

```
hundimiento = d(noviembre) − d(mayo)
```

Positivo = mayo más bajo que noviembre. Se promedia entre los años disponibles.
Es un desplazamiento, no un parámetro del seno, y es lo que entra en el
z-score. Encaja con la frase de la spec: el z-score del desplazamiento, no el
de la velocidad.

En el modo sintético el cono se inyecta como `−A·cos(2π·(día−135)/365,25)`,
mínimo a mediados de mayo. Noviembre − mayo vale unos `2A` más la contribución
de la tendencia en esos seis meses. Por eso la amplitud ajustada (~la mitad
del vaivén) y el hundimiento (el vaivén de mayo a noviembre) no son el mismo
número, y no tienen que serlo.

## Z-score contra el anillo de 1-2 km

El acuífero puede hundirse entero unos milímetros al año. Eso no delata un
pozo. Para cada celda se toma la media y la desviación del hundimiento en el
anillo entre 1 y 2 km (no dentro de 1 km: ahí todavía está el propio cono) y

```
exceso = valor − media_del_anillo
z      = exceso / max(desviación, sigma_suelo)
```

`sigma_suelo` es 1 mm. Si el anillo es casi homogéneo, la desviación muestral
sale ridícula y cualquier décima de milímetro, ruido numérico, daría un
z-score enorme. El suelo pone un ruido mínimo creíble para un apilado corto
sin corrección atmosférica fina. Una celda tiene que separarse más de 2 mm
de su anillo (con el suelo a 1 mm) para pasar de z = 2. Los conos que se
buscan están en el rango de 5-10 mm o más; el suelo no se los traga. Sí impide
que un campo plano se llene de falsas anomalías.

El anillo se calcula por desplazamientos enteros de celda, sin matriz de
distancias. En el bbox completo (~200×220 celdas) una matriz celda-contra-celda
no cabe en memoria; los offsets sí.

Una celda es anomalía si `z > 2` y su coherencia media sigue por encima de 0,4.

El percentil 90 del exceso en **toda** la tesela no sirve como umbral de
viabilidad: un cono ocupa poca superficie y no mueve ese percentil. El criterio
de señal usa la mediana del exceso dentro de las celdas que ya tienen z > 2
(cuántos milímetros mide el cono) y exige además que esas celdas estén
agrupadas. Ver `docs/06-validacion-go-nogo.md`.

## Coherencia media

La media de la coherencia de los pares, agregada a la celda, y la media solo
de los pares cuyo extremo cae en abril-junio. La segunda es la que usa el
criterio de campaña de riego, calculada en la resolución nativa para no
maquillarla con el promediado a 100 m.

## Columnas de `resultados.parquet`

`id_celda`, `fila`, `columna`, `x_utm`, `y_utm`, `lon`, `lat`,
`velocidad_mm_anio`, `velocidad_lineal_mm_anio`, `amplitud_estacional_mm`,
`hundimiento_estacional_mm`, `zscore`, `media_anillo_mm`, `std_anillo_mm`,
`exceso_mm`, `coherencia_media`, `coherencia_campana`,
`desplazamiento_final_mm`, y la geometría de la celda en EPSG:25829.

## GeoTIFF

`src/medir.py` escribe en `data/geotiff/`, float32, nodata −9999, deflate,
el mismo affine que la malla de 100 m:

- `zscore.tif`
- `amplitud_estacional_mm.tif`
- `velocidad_mm_anio.tif`
- `hundimiento_estacional_mm.tif`
- `coherencia_media.tif`

Sirven para abrirlos en QGIS sobre el PNOA sin pasar por el visor.
