#!/usr/bin/env python3
"""
Reverse-engineer AIG benchmark truth tables.
For each benchmark: parse I/O structure, sample I/O pairs, identify function.
"""
import os
import sys
import struct
import random

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'


def load_truth(name):
    """Load truth table. Returns (n_inputs, n_outputs, list_of_output_bitvectors).
    Each output bitvector is a list of bits indexed by input integer value."""
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f:
        data = f.read()
    lines = data.split(b'\n')
    lines = [l for l in lines if l.strip()]
    n_outputs = len(lines)
    tt_len = len(lines[0])
    n_inputs = tt_len.bit_length() - 1
    # Parse each output row as array of bits
    outputs = []
    for line in lines:
        bits = [int(b) - 48 for b in line]  # b'0'=48, b'1'=49
        outputs.append(bits)
    return n_inputs, n_outputs, outputs


def eval_func(outputs, input_val):
    """Given input integer, return output integer."""
    result = 0
    for i, out_bits in enumerate(outputs):
        bit = out_bits[input_val]
        result |= (bit << (len(outputs) - 1 - i))
    return result


def sample_io(n_inputs, n_outputs, outputs, n_samples=32, seed=42):
    """Sample random input->output pairs."""
    random.seed(seed)
    max_val = 2**n_inputs
    samples = sorted(random.sample(range(max_val), min(n_samples, max_val)))
    pairs = []
    for inp in samples:
        out = eval_func(outputs, inp)
        pairs.append((inp, out))
    return pairs


def check_constant_outputs(n_outputs, outputs):
    """Find which output bits are constant."""
    constants = []
    for i, bits in enumerate(outputs):
        ones = sum(bits)
        total = len(bits)
        if ones == 0:
            constants.append((i, 0))
        elif ones == total:
            constants.append((i, 1))
    return constants


def check_identity_outputs(n_inputs, n_outputs, outputs):
    """Check if any output bits are just input bits."""
    identity = []
    for o_idx, bits in enumerate(outputs):
        for i_idx in range(n_inputs):
            # Input bit i_idx in position i_idx from MSB
            match = True
            for inp_val in range(min(256, 2**n_inputs)):
                inp_bit = (inp_val >> (n_inputs - 1 - i_idx)) & 1
                if bits[inp_val] != inp_bit:
                    match = False
                    break
            if match:
                identity.append((o_idx, f'in[{i_idx}]'))
                break
            # Also check inverted
            match_inv = True
            for inp_val in range(min(256, 2**n_inputs)):
                inp_bit = (inp_val >> (n_inputs - 1 - i_idx)) & 1
                if bits[inp_val] != (1 - inp_bit):
                    match_inv = False
                    break
            if match_inv:
                identity.append((o_idx, f'~in[{i_idx}]'))
                break
    return identity


def analyze_bf16_unary(n_inputs, n_outputs, outputs, name):
    """For BF16 unary: 16 inputs = {sign(1), exp(8), mantissa(7)}, 16 outputs."""
    # BF16: bit 15 = sign, bits 14-7 = exponent, bits 6-0 = mantissa
    # Input encoding: MSB first, so in[0]=sign, in[1..8]=exp, in[9..15]=mantissa
    print(f"\n  [BF16 Analysis for {name}]")

    # Check some specific values
    # +0.0 = 0x0000 = 0
    # +1.0 = 0x3F80 = 0011 1111 1000 0000 = 16256
    # +inf = 0x7F80 = 0111 1111 1000 0000 = 32640
    # -0.0 = 0x8000 = 32768
    # NaN  = 0x7FC0 = 0111 1111 1100 0000 = 32704

    test_vals = {
        '+0.0': 0x0000,
        '-0.0': 0x8000,
        '+1.0': 0x3F80,
        '-1.0': 0xBF80,
        '+2.0': 0x4000,
        '+0.5': 0x3F00,
        '+inf': 0x7F80,
        '-inf': 0xFF80,
        '+NaN': 0x7FC0,
        '+3.14': 0x4049,  # approx
        '+0.1': 0x3DCC,
        '-0.5': 0xBF00,
    }

    print(f"  Specific value outputs (as hex):")
    for label, inp in test_vals.items():
        out = eval_func(outputs, inp)
        # Try to interpret output as BF16 float
        out_as_float = interpret_bf16(out)
        inp_as_float = interpret_bf16(inp)
        print(f"    {label} (0x{inp:04X} = {inp_as_float:.6g}) -> 0x{out:04X} ({interpret_bf16(out):.6g})")

    # Check if output = input (identity)
    identity_check = all(eval_func(outputs, i) == i for i in range(min(1000, 2**n_inputs)))
    print(f"  Is identity (first 1000): {identity_check}")

    # Check if output = -input (negate)
    negate_check = all(eval_func(outputs, i) == (i ^ 0x8000) for i in range(min(1000, 2**n_inputs)))
    print(f"  Is negate (flip sign bit): {negate_check}")

    # Check if output = abs(input)
    abs_check = all(eval_func(outputs, i) == (i & 0x7FFF) for i in range(min(1000, 2**n_inputs)))
    print(f"  Is abs(): {abs_check}")

    # Check if it's reciprocal 1/x
    print(f"  Checking reciprocal...")
    recip_correct = 0
    recip_total = 100
    for i in range(recip_total):
        inp = 0x3F80 + i  # Start from +1.0 going up
        out = eval_func(outputs, inp)
        inp_f = interpret_bf16(inp)
        out_f = interpret_bf16(out)
        if inp_f != 0 and abs(out_f - 1.0/inp_f) < 0.01 * abs(1.0/inp_f):
            recip_correct += 1
    print(f"  Reciprocal matches: {recip_correct}/{recip_total}")

    # Check if it's sqrt
    print(f"  Checking sqrt...")
    import math
    sqrt_correct = 0
    for i in range(100):
        inp = 0x3F80 + i * 10
        out = eval_func(outputs, inp)
        inp_f = interpret_bf16(inp)
        out_f = interpret_bf16(out)
        if inp_f >= 0 and abs(inp_f) < 1e30:
            expected = math.sqrt(abs(inp_f))
            if abs(out_f - expected) < 0.01 * expected + 1e-10:
                sqrt_correct += 1
    print(f"  Sqrt matches: {sqrt_correct}/100")

    # Check exp
    exp_correct = 0
    for i in range(50):
        inp = 0x3D00 + i * 5  # around 0.0625 to ~1.0
        out = eval_func(outputs, inp)
        inp_f = interpret_bf16(inp)
        out_f = interpret_bf16(out)
        if abs(inp_f) < 80:
            expected = math.exp(inp_f)
            if abs(expected) < 1e30 and expected > 0:
                rel_err = abs(out_f - expected) / expected
                if rel_err < 0.02:
                    exp_correct += 1
    print(f"  Exp matches: {exp_correct}/50")

    # Check log
    log_correct = 0
    for i in range(100):
        inp = 0x3F80 + i * 50  # positive values starting from 1.0
        out = eval_func(outputs, inp)
        inp_f = interpret_bf16(inp)
        out_f = interpret_bf16(out)
        if inp_f > 0 and inp_f < 1e30:
            expected = math.log(inp_f)
            if abs(expected) < 1e30:
                if abs(out_f) < 1e-30 and abs(expected) < 1e-30:
                    log_correct += 1
                elif abs(expected) > 1e-30 and abs(out_f - expected) / abs(expected) < 0.02:
                    log_correct += 1
    print(f"  Log matches: {log_correct}/100")


def interpret_bf16(val):
    """Convert 16-bit integer to BF16 float."""
    # BF16 = top 16 bits of float32
    # Reconstruct as float32 with 16 zero mantissa bits
    as_f32_bits = val << 16
    import struct
    packed = struct.pack('>I', as_f32_bits)
    f32 = struct.unpack('>f', packed)[0]
    return f32


def interpret_fp16(val):
    """Convert 16-bit integer to FP16 float."""
    import struct
    packed = struct.pack('>H', val)
    f16 = struct.unpack('>e', packed)[0]
    return f16


def analyze_float_conversion(n_inputs, n_outputs, outputs, name):
    """For float conversion (ex246-ex254): 16 inputs, 8 outputs."""
    print(f"\n  [Float Conversion Analysis for {name}]")

    # 16 inputs could be BF16 or FP16 input
    # 8 outputs could be FP8 or integer

    # Try interpreting as BF16->FP8 conversion
    # Or FP16->FP8
    # Or BF16 to some 8-bit format

    print(f"  Input: 16 bits, Output: 8 bits")
    print(f"  Trying various interpretations...")

    # Check if upper byte of input = output (just truncation)
    upper_byte_check = all(eval_func(outputs, i) == (i >> 8) for i in range(min(10000, 2**n_inputs)))
    print(f"  Is upper byte passthrough: {upper_byte_check}")

    lower_byte_check = all(eval_func(outputs, i) == (i & 0xFF) for i in range(min(10000, 2**n_inputs)))
    print(f"  Is lower byte passthrough: {lower_byte_check}")

    # Sample some values and check
    print(f"  Sample BF16 inputs -> 8-bit outputs:")
    test_inputs = [0x0000, 0x8000, 0x3F80, 0xBF80, 0x4000, 0x3F00, 0x7F80, 0xFF80, 0x7FC0, 0x4049]
    labels = ['+0', '-0', '+1.0', '-1.0', '+2.0', '+0.5', '+inf', '-inf', 'NaN', '+pi']
    for label, inp in zip(labels, test_inputs):
        out = eval_func(outputs, inp)
        inp_as_bf16 = interpret_bf16(inp)
        inp_as_fp16 = interpret_fp16(inp & 0xFFFF)
        print(f"    {label:6s}: inp=0x{inp:04X}(BF16={inp_as_bf16:.4g}) -> out=0x{out:02X} ({out:08b})")

    # Try FP8 E4M3 interpretation: sign=1, exp=4, mantissa=3
    # FP8 E5M2: sign=1, exp=5, mantissa=2
    print(f"\n  FP8 interpretations for key BF16 inputs:")
    for label, inp in zip(labels, test_inputs):
        out = eval_func(outputs, inp)
        fp8_e4m3 = interpret_fp8_e4m3(out)
        fp8_e5m2 = interpret_fp8_e5m2(out)
        inp_as_bf16 = interpret_bf16(inp)
        print(f"    {label:6s}: BF16={inp_as_bf16:.4g} -> out=0x{out:02X} FP8_E4M3={fp8_e4m3:.4g} FP8_E5M2={fp8_e5m2:.4g}")

    # Scan for pattern: BF16 -> FP8 E4M3
    import math
    bf16_to_fp8e4m3_correct = 0
    total_check = 1000
    for i in range(total_check):
        inp = (i * 65536) // total_check
        out = eval_func(outputs, inp)
        inp_f = interpret_bf16(inp)
        out_f = interpret_fp8_e4m3(out)
        if math.isnan(inp_f) or math.isnan(out_f):
            continue
        if math.isinf(inp_f) or math.isinf(out_f):
            if math.isinf(inp_f) and math.isinf(out_f) and inp_f == out_f:
                bf16_to_fp8e4m3_correct += 1
            continue
        if abs(inp_f) < 1e-10 and abs(out_f) < 1e-10:
            bf16_to_fp8e4m3_correct += 1
        elif abs(inp_f) > 0:
            rel_err = abs(out_f - inp_f) / max(abs(inp_f), 1e-30)
            if rel_err < 0.3:  # FP8 has low precision
                bf16_to_fp8e4m3_correct += 1
    print(f"\n  BF16->FP8_E4M3 match rate: {bf16_to_fp8e4m3_correct}/{total_check}")


def interpret_fp8_e4m3(val):
    """FP8 E4M3: sign=1bit, exp=4bits(bias=7), mantissa=3bits. NaN=S1111111."""
    sign = (val >> 7) & 1
    exp = (val >> 3) & 0xF
    mantissa = val & 0x7
    if exp == 0xF and mantissa == 0x7:
        return float('nan')
    if exp == 0:
        # Subnormal
        f = mantissa / 8.0 * (2.0 ** (1 - 7))
    else:
        f = (1.0 + mantissa / 8.0) * (2.0 ** (exp - 7))
    return -f if sign else f


def interpret_fp8_e5m2(val):
    """FP8 E5M2: sign=1bit, exp=5bits(bias=15), mantissa=2bits."""
    sign = (val >> 7) & 1
    exp = (val >> 2) & 0x1F
    mantissa = val & 0x3
    if exp == 0x1F:
        if mantissa == 0:
            return float('-inf') if sign else float('inf')
        else:
            return float('nan')
    if exp == 0:
        f = mantissa / 4.0 * (2.0 ** (1 - 15))
    else:
        f = (1.0 + mantissa / 4.0) * (2.0 ** (exp - 15))
    return -f if sign else f


def analyze_integer_arithmetic(n_inputs, n_outputs, outputs, name):
    """For integer arithmetic (ex261): 10 inputs, 10 outputs."""
    print(f"\n  [Integer Arithmetic Analysis for {name}]")
    print(f"  Input: {n_inputs} bits, Output: {n_outputs} bits")

    # With 10 inputs, could be 5+5 -> 10 (multiply)
    # Or could be 10-bit -> 10-bit operation
    # Or 5-bit * 5-bit = 10-bit multiply

    # Test as 5x5 multiply
    print(f"  Testing as 5-bit x 5-bit multiply (inputs a[4:0] b[4:0]):")
    mult_correct = 0
    mult_total = 100
    for a in range(32):
        for b in range(32):
            inp = (a << 5) | b
            if inp >= 2**n_inputs:
                break
            out = eval_func(outputs, inp)
            expected = a * b
            if out == expected:
                mult_correct += 1
            if mult_total <= 0:
                break
    print(f"  5x5 multiply matches: {mult_correct}/1024")

    # Test as 5x5 signed multiply
    signed_mult_correct = 0
    for a in range(32):
        for b in range(32):
            inp = (a << 5) | b
            # Sign extend a and b (5-bit signed)
            a_signed = a - 32 if a >= 16 else a
            b_signed = b - 32 if b >= 16 else b
            expected = (a_signed * b_signed) & 0x3FF  # 10-bit mask
            out = eval_func(outputs, inp)
            if out == expected:
                signed_mult_correct += 1
    print(f"  5x5 signed multiply matches: {signed_mult_correct}/1024")

    # Test as 10-bit unary (square)
    # But 10 input -> 10 output is only 10 bits out, can't hold full square
    print(f"  Testing as single 10-bit input operation:")
    # Check for simple operations
    for a in range(0, min(64, 2**n_inputs), 4):
        out = eval_func(outputs, a)
        print(f"    inp={a:3d} (0x{a:03X}) -> out={out:4d} (0x{out:03X})")

    # Check for divide: 10-input as 5-bit quotient + 5-bit dividend?
    print(f"\n  Testing as 5-bit divide (a[4:0] / b[4:0]):")
    div_correct = 0
    for a in range(32):
        for b in range(1, 32):  # avoid div by 0
            inp = (a << 5) | b
            out = eval_func(outputs, inp)
            expected_q = a // b
            expected_r = a % b
            expected = (expected_q << 5) | expected_r
            if out == expected:
                div_correct += 1
    print(f"  5-bit divide (q<<5|r) matches: {div_correct}/992")

    # Check modulo separately
    mod_correct = 0
    for a in range(32):
        for b in range(1, 32):
            inp = (a << 5) | b
            out = eval_func(outputs, inp)
            if out == a % b:
                mod_correct += 1
    print(f"  5-bit modulo matches: {mod_correct}/992")

    quotient_correct = 0
    for a in range(32):
        for b in range(1, 32):
            inp = (a << 5) | b
            out = eval_func(outputs, inp)
            if out == a // b:
                quotient_correct += 1
    print(f"  5-bit quotient matches: {quotient_correct}/992")


def analyze_unknown_group(n_inputs, n_outputs, outputs, name):
    """For unknown group (ex286): 13 inputs, 13 outputs."""
    print(f"\n  [Unknown Group Analysis for {name}]")
    print(f"  Input: {n_inputs} bits, Output: {n_outputs} bits")

    # 13 bits could be many things
    # Check for class/rotation/split structure as mentioned
    # Try: input as two fields, output has transformed structure

    # Sample outputs
    print(f"  Input -> Output samples (decimal and binary):")
    for i in range(0, min(64, 2**n_inputs), 1):
        out = eval_func(outputs, i)
        print(f"    {i:4d} ({i:013b}) -> {out:4d} ({out:013b})")

    # Check for symmetry: f(x) = f(reverse_bits(x))?
    print(f"\n  Checking bit-reversal symmetry...")
    sym_count = 0
    for i in range(min(1000, 2**n_inputs)):
        rev_i = int(f'{i:013b}'[::-1], 2)
        if eval_func(outputs, i) == eval_func(outputs, rev_i):
            sym_count += 1
    print(f"  Bit-reversal symmetric: {sym_count}/1000")

    # Check for XOR pattern
    print(f"\n  Checking XOR-based patterns...")
    xor_self_count = 0
    for i in range(min(1000, 2**n_inputs)):
        out = eval_func(outputs, i)
        if out == (i ^ (i >> 1)):  # Gray code
            xor_self_count += 1
    print(f"  Is Gray code: {xor_self_count}/1000")

    # Check if it might be integer sqrt/square with specific bit layout
    # 13 bits input, 13 bits output - could be 6+7 or 7+6 split
    print(f"\n  Testing 6+7 split (a[6:0] b[5:0]):")
    for a in range(8):
        for b in range(8):
            inp = (a << 6) | b
            out = eval_func(outputs, inp)
            # Various ops
            ops = {
                'a+b': (a+b) & 0x1FFF,
                'a*b': (a*b) & 0x1FFF,
                'a-b': (a-b) & 0x1FFF,
            }
            print(f"    a={a} b={b} inp={inp}: out={out} | a+b={ops['a+b']} a*b={ops['a*b']} a-b={ops['a-b']}")
        if a >= 3:
            break

    # Check popcount
    print(f"\n  Checking if output is popcount of input:")
    popcount_correct = 0
    for i in range(min(1000, 2**n_inputs)):
        out = eval_func(outputs, i)
        if out == bin(i).count('1'):
            popcount_correct += 1
    print(f"  Popcount matches: {popcount_correct}/1000")

    # Check leading zeros count
    print(f"\n  Checking if output is leading zeros count:")
    lz_correct = 0
    for i in range(min(1000, 2**n_inputs)):
        out = eval_func(outputs, i)
        lz = n_inputs - i.bit_length() if i > 0 else n_inputs
        if out == lz:
            lz_correct += 1
    print(f"  Leading zeros matches: {lz_correct}/1000")

    # Deep dive: look for structure in output patterns
    print(f"\n  Checking correlation between specific input/output bits:")
    for o_bit in range(n_outputs):
        # Count how often this output bit is 1
        count_1 = sum(outputs[o_bit])
        count_0 = len(outputs[o_bit]) - count_1
        print(f"  Output bit {o_bit:2d}: ones={count_1}/{len(outputs[o_bit])} ({100*count_1/len(outputs[o_bit]):.1f}%)")


def analyze_all():
    cases = [
        ('ex252', 'float_conv'),
        ('ex286', 'unknown'),
        ('ex217', 'bf16_unary'),
        ('ex261', 'integer'),
        ('ex246', 'float_conv'),
        ('ex247', 'float_conv'),
        ('ex248', 'float_conv'),
        ('ex219', 'bf16_unary'),
    ]

    for name, category in cases:
        print(f"\n{'='*70}")
        print(f"ANALYZING {name} (category: {category})")
        print(f"{'='*70}")

        n_inputs, n_outputs, outputs = load_truth(name)
        print(f"  Inputs: {n_inputs}, Outputs: {n_outputs}, TT size: {2**n_inputs}")

        # Check constant outputs
        constants = check_constant_outputs(n_outputs, outputs)
        if constants:
            print(f"  Constant outputs: {constants}")

        if category == 'bf16_unary':
            analyze_bf16_unary(n_inputs, n_outputs, outputs, name)
        elif category == 'float_conv':
            analyze_float_conversion(n_inputs, n_outputs, outputs, name)
        elif category == 'integer':
            analyze_integer_arithmetic(n_inputs, n_outputs, outputs, name)
        elif category == 'unknown':
            analyze_unknown_group(n_inputs, n_outputs, outputs, name)


if __name__ == '__main__':
    analyze_all()
