#!/usr/bin/env python3
"""Semantic synthesis for unsigned-square benchmarks (x^2).

Identified bit-exact (all input rows):
  ex270 = 8-bit  x^2 -> 16
  ex271 = 10-bit x^2 -> 20
  ex272 = 12-bit x^2 -> 24
  ex273 = 14-bit x^2 -> 28
  ex274 = 16-bit x^2 -> 32

A dedicated square multiplier shares partial products (a_i*a_j appears twice),
so Yosys' `X * X` plus ABC + &my_deepsyn typically beats a generic multiplier
or the BDD result. Adopts only a CEC-verified, strictly-lower-ADP result.

Usage (from project root, inside WSL):
  python3 student/square_synth.py
  python3 student/square_synth.py --case ex270
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # student/experiment -> project
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"

# ex270-274 are all unsigned squares (x^2), verified 0-mismatch, BUT the x*x
# RTL loses to the existing structural AIG at every width tested (the BDD/ABC
# result is already tight), so none are adopted into the pipeline. Kept in
# IDENTIFIED_NONWINNING so they are documented and re-checkable via --case,
# without wasting pipeline time on a synthesis that never wins.
IDENTIFIED: dict[str, int] = {}

IDENTIFIED_NONWINNING: dict[str, int] = {
    "ex270": 8,
    "ex271": 10,
    "ex272": 12,
    "ex273": 14,
    "ex274": 16,
}

ABC_FLOWS = [
    ("base",  "dc2; balance"),
    ("deep",  "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",  "&get; &syn2 -J 8; &put; dc2; balance"),
    ("syn3",  "&get; &syn3; &put; dc2; balance"),
    ("resyn", "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
              "balance; refactor -z; rewrite -z; balance"),
]


def verilog_square(width: int) -> str:
    """unsigned width-bit square: X = {x[w-1..0]}, P = X*X (2w bits)."""
    n_in = width
    n_out = 2 * width
    x_bits = ", ".join(f"x{i}" for i in range(width - 1, -1, -1))
    in_decls = ", ".join(f"x{i}" for i in range(n_in))
    out_decls = ", ".join(f"y{i}" for i in range(n_out))
    y_concat = ", ".join(f"y{i}" for i in range(n_out - 1, -1, -1))
    return f"""\
module top (
  input  {in_decls},
  output {out_decls}
);
  wire [{width-1}:0] X = {{{x_bits}}};
  wire [{n_out-1}:0] P = X * X;
  assign {{{y_concat}}} = P;
endmodule
"""


def synth_case(case: str, keep_tmp: bool = False) -> bool:
    width = {**IDENTIFIED, **IDENTIFIED_NONWINNING}[case]
    verilog = verilog_square(width)
    truth = BENCHMARKS / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    tmp = Path(tempfile.mkdtemp(prefix=f"sq_{case}_"))
    try:
        vfile = tmp / f"{case}.v"
        blif = tmp / f"{case}.blif"
        vfile.write_text(verilog)
        ys = (f'read_verilog "{vfile}"; hierarchy -top top; proc; flatten; '
              f'opt; techmap; opt; write_blif "{blif}"')
        proc = subprocess.run(["yosys", "-p", ys], capture_output=True, text=True, timeout=300)
        if not blif.is_file():
            print(f"[{case}] yosys failed:\n{proc.stderr[-1500:]}")
            return False

        best = cur_adp
        improved = False

        def consider(cand: Path, label: str) -> None:
            nonlocal best, improved
            if not cand.is_file():
                return
            if not is_equivalent(ABC, truth, cand, 180, ROOT):
                print(f"[{case}] {label}: NOT EQUIVALENT")
                return
            _, _, adp = measure_adp(ABC, cand, 60, ROOT)
            tag = f" (current {cur_adp:,})" if cur_adp else ""
            print(f"[{case}] {label}: ADP={adp:,}{tag}")
            if best is None or adp < best:
                shutil.copyfile(cand, aig)
                best = adp
                improved = True

        for name, flow in ABC_FLOWS:
            cand = tmp / f"{case}_{name}.aig"
            try:
                run_abc_script(
                    ABC, f'read_blif "{blif}"; strash; {flow}; write_aiger -s "{cand}"', 180)
            except Exception as exc:
                print(f"[{case}] {name} error: {exc}")
                continue
            consider(cand, name)

        for seed in (42, 7, 0):
            pareto = tmp / f"pareto_s{seed}"
            pareto.mkdir(exist_ok=True)
            for cost in ("adp", "area"):
                try:
                    run_abc_script(
                        ABC,
                        f'read_blif "{blif}"; strash; dc2; dc2; '
                        f'&get; &my_deepsyn -T 120 -S {seed} -O "{pareto}" -C {cost}; &put',
                        260,
                    )
                except Exception:
                    pass
            for p_aig in sorted(pareto.glob("*.aig")):
                consider(p_aig, f"deepsyn_s{seed}/{p_aig.stem}")

        if improved:
            print(f"[{case}] ADOPTED square RTL: {cur_adp:,} -> {best:,}")
        else:
            print(f"[{case}] RTL did not beat current ({cur_adp:,}); kept existing")
        return improved
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", default=None)
    ap.add_argument("--keep-tmp", action="store_true")
    args = ap.parse_args()
    known = {**IDENTIFIED, **IDENTIFIED_NONWINNING}
    cases = args.case if args.case else list(IDENTIFIED)
    any_improved = False
    for case in cases:
        if case not in known:
            print(f"{case}: not identified, skipping")
            continue
        if synth_case(case, args.keep_tmp):
            any_improved = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
