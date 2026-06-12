#!/usr/bin/env python3
"""Boost lagging cases using proper case_runner functions.

Strategy per family:
  mux_shannon     → run_type_guided_refine_case + run_deepsyn_structural_case
  monotone_general→ run_type_guided_refine_case + run_deepsyn_structural_case
  general         → run_long_large_structural_case
  signed_mult     → run_type_guided_refine_case (uses template-aware flows)
  constant_mixed  → run_type_guided_refine_case + run_small_case_refine_case
"""
import sys, csv, shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import measure_adp
from case_runners import (
    run_type_guided_refine_case,
    run_deepsyn_structural_case,
    run_long_large_structural_case,
    run_convergence_loop_case,
    run_small_case_refine_case,
    run_area_first_refine_case,
    run_objective_guided_refine_case,
)

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

# Family classification from previous analysis
FAMILY = {
    "ex223": "mux_shannon",
    "ex224": "mux_shannon",
    "ex225": "mux_shannon",
    "ex240": "monotone_general",
    "ex246": "mux_shannon",
    "ex247": "monotone_general",
    "ex248": "mux_shannon",
    "ex250": "monotone_general",
    "ex252": "constant_mixed",
    "ex262": "signed_mult",
    "ex263": "signed_mult",
    "ex264": "signed_mult",
    "ex286": "monotone_general",
    "ex295": "general",
    "ex297": "general",
    "ex299": "general",
}


def _load_ref() -> dict[str, int]:
    ref: dict[str, int] = {}
    csv_path = ROOT / "reference_result.csv"
    if csv_path.exists():
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def _cur_adp(case: str) -> int:
    return measure_adp(ABC, OUTPUT / f"{case}.aig", 60, ROOT)[2]


def _rollback(case: str, backup: Path, start_adp: int) -> None:
    try:
        cur = _cur_adp(case)
        bak_adp = measure_adp(ABC, backup, 30, ROOT)[2]
        if cur > bak_adp:
            shutil.copyfile(backup, OUTPUT / f"{case}.aig")
            print(f"  [{case}] rolled back", flush=True)
    except Exception:
        pass


def boost_case(case: str) -> None:
    family = FAMILY.get(case, "general")
    aig = OUTPUT / f"{case}.aig"
    backup = LOGS / f"boost_lagging_backup_{case}.aig"
    shutil.copyfile(aig, backup)
    start_adp = _cur_adp(case)

    print(f"[{case}] start={start_adp:,}  family={family}", flush=True)

    args = dict(abc=ABC, benchmarks=BENCHMARKS, output=OUTPUT, logs=LOGS, root=ROOT)

    try:
        if family in ("mux_shannon", "monotone_general", "constant_mixed", "signed_mult"):
            # type-guided flows (respects fingerprint family)
            run_type_guided_refine_case(case, **args, timeout_per_case=300, max_flows=40)
            # objective-guided flows
            run_objective_guided_refine_case(case, **args, timeout_per_case=240,
                                              max_per_objective=8)
            # deepsyn from current AIG
            run_deepsyn_structural_case(case, **args, timeout_per_case=300,
                                         seed=0, iterations=8, search_seconds=120)
            run_deepsyn_structural_case(case, **args, timeout_per_case=300,
                                         seed=7, iterations=8, search_seconds=120)
            # area-first refinement
            run_area_first_refine_case(case, **args, timeout_per_case=240)
            # convergence loop
            run_convergence_loop_case(case, **args, timeout_per_case=180, max_passes=30)

        elif family == "general":
            # longer structural search
            run_long_large_structural_case(case, **args, timeout_per_case=600,
                                            seed=0, search_seconds=300, ttopt_rounds=3)
            run_deepsyn_structural_case(case, **args, timeout_per_case=600,
                                         seed=0, iterations=8, search_seconds=300)
            run_type_guided_refine_case(case, **args, timeout_per_case=300, max_flows=30)

    except Exception as exc:
        print(f"  [{case}] error: {exc}", flush=True)

    _rollback(case, backup, start_adp)
    final = _cur_adp(case)
    delta = start_adp - final
    tag = f"  *** IMPROVED +{delta:,} ***" if delta > 0 else ""
    print(f"[{case}] {start_adp:,} → {final:,}{tag}", flush=True)


def main() -> None:
    ref = _load_ref()

    # Only run cases that are still > 1.5x ref
    lagging = []
    for case in FAMILY:
        if not (OUTPUT / f"{case}.aig").is_file():
            continue
        adp = _cur_adp(case)
        r = ref.get(case, 0)
        if r and adp / r > 1.45:  # slight slack
            lagging.append(case)

    print(f"Lagging cases ({len(lagging)}): {lagging}", flush=True)
    print("Current state:", flush=True)
    for case in lagging:
        adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: adp={adp:,} ref={r:,} ratio={adp/r:.3f}", flush=True)
    print(flush=True)

    # Run larger cases sequentially, smaller ones in parallel
    large = [c for c in lagging if FAMILY.get(c) == "general"]
    small = [c for c in lagging if FAMILY.get(c) != "general"]

    # Small/medium: up to 4 parallel
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(boost_case, c): c for c in small}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)

    # Large cases: 2 parallel (they need more RAM/time)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(boost_case, c): c for c in large}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)

    # Final summary
    print("\n=== Final Summary ===", flush=True)
    total_gain = 0
    for case in lagging:
        adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: adp={adp:,} ref={r:,} ratio={adp/r:.3f}", flush=True)


if __name__ == "__main__":
    main()
