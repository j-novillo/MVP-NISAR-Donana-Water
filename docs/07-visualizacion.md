# Visualización

## Visor (`src/visor.py`)

```bash
streamlit run src/visor.py
```

Hace falta haber corrido la tubería: lee `resultados.parquet`,
`parcelas_score.parquet`, la serie de 100 m y, si existe, `validacion.json`.
Si falta algo, la página lo dice y se para.

Tres pestañas:

1. **Deformación.** Mapa Folium centrado en Rociana. Debajo, el raster de
   amplitud estacional (mm). Encima, las parcelas coloreadas por score, con
   tooltip. Pozos registrados en verde. Celdas con z > 2 cuyo centro está a
   más de 500 m de cualquier pozo registrado, en rojo. Los pozos cerrados van
   en una capa apagada por defecto, en negro, y el nombre de la capa dice que
   no entran en el score.
2. **NDVI de campaña.** Las mismas parcelas, coloreadas por el NDVI de
   octubre-mayo.
3. **Ranking.** La tabla ordenada por score. El interruptor de la barra
   lateral deja solo las parcelas que tocan el buffer de una anomalía.

Al elegir una parcela (lista, o clic: se toma la parcela más cercana al punto)
se dibuja su serie LOS media, el ajuste `c + v t + A sin + B cos`, y una banda
amarilla en cada campaña de fresa (1 de octubre a 30 de junio). Positivo es
hacia el satélite. En el sintético se ve el pico de hundimiento dentro de la
banda y el rebote fuera, frente a una parcela de la SAR que apenas se mueve.

La barra lateral resume el go/no-go. En modo sintético repite la advertencia
de que aquello no valida el acuífero.

## GeoTIFF

Quien prefiera no abrir el visor: `data/geotiff/zscore.tif` en QGIS, CRS
EPSG:25829, nodata −9999, encima del PNOA. Misma rejilla para amplitud,
velocidad, hundimiento y coherencia. Quince minutos y se ve si hay conos, que
es lo que pedía la spec como primer contacto.

## Figuras de control

`src/figuras.py`, llamado al validar, escribe en `data/figuras/` (no se
versiona):

- `zscore.png`, `amplitud_estacional.png`
- `serie_parcela.png` (la de mayor score y una dentro de la SAR)
- `go_nogo.png`

Las copias que ilustran el README están en `docs/figuras/` y salen de la
corrida sintética con semilla 2026. Si se cambia la semilla o la amplitud del
cono, esas figuras dejan de corresponder al JSON y hay que regenerarlas.
