#!/usr/bin/env python3
"""Semantic RTL synthesis for identified arithmetic benchmarks.

Covers three families of circuits, all verified bit-exact against the full
truth table before adoption:

  FP8 (fp8_synth):
    ex240 = fp8 add  (e4m3)
    ex241 = fp8 mul  (e4m3)
    ex245 = fp8 add  (e5m2)

  Signed multiplier (mult_synth):
    ex261 = signed 5x5 -> 10
    ex262 = signed 6x6 -> 12
    ex263 = signed 7x7 -> 14
    ex264 = signed 8x8 -> 16

  Integer isqrt (isqrt_synth):
    ex279 = isqrt(16-bit) -> 8

Flow per case: emit Verilog -> yosys synth -> BLIF -> ABC flows + &my_deepsyn
Pareto search -> CEC against truth table -> adopt only strict ADP improvement.

Usage (from project root, inside WSL):
  python3 student/rtl_synth.py              # all pipeline-winning cases
  python3 student/rtl_synth.py --family fp8
  python3 student/rtl_synth.py --family mult
  python3 student/rtl_synth.py --family isqrt
  python3 student/rtl_synth.py --case ex240
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

# ---------------------------------------------------------------------------
# Shared ABC flows used by all three families
# ---------------------------------------------------------------------------

_BASE_FLOWS = [
    ("base",   "dc2; balance"),
    ("deep",   "dc2; dc2; rewrite -z; refactor -z; balance; dc2; balance"),
    ("syn2",   "&get; &syn2 -J 8; &put; dc2; balance"),
    ("resyn",  "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
               "balance; refactor -z; rewrite -z; balance"),
]

_MULT_EXTRA_FLOWS = [
    ("syn3",   "&get; &syn3; &put; dc2; balance"),
]

# ---------------------------------------------------------------------------
# FP8 Verilog generators
# ---------------------------------------------------------------------------

_FP8_HEADER = """\
module top (
  input  x0, x1, x2, x3, x4, x5, x6, x7,
  input  x8, x9, x10, x11, x12, x13, x14, x15,
  output y0, y1, y2, y3, y4, y5, y6, y7
);
  wire [7:0] A = {x15, x14, x13, x12, x11, x10, x9, x8};
  wire [7:0] B = {x7, x6, x5, x4, x3, x2, x1, x0};
"""

_FP8_FOOTER = """\
  assign {y7, y6, y5, y4, y3, y2, y1, y0} = R;
endmodule
"""

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

_E4M3_DECODE = """\
  wire sa = A[7]; wire [3:0] ea = A[6:3]; wire [2:0] ma = A[2:0];
  wire sb = B[7]; wire [3:0] eb = B[6:3]; wire [2:0] mb = B[2:0];
  wire nan_in = ((ea == 4'hF) & (ma == 3'h7)) | ((eb == 4'hF) & (mb == 3'h7));
  wire [3:0] siga = (ea == 0) ? {1'b0, ma} : {1'b1, ma};
  wire [3:0] sigb = (eb == 0) ? {1'b0, mb} : {1'b1, mb};
  wire [3:0] eaeff = (ea == 0) ? 4'd1 : ea;
  wire [3:0] ebeff = (eb == 0) ? 4'd1 : eb;
"""

_E5M2_RNE_FUNC = """\
  function [6:0] rne7;
    input [2:0] sig3;
    input g, r, s_in;
    input signed [6:0] e_in;
    reg sticky, rb;
    reg [3:0] sig_r;
    reg signed [6:0] e;
    begin
      e = e_in;
      sticky = r | s_in;
      rb = g & (sticky | sig3[0]);
      sig_r = {1'b0, sig3} + {3'b0, rb};
      if (sig_r[3]) begin
        sig_r = sig_r >> 1;
        e = e + 1;
      end
      if (sig_r[2]) begin
        if (e > 31 || (e == 31 && sig_r[1:0] == 2'd3))
          rne7 = {5'd31, 2'd2};
        else
          rne7 = {e[4:0], sig_r[1:0]};
      end else begin
        rne7 = {5'd0, sig_r[1:0]};
      end
    end
  endfunction
"""

_E5M2_DECODE = """\
  wire sa = A[7]; wire [4:0] ea = A[6:2]; wire [1:0] ma = A[1:0];
  wire sb = B[7]; wire [4:0] eb = B[6:2]; wire [1:0] mb = B[1:0];
  wire nan_a = (A[6:0] == 7'h7f);
  wire nan_b = (B[6:0] == 7'h7f);
  wire nan_in = nan_a | nan_b;
  wire [2:0] siga = (ea == 0) ? {1'b0, ma} : {1'b1, ma};
  wire [2:0] sigb = (eb == 0) ? {1'b0, mb} : {1'b1, mb};
  wire [4:0] eaeff = (ea == 0) ? 5'd1 : ea;
  wire [4:0] ebeff = (eb == 0) ? 5'd1 : eb;
"""


def _verilog_fp8_add_e4m3() -> str:
    body = _E4M3_DECODE + """\
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
    return _FP8_HEADER + body + _FP8_FOOTER


def _verilog_fp8_mul_e4m3() -> str:
    body = _E4M3_DECODE + """\
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
    if (prod[7]) begin
      sticky = prod[0];
      prod = prod >> 1;
      e = e + 1;
    end
    for (i = 0; i < 6; i = i + 1) begin
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
      sh = 4'd1 - e[3:0];
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
    return _FP8_HEADER + body + _FP8_FOOTER


def _verilog_fp8_add_e5m2() -> str:
    body = _E5M2_DECODE + """\
  wire swap = (B[6:0] > A[6:0]);
  wire sx = swap ? sb : sa;
  wire [4:0] ex0 = swap ? ebeff : eaeff;
  wire [2:0] sigx = swap ? sigb : siga;
  wire [4:0] ey = swap ? eaeff : ebeff;
  wire [2:0] sigy = swap ? siga : sigb;
  wire [5:0] d = ex0 - ey;

  wire [4:0] ywide = {sigy, 2'b00};
  wire [4:0] ysh = (d == 0) ? ywide : (d <= 5'd4) ? (ywide >> d) : 5'd0;
  wire ysticky = (d == 0) ? 1'b0 :
                 (d <= 5'd4) ? |(ywide & ~(5'h1F << d)) : |sigy;
  wire [4:0] xwide = {sigx, 2'b00};
  wire sub = sa ^ sb;

  reg [5:0] msum;
  reg sticky_in;
  reg signed [6:0] e;
  reg [2:0] sig3;
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
        msum = msum - 6'd1;
        sticky_in = 1;
      end
      if (msum == 0 && !sticky_in) zero = 1;
    end else begin
      msum = {1'b0, xwide} + {1'b0, ysh};
      sticky_in = ysticky;
      if (msum[5]) begin
        sticky_in = sticky_in | msum[0];
        msum = msum >> 1;
        e = e + 1;
      end
    end
    for (i = 0; i < 5; i = i + 1) begin
      if (!msum[4] && e > 1 && msum != 0) begin
        msum = msum << 1;
        e = e - 1;
      end
    end
    sig3 = msum[4:2];
    g = msum[1];
    r2 = msum[0];
  end
  wire szero = sa & sb;
  wire [6:0] em = rne7(sig3, g, r2, sticky_in, e);
  wire [7:0] R = nan_in ? 8'h7F :
                 zero   ? {szero, 7'b0} :
                 (msum == 0 && !sticky_in) ? {szero, 7'b0} :
                 {sx, em};
""" + _E5M2_RNE_FUNC
    return _FP8_HEADER + body + _FP8_FOOTER


# case -> generator function
_FP8_GENERATORS = {
    "ex240": _verilog_fp8_add_e4m3,
    "ex241": _verilog_fp8_mul_e4m3,
    "ex245": _verilog_fp8_add_e5m2,
}

# Identified but RTL larger than current structural AIG — not in pipeline.
_FP8_NONWINNING = {"ex242", "ex246"}


# ---------------------------------------------------------------------------
# Multiplier Verilog generator
# ---------------------------------------------------------------------------

# case -> (width, signed)
_MULT_CASES: dict[str, tuple[int, bool]] = {
    "ex261": (5, True),
    "ex262": (6, True),
    "ex263": (7, True),
    "ex264": (8, True),
}

_MULT_NONWINNING: dict[str, tuple[int, bool]] = {
    "ex255": (4, False),
    "ex256": (5, False),
    "ex257": (6, False),
    "ex258": (7, False),
    "ex259": (8, False),
    "ex260": (4, True),
}


def _verilog_mult(width: int, signed: bool) -> str:
    n = 2 * width
    a_bits = ", ".join(f"x{i}" for i in range(n - 1, width - 1, -1))
    b_bits = ", ".join(f"x{i}" for i in range(width - 1, -1, -1))
    in_decls = ", ".join(f"x{i}" for i in range(n))
    out_decls = ", ".join(f"y{i}" for i in range(n))
    y_concat = ", ".join(f"y{i}" for i in range(n - 1, -1, -1))
    sgn = "signed " if signed else ""
    return f"""\
module top (
  input  {in_decls},
  output {out_decls}
);
  wire {sgn}[{width-1}:0] A = {{{a_bits}}};
  wire {sgn}[{width-1}:0] B = {{{b_bits}}};
  wire {sgn}[{n-1}:0] P = A * B;
  assign {{{y_concat}}} = P;
endmodule
"""


# ---------------------------------------------------------------------------
# Integer isqrt Verilog generator
# ---------------------------------------------------------------------------

# case -> input_bits
_ISQRT_CASES: dict[str, int] = {
    "ex279": 16,
}

_ISQRT_NONWINNING: dict[str, int] = {
    "ex275": 8,
    "ex276": 10,
    "ex277": 12,
    "ex278": 14,
}


def _verilog_isqrt(in_bits: int) -> str:
    out_bits = in_bits // 2
    in_decls = ", ".join(f"x{i}" for i in range(in_bits))
    out_decls = ", ".join(f"y{i}" for i in range(out_bits))
    x_concat = ", ".join(f"x{i}" for i in range(in_bits - 1, -1, -1))
    y_concat = ", ".join(f"y{i}" for i in range(out_bits - 1, -1, -1))
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


# ---------------------------------------------------------------------------
# Shared synthesis engine
# ---------------------------------------------------------------------------

def _synth_case(case: str, verilog: str, abc_flows: list[tuple[str, str]],
                keep_tmp: bool = False) -> bool:
    truth = BENCHMARKS / f"{case}.truth"
    aig   = OUTPUT / f"{case}.aig"

    cur_adp = None
    if aig.is_file():
        try:
            _, _, cur_adp = measure_adp(ABC, aig, 60, ROOT)
        except Exception:
            pass

    prefix = case.replace("ex", "rtl_")
    tmp = Path(tempfile.mkdtemp(prefix=f"{prefix}_"))
    try:
        vfile = tmp / f"{case}.v"
        blif  = tmp / f"{case}.blif"
        vfile.write_text(verilog)

        ys = (f'read_verilog "{vfile}"; hierarchy -top top; proc; flatten; '
              f'opt; techmap; opt; write_blif "{blif}"')
        proc = subprocess.run(["yosys", "-p", ys], capture_output=True, text=True, timeout=300)
        if not blif.is_file():
            print(f"[{case}] yosys failed:\n{proc.stderr[-2000:]}")
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

        for name, flow in abc_flows:
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
            print(f"[{case}] ADOPTED RTL: {cur_adp:,} -> {best:,}")
        else:
            print(f"[{case}] RTL did not beat current ({cur_adp:,}); kept existing")
        return improved
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Per-family entry points
# ---------------------------------------------------------------------------

def synth_fp8(cases: list[str] | None = None, keep_tmp: bool = False) -> None:
    known = set(_FP8_GENERATORS) | _FP8_NONWINNING
    targets = cases if cases else list(_FP8_GENERATORS)
    flows = _BASE_FLOWS
    for case in targets:
        if case not in known:
            print(f"[{case}] not an identified fp8 case, skipping")
            continue
        if case in _FP8_NONWINNING:
            print(f"[{case}] fp8 non-winning (RTL larger than structural AIG), skipping pipeline")
            continue
        _synth_case(case, _FP8_GENERATORS[case](), flows, keep_tmp)


def synth_mult(cases: list[str] | None = None, keep_tmp: bool = False) -> None:
    known = {**_MULT_CASES, **_MULT_NONWINNING}
    targets = cases if cases else list(_MULT_CASES)
    flows = _BASE_FLOWS + _MULT_EXTRA_FLOWS
    for case in targets:
        if case not in known:
            print(f"[{case}] not an identified multiplier case, skipping")
            continue
        if case in _MULT_NONWINNING:
            print(f"[{case}] mult non-winning (RTL larger than structural AIG), skipping pipeline")
            continue
        w, s = known[case]
        _synth_case(case, _verilog_mult(w, s), flows, keep_tmp)


def synth_isqrt(cases: list[str] | None = None, keep_tmp: bool = False) -> None:
    known = {**_ISQRT_CASES, **_ISQRT_NONWINNING}
    targets = cases if cases else list(_ISQRT_CASES)
    flows = _BASE_FLOWS + _MULT_EXTRA_FLOWS
    for case in targets:
        if case not in known:
            print(f"[{case}] not an identified isqrt case, skipping")
            continue
        if case in _ISQRT_NONWINNING:
            print(f"[{case}] isqrt non-winning (RTL larger than structural AIG), skipping pipeline")
            continue
        _synth_case(case, _verilog_isqrt(known[case]), flows, keep_tmp)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", choices=["fp8", "mult", "isqrt"],
                    help="Run only this family (default: all)")
    ap.add_argument("--case", action="append", default=None,
                    help="Specific case(s) to run (can repeat; overrides --family)")
    ap.add_argument("--keep-tmp", action="store_true",
                    help="Keep temporary Verilog/BLIF/AIG files for debugging")
    args = ap.parse_args()

    cases = args.case  # None means "use family defaults"

    if cases:
        # Route each case to the right family
        fp8_cases   = [c for c in cases if c in set(_FP8_GENERATORS) | _FP8_NONWINNING]
        mult_cases  = [c for c in cases if c in {**_MULT_CASES, **_MULT_NONWINNING}]
        isqrt_cases = [c for c in cases if c in {**_ISQRT_CASES, **_ISQRT_NONWINNING}]
        unknown     = [c for c in cases if c not in fp8_cases + mult_cases + isqrt_cases]
        for c in unknown:
            print(f"[{c}] unknown case, skipping")
        if fp8_cases:
            synth_fp8(fp8_cases, args.keep_tmp)
        if mult_cases:
            synth_mult(mult_cases, args.keep_tmp)
        if isqrt_cases:
            synth_isqrt(isqrt_cases, args.keep_tmp)
    elif args.family == "fp8":
        synth_fp8(None, args.keep_tmp)
    elif args.family == "mult":
        synth_mult(None, args.keep_tmp)
    elif args.family == "isqrt":
        synth_isqrt(None, args.keep_tmp)
    else:
        synth_fp8(None, args.keep_tmp)
        synth_mult(None, args.keep_tmp)
        synth_isqrt(None, args.keep_tmp)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
