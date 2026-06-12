#!/usr/bin/env python3
"""Quick test of refinement functions on small lagging cases."""
import sys, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import measure_adp
from case_runners import (
    run_type_guided_refine_case,
    run_deepsyn_structural_case,
    run_objective_guided_refine_case,
    run_area_first_refine_case,
    run_convergence_loop_case,
)

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

CASES = ["ex246", "ex247", "ex248", "ex262"]  # Small cases first

for case in CASES:
    aig = OUTPUT / f"{case}.aig"
    backup = LOGS / f"test_refiner_{case}.aig"
    shutil.copyfile(aig, backup)

    start_adp = measure_adp(ABC, aig, 60, ROOT)[2]
    print(f"\n[{case}] start={start_adp:,}", flush=True)

    args = dict(abc=ABC, benchmarks=BENCHMARKS, output=OUTPUT, logs=LOGS, root=ROOT)

    try:
        run_type_guided_refine_case(case, **args, timeout_per_case=120, max_flows=20)
        adp1 = measure_adp(ABC, aig, 60, ROOT)[2]
        print(f"  after type_guided: {adp1:,}", flush=True)

        run_deepsyn_structural_case(case, **args, timeout_per_case=120,
                                     seed=0, iterations=4, search_seconds=60)
        adp2 = measure_adp(ABC, aig, 60, ROOT)[2]
        print(f"  after deepsyn: {adp2:,}", flush=True)

        run_objective_guided_refine_case(case, **args, timeout_per_case=120, max_per_objective=6)
        adp3 = measure_adp(ABC, aig, 60, ROOT)[2]
        print(f"  after objective_guided: {adp3:,}", flush=True)

    except Exception as e:
        print(f"  ERROR: {e}", flush=True)

    final = measure_adp(ABC, aig, 60, ROOT)[2]
    if final < start_adp:
        print(f"  IMPROVED: {start_adp:,} → {final:,}  (saved {start_adp-final:,})", flush=True)
    else:
        shutil.copyfile(backup, aig)
        print(f"  no improvement, restored {start_adp:,}", flush=True)
