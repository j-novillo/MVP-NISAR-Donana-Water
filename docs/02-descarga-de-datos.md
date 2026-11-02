# Descarga de datos

`bash src/download.sh` mira `modo` en `config.yaml`.

- `sintetico`: ejecuta `src/sintetico.py` y no abre la red.
- `real`: ASF, Copernicus y capas. `--listar` escribe los CSV de catálogo y
  no baja binarios. `--real` y `--sintetico` fuerzan el modo aunque el YAML
  diga otra cosa.

Los CSV de catálogo salen en `data/raw/` y no se versionan.

## ASF / NASA (`src/descarga_asf.py`)

Cliente: `asf_search`. Búsquedas que construye `construir_busquedas` (se puede
probar sin red; el test lo hace):

| Colección | Filtro | Cuándo |
|---|---|---|
| NISAR GUNW | `dataset=NISAR`, `processingLevel=GUNW`, desde 2025-10-01 | Siempre en modo real. Es el producto del reto |
| ARIA S1 GUNW | `dataset=ARIA S1 GUNW`, `processingLevel=GUNW_STD`, 2022-2026 | Interferogramas ya desenvueltos para alargar la serie |
| Sentinel-1 SLC | IW, ascendente y descendente | Solo si `descarga.sentinel1_slc: true`. Pesan mucho; son la entrada de la opción B |

El catálogo de la NASA (CMR) se consulta sin token. La descarga llama a
`resultados.download` y exige `EARTHDATA_TOKEN` (token de portador de
<https://urs.earthdata.nasa.gov/>). Si falta, el programa se detiene y lo
dice; no intenta una sesión a medias.

### Qué había en el catálogo el 2 de noviembre de 2026

Sobre la tesela de Rociana, sin descargar:

- 36 GUNW de NISAR entre el 27 de junio y el 8 de octubre de 2026, en pases
  ascendentes y descendentes, con pares de unos 12 días. Hay producto, y la
  serie es de un verano: corta para un seno anual.
- 0 GUNW de ARIA Sentinel-1 entre 2022 y 2026. La serie larga no está hecha
  en ASF para este recinto.
- Sí hay SLC de Sentinel-1 (el recorte enero-junio de 2024 devuelve productos).

Los nombres de NISAR traen cuatro sellos de tiempo (inicio y fin de cada
época). El lector se queda con el primero y el tercero como fechas del par.

## Copernicus Data Space (`src/descarga_cdse.py`)

Catálogo OData público:
`https://catalogue.dataspace.copernicus.eu/odata/v1/Products`.

Descarga:
`https://zipper.dataspace.copernicus.eu/odata/v1/Products(<id>)/$value`.

### Token

El access token de CDSE caduca en unos 10-30 minutos. Por eso el camino
previsto es `CDSE_USERNAME` + `CDSE_PASSWORD`:

1. La primera vez, grant `password` contra
   `https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token`
   con `client_id=cdse-public`.
2. La respuesta trae `refresh_token` y `expires_in`.
3. Dos minutos antes de caducar, el cliente pide un grant `refresh_token` y
   no vuelve a enviar la contraseña.
4. Si una descarga responde 401, se renueva una vez y se reintenta.

`CDSE_ACCESS_TOKEN` se acepta si no hay usuario. No se puede refrescar: al
caducar hay que generar otro. El cliente no escribe usuario, clave ni token
en el log; si el servidor rechaza el token, el mensaje solo lleva el código
HTTP.

### Filtros

- Sentinel-2 L2A (`S2MSI2A`), nubes por debajo de `sentinel2_nubes_max` (20),
  desde 2022. El 2 de noviembre de 2026 este filtro respondía y los productos
  de la tesela caen en el tile MGRS `T29SQB`.
- DEM Copernicus GLO-30: `Collection/Name eq 'COP-DEM'` y nombre con `GLO-30`.
  La misma consulta, incluso sin recorte espacial, devolvió cero productos.
  La opción A no usa el DEM. Si la opción B lo necesita y el catálogo sigue
  vacío, hay que bajarlo del Copernicus Browser.
- Sentinel-1 SLC por CDSE solo si `descarga.sentinel1_slc` está activo (el
  mismo interruptor que en ASF). El filtro de SLC sí responde.

`src/ndvi_s2.py` no descarga. Lee los JP2 ya bajados (B04, B08 y, si está, SCL),
calcula el NDVI y lo promedia por parcela al CSV que espera el score.

## Capas legales (`src/descarga_capas.py`)

### Captaciones de la CHG (sí hay WFS)

Conjunto publicado en datos.gob.es y servido por la IDE del Guadalquivir:

```
https://idechg.chguadalquivir.es/geoserver/ggiscloud_root/ows
typeName = ggiscloud_root:captaciones_dph
```

`construir_url_wfs` pide GeoJSON, `EPSG:4326` y el bbox del AOI. El resultado
se recorta otra vez en local y se guarda como
`data/raw/capas/pozos_registrados.gpkg`. Si el servicio no responde, el estado
queda en `estado_descarga.json` y el proceso sigue: el resto de capas no debe
caerse por una.

El mismo servicio tiene un WMS para mirar la capa sin descargarla:
`https://idechg.chguadalquivir.es/geoserver/ggiscloud_root/wms`.

### Piezómetros SIA (se intenta, no se promete)

WMS conocido de MITECO:

```
https://gis.miteco.gob.es/geoserver/agua/RedPiezometrica/wms
```

El script pide el GetCapabilities del WFS homónimo, busca una capa cuyo nombre
contenga "piezo" y prueba un GetFeature recortado. Si no hay geometrías, no
falla la tubería.

Pasos manuales si el WFS no sirve:

1. Visor <https://sig.mapama.gob.es/geoportal/>, red piezométrica, dentro del AOI.
2. `data/raw/capas/piezometros.gpkg` con columna `id_piezometro`.
3. `data/raw/capas/piezometros_niveles.csv` con `id_piezometro`, `fecha`,
   `profundidad_m` (mayor = nivel más bajo).

### SIGPAC (no hay descarga vectorial estable)

Los WMS nacionales dibujan y no devuelven el recinto:

- <https://wms.mapa.gob.es/sigpac/wms>
- <https://sigpac-hubcloud.es/wms>

Pasos:

1. Visor <https://sigpac.mapa.gob.es/fega/visor/> o el de la Junta
   (<https://www.juntadeandalucia.es/agriculturaypesca/sigpac/>).
2. Municipios Rociana del Condado y Almonte (Huelva, provincia 21).
3. Exportar los recintos del AOI.
4. Guardarlos como `data/raw/capas/parcelas.gpkg` con una columna `id_parcela`.
   Sin ese nombre el score inventa un id por fila y el NDVI no casa.

### SAR del Plan Especial (no hay WFS)

La superficie agraria regable autorizada sale del Plan Especial de ordenación
de las zonas de regadío al norte de la corona forestal de Doñana (Junta de
Andalucía, 2014) y de sus revisiones. A menudo circula como plano, no como
capa.

1. Conseguir el plano o la capa de la Junta / la CHG.
2. Si solo hay PDF, georreferenciarlo en QGIS sobre el PNOA y digitalizar el
   contorno.
3. `data/raw/capas/sar.gpkg`, un polígono, con CRS.

Sin este fichero el término legal del score vale 0. No se da por "fuera de
SAR" lo que simplemente no se ha cargado.

### Pozos cerrados y mapas WWF

La cifra de cierres (del orden de 847 desde 2024, más precintos) está en notas
y boletines de la CHG, no en un shapefile único.

1. Reunir resoluciones o el listado que facilite la CHG.
2. Georreferenciar cada pozo.
3. `data/raw/capas/pozos_cerrados.gpkg` con `id_pozo` y, si se sabe, `fecha_cierre`.

Los mapas de regadío fuera de ordenación de WWF, si se consiguen en vectorial,
van a `data/raw/capas/puntos_wwf.gpkg`. Entran en la validación como
"documentado". No entran en el score: si entraran, la comprobación sería
circular.

El script escribe estas instrucciones también en
`data/raw/capas/LEEME_CAPAS.txt` cada vez que corre en modo real.

## Modo sintético, para no confundirlo con esto

`src/sintetico.py` escribe los mismos nombres de fichero
(`parcelas.gpkg`, `pozos_registrados.gpkg`, `sar.gpkg`, …) con
`sintetico=True` y un manifiesto. No son la CHG, ni el SIGPAC, ni el SIA.
Si se pasa a modo real, conviene vaciar `data/raw/capas/` antes: un GeoPackage
sintético que se haya quedado ahí se leería como si fuera de verdad.
