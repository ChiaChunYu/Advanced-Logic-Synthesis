#!/usr/bin/env python3
"""Re-synthesize every case from its truth table with more candidates/time.

Directly calls optimize_case() which already competes against the existing
output AIG — existing result is kept when new candidates are not better.

Usage (from WSL):
  python3 student/resynth_all.py [--workers N] [--candidates N] [--timeout N]
"""
from __future__ import annotations

import argparse, shutil, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import measure_adp
from blif_builder import read_truth
from flow_optimizer import optimize_case, ALL_CASES

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)


def _adp(case: str) -> int | None:
    aig = OUTPUT / f"{case}.aig"
    if not aig.is_file():
        return None
    try:
        return measure_adp(ABC, aig, 60, ROOT)[2]
    except Exception:
        return None


def run_case(case: str, max_candidates: int, seed: int, timeout: int,
             use_ga: bool, use_bdd: bool) -> dict:
    before = _adp(case)
    aig = OUTPUT / f"{case}.aig"
    backup = LOGS / f"resynth_backup_{case}.aig"
    if aig.is_file():
        shutil.copyfile(aig, backup)

    start_t = time.monotonic()
    try:
        # use_polish=True so best candidate gets further polished
        rows, summary = optimize_case(
            case, ABC, BENCHMARKS, OUTPUT,
            LOGS / "tmp_resynth",
            max_candidates, seed, timeout, ROOT,
            use_ga=use_ga,
            use_bdd=use_bdd,
            use_polish=True,
            try_complement=True,
            history_guided_ga=False,
        )
        # optimize_case already writes the best to OUTPUT if it beats existing
        after = _adp(case)
        elapsed = time.monotonic() - start_t

        improved = (before is not None and after is not None and after < before)
        tag = f"  *** IMPROVED {before:,} -> {after:,} (-{before-after:,}) ***" if improved else ""
        print(f"[{case}] {before or '?':>10} → {after or '?':>10}  ({elapsed:.0f}s){tag}", flush=True)

        # safety rollback: if somehow worse, restore backup
        if before is not None and after is not None and after > before:
            print(f"  [{case}] ROLLBACK (new={after} > old={before})", flush=True)
            if backup.is_file():
                shutil.copyfile(backup, aig)
            after = before

        return {"case": case, "before": before, "after": after}

    except Exception as exc:
        print(f"[{case}] ERROR: {exc}", flush=True)
        if backup.is_file() and aig.is_file():
            # restore if something went wrong
            before2 = _adp(case)
            bak_adp = measure_adp(ABC, backup, 30, ROOT)[2] if backup.is_file() else None
            if bak_adp and before2 and before2 > bak_adp:
                shutil.copyfile(backup, aig)
        return {"case": case, "before": before, "after": _adp(case)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers",    type=int, default=6)
    ap.add_argument("--candidates", type=int, default=120,
                    help="Number of initial×flow pairs to try per case")
    ap.add_argument("--timeout",    type=int, default=600,
                    help="Per-case timeout in seconds")
    ap.add_argument("--seed",       type=int, default=0)
    ap.add_argument("--no-ga",      action="store_true")
    ap.add_argument("--no-bdd",     action="store_true")
    ap.add_argument("--cases",      nargs="*", default=None,
                    help="Specific cases to run (default: all 100)")
    args = ap.parse_args()

    cases = args.cases if args.cases else [c for c in ALL_CASES
                                           if (BENCHMARKS / f"{c}.truth").is_file()]
    print(f"Re-synthesizing {len(cases)} cases  candidates={args.candidates}"
          f"  timeout={args.timeout}s  workers={args.workers}", flush=True)

    # Measure starting total
    totals_before = {c: _adp(c) for c in cases}
    total_before = sum(v for v in totals_before.values() if v)
    print(f"Total ADP before: {total_before:,}", flush=True)

    # Large cases (big AIG area) get fewer parallel slots
    large = {"ex297", "ex299", "ex226", "ex206", "ex220", "ex221", "ex222", "ex230"}
    small_cases = [c for c in cases if c not in large]
    large_cases = [c for c in cases if c in large]

    results = []

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {
            pool.submit(run_case, c, args.candidates, args.seed,
                        args.timeout, not args.no_ga, not args.no_bdd): c
            for c in small_cases
        }
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as exc:
                print(f"WORKER ERROR {futs[f]}: {exc}", flush=True)

    # Large cases: 2 workers max
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {
            pool.submit(run_case, c, args.candidates, args.seed,
                        args.timeout, not args.no_ga, not args.no_bdd): c
            for c in large_cases
        }
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as exc:
                print(f"WORKER ERROR {futs[f]}: {exc}", flush=True)

    # Summary
    total_after = sum(r["after"] for r in results if r["after"] is not None)
    improved = [r for r in results if r["before"] and r["after"] and r["after"] < r["before"]]
    regressed = [r for r in results if r["before"] and r["after"] and r["after"] > r["before"]]

    print(f"\n{'='*60}")
    print(f"Total ADP: {total_before:,} → {total_after:,}  (saved {total_before - total_after:,})")
    print(f"Improved: {len(improved)}  |  Regressed: {len(regressed)}  |  Unchanged: {len(results)-len(improved)-len(regressed)}")
    if improved:
        print("\nImproved cases:")
        for r in sorted(improved, key=lambda x: (x["before"] or 0) - (x["after"] or 0), reverse=True):
            print(f"  {r['case']}: {r['before']:,} → {r['after']:,}  (-{r['before']-r['after']:,})")
    if regressed:
        print("\nWARNING - Regressed cases (should not happen due to rollback):")
        for r in regressed:
            print(f"  {r['case']}: {r['before']:,} → {r['after']:,}")


if __name__ == "__main__":
    main()
