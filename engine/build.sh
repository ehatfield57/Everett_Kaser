#!/bin/bash
# Build the KINT interpreters as WebAssembly:
#   web/kint5.js + kint5.wasm   (KINT 1-5 games)
#   web/kint6.js + kint6.wasm   (KINT 6 games)
#
# Needs Emscripten (emcc).  Usage:  engine/build.sh [debug]
set -euo pipefail
cd "$(dirname "$0")"

python3 patch_k5.py
python3 patch_k6.py

OPT="-O3"
if [ "${1:-}" = "debug" ]; then OPT="-O1 -g -sASSERTIONS=2 -sSAFE_HEAP=1"; fi

COMMON="-Wno-everything --js-library k5/kint_lib.js
  -sENVIRONMENT=worker -sMODULARIZE=1
  -sALLOW_MEMORY_GROWTH=1 -sINITIAL_MEMORY=64MB -sMAXIMUM_MEMORY=2GB -sSTACK_SIZE=1MB
  -sEXPORTED_RUNTIME_METHODS=HEAPU8,ccall
  -sINVOKE_RUN=0 -sEXIT_RUNTIME=0"

emcc $OPT $COMMON -I k5 -I k5/gen \
  k5/gen/pmach.c k5/gen/hlb.c k5/gen/float.c k5/gen/djpeg.c k5/kplat.c \
  -sEXPORTED_FUNCTIONS=_kp_main,_kp_event,_kp_set_paths -sEXPORT_NAME=createKint5 -o ../web/kint5.js
echo "built web/kint5.js and web/kint5.wasm"

emcc $OPT $COMMON -I k6 -I k6/gen -DSPNG_USE_MINIZ -DSPNG_DISABLE_OPT \
  k6/gen/pmach.c k6/gen/graph.c k6/gen/kmain6.c k6/gen/miniz.c k6/gen/spng.c k6/kplat6.c \
  -sEXPORTED_FUNCTIONS=_kp_main,_kp_event,_kp_set_paths,_kp_set_beta -sEXPORT_NAME=createKint6 -o ../web/kint6.js
echo "built web/kint6.js and web/kint6.wasm"
