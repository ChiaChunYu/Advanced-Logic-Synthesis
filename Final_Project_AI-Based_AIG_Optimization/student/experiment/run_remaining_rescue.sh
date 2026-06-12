#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

small_cases=(ex286 ex252 ex250 ex264 ex263 ex240 ex261 ex262 ex248 ex247 ex246)
semantic_cases=(ex286 ex252 ex250 ex240 ex225 ex223 ex224 ex295 ex297 ex299)
large_cases=(ex297 ex299)

for case in "${small_cases[@]}"; do
  echo "NPN ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --exact-npn-rescue \
    --npn-max-support 8 \
    --npn-max-flows 6 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs

  echo "TRANSDUCTION ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --transduction-rescue \
    --transduction-budget 20 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done

for case in "${semantic_cases[@]}"; do
  echo "CIRCUIT_TYPE ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --circuit-type-optimize \
    --circuit-type-max-flows 12 \
    --circuit-type-max-seeds 5 \
    --timeout-per-case 240 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs

  echo "SEMANTIC_SPLIT ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --semantic-split-optimize \
    --semantic-max-splits 10 \
    --semantic-max-flows 5 \
    --timeout-per-case 360 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done

for case in "${large_cases[@]}"; do
  echo "LONG_LARGE ${case}"
  python3 student/flow_optimizer.py \
    --case "${case}" \
    --long-large-structural \
    --long-large-seconds 300 \
    --long-large-min-area 0 \
    --long-large-min-adp 0 \
    --abc student/abc \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs
done
