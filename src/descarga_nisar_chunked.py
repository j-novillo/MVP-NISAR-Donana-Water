#!/usr/bin/env python3
"""Descarga reanudable de NISAR GUNW por rangos de 1 MiB.

No se ejecuta al importar. El token se lee dentro de main(), desde
EARTHDATA_TOKEN. Rutas por argumentos, no fijas a una máquina.

    python src/descarga_nisar_chunked.py --csv data/raw/nisar_subset.csv --destino data/raw/interferogramas

No lanzar esto en el agente cloud: cada GUNW pesa unos 2 GB.
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd
import requests

CHUNK = 1 * 1024 * 1024

def free_gb():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 1e9

def alinear_reanudacion(tamano_parcial: int, total: int | None = None) -> int:
    """El parcial se retoma en un múltiplo del chunk, sin pasar del tamaño anunciado."""
    if tamano_parcial < 0:
        return 0
    inicio = (tamano_parcial // CHUNK) * CHUNK
    if total is not None and inicio > total:
        return total
    return inicio


def resolve(url, session: requests.Session, token: str):
    r = session.get(url, headers={"Authorization": f"Bearer {token}"}, stream=True, timeout=60, allow_redirects=True)
    final = r.url
    r.close()
    rr = session.get(url, headers={"Authorization": f"Bearer {token}", "Range": "bytes=0-0"}, timeout=60, allow_redirects=True)
    cr = rr.headers.get("Content-Range", "")
    rr.close()
    total = int(cr.split("/")[-1])
    return final, total

def download(url, out: Path, session: requests.Session, token: str):
    tmp = out.with_suffix(".part")
    final, total = resolve(url, session, token)
    start = tmp.stat().st_size if tmp.exists() else 0
    start = alinear_reanudacion(start, total)
    if tmp.exists():
        with tmp.open("r+b") as fh:
            fh.truncate(start)
    print(f"  total={total/1e9:.2f}G resume={start/1e9:.3f}G chunk=1MiB", flush=True)
    failures = 0
    with tmp.open("ab" if start else "wb") as fh:
        pos = start
        while pos < total:
            end = min(pos + CHUNK - 1, total - 1)
            ok = False
            for attempt in range(1, 15):
                try:
                    rr = session.get(final, headers={"Range": f"bytes={pos}-{end}"}, timeout=(20, 90), stream=True)
                    if rr.status_code not in (200, 206):
                        final, total = resolve(url, session, token)
                        rr = session.get(final, headers={"Range": f"bytes={pos}-{end}"}, timeout=(20, 90), stream=True)
                    rr.raise_for_status()
                    buf = bytearray()
                    for c in rr.iter_content(128 * 1024):
                        if c:
                            buf.extend(c)
                    need = end - pos + 1
                    if len(buf) != need:
                        raise IOError(f"short {len(buf)}!={need}")
                    if pos + len(buf) > total:
                        buf = buf[: max(0, total - pos)]
                    fh.write(buf)
                    fh.flush()
                    pos = pos + len(buf)
                    ok = True
                    failures = 0
                    if (pos // CHUNK) % 20 == 0 or pos >= total:
                        print(f"  {100*pos/total:.1f}% ({pos/1e6:.0f}MB) free={free_gb():.1f}G", flush=True)
                    break
                except Exception as e:
                    failures += 1
                    print(f"  retry {attempt} @ {pos/1e6:.1f}MB: {type(e).__name__}", flush=True)
                    time.sleep(min(20, attempt))
                    try:
                        final, total = resolve(url, session, token)
                    except Exception:
                        pass
            if not ok:
                raise RuntimeError(f"stuck at {pos}")
    if tmp.stat().st_size != total:
        raise RuntimeError(f"size mismatch {tmp.stat().st_size} != {total}")
    tmp.rename(out)
    return out.stat().st_size

def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="CSV con columnas scene_name,url")
    parser.add_argument("--destino", required=True)
    args = parser.parse_args(argv)
    token = os.environ.get("EARTHDATA_TOKEN", "").strip()
    if not token:
        raise SystemExit("Falta EARTHDATA_TOKEN. No se descarga.")
    rows = pd.read_csv(args.csv)
    dest = Path(args.destino)
    dest.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    print(f"subset {len(rows)} free={free_gb():.1f}", flush=True)
    for i, row in enumerate(rows.itertuples(), 1):
        name = row.scene_name
        out = dest / f"{name}.h5"
        if out.exists() and out.stat().st_size > 50_000_000:
            print(f"[{i}] skip {name}", flush=True)
            continue
        if free_gb() < 10:
            print("LOW DISK", flush=True)
            break
        print(f"[{i}/{len(rows)}] {name}", flush=True)
        t0 = time.time()
        try:
            sz = download(row.url, out, session, token)
            print(f"  OK {sz/1e9:.2f}G in {(time.time()-t0)/60:.1f} min", flush=True)
        except Exception as e:
            print(f"  FAIL {type(e).__name__}: {e}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
