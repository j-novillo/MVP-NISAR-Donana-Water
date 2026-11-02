# Cruce legal y score

Script: `src/score.py`. Al terminar llama a `src/validar.py`, salvo que se
pase `--sin-validar`.

## De la celda a la parcela

Cada celda de 100 m se asigna a la parcela que contiene su centroide. Una celda
a caballo entre dos recintos no se parte: entra en la que se queda el centro.
En el sintético las parcelas miden 200×200 m y están alineadas con la malla,
así que cada una se queda cuatro celdas limpias. En un SIGPAC real el borde
será más sucio; es una limitación conocida, no un error de asignación oculto.

Por parcela se promedian amplitud, velocidad y hundimiento, y se toma el
z-score máximo y la coherencia media.

## Buffer de 500 m

Se dibuja un buffer de 500 m alrededor del centro de cada celda con z > 2.
Una parcela que toca alguno de esos buffers lleva `en_buffer_anomalia=True`.

Ese buffer no entra en la fórmula. Sirve para dos cosas:

- el visor puede listar solo las parcelas que caen junto a una anomalía;
- se puede preguntar, como pide la spec, si dentro del entorno de la anomalía
  hay una captación registrada.

La pregunta "¿hay pozo declarado?" del término legal se responde a 500 m de la
**parcela**, no del centro de la anomalía: `sin_pozo_declarado` es falso si
algún pozo de `pozos_registrados.gpkg` intersecta el buffer de 500 m de la
parcela. `fuera_sar` es cierto si el punto representativo de la parcela cae
fuera del polígono SAR.

Si el fichero de pozos no existe, o el de la SAR no existe, el término legal
vale 0 y el log avisa. Una capa que no se ha podido descargar no es una prueba
de ilegalidad.

## NDVI de campaña

`data/raw/ndvi/ndvi_parcelas.csv` tiene `id_parcela`, `fecha`, `ndvi`.
El NDVI de campaña es la media de los meses de `score.meses_campana`:
octubre, noviembre, diciembre, enero, febrero, marzo, abril y mayo. La spec
menciona octubre-junio como temporada agronómica y octubre-mayo en la fórmula;
se usa octubre-mayo, que es lo que está escrito junto al score.

`cultivo_activo` es esa media por encima de 0,35. No filtra el score: queda
como columna para leer la tabla. Un barbecho con un cono encima puntúa menos
por el término de NDVI, no desaparece.

En datos reales el CSV lo construye `src/ndvi_s2.py` a partir de Sentinel-2 L2A
(`(B08−B04)/(B08+B04)`, máscara SCL de nube y sombra). En el sintético, el
cultivo activo ronda 0,66 en campaña y 0,18 en verano; el barbecho se queda
en ~0,22.

## La fórmula, tal cual

```
score = 40 · norm(amplitud_estacional)
      + 30 · norm(velocidad_subsidencia)
      + 20 · norm(ndvi_campaña)
      + 10 · (1 si sin_pozo_declarado y fuera_sar, si no 0)
```

`norm` es `(x − min) / (max − min)` sobre las parcelas con valor finito,
recortado a [0, 1]. Si todas valen lo mismo, el término vale 0.

`velocidad_subsidencia` es `max(0, −velocidad_mm_anio)`. Solo cuenta el
hundimiento. Un levantamiento no suma sospecha.

Los cuatro sumandos se guardan como `p_amplitud`, `p_velocidad`, `p_ndvi` y
`p_legal` para poder rehacer la cuenta a mano. El máximo teórico es 100.

Consecuencia que hay que tener presente: el mínimo-máximo es **relativo a la
tesela**. La parcela más extrema marca el 40, el 30 o el 20 aunque su
amplitud sea de 3 mm. El score ordena; no es una probabilidad ni un umbral
absoluto de ilegalidad. El z-score y los criterios go/no-go son los que miran
magnitudes en milímetros.

## Ejemplo numérico (el del test)

Dos parcelas, una en el mínimo de todo y otra en el máximo, con el flag legal
a 0 y a 1:

| | amplitud | velocidad subs. | NDVI | flag | score |
|---|---|---|---|---|---|
| A | 0 | 0 | 0,2 | 0 | 0 |
| B | 10 | 10 | 0,8 | 1 | 40+30+20+10 = 100 |

## Salida

`data/parcelas_score.parquet` y `data/parcelas_score.gpkg`, en WGS84, ordenadas
por score descendente, con columna `ranking`.

En la corrida sintética de referencia la primera es `I-011` (score 99,5):
fuera de la SAR, sin pozo declarado, NDVI ~0,66, amplitud ~33 mm. La amplitud
supera los 12 mm inyectados en cada cono porque los conos se solapan: en un
punto cercano a varios centros las gaussianas se suman. Las últimas del ranking
están dentro de la SAR y se quedan en torno a 5 puntos.

## Lo que el score no es

No es una denuncia. No usa los pozos cerrados ni los puntos WWF: esos solo
entran en la validación. Un score alto con la capa de pozos incompleta (y el
registro de la CHG lo es, en tramos) puede marcar un pozo que existe y no está
en la capa. Por eso la ausencia de capa entera anula el +10, y por eso un go
legal en datos reales exige haber mirado la completitud del registro, no solo
el JSON.
