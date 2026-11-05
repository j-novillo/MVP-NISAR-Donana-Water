# Procesamiento InSAR (opción A)

Script: `src/procesar_insar.py`. Lectura: `src/lectura_gunw.py`.

La opción A no genera interferogramas y no desenvuelve la fase. Parte de un
GUNW: un interferograma ya geocodificado y ya desenvuelto. NISAR lo distribuye
en HDF5, a unos 80 m. ARIA hace lo equivalente en banda C de Sentinel-1. El
modo sintético escribe un GeoTIFF de dos bandas con el mismo papel, para que
el resto de la tubería no tenga un camino aparte.

## Qué es un interferograma, en una página

Cada píxel de un GUNW es la diferencia de fase entre dos pasadas del satélite
sobre el mismo punto. La fase envuelta vive entre −π y π; desenvolverla es
sumar los saltos de 2π para recuperar una rampa continua. Eso ya lo ha hecho
el productor del GUNW. Aquí se asume que ese desenvolvimiento es bueno donde
la coherencia es alta y donde la componente conexa no es cero.

La fase (radianes) se pasa a desplazamiento en la línea de visión (LOS), en
milímetros:

```
d_mm = signo · (λ / 4π) · fase · 1000
```

Con `signo = -1` (el defecto), una fase positiva es un alejamiento del
satélite. En una geometría casi vertical, alejarse es hundirse, así que la
subsidencia sale negativa. λ de la banda L de NISAR se toma como 0,238403 m
si el producto no trae la suya. La de Sentinel-1, cuando entra un GUNW de
ARIA, es la del propio fichero (~0,0555 m).

Este signo no es una ley. Hay productos que definen la fase al revés. Antes
de creerse un mapa real hay que mirar un punto que se sepa estable o un
hundimiento conocido y, si hace falta, cambiar `procesado.signo_fase`.
El valor −1 no está anclado en los GUNW reales. Su `centerFrequency` es
1,229 GHz (λ = 0,2439320244 m) y declaran EPSG:32630; el huso 29 de Rociana
no sustituye a ese CRS. NISAR mira a la izquierda y Sentinel-1 a la derecha.

## Coherencia

La coherencia (0 a 1) mide cuánto se parecen los dos ecos. Cerca de 1, la fase
es repetible (urbano, roca, suelo desnudo). Cerca de 0, el eco ha cambiado
entre las dos fechas (vegetación movida por el viento, agua, laboreo) y la
fase es ruido.

El umbral de la spec es 0,4. Por debajo, el píxel se enmascara y no entra en
la inversión. Además, si el HDF5 trae `connectedComponents`, el valor 0 se
enmascara: el algoritmo de desenvolvimiento no supo enlazar ese píxel con el
resto.

La banda L de NISAR (longitud de onda ~24 cm) mantiene la coherencia mejor que
la banda C de Sentinel-1 sobre cultivo y sobre los plásticos de los
macrotúneles. Por eso el reto pide NISAR aunque su serie todavía sea corta:
puede haber fase útil donde Sentinel-1 solo ve decorrelación. El criterio de
viabilidad lo mide directamente: si en campaña de riego (abril-junio) menos
del 30 % de los píxeles supera 0,4, la opción A no tiene de dónde sacar un
cono, y toca mirar la B o aceptar que esa zona no se puede medir así.

## Rampa atmosférica

La troposfera añade una fase que varía suave en el espacio, a escala de
kilómetros, y que no tiene nada que ver con el pozo. En un interferograma
suelto puede valer más que los 5-10 mm que se buscan.

Se ajusta un plano `a + b·columna + c·fila` a los píxeles con coherencia
≥ 0,5 (la "zona estable" de la spec) y se resta. Un plano cabe en una rampa
regional. Un cono de unos cientos de metros no es un plano: el ajuste, dominado
por el resto de la tesela, casi no lo toca.

Eso deja de ser verdad si la señal ocupa media tesela (un hundimiento de todo
el acuífero, no un pozo). El plano se lo comería. El anillo de 1-2 km del
paso siguiente está pensado para quitar lo que es regional y dejar lo local;
el plano de este paso solo persigue la atmósfera de cada par. No sustituye a
una corrección troposférica de verdad (PyAPS, en la opción B).

## Punto de referencia

Después de quitar el plano, se resta el valor del píxel del casco urbano de
Rociana. Cada interferograma queda referido a ese punto: lo que se mide es
movimiento respecto a Rociana, no un absoluto. Si ese píxel está enmascarado,
se usa el vecino finito más cercano, hasta 5 píxeles. Si no hay ninguno, el
par entero se descarta.

La hipótesis es que el casco, compactado, no se mueve con el bombeo. Si se
moviera, toda la tesela heredaría ese movimiento con el signo cambiado.

## Inversión de la red

Un interferograma no da el desplazamiento en una fecha: da la diferencia entre
dos. Con muchos pares se monta un sistema.

Para cada par entre las fechas i y j, con la fecha 0 fija en cero:

```
d_j − d_i = observación
```

La matriz de diseño tiene una fila por par y una columna por fecha (menos la
primera). Se resuelve por mínimos cuadrados (`numpy.linalg.lstsq`), a la vez
para todos los píxeles que tienen todos los pares válidos. Es el sistema de
unas pocas decenas de ecuaciones que menciona la spec.

Los pares redundantes (en el sintético, cada mes y cada tres meses) sobredeterminan
el sistema y promedian el ruido. Si a un píxel le faltan pares, se resuelve
aparte, y solo si el rango de su matriz sigue siendo completo. Si la red no
ancla todas las fechas, no se acepta la solución de norma mínima que devolvería
`lstsq`: inventaría desplazamientos en la componente que nadie ha observado.
Ese píxel se queda en NaN.

La serie resultante está en milímetros, relativa a la primera fecha y al
punto de Rociana. Positivo = hacia el satélite.

No se mezclan NISAR y Sentinel-1 en la misma inversión. Cambia la longitud de
onda, el ángulo de incidencia y lo que "ve" la coherencia. `plataforma: auto`
se queda con la que aporte más pares y lo escribe en el log.

Si un producto no cae en la rejilla del primero, se remuestrea con `rasterio`
(bilineal). En la tesela sintética todos comparten rejilla y este paso no hace
nada.

## Salida

`data/procesado/serie_mm.npz`

- `serie_mm`: (fechas, filas, columnas)
- `fechas`: ISO-8601
- `coherencia_media` y `coherencia_campana`: medias de la coherencia **sin**
  enmascarar, para que el criterio de viabilidad cuente también los píxeles
  malos

`data/procesado/metadatos.json` guarda la plataforma, el affine, el CRS, el
píxel de referencia y el signo usado.

## Lo que este paso no hace

No corrige atmósfera con un modelo, no desenvuelve, no proyecta de LOS a
vertical (haría falta el ángulo de incidencia, que el GUNW trae y aquí no se
usa: la spec pide la serie en la geometría del producto). No rellena huecos.
