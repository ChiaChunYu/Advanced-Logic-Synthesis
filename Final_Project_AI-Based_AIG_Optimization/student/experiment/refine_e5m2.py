#!/usr/bin/env python3
"""Full-check the near-miss e5m2 hypotheses (ex245/246/247) and dump diffs."""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth
from identify_fp8 import Fp8, OPS

CONFIGS = [
    # case, op, fmt, specials, daz, ftz, sat, rounding, nan_byte, swap
    ("ex245", "add", "e5m2", "none", False, False, True, "rne", 0x7F, False),
    ("ex246", "mul", "e5m2", "none", False, False, True, "rne", 0x7F, False),
    ("ex247", "div", "e5m2", "none", False, False, True, "rne", 0x7F, True),
]


def main() -> None:
    for case, opname, fmt, spec, daz, ftz, sat, rnd, nanb, swap in CONFIGS:
        t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
        n = 1 << 16
        out = [0] * n
        for j in range(8):
            col = t.outputs[j]
            for r in range(n):
                if col[r]:
                    out[r] |= 1 << j
        codec = Fp8(fmt, spec, daz, ftz, sat, rnd, nanb)
        opfn = OPS[opname]
        mism = []
        for r in range(n):
            a8 = (r >> 8) & 0xFF
            b8 = r & 0xFF
            if swap:
                a8, b8 = b8, a8
            res = opfn(codec.dec[a8], codec.dec[b8])
            got = codec.encode(res)
            if got != out[r if not swap else r] :
                mism.append((a8, b8, out[r], got))
        print(f"{case} {opname} {fmt} spec={spec}: {len(mism)} mismatches / 65536")
        for a8, b8, want, got in mism[:15]:
            va, vb = codec.dec[a8], codec.dec[b8]
            res = opfn(va, vb)
            print(f"  a={a8:02x}({va:g}) b={b8:02x}({vb:g}) res={res:g} want={want:02x}({codec.dec[want]:g}) got={got:02x}({codec.dec[got]:g})")
        print()


if __name__ == "__main__":
    main()
