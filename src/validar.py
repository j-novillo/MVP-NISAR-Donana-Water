"""Criterios go / no-go de la spec, más un apoyo con piezómetros.

Los cuatro criterios de la tabla son los que deciden. El contraste con los
niveles freáticos del SIA se informa aparte: la spec lo pide como comprobación
hidrológica, no como umbral.

En modo sintético un "go" solo demuestra que la tubería recupera la señal que
ella misma inyectó. No dice nada todavía sobre el acuífero de Doñana.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from utilidades import cargar_config, guardar_json, ruta_proyecto

log = logging.getLogger("poc.validar")


def _capa(ruta: Path, crs: str) -> gpd.GeoDataFrame | None:
    if not ruta.is_file():
        return None
    capa = gpd.read_file(ruta)
    if capa.crs is None:
        capa = capa.set_crs("EPSG:4326")
    if capa.empty:
        return capa
    return capa.to_crs(crs)


def _criterio(identificador: str, titulo: str, valor, resultado: str, detalle: str, umbral_go, umbral_nogo) -> dict:
    return {
        "id": identificador,
        "titulo": titulo,
        "valor": None if valor is None or (isinstance(valor, float) and not np.isfinite(valor)) else valor,
        "resultado": resultado,
        "detalle": detalle,
        "umbral_go": umbral_go,
        "umbral_nogo": umbral_nogo,
    }


def _tres_bandas(valor: float, go: float, nogo: float, mayor_es_go: bool) -> str:
    """Clasifica un número. Si mayor_es_go, por encima de `go` es go y por debajo de `nogo` es no-go."""
    if valor is None or not np.isfinite(valor):
        return "indeterminado"
    if mayor_es_go:
        if valor >= go:
            return "go"
        if valor < nogo:
            return "no-go"
        return "indeterminado"
    if valor <= go:
        return "go"
    if valor > nogo:
        return "no-go"
    return "indeterminado"


def _recall_pozos(pozos: gpd.GeoDataFrame, celdas: gpd.GeoDataFrame, umbral_z: float) -> tuple[float, int, int]:
    if pozos is None or pozos.empty:
        return float("nan"), 0, 0
    cruce = gpd.sjoin_nearest(
        pozos,
        celdas[["zscore", "coherencia_media", "geometry"]],
        how="left",
        distance_col="distancia_m",
    )
    cruce = cruce[~cruce.index.duplicated(keep="first")]
    # Una celda de 100 m: si el punto cae a más de 150 m del centroide más cercano, no cuenta como "cae en la celda".
    dentro = cruce["distancia_m"] <= 150
    detectado = dentro & (cruce["zscore"] > umbral_z)
    n = int(len(pozos))
    n_ok = int(detectado.fillna(False).sum())
    return (n_ok / n if n else float("nan")), n_ok, n


def _fraccion_agrupada(celdas_anom: gpd.GeoDataFrame, distancia_m: float) -> float:
    """Fracción de anomalías que tienen otra anomalía a menos de `distancia_m`."""
    if len(celdas_anom) < 2:
        return 0.0
    puntos = celdas_anom.geometry.centroid
    coords = np.column_stack([puntos.x, puntos.y])
    # Para no construir una matriz gigante se usa una rejilla gruesa.
    lado = distancia_m
    claves = np.floor(coords / lado).astype(int)
    cubo: dict[tuple[int, int], list[int]] = {}
    for i, clave in enumerate(map(tuple, claves)):
        cubo.setdefault(clave, []).append(i)
    con_vecino = 0
    for i, (x, y) in enumerate(coords):
        cx, cy = claves[i]
        encontrado = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in cubo.get((cx + dx, cy + dy), []):
                    if j == i:
                        continue
                    if (coords[j, 0] - x) ** 2 + (coords[j, 1] - y) ** 2 <= distancia_m**2:
                        encontrado = True
                        break
                if encontrado:
                    break
            if encontrado:
                break
        if encontrado:
            con_vecino += 1
    return con_vecino / len(coords)


def _distancia_minima(origen: gpd.GeoDataFrame, destino: gpd.GeoDataFrame) -> np.ndarray:
    if destino is None or destino.empty or origen.empty:
        return np.full(len(origen), np.inf)
    cruce = gpd.sjoin_nearest(origen, destino[["geometry"]], how="left", distance_col="distancia_m")
    # sjoin_nearest puede duplicar si hay empates. Nos quedamos con la menor distancia por índice de origen.
    return cruce.groupby(cruce.index)["distancia_m"].min().reindex(origen.index).to_numpy()


def evaluar(cfg: dict) -> dict:
    """Calcula los criterios y escribe `data/validacion.json`."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from figuras import guardar_figuras

    crs = cfg["crs_metrico"]
    val = cfg["validacion"]
    umbral_z = float(cfg["medicion"]["z_anomalia"])
    umbral_coh = float(cfg["procesado"]["coherencia_min"])
    capas = ruta_proyecto(cfg, "capas")
    procesado = ruta_proyecto(cfg, "procesado")

    celdas = gpd.read_parquet(ruta_proyecto(cfg, "resultados")).to_crs(crs)
    parcelas = None
    ruta_parcelas = ruta_proyecto(cfg, "parcelas_score")
    if ruta_parcelas.is_file():
        parcelas = gpd.read_parquet(ruta_parcelas).to_crs(crs)

    rejilla = {}
    ruta_rejilla = procesado / "rejilla.json"
    if ruta_rejilla.is_file():
        rejilla = json.loads(ruta_rejilla.read_text(encoding="utf-8"))
    fraccion_coh = float(rejilla.get("fraccion_coherencia_campana_nativa", np.nan))
    res_coh = _tres_bandas(
        fraccion_coh,
        float(val["coherencia_fraccion_go"]),
        float(val["coherencia_fraccion_nogo"]),
        mayor_es_go=True,
    )
    criterios = [
        _criterio(
            "coherencia",
            "Coherencia InSAR en campaña de riego",
            fraccion_coh,
            res_coh,
            (
                f"{fraccion_coh:.1%} de los píxeles nativos tienen coherencia media "
                f"> {umbral_coh} en los interferogramas de abril-junio. "
                "Go por encima del 30 %. No-go si la cobertura coherente en cultivo se queda por debajo del 5 %."
            ),
            val["coherencia_fraccion_go"],
            val["coherencia_fraccion_nogo"],
        )
    ]

    exceso = celdas["exceso_mm"].to_numpy()
    coh = celdas["coherencia_media"].to_numpy()
    mascara = np.isfinite(exceso) & np.isfinite(coh) & (coh >= umbral_coh)
    p90_global = float(np.nanpercentile(exceso[mascara], 90)) if mascara.any() else float("nan")
    anomalias = celdas[(celdas["zscore"] > umbral_z) & (celdas["coherencia_media"] >= umbral_coh)].copy()
    agrupacion = _fraccion_agrupada(anomalias, 250.0)
    # El percentil 90 de TODO el AOI diluye un cono que ocupa poca superficie.
    # El gradiente local es el exceso típico (mediana) dentro de las celdas
    # que ya se salen del anillo (z > 2): cuántos milímetros mide el cono.
    if len(anomalias) >= 5 and np.isfinite(anomalias["exceso_mm"]).any():
        magnitud = float(np.nanmedian(anomalias["exceso_mm"]))
    else:
        magnitud = p90_global
    if not np.isfinite(magnitud):
        res_senal = "indeterminado"
    elif magnitud >= float(val["gradiente_mm_go"]) and agrupacion >= float(val["fraccion_vecinos_go"]):
        res_senal = "go"
    elif magnitud < float(val["gradiente_mm_nogo"]) or (
        len(anomalias) > 0 and agrupacion < 0.2 and magnitud < float(val["gradiente_mm_go"])
    ):
        res_senal = "no-go"
    else:
        res_senal = "indeterminado"
    criterios.append(
        _criterio(
            "senal",
            "Señal de subsidencia local",
            {
                "mediana_exceso_en_anomalias_mm": magnitud,
                "p90_exceso_aoi_mm": p90_global,
                "fraccion_anomalias_agrupadas": agrupacion,
                "n_celdas_z": int(len(anomalias)),
            },
            res_senal,
            (
                f"La mediana del exceso de hundimiento (celda menos anillo de 1-2 km) "
                f"dentro de las celdas con z > {umbral_z} es {magnitud:.2f} mm. "
                f"El percentil 90 de todo el AOI es {p90_global:.2f} mm y no se usa como umbral: "
                "un cono local no mueve ese percentil. "
                f"El {agrupacion:.0%} de las anomalías tiene otra a menos de 250 m. "
                "Go si el cono mide al menos 5 mm y las anomalías se agrupan; "
                "no-go si se queda por debajo de 2 mm o el z-score no tiene estructura."
            ),
            val["gradiente_mm_go"],
            val["gradiente_mm_nogo"],
        )
    )

    registrados = _capa(capas / "pozos_registrados.gpkg", crs)
    sar = _capa(capas / "sar.gpkg", crs)
    wwf = _capa(capas / "puntos_wwf.gpkg", crs)
    cerrados = _capa(capas / "pozos_cerrados.gpkg", crs)
    documentados = None
    trozos = [c for c in (wwf, cerrados) if c is not None and not c.empty]
    if trozos:
        documentados = pd.concat(trozos, ignore_index=True)
        documentados = gpd.GeoDataFrame(documentados, geometry="geometry", crs=crs)

    if anomalias.empty or registrados is None or sar is None:
        criterios.append(
            _criterio(
                "legal",
                "Discriminación legal",
                None,
                "indeterminado",
                "Falta la capa de pozos registrados, el polígono SAR, o no hay celdas con z > 2. "
                "Sin ese cruce no se puede decir si las anomalías caen solo sobre pozos legales.",
                "anomalías fuera de SAR y sin pozo, coincidiendo con WWF/CHG",
                "anomalías solo sobre pozos legales",
            )
        )
    else:
        from shapely.ops import unary_union

        sar_union = unary_union(list(sar.geometry))
        centros = anomalias.copy()
        centros["geometry"] = anomalias.geometry.centroid
        fuera = ~centros.within(sar_union)
        dist_reg = _distancia_minima(centros, registrados if registrados is not None else gpd.GeoDataFrame(geometry=[], crs=crs))
        dist_doc = _distancia_minima(centros, documentados)
        cerca_reg = dist_reg <= float(val["distancia_pozo_registrado_m"])
        sin_pozo = dist_reg > float(val["distancia_pozo_registrado_m"])
        inexplicadas = fuera.to_numpy() & sin_pozo
        if inexplicadas.any() and documentados is not None:
            solape = float(np.mean(dist_doc[inexplicadas] <= float(val["distancia_documentada_m"])))
        elif inexplicadas.any():
            solape = float("nan")
        else:
            solape = 0.0
        frac_sobre_legal = float(np.mean(cerca_reg))
        if (
            np.isfinite(solape)
            and solape >= 0.5
            and frac_sobre_legal < 0.5
        ):
            res_legal = "go"
        elif frac_sobre_legal >= 0.8 and (not np.isfinite(solape) or solape < 0.2):
            res_legal = "no-go"
        else:
            res_legal = "indeterminado"
        criterios.append(
            _criterio(
                "legal",
                "Discriminación legal",
                {
                    "fraccion_anomalias_cerca_de_pozo_registrado": frac_sobre_legal,
                    "fraccion_inexplicadas_cerca_de_documentadas": solape,
                    "n_anomalias_fuera_sar_sin_pozo": int(inexplicadas.sum()),
                },
                res_legal,
                (
                    f"El {frac_sobre_legal:.0%} de las celdas con z > {umbral_z} tiene un pozo "
                    f"registrado a menos de {val['distancia_pozo_registrado_m']:.0f} m. "
                    f"De las que están fuera de la SAR y sin pozo declarado, el {solape:.0%} "
                    "cae junto a un punto documentado (pozo cerrado de la CHG o mapa WWF). "
                    "Go si esas anomalías inexplicadas coinciden con la documentación y no se concentran en pozos legales."
                ),
                "solape documentado >= 50 % y < 50 % de anomalías junto a pozo legal",
                ">= 80 % de las anomalías junto a un pozo legal y solape documentado < 20 %",
            )
        )

    recall, n_ok, n_cerr = _recall_pozos(cerrados, celdas, umbral_z)
    if cerrados is None or n_cerr == 0:
        res_recall = "indeterminado"
        detalle_recall = (
            "No hay capa de pozos cerrados. En datos reales hay que georreferenciar "
            "los cierres de la CHG (847 citados desde 2024 no están en un shapefile único): "
            "ver docs/02-descarga-de-datos.md."
        )
    else:
        res_recall = _tres_bandas(recall, float(val["recall_go"]), float(val["recall_nogo"]), mayor_es_go=True)
        detalle_recall = (
            f"{n_ok} de {n_cerr} pozos cerrados caen en una celda con z > {umbral_z} "
            f"(recuerdo {recall:.1%}). Go por encima del 50 %, no-go por debajo del 20 %."
        )
    criterios.append(
        _criterio(
            "pozos_cerrados",
            "Validación con pozos cerrados",
            {"recall": recall, "detectados": n_ok, "total": n_cerr},
            res_recall,
            detalle_recall,
            val["recall_go"],
            val["recall_nogo"],
        )
    )

    apoyo = _apoyo_piezometros(capas, anomalias, crs)
    puerta = [c["resultado"] for c in criterios]
    if all(r == "go" for r in puerta):
        decision = "go"
    elif any(r == "no-go" for r in puerta):
        decision = "no-go"
    else:
        decision = "indeterminado"

    modo = cfg.get("modo", "real")
    informe = {
        "alcance": modo,
        "decision_tuberia": decision,
        "decision_cientifica_donana": (
            "pendiente_de_datos_reales"
            if modo == "sintetico"
            else decision
        ),
        "advertencia": (
            "Resultado sobre interferogramas sintéticos con conos inyectados. "
            "Sirve para ver que el código mide lo que dice medir. No es una validación del acuífero."
            if modo == "sintetico"
            else "Resultado sobre los productos presentes en data/raw. Revise el signo de la fase y la completitud del registro de pozos antes de interpretar un go."
        ),
        "criterios": criterios,
        "apoyo_piezometros": apoyo,
        "aoi": cfg["aoi"]["activa"],
    }
    destino = ruta_proyecto(cfg, "validacion")
    guardar_json(destino, informe)
    log.info("Decisión de la tubería: %s (%s)", decision, modo)
    for criterio in criterios:
        log.info("  - %s: %s", criterio["id"], criterio["resultado"])
    try:
        guardar_figuras(cfg, celdas, parcelas, informe)
    except Exception as exc:  # una figura rota no invalida el informe
        log.warning("No se pudieron guardar las figuras: %s", exc)
    return informe


def _apoyo_piezometros(capas: Path, anomalias: gpd.GeoDataFrame, crs: str) -> dict:
    puntos = _capa(capas / "piezometros.gpkg", crs)
    niveles_ruta = capas / "piezometros_niveles.csv"
    if puntos is None or puntos.empty or not niveles_ruta.is_file():
        return {
            "disponible": False,
            "detalle": "No hay piezómetros. En datos reales, descargar la red SIA (docs/02).",
        }
    niveles = pd.read_csv(niveles_ruta, parse_dates=["fecha"])
    if "profundidad_m" not in niveles.columns:
        return {"disponible": False, "detalle": "El CSV de niveles no tiene columna profundidad_m."}
    descensos = []
    for pid, grupo in niveles.groupby("id_piezometro"):
        grupo = grupo.sort_values("fecha")
        # Descenso de campaña: profundidad media de abril-junio menos la de octubre-noviembre.
        prim = grupo[grupo["fecha"].dt.month.isin([4, 5, 6])]["profundidad_m"].mean()
        oton = grupo[grupo["fecha"].dt.month.isin([10, 11])]["profundidad_m"].mean()
        if np.isfinite(prim) and np.isfinite(oton):
            descensos.append({"id_piezometro": pid, "descenso_m": float(prim - oton)})
    if not descensos:
        return {"disponible": False, "detalle": "Los niveles no cubren primavera y otoño."}
    tabla = pd.DataFrame(descensos)
    fusion = puntos.merge(tabla, on="id_piezometro", how="inner")
    if anomalias.empty:
        cerca = np.zeros(len(fusion), dtype=bool)
    else:
        from shapely.ops import unary_union

        zona = unary_union(list(anomalias.geometry)).buffer(1000)
        cerca = fusion.geometry.intersects(zona).to_numpy()
    cerca_media = float(fusion.loc[cerca, "descenso_m"].mean()) if cerca.any() else float("nan")
    lejos_media = float(fusion.loc[~cerca, "descenso_m"].mean()) if (~cerca).any() else float("nan")
    coherente = bool(np.isfinite(cerca_media) and np.isfinite(lejos_media) and cerca_media > lejos_media + 0.5)
    return {
        "disponible": True,
        "descenso_medio_cerca_anomalia_m": cerca_media,
        "descenso_medio_lejos_m": lejos_media,
        "coherente_con_anomalias": coherente,
        "detalle": (
            "Los piezómetros a menos de 1 km de una anomalía bajan más en primavera "
            "que los alejados."
            if coherente
            else "El descenso freático de primavera no es claramente mayor junto a las anomalías."
        ),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Criterios go/no-go de la PoC.")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    evaluar(cargar_config(args.config))


if __name__ == "__main__":
    main()
