#!/usr/bin/env bash
# Descarga (o fabrica) las entradas de la PoC.
#   bash src/download.sh              usa config.yaml (modo: sintetico | real)
#   bash src/download.sh --sintetico  fuerza la escena falsa
#   bash src/download.sh --real       ASF + Copernicus + capas
#   bash src/download.sh --real --listar
#                                     solo catálogos, sin bajar los binarios
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$RAIZ"

if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "Hace falta Python 3.11 o posterior." >&2
  exit 1
fi

MODO=""
LISTAR=""
for arg in "$@"; do
  case "$arg" in
    --real) MODO="real" ;;
    --sintetico|--sintético) MODO="sintetico" ;;
    --listar) LISTAR="--listar" ;;
    *) echo "Argumento no reconocido: $arg" >&2; exit 2 ;;
  esac
done

if [[ -z "$MODO" ]]; then
  MODO="$("$PY" - <<'PY'
import sys
sys.path.insert(0, "src")
from utilidades import cargar_config
print(cargar_config().get("modo", "sintetico"))
PY
)"
fi

if [[ "$MODO" == "sintetico" ]]; then
  echo "Modo sintético: no se llama a ASF ni a Copernicus."
  "$PY" src/sintetico.py
  exit 0
fi

if [[ "$MODO" != "real" ]]; then
  echo "modo='$MODO' no es sintetico ni real." >&2
  exit 2
fi

echo "Modo real. Credenciales solo desde el entorno (.env.example)."
"$PY" src/descarga_asf.py ${LISTAR}
"$PY" src/descarga_cdse.py ${LISTAR}
if [[ -z "$LISTAR" ]]; then
  "$PY" src/descarga_capas.py
  echo "Si hay Sentinel-2 L2A descargado y parcelas SIGPAC:"
  echo "  $PY src/ndvi_s2.py"
fi
