"""Prepara jobs HyP3 INSAR_GAMMA oficiales. No los envía.

`hyp3_sdk.HyP3(token=EARTHDATA_TOKEN)` autentica con el token Earthdata
que ya existe. No hace falta EARTHDATA_USERNAME ni EARTHDATA_PASSWORD.

Este archivo no llama a HyP3 al importarse. `--enviar` hace el POST y no
debe usarse desde el agente cloud: hay jobs ya en curso en el box.

El cuerpo sigue la API pública:
https://hyp3-docs.asf.alaska.edu/using/api/
POST https://hyp3-api.asf.alaska.edu/jobs
job_type INSAR_GAMMA, job_parameters.granules = [referencia, secundaria].

Por defecto escribe el JSON. Enviarlo exige `--enviar` y EARTHDATA_TOKEN.
Este módulo, importado, no llama a la red. Un agente en la nube no debe
usar `--enviar`: el job se lanza en el box, con el secreto ya autorizado.

    python src/preparar_hyp3.py --referencias pares.csv --salida data/hyp3/jobs.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from utilidades import RAIZ, guardar_json

API_OFICIAL = "https://hyp3-api.asf.alaska.edu/jobs"


def preparar_insar_gamma(
    referencia: str,
    secundaria: str,
    nombre: str | None = None,
) -> dict:
    """Un job, sin enviarlo. Pide mapas de desplazamiento, incidencia y look vectors."""
    parametros = {
        "granules": [referencia, secundaria],
        "include_displacement_maps": True,
        "include_inc_map": True,
        "include_look_vectors": True,
        "looks": "20x4",
    }
    job = {"job_type": "INSAR_GAMMA", "job_parameters": parametros}
    if nombre:
        job["name"] = nombre
    return job


def cuerpo_jobs(jobs: list[dict]) -> dict:
    return {"jobs": jobs}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--referencia", default=None, help="ID de gránulo SLC de referencia")
    parser.add_argument("--secundaria", default=None, help="ID de gránulo SLC secundario")
    parser.add_argument(
        "--pares",
        default=None,
        help="CSV con columnas referencia,secundaria. Sustituye a los dos IDs sueltos.",
    )
    parser.add_argument("--nombre", default="donana-solape-nisar")
    parser.add_argument("--salida", default="data/hyp3/jobs.json")
    parser.add_argument(
        "--enviar",
        action="store_true",
        help="POST a la API oficial. Requiere EARTHDATA_TOKEN. No usar en el agente cloud.",
    )
    args = parser.parse_args(argv)
    jobs = []
    if args.pares:
        import pandas as pd

        tabla = pd.read_csv(args.pares)
        for i, fila in tabla.iterrows():
            jobs.append(
                preparar_insar_gamma(
                    str(fila["referencia"]),
                    str(fila["secundaria"]),
                    f"{args.nombre}-{i}",
                )
            )
    elif args.referencia and args.secundaria:
        jobs.append(preparar_insar_gamma(args.referencia, args.secundaria, args.nombre))
    else:
        raise SystemExit("Hace falta --referencia y --secundaria, o --pares.")
    cuerpo = cuerpo_jobs(jobs)
    destino = RAIZ / args.salida
    guardar_json(destino, {"api": API_OFICIAL, "enviado": False, "cuerpo": cuerpo})
    if not args.enviar:
        print(json.dumps({"enviado": False, "n": len(jobs), "salida": str(destino)}))
        return
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        raise SystemExit("EARTHDATA_TOKEN vacío: no se envía el job.")
    import requests

    respuesta = requests.post(
        API_OFICIAL,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=cuerpo,
        timeout=120,
    )
    respuesta.raise_for_status()
    destino.write_text(
        json.dumps({"api": API_OFICIAL, "enviado": True, "respuesta": respuesta.json()}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"enviado": True, "n": len(jobs)}))


if __name__ == "__main__":
    main()
