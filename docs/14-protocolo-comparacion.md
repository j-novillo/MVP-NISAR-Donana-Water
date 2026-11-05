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

## GUNW observados

Los dos HDF5 completos declaran EPSG:32630, fase en radians y
`centerFrequency` 1,229 GHz, así que λ = c / f = 0,2439320244 m. No se usa
0,238403 m. Ambos son Ascending y Left. La incidencia aproximada en el punto
de referencia, a cota 0, es 45,71° y 45,72°; el array de incidencia es una
rejilla, no ese número. El par del 30 oct al 23 nov 2025 dura 24 días; el del
5 al 17 dic 2025 dura 12. El signo −1 de la configuración sigue sin anclar.

Que Rociana esté en el huso 29 no invalida el 32630. Se lee el CRS declarado
y se reproyecta. `crs_leido` queda en false solo si el fichero no trae EPSG.

Sentinel-1 IW mira a la derecha. Un ascendente S1 y un ascendente NISAR no
comparten la línea de visión. No se comparan desplazamientos como la misma
dirección sin proyectarlos con la incidencia y el azimut de cada geometría.
Las coherencias nativas se listan por producto en
`docs/datos-referencia/nisar_gunw_observado.json`, con `is_accuracy: false`.
No se convierten en un porcentaje frente a S1.

Hay seis jobs HyP3 en curso en el box: tres ascendentes de octubre–diciembre
de 2025, dos descendentes que se quieren comparar, y uno descendente del
20 oct al 1 nov de 2026. Ese último intervalo no corta los dos GUNW de 2025.
Aunque un ascendente S1 coincida en fechas, la mirada derecha frente a la
izquierda deja el desplazamiento `no_evaluable` hasta la proyección. No se
envían más jobs desde aquí. `HyP3(token=...)` usa el token Earthdata; no
hace falta usuario ni contraseña. EGMS sigue bloqueado por el login CLMS.

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
