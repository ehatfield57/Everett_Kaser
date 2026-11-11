#!/bin/bash
# Build the KINT 5 interpreter as WebAssembly: web/kint5.js + web/kint5.wasm
#
# Needs Emscripten (emcc).  Usage:  engine/build.sh [debug]
set -euo pipefail
cd "$(dirname "$0")"

python3 patch_k5.py

OPT="-O3"
if [ "${1:-}" = "debug" ]; then OPT="-O1 -g -sASSERTIONS=2 -sSAFE_HEAP=1"; fi

emcc $OPT \
  -I k5 -I k5/gen \
  -Wno-everything \
  k5/gen/pmach.c k5/gen/float.c k5/gen/djpeg.c k5/kplat.c \
  --js-library k5/kint_lib.js \
  -sENVIRONMENT=worker \
  -sMODULARIZE=1 -sEXPORT_NAME=createKint5 \
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=64MB -sMAXIMUM_MEMORY=2GB \
  -sSTACK_SIZE=1MB \
  -sEXPORTED_FUNCTIONS=_kp_main,_kp_event \
  -sEXPORTED_RUNTIME_METHODS=HEAPU8 \
  -sINVOKE_RUN=0 -sEXIT_RUNTIME=0 \
  -o ../web/kint5.js

echo "built web/kint5.js and web/kint5.wasm"
