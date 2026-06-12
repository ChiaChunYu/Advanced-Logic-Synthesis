#!/usr/bin/env python3
"""Semantic synthesis for fp16 unary logarithm benchmarks.

Identified bit-exact:
  ex224 = fp16 log2(x)   (verified 0/65536 with a 24-bit fixed-point datapath)

Datapath (DAZ):
  x = (1 + m/1024) * 2^(e-15)            [normal, sign 0]
  log2(x) = (e - 15) + log2(1 + m/1024)
          = signed integer (e-15) + LUT[m] (24-bit fraction in [0,1))
  result is a signed fixed-point number; normalize + round to fp16 (RNE).

  Specials: subnormal/zero input -> -inf (0xfc00); negative -> NaN (0x7e00);
  +inf -> +inf (0x7c00); NaN -> NaN (0x7e00).

ln (ex223) and log10 (ex225) match to within 1 ULP with library math, so they
are NOT bit-exact here and are excluded (kept for reference in
experiment/check_fp16_log.py).

The fp16 encoder is generated as a Verilog function; the mantissa LUT is a
1024-entry case. Yosys builds it, ABC + &my_deepsyn compress it, CEC gates
adoption.

Usage (from project root, inside WSL):
  python3 student/fp16_synth.py              # all identified cases
  python3 student/fp16_synth.py --case ex224
"""
from __future__ import annotations

import argparse
import math
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

# Bit-exact identification confirmed, but the LUT+fixed-point RTL is deeper than
# the existing BDD structure (deepsyn floors at ~132K vs current ~103K), so
# log2 is NOT adopted into the pipeline. Kept here, runnable via --case ex224,
# to document the function and the verified datapath.
IDENTIFIED: dict[str, str] = {}

IDENTIFIED_NONWINNING: dict[str, str] = {
    "ex224": "log2",
}

F = 24  # fractional bits (bit-exact for log2)

ABC_FLOWS = [
    ("base",  "dc2; balance"),
    ("deep",  "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",  "&get; &syn2 -J 8; &put; dc2; balance"),
]


def _lut_entries() -> list[int]:
    scale = 1 << F
    return [round(math.log2(1 + m / 1024) * scale) for m in range(1024)]


def verilog_fp16_log2() -> str:
    """fp16 log2 with a 24-bit fractional fixed-point intermediate."""
    lut = _lut_entries()
    # signed fixed-point result width: int part in [-15, 15] (5 bits + sign),
    # fraction F bits. Use a wide signed accumulator.
    IW = 6                    # signed int part headroom
    W = IW + F                # total magnitude bits below the sign
    in_decls = ", ".join(f"x{i}" for i in range(16))
    out_decls = ", ".join(f"y{i}" for i in range(16))
    y_concat = ", ".join(f"y{i}" for i in range(15, -1, -1))

    lut_cases = "\n".join(
        f"      10'd{m}: frac = {F}'d{lut[m]};" for m in range(1024)
    )

    return f"""\
module top (
  input  {in_decls},
  output {out_decls}
);
  wire [15:0] X = {{x15, x14, x13, x12, x11, x10, x9, x8, x7, x6, x5, x4, x3, x2, x1, x0}};
  wire        s = X[15];
  wire [4:0]  e = X[14:10];
  wire [9:0]  m = X[9:0];

  // mantissa fraction LUT: log2(1 + m/1024) scaled by 2^{F}
  reg [{F-1}:0] frac;
  always @* begin
    case (m)
{lut_cases}
      default: frac = {F}'d0;
    endcase
  end

  // signed fixed-point result = (e-15) + frac/2^{F}, units 2^-{F}
  wire signed [{W}:0] int_part = $signed({{1'b0, e}}) - 7'sd15;
  wire signed [{W}:0] result   = (int_part <<< {F}) + $signed({{1'b0, frac}});
  wire           neg_r = result[{W}];
  wire [{W-1}:0] mag    = neg_r ? (~result[{W-1}:0] + 1'b1) : result[{W-1}:0];

  // normalize: find MSB position p of mag, value = mag * 2^-{F}
  reg [5:0] p;
  integer i;
  always @* begin
    p = 0;
    for (i = 0; i < {W}; i = i + 1)
      if (mag[i]) p = i[5:0];
  end

  // fp16 exponent of result: 2^(p-{F}); biased = (p-{F}) + 15
  wire signed [6:0] uexp = $signed({{1'b0, p}}) - 7'sd{F} + 7'sd15;

  // mantissa: 10 bits below the leading 1, with guard/round/sticky for RNE
  // shift so the leading 1 is at bit position {F}; take next 10 bits.
  reg [9:0] mant;
  reg       g, r, st;
  reg [10:0] mant_r;
  reg signed [6:0] fexp;
  reg [15:0] R;
  reg [{W}:0] norm;
  always @* begin
    if (result == 0) begin
      R = 16'h0000;                                   // log2(1) = +0
    end else begin
      // align leading 1 to a known position: norm = mag << ({W}-1 - p)
      norm = mag << ({W} - 1 - p);                    // MSB now at bit {W}-1
      mant = norm[{W}-2 -: 10];                       // 10 bits after hidden 1
      g    = norm[{W}-12];
      r    = norm[{W}-13];
      st   = |(norm & (({W+1}'d1 << ({W}-13)) - 1));
      fexp = uexp;
      mant_r = {{1'b0, mant}} + ((g & (r | st | mant[0])) ? 11'd1 : 11'd0);
      if (mant_r[10]) begin                           // mantissa overflow
        fexp = fexp + 1;
        mant_r = 11'd0;                                // 1.111..+1 -> 10.000, mant=0
      end
      if (fexp >= 31)      R = {{s, 5'b0, 10'b0}} | 16'h7c00; // overflow -> inf (sign kept)
      else if (fexp <= 0)  R = {{neg_r, 15'b0}};             // underflow -> signed 0
      else                 R = {{neg_r, fexp[4:0], mant_r[9:0]}};
    end
  end

  // specials override
  wire is_nan_in  = (e == 5'd31) && (m != 0);
  wire is_inf_in  = (e == 5'd31) && (m == 0);
  wire is_zero_in = (e == 5'd0);                       // DAZ: subnormal too
  wire [15:0] RES =
       is_nan_in              ? 16'h7e00 :
       (is_inf_in &&  s)      ? 16'h7e00 :             // log2(-inf) = NaN
       (is_inf_in && !s)      ? 16'h7c00 :             // log2(+inf) = +inf
       is_zero_in             ? 16'hfc00 :             // log2(0) = -inf
       s                      ? 16'h7e00 :             // negative normal -> NaN
                                R;
  assign {{{y_concat}}} = RES;
endmodule
"""


GENERATORS = {
    ("log2",): verilog_fp16_log2,
}


def synth_case(case: str, keep_tmp: bool = False) -> bool:
    fn = {**IDENTIFIED, **IDENTIFIED_NONWINNING}[case]
    verilog = GENERATORS[(fn,)]()
    truth = BENCHMARKS / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    tmp = Path(tempfile.mkdtemp(prefix=f"fp16_{case}_"))
    try:
        vfile = tmp / f"{case}.v"
        blif = tmp / f"{case}.blif"
        vfile.write_text(verilog)
        # `memory` pass flattens the 1024-entry mantissa LUT (inferred as a ROM)
        # into logic; the BLIF backend rejects unmapped memories otherwise.
        ys = (f'read_verilog "{vfile}"; hierarchy -top top; proc; memory; '
              f'flatten; opt; techmap; opt; write_blif "{blif}"')
        proc = subprocess.run(["yosys", "-p", ys], capture_output=True, text=True, timeout=600)
        if not blif.is_file():
            print(f"[{case}] yosys failed:\n{proc.stderr[-2000:]}")
            return False

        best = cur_adp
        improved = False

        def consider(cand: Path, label: str) -> None:
            nonlocal best, improved
            if not cand.is_file():
                return
            if not is_equivalent(ABC, truth, cand, 240, ROOT):
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
                    ABC, f'read_blif "{blif}"; strash; {flow}; write_aiger -s "{cand}"', 240)
            except Exception as exc:
                print(f"[{case}] {name} error: {exc}")
                continue
            consider(cand, name)

        for seed in (42, 7):
            pareto = tmp / f"pareto_s{seed}"
            pareto.mkdir(exist_ok=True)
            for cost in ("adp", "area"):
                try:
                    run_abc_script(
                        ABC,
                        f'read_blif "{blif}"; strash; dc2; dc2; '
                        f'&get; &my_deepsyn -T 150 -S {seed} -O "{pareto}" -C {cost}; &put',
                        320,
                    )
                except Exception:
                    pass
            for p_aig in sorted(pareto.glob("*.aig")):
                consider(p_aig, f"deepsyn_s{seed}/{p_aig.stem}")

        if improved:
            print(f"[{case}] ADOPTED fp16-{fn} RTL: {cur_adp:,} -> {best:,}")
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
