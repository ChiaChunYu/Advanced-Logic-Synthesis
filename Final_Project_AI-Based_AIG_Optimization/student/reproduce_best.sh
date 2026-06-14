#!/usr/bin/env bash
# Usage:
#   bash student/reproduce_best.sh    # full reproduction pipeline
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command not found: $1" >&2
    exit 2
  fi
}

# ── full reproduction ──────────────────────────────────────────────────────────

require_command python3
require_command yosys

if [[ ! -x student/abc ]]; then
  echo "Required ABC executable not found or not executable: student/abc" >&2
  exit 2
fi

if [[ ! -x student/mockturtle_opt/mockturtle_opt ]]; then
  require_command cmake
  if [[ ! -d student/mockturtle_src ]]; then
    echo "mockturtle sources not found: student/mockturtle_src" >&2
    exit 2
  fi
  cmake -S student/mockturtle_opt -B student/mockturtle_opt/build
  cmake --build student/mockturtle_opt/build --target mockturtle_opt -j2
fi

# ════════════════════════════════════════════════════════════════════════════
# CORE PIPELINE — truth-table synthesis through full structural convergence.
# (flow_optimizer.py internal stages 1-17; see --show-reproduce-recipe.)
# ════════════════════════════════════════════════════════════════════════════
echo "=== Core pipeline: hybrid synthesis + structural convergence ==="
python3 student/flow_optimizer.py \
  --reproduce-best \
  --mockturtle-max-modes 4 \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs

abc_refine() {  # post_optimize.py refine with the standard --workers/--max-ratio tail
  python3 student/post_optimize.py refine "$@" --workers 4 --max-ratio 99
}

flow_opt() {    # flow_optimizer.py single-case helper with the standard paths
  python3 student/flow_optimizer.py \
    --abc student/abc --benchmarks benchmarks --output output --logs student/logs "$@"
}

# The post-core stages below run in their original, validated execution order.
# They are only grouped and commented here for clarity — every command is
# identical to the historical Stage 18-29 sequence.

# ── Block A: semantic / family front-end reconstruction ─────────────────────
echo "=== Block A: semantic front-end reconstruction (was stage 18-19) ==="

echo "[A1] semantic split reconstruction (exponent / field-pair / class split)"
for case in ex200 ex201 ex202 ex203 ex220 ex240 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex298 ex299; do
  flow_opt --semantic-split-optimize --case "${case}" \
    --semantic-max-splits 8 --semantic-max-flows 4 --timeout-per-case 300
done

echo "[A2] circuit-family refinement (truth-seed + polish for ambiguous cases)"
for case in ex223 ex225 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex299; do
  flow_opt --circuit-type-optimize --case "${case}" \
    --circuit-type-max-flows 8 --circuit-type-max-seeds 3 --timeout-per-case 180
done

# ── Block B: back-end flow refinement (equivalence-gated, ADP-only) ──────────
echo "=== Block B: back-end flow refinement (was stage 20-28) ==="

echo "[B1] global flow refinement over all above-reference cases"
abc_refine --case-workers 8

echo "[B2] cleanup of the case improved by the global sweep (ex262)"
abc_refine --cases ex262 --case-workers 1

echo "[B3] area-first &my_deepsyn pass for high-ratio cases"
python3 student/post_optimize.py advanced --mode deepsyn

echo "[B4] cleanup after the area-first pass (ex219 ex247 ex261)"
for case in ex219 ex247 ex261; do
  abc_refine --cases "${case}" --case-workers 1
done

echo "[B5] decoded semantic probe + ex261 cleanup"
python3 student/post_optimize.py advanced --mode semantic --case ex261
abc_refine --cases ex261 --case-workers 1

echo "[B6] ex295 guarded cleanup tail (Pareto -> refine -> area-first -> objective)"
flow_opt --case ex295 --pareto-area-structural --pareto-area-seconds 180
abc_refine --cases ex295 --case-workers 1
flow_opt --case ex295 --area-first-refine --timeout-per-case 180
flow_opt --case ex295 --objective-guided-refine --objective-max-per-family 5
abc_refine --cases ex295 --case-workers 1

# ── Block C: word-level semantic reconstruction (arithmetic RTL) ─────────────
echo "=== Block C: word-level semantic reconstruction ==="
echo "[C1] fp8 RTL (ex240 e4m3 add, ex241 e4m3 mul, ex245 e5m2 add)"
python3 student/rtl_synth.py --family fp8
echo "[C2] signed multiplier RTL (ex261 5x5, ex262 6x6, ex263 7x7, ex264 8x8)"
python3 student/rtl_synth.py --family mult
echo "[C3] integer isqrt RTL (ex279 16-bit)"
python3 student/rtl_synth.py --family isqrt
# Note: square (ex270-274) and small mult/isqrt are identified but their RTL
# loses to the structural AIG, so they are intentionally not run here.

# ── Block D: final back-end sweep over every case ────────────────────────────
# optimize.py applies the strongest equivalence-gated back-end search (broad
# ABC flows, truth re-synthesis, &my_deepsyn ADP/area Pareto, and mockturtle
# structural resynthesis) to all 100 cases. It only ever replaces a case's
# output AIG with a CEC-verified, strictly-lower-ADP result, so re-running it
# is safe and reproduces the gains that were found interactively.
echo "=== Block D: final back-end sweep (optimize.py --all) ==="
python3 student/optimize.py --all \
  --strategies flows resynth deepsyn mockturtle \
  --timeout 200 --deepsyn-seconds 90 --seeds 0 42 --workers 6 --no-refresh

# ── Block D2: extra-long deepsyn on cases that only break through under a long,
# multi-seed randomized search (e.g. ex242 fp8-div: 15,285 -> 11,040 found only
# at 480s x4 seeds, which the 90s pass above misses). Equivalence-gated, so it
# is always safe and only adopts a strict improvement. ────────────────────────
echo "=== Block D2: extra-long deepsyn on long-search-sensitive cases ==="
python3 student/optimize.py \
  --cases ex242 ex243 ex247 ex248 ex249 ex251 ex262 ex289 ex205 ex264 ex263 \
  --strategies deepsyn \
  --timeout 600 --deepsyn-seconds 480 --seeds 0 42 7 11 --workers 6 --no-refresh

# ── Block E: evaluate, verify no regression, refresh per-case records ────────
echo "=== Block E: evaluate + verify + record ==="
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
python3 student/pipeline_bookend.py verify
python3 student/pipeline_bookend.py recipe --refresh
