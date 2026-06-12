#!/usr/bin/env python3
"""Full-sweep optimizer: runs every available strategy on every case.

Strategy per case (all have per-case rollback):
  Pass A  – broad ABC flow suite (syn2/syn3/dch/dc2/rwz variants) [all cases]
  Pass B  – type-guided + objective-guided refine [all cases]
  Pass C  – mockturtle structural [all cases]
  Pass D  – convergence loop [all cases]
  Pass E  – deepsyn structural (area-gated) [cases area >= 500]
  Pass F  – long deepsyn (cases still > 1.2x ref AND area >= 2000)

All passes write to output/ only if strictly better AND equivalent.
"""
from __future__ import annotations

import csv, shutil, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script
from case_runners import (
    run_type_guided_refine_case,
    run_objective_guided_refine_case,
    run_mockturtle_structural_case,
    run_convergence_loop_case,
    run_deepsyn_structural_case,
    run_pareto_area_structural_case,
    run_long_large_structural_case,
)

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"
LOGS       = ROOT / "student" / "logs"
MOCKTURTLE = ROOT / "student" / "mockturtle_opt" / "mockturtle_opt"
LOGS.mkdir(parents=True, exist_ok=True)

ALL_CASES = [f"ex{i}" for i in range(200, 300)]

ARGS = dict(abc=ABC, benchmarks=BENCHMARKS, output=OUTPUT, logs=LOGS, root=ROOT)


def _load_ref() -> dict[str, int]:
    ref: dict[str, int] = {}
    p = ROOT / "reference_result.csv"
    if p.exists():
        with open(p) as f:
            for row in csv.DictReader(f):
                ref[row["case"]] = int(row["adp"])
    return ref


def _adp(case: str) -> int:
    return measure_adp(ABC, OUTPUT / f"{case}.aig", 60, ROOT)[2]


def _area(case: str) -> int:
    return measure_adp(ABC, OUTPUT / f"{case}.aig", 60, ROOT)[0]


def _replace_if_better(case: str, candidate: Path, backup: Path) -> bool:
    try:
        _, _, cand_adp = measure_adp(ABC, candidate, 30, ROOT)
        _, _, cur_adp  = measure_adp(ABC, OUTPUT / f"{case}.aig", 30, ROOT)
        if cand_adp and cur_adp and cand_adp < cur_adp:
            truth = BENCHMARKS / f"{case}.truth"
            if is_equivalent(ABC, truth, candidate, 120, ROOT):
                shutil.copyfile(candidate, OUTPUT / f"{case}.aig")
                print(f"  [{case}] {cur_adp:,} → {cand_adp:,}  *** IMPROVED ***", flush=True)
                return True
    except Exception as exc:
        print(f"  [{case}] replace error: {exc}", flush=True)
    return False


def pass_a_flows(case: str) -> bool:
    """Run broad ABC synthesis flow suite on existing AIG."""
    import tempfile
    aig = OUTPUT / f"{case}.aig"
    improved = False
    backup = LOGS / f"sweep_a_{case}.aig"
    shutil.copyfile(aig, backup)

    flows = [
        ("dc2x3",      "dc2; dc2; dc2; balance"),
        ("rwz_rfz",    "rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
        ("syn2",       "&get; &syn2 -J 8; &put; balance"),
        ("syn3",       "&get; &syn3; &put; balance"),
        ("dch",        "&get; &dch; &put; balance"),
        ("dc2_syn2",   "dc2; &get; &syn2 -J 8; &put; dc2; balance"),
        ("rwz_syn2",   "rewrite -z; refactor -z; &get; &syn2 -J 8; &put; balance"),
        ("b_dc2_b",    "balance; dc2; balance; rewrite -z; balance"),
        ("resub_dc2",  "resub -K 8; dc2; rewrite -z; balance"),
        ("fraig_dc2",  "fraig; dc2; rewrite -z; balance"),
        ("dch_syn2",   "&get; &dch; &syn2 -J 8; &put; balance"),
        ("if6_balance","&get; &if -K 6 -a; &put; balance"),
    ]

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for fname, fcmds in flows:
            cand = tmp / f"{case}_a_{fname}.aig"
            try:
                run_abc_script(
                    ABC,
                    f'read_aiger "{aig}"; {fcmds}; write_aiger -s "{cand}"',
                    90,
                )
                if _replace_if_better(case, cand, backup):
                    improved = True
                    aig = OUTPUT / f"{case}.aig"  # re-read updated path
            except Exception:
                pass

    if measure_adp(ABC, OUTPUT / f"{case}.aig", 30, ROOT)[2] > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
    return improved


def pass_b_guided(case: str) -> bool:
    """Type-guided + objective-guided refinement."""
    start = _adp(case)
    backup = LOGS / f"sweep_b_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_type_guided_refine_case(case, **ARGS, timeout_per_case=180, max_flows=30)
        run_objective_guided_refine_case(case, **ARGS, timeout_per_case=120, max_per_objective=8)
    except Exception as exc:
        print(f"  [{case}] pass_b error: {exc}", flush=True)
    final = _adp(case)
    if final > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return False
    return final < start


def pass_c_mockturtle(case: str) -> bool:
    """Mockturtle structural optimization."""
    if not MOCKTURTLE.is_file():
        return False
    start = _adp(case)
    backup = LOGS / f"sweep_c_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_mockturtle_structural_case(
            case, **ARGS,
            timeout_per_case=240,
            mockturtle_bin=MOCKTURTLE,
            max_modes=4,
            exact_max_inputs=12,
        )
    except Exception as exc:
        print(f"  [{case}] pass_c error: {exc}", flush=True)
    final = _adp(case)
    if final > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return False
    return final < start


def pass_d_convergence(case: str) -> bool:
    """Polish with convergence loop."""
    start = _adp(case)
    backup = LOGS / f"sweep_d_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_convergence_loop_case(case, **ARGS, timeout_per_case=180, max_passes=40)
    except Exception as exc:
        print(f"  [{case}] pass_d error: {exc}", flush=True)
    final = _adp(case)
    if final > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return False
    return final < start


def pass_e_deepsyn(case: str, ref_adp: int) -> bool:
    """Deepsyn structural for medium/large cases."""
    area = _area(case)
    if area < 500:
        return False
    start = _adp(case)
    backup = LOGS / f"sweep_e_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_deepsyn_structural_case(
            case, **ARGS,
            timeout_per_case=300,
            seed=0, iterations=8, search_seconds=120,
        )
        run_deepsyn_structural_case(
            case, **ARGS,
            timeout_per_case=300,
            seed=7, iterations=8, search_seconds=120,
        )
    except Exception as exc:
        print(f"  [{case}] pass_e error: {exc}", flush=True)
    final = _adp(case)
    if final > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return False
    return final < start


def pass_f_long_deepsyn(case: str, ref_adp: int) -> bool:
    """Long deepsyn for large cases still > 1.2x ref."""
    area = _area(case)
    cur = _adp(case)
    if area < 2000:
        return False
    if ref_adp and cur / ref_adp < 1.2:
        return False
    start = cur
    backup = LOGS / f"sweep_f_{case}.aig"
    shutil.copyfile(OUTPUT / f"{case}.aig", backup)
    try:
        run_long_large_structural_case(
            case, **ARGS,
            timeout_per_case=480,
            seed=0, search_seconds=300, ttopt_rounds=2,
        )
    except Exception as exc:
        print(f"  [{case}] pass_f error: {exc}", flush=True)
    final = _adp(case)
    if final > measure_adp(ABC, backup, 30, ROOT)[2]:
        shutil.copyfile(backup, OUTPUT / f"{case}.aig")
        return False
    return final < start


def optimize_case(case: str, ref_adp: int) -> dict:
    start = _adp(case)
    r = ref_adp or 1
    print(f"[{case}] start={start:,}  ratio={start/r:.3f}x", flush=True)

    any_improved = False

    _r = ref_adp
    for pass_fn, label in [
        (lambda c: pass_a_flows(c),         "A:flows"),
        (lambda c: pass_b_guided(c),        "B:guided"),
        (lambda c: pass_c_mockturtle(c),    "C:mockturtle"),
        (lambda c: pass_d_convergence(c),   "D:convergence"),
        (lambda c: pass_e_deepsyn(c, _r),   "E:deepsyn"),
        (lambda c: pass_f_long_deepsyn(c, _r), "F:long_deepsyn"),
    ]:
        try:
            if pass_fn(case):
                any_improved = True
                cur = _adp(case)
                print(f"  [{case}] {label} improved → {cur:,}", flush=True)
        except Exception as exc:
            print(f"  [{case}] {label} ERROR: {exc}", flush=True)

    final = _adp(case)
    delta = start - final
    tag = f"  TOTAL GAIN={delta:,}" if delta > 0 else "  no gain"
    print(f"[{case}] {start:,} → {final:,}{tag}", flush=True)
    return {"case": case, "start": start, "final": final}


def main() -> None:
    ref = _load_ref()

    cases = [c for c in ALL_CASES if (OUTPUT / f"{c}.aig").is_file()]
    print(f"Sweeping {len(cases)} cases...", flush=True)

    # Sort: lagging cases first (highest priority), then by ratio desc
    def priority(c):
        adp = _adp(c)
        r = ref.get(c, 1)
        return -(adp / r)

    cases_sorted = sorted(cases, key=priority)

    # Use 6 workers for small/medium cases; large cases (ex297, ex299) need fewer
    large = {"ex297", "ex299", "ex226", "ex206", "ex220", "ex221", "ex222", "ex230"}
    small_cases = [c for c in cases_sorted if c not in large]
    large_cases = [c for c in cases_sorted if c in large]

    total_start = sum(_adp(c) for c in cases)
    print(f"Total ADP start: {total_start:,}", flush=True)

    results = []
    # Small/medium: 6 parallel workers
    with ThreadPoolExecutor(max_workers=6) as pool:
        futs = {pool.submit(optimize_case, c, ref.get(c, 0)): c for c in small_cases}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)

    # Large: 2 parallel workers
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(optimize_case, c, ref.get(c, 0)): c for c in large_cases}
        for f in as_completed(futs):
            try:
                results.append(f.result())
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)

    # Final summary
    total_final = sum(_adp(c) for c in cases)
    improved = [r for r in results if r["final"] < r["start"]]
    print(f"\n=== SUMMARY ===")
    print(f"Total ADP: {total_start:,} → {total_final:,}  (saved {total_start - total_final:,})")
    print(f"Improved cases: {len(improved)}/{len(cases)}")
    for r in sorted(improved, key=lambda x: x["start"] - x["final"], reverse=True):
        ratio = r["final"] / ref.get(r["case"], 1)
        print(f"  {r['case']}: {r['start']:,} → {r['final']:,}  (ratio={ratio:.3f}x)")


if __name__ == "__main__":
    main()
