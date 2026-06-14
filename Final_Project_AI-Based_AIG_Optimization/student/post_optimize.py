#!/usr/bin/env python3
"""Post-optimization tools: flow refinement and advanced synthesis strategies.

Two subcommands:
  refine   -- parallel ABC flow search over cases above reference ADP, iterates
              until convergence, writes only CEC-verified strictly-better AIGs.
  advanced -- mode deepsyn: &my_deepsyn on a curated list of hard cases;
              mode semantic: specialised BLIF generators for decoded cases.

Usage:
  python3 student/post_optimize.py refine [--max-ratio 1.20] [--workers 4] [--cases ex231]
  python3 student/post_optimize.py advanced --mode deepsyn
  python3 student/post_optimize.py advanced --mode semantic [--case ex261]
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT      = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import (
    PS_RE,
    is_equivalent,
    measure_adp,
    measure_aig,
    run_abc as _run_abc,
    run_abc_script,
    verify_equivalence,
    resolve_reference_csv,
)
from blif_builder import BlifBuilder, TruthTable, read_truth, emit_column_outputs, reduce_weighted_columns
from flow_library import PostFlow

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"


# =============================================================================
# Section 1: Refine Close  (parallel ABC flow search)
# =============================================================================
ROOT      = Path(__file__).resolve().parent.parent
ABC       = ROOT / "student" / "abc"
OUTPUT    = ROOT / "output"
TMP       = Path(tempfile.gettempdir()) / "refine_close"



FLOWS = [
    ("resub4",          "resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("resub6",          "resub -K 6; balance; rewrite -z; refactor -z; balance"),
    ("resub8",          "resub -K 8; balance; rewrite -z; refactor -z; balance"),
    ("resub4x3",        "; ".join(["resub -K 4; balance; rewrite -z; refactor -z; balance"]*3)),
    ("resub6x2",        "; ".join(["resub -K 6; balance; rewrite -z; refactor -z; balance"]*2)),
    ("resub8_n2",       "resub -K 8 -N 2; balance; rewrite -z; refactor -z; balance"),
    ("resub6_f1",       "resub -K 6 -F 1; balance; rewrite -z; refactor -z; balance"),
    ("gia_can",         "&get; &put; strash; dc2; balance"),
    ("gia_can_x2",      "&get; &put; strash; dc2; balance; &get; &put; strash; dc2; balance"),
    ("gia_resyn2",      "&get; &resyn2; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3",      "&get; &resyn3; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_compress2rs", "&get; &compress2rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3rs",    "&get; &resyn3rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("dc2_loop",        "dc2; rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
    ("fraig_dc2",       "fraig; dc2; rewrite -z; refactor -z; balance"),
    ("dch_if4",         "dch; if -K 4; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6",         "dch; if -K 6; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("dch_if8",         "dch; if -K 8; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ("sopb_c8",         "&get; &sopb -C 8 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    ("sopb_c16",        "&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    ("b_ds",            "&get; &b -d -s; &put; balance; rewrite -z; refactor -z; balance"),
    ("mfs2",            "mfs2; dc2; balance; rewrite -z; refactor -z; balance"),
    ("resub4_gia",      "resub -K 4; balance; rewrite -z; refactor -z; balance; &get; &put; strash; dc2; balance"),
    ("gia_resub4",      "&get; &put; strash; dc2; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6_resub4",  "dch; if -K 6; strash; dc2; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
    ("dch_if6_resub6",  "dch; if -K 6; strash; dc2; balance; resub -K 6; balance; rewrite -z; refactor -z; balance"),
    ("compress2rs_lp",  "&get; &compress2rs; &put; dch; if -K 6; strash; dc2; balance"),
    ("resub4_compress", "resub -K 4; balance; &get; &compress2rs; &put; balance; rewrite -z; refactor -z; balance"),
    ("gia_resyn3_dch",  "&get; &resyn3; &put; dch; if -K 6; strash; dc2; balance"),
    ("resyn3rs_resub4", "&get; &resyn3rs; &put; balance; resub -K 4; balance; rewrite -z; refactor -z; balance"),
]

# deepsyn flows are handled separately (need per-case -O dir)
DEEPSYN_FLOWS = [
    ("deepsyn_s42", 42),
    ("deepsyn_s7",   7),
    ("deepsyn_s13", 13),
]

# ── helpers ────────────────────────────────────────────────────────────────────

def measure(p: str):
    return measure_aig(ABC, p)

def verify(truth: str, aig: str):
    return verify_equivalence(ABC, truth, aig)

def try_one_flow(case, fname, fflow, seed: str, truth: str, cur_adp: int, tid: int):
    """Run one flow against seed. Returns (fname, area, delay, adp, cand_path) or None."""
    cand = str(Path(tempfile.gettempdir()) / "post_optimize" / case / f"{fname}_{tid}.aig")
    try:
        r = subprocess.run([str(ABC), "-c",
                            f"read_aiger {seed}; {fflow}; write_aiger -s {cand}"],
                           capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if not Path(cand).exists():
        return None
    ca, cd = measure(cand)
    if ca is None:
        return None
    cadp = ca * cd
    if cadp >= cur_adp:
        return None
    return (fname, ca, cd, cadp, cand)

def try_deepsyn(case, fname, seed, cur_adp, tid):
    """Run &my_deepsyn with a fixed seed. Picks best Pareto AIG by ADP."""
    seed_n = int(fname.split("s")[-1])
    pareto_dir = Path(tempfile.gettempdir()) / "post_optimize" / case / f"ds_{tid}_s{seed_n}"
    pareto_dir.mkdir(exist_ok=True)
    cand = str(Path(tempfile.gettempdir()) / "post_optimize" / case / f"{fname}_{tid}.aig")
    try:
        subprocess.run([str(ABC), "-c",
                        f"read_aiger {seed}; &get; "
                        f"&my_deepsyn -I 1 -J 500 -T 25 -S {seed_n} -O {pareto_dir} -C area; "
                        f"&put; strash; dc2; balance; write_aiger -s {cand}"],
                       capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return None

    # also check Pareto frontier AIGs directly
    best_cadp = cur_adp
    best_cand = None
    for p in list(pareto_dir.glob("*.aig")) + ([Path(cand)] if Path(cand).exists() else []):
        ca, cd = measure(str(p))
        if ca is None: continue
        cadp = ca * cd
        if cadp < best_cadp:
            best_cadp = cadp
            best_cand = str(p)

    if best_cand is None:
        return None
    # copy best to cand path for uniform handling
    if Path(best_cand).resolve() != Path(cand).resolve():
        shutil.copy(best_cand, cand)
    ca, cd = measure(cand)
    if ca is None: return None
    return (fname, ca, cd, ca * cd, cand)

def optimize_case(case: str, ref_adp: int, workers: int, timeout: int) -> dict:
    case_tmp = Path(tempfile.gettempdir()) / "post_optimize" / case
    case_tmp.mkdir(exist_ok=True)

    truth = str(case_tmp / f"{case}.truth")
    shutil.copy(str(BENCHMARKS / f"{case}.truth"), truth)

    work = str(case_tmp / "work.aig")
    shutil.copy(str(OUTPUT / f"{case}.aig"), work)

    sa, sd = measure(work)
    start_adp  = sa * sd
    best_adp   = start_adp
    best_area  = sa
    best_delay = sd
    improved_flows = []

    round_n = 0
    improved = True
    while improved:
        improved = False
        round_n += 1
        candidates = []   # (adp, fname, area, delay, cand_path)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {
                ex.submit(try_one_flow, case, fn, ff, work, truth, best_adp, round_n * 1000 + i): (fn, ff)
                for i, (fn, ff) in enumerate(FLOWS)
            }
            # add deepsyn flows
            for j, (dfname, _) in enumerate(DEEPSYN_FLOWS):
                futs[ex.submit(try_deepsyn, case, dfname, work, best_adp, round_n * 1000 + len(FLOWS) + j)] = (dfname, "")
            for fut in as_completed(futs):
                res = fut.result()
                if res is None:
                    continue
                fn, ca, cd, cadp, cand_path = res
                candidates.append((cadp, fn, ca, cd, cand_path))

        # sort by ADP, verify best-first
        candidates.sort(key=lambda x: x[0])
        for cadp, fn, ca, cd, cand_path in candidates:
            if cadp >= best_adp:
                break
            if verify(truth, cand_path):
                best_adp   = cadp
                best_area  = ca
                best_delay = cd
                shutil.copy(cand_path, work)
                improved_flows.append(f"[r{round_n}] {fn}: area={ca} delay={cd} adp={cadp}")
                improved = True
                break   # restart with new best as seed

    return {
        "case":         case,
        "start_adp":    start_adp,
        "best_adp":     best_adp,
        "best_area":    best_area,
        "best_delay":   best_delay,
        "ref_adp":      ref_adp,
        "ratio":        best_adp / ref_adp,
        "flows":        improved_flows,
        "work":         work,
        "improved":     best_adp < start_adp,
        "beats_ref":    best_adp < ref_adp,
    }

# ── main ───────────────────────────────────────────────────────────────────────

def _cmd_refine():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-ratio", type=float, default=1.20,
                    help="Only target cases with ratio <= this value (default 1.20)")
    ap.add_argument("--workers",   type=int,   default=4,
                    help="Parallel ABC processes per case (default 4)")
    ap.add_argument("--case-workers", type=int, default=8,
                    help="How many cases to run in parallel (default 8)")
    ap.add_argument("--timeout",   type=int,   default=60,
                    help="(reserved) per-flow timeout seconds")
    ap.add_argument("--cases",     nargs="*",
                    help="Explicit list of cases to run (e.g. ex231 ex227)")
    args = ap.parse_args()

    # Load reference
    ref = {}
    with open(str(REF_CSV)) as f:
        for row in csv.DictReader(f):
            ref[row["case"]] = int(row["adp"])

    # Measure current output ADP after copying each AIG to a temp path to avoid
    # shell/path issues in directories that contain spaces.
    current = {}
    for case in sorted(ref):
        aig = OUTPUT / f"{case}.aig"
        if not aig.exists():
            continue
        tmp_aig = str(Path(tempfile.gettempdir()) / "post_optimize" / f"measure_{case}.aig")
        shutil.copy(str(aig), tmp_aig)
        a, d = measure(tmp_aig)
        if a:
            current[case] = a * d

    # Select targets
    if args.cases:
        targets = {c: ref[c] for c in args.cases if c in ref and c in current}
    else:
        targets = {c: ref[c] for c in sorted(ref)
                   if c in current and 1.0 < current[c] / ref[c] <= args.max_ratio}

    print(f"Targeting {len(targets)} cases (ratio 1.0-{args.max_ratio}x, {args.workers} workers/case)")
    print(f"{'Case':<8} {'Start':>8} {'Best':>8} {'Ref':>8} {'Ratio':>7}  Flows used")
    print("-" * 75)

    results = []
    # Run cases in parallel (case_workers cases at a time, each with args.workers flow threads)
    case_list = sorted(targets.items(), key=lambda x: current[x[0]] / x[1])
    with ThreadPoolExecutor(max_workers=args.case_workers) as ex:
        futs = {ex.submit(optimize_case, case, ref_adp, args.workers, args.timeout): case
                for case, ref_adp in case_list}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            marker = " < BEATS" if r["beats_ref"] else ("" if not r["improved"] else " improved")
            print(f"{r['case']:<8} {r['start_adp']:>8} {r['best_adp']:>8} {r['ref_adp']:>8} {r['ratio']:>7.4f}{marker}")
            for fl in r["flows"]:
                print(f"         {fl}")
            sys.stdout.flush()

    # Write improvements to output/
    print()
    written = []
    for r in results:
        if r["improved"]:
            dst = OUTPUT / f"{r['case']}.aig"
            shutil.copy(r["work"], str(dst))
            written.append(r["case"])
            print(f"  Updated output/{r['case']}.aig  adp {r['start_adp']} -> {r['best_adp']}"
                  f"  (ref={r['ref_adp']}  ratio={r['ratio']:.4f})")

    if not written:
        print("  No improvements found.")

    print(f"\nDone. {len(written)} case(s) updated in output/")
    beats = [r["case"] for r in results if r["beats_ref"]]
    if beats:
        print(f"Cases now beating reference: {beats}")

# =============================================================================
# Section 2: Advanced Synthesis  (deepsyn + semantic generators)
# =============================================================================


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

def _cmd_advanced() -> int:
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


# =============================================================================
# Combined CLI
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_r = sub.add_parser("refine", help="parallel flow refinement")
    p_r.add_argument("--max-ratio", type=float, default=1.20)
    p_r.add_argument("--workers",     type=int,   default=4)
    p_r.add_argument("--case-workers",type=int,   default=8)
    p_r.add_argument("--timeout",     type=int,   default=60)
    p_r.add_argument("--cases",       nargs="*")

    p_a = sub.add_parser("advanced", help="deepsyn / semantic strategies")
    p_a.add_argument("--mode", choices=["deepsyn", "semantic"], required=True)
    p_a.add_argument("--case", default="all")

    args = ap.parse_args()
    if args.cmd == "refine":
        return _cmd_refine(args)
    return _cmd_advanced(args)


if __name__ == "__main__":
    raise SystemExit(main())
