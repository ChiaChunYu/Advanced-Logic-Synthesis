#!/usr/bin/env python3
import struct, math

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'

def load_truth(name):
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f:
        data = f.read()
    lines = [l for l in data.split(b'\n') if l.strip()]
    n_outputs = len(lines)
    tt_len = len(lines[0])
    n_inputs = tt_len.bit_length() - 1
    outputs = [[int(b)-48 for b in line] for line in lines]
    return n_inputs, n_outputs, outputs

def eval_func(outputs, input_val):
    result = 0
    for i, out_bits in enumerate(outputs):
        bit = out_bits[input_val]
        result |= (bit << (len(outputs) - 1 - i))
    return result

def bf16_to_float(val):
    as_f32_bits = val << 16
    packed = struct.pack('>I', as_f32_bits)
    return struct.unpack('>f', packed)[0]

def fp16_to_float(val):
    packed = struct.pack('>H', val & 0xFFFF)
    return struct.unpack('>e', packed)[0]

def remap_bits(val, n_bits):
    """Reverse bit order"""
    return int(f'{val:0{n_bits}b}'[::-1], 2)

# =========================================================================
# ex217 and ex219: BF16 unary - try different bit orderings
# =========================================================================
print("=== ex217 and ex219: BF16 Unary Analysis ===")
for name in ['ex217', 'ex219']:
    print(f"\n--- {name} ---")
    n_inputs, n_outputs, outputs = load_truth(name)

    test_vals = [('+0', 0x0000), ('+1.0', 0x3F80), ('-1.0', 0xBF80), ('+2.0', 0x4000),
                 ('+inf', 0x7F80), ('-inf', 0xFF80), ('NaN', 0x7FC0), ('+0.5', 0x3F00),
                 ('+4.0', 0x4080), ('+0.25', 0x3E80), ('+e', 0x402E)]

    print(f"  Standard encoding (input index = bf16 bitpattern):")
    for label, inp in test_vals:
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        print(f"    {label:6s}: {inp:04X}({inp_f:.5g}) -> {out:04X}({out_f:.5g})")

    # Check: is the output the SAME value shifted (like floor/round to some precision)?
    print(f"\n  Checking bit patterns more carefully for +1.0 region:")
    for inp in range(0x3F80, 0x3F90):
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        print(f"    {inp:04X}({inp_f:.6g}) -> {out:04X}({out_f:.6g})")

    # Check if output MSB is same as input MSB (sign preservation)
    sign_preserved = sum(1 for i in range(min(10000,65536)) if (eval_func(outputs,i)>>15)==(i>>15))
    print(f"\n  Sign preserved: {sign_preserved}/10000")

# =========================================================================
# ex246, ex247, ex248, ex252: Float conversion 16->8 bit
# More careful analysis: what INPUT range actually gives non-0xFE outputs?
# =========================================================================
print("\n\n=== Float Conversion 16->8 bit ===")
for name in ['ex246', 'ex247', 'ex248', 'ex252']:
    print(f"\n--- {name} ---")
    n_inputs, n_outputs, outputs = load_truth(name)

    # Count output distribution
    from collections import Counter
    out_dist = Counter()
    for i in range(65536):
        out = eval_func(outputs, i)
        out_dist[out] += 1

    print(f"  Top 10 most common outputs:")
    for val, cnt in sorted(out_dist.items(), key=lambda x: -x[1])[:10]:
        print(f"    out=0x{val:02X} ({val:08b}): count={cnt} ({100*cnt/65536:.1f}%)")

    print(f"  Unique output values: {len(out_dist)}")

    # Find what input values DON'T give 0xFE output
    non_fe_count = sum(1 for i in range(65536) if eval_func(outputs,i) != 0xFE)
    print(f"  Inputs with non-0xFE output: {non_fe_count}")

    # Sample non-0xFE outputs
    print(f"  Sample non-0xFE BF16 inputs:")
    shown = 0
    for inp in range(0x4000, 0x4200):  # positive range > 2.0
        out = eval_func(outputs, inp)
        if out != 0xFE:
            inp_f = bf16_to_float(inp)
            print(f"    {inp:04X}({inp_f:.5g}) -> {out:02X}")
            shown += 1
            if shown >= 15:
                break

# =========================================================================
# ex261: Integer arithmetic
# =========================================================================
print("\n\n=== ex261: Integer Arithmetic ===")
n_inputs, n_outputs, outputs = load_truth('ex261')
print(f"Inputs: {n_inputs}, Outputs: {n_outputs}")

# Dense sample
print("\nFull 10-bit enumeration (first 128):")
for inp in range(128):
    out = eval_func(outputs, inp)
    print(f"  {inp:3d} (0b{inp:010b}) -> {out:4d} (0b{out:010b})")

# Check: output = reverse_bits(input)?
rev_check = sum(1 for i in range(1024) if eval_func(outputs,i) == remap_bits(i,10))
print(f"\nBit-reversal check: {rev_check}/1024")

# Check: output = rotate_left(input, 1)?
rot_check = sum(1 for i in range(1024)
                if eval_func(outputs,i) == (((i<<1)|(i>>9))&0x3FF))
print(f"Rotate-left-1 check: {rot_check}/1024")

# Check: output = rotate_right(input, 1)?
rot_r_check = sum(1 for i in range(1024)
                  if eval_func(outputs,i) == (((i>>1)|(i<<9))&0x3FF))
print(f"Rotate-right-1 check: {rot_r_check}/1024")

# Try: output bits are shuffled version of input bits
# Look at which input bits correlate with each output bit
print("\nInput->Output bit correlation:")
for o in range(n_outputs):
    for i_bit in range(n_inputs):
        match_same = sum(1 for v in range(1024)
                        if outputs[o][v] == ((v >> (n_inputs-1-i_bit)) & 1))
        if match_same == 1024:
            print(f"  out[{o}] == in[{i_bit}]")
        elif match_same == 0:
            print(f"  out[{o}] == ~in[{i_bit}]")

# =========================================================================
# ex286: Unknown group - deeper analysis
# =========================================================================
print("\n\n=== ex286: Unknown Group Deep Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex286')
print(f"Inputs: {n_inputs}, Outputs: {n_outputs}")

# Key observation from earlier: input=0 -> output=8191 (all 1s = ~0 for 13 bits)
# input=32=input[16..31] -> output=7935 (same as input=16)
# This suggests periodicity!

print("\nChecking periodicity:")
for period in [1, 2, 4, 8, 16, 32, 64, 128]:
    matches = sum(1 for i in range(min(1000, 8192-period))
                  if eval_func(outputs,i) == eval_func(outputs, (i+period)%8192))
    print(f"  Period {period}: {matches}/1000 match")

# Try: is it complement? output = ~input (13-bit)
compl_check = sum(1 for i in range(8192) if eval_func(outputs,i) == (~i & 0x1FFF))
print(f"\n~input check: {compl_check}/8192")

# Try: is it XOR with something?
# output XOR input
xor_vals = Counter()
for i in range(8192):
    xor_vals[eval_func(outputs,i) ^ i] += 1
print(f"\nTop XOR(output,input) values:")
for val, cnt in sorted(xor_vals.items(), key=lambda x: -x[1])[:10]:
    print(f"  XOR={val:04X} ({val:013b}): count={cnt}")

# Split interpretation: maybe 6+7 or 7+6 bits
print("\nChecking split-field interpretations:")
for split_a in [5, 6, 7]:
    split_b = 13 - split_a
    print(f"  a={split_a}bits + b={split_b}bits:")
    correct_sum = sum(1 for i in range(8192)
                      if eval_func(outputs,i) == (((i>>split_b) + (i&((1<<split_b)-1))) & 0x1FFF))
    print(f"    a+b matches: {correct_sum}/8192")
    correct_xor = sum(1 for i in range(8192)
                      if eval_func(outputs,i) == (((i>>split_b) ^ (i&((1<<split_b)-1)))))
    print(f"    a XOR b matches: {correct_xor}/8192")
    correct_cat = sum(1 for i in range(8192)
                      if eval_func(outputs,i) == ((i&((1<<split_b)-1)) << split_a) | (i>>split_b))
    print(f"    swap fields matches: {correct_cat}/8192")
