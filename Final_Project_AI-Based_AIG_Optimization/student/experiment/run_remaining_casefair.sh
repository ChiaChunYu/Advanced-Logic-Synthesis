#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

cases=(
  ex286 ex252 ex297 ex250 ex299 ex264 ex263 ex240 ex225
  ex261 ex262 ex248 ex295 ex223 ex224 ex247 ex246
)

for case in "${cases[@]}"; do
  echo "CASE ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --case-fair-next-optimize \
    --case-fair-stage-timeout 25 \
    --time-budget 180 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done
