#!/usr/bin/env python3
"""Long &my_deepsyn area-Pareto search on the hardest lagging cases.

Pure structural optimization (always equivalent). Tries multiple seeds and
both ADP and area cost functions, adopts only on strict ADP improvement.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"

DEFAULT_CASES = ["ex250", "ex252", "ex286"]


def optimize(case: str, seconds: int, seeds: list[int]) -> None:
    aig = OUTPUT / f"{case}.aig"
    truth = BENCHMARKS / f"{case}.truth"
    _, _, cur = measure_adp(ABC, aig, 60, ROOT)
    print(f"[{case}] current ADP={cur:,}", flush=True)
    best = cur

    with tempfile.TemporaryDirectory(prefix=f"hard_{case}_") as tmp_str:
        tmp = Path(tmp_str)
        for cost in ("adp", "area"):
            for seed in seeds:
                pareto = tmp / f"p_{cost}_{seed}"
                pareto.mkdir(parents=True, exist_ok=True)
                try:
                    run_abc_script(
                        ABC,
                        f'read_aiger "{aig}"; dc2; dc2; '
                        f'&get; &my_deepsyn -T {seconds} -S {seed} -O "{pareto}" -C {cost}; &put',
                        seconds + 120,
                    )
                except Exception as exc:
                    print(f"[{case}] deepsyn {cost}/{seed} error: {exc}", flush=True)
                    continue
                for cand in sorted(pareto.glob("*.aig")):
                    try:
                        _, _, adp = measure_adp(ABC, cand, 60, ROOT)
                    except Exception:
                        continue
                    if adp < best and is_equivalent(ABC, truth, cand, 180, ROOT):
                        shutil.copyfile(cand, aig)
                        best = adp
                        print(f"[{case}] {cost}/{seed} {cand.stem}: ADP={adp:,} *** ADOPTED ***", flush=True)
    if best < cur:
        print(f"[{case}] {cur:,} -> {best:,} (-{cur - best:,})", flush=True)
    else:
        print(f"[{case}] no improvement (kept {cur:,})", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=DEFAULT_CASES)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--seeds", type=int, nargs="*", default=[0, 42, 7])
    args = ap.parse_args()
    for case in args.cases:
        optimize(case, args.seconds, args.seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
