#!/usr/bin/env python3
"""Final definitive analysis."""
import struct, math
from collections import Counter

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'

def load_truth(name):
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f: data = f.read()
    lines = [l for l in data.split(b'\n') if l.strip()]
    outputs = [[int(b)-48 for b in line] for line in lines]
    return len(lines[0]).bit_length()-1, len(lines), outputs

def eval_func(outputs, v):
    return sum(outputs[i][v] << (len(outputs)-1-i) for i in range(len(outputs)))

def bf16_to_float(val):
    return struct.unpack('>f', struct.pack('>I', val<<16))[0]

def fp16_to_float(val):
    return struct.unpack('>e', struct.pack('>H', val&0xFFFF))[0]

# =========================================================================
# ex261: KEY FINDINGS
# - Not a bijection (194 unique outputs out of 1024 possible)
# - For i=0..15: f(i) = bit_reverse_10(i+1) exactly
# - f(i+16) = f(i) + 63 for i=0..30 (exactly!)
# - f(31) = 0 (breaks pattern) and f(15) = 32
#
# NEW HYPOTHESIS: This is an LFSR or counter-based sequence
# Let me count how many times each output appears
# =========================================================================
print("=== ex261: Output Frequency Analysis ===")
n_in, n_out, outputs261 = load_truth('ex261')

all_out = [eval_func(outputs261, i) for i in range(1024)]
freq = Counter(all_out)
print(f"Most common outputs and their frequencies:")
for val, cnt in sorted(freq.items(), key=lambda x: -x[1])[:20]:
    print(f"  {val:4d} ({val:010b}): {cnt} times")

# What inputs give output=0?
zero_inputs = [i for i in range(1024) if eval_func(outputs261, i) == 0]
print(f"\nInputs giving output=0: {zero_inputs}")

# What inputs give output=512?
inp512 = [i for i in range(1024) if eval_func(outputs261, i) == 512]
print(f"Inputs giving output=512: {inp512[:10]}")

# NEW APPROACH: Maybe input has TWO parts:
# Part A = some bits = CONTROL
# Part B = other bits = DATA
# And output = some_operation(A, B)
#
# From f(16)=575 and f(32)=256 and f(48)=287:
# 16=0b10000, 32=0b100000, 48=0b110000
# f(16)=575=0b1000111111, f(32)=256=0b0100000000, f(48)=287=0b0100011111
# The lower 6 bits of 575 are 111111=63, of 256 are 0, of 287 are 011111=31
# These look like THRESHOLDS or MASKS

# MULTIPLICATION CHECK: what if this is 5-bit * 5-bit with different bit layout?
# Input[9:5] = A (5 bits), Input[4:0] = B (5 bits) -> 10-bit result
# OR: Input[4:0] = A, Input[9:5] = B
print("\n5x5 Multiply check (A=inp[9:5], B=inp[4:0]):")
correct = 0
for i in range(1024):
    A = (i >> 5) & 0x1F
    B = i & 0x1F
    expected = A * B
    out = eval_func(outputs261, i)
    if out == expected:
        correct += 1
print(f"  matches: {correct}/1024")

print("\n5x5 Multiply check (A=inp[4:0], B=inp[9:5]):")
correct2 = 0
for i in range(1024):
    B = (i >> 5) & 0x1F
    A = i & 0x1F
    expected = A * B
    out = eval_func(outputs261, i)
    if out == expected:
        correct2 += 1
print(f"  matches: {correct2}/1024")

# Sample A=1, B=0..31
print("\nFor A=1 (upper bits), B=0..31:")
for B in range(32):
    i = (1 << 5) | B
    out = eval_func(outputs261, i)
    print(f"  A=1, B={B}: i={i} -> out={out} (expected A*B={1*B})")

# Let me try a completely different split
print("\nFor A=0..31 (MSB), B=1:")
for A in range(32):
    i = (A << 5) | 1
    out = eval_func(outputs261, i)
    print(f"  A={A:2d}, B=1: i={i:4d} -> out={out:4d} (expected A*B={A*1})")

# =========================================================================
# ex286: From the data, groups of 16 and 32 show EXACT repetition for some
# This is the "class/rotation/split" structure
#
# Key observation: f(16)==f(32) for the first 16 values in the group
# (groups 16-31 and 32-47 are IDENTICAL)
# This means input bit 4 (0b10000) is IGNORED for some inputs
# Let me figure out which input bits are redundant
# =========================================================================
print("\n\n=== ex286: Bit redundancy analysis ===")
n_in, n_out, outputs286 = load_truth('ex286')

# Check which individual bits, when flipped, change the output
print("For each bit position: how often does flipping it change the output?")
for bit in range(13):
    changes = sum(1 for i in range(8192)
                  if eval_func(outputs286, i) != eval_func(outputs286, i ^ (1<<bit)))
    print(f"  bit {bit:2d}: changes output for {changes}/8192 ({100*changes/8192:.1f}%) inputs")

# The LSB pattern from earlier: groups of 16 are often identical
# Let me check which bit patterns cause identical outputs
# If f(i) = f(i ^ bit_k) for all i, then bit_k is truly redundant
for bit in range(13):
    fully_redundant = all(eval_func(outputs286, i) == eval_func(outputs286, i ^ (1<<bit))
                          for i in range(8192))
    if fully_redundant:
        print(f"  BIT {bit} IS FULLY REDUNDANT!")

# =========================================================================
# ex217/ex219: CRITICAL INSIGHT
# Looking at the outputs for 0.5, 1.0, 2.0, 4.0, 8.0, 16.0:
# ex217: 0003, D3FD, 85FD, 01FD, D2FD, 84FD
# ex219: 00FD, 84FD, D2FD, 01FD, 85FD, D3FD
#
# NOTICE: ex217(1.0) = D3FD = ex219(16.0)
#         ex217(2.0) = 85FD = ex219(8.0)
#         ex217(4.0) = 01FD = ex219(4.0)  [same!]
#         ex217(8.0) = D2FD = ex219(2.0)
#         ex217(16.0) = 84FD = ex219(1.0)
#
# So ex217 and ex219 compute the SAME function evaluated at x and 4.0/x ??
# Or they compute the same function but different NORMALIZATIONS
#
# Actually: both give same output for 4.0 (01FD)
# ex217: f(0.5)=0003, f(1.0)=D3FD, f(2.0)=85FD, f(4.0)=01FD
# ex219: f(0.5)=00FD, f(1.0)=84FD, f(2.0)=D2FD, f(4.0)=01FD
#
# 0xD3FD = 1101_0011_1111_1101
# 0x84FD = 1000_0100_1111_1101
# Both have lower byte 0xFD = 1111_1101
#
# Upper byte of ex217(1.0) = 0xD3 = 11010011
# Upper byte of ex219(1.0) = 0x84 = 10000100
# These are NOT simply related...
#
# BUT WAIT: 0xD3 >> 1 = 0x69, 0x84 >>1 = 0x42... not helpful
# 0xD3 as signed = -45, 0x84 = -124 as signed...
# XOR: 0xD3 ^ 0x84 = 0101_0111 = 0x57 = 87
#
# Let me check if this could be a POLYNOMIAL EVALUATION
# or maybe input exponent bits determine upper byte while mantissa bits determine lower byte
#
# Key insight: the output's lower byte is almost always 0xFD for normal-range inputs
# 0xFD = 1111_1101 = 11111101
# What if the OUTPUT is a PAIR of 8-bit values?
# byte_high = some function of input
# byte_low = some function of input (usually 0xFD for normals)
#
# Actually 0xFD has 7 set bits and bit 1 unset
# Could the lower 7 bits (0b1111101 = 125) be a BIASED EXPONENT of some output format?
# =========================================================================
print("\n\n=== ex217/ex219: Output structure deep analysis ===")
for name in ['ex217', 'ex219']:
    n_in, n_out, outputs = load_truth(name)
    print(f"\n{name}:")
    # Look at the exponent and mantissa of the OUTPUT interpreted as BF16
    # For output 0xD3FD:
    # sign = 1 (negative)
    # exp = 0b10100111 = 0xA7 = 167 -> true_exp = 167-127 = 40
    # mantissa = 0b1111101 = 0x7D = 125
    # Value = -2^40 * (1 + 125/128) = -2^40 * 1.9765625 = huge!
    # That's not a meaningful float...

    # ALTERNATIVE: output is NOT BF16
    # Maybe output[15:8] = one thing, output[7:0] = another

    # Check: is output bit[7] always 1? (the MSB of lower byte = 0xFD)
    bit7_dist = Counter((eval_func(outputs, i) >> 7) & 1 for i in range(65536))
    print(f"  Output bit 7 distribution: {dict(bit7_dist)}")

    # Is output bit 1 always 0? (bit 1 of 0xFD is 0)
    bit1_dist = Counter((eval_func(outputs, i) >> 1) & 1 for i in range(65536))
    print(f"  Output bit 1 distribution: {dict(bit1_dist)}")

    # For BF16 inputs with exp != 0 and != 255 (normals):
    normal_low_bytes = Counter()
    for i in range(65536):
        exp = (i >> 7) & 0xFF
        if 0 < exp < 255:
            out = eval_func(outputs, i)
            normal_low_bytes[out & 0xFF] += 1
    print(f"  Low byte for normal inputs (top 10): {sorted(normal_low_bytes.items(), key=lambda x:-x[1])[:10]}")

    # What if the lower 9 bits are a separate function?
    # output[8:0] = 9 bits
    low9_dist = Counter(eval_func(outputs, i) & 0x1FF for i in range(65536))
    print(f"  Unique lower 9 bits: {len(low9_dist)}")
    print(f"  Top 10 lower-9-bit values: {sorted(low9_dist.items(), key=lambda x:-x[1])[:10]}")

# =========================================================================
# ex252: The 26 output values and their relationship to BF16 exponents
# From earlier: output 0x8A only appears for +zero (sign=0, exp=0)
#               output 0xF2 appears for -zero AND -subnormals AND...
# Wait: earlier showed 0xF2 for exps [0,1,4,8,10]... 15 unique
# And 0x8A for exps=[0] only, signs={0}
#
# So output 0x8A = +zero, output 0xF2 is for a broader class
#
# KEY: these 26 values are NOT BF16 floats
#
# New hypothesis: this is a BF16 -> INT8 conversion
# Or a BF16 to FLOAT8 conversion using a non-standard format
#
# Look at the values 0x0C (+inf->0x0C) and 0x00 (-inf->0x00)
# If infinity maps to 12 and 0 respectively...
# These could be indices or classification codes
#
# ALTERNATIVELY: the 26 values with bit 0 always 0 means 7 meaningful bits
# And the high bit being set only for some values suggests sign
#
# Let me count the VALUES as if they're indices: 0,1,5,6,9,10,14,17,22,...
# (those are the val>>1 values)
# Differences: 1,4,1,3,1,4,3,5,3,5,3,8,8,3,8,8,8,8...
# Hard to see pattern
#
# Let me instead check: can this be a fp_to_int8 saturating conversion?
# BF16 -> clamp(-128, 127) -> signed int8 -> store in low 8 bits (bit0=0 from parity?)
# +inf -> +127 (0x7F), but we get 0x0C
# Doesn't work
#
# What about FLOAT-8 E5M2 (sign=1, exp=5, mantissa=2)?
# These have values 0..255, but we only see 26 even values
# FLOAT-8 E5M2 encoding of specific values...
# Actually with bit 0 always 0, we have 7 remaining bits [7:1]
# Let me map those 7 bits to the actual values
# =========================================================================
print("\n\n=== ex252: 7-bit encoding analysis ===")
n_in, n_out, outputs252 = load_truth('ex252')

# All outputs have bit 0 = 0. Look at bits [7:1]
# These 7 bits give values 0..127
# Map from BF16 input to 7-bit output
vals_7bit = set(eval_func(outputs252, i) >> 1 for i in range(65536))
print(f"Unique 7-bit values: {sorted(vals_7bit)}")

# How are they distributed?
# 0,1,5,6,9,10,14,17,22,25,30,33,41,46,49,57,62,65,69,73,81,89,97,105,113,121
# Hmm. 0,1 then 5,6 then 9,10 then 14 then 17 then 22 then 25,30 then 33 etc.
# Let me check DIFFERENCES between consecutive values:
vals_list = sorted(vals_7bit)
diffs = [vals_list[i+1]-vals_list[i] for i in range(len(vals_list)-1)]
print(f"Differences: {diffs}")
# Do these differences have a pattern?

# Check TRIANGLE NUMBERS: 0,1,3,6,10,15,21,28...
tri = [n*(n+1)//2 for n in range(20)]
print(f"Triangle numbers: {tri}")
tri_check = sum(1 for v in vals_7bit if v in tri)
print(f"Values that are triangle numbers: {tri_check}")

# PENTAGONAL NUMBERS: 1,5,12,22,35,51,70,92...
pent = [(n*(3*n-1)//2) for n in range(1, 20)]
print(f"Pentagonal numbers: {pent}")

# Actually: 0,1,5,6,9,10,14,17,22,25,30,33,41,46,49,57,62,65,69,73,81,89,97,105,113,121
# Let me see if these are LOGARITHMICALLY SPACED
print(f"\nValues with their log2:")
for v in vals_list:
    if v > 0:
        print(f"  {v:3d}: log2={math.log2(v):.3f}")
    else:
        print(f"  {v:3d}: log2=-inf")

# =========================================================================
# Let me try checking other benchmarks to see if ex246/247/248/252 are related
# ex246 and ex247 gave lots of 0xFE outputs, but ex252 never gives 0xFE
#
# NEW OBSERVATION from ex252 data:
# Output bit 0 is always 0 (CONSTANT)
# This means there are actually 7 meaningful output bits
#
# The 26 distinct 7-bit values (if we count output>>1):
# These 26 values out of 128 possible strongly suggest this is NOT a simple FP conversion
#
# Let me check if ex252 is a BF16 -> some kind of LOGARITHM TABLE INDEX
# or if it's related to the EXPONENT bits of a compressed format
# =========================================================================

# FINAL: look at what range of BF16 gives each output
print("\n\nFor ex252: BF16 value range for key outputs:")
out_to_inputs = {}
for i in range(65536):
    out = eval_func(outputs252, i)
    if out not in out_to_inputs:
        out_to_inputs[out] = []
    out_to_inputs[out].append(i)

for out in sorted(out_to_inputs.keys())[:10]:
    inputs = out_to_inputs[out]
    bf16_vals = [bf16_to_float(i) for i in inputs[:5]]
    print(f"  out=0x{out:02X}: {len(inputs)} inputs, sample BF16 vals: {[f'{v:.4g}' for v in bf16_vals]}")

# Very important: what's the actual output for a continuous range
print("\nEx252 continuous BF16 range 1.0..2.0 (0x3F80..0x4000):")
prev_out = None
for inp in range(0x3F80, 0x4001, 1):
    out = eval_func(outputs252, inp)
    if out != prev_out:
        print(f"  At {inp:04X} ({bf16_to_float(inp):.6g}): output changes to 0x{out:02X}")
        prev_out = out
