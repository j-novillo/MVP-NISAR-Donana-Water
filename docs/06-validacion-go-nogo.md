# Validación go / no-go

Script: `src/validar.py`. Lo llama `score.py` al acabar, y también se puede
lanzar solo: `python src/validar.py`. Escribe `data/validacion.json`.

Hay dos decisiones y no significan lo mismo.

- `decision_tuberia`: los cuatro criterios de la tabla de la spec, aplicados
  a los ficheros que hay ahora mismo.
- `decision_cientifica_donana`: en modo sintético queda siempre en
  `pendiente_de_datos_reales`. Un go de la tubería, ahí, demuestra que el
  detector recupera conos que se han inyectado a propósito. No dice nada del
  acuífero.

## Los cuatro criterios

### 1. Coherencia en campaña de riego

Fracción de píxeles nativos cuya coherencia media en los pares de abril, mayo
y junio supera 0,4.

- Go: > 30 %.
- No-go: < 5 % (la spec habla de cobertura fragmentada, sin píxeles coherentes
  en cultivo).
- En medio: indeterminado.

En el sintético, con una coherencia pensada para parecerse a banda L sobre
cultivo (~0,6) y una franja de marisma a ~0,25, sale en torno al 86 %. En
banda C real, sobre fresa y plástico, este número puede caer por debajo del
30 % aunque el resto de la tubería esté bien. Ese sería un no-go de la opción
A, y el motivo para probar la B o para quedarse con NISAR donde la L sí
coherencie.

### 2. Señal de subsidencia local

Dos números:

- La mediana del exceso (hundimiento de la celda menos media del anillo) dentro
  de las celdas con z > 2 y coherencia suficiente. Es el tamaño del cono, en
  milímetros.
- La fracción de esas celdas que tiene otra anomalía a menos de 250 m.

Go si el cono mide al menos 5 mm **y** al menos la mitad de las anomalías
están agrupadas. No-go si el cono se queda por debajo de 2 mm, o si hay
anomalías sueltas (menos del 20 % agrupadas) y además no llegan a 5 mm.
La spec contrapone "gradientes locales de 5-10 mm distinguibles del ruido" a
"z-score sin estructura espacial".

No se usa el percentil 90 de toda la tesela como umbral. Un cono local no lo
mueve, y declararía no-go aunque el cono fuera nítido. Ese percentil se guarda
igual, como `p90_exceso_aoi_mm`, para no esconderlo.

En el sintético la mediana del exceso en las anomalías ronda 30 mm (conos de
12 mm de amplitud que se solapan; el hundimiento mayo-noviembre es del orden
del doble de la amplitud) y el 100 % de las anomalías tiene vecina.

### 3. Discriminación legal

Entre las celdas con z > 2:

- fracción que tiene un pozo registrado a menos de 500 m;
- de las que están fuera de la SAR y a más de 500 m de cualquier pozo
  registrado, fracción que cae a menos de 500 m de un punto documentado
  (pozo cerrado o punto WWF).

Go si el solape con lo documentado es ≥ 50 % y menos de la mitad de las
anomalías cae junto a un pozo legal. No-go si ≥ 80 % de las anomalías está
junto a un pozo legal y el solape documentado es < 20 % ("las anomalías solo
salen donde ya hay pozo declarado").

Sin capa de registrados, sin SAR o sin ninguna anomalía, el criterio queda en
indeterminado. No se fuerza un go por falta de contradicción.

En el sintético: 0 % de las anomalías junto a un pozo registrado, y ~90 % de
las inexplicadas junto a un punto documentado.

### 4. Pozos cerrados

Fracción de los puntos de `pozos_cerrados.gpkg` cuya celda de 100 m (el
centroide más cercano, a 150 m como mucho) tiene z > 2.

- Go: > 50 %.
- No-go: < 20 %.
- En medio: indeterminado.

Sin la capa, indeterminado, con un texto que recuerda que los 847 cierres no
están en un shapefile público único.

En el sintético hay 8 cierres. Seis se colocaron en un cono y dos, lejos, sin
señal inyectada. El recuerdo sale 6/8 = 75 %: por encima del go, y no el
100 %, que sería sospechoso. Esos dos son el caso "se cerró, o la coordenada
está mal, y no queda un cono medible".

## Decisión global

Go solo si los cuatro son go. Un solo no-go vuelve la global no-go. Cualquier
indeterminado sin no-go deja la global en indeterminado.

## Piezómetros

No son un quinto umbral. La spec pide comprobar que el nivel freático cae
donde hay anomalía. Se compara la profundidad media de abril-junio con la de
octubre-noviembre.

- Cerca: piezómetros a menos de 1 km de alguna celda con z > 2.
- Lejos: el resto.

`coherente_con_anomalias` es cierto si el descenso cercano supera al lejano
en más de 0,5 m. En el sintético, ~1,9 m frente a ~0,3 m. En datos reales es
una comprobación cualitativa: un acuífero semilibre puede bajar el nivel sin
comprimir el terreno, y al revés un cono puede no tener un piezómetro al lado.

## Cómo no leer el JSON

- Un go sintético no autoriza a señalar parcelas reales.
- Un no-go de coherencia en banda C no cierra la hipótesis: puede ser el
  sensor, no la ausencia de subsidencia.
- Un go de recuerdo con una capa de cierres pequeña y elegida a mano tampoco
  es una validación. Hace falta el conjunto, o una muestra definida antes de
  mirar el mapa.
- El score de una parcela no es el criterio. Una parcela puede puntuar alto
  por NDVI y amplitud y estar dentro de la SAR; el +10 no la convierte en
  hallazgo, y su ausencia no la absuelve si el cono es claro.
