#!/usr/bin/env python3
import struct

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'

def load_truth(name):
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f: data = f.read()
    lines = [l for l in data.split(b'\n') if l.strip()]
    outputs = [[int(b)-48 for b in line] for line in lines]
    return len(lines[0]).bit_length()-1, len(lines), outputs

def ef(outputs, v):
    return sum(outputs[i][v] << (len(outputs)-1-i) for i in range(len(outputs)))

def brev10(v):
    return int(f'{v:010b}'[::-1], 2)

n_in, n_out, outputs261 = load_truth('ex261')

# Check symmetry
sym_check = sum(1 for i in range(1024)
                if ef(outputs261, i) == ef(outputs261, ((i&0x1F)<<5)|(i>>5)))
print(f"ex261 symmetric in A,B (upper5 <-> lower5): {sym_check}/1024")

# Key: f(i=1)=256=brev10(2), f(i=32)=256 (same!)
print(f"f(2)={ef(outputs261,2)}, f(64)={ef(outputs261,64)}")
print(f"f(3)={ef(outputs261,3)}, f(96)={ef(outputs261,96)}")
print(f"f(4)={ef(outputs261,4)}, f(128)={ef(outputs261,128)}")

# Check for i=32..47:
print("\nf(32..47) vs brev10(2*(i-32)+2):")
for i in range(32,48):
    expected = brev10(2*(i-32)+2)
    actual = ef(outputs261, i)
    print(f"  f({i})={actual}, brev10({2*(i-32)+2})={expected}, match={actual==expected}")

# The pattern seems to be that f is related to a bit-reverse counter
# that increments differently based on the input structure.
# Let me try: what is the "effective counter value" for each input?
# I.e., what N satisfies f(i)=brev10(N)?

print("\nReverse-engineering effective counter N for each input:")
brev_to_n = {brev10(n): n for n in range(1, 2048) if brev10(n) < 1024}
for i in range(64):
    out = ef(outputs261, i)
    N = brev_to_n.get(out, -1)
    A = (i>>5) & 0x1F
    B = i & 0x1F
    print(f"  i={i:3d}(A={A:2d},B={B:2d}): f={out:4d}, N_where_brev(N)=f: {N}")

# HYPOTHESIS: N = A*B + A + B + 1 = (A+1)*(B+1)?
print("\nChecking N = (A+1)*(B+1):")
correct = 0
for i in range(1024):
    A = (i>>5) & 0x1F
    B = i & 0x1F
    N = (A+1)*(B+1)
    if N < 1024 and brev10(N) == ef(outputs261, i):
        correct += 1
    elif N == 0 and ef(outputs261, i) == 0:
        correct += 1
print(f"  Matches: {correct}/1024")

# Sample check:
for A in range(5):
    for B in range(5):
        i = (A<<5)|B
        out = ef(outputs261, i)
        N = (A+1)*(B+1)
        expected = brev10(N) if N < 1024 else 0
        print(f"  A={A},B={B}: out={out}, (A+1)*(B+1)={N}, brev({N})={expected}, match={out==expected}")

# =========================================================================
# ex252: Let me check if this is related to exponent+mantissa arithmetic
# Output pattern for mantissa=5, varying exp:
# exp=0: 0xF2, exp=1: 0x32, exp=2: 0x72, exp=3: 0xD2, exp=4: 0xB2, exp=5: 0x52...
#
# 0xF2=11110010, 0x32=00110010, 0x72=01110010, 0xD2=11010010, 0xB2=10110010, 0x52=01010010
# All end in 0010 = 2! So last 4 bits = mantissa mod 16 or something?
# Actually all values end in "10" (bits 1:0 = 2)... wait no:
# bit 0 is always 0, bit 1 varies. Let me check: 0xF2=11110010, bit1=1; 0x32=00110010, bit1=1
# Actually they all have bit1=1 for mantissa=5?
# Let me look at the upper nibble of 0xF2>>2=0x3C=60, 0x32>>2=0x0C=12, 0x72>>2=0x1C=28
# 60,12,28,52,44,20... differences: -48, +16, +24, -8, -24...
#
# 0xF2 >> 1 = 0x79 = 121 (val in 7-bit space)
# 0x32 >> 1 = 0x19 = 25
# 0x72 >> 1 = 0x39 = 57
# 0xD2 >> 1 = 0x69 = 105
# 0xB2 >> 1 = 0x59 = 89
# 0x52 >> 1 = 0x29 = 41
# Differences: 25-121=-96, 57-25=32, 105-57=48, 89-105=-16, 41-89=-48...
# These differ by multiples of 16 roughly
#
# INSIGHT: These 26 output values ALL have bit 0 = 0
# If we look at output >> 1, we get 26 7-bit values
# The 7-bit values are: 0,1,5,6,9,10,14,17,22,25,30,33,41,46,49,57,62,65,69,73,81,89,97,105,113,121
# These are 26 distinct values in [0, 127]
#
# A simple check: are these the values of some simple sequence?
# 0,1,5,6 -> diffs 1,4,1
# 9,10,14 -> diffs 1,4
# 17,22,25,30 -> diffs 5,3,5
# 33,41,46,49 -> diffs 8,5,3
# 57,62,65,69,73 -> diffs 5,3,4,4
# 81,89,97,105,113,121 -> diffs 8,8,8,8,8
#
# The last 6 values (81..121) increase by 8 each time
# 121 = 7*17 + 2, or just these are specific lookup indices
# =========================================================================

n_in252, n_out252, outputs252 = load_truth('ex252')

print("\n=== ex252: What determines the output? ===")
# For exp=1, mantissa varies (normals starting at BF16=0x80)
# Let me check if this is related to mantissa + exp*C for some constant C
print("For exp=0..8, mantissa=0..7:")
for exp in range(9):
    for m in range(8):
        inp = (exp << 7) | m
        out = ef(outputs252, inp)
        out7 = out >> 1  # 7-bit value
        print(f"  exp={exp},m={m}: out=0x{out:02X} out7={out7}")

# Check: out7 = (exp + m) mod something? or exp*k + m*j mod something?
print("\nCheck out7 = f(exp, mantissa) for pattern:")
for exp in range(5):
    for m in range(5):
        inp = (exp << 7) | m
        out = ef(outputs252, inp)
        out7 = out >> 1
        print(f"  exp={exp},m={m}: out7={out7}")
