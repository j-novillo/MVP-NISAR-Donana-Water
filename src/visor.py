"""Visor Streamlit + Folium de la PoC.

Dos mapas (amplitud estacional y NDVI de campaña), los pozos registrados en
verde, las anomalías sin registro en rojo, y al elegir una parcela la serie
de deformación con la campaña de fresa sombreada. La tabla ordena por score.

Los pozos cerrados se pueden superponer como capa de validación. No entran
en el score: si se usaran para puntuar, la comprobación sería circular.

Arranque, desde la raíz del repositorio:

    streamlit run src/visor.py
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image

from medir import ajuste_estacional
from utilidades import RAIZ, cargar_config, parsear_fecha, ruta_proyecto

# Folium no lee un array: se vuelca a PNG con la misma rampa que la leyenda.
CMAP_AMPLITUD = "YlOrRd"
CMAP_NDVI = "RdYlGn"


def _png_raster(plano: np.ndarray, ruta: Path, cmap: str, vmin: float, vmax: float) -> Path:
    """PNG RGBA. El nodato queda transparente para que se vea el mapa de fondo."""
    norma = plt.Normalize(vmin=vmin, vmax=vmax)
    colores = matplotlib.colormaps[cmap](norma(np.ma.masked_invalid(plano)))
    colores[..., 3] = np.where(np.isfinite(plano), 0.85, 0.0)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((colores * 255).astype(np.uint8), mode="RGBA").save(ruta)
    return ruta


def _limites_latlon(rejilla: dict) -> list[list[float]]:
    """[[sur, oeste], [norte, este]] para ImageOverlay, a partir de la affine métrica."""
    from rasterio.transform import Affine

    from utilidades import a_geografico

    transform = Affine(*rejilla["transform"])
    crs = rejilla["crs"]
    filas, cols = rejilla["filas"], rejilla["columnas"]
    esquinas = []
    for col, fila in ((0, 0), (cols, 0), (0, filas), (cols, filas)):
        x, y = transform * (col, fila)
        esquinas.append(a_geografico(x, y, crs))
    lons = [p[0] for p in esquinas]
    lats = [p[1] for p in esquinas]
    return [[min(lats), min(lons)], [max(lats), max(lons)]]


def _plano_columna(celdas: gpd.GeoDataFrame, columna: str, rejilla: dict) -> np.ndarray:
    plano = np.full((rejilla["filas"], rejilla["columnas"]), np.nan)
    plano[celdas["fila"].to_numpy(), celdas["columna"].to_numpy()] = celdas[columna].to_numpy()
    return plano


def cargar_capas(cfg: dict) -> dict:
    """Lee los productos del pipeline. Lanza FileNotFoundError si falta el paso previo."""
    resultados = ruta_proyecto(cfg, "resultados")
    parcelas_ruta = ruta_proyecto(cfg, "parcelas_score")
    if not resultados.is_file() or not parcelas_ruta.is_file():
        raise FileNotFoundError(
            "No están data/resultados.parquet y data/parcelas_score.parquet. "
            "Ejecute primero el pipeline (bash ejecutar_sintetico.sh, o los pasos del README)."
        )
    celdas = gpd.read_parquet(resultados)
    parcelas = gpd.read_parquet(parcelas_ruta)
    rejilla = json.loads((ruta_proyecto(cfg, "procesado") / "rejilla.json").read_text(encoding="utf-8"))
    validacion = {}
    ruta_val = ruta_proyecto(cfg, "validacion")
    if ruta_val.is_file():
        validacion = json.loads(ruta_val.read_text(encoding="utf-8"))
    capas = ruta_proyecto(cfg, "capas")

    def leer(nombre):
        ruta = capas / nombre
        if not ruta.is_file():
            return None
        return gpd.read_file(ruta).to_crs("EPSG:4326")

    return {
        "celdas": celdas.to_crs("EPSG:4326"),
        "celdas_nativas": celdas,
        "parcelas": parcelas.to_crs("EPSG:4326"),
        "rejilla": rejilla,
        "validacion": validacion,
        "pozos": leer("pozos_registrados.gpkg"),
        "cerrados": leer("pozos_cerrados.gpkg"),
        "cfg": cfg,
    }


def mapa_deformacion(datos: dict, directorio_png: Path | None = None) -> folium.Map:
    """Mapa 1: amplitud estacional, parcelas y pozos."""
    cfg = datos["cfg"]
    aoi_lat = float(cfg["referencia"]["lat"])
    aoi_lon = float(cfg["referencia"]["lon"])
    mapa = folium.Map(location=[aoi_lat, aoi_lon], zoom_start=14, tiles="OpenStreetMap")
    rejilla = datos["rejilla"]
    celdas = datos["celdas_nativas"]
    plano = _plano_columna(celdas, "amplitud_estacional_mm", rejilla)
    vmin = float(np.nanpercentile(plano, 5))
    vmax = float(np.nanpercentile(plano, 98))
    png = _png_raster(
        plano,
        (directorio_png or ruta_proyecto(cfg, "figuras")) / "overlay_amplitud.png",
        CMAP_AMPLITUD,
        vmin,
        vmax,
    )
    folium.raster_layers.ImageOverlay(
        image=str(png),
        bounds=_limites_latlon(rejilla),
        opacity=0.85,
        name="Amplitud estacional (mm)",
    ).add_to(mapa)
    _anadir_leyenda(mapa, vmin, vmax, "Amplitud estacional (mm)", CMAP_AMPLITUD)
    _anadir_parcelas(mapa, datos["parcelas"], "score")
    _anadir_pozos(mapa, datos, umbral_z=float(cfg["medicion"]["z_anomalia"]))
    folium.LayerControl().add_to(mapa)
    return mapa


def mapa_ndvi(datos: dict) -> folium.Map:
    """Mapa 2: NDVI de campaña por parcela."""
    cfg = datos["cfg"]
    mapa = folium.Map(
        location=[float(cfg["referencia"]["lat"]), float(cfg["referencia"]["lon"])],
        zoom_start=14,
        tiles="OpenStreetMap",
    )
    parcelas = datos["parcelas"]
    if "ndvi_campana" not in parcelas.columns or parcelas["ndvi_campana"].isna().all():
        return mapa
    vmin, vmax = 0.1, 0.8

    def estilo(feature):
        valor = feature["properties"].get("ndvi_campana")
        color = "#cccccc" if valor is None else _color_ndvi(float(valor), vmin, vmax)
        return {"fillColor": color, "color": "#333333", "weight": 0.6, "fillOpacity": 0.75}

    folium.GeoJson(
        _geojson_parcelas(parcelas),
        name="NDVI de campaña",
        style_function=estilo,
        tooltip=folium.GeoJsonTooltip(fields=["id_parcela", "ndvi_campana", "cultivo_activo"]),
    ).add_to(mapa)
    _anadir_pozos(mapa, datos, umbral_z=float(cfg["medicion"]["z_anomalia"]))
    folium.LayerControl().add_to(mapa)
    return mapa


def _color_ndvi(valor: float, vmin: float, vmax: float) -> str:
    t = min(1.0, max(0.0, (valor - vmin) / (vmax - vmin)))
    r, g, b, _ = matplotlib.colormaps[CMAP_NDVI](t)
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _geojson_parcelas(parcelas: gpd.GeoDataFrame) -> dict:
    columnas = [
        c
        for c in (
            "id_parcela",
            "score",
            "ndvi_campana",
            "cultivo_activo",
            "fuera_sar",
            "sin_pozo_declarado",
            "amplitud_estacional_mm",
            "velocidad_mm_anio",
            "ranking",
            "zona",
        )
        if c in parcelas.columns
    ]
    return json.loads(parcelas[columnas + ["geometry"]].to_json())


def _anadir_parcelas(mapa: folium.Map, parcelas: gpd.GeoDataFrame, campo_color: str) -> None:
    def estilo(feature):
        score = feature["properties"].get(campo_color) or 0
        t = min(1.0, max(0.0, float(score) / 100.0))
        rojo = int(255 * t)
        return {"fillColor": f"#{rojo:02x}{int(80*(1-t)):02x}40", "color": "#222222", "weight": 0.7, "fillOpacity": 0.35}

    campos = [c for c in ("id_parcela", "score", "ndvi_campana", "fuera_sar", "sin_pozo_declarado", "ranking") if c in parcelas.columns]
    folium.GeoJson(
        _geojson_parcelas(parcelas),
        name="Parcelas",
        style_function=estilo,
        tooltip=folium.GeoJsonTooltip(fields=campos),
    ).add_to(mapa)


def _anadir_pozos(mapa: folium.Map, datos: dict, umbral_z: float) -> None:
    pozos = datos.get("pozos")
    if pozos is not None and len(pozos):
        grupo = folium.FeatureGroup(name="Pozos registrados")
        for _, fila in pozos.iterrows():
            folium.CircleMarker(
                location=[fila.geometry.y, fila.geometry.x],
                radius=5,
                color="#006d2c",
                fill=True,
                fill_opacity=0.9,
                tooltip=f"Registrado {fila.get('id_pozo', '')}",
            ).add_to(grupo)
        grupo.add_to(mapa)
    celdas_m = datos["celdas_nativas"]
    if "zscore" in celdas_m.columns and pozos is not None and len(pozos) and celdas_m.crs is not None:
        from shapely.ops import unary_union

        from utilidades import a_geografico

        pozos_m = pozos.to_crs(celdas_m.crs)
        zona_legal = unary_union(list(pozos_m.geometry)).buffer(500)
        anom = celdas_m[celdas_m["zscore"] > umbral_z]
        grupo_rojo = folium.FeatureGroup(name="Anomalía sin pozo registrado")
        for _, fila in anom.iterrows():
            punto = fila.geometry.centroid
            if zona_legal.contains(punto):
                continue
            lon, lat = a_geografico(punto.x, punto.y, str(celdas_m.crs))
            folium.CircleMarker(
                location=[lat, lon],
                radius=3,
                color="#a50f15",
                fill=True,
                fill_opacity=0.8,
                tooltip=f"z={fila['zscore']:.1f}",
            ).add_to(grupo_rojo)
        grupo_rojo.add_to(mapa)
    cerrados = datos.get("cerrados")
    if cerrados is not None and len(cerrados):
        grupo_c = folium.FeatureGroup(name="Pozos cerrados (validación, no entra en el score)", show=False)
        for _, fila in cerrados.iterrows():
            folium.CircleMarker(
                location=[fila.geometry.y, fila.geometry.x],
                radius=6,
                color="#000000",
                fill=False,
                tooltip=f"Cerrado {fila.get('id_pozo', '')}",
            ).add_to(grupo_c)
        grupo_c.add_to(mapa)


def _anadir_leyenda(mapa, vmin, vmax, titulo, cmap) -> None:
    import branca.colormap as bcm

    mapa_color = bcm.linear.YlOrRd_09.scale(vmin, vmax)
    mapa_color.caption = titulo
    mapa_color.add_to(mapa)


def grafico_serie(datos: dict, id_parcela: str):
    """Serie LOS de la parcela, ajuste estacional y campaña de fresa sombreada."""
    cfg = datos["cfg"]
    npz = np.load(ruta_proyecto(cfg, "procesado") / "serie_malla100.npz")
    fechas = [parsear_fecha(f) for f in npz["fechas"]]
    serie = npz["serie_mm"]
    parcelas = datos["parcelas"]
    fila = parcelas.loc[parcelas["id_parcela"] == id_parcela]
    if fila.empty:
        return None
    geom = fila.iloc[0].geometry
    celdas = datos["celdas"]
    dentro = celdas[celdas.geometry.intersects(geom)]
    if dentro.empty:
        return None
    curvas = serie[:, dentro["fila"].to_numpy(), dentro["columna"].to_numpy()]
    with np.errstate(all="ignore"):
        media = np.nanmean(curvas, axis=1)
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    ax.plot(fechas, media, color="#b2182b", lw=1.8, label="Desplazamiento medio de la parcela")
    v, a, _, coef = ajuste_estacional(fechas, media.reshape(-1, 1), min_fechas=6)
    if np.isfinite(coef).all():
        t = np.array([(f - fechas[0]).days / 365.25 for f in fechas])
        ajuste = (
            coef[0, 0]
            + coef[1, 0] * t
            + coef[2, 0] * np.sin(2 * np.pi * t)
            + coef[3, 0] * np.cos(2 * np.pi * t)
        )
        ax.plot(fechas, ajuste, color="#b2182b", ls="--", lw=1.0, label=f"Ajuste (A={a.ravel()[0]:.1f} mm, v={v.ravel()[0]:.1f} mm/año)")
    for anio in range(fechas[0].year - 1, fechas[-1].year + 1):
        ax.axvspan(date(anio, 10, 1), date(anio + 1, 6, 30), color="#fee08b", alpha=0.35, lw=0)
    ax.axhline(0, color="0.5", lw=0.6)
    ax.set_ylabel("LOS (mm), positivo hacia el satélite")
    ax.set_title(f"{id_parcela}: la banda amarilla es la campaña de fresa (oct-jun)")
    ax.legend(fontsize=8, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    return fig


def parcela_mas_cercana(parcelas: gpd.GeoDataFrame, lat: float, lon: float) -> str | None:
    """Identificador de la parcela más cercana a un clic, en grados."""
    if parcelas.empty:
        return None
    puntos = parcelas.geometry.representative_point()
    dist = (puntos.y - lat) ** 2 + (puntos.x - lon) ** 2
    return str(parcelas.iloc[int(np.argmin(dist.to_numpy()))]["id_parcela"])


def main() -> None:
    import streamlit as st

    st.set_page_config(page_title="PoC Doñana — InSAR", layout="wide")
    st.title("Doñana: subsidencia estacional y pozos")
    st.caption(
        "Prueba de concepto. En modo sintético los pozos y la SAR son ficticios: "
        "un go aquí no valida el acuífero."
    )
    cfg = cargar_config()
    try:
        datos = cargar_capas(cfg)
    except FileNotFoundError as exc:
        st.error(str(exc))
        st.stop()

    validacion = datos["validacion"]
    if validacion:
        decision = validacion.get("decision_tuberia", "?")
        st.sidebar.header(f"Go / no-go: {decision}")
        st.sidebar.write(validacion.get("advertencia", ""))
        for criterio in validacion.get("criterios", []):
            st.sidebar.write(f"**{criterio['titulo']}:** {criterio['resultado']}")
    else:
        st.sidebar.info("Aún no hay data/validacion.json. Ejecute python src/score.py")

    parcelas = datos["parcelas"].sort_values("score", ascending=False)
    st.sidebar.header("Parcela")
    solo_buffer = st.sidebar.checkbox("Solo parcelas en el buffer de una anomalía", value=True)
    tabla = parcelas
    if solo_buffer and "en_buffer_anomalia" in tabla.columns:
        filtrada = tabla[tabla["en_buffer_anomalia"] == True]
        if len(filtrada):
            tabla = filtrada
    opciones = tabla["id_parcela"].astype(str).tolist()
    elegida = st.sidebar.selectbox("Parcela", opciones) if opciones else None

    pestaña_def, pestaña_ndvi, pestaña_tabla = st.tabs(["Deformación", "NDVI de campaña", "Ranking"])
    with pestaña_def:
        from streamlit_folium import st_folium

        salida = st_folium(mapa_deformacion(datos), height=560, returned_objects=["last_clicked"])
        if salida and salida.get("last_clicked"):
            clic = salida["last_clicked"]
            cercana = parcela_mas_cercana(datos["parcelas"], clic["lat"], clic["lng"])
            if cercana:
                elegida = cercana
                st.info(f"Clic junto a la parcela {cercana}")
        if elegida:
            figura = grafico_serie(datos, elegida)
            if figura is not None:
                st.pyplot(figura)
                plt.close(figura)
            fila = parcelas.loc[parcelas["id_parcela"] == elegida]
            if len(fila):
                st.write(
                    fila[
                        [
                            c
                            for c in (
                                "id_parcela",
                                "score",
                                "ranking",
                                "amplitud_estacional_mm",
                                "velocidad_mm_anio",
                                "ndvi_campana",
                                "sin_pozo_declarado",
                                "fuera_sar",
                                "cultivo_activo",
                                "en_buffer_anomalia",
                            )
                            if c in fila.columns
                        ]
                    ]
                )
    with pestaña_ndvi:
        from streamlit_folium import st_folium

        st_folium(mapa_ndvi(datos), height=560)
    with pestaña_tabla:
        columnas = [
            c
            for c in (
                "ranking",
                "id_parcela",
                "score",
                "p_amplitud",
                "p_velocidad",
                "p_ndvi",
                "p_legal",
                "amplitud_estacional_mm",
                "velocidad_subsidencia_mm_anio",
                "ndvi_campana",
                "sin_pozo_declarado",
                "fuera_sar",
                "cultivo_activo",
                "en_buffer_anomalia",
                "zscore_max",
            )
            if c in tabla.columns
        ]
        st.dataframe(tabla[columnas], hide_index=True, height=560)


if __name__ == "__main__":
    main()
