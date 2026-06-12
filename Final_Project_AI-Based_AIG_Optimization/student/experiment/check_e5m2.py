#!/usr/bin/env python3
"""Confirmed e5m2 (no-inf) semantics for ex245 (add) / ex246 (mul).

Key finding: these are e5m2 (1s/5e/2m, bias 15) but WITHOUT infinities.
Only 0x7f and 0xff are NaN; 0x7c/0x7d/0x7e are ordinary finite numbers.
Any operation touching a NaN returns canonical 0x7f. Overflow saturates to
the max finite magnitude (0x7e / 0xfe). RNE rounding, ties to even byte.

Both verified at 0 mismatches over all 65536 input rows.
"""
from __future__ import annotations

import math
import sys
from bisect import bisect_left
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth


def decode(b: int) -> float:
    s = (b >> 7) & 1
    e = (b >> 2) & 0x1F
    m = b & 3
    sign = -1.0 if s else 1.0
    if e == 0:
        return sign * (m / 4) * 2.0 ** (1 - 15)
    return sign * (1 + m / 4) * 2.0 ** (e - 15)


VALS = [decode(b) for b in range(256)]
_grid = sorted((VALS[b], b) for b in range(0x7f))   # finite magnitudes 0x00..0x7e
GRID_V = [v for v, _ in _grid]
GRID_B = [b for _, b in _grid]
MAXV = GRID_V[-1]


def encode(x: float) -> int:
    if x == 0.0:
        return 0x80 if math.copysign(1.0, x) < 0 else 0x00
    neg = x < 0
    a = abs(x)
    sb = 0x80 if neg else 0
    if a >= MAXV:
        return sb | GRID_B[-1]
    i = bisect_left(GRID_V, a)
    if i < len(GRID_V) and GRID_V[i] == a:
        return sb | GRID_B[i]
    lo_v, lo_b = GRID_V[i - 1], GRID_B[i - 1]
    hi_v, hi_b = GRID_V[i], GRID_B[i]
    dlo, dhi = a - lo_v, hi_v - a
    if dlo < dhi:
        b = lo_b
    elif dhi < dlo:
        b = hi_b
    else:
        b = lo_b if lo_b % 2 == 0 else hi_b
    return sb | b


def is_nan(b: int) -> bool:
    return b in (0x7f, 0xff)


def op_byte(a8: int, b8: int, op: str) -> int:
    if is_nan(a8) or is_nan(b8):
        return 0x7f
    return encode(VALS[a8] * VALS[b8] if op == "mul" else VALS[a8] + VALS[b8])


def check(case: str, op: str) -> int:
    t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
    n = 1 << 16
    out = [0] * n
    for j in range(8):
        col = t.outputs[j]
        for r in range(n):
            if col[r]:
                out[r] |= 1 << j
    mism = sum(1 for r in range(n) if op_byte((r >> 8) & 0xFF, r & 0xFF, op) != out[r])
    print(f"{case} e5m2-{op} (no-inf): {mism} mismatches")
    return mism


if __name__ == "__main__":
    check("ex245", "add")
    check("ex246", "mul")
