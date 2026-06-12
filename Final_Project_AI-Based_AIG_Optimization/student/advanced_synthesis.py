#!/usr/bin/env python3
"""Advanced per-case synthesis strategies.

Two modes:
  python3 student/advanced_synthesis.py --mode deepsyn
      Deep area optimisation via &my_deepsyn for hard cases.

  python3 student/advanced_synthesis.py --mode semantic [--case ex261|all]
      Specialised semantic BLIF generators for decoded high-ratio cases.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from abc_core import (
    PS_RE,
    is_equivalent,
    measure_adp,
    run_abc as _run_abc,
    run_abc_script,
)

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
OUTPUT = ROOT / "output"
ABC = ROOT / "student" / "abc"


# ---------------------------------------------------------------------------
# Mode 1: deep area optimisation (&my_deepsyn)
# ---------------------------------------------------------------------------

HARD_CASES = [
    ("ex286", 120), ("ex252", 120), ("ex261", 90), ("ex219", 90),
    ("ex297", 90),  ("ex250", 120), ("ex299", 120), ("ex264", 60),
    ("ex263", 60),  ("ex240", 60),  ("ex217", 60),  ("ex225", 90),
    ("ex247", 45),  ("ex248", 120), ("ex262", 45),  ("ex295", 60),
    ("ex223", 90),  ("ex224", 90),  ("ex246", 45),
    ("ex241", 120), ("ex242", 90),  ("ex251", 120), ("ex280", 120),
    ("ex281", 120), ("ex282", 120), ("ex283", 120), ("ex284", 120),
    ("ex287", 120),
]

SEEDS = [0, 7, 42]


def _run_abc_script_local(script: str, timeout: int = 180):
    return run_abc_script(ABC, script, timeout)


def _get_current_adp(case: str):
    aig = OUTPUT / f"{case}.aig"
    if not aig.exists():
        return None, None, float("inf")
    a, d = _run_abc_script_local(f'read_aiger "{aig}"\nprint_stats\n', 30)
    return a, d, (a * d) if a else float("inf")


def _check_pareto_dir(pareto_dir: Path, best_adp: float, case: str):
    import re
    best = best_adp
    best_file = None
    for pf in sorted(pareto_dir.glob("*.aig")):
        m = re.search(r'_(\d+)_(\d+)\.aig$', pf.name)
        if m:
            pd, pa = int(m.group(1)), int(m.group(2))
            padp = pa * pd
            if padp < best:
                best = padp
                best_file = str(pf)
                print(f"[{case}] pareto: {pa}x{pd}={padp:,} *** BEST ***", flush=True)
    return best, best_file


def _opt_case_deepsyn(case: str, run_timeout: int):
    truth = BENCH / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_a, cur_d, cur_adp = _get_current_adp(case)
    best_adp = cur_adp
    best_file = None

    print(f"[{case}] start: {cur_a}x{cur_d}={cur_adp:,}", flush=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        for seed in SEEDS:
            if truth.exists():
                for cost in ["area", "adp"]:
                    pareto_dir = tmp / f"p_tt_{seed}_{cost}"
                    pareto_dir.mkdir()
                    out_tmp = tmp / f"{case}_tt_{seed}_{cost}.aig"
                    script = (
                        f'read_truth -xf "{truth}"\n'
                        f'st; &get; &my_deepsyn -T {run_timeout} -I 8 -S {seed} '
                        f'-O "{pareto_dir}" -C {cost}; &put; '
                        f'write_aiger -s "{out_tmp}"\nprint_stats\n'
                    )
                    a, d = _run_abc_script_local(script, run_timeout + 30)
                    if a and d:
                        adp = a * d
                        tag = " *** BEST ***" if adp < best_adp else ""
                        if adp < best_adp:
                            best_adp = adp
                            best_file = str(out_tmp)
                        print(f"[{case}] tt seed={seed} {cost}: {a}x{d}={adp:,}{tag}", flush=True)
                    b, bf = _check_pareto_dir(pareto_dir, best_adp, case)
                    if b < best_adp:
                        best_adp = b
                        best_file = bf

            if aig.exists():
                for cost in ["area", "adp"]:
                    pareto_dir = tmp / f"p_aig_{seed}_{cost}"
                    pareto_dir.mkdir()
                    out_tmp = tmp / f"{case}_aig_{seed}_{cost}.aig"
                    script = (
                        f'read_aiger "{aig}"\n'
                        f'&get; &my_deepsyn -T {run_timeout} -I 8 -S {seed} '
                        f'-O "{pareto_dir}" -C {cost}; &put; '
                        f'write_aiger -s "{out_tmp}"\nprint_stats\n'
                    )
                    a, d = _run_abc_script_local(script, run_timeout + 30)
                    if a and d:
                        adp = a * d
                        tag = " *** BEST ***" if adp < best_adp else ""
                        if adp < best_adp:
                            best_adp = adp
                            best_file = str(out_tmp)
                        print(f"[{case}] aig seed={seed} {cost}: {a}x{d}={adp:,}{tag}", flush=True)
                    b, bf = _check_pareto_dir(pareto_dir, best_adp, case)
                    if b < best_adp:
                        best_adp = b
                        best_file = bf

        if best_file and best_adp < cur_adp and Path(best_file).exists():
            shutil.copy2(best_file, aig)
            pct = (1 - best_adp / cur_adp) * 100
            print(f"[{case}] IMPROVED {cur_adp:,} -> {best_adp:,} ({pct:.1f}%)", flush=True)
            return case, True, cur_adp, best_adp
        else:
            print(f"[{case}] no_improvement (best={best_adp:,})", flush=True)
            return case, False, cur_adp, best_adp


def run_deepsyn() -> None:
    print(f"Deep area opt: {len(HARD_CASES)} cases, 6 workers", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_opt_case_deepsyn, c, t): c for c, t in HARD_CASES}
        results = [f.result() for f in as_completed(futs)]
    print("\n=== SUMMARY ===", flush=True)
    improved_total = 0
    for case, improved, old, new in sorted(results, key=lambda x: x[0]):
        if improved:
            gain = old - new
            improved_total += gain
            print(f"  IMPROVED {case}: {old:,} -> {new:,} (saved {gain:,})", flush=True)
        else:
            print(f"  no_improvement {case}: {new:,}", flush=True)
    print(f"\nTotal ADP saved: {improved_total:,}", flush=True)
    print("Done.", flush=True)


# ---------------------------------------------------------------------------
# Mode 2: specialised semantic generators
# ---------------------------------------------------------------------------

from blif_builder import BlifBuilder, TruthTable, read_truth, emit_column_outputs, reduce_weighted_columns
from flow_library import PostFlow

SEMANTIC_FLOWS = [
    PostFlow("identity", "strash; balance"),
    PostFlow("area", "strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("resub", "strash; resub -K 6; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("gia", "strash; &get; &dc2; &compress3rs; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("delay", "strash; balance; rewrite; balance; refactor; balance"),
]


def _run_abc_cmd(command: str, timeout: int = 120) -> str:
    return _run_abc(ABC, command, timeout, cwd=ROOT)


def _measure(aig: Path) -> tuple[int, int, int]:
    return measure_adp(ABC, aig, 30, ROOT)


def _equivalent(case: str, aig: Path) -> bool:
    return is_equivalent(ABC, BENCH / f"{case}.truth", aig, 180, ROOT)


def _add_one_signed_5_to_6(builder: BlifBuilder, bits: list[str]) -> list[str]:
    extended = bits + [bits[-1]]
    result: list[str] = []
    carry = builder.const1
    for bit in extended:
        result.append(builder.emit_xor(bit, carry))
        carry = builder.emit_and(bit, carry)
    return result


def _emit_signed_product_bits(
    builder: BlifBuilder,
    a_bits: list[str],
    b_bits: list[str],
    output_count: int,
) -> list[str]:
    width = len(a_bits)
    columns: list[list[str]] = [[] for _ in range(output_count + 2 * width + 4)]
    for left, a_bit in enumerate(a_bits):
        for right, b_bit in enumerate(b_bits):
            columns[left + right].append(builder.emit_and(a_bit, b_bit))

    def add_conditional_twos_complement(control: str, bits: list[str], shift: int) -> None:
        for bit_index in range(output_count):
            source_index = bit_index - shift
            if 0 <= source_index < len(bits):
                columns[bit_index].append(builder.emit_and(control, builder.emit_not(bits[source_index])))
            else:
                columns[bit_index].append(control)
        columns[0].append(control)

    add_conditional_twos_complement(a_bits[-1], b_bits, width)
    add_conditional_twos_complement(b_bits[-1], a_bits, width)
    columns = reduce_weighted_columns(builder, columns)
    return emit_column_outputs(builder, columns, output_count)


def _write_ex261_blif(path: Path, table: TruthTable) -> None:
    builder = BlifBuilder(table, "ex261_biased_signed_product")
    high_lsb = [f"x{var}" for var in [4, 3, 2, 1, 0]]
    low_lsb = [f"x{var}" for var in [9, 8, 7, 6, 5]]
    high_plus = _add_one_signed_5_to_6(builder, high_lsb)
    low_plus = _add_one_signed_5_to_6(builder, low_lsb)
    outputs = _emit_signed_product_bits(builder, high_plus, low_plus, table.num_outputs)
    builder.finish(outputs, path)


def optimize_ex261() -> bool:
    case = "ex261"
    table = read_truth(BENCH / f"{case}.truth")
    current = OUTPUT / f"{case}.aig"
    cur_area, cur_delay, cur_adp = _measure(current)
    best = (cur_adp, cur_area, cur_delay, current, "current")

    with tempfile.TemporaryDirectory(prefix="specialized_ex261_") as tmp_name:
        tmp = Path(tmp_name)
        blif = tmp / "ex261_biased_signed_product.blif"
        _write_ex261_blif(blif, table)
        for flow in SEMANTIC_FLOWS:
            cand = tmp / f"ex261_{flow.name}.aig"
            try:
                _run_abc_cmd(f'read_blif "{blif}"; {flow.commands}; write_aiger -s "{cand}"', timeout=180)
                area, delay, adp = _measure(cand)
            except Exception as exc:
                print(f"[ex261] {flow.name}: error {exc}")
                continue
            print(f"[ex261] {flow.name}: area={area} delay={delay} adp={adp}")
            if adp < best[0] and _equivalent(case, cand):
                best = (adp, area, delay, cand, flow.name)

        if best[3] != current:
            shutil.copy2(best[3], current)
            print(
                f"[ex261] IMPROVED {cur_area}x{cur_delay}={cur_adp} "
                f"-> {best[1]}x{best[2]}={best[0]} via {best[4]}"
            )
            return True

    print(f"[ex261] kept current {cur_area}x{cur_delay}={cur_adp}")
    return False


def run_all_specialized_generators(case: str = "all") -> None:
    if case in {"ex261", "all"}:
        optimize_ex261()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["deepsyn", "semantic"], required=True,
                        help="deepsyn: run &my_deepsyn on hard cases; semantic: run specialised BLIF generators")
    parser.add_argument("--case", default="all",
                        help="(semantic mode only) which case to run: ex261 or all")
    args = parser.parse_args()

    if args.mode == "deepsyn":
        run_deepsyn()
    elif args.mode == "semantic":
        run_all_specialized_generators(args.case)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
