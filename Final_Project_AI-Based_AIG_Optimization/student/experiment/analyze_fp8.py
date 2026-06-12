#!/usr/bin/env python3
"""
Analyze ex246/247/248 to identify BF16->FP8 conversion format.
Prints special-value mappings and tries to reverse-engineer the FP8 format.
"""
import sys
sys.set_int_max_str_digits(200000)
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"

def read_truth(path):
    lines = [l for l in Path(path).read_text().strip().splitlines() if l.strip()]
    n_entries = len(lines[0])
    n_in = n_entries.bit_length() - 1
    return n_in, lines

def get_output(outs, n_out, idx):
    val = 0
    for b in range(n_out):
        val |= int(outs[b][idx]) << (n_out - 1 - b)
    return val

def bf16_to_parts(x):
    sign = (x >> 15) & 1
    exp  = (x >> 7) & 0xFF
    mant = x & 0x7F
    return sign, exp, mant

def bf16_to_float(x):
    import struct
    # BF16 is just the upper 16 bits of float32
    f32_bits = x << 16
    return struct.unpack('f', f32_bits.to_bytes(4, 'big'))[0]

def analyze_case(case):
    print(f"\n{'='*60}")
    print(f"  {case}")
    print(f"{'='*60}")
    n_in, outs = read_truth(BENCH / f"{case}.truth")
    n_out = len(outs)
    N = 2**n_in
    print(f"  {n_in} inputs, {n_out} outputs, {N} entries")

    # Special BF16 values
    specials = [
        ("+0",    0x0000), ("-0",    0x8000),
        ("+inf",  0x7F80), ("-inf",  0xFF80),
        ("+NaN",  0x7FC0), ("-NaN",  0xFFC0),
        ("+NaN2", 0x7FFF), ("-NaN2", 0xFFFF),
        ("+1.0",  0x3F80), ("-1.0",  0xBF80),
        ("+2.0",  0x4000), ("-2.0",  0xC000),
        ("+0.5",  0x3F00), ("-0.5",  0xBF00),
        ("+max",  0x7F7F), ("-max",  0xFF7F),
        ("+min_normal", 0x0080), ("+min_subnorm", 0x0001),
    ]
    print("\n  Special values:")
    for name, val in specials:
        out = get_output(outs, n_out, val)
        s, e, m = bf16_to_parts(val)
        print(f"    {name:15s} bf16=0x{val:04X}(s={s},e={e:3d},m={m:3d}) -> fp8=0x{out:02X} = {out:08b}")

    # Count unique outputs
    unique = set()
    for i in range(N):
        unique.add(get_output(outs, n_out, i))
    print(f"\n  Unique output values: {len(unique)}")
    print(f"  Max output value: 0x{max(unique):02X}")
    print(f"  Output 0x00 count: {sum(1 for i in range(N) if get_output(outs,n_out,i)==0)}")
    print(f"  Output 0xFF count: {sum(1 for i in range(N) if get_output(outs,n_out,i)==0xFF)}")
    print(f"  Output 0xFE count: {sum(1 for i in range(N) if get_output(outs,n_out,i)==0xFE)}")
    print(f"  Output 0x7F count: {sum(1 for i in range(N) if get_output(outs,n_out,i)==0x7F)}")
    print(f"  Output 0x80 count: {sum(1 for i in range(N) if get_output(outs,n_out,i)==0x80)}")

    # Check sign symmetry: f(-x) = f(x) with MSB flipped?
    sign_sym = True
    asym_examples = []
    for i in range(min(N//2, 8192)):
        pos_out = get_output(outs, n_out, i)
        neg_out = get_output(outs, n_out, i | 0x8000)
        if (pos_out ^ neg_out) != 0x80 and (pos_out ^ neg_out) != 0x00:
            if len(asym_examples) < 3:
                asym_examples.append((i, pos_out, neg_out, pos_out ^ neg_out))
            sign_sym = False
    if sign_sym:
        print(f"\n  Sign symmetry: f(-x) = f(x) XOR 0x80  (expected for signed FP8)")
    else:
        print(f"\n  Sign asymmetric (first violations): {asym_examples}")

    # Check exponent linearity for mantissa=0
    # For BF16 normal, varying exponent: 0x0080, 0x0100, 0x0180, ..., 0x7F80
    print("\n  Exponent sweep (mantissa=0, sign=0):")
    prev_out = None
    for e in range(0, 256, 16):
        val = e << 7
        out = get_output(outs, n_out, val)
        s, ev, m = bf16_to_parts(val)
        diff = (out - prev_out) if prev_out is not None else 0
        print(f"    exp={e:3d} bf16=0x{val:04X} -> 0x{out:02X} ({out:3d}) diff={diff:+d}")
        prev_out = out

    # Look at output bit structure
    print("\n  Output bit[7] (sign?) distribution:")
    bit7_0 = sum(1 for i in range(N) if (get_output(outs,n_out,i)>>7)==0)
    bit7_1 = sum(1 for i in range(N) if (get_output(outs,n_out,i)>>7)==1)
    print(f"    bit7=0: {bit7_0}, bit7=1: {bit7_1}")
    pos_with_0 = sum(1 for i in range(N//2) if (get_output(outs,n_out,i)>>7)==0)
    print(f"    Positive inputs (MSB=0) with bit7=0: {pos_with_0}/{N//2}")

if __name__ == "__main__":
    for case in ["ex246", "ex247", "ex248"]:
        analyze_case(case)
