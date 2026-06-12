#!/usr/bin/env python3
"""Identify fp8 binary ops / conversions / int8 ops for ex240-ex254 (16in/8out).

Confirmed so far (full 65536-row exact):
  ex240 = fp8 add, e4m3, subnormals on (no DAZ/FTZ), saturating, NaN=0x7F
  ex241 = fp8 mul, e4m3, same conventions

Hypothesis space:
  fmt       : e4m3 / e5m2
  specials  : ieee (inf/NaN per OCP spec) | none (all exponents are normal)
  daz / ftz : flush subnormal inputs / results
  sat       : overflow saturates to max finite (else inf / NaN)
  rounding  : rne / rna / rtz
  nan_mode  : canonical byte | propagate operand byte (a-first / b-first)
  ops       : add sub mul div min max (swap for non-commutative)
  int8      : signed/unsigned add sub mul, sat/wrap
  cvt       : fp16/bf16 -> fp8 with all conventions
Bit mapping (confirmed by ex240/ex241): A = x0..x7 (x0=MSB), B = x8..x15,
output y_j = bit j of result byte (LSB-first).
"""
from __future__ import annotations

import math
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth

CASES = ["ex242", "ex243", "ex244", "ex245", "ex246", "ex247",
         "ex248", "ex249", "ex250", "ex251", "ex252", "ex253", "ex254"]

FMT = {
    "e4m3": dict(ebits=4, mbits=3, bias=7),
    "e5m2": dict(ebits=5, mbits=2, bias=15),
}


def bitrev8(b: int) -> int:
    r = 0
    for i in range(8):
        if b & (1 << i):
            r |= 1 << (7 - i)
    return r


BITREV8 = [bitrev8(i) for i in range(256)]


class Fp8:
    def __init__(self, fmt: str, specials: str = "ieee", daz: bool = False,
                 ftz: bool = False, sat: bool = True, rounding: str = "rne",
                 nan_byte: int = 0x7F):
        p = FMT[fmt]
        self.fmt, self.specials = fmt, specials
        self.daz, self.ftz, self.sat = daz, ftz, sat
        self.rounding, self.nan_byte = rounding, nan_byte
        self.ebits, self.mbits, self.bias = p["ebits"], p["mbits"], p["bias"]
        self.emax_field = (1 << self.ebits) - 1
        self.min_normal = 2.0 ** (1 - self.bias)

        self.dec = [self._decode(b) for b in range(256)]

        grid: list[tuple[float, int]] = []
        for byte in range(128):
            v = self._decode_raw(byte)
            if v is None or math.isnan(v) or math.isinf(v):
                continue
            grid.append((v, byte))
        grid.sort()
        self.grid_vals = [v for v, _ in grid]
        self.grid_bytes = [b for _, b in grid]
        self.max_finite = self.grid_vals[-1]
        self.inf_byte = (self.emax_field << self.mbits) if (fmt == "e5m2" and specials == "ieee") else None

    def _decode_raw(self, byte: int) -> float:
        s = (byte >> 7) & 1
        e = (byte >> self.mbits) & self.emax_field
        m = byte & ((1 << self.mbits) - 1)
        sign = -1.0 if s else 1.0
        if self.specials == "ieee":
            if self.fmt == "e4m3":
                if e == self.emax_field and m == (1 << self.mbits) - 1:
                    return math.nan
            else:
                if e == self.emax_field:
                    return math.inf * sign if m == 0 else math.nan
        if e == 0:
            return sign * (m / (1 << self.mbits)) * 2.0 ** (1 - self.bias)
        return sign * (1 + m / (1 << self.mbits)) * 2.0 ** (e - self.bias)

    def _decode(self, byte: int) -> float:
        v = self._decode_raw(byte)
        if self.daz and v != 0.0 and not math.isnan(v) and not math.isinf(v) and abs(v) < self.min_normal:
            return math.copysign(0.0, v)
        return v

    def encode(self, x: float) -> int:
        if math.isnan(x):
            return self.nan_byte
        neg = math.copysign(1.0, x) < 0
        sbit = 0x80 if neg else 0
        a = abs(x)
        if a == 0.0:
            return sbit
        if math.isinf(a):
            if self.inf_byte is not None and not self.sat:
                return self.inf_byte | sbit
            if self.fmt == "e4m3" and self.specials == "ieee" and not self.sat:
                return self.nan_byte
            return self.grid_bytes[-1] | sbit
        if a > self.max_finite:
            last, second = self.grid_vals[-1], self.grid_vals[-2]
            ulp = last - second
            inside = a < last + ulp / 2 if self.rounding in ("rne", "rna") else (a < last + ulp if self.rounding == "rtz" else False)
            if inside or self.sat:
                if not inside and not self.sat:
                    pass
                if inside:
                    return self.grid_bytes[-1] | sbit
                return self.grid_bytes[-1] | sbit
            if self.inf_byte is not None:
                return self.inf_byte | sbit
            if self.fmt == "e4m3" and self.specials == "ieee":
                return self.nan_byte
            return self.grid_bytes[-1] | sbit
        i = bisect_left(self.grid_vals, a)
        if i < len(self.grid_vals) and self.grid_vals[i] == a:
            byte = self.grid_bytes[i]
        else:
            lo_v, lo_b = self.grid_vals[i - 1], self.grid_bytes[i - 1]
            hi_v, hi_b = self.grid_vals[i], self.grid_bytes[i]
            if self.rounding == "rtz":
                byte = lo_b
            else:
                dlo, dhi = a - lo_v, hi_v - a
                if dlo < dhi:
                    byte = lo_b
                elif dhi < dlo:
                    byte = hi_b
                elif self.rounding == "rna":
                    byte = hi_b
                else:  # rne
                    byte = lo_b if lo_b % 2 == 0 else hi_b
        v = self.grid_vals[self.grid_bytes.index(byte)] if False else None
        # cheaper: recompute decode
        val = self._decode_raw(byte)
        if self.ftz and val != 0.0 and abs(val) < self.min_normal:
            return sbit
        if val == 0.0:
            return sbit
        return byte | sbit


def fdiv(a: float, b: float) -> float:
    try:
        return a / b
    except ZeroDivisionError:
        if a == 0.0 or math.isnan(a):
            return math.nan
        return math.copysign(math.inf, a) * math.copysign(1.0, b)


OPS = {
    "add": lambda a, b: a + b,
    "sub": lambda a, b: a - b,
    "mul": lambda a, b: a * b,
    "div": fdiv,
    "min": lambda a, b: min(a, b) if not (math.isnan(a) or math.isnan(b)) else math.nan,
    "max": lambda a, b: max(a, b) if not (math.isnan(a) or math.isnan(b)) else math.nan,
}
NONCOMM = {"sub", "div"}


def decode_fp16(h: int, daz: bool) -> float:
    s, e, m = (h >> 15) & 1, (h >> 10) & 0x1F, h & 0x3FF
    sign = -1.0 if s else 1.0
    if e == 0x1F:
        return math.inf * sign if m == 0 else math.nan
    if e == 0:
        return math.copysign(0.0, sign) if daz else sign * (m / 1024.0) * 2.0 ** -14
    return sign * (1 + m / 1024.0) * 2.0 ** (e - 15)


def decode_bf16(h: int, daz: bool) -> float:
    s, e, m = (h >> 15) & 1, (h >> 7) & 0xFF, h & 0x7F
    sign = -1.0 if s else 1.0
    if e == 0xFF:
        return math.inf * sign if m == 0 else math.nan
    if e == 0:
        return math.copysign(0.0, sign) if daz else sign * (m / 128.0) * 2.0 ** -126
    return sign * (1 + m / 128.0) * 2.0 ** (e - 127)


def check_fp8_binary(out_arr, rows, codec: Fp8, opname, swap: bool, nan_mode: str) -> int:
    opfn = OPS[opname]
    mism = 0
    for r in rows:
        a8 = (r >> 8) & 0xFF
        b8 = r & 0xFF
        if swap:
            a8, b8 = b8, a8
        va, vb = codec.dec[a8], codec.dec[b8]
        res = opfn(va, vb)
        if math.isnan(res) and nan_mode != "canonical":
            if nan_mode == "prop_a":
                got = a8 if math.isnan(va) else (b8 if math.isnan(vb) else codec.nan_byte)
            else:
                got = b8 if math.isnan(vb) else (a8 if math.isnan(va) else codec.nan_byte)
        else:
            got = codec.encode(res)
        if got != out_arr[r]:
            mism += 1
    return mism


def main() -> None:
    full = "--full" in sys.argv
    sample = list(range(0, 1 << 16, 251))
    for case in CASES:
        truth = ROOT / "benchmarks" / f"{case}.truth"
        if not truth.is_file():
            continue
        t = read_truth(truth)
        if t.num_inputs != 16 or t.num_outputs != 8:
            continue
        n_rows = 1 << 16
        out_lsb = [0] * n_rows
        for j in range(8):
            col = t.outputs[j]
            for r in range(n_rows):
                if col[r]:
                    out_lsb[r] |= 1 << j
        out_msb = [BITREV8[b] for b in out_lsb]

        results = []

        # ---- fp8 binary ops ----
        for fmt in ("e4m3", "e5m2"):
            for specials in ("ieee", "none"):
                nan_opts = ((0x7F, 0xFF) if fmt == "e4m3" else (0x7E, 0x7F, 0xFF)) if specials == "ieee" else (0x7F,)
                for daz in (False, True):
                    for ftz in (False, True):
                        for sat in (True, False):
                            if specials == "none" and not sat:
                                continue
                            for rounding in ("rne", "rna", "rtz"):
                                for nan_byte in nan_opts:
                                    codec = Fp8(fmt, specials, daz, ftz, sat, rounding, nan_byte)
                                    for opname in OPS:
                                        swaps = (False, True) if opname in NONCOMM else (False,)
                                        nan_modes = ("canonical", "prop_a", "prop_b") if specials == "ieee" else ("canonical",)
                                        for swap in swaps:
                                            for nan_mode in nan_modes:
                                                for out_name, out_arr in (("lsb", out_lsb), ("msb", out_msb)):
                                                    m = check_fp8_binary(out_arr, sample, codec, opname, swap, nan_mode)
                                                    desc = (f"fp8-{opname} {fmt} spec={specials} daz={int(daz)} ftz={int(ftz)} "
                                                            f"sat={int(sat)} rnd={rounding} nan={nan_byte:02x}/{nan_mode} "
                                                            f"swap={int(swap)} out={out_name}")
                                                    results.append((m, desc, ("fp8", codec, opname, swap, nan_mode, out_arr)))

        # ---- int8 ops ----
        for signed in (False, True):
            for opname in ("add", "sub", "mul"):
                for mode in ("wrap", "sat"):
                    for swap in ((False, True) if opname == "sub" else (False,)):
                        for out_name, out_arr in (("lsb", out_lsb), ("msb", out_msb)):
                            for inrev in (False, True):
                                mism = 0
                                for r in sample:
                                    a8 = (r >> 8) & 0xFF
                                    b8 = r & 0xFF
                                    if inrev:
                                        a8, b8 = BITREV8[a8], BITREV8[b8]
                                    if swap:
                                        a8, b8 = b8, a8
                                    ia = a8 - 256 if signed and a8 >= 128 else a8
                                    ib = b8 - 256 if signed and b8 >= 128 else b8
                                    v = {"add": ia + ib, "sub": ia - ib, "mul": ia * ib}[opname]
                                    if mode == "sat":
                                        lo, hi = (-128, 127) if signed else (0, 255)
                                        v = max(lo, min(hi, v))
                                    got = v & 0xFF
                                    if got != out_arr[r]:
                                        mism += 1
                                desc = f"int8-{opname} signed={int(signed)} {mode} swap={int(swap)} inrev={int(inrev)} out={out_name}"
                                results.append((mism, desc, None))

        # ---- conversions ----
        for srcname, decfn in (("fp16", decode_fp16), ("bf16", decode_bf16)):
            for fmt in ("e4m3", "e5m2"):
                for specials in ("ieee", "none"):
                    nan_opts = ((0x7F, 0xFF) if fmt == "e4m3" else (0x7E, 0x7F)) if specials == "ieee" else (0x7F,)
                    for daz in (False, True):
                        for ftz in (False, True):
                            for sat in (True, False):
                                if specials == "none" and not sat:
                                    continue
                                for rounding in ("rne", "rna", "rtz"):
                                    for nan_byte in nan_opts:
                                        codec = Fp8(fmt, specials, daz, ftz, sat, rounding, nan_byte)
                                        for out_name, out_arr in (("lsb", out_lsb), ("msb", out_msb)):
                                            mism = 0
                                            for r in sample:
                                                got = codec.encode(decfn(r, daz))
                                                if got != out_arr[r]:
                                                    mism += 1
                                            desc = (f"cvt {srcname}->{fmt} spec={specials} daz={int(daz)} ftz={int(ftz)} "
                                                    f"sat={int(sat)} rnd={rounding} nan={nan_byte:02x} out={out_name}")
                                            results.append((mism, desc, None))

        results.sort(key=lambda x: x[0])
        n_s = len(sample)
        best_m, best_d, best_ctx = results[0]
        line = f"{case}: best {best_m}/{n_s}  {best_d}"
        if best_m == 0 and best_ctx and best_ctx[0] == "fp8":
            _, codec, opname, swap, nan_mode, out_arr = best_ctx
            fm = check_fp8_binary(out_arr, range(n_rows), codec, opname, swap, nan_mode)
            line += f"  FULL={fm}/65536" + (" *** EXACT ***" if fm == 0 else "")
        print(line)
        seen = {best_d.split(" out=")[0]}
        shown = 0
        for m, d, _ in results[1:]:
            k = d.split(" out=")[0]
            if k in seen:
                continue
            seen.add(k)
            print(f"         alt {m}/{n_s}: {d}")
            shown += 1
            if shown >= 2:
                break
        sys.stdout.flush()


if __name__ == "__main__":
    main()
