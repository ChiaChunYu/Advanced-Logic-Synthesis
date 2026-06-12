#!/usr/bin/env python3
"""Full 65536-row verification of identified fp8 hypotheses + mismatch dumps."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth
from identify_fp8 import Fp8, BITREV8, OPS

HYPOTHESES = [
    # case, op, fmt, daz, ftz, sat, nan_byte
    ("ex240", "add", "e4m3", False, False, True, 0x7F),
    ("ex241", "mul", "e4m3", False, False, True, 0x7F),
    ("ex245", "add", "e5m2", False, False, False, 0x7F),
    ("ex246", "mul", "e5m2", False, False, False, 0x7F),
]


def main() -> None:
    for case, opname, fmt, daz, ftz, sat, nan_byte in HYPOTHESES:
        t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
        n_rows = 1 << 16
        out = [0] * n_rows
        for j in range(8):
            col = t.outputs[j]
            for r in range(n_rows):
                if col[r]:
                    out[r] |= 1 << j  # y_j = bit j (LSB-first, "out=lsb")

        codec = Fp8(fmt, daz, ftz, sat, nan_byte)
        opfn = OPS[opname]
        mism = []
        for r in range(n_rows):
            a8 = (r >> 8) & 0xFF
            b8 = r & 0xFF
            res = opfn(codec.dec[a8], codec.dec[b8])
            got = codec.encode(res)
            if got != out[r]:
                mism.append((a8, b8, out[r], got))
        print(f"{case} fp8-{opname} {fmt}: {len(mism)} mismatches / 65536")
        for a8, b8, want, got in mism[:12]:
            va, vb = codec.dec[a8], codec.dec[b8]
            try:
                res = opfn(va, vb)
            except Exception:
                res = math.nan
            print(f"  a={a8:02x}({va}) b={b8:02x}({vb}) res={res} want={want:02x}({codec.dec[want]}) got={got:02x}({codec.dec[got]})")
        print()


if __name__ == "__main__":
    main()
