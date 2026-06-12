#!/usr/bin/env python3
"""
Critical analysis: ex261 (bit reversal) and ex252 (float classification).
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

def eval_func(outputs, v):
    return sum(outputs[i][v] << (len(outputs)-1-i) for i in range(len(outputs)))

def bf16_to_float(val):
    return struct.unpack('>f', struct.pack('>I', val<<16))[0]

# =========================================================================
# ex261 FINAL HYPOTHESIS:
#
# For A=1, B=0..31: outputs are 256,128,384,64,320,192,448,32,...,0
# This is a BIT-REVERSAL of the 9-bit value (B concatenated with some carry)!
#
# Actually: A=1, B=0 -> 256 = 0b100000000
#           A=1, B=1 -> 128 = 0b010000000
#           A=1, B=2 -> 384 = 0b110000000
#           A=1, B=3 ->  64 = 0b001000000
# These are 9-bit bit-reversals of 2,4,6,8... NO
#
# WAIT: 256=2^8, 128=2^7, 384=3*128, 64=2^6...
# And for i=0..31 (just upper 5 bits = 0):
# output for B=k is bit_reverse_10(k+1) but CAPPED at different threshold
#
# KEY INSIGHT from "A=0, B=1: i=1 -> out=256":
# f(A=0, B=1) = 256 = bit_reverse10(2) = bit_reverse10(2*1)
# f(A=0, B=2) = 768 = bit_reverse10(3) = bit_reverse10(2*2)?  no, brev(3)=768, brev(4)=64
# Hmm: f(A=0, B=k) for k=1,2,3,4 = brev10(2),brev10(3),brev10(4)?
# brev10(2) = 256? 2 = 0b0000000010, rev = 0b0100000000 = 256. YES!
# brev10(3) = 0b0000000011 -> 0b1100000000 = 768. YES!
# brev10(4) = 0b0000000100 -> 0b0010000000 = 128. But f(A=0,B=3)=128...
# Wait: f(A=0, B=3) = 128. brev10(4) = 128. And B=3 gives brev10(4)?
# That would mean f(A=0, B=k) = brev10(k+1) which is what I found earlier (for i=0..15)
#
# Now for A=1: f(A=1, B=0) = 256 = brev10(2) = f(A=0, B=1)
#              f(A=1, B=1) = 128 = brev10(4) = f(A=0, B=3)
# So f(A=1, B=k) = f(A=0, B=2k+1)?  NO:
# f(A=1, B=0) = brev10(2) corresponds to k+1=2
# f(A=1, B=1) = brev10(4) corresponds to k+1=4... that's k*2 not 2k+1
#
# INSIGHT: This is a BIT-REVERSED ADDRESS / VAN DER CORPUT SEQUENCE!
# The input is an INDEX, and the output is the bit-reversal of that index + 1
# BUT: for large inputs (i >= some threshold), the output clamps to 0
#
# Let me check: which inputs give output = 0?
# From earlier: 31, 63, 95, 127, ..., 991 (all multiples of 32 that end in 11111)
# AND 992..1023 all give 0
#
# Interesting: inputs 992-1023 all give 0. That's the range where BOTH halves
# of the 10-bit input have top bits set...
# 992 = 0b1111100000, 1023 = 0b1111111111
# 31  = 0b0000011111
# 63  = 0b0000111111
# These are all inputs where LOWER 5 BITS are all 1 (= 0x1F = 31)
# OR where upper 5 bits are all 1 (0x1F << 5 = 992-1023)
# Let me verify:
n_in, n_out, outputs261 = load_truth('ex261')

print("=== ex261: PATTERN VERIFICATION ===")
zero_inputs = [i for i in range(1024) if eval_func(outputs261, i) == 0]
lower5_mask = [i for i in range(1024) if (i & 0x1F) == 0x1F]
upper5_mask = [i for i in range(1024) if (i >> 5) == 0x1F]
print(f"Inputs giving 0: {zero_inputs[:20]}...")
print(f"Inputs with lower5=0x1F: {lower5_mask[:20]}...")
print(f"Inputs with upper5=0x1F: {upper5_mask[:20]}...")
print(f"Union of masks: {set(lower5_mask)|set(upper5_mask) == set(zero_inputs)}")

# So: f(i)=0 IFF (lower5(i)==31 OR upper5(i)==31)
# This means: f is defined for inputs where NEITHER half is all-ones
# This looks like a SAFE DIVISION or MODULAR ARITHMETIC constraint

# NEW HYPOTHESIS: This is a 5-bit UNSIGNED DIVIDE with 10-bit output
# In Booth or non-restoring division:
# Dividend = upper5, Divisor = lower5
# But divisor cannot be 0 or 31 (all ones)?

# Let me try: A=dividend=upper5, B=divisor=lower5
# f(A, B) = some division-related result
print("\n5-bit division checks:")
div_results = {}
for A in range(31):  # skip A=31 (all ones)
    for B in range(1, 31):  # skip B=0 and B=31
        i = (A << 5) | B
        out = eval_func(outputs261, i)
        q = A // B
        r = A % B
        div_results[(A, B)] = (out, q, r)

# Check various encodings
for encoding_name, encoding_fn in [
    ("q*32+r", lambda q,r,A,B: q*32+r),
    ("r*32+q", lambda q,r,A,B: r*32+q),
    ("q only", lambda q,r,A,B: q),
    ("r only", lambda q,r,A,B: r),
    ("q*64+r*2", lambda q,r,A,B: q*64+r*2),
]:
    correct = sum(1 for (A,B),(out,q,r) in div_results.items()
                  if out == encoding_fn(q,r,A,B))
    total = len(div_results)
    print(f"  '{encoding_name}': {correct}/{total}")

# Sample outputs for small A, B
print("\nSample (A, B) -> output, expected quotient, remainder:")
for A in range(8):
    for B in [1, 2, 3, 4, 5]:
        i = (A << 5) | B
        out = eval_func(outputs261, i)
        print(f"  A={A}, B={B}: out={out} q={A//B} r={A%B}")

# ALTERNATIVE: try A=lower 5, B=upper 5
print("\nReversed: A=lower5 (dividend), B=upper5 (divisor):")
for A in range(8):
    for B in [1, 2, 3, 4, 5]:
        i = (B << 5) | A  # A in lower 5, B in upper 5
        out = eval_func(outputs261, i)
        print(f"  A={A}(lower), B={B}(upper): out={out} q={A//B} r={A%B}")

# =========================================================================
# ex252: BF16 values 1.0->0x2C, 1.5->0x00, 2.0->0x0A
#
# These are TINY BF16 values being used as inputs: 4.316e-39, 5.418e-39...
# These are the SUBNORMAL range of BF16 (exp=0)!
# But 1.0 and 2.0 are definitely normal...
#
# WAIT: I may have the bit ordering WRONG for the input
# The truth table index is bits[0..N-1] where bit 0 might be MSB or LSB
# Let me check: if input encoding is REVERSED (bit 0 = LSB, bit 15 = MSB):
# The index 0x3F80 is being used directly, but maybe the ACTUAL BF16 value
# is bit-reversed: bits of 0x3F80 = 0011 1111 1000 0000
# Reversed = 0000 0001 1111 1100 = 0x01FC
# 0x01FC as BF16 = 2^(3-127) * (1 + 0x7C/0x80) = tiny subnormal? no
# Actually as float32 bits: 0x01FC0000 = 1.09356e-38? Still tiny.
#
# But WAIT: the inputs for output=0x2C have sample BF16 vals:
# 1.754e-38, 2.195e-38, 2.305e-38... These are normal but tiny
# And my "1.0->0x2C" example used inp=0x3F80 which as a 16-bit integer is:
# 0x3F80 = 16256. Does this make sense? YES - 0x3F80 IS 1.0 in BF16!
#
# So the output for BF16(1.0) = 0x2C. Let me just check a wider range:
# =========================================================================
print("\n=== ex252: Full range scan for key outputs ===")
n_in, n_out, outputs252 = load_truth('ex252')

# What BF16 values map to each output?
print("\nOut=0x2C: BF16 inputs (first 20):")
out2c_inputs = [i for i in range(65536) if eval_func(outputs252, i) == 0x2C]
for inp in out2c_inputs[:20]:
    print(f"  {inp:04X} = {bf16_to_float(inp):.6g}")

print("\nOut=0x3C: BF16 inputs (first 20):")
out3c_inputs = [i for i in range(65536) if eval_func(outputs252, i) == 0x3C]
for inp in out3c_inputs[:20]:
    print(f"  {inp:04X} = {bf16_to_float(inp):.6g}")

print("\nOut=0x82: BF16 inputs (first 20):")
out82_inputs = [i for i in range(65536) if eval_func(outputs252, i) == 0x82]
for inp in out82_inputs[:20]:
    print(f"  {inp:04X} = {bf16_to_float(inp):.6g}")

# Let me look at all 65536 (input, output) pairs organized by output
# and try to find what RANGE of BF16 values each output corresponds to
print("\nFor each output: min/max BF16 positive value that gives it:")
out_to_pos_inputs = {}
for i in range(32768):  # positive BF16 values
    out = eval_func(outputs252, i)
    if out not in out_to_pos_inputs:
        out_to_pos_inputs[out] = []
    out_to_pos_inputs[out].append(i)

print("Positive BF16 -> output mapping (ranges):")
prev_out = None
transitions = []
for inp in range(65536):
    out = eval_func(outputs252, inp)
    if out != prev_out:
        transitions.append((inp, out, bf16_to_float(inp)))
        prev_out = out
    if len(transitions) > 100:
        break

print("First 50 transitions in BF16 value space:")
for inp, out, f in transitions[:50]:
    print(f"  {inp:04X} ({f:.6g}) -> 0x{out:02X}")
