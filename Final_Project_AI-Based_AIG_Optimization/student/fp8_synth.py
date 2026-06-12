#!/usr/bin/env python3
"""Semantic fp8 synthesis: build exact word-level RTL for identified fp8 cases.

Identified functions (verified bit-exact against the full 65536-row truth
table by student/experiment/identify_fp8.py):

  ex240 = fp8 add  (e4m3, subnormals honored, RNE, saturate, NaN -> 0x7F)
  ex241 = fp8 mul  (same conventions)
  ex242 = fp8 div  (same conventions, result = B / A)

Bit mapping (confirmed): operand A = x0..x7 (x0 = sign/MSB),
operand B = x8..x15, output bit y_j = bit j of the fp8 result (LSB-first).

Flow per case: emit Verilog -> yosys synth -> BLIF -> ABC strash + flows ->
equivalence check against the truth table -> adopt only on strict ADP
improvement (rollback safe).

Usage (from project root, inside WSL):
  python3 student/fp8_synth.py                # all identified cases
  python3 student/fp8_synth.py --case ex240   # one case
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
LOGS       = ROOT / "student" / "logs"

# case -> (op, fmt)  — only entries verified bit-exact AND that beat the
# existing AIG belong here. ex242 (fp8 div) is bit-exact but its RTL stays
# far larger than the current structural result, so it is intentionally
# excluded from the pipeline (kept verifiable via --case ex242 if desired).
IDENTIFIED: dict[str, tuple[str, str]] = {
    "ex240": ("add", "e4m3"),
    "ex241": ("mul", "e4m3"),
}

# Bit-exact but not adopted (RTL larger than current). For experiments only.
IDENTIFIED_NONWINNING: dict[str, tuple[str, str]] = {
    "ex242": ("div_ba", "e4m3"),
}

# ---------------------------------------------------------------------------
# Verilog generators (e4m3: 1s/4e/3m, bias 7, max finite 448 = S.1111.110,
# NaN = S.1111.111 -> canonical 0x7F, subnormals fully supported, RNE,
# overflow saturates to +-448)
# ---------------------------------------------------------------------------

_VERILOG_HEADER = """\
module top (
  input  x0, x1, x2, x3, x4, x5, x6, x7,
  input  x8, x9, x10, x11, x12, x13, x14, x15,
  output y0, y1, y2, y3, y4, y5, y6, y7
);
  // ABC truth-table convention: PI k carries minterm bit k, so operand A
  // (high byte of the row index) is {x15..x8} and B is {x7..x0}.
  wire [7:0] A = {x15, x14, x13, x12, x11, x10, x9, x8};
  wire [7:0] B = {x7, x6, x5, x4, x3, x2, x1, x0};
"""

_VERILOG_FOOTER = """\
  assign {y7, y6, y5, y4, y3, y2, y1, y0} = R;
endmodule
"""

# Compact RNE rounder: {sig4(hidden at bit3), g, r, s} + exponent -> {e, m}
# with saturation to 448 and subnormal (e field 0) encoding.
_E4M3_RNE_FUNC = """\
  function [6:0] rne7;
    input [3:0] sig4;
    input g, r, s_in;
    input signed [5:0] e_in;
    reg sticky, rb;
    reg [4:0] sig_r;
    reg signed [5:0] e;
    begin
      e = e_in;
      sticky = r | s_in;
      rb = g & (sticky | sig4[0]);
      sig_r = {1'b0, sig4} + {4'b0, rb};
      if (sig_r[4]) begin
        sig_r = sig_r >> 1;
        e = e + 1;
      end
      if (sig_r[3]) begin
        if (e > 15 || (e == 15 && sig_r[2:0] == 3'd7))
          rne7 = {4'd15, 3'd6};
        else
          rne7 = {e[3:0], sig_r[2:0]};
      end else begin
        rne7 = {4'd0, sig_r[2:0]};
      end
    end
  endfunction
"""

# Legacy wide rounder (kept for reference flows).
# Input: 38-bit magnitude in units of 2^-18 (so subnormal LSB = 1<<9).
# Output: 7-bit magnitude pattern {e[3:0], m[2:0]} with RNE and saturation.
_E4M3_ROUND_FUNC = """\
  function [6:0] round18;
    input [37:0] mag;     // units of 2^-18
    reg [5:0] p;          // MSB index
    reg [5:0] er;         // wide: saturation check needs er up to ~30
    reg [2:0] mr;
    reg g, s, rb;
    reg [4:0] km;         // {carry, 1, m} after rounding
    integer i;
    begin
      if (mag == 0) begin
        round18 = 7'd0;
      end else begin
        p = 0;
        for (i = 0; i < 38; i = i + 1)
          if (mag[i]) p = i[5:0];
        if (mag < (38'd8 << 9)) begin
          // subnormal result: round units 2^-18 -> 2^-9 grid
          mr = mag[11:9];
          g = mag[8];
          s = |mag[7:0];
          rb = g & (s | mag[9]);
          km = {1'b0, 1'b0, mr} + {4'b0, rb};
          if (km[3])
            round18 = {4'd1, 3'd0};       // rounded up to min normal
          else
            round18 = {4'd0, km[2:0]};
        end else begin
          er = p - 6'd11;
          mr = (mag >> (p - 3));          // {1,m} -> take low 3 as m
          g  = (mag >> (p - 4)) & 1'b1;
          s  = |(mag & ((38'd1 << (p - 4)) - 38'd1));
          rb = g & (s | mr[0]);
          km = {1'b0, 1'b1, mr} + {4'b0, rb};
          if (km[4]) begin                // mantissa overflow -> exp + 1
            er = er + 6'd1;
            mr = 3'd0;
          end else begin
            mr = km[2:0];
          end
          if (er > 6'd15 || (er == 6'd15 && mr == 3'd7))
            round18 = {4'd15, 3'd6};      // saturate to 448
          else
            round18 = {er[3:0], mr};
        end
      end
    end
  endfunction
"""

_DECODE_COMMON = """\
  wire sa = A[7]; wire [3:0] ea = A[6:3]; wire [2:0] ma = A[2:0];
  wire sb = B[7]; wire [3:0] eb = B[6:3]; wire [2:0] mb = B[2:0];
  wire nan_in = ((ea == 4'hF) & (ma == 3'h7)) | ((eb == 4'hF) & (mb == 3'h7));
  wire [3:0] siga = (ea == 0) ? {1'b0, ma} : {1'b1, ma};
  wire [3:0] sigb = (eb == 0) ? {1'b0, mb} : {1'b1, mb};
  wire [3:0] eaeff = (ea == 0) ? 4'd1 : ea;
  wire [3:0] ebeff = (eb == 0) ? 4'd1 : eb;
"""


def verilog_fp8_add_e4m3() -> str:
    body = _DECODE_COMMON + """\
  // order by magnitude (7-bit field compare is magnitude-monotone)
  wire swap = (B[6:0] > A[6:0]);
  wire sx = swap ? sb : sa;
  wire [3:0] ex0 = swap ? ebeff : eaeff;
  wire [3:0] sigx = swap ? sigb : siga;
  wire [3:0] ey = swap ? eaeff : ebeff;
  wire [3:0] sigy = swap ? siga : sigb;
  wire [3:0] d = ex0 - ey;

  wire [5:0] ywide = {sigy, 2'b00};
  wire [5:0] ysh = (d == 0) ? ywide :
                   (d <= 4'd5) ? (ywide >> d) : 6'd0;
  wire ysticky = (d == 0) ? 1'b0 :
                 (d <= 4'd5) ? |(ywide & ~(6'h3F << d)) :
                 |sigy;
  wire [5:0] xwide = {sigx, 2'b00};
  wire sub = sa ^ sb;

  reg [6:0] msum;
  reg sticky_in;
  reg signed [5:0] e;
  reg [3:0] sig4;
  reg g, r2;
  reg zero;
  integer i;
  always @* begin
    e = {2'b0, ex0};
    sticky_in = 0;
    zero = 0;
    if (sub) begin
      msum = {1'b0, xwide} - {1'b0, ysh};
      if (ysticky) begin
        msum = msum - 7'd1;
        sticky_in = 1;
      end
      if (msum == 0 && !sticky_in)
        zero = 1;
    end else begin
      msum = {1'b0, xwide} + {1'b0, ysh};
      sticky_in = ysticky;
      if (msum[6]) begin
        sticky_in = sticky_in | msum[0];
        msum = msum >> 1;
        e = e + 1;
      end
    end
    // normalize left (at most 6 steps), floor exponent at 1
    for (i = 0; i < 6; i = i + 1) begin
      if (!msum[5] && e > 1 && msum != 0) begin
        msum = msum << 1;
        e = e - 1;
      end
    end
    sig4 = msum[5:2];
    g = msum[1];
    r2 = msum[0];
  end
  wire szero = sa & sb;
  wire [6:0] em = rne7(sig4, g, r2, sticky_in, e);
  wire [7:0] R = nan_in ? 8'h7F :
                 zero   ? {szero, 7'b0} :
                 (msum == 0 && !sticky_in) ? {szero, 7'b0} :
                 {sx, em};
""" + _E4M3_RNE_FUNC
    return _VERILOG_HEADER + body + _VERILOG_FOOTER


def verilog_fp8_mul_e4m3() -> str:
    body = _DECODE_COMMON + """\
  wire sout = sa ^ sb;
  wire zero = (siga == 0) || (sigb == 0);

  reg [7:0] prod;
  reg signed [5:0] e;
  reg sticky;
  reg [3:0] sig4;
  reg g, r2, s_b;
  reg [3:0] sh;
  reg [7:0] wide;
  reg sticky2;
  integer i;
  always @* begin
    prod = siga * sigb;
    e = $signed({2'b0, eaeff}) + $signed({2'b0, ebeff}) - 6'sd7;
    sticky = 0;
    if (prod[7]) begin               // at most one right-shift (prod <= 225)
      sticky = prod[0];
      prod = prod >> 1;
      e = e + 1;
    end
    for (i = 0; i < 6; i = i + 1) begin   // normalize to hidden at bit6
      if (!prod[6] && e > -6'sd8) begin
        prod = prod << 1;
        e = e - 1;
      end
    end
    if (e >= 1) begin
      sig4 = prod[6:3];
      g = prod[2];
      r2 = prod[1];
      s_b = prod[0] | sticky;
      sh = 0;
      wide = 0;
      sticky2 = 0;
    end else begin
      sh = 4'd1 - e[3:0];            // 1 - e, e in [-8, 0] -> sh in [1, 9]
      sticky2 = sticky | |(prod & ~(8'hFF << sh));
      wide = prod >> sh;
      sig4 = wide[6:3];
      g = wide[2];
      r2 = wide[1];
      s_b = wide[0] | sticky2;
    end
  end
  wire signed [5:0] e_rnd = (e >= 1) ? e : 6'sd1;
  wire [6:0] em = rne7(sig4, g, r2, s_b, e_rnd);
  wire [7:0] R = nan_in ? 8'h7F : (zero ? {sout, 7'b0} : {sout, em});
""" + _E4M3_RNE_FUNC
    return _VERILOG_HEADER + body + _VERILOG_FOOTER


def verilog_fp8_div_ba_e4m3() -> str:
    # result = B / A  (swap=1 confirmed). x/0 -> sat (no inf in e4m3 sat mode),
    # 0/0 -> NaN. Division: integer divide of scaled significands.
    body = _DECODE_COMMON + """\
  // quotient = (sigb / siga) * 2^(ebeff - eaeff)
  // scale sigb << 20 to get enough quotient precision plus exactness bit
  wire [23:0] numer = {20'b0, sigb} << 20;        // sigb * 2^20
  wire [23:0] quo  = (siga == 0) ? 24'hFFFFFF : numer / {20'b0, siga};
  wire        exact = (siga == 0) ? 1'b0 : ((quo * {20'b0, siga}) == numer);
  // value = quo * 2^-20 * 2^(ebeff - eaeff); in units 2^-18:
  // mag = quo * 2^(ebeff - eaeff - 2); ebeff-eaeff in [-14, 14]
  wire [4:0] shl = 5'd14 + ebeff - eaeff;          // 0..28 ; mag = quo << shl >> 16
  wire [52:0] wide = {29'b0, quo} << shl;          // quo * 2^(ebeff-eaeff+14)
  // units: 2^-20 * 2^-14 relative -> value in units 2^-34: need >> 16 to 2^-18
  wire [37:0] mag = wide[52:16];
  wire sticky_low = |wide[15:0] | ~exact;
  wire [37:0] mag_adj = {mag[37:1], mag[0] | sticky_low};
  wire zero_b = (sigb == 0);
  wire zero_a = (siga == 0);
  wire nan_div = zero_a & zero_b;                  // 0/0
  wire sout = sa ^ sb;
  wire [6:0] em = round18(mag_adj);
  wire [6:0] sat = {4'd15, 3'd6};
  wire [7:0] R = (nan_in | nan_div) ? 8'h7F
               : zero_b ? {sout, 7'b0}
               : zero_a ? {sout, sat}
               : {sout, em};
""" + _E4M3_ROUND_FUNC
    return _VERILOG_HEADER + body + _VERILOG_FOOTER


GENERATORS = {
    ("add", "e4m3"): verilog_fp8_add_e4m3,
    ("mul", "e4m3"): verilog_fp8_mul_e4m3,
    ("div_ba", "e4m3"): verilog_fp8_div_ba_e4m3,
}

ABC_FLOWS = [
    ("base",     "dc2; balance"),
    ("deep",     "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",     "&get; &syn2 -J 8; &put; dc2; balance"),
    ("resyn",    "balance; rewrite; refactor; balance; rewrite; rewrite -z; balance; refactor -z; rewrite -z; balance"),
    ("if_area",  "&get; &if -K 6 -a; &put; dc2; balance"),
]


def synth_case(case: str, keep_tmp: bool = False) -> bool:
    op, fmt = {**IDENTIFIED, **IDENTIFIED_NONWINNING}[case]
    verilog = GENERATORS[(op, fmt)]()
    truth = BENCHMARKS / f"{case}.truth"
    aig = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    tmpdir = Path(tempfile.mkdtemp(prefix=f"fp8_{case}_"))
    try:
        vfile = tmpdir / f"{case}.v"
        blif = tmpdir / f"{case}.blif"
        vfile.write_text(verilog)

        # yosys: behavioral verilog -> gate-level BLIF (ports keep order)
        ys = (
            f'read_verilog "{vfile}"; hierarchy -top top; proc; flatten; '
            f'opt; techmap; opt; write_blif "{blif}"'
        )
        proc = subprocess.run(["yosys", "-p", ys], capture_output=True, text=True, timeout=300)
        if not blif.is_file():
            print(f"[{case}] yosys failed:\n{proc.stderr[-2000:]}")
            return False

        improved = False
        best_new = cur_adp

        def consider(cand: Path, label: str) -> None:
            nonlocal improved, best_new
            if not cand.is_file():
                return
            if not is_equivalent(ABC, truth, cand, 180, ROOT):
                print(f"[{case}] {label}: NOT EQUIVALENT (semantics bug)")
                return
            _, _, adp = measure_adp(ABC, cand, 60, ROOT)
            print(f"[{case}] {label}: ADP={adp:,}" + (f" (current {cur_adp:,})" if cur_adp else ""))
            if best_new is None or adp < best_new:
                shutil.copyfile(cand, aig)
                best_new = adp
                improved = True

        for flow_name, flow in ABC_FLOWS:
            cand = tmpdir / f"{case}_{flow_name}.aig"
            try:
                run_abc_script(
                    ABC,
                    f'read_blif "{blif}"; strash; {flow}; write_aiger -s "{cand}"',
                    180,
                )
            except Exception as exc:
                print(f"[{case}] {flow_name} flow error: {exc}")
                continue
            consider(cand, flow_name)

        # heavy stage: &my_deepsyn ADP-Pareto search from the RTL AIG
        for seed in (42, 7):
            pareto = tmpdir / f"pareto_s{seed}"
            pareto.mkdir(exist_ok=True)
            try:
                run_abc_script(
                    ABC,
                    f'read_blif "{blif}"; strash; dc2; dc2; '
                    f'&get; &my_deepsyn -T 120 -S {seed} -O "{pareto}" -C adp; &put',
                    240,
                )
            except Exception as exc:
                print(f"[{case}] deepsyn seed {seed} error: {exc}")
            for p_aig in sorted(pareto.glob("*.aig")):
                consider(p_aig, f"deepsyn_s{seed}/{p_aig.stem}")
        if improved:
            print(f"[{case}] ADOPTED semantic RTL: {cur_adp:,} -> {best_new:,}")
        else:
            print(f"[{case}] semantic RTL did not beat current ({cur_adp:,}); kept existing")
        return improved
    finally:
        if not keep_tmp:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", default=None)
    parser.add_argument("--keep-tmp", action="store_true")
    args = parser.parse_args()

    known = {**IDENTIFIED, **IDENTIFIED_NONWINNING}
    cases = args.case if args.case else list(IDENTIFIED)
    any_improved = False
    for case in cases:
        if case not in known:
            print(f"{case}: not identified yet, skipping")
            continue
        if synth_case(case, args.keep_tmp):
            any_improved = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
