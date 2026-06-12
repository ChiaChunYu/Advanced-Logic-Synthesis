#!/usr/bin/env python3
"""Final focused analysis."""
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
# ex261: The VdC matches for i=0..15 (values with max 4 set bits in lower nibble)
# At i=16 (0b10000), expected VdC(17)=0b10001000000 but got 0b1000111111
# The difference is lower 6 bits: expected=0, got=0b111111=63
# At i=31 (0b11111), VdC(32)=0b1 shifted = 0b0000010000 = 16, but got 0
#
# NEW HYPOTHESIS: This might be a bit-reversal sort network output
# Or a counting sequence: it outputs the k-th number in some sequence
#
# Let me look at the complete bijection: for i=0..1023, what is f(i)?
# First check: is f surjective (do all outputs appear)?
# =========================================================================
print("=== ex261: Complete Analysis ===")
n_in, n_out, outputs = load_truth('ex261')

all_outputs = [eval_func(outputs, i) for i in range(1024)]
out_set = set(all_outputs)
print(f"Output range: {min(out_set)}..{max(out_set)}, unique values: {len(out_set)}")
print(f"Is bijection (surjective): {out_set == set(range(1024))}")

# If it IS a bijection, find cycles
if out_set == set(range(1024)):
    # Find the cycle that starts at 0
    cycle = [0]
    cur = eval_func(outputs, 0)
    while cur != 0:
        cycle.append(cur)
        cur = eval_func(outputs, cur)
    print(f"Cycle containing 0: length={len(cycle)}, first few: {cycle[:10]}")

    # Find all cycle lengths
    visited = set()
    cycle_lengths = []
    for start in range(1024):
        if start not in visited:
            cycle = []
            cur = start
            while cur not in visited:
                visited.add(cur)
                cycle.append(cur)
                cur = eval_func(outputs, cur)
            cycle_lengths.append(len(cycle))
    print(f"Cycle length distribution: {Counter(cycle_lengths)}")

# Check if this might be multiply by odd number mod 1024
print("\nChecking f(i) = (i * K) mod 1024:")
for K in [3, 5, 7, 11, 13, 17, 19, 23, 127, 255, 341, 512]:
    matches = sum(1 for i in range(1024) if eval_func(outputs, i) == (i * K) % 1024)
    print(f"  K={K}: {matches}/1024")

# Check bit-reversal group: what about reversed with some XOR masking?
# At i=0: f=512, reversed(0)=0, so +512 offset?
# At i=16=0b10000: f=575=0b1000111111
# reversed(16)=0b0000001000=8, but 8+512=520 != 575
# What if f(i) = bit_reverse(i, 10) XOR something?
print("\nChecking f(i) = bit_reverse(i, 10) XOR K:")
def brev10(v):
    return int(f'{v:010b}'[::-1], 2)
for K in [0, 63, 512, 575, 1023]:
    matches = sum(1 for i in range(1024) if eval_func(outputs, i) == (brev10(i) ^ K))
    print(f"  K={K}: {matches}/1024")

# What if f(i) = brev(i+1) ^ brev(1)?
# brev(1) = 0b1000000000 = 512
# i=0: brev(1)=512 ^ 0? That gives 512, matches!
# i=1: brev(2)=0b0100000000=256 ^ 0? = 256, matches!
# i=15: brev(16)=0b0000100000=32, f(15)=32, matches!
# i=16: brev(17)=0b1000100000=544, but f(16)=575
# Not quite. But matches for i=0..15.

# CRITICAL INSIGHT: The pattern changes at i=16.
# For i=0..15 (4 LSBs only set), f(i) = brev10(i+1)
# For i=16 (bit 4 set): f(16)=575=0b1000111111
# brev10(17) = brev10(0b0010001) = 0b1000100000 = 544
# Difference = 575-544 = 31 = 0b11111 = 2^5-1
# For i=17: f(17)=319=0b0100111111, brev10(18)=0b0100100000=288
# Diff = 319-288 = 31 again!
# For i=31: f(31)=0, brev10(32)=0b0000010000=16, diff = -16...
# Hmm not consistent

# Let me try another approach: look at individual bit output functions
# bit 9 of output: should be output[0]
print("\nAnalyzing output bit functions:")
for o_bit in range(10):
    # Which output row (0=MSB, 9=LSB)
    row = outputs[o_bit]
    ones = sum(row)
    # Check if this bit is the MSB of (i*K mod 1024)
    # Or try: is this bit determined by a subset of input bits?
    # Find the minimum set of input bits that determines this output bit
    pass

# ACTUAL INSIGHT: For i=0..31 (5 bits), the pattern changes at 16
# i=0..15: matches brev10(i+1) pattern
# i=16..31: matches some other pattern
# For i=16..30: f(16+k) = f(k) - 1  (for k=0..14)?
# f(0)=512, f(16)=575... no, 575 > 512
# f(1)=256, f(17)=319... 319-256=63
# f(2)=768, f(18)=831... 831-768=63
# ALL differ by exactly 63 = 0b111111 = 2^6-1
print("\nChecking f(i+16) - f(i) for i=0..15:")
for i in range(16):
    fi = eval_func(outputs, i)
    fi16 = eval_func(outputs, i+16)
    diff = fi16 - fi
    print(f"  f({i+16})-f({i}) = {fi16}-{fi} = {diff} (0b{diff&1023:010b})")

print("\nChecking f(i+32) - f(i) for i=0..31:")
diffs = set()
for i in range(32):
    fi = eval_func(outputs, i)
    fi32 = eval_func(outputs, i+32)
    diffs.add((fi32 - fi) & 1023)
print(f"  Differences mod 1024: {diffs}")

print("\nChecking f(i+64) - f(i) for i=0..63:")
diffs64 = set()
for i in range(64):
    fi = eval_func(outputs, i)
    fi64 = eval_func(outputs, i+64)
    diffs64.add((fi64 - fi) & 1023)
print(f"  Differences mod 1024: {diffs64}")

# Let me try to understand the full structure by looking at the output
# as a 10x10 matrix where rows=input and cols=output bits
print("\nLooking at correlation matrix (which input bits determine which output bits):")
for o_bit in range(10):
    row = outputs[o_bit]  # MSB is output[0]
    correlations = []
    for i_bit in range(10):
        agree = sum(1 for v in range(1024) if row[v] == ((v >> (9-i_bit)) & 1))
        correlations.append(agree)
    best_corr = max(correlations)
    best_bit = correlations.index(best_corr)
    print(f"  out[{o_bit}]: best_corr with in[{best_bit}] = {best_corr}/1024")

# =========================================================================
# ex217/ex219: output always ends in FD
# 0xFD = 11111101... that's always in the low byte?
# Wait: for +inf: 0x0001, for +0: 0x03FE...
# No, some don't end in FD. Let me recheck the BF16 sample:
# +0.5 -> 0x0003, +inf -> 0x0001, -inf -> 0x0000
# +1.0 -> 0xD3FD, +2.0 -> 0x85FD, +3.0 -> 0x49FD, etc.
# Low byte 0xFD = 11111101, 0x03 = 00000011, 0x01 = 00000001
#
# CRITICAL: 0xFD = ~0x02!
# 0x03 = 0x02 | 0x01
# These are all values ending in odd bits...
#
# Let me look at what bits in the output are always 0
# From earlier: "Output bit X is always Y" - nothing was constant in ex217/ex219
# except for NaN/inf edge cases
#
# Output for ex217 range 0.5-16.0: all end in FD except for very small outputs
# 0x0003, 0x0001, etc. are for the zero/subnormal region
#
# MAJOR CLUE: Look at the outputs for BF16 1.0, 2.0, 3.0, 4.0:
# ex217: 1.0->D3FD, 2.0->85FD, 3.0->49FD, 4.0->01FD (all *FD!)
# ex219: 1.0->84FD, 2.0->D2FD, 3.0->06FD, 4.0->01FD (all *FD!)
#
# They differ in upper byte: D3 vs 84, 85 vs D2, 49 vs 06, 01 vs 01
# So the two functions give DIFFERENT BF16 outputs for same inputs,
# suggesting they compute DIFFERENT functions
#
# The upper bytes of ex217 outputs: D3=1101_0011, 85=1000_0101, 49=0100_1001, 01=0000_0001
# The upper bytes of ex219 outputs: 84=1000_0100, D2=1101_0010, 06=0000_0110, 01=0000_0001
#
# For ex217: these look like sin/cos coefficients or Chebyshev approximation coefficients?
# For ex219: similar structure
#
# ANOTHER APPROACH: Check if this is a LOOKUP TABLE for transcendental functions
# where the input BF16 is used as an INDEX and output is some table value
#
# Actually: the key insight may be that the output is NOT meant to be interpreted as BF16
# It might be 16 bits of fixed-point or other encoding
# =========================================================================

print("\n=== ex217/ex219: Upper byte analysis ===")
for name in ['ex217', 'ex219']:
    n_in, n_out, outputs = load_truth(name)
    print(f"\n{name}:")
    # For the range 0x3F00-0x4200 (BF16 0.5 to ~4.0)
    print("  inp -> out (hex) and difference upper_byte from expected:")
    for inp in range(0x3F00, 0x4200, 0x80):
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        upper = out >> 8
        lower = out & 0xFF
        print(f"  {inp_f:6.3f} ({inp:04X}) -> {out:04X} (upper={upper:02X}={upper:08b}, lower={lower:02X})")

# Check: what if the output is the mantissa lookup for a transcendental?
# Like: for sin(x*pi), the 16-bit output encodes a high-precision mantissa

# Let me check if BOTH ex217 and ex219 together encode the REAL and IMAGINARY parts
# of a complex function (like e^(i*x) = cos(x) + i*sin(x))
print("\nChecking ex217+ex219 joint outputs for BF16 angle values:")
n_in217, n_out217, outputs217 = load_truth('ex217')
n_in219, n_out219, outputs219 = load_truth('ex219')
for inp in [0x3F00, 0x3F80, 0x4000, 0x4040, 0x4080, 0x40C0, 0x4100]:
    out17 = eval_func(outputs217, inp)
    out19 = eval_func(outputs219, inp)
    inp_f = bf16_to_float(inp)
    out17_f = bf16_to_float(out17)
    out19_f = bf16_to_float(out19)
    # Check sin/cos
    cos_v = math.cos(inp_f)
    sin_v = math.sin(inp_f)
    tanh_v = math.tanh(inp_f)
    print(f"  inp={inp_f:.4f}: out217={out17_f:.5g}  out219={out19_f:.5g}  cos={cos_v:.5g}  sin={sin_v:.5g}")

# =========================================================================
# ex252: Output is always even (26 unique values)
# Special values: +inf->0x0C, -inf->0x00, +zero->0x8A, -zero->0xF2
# NaN maps to {0x00, 0x0C}
#
# 0x0C = 0000_1100 (12)
# 0x00 = 0000_0000 (0)
# 0x8A = 1000_1010 (138)
# 0xF2 = 1111_0010 (242)
#
# Interesting: for +inf we get 0x0C and for -inf we get 0x00
# For +zero we get 0x8A and for -zero we get 0xF2
# 0x8A XOR 0xF2 = 0111_1000 = 0x78
# 0x0C XOR 0x00 = 0x0C
#
# The 26 values arranged: 0x00, 0x02, 0x0A, 0x0C, 0x12, 0x14, 0x1C, 0x22...
# Looking at upper nibbles: 0,0,0,0,1,1,1,2,2,3,3,4,5,5,6,7,7,8,8,9,10,11,12,13,14,15
# These seem like they could be 5-bit exponent biased values? No...
#
# The fact that all 26 outputs are EVEN (bit 0 always 0) means the output[7] is always 0
# This is confirmed from the analysis. With 7 meaningful bits, we'd expect up to 128 values
# but only 26 appear. Very structured.
#
# The value 0x8A = 10001010: sign bit set, next 3 bits=001, then 010...
# Could this be a 7-bit signed integer? Then 0x8A>>1 = 69...
#
# WAIT: Let me check the exponent field!
# For BF16 exp=255 (all 1s): NaN or inf, output = {0x00, 0x0C}
# For BF16 exp=254: NaN-adjacent, few outputs
# For BF16 exp=126,127: near +0 (subnormal boundary region), outputs like {0xC, 0x2C, 0x3C, 0x82}
# These seem like DIFFERENT CLASS LABELS
#
# HYPOTHESIS for ex252: This is a BF16 EXPONENT EXTRACTOR or LOG2 floor
# floor(log2(|x|)) for normalized = exp - 127 (biased), range -126 to +127
# But output only has 26 values, and BF16 exponent has 256 values (0-255)...
# Wait: valid normalized BF16 exponents are 1-254 (bias=127), so exp-127 = -126 to +127
# But we have only 26 output values!
#
# Perhaps it's floor(log2(|x|)) mapped to some smaller range?
# Or it's computing something with only 7 bits of meaningful info?
# =========================================================================
print("\n=== ex252: Exponent/log relationship ===")
n_in, n_out, outputs = load_truth('ex252')

# Check: for each BF16 normal value, what is floor(log2(|val|))?
# BF16 exp field = 1-254 for normals
# True exponent = exp_field - 127
# For +1.0: exp_field=127, true_exp=0
# For +2.0: exp_field=128, true_exp=1
# For +0.5: exp_field=126, true_exp=-1

# Map each output value to what BF16 exponent fields lead to it
out_to_exps = {}
for i in range(65536):
    out = eval_func(outputs, i)
    exp = (i >> 7) & 0xFF
    sign = (i >> 15) & 1
    if out not in out_to_exps:
        out_to_exps[out] = set()
    out_to_exps[out].add((sign, exp))

print("\nOutput value -> (sign, exp_field) mapping (unique exps per output):")
for out in sorted(out_to_exps.keys()):
    exps = out_to_exps[out]
    unique_exps = set(e for s,e in exps)
    unique_signs = set(s for s,e in exps)
    print(f"  0x{out:02X}: exps={sorted(unique_exps)[:5]}... ({len(unique_exps)} unique), signs={unique_signs}")

# =========================================================================
# ex286: Let's look at groups of 16 (since period-16 has 256/1000 = 25.6% match)
# =========================================================================
print("\n=== ex286: Deeper structure ===")
n_in, n_out, outputs = load_truth('ex286')

# Look at consecutive values
print("\nPattern for consecutive values (showing XOR with first in group):")
for group_start in [0, 16, 32, 48, 64]:
    print(f"\nGroup starting at {group_start}:")
    base_out = eval_func(outputs, group_start)
    for i in range(16):
        v = group_start + i
        out = eval_func(outputs, v)
        diff = out ^ base_out
        print(f"  {v:3d} ({v:013b}) -> {out:4d} ({out:013b}) | diff from base: {diff:013b}")

# Look at exponent pattern mapping
print("\nMapping from 13-bit input to output (try interpreting as a permutation matrix):")
# Check if this could be an 8x8 matrix rotation or transformation
# 13 bits = 3+10, 4+9, 6+7, etc.
# The problem description says "class/rotation/split"
# Try: class = top N bits, rotation = middle bits, split = lower bits

# Let me look for the actual pattern more carefully
# From earlier data: 0->8191, 16->7935, 32->7935
# 0=0000000000000 -> 1111111111111 = ~0
# 16=0000000010000 -> 1111011111111 = ~(0b0000100000000) = ~128
# 32=0000000100000 -> 1111011111111 = ~128 (same as 16!)
# 48=0000000110000 -> 1111110011111 = ~(0b0000001100000) = ~96
# Interesting pattern:
# 0  = 0000000|000000 -> ~0
# 16 = 0000000|010000 -> ~128
# 32 = 0000000|100000 -> ~128 (same!)
# 48 = 0000000|110000 -> ~(0b01100000) = ~96

print("\nSmall sample: inp -> out -> ~out (what's being complemented?):")
for i in range(64):
    out = eval_func(outputs, i)
    compl_of_out = (~out) & 0x1FFF
    print(f"  {i:3d} ({i:013b}) -> {out:4d} ({out:013b}) ~out={compl_of_out:4d} ({compl_of_out:013b})")

# Check if ~out has any simple relationship to input
print("\nChecking ~out vs inp:")
matches_inv = 0
for i in range(8192):
    out = eval_func(outputs, i)
    if (~out & 0x1FFF) == i:
        matches_inv += 1
print(f"  ~f(i)==i (involution after complement): {matches_inv}/8192")

# Check if this might be popcount-based:
# ~0 = 1111111111111 -> popcount = 0?
# No, f(0)=8191=~0, popcount(0)=0, not matching
