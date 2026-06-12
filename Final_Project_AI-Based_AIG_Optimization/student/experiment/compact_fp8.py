#!/usr/bin/env python3
"""Compact FPU-style fp8 e4m3 algorithms (RTL-shaped), verified against truth.

These mirror the intended Verilog structure operation-for-operation so the
translation to RTL is mechanical.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth


def dec(byte):
    s = (byte >> 7) & 1
    e = (byte >> 3) & 0xF
    m = byte & 7
    nan = (e == 0xF) and (m == 7)
    sig = m if e == 0 else (8 | m)
    eeff = 1 if e == 0 else e
    return s, e, m, sig, eeff, nan


def pack(s, e, m):
    return (s << 7) | (e << 3) | m


def round_rne(sig4, g, r, s_bit, e):
    """Round {sig4, g, r, s} (sig4 has hidden bit at bit3) -> (e, m) with sat."""
    sticky = r | s_bit
    rb = g & (sticky | (sig4 & 1))
    sig_r = sig4 + rb
    if sig_r & 0x10:          # mantissa carry: 1111 + 1 -> 10000
        sig_r >>= 1
        e += 1
    if sig_r & 8:             # normal
        m = sig_r & 7
        if e > 15 or (e == 15 and m == 7):
            return 15, 6      # saturate to 448
        return e, m
    # subnormal result (hidden bit 0): e field = 0
    return 0, sig_r & 7


def fp8_add_compact(a8, b8):
    sa, ea, ma, siga, eaeff, nana = dec(a8)
    sb, eb, mb, sigb, ebeff, nanb = dec(b8)
    if nana or nanb:
        return 0x7F
    # order by magnitude: 7-bit field compare works monotonically
    swap = (b8 & 0x7F) > (a8 & 0x7F)
    if swap:
        (sx, ex, sigx) = (sb, ebeff, sigb)
        (sy, ey, sigy) = (sa, eaeff, siga)
    else:
        (sx, ex, sigx) = (sa, eaeff, siga)
        (sy, ey, sigy) = (sb, ebeff, sigb)
    d = ex - ey  # >= 0
    # align Y into {sig,G,R} with sticky
    ywide = sigy << 2          # 6 bits: sig4 + G + R
    if d == 0:
        ysh, ysticky = ywide, 0
    elif d <= 5:
        ysh = ywide >> d
        ysticky = 1 if (ywide & ((1 << d) - 1)) else 0
    else:
        ysh, ysticky = 0, 1 if sigy else 0
    xwide = sigx << 2          # 6 bits
    sub = sa ^ sb
    if sub:
        msum = xwide - ysh - ysticky   # borrow from sticky: conservative
        # exact subtraction with sticky: represent as value*4 - eps
        # handle as integer with sticky kept separate below
        msum = xwide - ysh
        borrow_sticky = ysticky        # remaining sticky reduces magnitude
    else:
        msum = xwide + ysh
        borrow_sticky = 0
        add_sticky = ysticky
    if sub:
        if msum == 0 and borrow_sticky == 0:
            # exact cancel -> +0 ; both -0 -> -0
            szero = sa & sb
            return szero << 7
        if borrow_sticky:
            msum -= 1
            sticky_in = 1     # the subtracted fraction leaves nonzero sticky
        else:
            sticky_in = 0
    else:
        sticky_in = add_sticky

    # msum: up to 7 bits (carry at bit6) in units of 2^-2 of sig lsb
    e = ex
    if not sub and (msum & 0x40):       # carry out: shift right 1
        sticky_in |= msum & 1
        msum >>= 1
        e += 1
    # normalize left for subtraction (hidden bit at bit5 of msum)
    while not (msum & 0x20) and e > 1 and msum != 0:
        msum <<= 1
        e -= 1
    if msum == 0 and sticky_in == 0:
        szero = sa & sb
        return szero << 7
    sig4 = (msum >> 2) & 0xF
    g = (msum >> 1) & 1
    r = msum & 1
    er, mr = round_rne(sig4, g, r, sticky_in, e)
    sout = sx
    return pack(sout, er, mr)


def fp8_mul_compact(a8, b8):
    sa, ea, ma, siga, eaeff, nana = dec(a8)
    sb, eb, mb, sigb, ebeff, nanb = dec(b8)
    if nana or nanb:
        return 0x7F
    sout = sa ^ sb
    if siga == 0 or sigb == 0:
        return sout << 7
    prod = siga * sigb           # 8 bits, value = prod * 2^-6 * 2^(ea+eb-14)
    e = eaeff + ebeff - 7        # tentative: prod in [1,225]; treat prod as
    #                              fixed-point with hidden at bit6 (prod>=64)
    # normalize prod to hidden at bit6 (i.e. [64,127]): value=prod*2^(e-13)...
    # simpler: shift so MSB at bit7..  let's place hidden at bit 6:
    sticky = 0
    while prod & 0x80:           # prod >= 128: shift right (at most 1)
        sticky |= prod & 1
        prod >>= 1
        e += 1
    while not (prod & 0x40) and e > -8:   # normalize left while subnormal-capable
        if e <= 1 - 7 + 6:       # guard: allow going to subnormal domain later
            pass
        prod <<= 1
        e -= 1
        if e <= -8:
            break
    # now hidden at bit6; value = (prod/64) * 2^(e-7+6)?  -- calibrate below
    # We calibrate empirically: value = (prod / 2^6) * 2^(e - 7)
    # convert to fp8: if e >= 1: sig4 = prod>>3 bits [6:3], g=bit2,r=bit1,s=bit0|sticky
    if e >= 1:
        sig4 = (prod >> 3) & 0xF
        g = (prod >> 2) & 1
        r = (prod >> 1) & 1
        s_b = (prod & 1) | sticky
        er, mr = round_rne(sig4, g, r, s_b, e)
        return pack(sout, er, mr)
    # subnormal: need right shift by (1 - e)
    sh = 1 - e
    if sh > 10:
        return sout << 7
    wide = prod
    sticky2 = sticky | (1 if (wide & ((1 << sh) - 1)) else 0)
    wide >>= sh
    sig4 = (wide >> 3) & 0xF
    g = (wide >> 2) & 1
    r = (wide >> 1) & 1
    s_b = (wide & 1) | sticky2
    er, mr = round_rne(sig4, g, r, s_b, 1)
    return pack(sout, er, mr)


def check(case, fn, limit=10):
    t = read_truth(ROOT / "benchmarks" / f"{case}.truth")
    n = 1 << 16
    out = [0] * n
    for j in range(8):
        col = t.outputs[j]
        for r in range(n):
            if col[r]:
                out[r] |= 1 << j
    mism = []
    for rr in range(n):
        a8 = (rr >> 8) & 0xFF
        b8 = rr & 0xFF
        got = fn(a8, b8)
        if got != out[rr]:
            mism.append((a8, b8, out[rr], got))
    print(f"{case}: {len(mism)} mismatches")
    for a8, b8, want, got in mism[:limit]:
        print(f"  a={a8:02x} b={b8:02x} want={want:02x} got={got:02x}")
    return len(mism)


if __name__ == "__main__":
    check("ex240", fp8_add_compact)
    check("ex241", fp8_mul_compact)
