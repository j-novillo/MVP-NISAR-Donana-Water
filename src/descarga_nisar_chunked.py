#!/usr/bin/env python3
"""Resumable 1 MiB Range downloader for NISAR GUNW (CloudFront drops larger streams)."""
import os, time, requests, pandas as pd
from pathlib import Path

tok = os.environ["EARTHDATA_TOKEN"]
rows = pd.read_csv("/workspace/MVP-NISAR-Donana-Water/data/raw/nisar_subset.csv")
dest = Path("/workspace/MVP-NISAR-Donana-Water/data/raw/interferogramas")
dest.mkdir(parents=True, exist_ok=True)
CHUNK = 1 * 1024 * 1024
session = requests.Session()

def free_gb():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 1e9

def resolve(url):
    r = session.get(url, headers={"Authorization": f"Bearer {tok}"}, stream=True, timeout=60, allow_redirects=True)
    final = r.url
    r.close()
    rr = session.get(url, headers={"Authorization": f"Bearer {tok}", "Range": "bytes=0-0"}, timeout=60, allow_redirects=True)
    cr = rr.headers.get("Content-Range", "")
    rr.close()
    total = int(cr.split("/")[-1])
    return final, total

def download(url, out: Path):
    tmp = out.with_suffix(".part")
    final, total = resolve(url)
    start = tmp.stat().st_size if tmp.exists() else 0
    start = (start // CHUNK) * CHUNK
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
                        final, total = resolve(url)
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
                        final, total = resolve(url)
                    except Exception:
                        pass
            if not ok:
                raise RuntimeError(f"stuck at {pos}")
    if tmp.stat().st_size != total:
        raise RuntimeError(f"size mismatch {tmp.stat().st_size} != {total}")
    tmp.rename(out)
    return out.stat().st_size

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
        sz = download(row.url, out)
        print(f"  OK {sz/1e9:.2f}G in {(time.time()-t0)/60:.1f} min", flush=True)
    except Exception as e:
        print(f"  FAIL {type(e).__name__}: {e}", flush=True)
print("DONE", flush=True)
