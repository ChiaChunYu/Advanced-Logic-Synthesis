#!/usr/bin/env python3
"""Bit-exact Python emulation of the fp8 RTL datapaths in fp8_synth.py.

Validates the algorithm against the truth tables BEFORE running yosys/ABC,
so logic bugs surface instantly with concrete counterexamples.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth


def round18(mag: int) -> int:
    """Mirror of the Verilog round18 function (e4m3). mag in units 2^-18."""
    if mag == 0:
        return 0
    p = mag.bit_length() - 1
    if mag < (8 << 9):
        mr = (mag >> 9) & 7
        g = (mag >> 8) & 1
        s = 1 if (mag & 0xFF) else 0
        rb = g & (s | ((mag >> 9) & 1))
        km = mr + rb
        if km & 8:
            return (1 << 3) | 0
        return km & 7
    er = p - 11
    mr = (mag >> (p - 3)) & 7
    g = (mag >> (p - 4)) & 1
    s = 1 if (mag & ((1 << (p - 4)) - 1)) else 0
    rb = g & (s | (mr & 1))
    km = (0b1000 | mr) + rb  # {1, mr} + rb in 5 bits
    if km & 0b10000:
        er += 1
        mr = 0
    else:
        mr = km & 7
    if er > 15 or (er == 15 and mr == 7):
        return (15 << 3) | 6
    return (er << 3) | mr


def decode(byte: int) -> tuple[int, int, int, int, int]:
    s = (byte >> 7) & 1
    e = (byte >> 3) & 0xF
    m = byte & 7
    nan = (e == 0xF and m == 7)
    sig = m if e == 0 else (8 | m)
    eeff = 1 if e == 0 else e
    return s, sig, eeff, nan, e


def fp8_add(a8: int, b8: int) -> int:
    sa, siga, eaeff, nana, _ = decode(a8)
    sb, sigb, ebeff, nanb, _ = decode(b8)
    if nana or nanb:
        return 0x7F
    maga = siga << (eaeff - 1)
    magb = sigb << (ebeff - 1)
    va = -maga if sa else maga
    vb = -magb if sb else magb
    ssum = va + vb
    neg = ssum < 0
    mag = -ssum if neg else ssum
    em = round18(mag << 9)
    if mag == 0:
        sout = sa & sb
        return (sout << 7)
    return (int(neg) << 7) | em


def fp8_mul(a8: int, b8: int) -> int:
    sa, siga, eaeff, nana, _ = decode(a8)
    sb, sigb, ebeff, nanb, _ = decode(b8)
    if nana or nanb:
        return 0x7F
    prod = siga * sigb
    sout = sa ^ sb
    if prod == 0:
        return sout << 7
    esum = eaeff + ebeff
    mag = prod << (esum - 2)
    em = round18(mag)
    return (sout << 7) | em


def fp8_div_ba(a8: int, b8: int) -> int:
    """result = B / A."""
    sa, siga, eaeff, nana, _ = decode(a8)
    sb, sigb, ebeff, nanb, _ = decode(b8)
    if nana or nanb:
        return 0x7F
    sout = sa ^ sb
    if siga == 0 and sigb == 0:
        return 0x7F           # 0/0
    if sigb == 0:
        return sout << 7      # 0/x
    if siga == 0:
        return (sout << 7) | (15 << 3) | 6   # x/0 -> saturate (no inf)
    numer = sigb << 20
    quo = numer // siga
    exact = (quo * siga) == numer
    shl = 14 + ebeff - eaeff
    wide = quo << shl
    mag = wide >> 16
    sticky_low = (wide & 0xFFFF) != 0 or not exact
    mag_adj = mag | (1 if sticky_low else 0)
    em = round18(mag_adj)
    return (sout << 7) | em


def check(case: str, fn) -> None:
    t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
    n = 1 << 16
    out = [0] * n
    for j in range(8):
        col = t.outputs[j]
        for r in range(n):
            if col[r]:
                out[r] |= 1 << j
    mism = []
    for r in range(n):
        a8 = (r >> 8) & 0xFF
        b8 = r & 0xFF
        got = fn(a8, b8)
        if got != out[r]:
            mism.append((a8, b8, out[r], got))
    print(f"{case}: {len(mism)} mismatches / 65536")
    for a8, b8, want, got in mism[:10]:
        print(f"  a={a8:02x} b={b8:02x} want={want:02x} got={got:02x}")


if __name__ == "__main__":
    check("ex240", fp8_add)
    check("ex241", fp8_mul)
    check("ex242", fp8_div_ba)
