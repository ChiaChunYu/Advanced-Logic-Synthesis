#!/usr/bin/env python3
"""Aggressive optimization for the hardest cases (ex252, ex286) and medium hard ones.

Strategy: try &syn2, &if, &dc2, &dch on existing AIG and from truth table.
"""
import sys, subprocess, tempfile, shutil, re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp

ABC = ROOT / "student" / "abc"
OUTPUT = ROOT / "output"
BENCHMARKS = ROOT / "benchmarks"
LOGS = ROOT / "student" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

CASES = [
    "ex252", "ex286",       # worst ratio
    "ex240", "ex247", "ex250",  # monotone_general
    "ex246", "ex248",       # mux_shannon small
    "ex262", "ex263", "ex264",  # signed_mult
]


def run_abc_f(script: str, timeout: int) -> str:
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    try:
        r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout + 5)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return ""


def get_adp(path: Path) -> tuple[int, int, int]:
    return measure_adp(ABC, path, 30, ROOT)


def try_replace(case: str, candidate: Path) -> bool:
    """Replace output if candidate is better AND equivalent."""
    try:
        _, _, cand_adp = get_adp(candidate)
        _, _, cur_adp = get_adp(OUTPUT / f"{case}.aig")
        if cand_adp and cand_adp < cur_adp:
            truth = BENCHMARKS / f"{case}.truth"
            if is_equivalent(ABC, truth, candidate, 120, ROOT):
                shutil.copyfile(candidate, OUTPUT / f"{case}.aig")
                print(f"  [{case}] {cur_adp:,} → {cand_adp:,}  *** IMPROVED ***", flush=True)
                return True
    except Exception as exc:
        print(f"  [{case}] replace error: {exc}", flush=True)
    return False


def optimize_case(case: str) -> None:
    aig = OUTPUT / f"{case}.aig"
    truth = BENCHMARKS / f"{case}.truth"
    backup = LOGS / f"boost_hard_backup_{case}.aig"
    shutil.copyfile(aig, backup)

    _, _, start_adp = get_adp(aig)
    print(f"[{case}] start ADP={start_adp:,}", flush=True)

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)

        # All synthesis scripts to try (source_name, src_cmd, flow_name, flow_cmds)
        flows = []

        # From existing AIG
        for fname, fcmds in [
            ("dc2x3",     "dc2; dc2; dc2; balance"),
            ("rwz_rfz",   "rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
            ("syn2",      "&get; &syn2 -J 8; &put; balance"),
            ("syn3",      "&get; &syn3; &put; balance"),
            ("dch",       "&get; &dch; &put; balance"),
            ("if6",       "&get; &if -K 6 -a; &put; balance"),
            ("if8",       "&get; &if -K 8 -a; &put; balance"),
            ("dc2_syn2",  "dc2; &get; &syn2 -J 8; &put; dc2; balance"),
            ("rwz_syn2",  "rewrite -z; refactor -z; &get; &syn2 -J 8; &put; balance"),
            ("b_dc2_b",   "balance; dc2; balance; rewrite -z; balance"),
        ]:
            flows.append(("aig", f'read_aiger "{aig}"', fname, fcmds))

        # From truth table
        for fname, fcmds in [
            ("st_dc2",    "st; dc2; balance"),
            ("st_syn2",   "st; &get; &syn2 -J 8; &put; balance"),
            ("st_dc2_syn2", "st; dc2; &get; &syn2 -J 8; &put; balance"),
            ("st_rwz",    "st; rewrite -z; refactor -z; dc2; balance"),
        ]:
            flows.append(("tt", f'read_truth -xf "{truth}"', fname, fcmds))

        improved_this_round = True
        while improved_this_round:
            improved_this_round = False
            for src_name, src_cmd, fname, fcmds in flows:
                # re-read current best AIG for AIG-sourced flows
                if src_name == "aig":
                    src_cmd = f'read_aiger "{aig}"'

                out = tmp / f"{case}_{src_name}_{fname}.aig"
                script = f'{src_cmd}; {fcmds}; write_aiger -s "{out}"'
                try:
                    run_abc_f(script, 90)
                    if out.exists():
                        if try_replace(case, out):
                            improved_this_round = True
                            out.unlink(missing_ok=True)
                except Exception as exc:
                    print(f"  [{case}] {fname} error: {exc}", flush=True)

            # Also try deepsyn (only if case still large enough)
            cur_a, _, cur_adp = get_adp(aig)
            if cur_a < 5000:
                for seed in [0, 7, 42, 13, 99]:
                    pareto = tmp / f"p_h_{seed}"
                    pareto.mkdir(exist_ok=True)
                    script = f'read_aiger "{aig}"; &get; &my_deepsyn -T 60 -I 8 -S {seed} -O "{pareto}"; &put; ps'
                    try:
                        run_abc_f(script, 70)
                        for f in sorted(pareto.glob("*.aig")):
                            if try_replace(case, f):
                                improved_this_round = True
                    except Exception:
                        pass
            break  # one pass for now (re-loop only if improvement found)

    # final check
    _, _, final_adp = get_adp(aig)
    if final_adp < start_adp:
        print(f"[{case}] TOTAL GAIN: {start_adp:,} → {final_adp:,}  (saved {start_adp - final_adp:,})", flush=True)
    else:
        # rollback to backup
        shutil.copyfile(backup, aig)
        print(f"[{case}] no improvement, keeping {start_adp:,}", flush=True)


def main() -> None:
    print(f"Boosting {len(CASES)} hard cases...", flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(optimize_case, c): c for c in CASES}
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as exc:
                print(f"ERROR {futs[f]}: {exc}", flush=True)
    print("\nDone.", flush=True)


if __name__ == "__main__":
    main()
