#!/usr/bin/env python3
"""Semantic synthesis for integer-square-root benchmarks (isqrt(x)).

Identified bit-exact (all input rows, verified vs hardware non-restoring sqrt):
  ex275 = isqrt(8-bit)  -> 4
  ex276 = isqrt(10-bit) -> 5
  ex277 = isqrt(12-bit) -> 6
  ex278 = isqrt(14-bit) -> 7
  ex279 = isqrt(16-bit) -> 8

Emits a combinational non-restoring bit-by-bit sqrt in Verilog (two input bits
consumed per output bit), lets Yosys + ABC + &my_deepsyn map it, and adopts
only a CEC-verified, strictly-lower-ADP result.

Usage (from project root, inside WSL):
  python3 student/isqrt_synth.py
  python3 student/isqrt_synth.py --case ex279
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from abc_core import is_equivalent, measure_adp, run_abc_script

ABC        = ROOT / "student" / "abc"
BENCHMARKS = ROOT / "benchmarks"
OUTPUT     = ROOT / "output"

# All of ex275-279 are integer isqrt (0-mismatch vs the non-restoring HW algo).
# Only the widest (ex279, 16-bit) RTL beats the structural AIG; ex278 (14-bit)
# and the smaller ones lose, so only ex279 is adopted into the pipeline. The
# rest stay in IDENTIFIED_NONWINNING (documented, re-checkable via --case).
IDENTIFIED: dict[str, int] = {
    "ex279": 16,
}

IDENTIFIED_NONWINNING: dict[str, int] = {
    "ex275": 8,
    "ex276": 10,
    "ex277": 12,
    "ex278": 14,
}

ABC_FLOWS = [
    ("base",  "dc2; balance"),
    ("deep",  "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",  "&get; &syn2 -J 8; &put; dc2; balance"),
    ("syn3",  "&get; &syn3; &put; dc2; balance"),
    ("resyn", "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
              "balance; refactor -z; rewrite -z; balance"),
]


def verilog_isqrt(in_bits: int) -> str:
    """Combinational non-restoring isqrt. in_bits even; out = in_bits/2 bits.

    Iterative C-style algorithm unrolled into a behavioural always block; Yosys
    flattens the loop since the bounds are constant.
    """
    out_bits = in_bits // 2
    in_decls = ", ".join(f"x{i}" for i in range(in_bits))
    out_decls = ", ".join(f"y{i}" for i in range(out_bits))
    x_concat = ", ".join(f"x{i}" for i in range(in_bits - 1, -1, -1))
    y_concat = ", ".join(f"y{i}" for i in range(out_bits - 1, -1, -1))
    # rem width: up to out_bits*2 ; root width out_bits ; trial out_bits+2
    rw = in_bits + 2
    return f"""\
module top (
  input  {in_decls},
  output {out_decls}
);
  wire [{in_bits-1}:0] X = {{{x_concat}}};
  reg  [{out_bits-1}:0] root;
  reg  [{rw-1}:0] rem;
  reg  [{rw-1}:0] trial;
  integer i;
  always @* begin
    rem  = 0;
    root = 0;
    for (i = {out_bits-1}; i >= 0; i = i - 1) begin
      rem   = (rem << 2) | ((X >> (2*i)) & 2'b11);
      trial = (root << 2) | 2'b01;
      root  = root << 1;
      if (rem >= trial) begin
        rem  = rem - trial;
        root = root | 1'b1;
      end
    end
  end
  assign {{{y_concat}}} = root;
endmodule
"""


def synth_case(case: str, keep_tmp: bool = False) -> bool:
    width = {**IDENTIFIED, **IDENTIFIED_NONWINNING}[case]
    verilog = verilog_isqrt(width)
    truth = BENCHMARKS / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    tmp = Path(tempfile.mkdtemp(prefix=f"isqrt_{case}_"))
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
            print(f"[{case}] ADOPTED isqrt RTL: {cur_adp:,} -> {best:,}")
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
