#!/usr/bin/env python3
"""Use mockturtle to boost lagging cases."""
import sys, shutil, subprocess, csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp
from case_runners import run_mockturtle_structural_case

ABC           = ROOT / "student" / "abc"
BENCHMARKS    = ROOT / "benchmarks"
OUTPUT        = ROOT / "output"
LOGS          = ROOT / "student" / "logs"
MOCKTURTLE    = ROOT / "student" / "mockturtle_opt" / "mockturtle_opt"
LOGS.mkdir(parents=True, exist_ok=True)

# All lagging cases
LAGGING = [
    "ex223", "ex224", "ex225",
    "ex240", "ex246", "ex247", "ex248", "ex250",
    "ex252", "ex262", "ex263", "ex264", "ex286",
    "ex295", "ex297", "ex299",
]


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


def boost_mockturtle(case: str) -> None:
    aig = OUTPUT / f"{case}.aig"
    backup = LOGS / f"boost_mt_backup_{case}.aig"
    shutil.copyfile(aig, backup)
    start = _cur_adp(case)
    print(f"[{case}] start={start:,}", flush=True)

    try:
        rows = run_mockturtle_structural_case(
            case, ABC, BENCHMARKS, OUTPUT, LOGS,
            timeout_per_case=300,
            root=ROOT,
            mockturtle_bin=MOCKTURTLE,
            max_modes=4,
            exact_max_inputs=12,
        )
        final = _cur_adp(case)
        delta = start - final
        tag = f"  *** IMPROVED +{delta:,} ***" if delta > 0 else ""
        print(f"[{case}] {start:,} → {final:,}{tag}", flush=True)
    except Exception as exc:
        print(f"[{case}] ERROR: {exc}", flush=True)
        # rollback
        shutil.copyfile(backup, aig)


def main() -> None:
    if not MOCKTURTLE.is_file():
        print(f"ERROR: mockturtle_opt not found at {MOCKTURTLE}")
        return

    ref = _load_ref()
    lagging = [c for c in LAGGING if (OUTPUT / f"{c}.aig").is_file()]
    print(f"Running mockturtle on {len(lagging)} cases...", flush=True)

    # Print current state
    print("Current state:", flush=True)
    for case in lagging:
        adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: {adp:,} / {r:,} = {adp/r:.3f}x", flush=True)
    print(flush=True)

    # small cases parallel, large sequential
    small = [c for c in lagging if c not in ("ex297", "ex299")]
    large = [c for c in lagging if c in ("ex297", "ex299")]

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(boost_mockturtle, c): c for c in small}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)

    for case in large:
        boost_mockturtle(case)

    print("\n=== Final ===", flush=True)
    for case in lagging:
        adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: {adp:,} / {r:,} = {adp/r:.3f}x", flush=True)


if __name__ == "__main__":
    main()
