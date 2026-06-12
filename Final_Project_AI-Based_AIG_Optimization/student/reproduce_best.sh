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

python3 student/flow_optimizer.py \
  --reproduce-best \
  --mockturtle-max-modes 4 \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs

# Stage 18: semantic front-end split reconstruction for representative float/arithmetic bottlenecks
echo "Stage 18: semantic_split_optimize - exponent/field-pair/class split front-end reconstruction"
for case in ex200 ex201 ex202 ex203 ex220 ex240 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex298 ex299; do
  python3 student/flow_optimizer.py \
    --semantic-split-optimize \
    --case "${case}" \
    --semantic-max-splits 8 \
    --semantic-max-flows 4 \
    --timeout-per-case 300 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done

# Stage 19: circuit-family specific refinement for structurally ambiguous cases
echo "Stage 19: circuit_type_optimize - family-specific truth-seed and polish search"
for case in ex223 ex225 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex299; do
  python3 student/flow_optimizer.py \
    --circuit-type-optimize \
    --case "${case}" \
    --circuit-type-max-flows 8 \
    --circuit-type-max-seeds 3 \
    --timeout-per-case 180 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done

# Stage 20: post-hoc ABC flow refinement for all cases above reference ADP
echo "Stage 20: refine_close - ABC flow search on all cases above reference"
python3 student/refine_close.py \
  --case-workers 8 \
  --workers 4 \
  --max-ratio 99

# Stage 21: ex262 cleanup (only case that improved in post-hoc refine)
echo "Stage 21: targeted refine_close for ex262"
python3 student/refine_close.py \
  --cases ex262 \
  --case-workers 1 \
  --workers 4 \
  --max-ratio 99

# Stage 24: area-first deepsyn pass for cases still above 1.5x reference
echo "Stage 24: deep_area_opt - area-first pass for high-ratio cases"
python3 student/advanced_synthesis.py --mode deepsyn

# Stage 25: cleanup after area-first pass for newly exposed wins
echo "Stage 25: targeted refine_close cleanup after area-first pass"
for case in ex219 ex247 ex261; do
  python3 student/refine_close.py \
    --cases "${case}" \
    --case-workers 1 \
    --workers 4 \
    --max-ratio 99
done

# Stage 26: decoded semantic probes and ex261 final cleanup
echo "Stage 26: specialized semantic generators and ex261 final cleanup"
python3 student/advanced_synthesis.py --mode semantic --case ex261
python3 student/refine_close.py \
  --cases ex261 \
  --case-workers 1 \
  --workers 4 \
  --max-ratio 99

# Stage 27: verified ex295 Pareto cleanup found after code organization
echo "Stage 27: ex295 area-Pareto cleanup"
python3 student/flow_optimizer.py \
  --case ex295 \
  --pareto-area-structural \
  --pareto-area-seconds 180 \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs

# Stage 28: ex295 guarded massive cleanup tail
echo "Stage 28: ex295 refine/area/objective cleanup"
python3 student/refine_close.py \
  --cases ex295 \
  --case-workers 1 \
  --workers 4 \
  --max-ratio 99
python3 student/flow_optimizer.py \
  --case ex295 \
  --area-first-refine \
  --timeout-per-case 180 \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs
python3 student/flow_optimizer.py \
  --case ex295 \
  --objective-guided-refine \
  --objective-max-per-family 5 \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs
python3 student/refine_close.py \
  --cases ex295 \
  --case-workers 1 \
  --workers 4 \
  --max-ratio 99

# Stage 29: semantic word-level reconstruction for identified fp8 cases
# (ex240 = fp8 e4m3 add, ex241 = fp8 e4m3 mul). Emits exact RTL, synthesizes
# via Yosys + ABC + &my_deepsyn, and adopts only on strict ADP improvement.
echo "Stage 29: fp8_synth - semantic word-level reconstruction"
python3 student/fp8_synth.py

python3 evaluate.py \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output

# Final: verify nothing regressed versus the recorded best results
echo "Final verification: output/ vs best_output/"
python3 student/verify_reproduce.py

# Refresh per-case optimization recipes (student/case_recipes/)
python3 student/recipe_store.py --refresh
