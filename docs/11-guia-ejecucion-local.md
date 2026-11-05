# Guía de ejecución local (PC propio)

El cierre del estudio actual está en `docs/16-informe-viabilidad-final.md`.
El texto de las 21:14 (`docs/15-informe-viabilidad-provisional.md`) quedó
superado. Esta guía solo dice cómo descargar y arrancar. Los secretos van
en `.env` (ver `.env.example`); no se versionan. El producto Sentinel-1 del
20 de octubre al 1 de noviembre de 2026 es otra ventana: el cruce con los
GUNW NISAR de 2025 usa octubre–diciembre de 2025.

Cómo instalar el entorno, qué datos bajar, desde dónde, con qué cuentas, y
cómo lanzar la tubería completa más la comparación NISAR vs Sentinel-1.

Tiempos orientativos en un portátil con 16 GB RAM y buen disco: entorno 10–20
min; descarga HyP3 ya hecha en el repo de trabajo ~1–2 GB; cada GUNW NISAR
≈ 2.0–2.4 GB y tarda 20–60 min por fichero con el descargador por rangos;
procesado opción A de la tesela 5×5 km: minutos.

## 1. Cuentas que necesitas

| Servicio | Para qué | Dónde crearla |
|---|---|---|
| NASA Earthdata (URS) | Catálogo y descarga NISAR GUNW / ASF | https://urs.earthdata.nasa.gov/ |
| Token Earthdata | Bearer HTTP (ASF cloud) | Perfil URS → Generate Token |
| Copernicus Data Space (CDSE) | Sentinel-2 / Process API NDVI | https://dataspace.copernicus.eu/ |
| ASF HyP3 (mismo login Earthdata) | Interferogramas Sentinel-1 listos | https://hyp3-docs.asf.alaska.edu/ |
| CLMS (Copernicus Land) | EGMS archive API | https://land.copernicus.eu/ (opcional) |

**Nunca** subas tokens al repo ni los pegues en issues. Usa un `.env` local
(plantilla en `.env.example`).

```bash
# .env (ejemplo de nombres; pon TUS valores)
EARTHDATA_TOKEN=...
CDSE_USERNAME=tu_email@ejemplo.com
CDSE_PASSWORD=...
# HyP3 no necesita usuario ni contraseña:
#   from hyp3_sdk import HyP3
#   HyP3(token=os.environ["EARTHDATA_TOKEN"])
```

## 2. Clonar e instalar

```bash
git clone https://github.com/j-novillo/MVP-NISAR-Donana-Water.git
cd MVP-NISAR-Donana-Water
git checkout cursor/poc-donana-insar-8c15   # o main cuando se fusione el PR

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
# Opcional para pedir jobs HyP3 desde Python:
pip install hyp3_sdk scipy
```

Alternativa conda:

```bash
conda env create -f environment.yml
conda activate poc-donana
```

Comprueba:

```bash
pytest -q
```

## 3. Qué datos bajar, de dónde y a dónde

Raíz de datos: `data/raw/` (está en `.gitignore`).

### 3.1 NISAR GUNW (ASF / NASA)

- **Qué**: productos `NISAR_L2_PR_GUNW_*.h5` que corten la tesela Rociana.
- **Catálogo** (sin token):

```bash
python src/descarga_asf.py --listar
# escribe data/raw/catalogo_asf.csv y/o nisar_download_list.csv
```

- **Descarga robusta** (CloudFront corta streams largos → rangos de 1 MiB):

```bash
# Recorta el CSV a los gránulos que quieras (p. ej. 2–4 para la PoC)
# y deja scene_name,url en data/raw/nisar_subset.csv
export EARTHDATA_TOKEN=...   # o carga .env
python src/descarga_nisar_chunked.py --csv data/raw/nisar_subset.csv --destino data/raw/interferogramas
```

- **Destino**: `data/raw/interferogramas/*.h5`
- **Sidecar** (λ banda L): al lado de cada `.h5` un JSON con
  `plataforma: NISAR`, `frecuencia_hz: 1229000000` o `longitud_onda_m: 0.24393202441008952`,
  `look_direction: Left`, `orbita: Ascending`. No uses 0,238403 m: no es la λ de estos GUNW.
  El comparador
  también detecta NISAR por el nombre del fichero.

### 3.2 Sentinel-1 (HyP3 INSAR_GAMMA)

- **Qué**: zips `S1AA_*_INT80_*.zip` (fase desenvuelta + coherencia).
- **Dónde**: https://hyp3.asf.alaska.edu/ o `hyp3_sdk.HyP3(token=EARTHDATA_TOKEN)`.
  El token Earthdata que ya existe autentica. No hace falta usuario ni contraseña.
  No lances jobs desde el agente cloud: en el box ya hay seis en curso.
- **Destino de los zip**: `data/raw/hyp3_s1/`
- **Conversión a GeoTIFF de 2 bandas** (lo que lee el pipeline):

```bash
python src/convertir_hyp3.py
# escribe data/raw/interferogramas/S1_GUNW_YYYYMMDD_YYYYMMDD.tif + .json
```

Para comparar en el **mismo periodo que NISAR** (oct 2025 en adelante)
necesitas jobs HyP3 de esas fechas. ARIA S1 GUNW en este AOI devolvió **0**
productos (comprobado 2026-11-04). Sin esos ifg coetáneos, la exactitud
frente a GNSS/piezómetros **no se puede calcular**.

### 3.3 Sentinel-2 NDVI (CDSE Process API)

```bash
export CDSE_USERNAME=...
export CDSE_PASSWORD=...
python src/descarga_ndvi_process.py
```

Destino: `data/raw/ndvi/`.

### 3.4 Capas legales y piezómetros (geometrías)

```bash
python src/descarga_capas.py          # captaciones CHG + intento SIA
python src/descarga_referencias.py    # piezómetros MITECO+CHG, catálogo GNSS, LEEMEs
```

| Capa | Fuente | ¿Automático? | Destino |
|---|---|---|---|
| Captaciones CHG | WFS `ggiscloud_root:captaciones_dph` | Sí | `data/raw/capas/pozos_registrados.gpkg` / `captaciones_chg.gpkg` |
| Piezómetros MITECO | WFS `RedPiezometrica` | Sí (puntos) | `data/raw/capas/piezometros.gpkg` |
| Piezómetros CHG | WFS `ggiscloud_root:piezometros` | Sí (puntos) | `data/raw/capas/piezometros_chg.gpkg` |
| Series de nivel | Visor CHG water-networks | **No** (manual) | `data/raw/capas/piezometros_niveles.csv` |
| SIGPAC / SAR / pozos cerrados | Visores Junta / CHG | **No** | ver `data/raw/capas/LEEME_CAPAS.txt` |
| EGMS L2b/L3 | Archive API CLMS | **No** (login) | `data/raw/egms/` + `LEEME_EGMS.txt` |
| GNSS catálogo | NGL DataHoldings | Sí | `data/raw/gnss/estaciones_cercanas.csv` |
| GNSS series (tenv3) | NGL | **No** (404 en 2026-11) | RINEX RAP/IGN → procesar a ENU |

URLs útiles:

- CHG piezómetros WFS: `https://idechg.chguadalquivir.es/geoserver/ggiscloud_root/ows`
- MITECO RedPiezometrica WFS: `https://gis.miteco.gob.es/geoserver/agua/RedPiezometrica/wfs`
- Visor series CHG: `https://idechg.chguadalquivir.es/geochg/areas/water-networks`
- EGMS Explorer: `https://egms.land.copernicus.eu/`
- RAP RINEX: `https://www.juntadeandalucia.es/institutodeestadisticaycartografia/rap/descarga-rinex`
- IGN ERGNSS: `https://datos-geodesia.ign.es/ERGNSS/`
- NGL holdings: `https://geodesy.unr.edu/NGLStationPages/DataHoldings.txt`

Estaciones GNSS cercanas a Doñana (catálogo NGL): HUEL, HUE1, HULV, LEBR,
SEV1, SEVI, ETSI, ALGC/UCA*, etc. Ninguna está dentro de la tesela 5×5 km de
Rociana; la más útil como ancla regional es **HUEL/HULV** (Huelva).

### 3.5 EGMS (opcional, muy recomendable para la serie larga S1)

1. Cuenta CLMS + token API.
2. `POST https://egms.land.copernicus.eu/insar-api/archive` con JSON
   `{ "levels":["L3"], "releases":["2020_2024"], "bbox":[[-6.7,37.2],[-6.48,37.4]], "productType":["ORTHO-UP"] }`
3. Descargar con el `id` de consulta que devuelve la búsqueda.
4. Dejar los ZIP/CSV en `data/raw/egms/`.

## 4. Arrancar el pipeline

Config por defecto: `config.yaml` (`modo: real`, tesela Rociana 5×5 km).

```bash
source .venv/bin/activate
set -a; source .env; set +a

# 1) Datos (lo que falte)
python src/descarga_referencias.py
# python src/descarga_nisar_chunked.py   # si faltan .h5
# python src/convertir_hyp3.py          # si hay zips HyP3 nuevos

# 2) Apilar e invertir (opción A)
python src/procesar_insar.py

# 3) Medir, puntuar, validar, figuras
python src/medir.py
python src/score.py
python src/validar.py
python src/figuras.py

# 4) Comparación. Escribe en data/comparacion/ y no pisa la instantánea de docs/.
python src/comparar_nisar_s1.py

# Catálogo S1 de la ventana de los GUNW NISAR de 2025 (30 oct–17 dic).
# El producto S1DD del 20 oct al 1 nov de 2026 es otra ventana. El cruce
# con esos GUNW usa este intervalo.
python src/catalogo_s1_solape.py --inicio 2025-10-01 --fin 2025-12-31
# En el box, si se quiere el listado CMR (metadatos, no los SLC):
# python src/catalogo_s1_solape.py --inicio 2025-10-01 --fin 2025-12-31 --consultar

# Spec HyP3 oficial, sin enviar el job:
python src/preparar_hyp3.py --referencia ID_SLC_REF --secundaria ID_SLC_SEC
# El POST (--enviar) solo en el box, con EARTHDATA_TOKEN. No lanzarlo desde el agente cloud.

# EGMS: construye la consulta oficial o lee un CSV ya bajado. No descarga.
python src/leer_egms.py
# python src/leer_egms.py --csv data/raw/egms/producto.csv

# 5) Visor
streamlit run src/visor.py
```

Atajo sintético (sin red, para comprobar que el entorno funciona):

```bash
bash ejecutar_sintetico.sh
```

## 5. Qué porcentaje está permitido

Solo uno, y solo si el protocolo de `docs/14-protocolo-comparacion.md` se
cumple entero:

```
100 * (err_S1 - err_NISAR) / err_S1
```

con `err_S1 > 0`. Coherencia, fracción usable y dispersión urbana no usan
esa fórmula. Piezómetros y EGMS no son el error de exactitud. Si falta
solape de pares, CRS leído, signo anclado, incidencia, máscara común o un
n suficiente, el estado es `no_evaluable` y el porcentaje es null. No hay
un porcentaje único que resuma la comparación.

## 6. Disco y hardware

- Reserva ≥ 20 GB libres si vas a bajar 4 GUNW NISAR + HyP3 + NDVI.
- El descargador NISAR se puede reanudar: deja los `.part` y vuelve a lanzar
  el mismo script.
- No mezcles banda L y banda C en la misma inversión SBAS.

## 7. Si algo falla

| Síntoma | Qué mirar |
|---|---|
| `IncompleteRead` / descarga NISAR a medias | `src/descarga_nisar_chunked.py` (rangos 1 MiB) |
| HyP3 AuthenticationError | `HyP3(token=EARTHDATA_TOKEN)` usa el token Earthdata que ya tienes. No hace falta usuario ni contraseña |
| CDSE 401 | renueva con usuario/clave; el JWT suelto caduca en minutos |
| EGMS 401 | falta login CLMS |
| Comparador `no_evaluable` | falta solape de pares, CRS leído, signo anclado o GNSS en LOS. No se rellena con un % |
| CRS del GUNW | los dos productos observados declaran EPSG:32630. Se lee y se reproyecta. Que Rociana esté en el huso 29 no invalida ese CRS |

Más detalle de diseño: `docs/01`…`docs/10` y `docs/resultados-datos-reales.md`.
