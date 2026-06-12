#!/usr/bin/env python3
"""
FINAL DECODE: Identify what functions each benchmark computes.
"""
import struct, math
from collections import Counter

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'

def load_truth(name):
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f: data = f.read()
    lines = [l for l in data.split(b'\n') if l.strip()]
    outputs = [[int(b)-48 for b in line] for line in lines]
    return len(lines[0]).bit_length()-1, len(lines), outputs

def ef(outputs, v):
    return sum(outputs[i][v] << (len(outputs)-1-i) for i in range(len(outputs)))

def bf16_f(val):
    return struct.unpack('>f', struct.pack('>I', val<<16))[0]

# =========================================================================
# ex261: FINAL DECODE
#
# f(i) = 0 IFF lower5(i)=31 OR upper5(i)=31
# f(A,B) = brev10(A+B+1)?  Let me check
# Actually: the truth table index is 10-bit integer,
# and f(i) = bit_reverse_10(i+1) for small i
# Let me find the ACTUAL FORMULA
# =========================================================================
print("=== ex261: FORMULA SEARCH ===")
n_in, n_out, outputs261 = load_truth('ex261')

# For i=0..1023, f(i) = ?
# Notice: inputs giving 0 include 31,63,95,...,991 (stride 32, lower5=11111)
# AND 992-1023 (upper5=11111)
# So output=0 when EITHER half is all 1s (value=31)

# What if the function is:
# Given upper5=A and lower5=B:
# Sort them: let S=max(A,B), L=min(A,B) (or the other way)
# Then output = bit_reverse_10(combined(S,L))

# Let me try: output = bit_reverse_10(A + B * something)
# or: output = bit_reverse_10(A * 32 + B)?
def brev10(v):
    return int(f'{v:010b}'[::-1], 2)

# Check brev(A*32+B) = brev(input itself)
# brev10(0) = 0, but f(0)=512... unless indexing starts at 1
correct_brev_i = sum(1 for i in range(1024) if ef(outputs261, i) == brev10(i))
correct_brev_ip1 = sum(1 for i in range(1024) if ef(outputs261, i) == brev10(i+1))
print(f"f(i) == brev10(i): {correct_brev_i}/1024")
print(f"f(i) == brev10(i+1): {correct_brev_ip1}/1024")

# For A=0, B=0: i=0, f=512. brev10(1)=512. YES
# For A=0, B=1: i=1, f=256. brev10(2)=256. YES
# For A=31, B=0: i=31*32+0=992, f=0. brev10(993)?
print(f"brev10(993) = {brev10(993)}, brev10(992) = {brev10(992)}")
print(f"f(992) = {ef(outputs261, 992)}, f(31) = {ef(outputs261, 31)}")

# So brev10(i+1) matches for i=0..15 (where i+1=1..16 in decimal)
# At i=16: brev10(17) = brev10(0b0010001) = 0b1000100000 = 544, but f=575
# At i=31: brev10(32) = 0b0000100000 = 16, but f=0
# At i=32: brev10(33) = 0b1000001000 = ... let me compute:
# 33 = 0b00100001 -> 0b10000100 as 8-bit -> as 10-bit: 0b0010000100 reversed
# 33 in 10 bits = 0b0000100001, reversed = 0b1000010000 = 528
print(f"brev10(33) = {brev10(33)}, f(32) = {ef(outputs261, 32)}")
# f(32) = 256 from earlier. brev10(33) = 528 != 256

# So the function DOESN'T follow brev10(i+1) after i=15

# NEW INSIGHT: It might be a LFSR counting sequence
# Let me compute what the function IS for all 1024 inputs and try to find the recurrence

# What are the outputs grouped?
all_f = [ef(outputs261, i) for i in range(1024)]

# Check: is f(2i) = some function of f(i)?
print("\nChecking doubling recurrence f(2i) vs f(i):")
for i in range(16):
    fi = ef(outputs261, i)
    f2i = ef(outputs261, 2*i) if 2*i < 1024 else -1
    print(f"  f({i})={fi}, f({2*i})={f2i}, ratio={f2i/fi if fi and f2i >= 0 else '?':.2f}")

# Let me try different hypothesis: KARATSUBA or FFT butterfly network
# Output = butterfly(input) where butterfly is a bit-reversal permutation circuit
# In FFT: the bit-reversed order of index i is brev(i)
# For a radix-2 FFT with N=1024 points, input index i maps to output index brev(i)
# So: f(i) = brev10(i) ? Let me recheck
print(f"\nf(0)={ef(outputs261,0)}, brev10(0)=0, brev10(1)=512")
print(f"f(1)={ef(outputs261,1)}, brev10(1)=512, brev10(2)=256")
# f(0)=512=brev10(1), f(1)=256=brev10(2)... so f(i)=brev10(i+1)!
# But why does it fail at i=16?

# CRITICAL: is the truth table perhaps ordered LSB-first instead of MSB-first?
# If the truth table index represents the input with bit0 = MSB (not LSB),
# then input i actually represents the value brev10(i)
# So the function evaluated at x (where x is the BF16-style bit pattern)
# would use index = brev10(x)

print("\nTesting LSB-first input encoding hypothesis:")
# If input x uses LSB-first encoding, index = brev10(x)
# Then f(brev10(x)) = some function of x
# For x=1 (0b0000000001): index = brev10(1) = 512
# ef(outputs261, 512) = ?
print(f"For x=1: index=brev10(1)=512, ef(512)={ef(outputs261, 512)}")
# If we ALSO interpret the output as LSB-first:
# output value brev10(ef(index))
for x in [0,1,2,3,4,7,8,15,16,31,32]:
    idx = brev10(x)
    out_raw = ef(outputs261, idx) if idx < 1024 else -1
    if out_raw >= 0:
        out_x = brev10(out_raw)
        print(f"  x={x}: idx={idx}, raw_out={out_raw}, decoded_out={out_x}")

# COMPLETELY different approach: look at the output as a SORT NETWORK output
# Input = 10 bits, each bit is an unsorted element
# Output = sorted version of the bits
# No: sorting 10 single bits just gives N ones followed by N zeros

# What if it's a NETWORK RANKING? Input = 10-element tournament graph?
# Or: input[9:5] and input[4:0] are two 5-bit NUMBERS to be sorted

print("\nSort hypothesis: output = sorted(upper5, lower5) concatenated:")
correct_sort = 0
for i in range(1024):
    A = (i >> 5) & 0x1F
    B = i & 0x1F
    lo, hi = min(A,B), max(A,B)
    expected = (hi << 5) | lo
    out = ef(outputs261, i)
    if out == expected:
        correct_sort += 1
print(f"  {correct_sort}/1024 match (sort two 5-bit numbers)")

# Check other sort orderings
correct_sort2 = 0
for i in range(1024):
    A = (i >> 5) & 0x1F
    B = i & 0x1F
    lo, hi = min(A,B), max(A,B)
    expected = (lo << 5) | hi
    out = ef(outputs261, i)
    if out == expected:
        correct_sort2 += 1
print(f"  {correct_sort2}/1024 match (sort two 5-bit numbers, lo in high)")

# =========================================================================
# ex252: The transitions show a pattern! Let me decode it.
# 0x0000 (0.0) -> 0x8A
# 0x0001 -> 0x0A
# 0x0002 -> 0xF2
# 0x0003 -> 0x72
# 0x0004 -> 0x0A  (same as 0x0001!)
# 0x0005 -> 0xF2  (same as 0x0002!)
# Pattern repeats with period 3... or at least shares values
#
# Wait: 0x0000 = 0 (special: +zero)
# 0x0001, 0x0004 both give 0x0A -> difference = 3
# 0x0002, 0x0005 both give 0xF2 -> difference = 3
# 0x0003, 0x0006 both give 0x72 -> difference = 3
# So there's a period of 3 in the MANTISSA?
#
# BF16 subnormals: exp=0, mantissa=0..127
# The 7-bit mantissa field runs from 0..127
# 0x0001 has mantissa=1, 0x0004 has mantissa=4... wait:
# 0x0001 as BF16: sign=0, exp=0, mantissa=0x01=1 -> out=0x0A
# 0x0004 as BF16: sign=0, exp=0, mantissa=0x04=4 -> out=0x0A
# Both have mantissa that differs by 3...
#
# The 7-bit mantissa is i & 0x7F (low 7 bits when exp=0)
# For mantissa=1,4,7,...: output = 0x0A (period-3!)
# For mantissa=2,5,8,...: output = 0xF2 (period-3!)
# For mantissa=3,6,9,...: output = 0x72 (period-3!)
# For mantissa=0: output = 0x8A (special: +zero)
#
# This is modular classification: output = f(mantissa mod 3)?
# Actually mantissa mod 3: 1%3=1, 4%3=1, 7%3=1 -> same output 0x0A YES!
#
# So for exp=0 (subnormals), f depends on mantissa mod 3?
# But BF16 normals (exp=1..254) have mantissa too...
# Let me check what happens for exp=1:
# =========================================================================
print("\n=== ex252: Modular structure analysis ===")
n_in, n_out, outputs252 = load_truth('ex252')

# For exp=0 (subnormals), check f(mantissa mod 3)
print("\nSubnormal (exp=0) outputs by mantissa mod 3:")
for mod in range(8):
    # Get all mantissa values with mantissa % mod3 == mod % 3
    sample = [(i, ef(outputs252, i)) for i in range(128) if i % 3 == mod % 3 and mod < 3]
    if mod >= 3:
        break
    outs = set(out for _, out in sample)
    print(f"  mantissa mod 3 == {mod%3}: outputs = {[hex(v) for v in sorted(outs)]}")

# Check for all subnormals (exp=0, mantissa=0..127):
print("\nAll subnormal outputs by mantissa:")
for m in range(16):
    inp = m  # sign=0, exp=0, mantissa=m
    out = ef(outputs252, inp)
    print(f"  mantissa={m:3d}: out=0x{out:02X} (mantissa mod 3 = {m%3})")

# Now check normals with exp=1
print("\nNormal (exp=1) outputs by mantissa:")
for m in range(16):
    inp = (1 << 7) | m  # sign=0, exp=1, mantissa=m
    out = ef(outputs252, inp)
    print(f"  exp=1,m={m:3d}: out=0x{out:02X}")

# Check exp=1 by mantissa mod 3
print("\nNormal exp=1 outputs by mantissa mod 3:")
for mod in range(3):
    outs = set(ef(outputs252, (1<<7)|m) for m in range(128) if m % 3 == mod)
    print(f"  exp=1, mantissa mod 3 == {mod}: outputs = {sorted([hex(v) for v in outs])[:5]}")

# Now the KEY question: does the output ONLY depend on mantissa mod 3 and something about exponent?
print("\nChecking if output depends on mantissa mod 3:")
mod3_correct = 0
for i in range(65536):
    exp = (i >> 7) & 0xFF
    mantissa = i & 0x7F
    sign = (i >> 15) & 1
    # Compute expected output based on mantissa mod 3 and sign
    m3 = mantissa % 3
    # We need to also check: does exp affect it?

# Check correlation: for fixed mantissa mod 3, does output vary with exp?
print("\nFor mantissa=5 (5%3=2), vary exp:")
for exp in range(12):
    inp = (exp << 7) | 5  # sign=0, exp=exp, mantissa=5
    out = ef(outputs252, inp)
    print(f"  exp={exp:3d}: out=0x{out:02X}")

print("\nFor mantissa=6 (6%3=0), vary exp:")
for exp in range(12):
    inp = (exp << 7) | 6
    out = ef(outputs252, inp)
    print(f"  exp={exp:3d}: out=0x{out:02X}")

# =========================================================================
# ex286: Let me now look at the complete 13x13 function more carefully
# Try: is this a 6-bit x 7-bit MULTIPLICATION mod 2^13?
# Or a MATRIX MULTIPLICATION over GF(2)?
# =========================================================================
print("\n=== ex286: Multiplication/XOR matrix check ===")
n_in, n_out, outputs286 = load_truth('ex286')

# Try: output = (A * B) mod 8192 where A=upper6, B=lower7
print("Testing A*B mod 8192 (A=upper6, B=lower7):")
correct = sum(1 for i in range(8192)
              if ef(outputs286, i) == (((i>>7)*(i&0x7F)) % 8192))
print(f"  Correct: {correct}/8192")

print("Testing A*B mod 8192 (A=upper7, B=lower6):")
correct = sum(1 for i in range(8192)
              if ef(outputs286, i) == (((i>>6)*(i&0x3F)) % 8192))
print(f"  Correct: {correct}/8192")

# Exhaustive split check with +1/-1 offsets
print("Trying A^B (XOR) with various splits:")
for split in range(1, 13):
    lo_bits = split
    hi_bits = 13 - split
    lo_mask = (1 << lo_bits) - 1
    correct = sum(1 for i in range(8192)
                  if ef(outputs286, i) == ((i & lo_mask) ^ (i >> lo_bits)))
    if correct > 100:
        print(f"  split={split} (lo={lo_bits}, hi={hi_bits}): {correct}/8192 XOR matches")

# Try: is it a square root? input = 13-bit number, output = some function
# sqrt(0) = 0, sqrt(1) = 1, sqrt(4) = 2...
# But f(0) = 8191 (all 1s), not 0
print("\nSqrt hypothesis: f(i) = floor(sqrt(i)) extended with complement?")
print("f(0)=8191 = 0b1111111111111 = all 1s (= ~0 in 13 bits)")
print("This could be: f(i) = NOT(something), or f is complement-based")

# Let me check: what does f DO for simple values with one bit set?
print("\nOne-hot inputs:")
for bit in range(13):
    inp = 1 << bit
    out = ef(outputs286, inp)
    compl_in = (~inp) & 0x1FFF
    compl_out = (~out) & 0x1FFF
    print(f"  inp={inp:4d} (bit {bit}): out={out:4d} ({out:013b})  ~out={compl_out:4d} (~out={compl_out:013b})")

# Check: is the function f(x) = some sort of CORRELATION between x and some constant?
# One-hot inputs give outputs: 6143, 7167, 8062, 8127, 8031, 7871, 8135, 8187, 8181, 8171, 7805, 6655, 2015
# Let me compute ~out for each:
print("\n~out for one-hot inputs:")
for bit in range(13):
    inp = 1 << bit
    out = ef(outputs286, inp)
    compl_out = (~out) & 0x1FFF
    print(f"  bit {bit}: inp={inp:4d}, ~out={compl_out:4d} ({compl_out:013b})")

# f(0) = 8191 = ~0. So f(0) = NOT(0) = all 1s
# f(1) = 6143, ~f(1) = 2048 = 0b10000000000 = 2^11
# f(2) = 7167, ~f(2) = 1024 = 0b01000000000 = 2^10
# f(4) = 8127, ~f(4) = 64  = 0b00001000000 = 2^6
# f(8) = 8187, ~f(8) = 4   = 0b00000000100 = 2^2
#
# So for inp=2^k, ~f(inp) = 2^(something)?
# inp=2^0=1: ~out=2^11
# inp=2^1=2: ~out=2^10
# inp=2^2=4: ~out=2^6
# inp=2^3=8: ~out=2^2
# ...wait: 2^2->2^6 and 2^3->2^2 don't fit a simple pattern
# Let me map these:
# bit 0 -> bit 11 (XOR distance = 11)
# bit 1 -> bit 10 (XOR distance = 9)
# bit 2 -> bit 6 (XOR distance = 4)
# bit 3 -> bit 2 (XOR distance = -1?!)
# Actually these are NON-LINEAR one-bit implications

# MOST IMPORTANT: f(0) = ~0 means that when input is ALL ZEROS, output is ALL ONES
# This looks like a COMPLEMENT operation, but with modifications for non-zero inputs

print("\nKey pattern: for input=0, output=~0 (13-bit all-ones)")
print("For other inputs, output differs from ~input")
print("Checking: is f(i) = NOT(permutation(i))?")
# If f(i) = ~p(i) where p is some permutation, then:
# ~f(i) = p(i) which should be a permutation
neg_outputs = [(~ef(outputs286, i)) & 0x1FFF for i in range(8192)]
neg_unique = len(set(neg_outputs))
print(f"Unique ~f(i) values: {neg_unique}/8192 (should be 8192 if bijection)")

if neg_unique < 8192:
    print("NOT a simple complemented bijection")
    dup_count = Counter(neg_outputs)
    print(f"Most common ~f(i): {sorted(dup_count.items(), key=lambda x:-x[1])[:5]}")
else:
    print("IS a complemented bijection (permutation)!")
