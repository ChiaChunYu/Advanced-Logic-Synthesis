#!/usr/bin/env python3
"""Unified per-case optimizer — the single place to push any case further.

Every strategy here is equivalence-gated and rollback-safe: a case's output
AIG is replaced only by a CEC-verified, strictly-lower-ADP candidate, so this
can be re-run on any case at any time without risk of regression.

Strategies (each tried in turn, best kept):
  1. resynth   — re-synthesize from the truth table (optimize_case, 120 cands)
  2. flows     — broad ABC synthesis flow suite on the current AIG
  3. deepsyn   — &my_deepsyn ADP + area Pareto search (multiple seeds)
  4. mockturtle— structural AIG/XAG/MIG resynthesis (if binary present)

After optimizing, the case recipe (student/case_recipes/<case>.json) is
refreshed so the new result and history are recorded.

Usage (from project root, inside WSL):
  python3 student/optimize.py --case ex250
  python3 student/optimize.py --case ex250 --strategies resynth deepsyn
  python3 student/optimize.py --all --workers 6
  python3 student/optimize.py --above-ratio 1.3        # only lagging cases
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script
from blif_builder import read_truth
from flow_optimizer import optimize_case
from case_runners import run_mockturtle_structural_case

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
MOCKTURTLE = ROOT / "student" / "mockturtle_opt" / "mockturtle_opt"
RECIPE     = ROOT / "student" / "recipe_store.py"
LOGS.mkdir(parents=True, exist_ok=True)

ALL_CASES = [f"ex{i}" for i in range(200, 300)]
LARGE_CASES = {"ex297", "ex299", "ex226", "ex206", "ex220", "ex221", "ex222", "ex230"}

ABC_FLOWS = [
    ("dc2x3",      "dc2; dc2; dc2; balance"),
    ("rwz_rfz",    "rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
    ("syn2",       "&get; &syn2 -J 8; &put; balance"),
    ("syn3",       "&get; &syn3; &put; balance"),
    ("dch",        "&get; &dch; &put; balance"),
    ("dch_syn2",   "&get; &dch; &syn2 -J 8; &put; balance"),
    ("dc2_syn2",   "dc2; &get; &syn2 -J 8; &put; dc2; balance"),
    ("resub_dc2",  "resub -K 8; dc2; rewrite -z; balance"),
    ("fraig_dc2",  "fraig; dc2; rewrite -z; balance"),
    # don't-care-based resubstitution (&mfs) — found to shrink several cases
    # that the rewrite/refactor flows had already saturated.
    ("mfs",        "dc2; &get; &mfs; &put; balance"),
    ("mfs_w4",     "&get; &dch; &mfs -W 4; &put; dc2; balance"),
    ("dc2_mfs",    "dc2; &get; &mfs -W 4 -M 5000; &put; dc2; balance"),
]


def cur_adp(case: str) -> int | None:
    aig = OUTPUT / f"{case}.aig"
    if not aig.is_file():
        return None
    try:
        return measure_adp(ABC, aig, 60, ROOT)[2]
    except Exception:
        return None


def _adopt(case: str, cand: Path, best: int) -> tuple[bool, int]:
    """Adopt cand if equivalent and strictly better. Returns (adopted, new_best)."""
    try:
        _, _, adp = measure_adp(ABC, cand, 60, ROOT)
    except Exception:
        return False, best
    if adp >= best:
        return False, best
    if not is_equivalent(ABC, BENCHMARKS / f"{case}.truth", cand, 180, ROOT):
        return False, best
    shutil.copyfile(cand, OUTPUT / f"{case}.aig")
    return True, adp


def strat_resynth(case: str, best: int, *, timeout: int) -> int:
    """Re-synthesize from truth table; optimize_case self-competes vs output."""
    try:
        optimize_case(
            case, ABC, BENCHMARKS, OUTPUT, LOGS / "tmp_optimize",
            120, 0, timeout, ROOT,
            use_ga=True, use_bdd=True, use_polish=True, try_complement=True,
        )
    except Exception as exc:
        print(f"  [{case}] resynth error: {exc}", flush=True)
    return cur_adp(case) or best


def strat_flows(case: str, best: int, *, timeout: int) -> int:
    aig = OUTPUT / f"{case}.aig"
    with tempfile.TemporaryDirectory(prefix=f"opt_{case}_") as tmp_str:
        tmp = Path(tmp_str)
        for name, flow in ABC_FLOWS:
            cand = tmp / f"{case}_{name}.aig"
            try:
                run_abc_script(
                    ABC,
                    f'read_aiger "{aig}"; {flow}; write_aiger -s "{cand}"',
                    timeout,
                )
            except Exception:
                continue
            adopted, best = _adopt(case, cand, best)
            if adopted:
                print(f"  [{case}] flows/{name}: ADP={best:,}", flush=True)
    return best


def strat_deepsyn(case: str, best: int, *, seconds: int, seeds: list[int]) -> int:
    aig = OUTPUT / f"{case}.aig"
    with tempfile.TemporaryDirectory(prefix=f"opt_ds_{case}_") as tmp_str:
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
                except Exception:
                    continue
                for cand in sorted(pareto.glob("*.aig")):
                    adopted, best = _adopt(case, cand, best)
                    if adopted:
                        print(f"  [{case}] deepsyn/{cost}/{seed}: ADP={best:,}", flush=True)
    return best


def strat_mockturtle(case: str, best: int, *, timeout: int) -> int:
    if not MOCKTURTLE.is_file():
        return best
    backup = LOGS / f"opt_mt_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_mockturtle_structural_case(
            case, ABC, BENCHMARKS, OUTPUT, LOGS,
            timeout_per_case=timeout, root=ROOT,
            mockturtle_bin=MOCKTURTLE, max_modes=4, exact_max_inputs=12,
        )
    except Exception as exc:
        print(f"  [{case}] mockturtle error: {exc}", flush=True)
    new = cur_adp(case) or best
    if new > best:  # safety rollback (run_mockturtle should never regress)
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return best
    return new


STRATEGIES = {
    "resynth":    lambda c, b, **k: strat_resynth(c, b, timeout=k["timeout"]),
    "flows":      lambda c, b, **k: strat_flows(c, b, timeout=min(k["timeout"], 120)),
    "deepsyn":    lambda c, b, **k: strat_deepsyn(c, b, seconds=k["deepsyn_seconds"], seeds=k["seeds"]),
    "mockturtle": lambda c, b, **k: strat_mockturtle(c, b, timeout=min(k["timeout"], 240)),
}
DEFAULT_ORDER = ["flows", "resynth", "deepsyn", "mockturtle"]


def optimize_one(case: str, strategies: list[str], **kw) -> dict:
    if not (OUTPUT / f"{case}.aig").is_file():
        print(f"[{case}] no output AIG, skipping", flush=True)
        return {"case": case, "start": None, "final": None}
    start = cur_adp(case)
    best = start
    print(f"[{case}] start ADP={start:,}", flush=True)
    for name in strategies:
        fn = STRATEGIES.get(name)
        if fn is None:
            print(f"  [{case}] unknown strategy '{name}'", flush=True)
            continue
        best = fn(case, best, **kw)
    if best < start:
        print(f"[{case}] {start:,} -> {best:,} (-{start - best:,})", flush=True)
    else:
        print(f"[{case}] no improvement (kept {start:,})", flush=True)
    return {"case": case, "start": start, "final": best}


def _select_cases(args) -> list[str]:
    explicit = list(args.case or []) + list(args.cases or [])
    if explicit:
        return explicit
    cases = [c for c in ALL_CASES if (OUTPUT / f"{c}.aig").is_file()]
    if args.above_ratio is not None:
        import csv
        ref = {}
        p = ROOT / "reference_result.csv"
        if p.exists():
            with open(p) as f:
                for row in csv.DictReader(f):
                    ref[row["case"]] = int(row["adp"])
        cases = [c for c in cases
                 if ref.get(c) and (cur_adp(c) or 0) / ref[c] >= args.above_ratio]
    return cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", action="append", help="case to optimize (repeatable)")
    ap.add_argument("--cases", nargs="+", default=None,
                    help="space-separated list of cases to optimize")
    ap.add_argument("--all", action="store_true", help="optimize all 100 cases")
    ap.add_argument("--above-ratio", type=float, default=None,
                    help="only cases with ADP/reference >= this ratio")
    ap.add_argument("--strategies", nargs="*", default=DEFAULT_ORDER,
                    help=f"subset/order of {list(STRATEGIES)}")
    ap.add_argument("--timeout", type=int, default=300, help="per-strategy timeout (s)")
    ap.add_argument("--deepsyn-seconds", type=int, default=120)
    ap.add_argument("--seeds", type=int, nargs="*", default=[0, 42])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-refresh", action="store_true",
                    help="skip recipe_store refresh at the end")
    args = ap.parse_args()

    if not args.case and not args.cases and not args.all and args.above_ratio is None:
        ap.error("specify --case, --cases, --all, or --above-ratio")

    cases = _select_cases(args)
    if not cases:
        print("no cases selected")
        return 0
    print(f"Optimizing {len(cases)} case(s): {', '.join(cases)}")
    print(f"Strategies: {args.strategies}\n")

    kw = dict(timeout=args.timeout, deepsyn_seconds=args.deepsyn_seconds, seeds=args.seeds)
    results = []
    small = [c for c in cases if c not in LARGE_CASES]
    large = [c for c in cases if c in LARGE_CASES]

    if len(small) == 1 and not large:
        results.append(optimize_one(small[0], args.strategies, **kw))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futs = {pool.submit(optimize_one, c, args.strategies, **kw): c for c in small}
            for f in as_completed(futs):
                results.append(f.result())
        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = {pool.submit(optimize_one, c, args.strategies, **kw): c for c in large}
            for f in as_completed(futs):
                results.append(f.result())

    improved = [r for r in results if r["start"] and r["final"] and r["final"] < r["start"]]
    saved = sum(r["start"] - r["final"] for r in improved)
    print(f"\n=== {len(improved)}/{len(results)} improved, saved {saved:,} ADP ===")
    for r in sorted(improved, key=lambda x: x["start"] - x["final"], reverse=True):
        print(f"  {r['case']}: {r['start']:,} -> {r['final']:,} (-{r['start']-r['final']:,})")

    if improved and not args.no_refresh:
        import subprocess
        subprocess.run([sys.executable, str(RECIPE), "--refresh"], cwd=str(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
