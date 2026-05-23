#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

python3 student/flow_optimizer.py \
  --reproduce-best \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs

python3 evaluate.py \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output
