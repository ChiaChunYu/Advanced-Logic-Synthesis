#!/usr/bin/env python3
"""Baseline optimizer for the ALS 2026 final project.

This example intentionally uses a very small ABC flow.  Students should replace
or extend this script with their own AI/LLM-guided search or optimization flow.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_abc(abc: Path, truth: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command = f"read_truth -xf {truth}; st; write_aiger -s {output}"
    result = subprocess.run(
        [str(abc), "-c", command],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ABC failed for {truth.name}\n{result.stdout}")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Generate baseline AIG files from truth-table benchmarks."
    )
    parser.add_argument(
        "--abc",
        type=Path,
        default=Path(__file__).resolve().with_name("abc"),
        help="Path to the ABC executable.",
    )
    parser.add_argument(
        "--benchmarks",
        type=Path,
        default=repo_root / "benchmarks",
        help="Directory containing exNNN.truth files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "output",
        help="Directory where exNNN.aig files will be written.",
    )
    parser.add_argument(
        "--case",
        help="Optional single case name, for example ex200.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.abc.is_file():
        print(f"ABC executable not found: {args.abc}", file=sys.stderr)
        return 2
    if not args.benchmarks.is_dir():
        print(f"Benchmark directory not found: {args.benchmarks}", file=sys.stderr)
        return 2

    if args.case:
        truth_files = [args.benchmarks / f"{args.case}.truth"]
    else:
        truth_files = sorted(args.benchmarks.glob("ex*.truth"))

    if not truth_files:
        print("No benchmark truth files found.", file=sys.stderr)
        return 2

    for truth in truth_files:
        if not truth.is_file():
            print(f"Missing benchmark: {truth}", file=sys.stderr)
            return 2
        output = args.output / f"{truth.stem}.aig"
        print(f"[ABC] {truth.name} -> {output}")
        run_abc(args.abc, truth, output)

    print(f"Generated {len(truth_files)} AIG file(s) in {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
