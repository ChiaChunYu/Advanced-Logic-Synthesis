#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/student/mockturtle_opt.cpp"
OUT="$ROOT_DIR/student/mockturtle"
MOCKTURTLE="$ROOT_DIR/student/mockturtle_src"

if [[ ! -d "$MOCKTURTLE/include" || ! -d "$MOCKTURTLE/lib" ]]; then
  echo "mockturtle checkout not found at $MOCKTURTLE" >&2
  exit 1
fi

CXX_BIN="${CXX:-}"
if [[ -z "$CXX_BIN" ]]; then
  if command -v g++ >/dev/null 2>&1; then
    CXX_BIN=g++
  elif command -v clang++ >/dev/null 2>&1; then
    CXX_BIN=clang++
  else
    echo "No C++ compiler found. Install g++ or clang++ in WSL, then rerun this script." >&2
    exit 1
  fi
fi

"$CXX_BIN" -std=c++17 -O2 -DNDEBUG -DFMT_HEADER_ONLY \
  -I"$MOCKTURTLE/include" \
  -I"$MOCKTURTLE/lib/kitty" \
  -I"$MOCKTURTLE/lib/lorina" \
  -I"$MOCKTURTLE/lib/parallel_hashmap" \
  -I"$MOCKTURTLE/lib/fmt" \
  -I"$MOCKTURTLE/lib/percy" \
  -I"$MOCKTURTLE/lib/bill" \
  -I"$MOCKTURTLE/lib/rang" \
  -I"$MOCKTURTLE/lib/nauty" \
  -I"$MOCKTURTLE/lib/abcsat" \
  -I"$MOCKTURTLE/lib/abcesop" \
  "$SRC" -o "$OUT"

echo "Built $OUT"
