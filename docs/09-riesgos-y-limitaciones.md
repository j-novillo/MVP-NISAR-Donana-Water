# Riesgos y limitaciones

La hipótesis puede ser falsa aunque el código sea correcto. Y el código puede
dar un mapa convincente sobre datos que no miden lo que se cree. Las dos cosas
están abiertas.

## Serie NISAR corta

A 2 de noviembre de 2026 hay del orden de 36 GUNW sobre la tesela, de finales
de junio a principios de octubre de 2026. No cubren una campaña de fresa
(octubre-junio). Un seno anual ajustado a un verano es inestable: se confunde
con la tendencia y con la atmósfera. NISAR, hoy, sirve para ver si la banda L
mantiene coherencia sobre el cultivo y los macrotúneles, y para el relato del
reto. La serie larga tiene que salir de Sentinel-1, y los GUNW de ARIA no
cubren este AOI: hay que procesar SLC (opción B) o traer los interferogramas
de otro sitio.

## El acuífero puede bajar de nivel sin hundirse

Almonte-Marismas es en buena parte semilibre. Si el esqueleto del terreno no
se comprime, el piezómetro cae y el satélite no ve nada. La spec lo dice: no
descartar la hipótesis hasta medir la amplitud estacional en dos o tres zonas
con bombeo conocido. El apoyo de piezómetros de esta PoC está para esa
comparación, no para sustituirla. Al revés, un cono claro con el nivel estable
tampoco se explica solo con el bombeo: puede ser una obra, una turba o un
artefacto.

## Atmósfera en pares cortos

Un par de 12 días puede llevar varios centímetros de fase troposférica. El
plano y el punto de referencia quitan la rampa y el sesgo constante; no quitan
una burbuja de vapor del tamaño del cono. El z-score con suelo de 1 mm asume
que, tras el apilado, el ruido residual está por debajo de la señal. Con pocos
pares de NISAR eso es optimista. Si el criterio de señal sale no-go, el
siguiente paso es MintPy con PyAPS, no un umbral más bajo.

## El plano se come lo que es grande

Una subsidencia de todo el sector, suave, cabe en el plano y en el anillo, y
desaparece. Es lo que se quiere (no marcar el acuífero entero como pozo) y es
también un límite: esta tubería no mide la explotación regional. Mide conos
de escala inferior a 1 km.

## Registro de pozos incompleto

`sin_pozo_declarado` es "no está en la capa", no "no existe". El registro de
la CHG tiene huecos, expedientes sin coordenada buena y captaciones en
trámite. Un +10 con la capa a medio bajar es un falso positivo. Por eso una
capa ausente anula el término en vez de activarlo. Aun así, una capa presente
pero incompleta no se detecta sola. Hay que leer la fecha y la cobertura del
WFS antes de fiarse del ranking.

## SIGPAC, SAR y los 847 cierres

Sin parcelas no hay score. Sin SAR el término legal se apaga. Sin cierres
georreferenciados el recuerdo queda en indeterminado y la viabilidad no se
puede cerrar. Ninguna de esas tres capas tiene, hoy, una descarga que esta
PoC pueda prometer. Los pasos manuales están en
`docs/02-descarga-de-datos.md`. Hasta que no estén, un go o un no-go real no
es interpretable.

## Signo de la fase y geometría LOS

El convenio de signo es una elección de configuración. Un signo al revés
invierte subsidencia y levantamiento, el z-score (definido sobre el hundimiento
mayo-noviembre) cambia de sentido y el detector deja de ver los conos o marca
los rebotes. Comprobarlo es parte del primer día con datos reales, no un
detalle.

El desplazamiento es en la línea de visión, no vertical. Un flujo horizontal
(poco probable aquí, no imposible en el borde del acuífero) entra en la misma
cifra. No se proyecta a vertical porque el ángulo no está en el flujo de la
opción A.

## El score es relativo

El mínimo-máximo se calcula dentro de la tesela. Ampliar al bbox completo
cambia el máximo y, con él, todos los scores. No se pueden comparar rankings
de dos AOI distintos. Los milímetros y el z-score sí se pueden comparar.

## Resolución y buffer

La celda es de 100 m y el buffer de 500 m. Un cono asigna sospecha a las
parcelas vecinas. El ranking no es una delimitación catastral del pozo. En
SIGPAC real, el centroide de la celda es una regla simple y discutible en los
bordes.

## Modo sintético

Los conos, los pozos, la SAR, el NDVI y los piezómetros están construidos para
que un pipeline sano supere el go, con dos cierres a propósito sin señal para
que el recuerdo no sea el 100 %. Superarlo no aporta evidencia sobre Doñana.
Sirve para no descubrir un error de inversión el día que lleguen los GUNW.

Los ficheros sintéticos usan los mismos nombres que los reales. Hay que
borrar `data/raw/` al cambiar de modo.

## Lo que quedaría fuera aunque todo lo anterior salga bien

Un mapa de score no es un procedimiento sancionador. La coordenada de un
cierre, la titularidad y el estado administrativo del expediente no salen de
un interferograma. Como mucho, esta tubería propone dónde mirar en campo y
contra el registro.
