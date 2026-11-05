# Comparación NISAR vs Sentinel-1

Estado de la comparación: **no_evaluable**. No hay un porcentaje global de mejora.

Este texto corrige la tabla que citaba +45,3 % de coherencia, +80,7 % de
píxeles usables y +25,1 % de «ruido» urbano. Esas tres cifras salieron de
comparar el stack Sentinel-1 HyP3 de 2022-01-06 a 2024-09-16 (8 pares) con
un solo GUNW NISAR de 2025-10-30 a 2025-11-23. No comparten fechas, no
comparten el número de pares y no se midieron sobre una máscara común. No
son una mejora de exactitud y no se vuelven a presentar como tal.

Los valores medidos entonces siguen en `docs/comparacion-nisar-s1.json`,
bajo `exploratorio_historico`, con `mejora_pct` en null. No se han
recalculado: en este entorno no están los interferogramas.

Los dos GUNW completos, leídos por sus metadatos, declaran EPSG:32630,
fase en radianes y 1,229 GHz (λ = 0,2439320244 m, no 0,238403 m). Son
Ascending/Left, con incidencia aproximada 45,7°. Sentinel-1 mira a la
derecha: aunque un job ascendente coincida en fechas, el desplazamiento no
es la misma dirección. Las coherencias nativas de cada par están en
`docs/datos-referencia/nisar_gunw_observado.json` y no se convierten en un
porcentaje. El signo −1 sigue sin anclar. El huso 29 de Rociana no invalida
el 32630: se reproyecta.

## Qué falta para que una mejora sea evaluable

La única fórmula admitida es `100 * (err_S1 − err_NISAR) / err_S1`, y solo
si el error de S1 es > 0 y se cumplen a la vez el solape de pares, la misma
zona, la máscara común (además de la cobertura nativa de cada sensor), la
resolución, la referencia, las unidades LOS en mm, la incidencia registrada,
el intervalo o la estación, un n suficiente, la incertidumbre, el CRS leído
del producto y el signo de fase anclado. El protocolo está en
`docs/14-protocolo-comparacion.md`.

## Exactitud

RMSE GNSS en LOS, correlación piezométrica y RMSE contra EGMS siguen sin
porcentaje. El nivel del pozo no es desplazamiento. EGMS sale de Sentinel-1
y no es una verdad independiente. El catálogo de estaciones GNSS no es una
serie de desplazamiento.
