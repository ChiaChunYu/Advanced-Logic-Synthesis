#!/usr/bin/env python3
"""Verify reproducibility: compare output/ against best_output/ per case.

For every case the reproduced AIG in output/ must:
  1. exist,
  2. be equivalent to the truth table,
  3. have ADP <= the recorded best in best_output/ (no regression).

Usage (from project root, inside WSL):
  python3 student/verify_reproduce.py            # compare output/ vs best_output/
  python3 student/verify_reproduce.py --update   # additionally copy strict
                                                 # improvements into best_output/

Exit code 0 = all cases pass; 1 = at least one regression/missing case.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp

ABC         = ROOT / "student" / "abc"
BENCHMARKS  = ROOT / "benchmarks"
OUTPUT      = ROOT / "output"
BEST_OUTPUT = ROOT / "best_output"
ALL_CASES   = [f"ex{i}" for i in range(200, 300)]


def _load_ref() -> dict[str, int]:
    ref: dict[str, int] = {}
    path = ROOT / "reference_result.csv"
    if path.exists():
        with open(path) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true",
                        help="copy strict improvements from output/ into best_output/")
    args = parser.parse_args()

    ref = _load_ref()
    BEST_OUTPUT.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    improved: list[str] = []
    total_out = 0
    total_best = 0

    print(f"{'case':<7} {'output ADP':>12} {'best ADP':>12} {'ref ADP':>12}  status")
    print("-" * 60)
    for case in ALL_CASES:
        truth = BENCHMARKS / f"{case}.truth"
        out_aig = OUTPUT / f"{case}.aig"
        best_aig = BEST_OUTPUT / f"{case}.aig"

        if not truth.is_file():
            continue
        if not out_aig.is_file():
            failures.append(f"{case}: missing output AIG")
            print(f"{case:<7} {'MISSING':>12}")
            continue

        if not is_equivalent(ABC, truth, out_aig, 180, ROOT):
            failures.append(f"{case}: output AIG NOT equivalent")
            print(f"{case:<7} {'NOT_EQUIV':>12}")
            continue

        _, _, out_adp = measure_adp(ABC, out_aig, 120, ROOT)
        best_adp = None
        if best_aig.is_file():
            try:
                _, _, best_adp = measure_adp(ABC, best_aig, 120, ROOT)
            except Exception:
                best_adp = None

        status = "ok"
        if best_adp is None:
            status = "new"
            if args.update:
                shutil.copyfile(out_aig, best_aig)
                improved.append(case)
        elif out_adp > best_adp:
            status = f"REGRESSION (+{out_adp - best_adp})"
            failures.append(f"{case}: output ADP {out_adp} > best {best_adp}")
        elif out_adp < best_adp:
            status = f"improved (-{best_adp - out_adp})"
            if args.update:
                shutil.copyfile(out_aig, best_aig)
                improved.append(case)

        total_out += out_adp
        total_best += best_adp if best_adp is not None else out_adp
        ref_str = f"{ref.get(case, 0):>12,}" if case in ref else f"{'-':>12}"
        print(f"{case:<7} {out_adp:>12,} {(best_adp or 0):>12,} {ref_str}  {status}")

    print("-" * 60)
    print(f"Total output ADP: {total_out:,}   total best ADP: {total_best:,}")
    if improved:
        print(f"Updated best_output for {len(improved)} cases: {', '.join(improved)}")
    if failures:
        print(f"\nFAILURES ({len(failures)}):")
        for f in failures:
            print(f"  {f}")
        return 1
    print("\nAll cases reproduced at or better than best_output.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
