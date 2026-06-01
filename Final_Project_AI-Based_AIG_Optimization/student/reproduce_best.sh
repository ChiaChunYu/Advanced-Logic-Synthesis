#!/usr/bin/env bash
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
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs

# Stage 18: post-hoc ABC flow refinement for all cases above reference ADP
echo "Stage 18: refine_close – ABC flow search on all cases above reference"
python3 student/refine_close.py \
  --case-workers 8 \
  --workers 4 \
  --max-ratio 99

# Stage 19: re-verify and keep the top-3 seed improvements (ex272/ex276/ex280)
echo "Stage 19: reproduce_top3 – re-seed from current output and verify top-3"
bash student/reproduce_top3.sh

python3 evaluate.py \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output
