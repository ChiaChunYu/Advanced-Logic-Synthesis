#!/usr/bin/env python3
"""Targeted boost for cases lagging > 1.5x reference ADP.

Three sub-passes, each with per-case rollback so they cannot hurt existing results:
  C1 – signed-multiplier template + CSA seed (for ex262/263/264 etc.)
  C2 – deepsyn for small/medium cases (area 500-2000) that the main pass skipped
  C3 – longer deepsyn (300 s) for large cases (area >= 10000) still > 1.5x

Usage (run from project root):
    python3 student/targeted_boost.py
"""
from __future__ import annotations

import csv
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script
from blif_builder import read_truth
from exact_function_recognition import detect_signed_multiplier
from blif_builder import (
    write_signed_multiplier_blif,
    write_signed_multiplier_csa_blif,
)
from case_runners import run_pareto_area_structural_case, run_convergence_loop_case

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
ALL_CASES  = [f"ex{i}" for i in range(200, 300)]

LOGS.mkdir(parents=True, exist_ok=True)


def _load_ref() -> dict[str, int]:
    ref: dict[str, int] = {}
    csv_path = ROOT / "reference_result.csv"
    if csv_path.exists():
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def _cur_adp(case: str) -> tuple[int, int, int]:
    return measure_adp(ABC, OUTPUT / f"{case}.aig", 60, ROOT)


def _ratio(case: str, ref: dict[str, int]) -> float:
    r = ref.get(case, 0)
    if not r:
        return 0.0
    _, _, adp = _cur_adp(case)
    return adp / r if adp else 999.0


def _safe_replace(case: str, candidate: Path) -> bool:
    """Replace output only if candidate is strictly better and equivalent."""
    try:
        _, _, cand_adp = measure_adp(ABC, candidate, 30, ROOT)
        _, _, cur_adp  = _cur_adp(case)
        if cand_adp and cand_adp < cur_adp:
            if is_equivalent(ABC, BENCHMARKS / f"{case}.truth", candidate, 120, ROOT):
                shutil.copyfile(candidate, OUTPUT / f"{case}.aig")
                print(f"  [{case}] {cur_adp:,} → {cand_adp:,}  *** IMPROVED ***", flush=True)
                return True
    except Exception as exc:
        print(f"  [{case}] error: {exc}", flush=True)
    return False


def run_c1_signed_mult(lagging: list[str]) -> None:
    """C1: signed-multiplier template + CSA blif seeds."""
    print("\n=== C1: signed-multiplier template ===", flush=True)
    for case in lagging:
        table = read_truth(BENCHMARKS / f"{case}.truth")
        orders = detect_signed_multiplier(table)
        if orders is None:
            continue
        a_order, b_order = orders
        print(f"  [{case}] signed_mult detected, trying templates...", flush=True)
        backup = LOGS / f"boost_c1_backup_{case}.aig"
        shutil.copyfile(OUTPUT / f"{case}.aig", backup)

        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            for blif_name, write_fn in [
                ("signed_mult",     write_signed_multiplier_blif),
                ("signed_mult_csa", write_signed_multiplier_csa_blif),
            ]:
                blif = tmp / f"{case}_{blif_name}.blif"
                write_fn(blif, f"{case}_{blif_name}", table, a_order, b_order)
                for flow_name, flow_cmds in [
                    ("balance",  "balance"),
                    ("dc2",      "strash; dc2; balance"),
                    ("rw_rf",    "strash; rewrite -z; refactor -z; dc2; balance"),
                    ("resub",    "strash; resub -K 6; rewrite -z; refactor -z; dc2; balance"),
                    ("deep",     "strash; dc2; rewrite -z; refactor -z; dc2; rewrite -z; balance"),
                ]:
                    cand = tmp / f"{case}_{blif_name}_{flow_name}.aig"
                    try:
                        run_abc_script(
                            ABC,
                            f'read_blif "{blif}"; {flow_cmds}; write_aiger -s "{cand}"',
                            180,
                        )
                        _safe_replace(case, cand)
                    except Exception:
                        pass

        # rollback if ended up worse
        try:
            _, _, new_adp = _cur_adp(case)
            _, _, bak_adp = measure_adp(ABC, backup, 30, ROOT)
            if new_adp > bak_adp:
                shutil.copyfile(backup, OUTPUT / f"{case}.aig")
                print(f"  [{case}] C1 rolled back", flush=True)
        except Exception:
            pass


def _run_deepsyn_direct(case: str, seconds: int, seeds: list[int]) -> bool:
    """Run &my_deepsyn directly on a case, from truth table and existing AIG.
    Returns True if output was improved."""
    truth = BENCHMARKS / f"{case}.truth"
    aig   = OUTPUT / f"{case}.aig"
    backup = LOGS / f"boost_deepsyn_backup_{case}.aig"
    shutil.copyfile(aig, backup)

    _, _, best_adp = _cur_adp(case)
    improved = False

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for seed in seeds:
            for cost in ["area", "adp"]:
                for src_name, src_cmd in [
                    ("tt",  f'read_truth -xf "{truth}"; st'),
                    ("aig", f'read_aiger "{aig}"'),
                ]:
                    pareto = tmp / f"p_{seed}_{cost}_{src_name}"
                    pareto.mkdir()
                    out = tmp / f"{case}_{seed}_{cost}_{src_name}.aig"
                    try:
                        run_abc_script(
                            ABC,
                            f'{src_cmd}; &get; &my_deepsyn -T {seconds} -I 8 -S {seed} '
                            f'-O "{pareto}" -C {cost}; &put; write_aiger -s "{out}"',
                            seconds + 30,
                        )
                    except Exception:
                        pass
                    for f in list(pareto.glob("*.aig")) + ([out] if out.exists() else []):
                        if _safe_replace(case, f):
                            _, _, best_adp = _cur_adp(case)
                            improved = True

    # rollback if somehow worse (shouldn't happen due to _safe_replace, but safety net)
    try:
        _, _, new_adp = _cur_adp(case)
        _, _, bak_adp = measure_adp(ABC, backup, 30, ROOT)
        if new_adp > bak_adp:
            shutil.copyfile(backup, aig)
            print(f"  [{case}] deepsyn rolled back", flush=True)
            return False
    except Exception:
        pass
    return improved


def run_c2_small_deepsyn(lagging: list[str]) -> None:
    """C2: &my_deepsyn directly for small/medium cases (area 500-2000) skipped by pass2."""
    print("\n=== C2: small/medium direct deepsyn (area 500-2000) ===", flush=True)
    c2_cases = []
    for case in lagging:
        area, _, _ = _cur_adp(case)
        if area and 500 <= area < 2000:
            c2_cases.append(case)
    print(f"  cases: {c2_cases}", flush=True)

    def _run(case: str) -> None:
        improved = _run_deepsyn_direct(case, seconds=120, seeds=[0, 7, 42])
        _, _, adp = _cur_adp(case)
        tag = " *** IMPROVED ***" if improved else ""
        print(f"  [{case}] C2 done: adp={adp:,}{tag}", flush=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_run, c): c for c in c2_cases}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"  C2 ERROR: {exc}", flush=True)


def run_c3_large_deepsyn(ref: dict[str, int]) -> None:
    """C3: &my_deepsyn (300 s) for large cases (area >= 10000) still > 1.5x."""
    print("\n=== C3: large case long deepsyn (area >= 10000, ratio > 1.5) ===", flush=True)
    c3_cases = []
    for case in ALL_CASES:
        if not (OUTPUT / f"{case}.aig").is_file():
            continue
        area, _, _ = _cur_adp(case)
        if area and area >= 10000 and _ratio(case, ref) > 1.5:
            c3_cases.append(case)
    print(f"  cases: {c3_cases}", flush=True)

    def _run(case: str) -> None:
        improved = _run_deepsyn_direct(case, seconds=300, seeds=[0, 7, 42])
        # also polish with convergence
        run_convergence_loop_case(
            case, ABC, BENCHMARKS, OUTPUT, LOGS,
            timeout_per_case=180, root=ROOT, max_passes=20,
        )
        _, _, adp = _cur_adp(case)
        tag = " *** IMPROVED ***" if improved else ""
        print(f"  [{case}] C3 done: adp={adp:,}{tag}", flush=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(_run, c): c for c in c3_cases}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"  C3 ERROR: {exc}", flush=True)


def main() -> None:
    ref = _load_ref()

    lagging = [
        c for c in ALL_CASES
        if (OUTPUT / f"{c}.aig").is_file() and _ratio(c, ref) > 1.5
    ]
    print(f"Cases with ratio > 1.5 ({len(lagging)}): {lagging}", flush=True)

    # Print current state
    print("\nCurrent state:", flush=True)
    for case in lagging:
        _, _, adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: adp={adp:,}  ref={r:,}  ratio={adp/r:.3f}", flush=True)

    run_c1_signed_mult(lagging)
    run_c2_small_deepsyn(lagging)
    run_c3_large_deepsyn(ref)

    # Final summary
    print("\n=== Final summary ===", flush=True)
    total_improvement = 0
    for case in lagging:
        _, _, adp = _cur_adp(case)
        r = ref.get(case, 0)
        print(f"  {case}: adp={adp:,}  ref={r:,}  ratio={adp/r:.3f}", flush=True)
        total_improvement += adp
    print(f"\nTotal ADP of boosted cases: {total_improvement:,}", flush=True)


if __name__ == "__main__":
    main()
