#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${PROJECT_ROOT}"

ABC="student/abc"
BACKUP="student/logs/massive_opt_backup"
mkdir -p "${BACKUP}"

cases=(
  ex286 ex252 ex297 ex250 ex299 ex264 ex263 ex240
  ex225 ex262 ex248 ex295 ex223 ex224 ex247 ex246
)

measure_adp() {
  local case="$1"
  python3 evaluate.py --case "${case}" --timeout 60 \
    | awk '/^ex[0-9]+[[:space:]]+OK/ { print $5 }'
}

copy_backup() {
  local case="$1"
  cp -f "output/${case}.aig" "${BACKUP}/${case}.aig"
}

restore_if_worse() {
  local case="$1"
  local before="$2"
  local after
  after="$(measure_adp "${case}")"
  if [[ -z "${after}" ]]; then
    echo "[${case}] verification failed after search; restoring backup"
    cp -f "${BACKUP}/${case}.aig" "output/${case}.aig"
    return
  fi
  if (( after > before )); then
    echo "[${case}] worsened ${before} -> ${after}; restoring backup"
    cp -f "${BACKUP}/${case}.aig" "output/${case}.aig"
  elif (( after < before )); then
    echo "[${case}] IMPROVED ${before} -> ${after}"
  else
    echo "[${case}] unchanged ${after}"
  fi
}

for case in "${cases[@]}"; do
  echo "=== ${case} ==="
  before="$(measure_adp "${case}")"
  copy_backup "${case}"
  echo "[${case}] start ADP ${before}"

  python3 student/refine_close.py \
    --cases "${case}" \
    --case-workers 1 \
    --workers 4 \
    --max-ratio 99 || true

  python3 student/flow_optimizer.py \
    --case "${case}" \
    --area-first-refine \
    --timeout-per-case 180 \
    --abc "${ABC}" \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs || true

  python3 student/flow_optimizer.py \
    --case "${case}" \
    --objective-guided-refine \
    --objective-max-per-family 5 \
    --abc "${ABC}" \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs || true

  python3 student/flow_optimizer.py \
    --case "${case}" \
    --micro-guided-refine \
    --micro-max-flows 8 \
    --abc "${ABC}" \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs || true

  python3 student/flow_optimizer.py \
    --case "${case}" \
    --gia-canonical-converge \
    --gia-canonical-max-passes 8 \
    --abc "${ABC}" \
    --benchmarks benchmarks \
    --output output \
    --logs student/logs || true

  restore_if_worse "${case}" "${before}"
done

echo "=== final verify ==="
python3 evaluate.py --timeout 60
