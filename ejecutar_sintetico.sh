#!/usr/bin/env bash
# Recorre la PoC entera con la escena sintética.
set -euo pipefail
cd "$(dirname "$0")"
if command -v python >/dev/null 2>&1; then
  PY=python
else
  PY=python3
fi
bash src/download.sh --sintetico
"$PY" src/procesar_insar.py
"$PY" src/medir.py
"$PY" src/score.py
