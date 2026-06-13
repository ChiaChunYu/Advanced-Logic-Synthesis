#!/usr/bin/env python3
"""Semantic synthesis for unsigned integer division benchmarks.

Identified bit-exact (all input rows):
  ex265 = 4-bit B / A -> 4   (A = high input bits = divisor, B = low = dividend)
  ex266 = 5-bit B / A -> 5
  ex267 = 6-bit B / A -> 6
  ex268 = 7-bit B / A -> 7
  ex269 = 8-bit B / A -> 8
Division by zero saturates the quotient to all-ones.

Emits a behavioural unsigned divide in Verilog (with the div-by-0 -> all-ones
guard), synthesizes via Yosys + ABC + &my_deepsyn, and adopts only a
CEC-verified, strictly-lower-ADP result. Small widths usually lose to the
existing structural AIG; the wider ones (ex268/269) are the likely winners.

Usage (from project root, inside WSL):
  python3 student/div_synth.py
  python3 student/div_synth.py --case ex269
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

# case -> operand width W (W-bit B / A -> W quotient; A = high bits, B = low).
# ALL widths verified 0-mismatch, but the behavioural-divide RTL loses to the
# existing structural AIG at every width tested (ex266/267/269 did not beat
# 936/3,124/14,880). So none are adopted into the pipeline; kept here for the
# record / re-check via --case.
IDENTIFIED: dict[str, int] = {}

IDENTIFIED_NONWINNING: dict[str, int] = {
    "ex266": 5,
    "ex267": 6,
    "ex269": 8,
}

# Verified but small; RTL not expected to beat the structural AIG.
IDENTIFIED_SMALL: dict[str, int] = {
    "ex265": 4,
    "ex268": 7,
}

ABC_FLOWS = [
    ("base",  "dc2; balance"),
    ("deep",  "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",  "&get; &syn2 -J 8; &put; dc2; balance"),
    ("syn3",  "&get; &syn3; &put; dc2; balance"),
    ("resyn", "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
              "balance; refactor -z; rewrite -z; balance"),
]


def verilog_div(width: int) -> str:
    """unsigned W-bit B / A -> W quotient; A = minterm bits [2W-1:W], B = [W-1:0].
    Division by zero saturates to all-ones."""
    n = 2 * width
    a_bits = ", ".join(f"x{i}" for i in range(n - 1, width - 1, -1))   # high W = A
    b_bits = ", ".join(f"x{i}" for i in range(width - 1, -1, -1))      # low W  = B
    in_decls = ", ".join(f"x{i}" for i in range(n))
    out_decls = ", ".join(f"y{i}" for i in range(width))
    y_concat = ", ".join(f"y{i}" for i in range(width - 1, -1, -1))
    return f"""\
module top (
  input  {in_decls},
  output {out_decls}
);
  wire [{width-1}:0] A = {{{a_bits}}};
  wire [{width-1}:0] B = {{{b_bits}}};
  wire [{width-1}:0] Q = (A == 0) ? {{{width}{{1'b1}}}} : (B / A);
  assign {{{y_concat}}} = Q;
endmodule
"""


def synth_case(case: str, keep_tmp: bool = False) -> bool:
    width = {**IDENTIFIED, **IDENTIFIED_NONWINNING, **IDENTIFIED_SMALL}[case]
    verilog = verilog_div(width)
    truth = BENCHMARKS / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    tmp = Path(tempfile.mkdtemp(prefix=f"div_{case}_"))
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
            print(f"[{case}] ADOPTED div RTL: {cur_adp:,} -> {best:,}")
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
    known = {**IDENTIFIED, **IDENTIFIED_NONWINNING, **IDENTIFIED_SMALL}
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
