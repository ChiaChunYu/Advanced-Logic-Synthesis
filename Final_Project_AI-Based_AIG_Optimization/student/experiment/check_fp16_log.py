#!/usr/bin/env python3
"""Python emulation of an fp16 log2 datapath (LUT + fixed-point + fp16 encode).

Goal: a hardware-shaped algorithm that is bit-exact with ex224 so it can be
translated to Verilog. Structure:

  x = (-1)^s * (1 + m/1024) * 2^(e-15)          [normal]
  log2(x) = (e - 15) + log2(1 + m/1024)
          = int_part            + frac_part in [0,1)

  frac_part = LUT2[m]   (10-bit address, fixed-point fraction)
  result    = (e - 15) + frac_part   (signed fixed-point)
  encode result back to fp16 (RNE).

Specials (DAZ): subnormal/zero input -> log2(0) = -inf (0xfc00);
negative input -> NaN (0x7e00); +inf -> +inf (0x7c00); NaN -> NaN.

We pick a fixed-point fraction width F and a LUT built by rounding
log2(1+m/1024) to F bits, then verify the whole pipeline against the truth
table. If 0 mismatch, the same constants/structure go into Verilog.
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth


def fp16_dec(h: int) -> float:
    return float(np.frombuffer(struct.pack("<H", h), dtype=np.float16)[0])


def fp16_enc(x: float) -> int:
    return int(np.frombuffer(np.float16(x).tobytes(), dtype=np.uint16)[0])


def build_truth(case: str) -> list[int]:
    t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
    n = 1 << 16
    out = [0] * n
    for j in range(16):
        col = t.outputs[j]
        for r in range(n):
            if col[r]:
                out[r] |= 1 << j
    return out


def emulate(case: str, F: int) -> int:
    """Fixed-point log2 with F fractional bits. Returns mismatch count."""
    out = build_truth(case)
    scale = 1 << F
    # LUT: round(log2(1+m/1024) * 2^F) for m in 0..1023, value in [0, 2^F)
    lut = [round(math.log2(1 + m / 1024) * scale) for m in range(1024)]
    mism = 0
    examples = []
    for h in range(1 << 16):
        s = (h >> 15) & 1
        e = (h >> 10) & 0x1F
        m = h & 0x3FF
        # specials
        if e == 0x1F:
            got = 0x7c00 if (m == 0 and s == 0) else 0x7e00  # +inf->+inf else NaN
        elif e == 0:
            got = 0xfc00                       # DAZ: subnormal/zero -> log2(0) = -inf
        elif s == 1:
            got = 0x7e00                       # negative normal -> NaN
        else:
            # fixed-point result = (e-15) + lut[m]/2^F  (signed)
            int_part = e - 15
            fixed = int_part * scale + lut[m]   # signed integer, units 2^-F
            # convert fixed-point (value = fixed / 2^F) to float and encode
            val = fixed / scale
            got = fp16_enc(val)
        if got != out[h]:
            mism += 1
            if len(examples) < 6:
                examples.append((h, out[h], got))
    if mism and examples:
        for h, w, g in examples:
            print(f"    in={h:04x}({fp16_dec(h):.5g}) want={w:04x} got={g:04x}")
    return mism


def main() -> None:
    for F in (16, 20, 24):
        m = emulate("ex224", F)
        print(f"ex224 log2 fixed-point F={F}: {m} mismatches")
        if m == 0:
            print(f"  *** F={F} is bit-exact ***")
            break


if __name__ == "__main__":
    main()
