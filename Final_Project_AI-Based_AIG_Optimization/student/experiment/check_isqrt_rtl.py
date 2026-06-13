#!/usr/bin/env python3
"""Verify a hardware isqrt (non-restoring, bit-by-bit) matches ex275-279.

Standard restoring/non-restoring integer sqrt: process two input bits per
output bit, from the MSB pair down. This is the shape that synthesizes well and
is easy to translate to Verilog.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth


def isqrt_hw(x: int, in_bits: int) -> int:
    """Bit-by-bit integer sqrt producing in_bits//2 result bits."""
    out_bits = in_bits // 2
    rem = 0
    root = 0
    for i in range(out_bits - 1, -1, -1):
        # bring down two bits of x at position 2i
        rem = (rem << 2) | ((x >> (2 * i)) & 0b11)
        trial = (root << 2) | 1
        root <<= 1
        if rem >= trial:
            rem -= trial
            root |= 1
    return root


def check(case: str) -> int:
    t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
    N = t.num_inputs
    nout = t.num_outputs
    n = 1 << N
    out = [0] * n
    for j in range(nout):
        col = t.outputs[j]
        for r in range(n):
            if col[r]:
                out[r] |= 1 << j
    mism = sum(1 for x in range(n) if isqrt_hw(x, N) != out[x])
    # also cross-check against math.isqrt
    mism_ref = sum(1 for x in range(n) if math.isqrt(x) != out[x])
    print(f"{case}: {N}/{nout}  hw_isqrt_mism={mism}  math_isqrt_mism={mism_ref}")
    return mism


if __name__ == "__main__":
    for c in ("ex275", "ex276", "ex277", "ex278", "ex279"):
        check(c)
