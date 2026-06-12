#!/usr/bin/env python3
"""Final targeted analysis to nail down function semantics."""
import struct, math
from collections import Counter

BASE = '/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization/benchmarks'

def load_truth(name):
    path = f'{BASE}/{name}.truth'
    with open(path, 'rb') as f:
        data = f.read()
    lines = [l for l in data.split(b'\n') if l.strip()]
    n_outputs = len(lines)
    outputs = [[int(b)-48 for b in line] for line in lines]
    return len(lines[0]).bit_length()-1, n_outputs, outputs

def eval_func(outputs, input_val):
    result = 0
    for i, out_bits in enumerate(outputs):
        result |= (out_bits[input_val] << (len(outputs) - 1 - i))
    return result

def bf16_to_float(val):
    packed = struct.pack('>I', val << 16)
    return struct.unpack('>f', packed)[0]

def fp16_to_float(val):
    packed = struct.pack('>H', val & 0xFFFF)
    return struct.unpack('>e', packed)[0]

# =========================================================================
# ex261: Input 0 -> 512, 1 -> 256, 2 -> 768
# Hypothesis: this looks like a 10-bit MULTIPLICATION TABLE but as bit matrix
# OR: it's a bit-reversal sort. Let's look carefully:
# inp=0 (0000000000) -> 512 (1000000000)
# inp=1 (0000000001) -> 256 (0100000000)  -- reversed: bit[0] -> bit[8] position?
# inp=2 (0000000010) -> 768 (1100000000)  = 512 + 256
# inp=3 (0000000011) -> 128 (0010000000)
# Hmm, 0->512, 1->256, 2->512+256=768, 3->128...
# That's NOT linear. But...
# What if it's: for each input bit i (from LSB), the output gets a contribution
# based on the VALUE of that bit?
# Actually: 0->512 (bit 9 set), 1->256 (bit 8 set), 2->768 (bit 9&8), 3->128 (bit 7)...
# 0,1,2,3 = 00,01,10,11 in 2 bits. Outputs: 512=10b at top, 256=01b at top, 768=11b, 128=001 shifted
# This looks like: input[1:0] reversed = output[9:8], but that gives 00->10, 01->10, 10->01, 11->11
# That's not right either.
#
# WAIT: Look at the LOWER bits more carefully!
# inp=0: 0000000000 -> out=1000000000 (just bit 9)
# inp=16: 0000010000 -> out=1000111111
# inp=32: 0000100000 -> out=0100000000
# The difference between inp=0 and inp=16 is bit 4 set
# When bit 4 is set, bits 5-9 of output flip from 100000 to 100011
#
# New hypothesis: outputs is (A * B) where A,B are 5-bit values,
# and the INPUT encodes (B[4:0], A[4:0]) (B in high bits, A in low bits)
# Let me check more carefully: inp=0b0000000001 = B=0,A=1 -> out=256
# inp=0b0000000010 = B=0,A=2 -> out=768=512+256
# inp=0b0000000011 = B=0,A=3 -> out=128... that's weird
#
# Actually wait - let me look at this as a SORT NETWORK or COMPARISON
# 0->512: f(0)=512=0x200 is just bit 9
# 31->0: f(31)=0
# These look like they could be OUTPUT of a merge sort or bitonic sort!
#
# Try: this is a 10-bit to 10-bit SORT of 2 5-bit values
# inp = [a[4:0], b[4:0]], out = [min(a,b)[4:0] (but sorted)]
# No that would give 5+5 -> 5+5
#
# Another idea: could this be integer SQUARE ROOT?
# sqrt(0)=0, sqrt(1)=1, sqrt(4)=2, sqrt(9)=3...
# f(0)=512, not 0. So no.
#
# Actually the most striking pattern: input 16 -> 575 = 0b1000111111
# 0b1000111111 = 575. If we take input = 16 = 0b10000, and flip it...
# or: 1024-16-1 = 1007? No.
#
# Let me try: f(i) = (i * K) mod 1023 for some K?
# f(1)=256, so K=256? f(2)=768=256*3=768 -> 768/2=384 not 256
# f(1)=256, f(2)=768, f(3)=128... 256*3=768, 256*3/2=384, not 128
#
# Try f(i) = reverse_of_9bits(i % 512)?
# reverse(0, 9 bits) = 0 -> but f(0)=512, not 0
#
# Completely different approach: maybe output[9:0] = LFSR or permuted index
# =========================================================================
print("=== ex261: Final Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex261')

# Let's check what f(f(i)) looks like - composition
print("Checking f(f(i)):")
for i in [0, 1, 2, 4, 8, 16, 31, 32, 64]:
    fi = eval_func(outputs, i)
    ffi = eval_func(outputs, fi) if fi < 1024 else -1
    print(f"  f({i:3d})={fi:4d}, f(f({i}))={ffi}")

# Check: is the output the van der Corput sequence (bit reversal)?
# f(0)=512, f(1)=256, f(2)=768
# van_der_corput(0,2)=0, van_der_corput(1,2)=0.5=512/1024,
# van_der_corput(2,2)=0.25=256/1024... that gives 0,512,256 not 512,256,768!
# But if we offset by 1: f(i) = van_der_corput(i+1, 2) * 1024?
# van_der_corput(1)=512, van_der_corput(2)=256, van_der_corput(3)=768... YES!
print("\nvan der Corput sequence check:")
def van_der_corput_base2(n, nbits=10):
    """Returns floor(VdC(n) * 2^nbits) = bit_reverse(n)"""
    return int(f'{n:0{nbits}b}'[::-1], 2)

correct_vdc = sum(1 for i in range(1024)
                  if eval_func(outputs, i) == van_der_corput_base2(i+1))
print(f"  f(i) == bit_reverse(i+1) [10 bits]: {correct_vdc}/1024")

# Try: f(i) = bit_reverse(i, 9 bits) shifted?
correct_vdc2 = sum(1 for i in range(1024)
                   if eval_func(outputs, i) == van_der_corput_base2(i+1, 10))
print(f"  Same check explicit: {correct_vdc2}/1024")

# Examine more values
for i in range(0, 32):
    fi = eval_func(outputs, i)
    vdc = van_der_corput_base2(i+1, 10)
    print(f"  i={i:3d}: f={fi:4d} ({fi:010b}), VdC(i+1)={vdc:4d} ({vdc:010b}), match={fi==vdc}")

# =========================================================================
# ex252: 26 unique output values, last bit always 0
# Output values are like 0x00, 0x02, 0x0A, 0x0C, 0x12, 0x14, 0x1C...
# All are EVEN (bit 0 = 0)
# The upper 7 bits give: 0,0,0,0,1,1,1, 1,2,2,2,2,3,3,3,3...
# Actually let's look at the binary patterns:
# 0x00 = 0000 0000
# 0x02 = 0000 0010
# 0x0A = 0000 1010
# 0x0C = 0000 1100
# 0x12 = 0001 0010
# 0x14 = 0001 0100
# 0x1C = 0001 1100
# 0x22 = 0010 0010
# 0x2C = 0010 1100
# The pattern in bits 7:1 (upper 7 bits):
# 0,1,5,6,9,10,14,17,22,25,30,33,38,41,46,49,57,62,65,73,81,89,97,105,113,121
# Hmm. Wait: 0x02>>1=1, 0x0A>>1=5, 0x0C>>1=6, 0x12>>1=9, 0x14>>1=10, 0x1C>>1=14
# Differences: 1,4,1,3,1,4...
# These look like values on a 4-bit or 5-bit grid
#
# Actually: let me look at this as a BF16 -> log2 LUT or something
# BF16 +inf -> 0x0C, -inf -> 0x00, +zero -> 0x8A, -zero -> 0xF2
# NaN -> 0x00 or 0x0C
# This is definitely a classification or encoding function
#
# 0x8A = 10001010 (for +zero), 0xF2 = 11110010 (for -zero)
# 0x0C = 00001100 (for +inf), 0x00 = 00000000 (for -inf)
#
# These look like they could be INDICES into a lookup table or ENCODED values
# Perhaps this is a REDUCTION/HASHING function for attention or softmax
# =========================================================================
print("\n=== ex252: Pattern Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex252')

# Look at all 26 values and think about what they encode
vals = sorted(set(eval_func(outputs, i) for i in range(65536)))
print("All output values and their bit patterns:")
for v in vals:
    bits = f'{v:08b}'
    # Interpret as: bit7=sign?, bits6:2=some_field, bit1=?, bit0=always_0
    print(f"  0x{v:02X} = {bits}  (>>1={v>>1}, sign_bit={v>>7})")

# BF16 structure analysis:
# For BF16: sign=bit15, exp=bits14:7, mantissa=bits6:0
# What does the output encode about the input?
print("\nMapping from BF16 fields to output:")
# Check if output is a function of just exp field
exp_outputs = {}
for i in range(65536):
    exp = (i >> 7) & 0xFF
    out = eval_func(outputs, i)
    if exp not in exp_outputs:
        exp_outputs[exp] = set()
    exp_outputs[exp].add(out)

print("Exponent -> unique outputs:")
for exp in sorted(exp_outputs.keys()):
    outs = exp_outputs[exp]
    if len(outs) > 1:
        print(f"  exp={exp:3d} (0x{exp:02X}): {len(outs)} unique outputs: {[hex(v) for v in sorted(outs)[:5]]}")
    else:
        print(f"  exp={exp:3d} (0x{exp:02X}): single output = {hex(list(outs)[0])}")

# =========================================================================
# ex286: The XOR dominant is 0x1FFF meaning output often = ~input
# Let me check: does it apply some permutation to "classes" of 13-bit numbers?
# The 'class/rotation/split' hint from the problem is very relevant
# 13 bits could be: 1 bit class + 6 bit rotation + 6 bit value
# or: 2 bits class + 5 bits rotation + 6 bits value etc.
# =========================================================================
print("\n=== ex286: Class/Rotation/Split Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex286')

# Try: split as 1+6+6 (class, a, b)
# class=0: operate one way, class=1: operate another
for class_bits in [1, 2, 3]:
    remaining = 13 - class_bits
    for a_bits in range(1, remaining):
        b_bits = remaining - a_bits
        print(f"\n  Split: class={class_bits}b, a={a_bits}b, b={b_bits}b")
        # Check if all outputs within the same class have the same structure
        class_analysis = {}
        for i in range(min(512, 8192)):
            cls = i >> (a_bits + b_bits)
            a = (i >> b_bits) & ((1 << a_bits) - 1)
            b = i & ((1 << b_bits) - 1)
            out = eval_func(outputs, i)
            key = (cls, a, b)
            class_analysis[key] = out

        # Check if the function for class=0 is complement
        compl_matches = 0
        for i in range(min(512, 8192)):
            cls = i >> (a_bits + b_bits)
            if cls == 0:
                out = eval_func(outputs, i)
                compl = (~i) & 0x1FFF
                if out == compl:
                    compl_matches += 1
        print(f"    Class=0 -> ~input matches: {compl_matches}/{min(512//(1<<(a_bits+b_bits))//1 * (1<<(a_bits+b_bits)), 512)}")
        break  # just check first split for now
    if class_bits > 1:
        break

# Direct search: what's the actual function?
# Let me look at it as: 13-bit Gray code conversion? Or CRC?
print("\n  Checking Gray code:")
gray_matches = sum(1 for i in range(8192) if eval_func(outputs,i) == (i ^ (i >> 1)))
print(f"  Gray code: {gray_matches}/8192")

print("\n  Checking inverse Gray code (Gray to binary):")
def gray_to_bin(g, nbits=13):
    b = 0
    for i in range(nbits):
        b ^= (g >> i)
    return b & ((1 << nbits) - 1)

igray_matches = sum(1 for i in range(8192) if eval_func(outputs,i) == gray_to_bin(i))
print(f"  Inverse Gray code: {igray_matches}/8192")

# Try CRC-ish approach - check if f is a linear function over GF(2)
print("\n  Checking if linear over GF(2):")
is_lin = True
for a in range(min(200, 8192)):
    for b in range(min(200, 8192)):
        if eval_func(outputs, a^b) != (eval_func(outputs,a) ^ eval_func(outputs,b)):
            is_lin = False
            break
    if not is_lin:
        break
print(f"  Linear over GF(2): {is_lin}")

if is_lin:
    print("  Linear transform matrix:")
    for i in range(13):
        out = eval_func(outputs, 1 << i)
        print(f"    in[{i}] -> out: {out:013b}")

# =========================================================================
# Final: BF16 unary - what ARE ex217 and ex219?
# They have ~21K unique outputs out of 65536 possible 16-bit values
# Output low bytes come in pairs (0x12,0x13), (0x1C,0x1D), etc.
# Let me check what function maps BF16 to another BF16 with these patterns
# =========================================================================
print("\n=== ex217/ex219: Trying more BF16 unary functions ===")
for name in ['ex217', 'ex219']:
    n_inputs, n_outputs, outputs = load_truth(name)
    print(f"\n--- {name} ---")

    # Check TANH: tanh(0)=0, tanh(1)~0.76, tanh(-1)~-0.76
    # Check SIGMOID: 1/(1+exp(-x))
    # Check FLOOR, CEIL, ROUND

    # Test round-to-nearest
    round_correct = 0
    for inp in range(0x3F00, 0x4100, 4):  # range 0.5 to 4.0
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        rounded = round(inp_f)
        # Convert rounded back to BF16
        rounded_bits = struct.unpack('>I', struct.pack('>f', float(rounded)))[0] >> 16
        if out == rounded_bits:
            round_correct += 1
    print(f"  Round-to-integer: {round_correct}")

    # Test floor
    floor_correct = 0
    for inp in range(0x3F00, 0x4100, 4):
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        floored = math.floor(inp_f)
        try:
            floor_bits = struct.unpack('>I', struct.pack('>f', float(floored)))[0] >> 16
            if out == floor_bits:
                floor_correct += 1
        except:
            pass
    print(f"  Floor: {floor_correct}")

    # Check if exponent of output = exponent of input (structure-preserving)
    exp_preserved = sum(1 for i in range(min(10000, 65536))
                       if ((eval_func(outputs,i) >> 7) & 0xFF) == ((i >> 7) & 0xFF))
    print(f"  Exponent preserved: {exp_preserved}/10000")

    # Check if output = f(|input|) (depends only on magnitude)
    abs_fn_check = sum(1 for i in range(min(10000, 32768))
                      if eval_func(outputs, i) == eval_func(outputs, i | 0x8000))
    print(f"  Even function (f(x)=f(-x)): {abs_fn_check}/10000")

    # Check if output = -f(|input|) * sign (odd function)
    sign_check = True
    wrong = 0
    for i in range(min(1000, 32768)):
        out_pos = eval_func(outputs, i)
        out_neg = eval_func(outputs, i | 0x8000)
        # Is out_neg = out_pos with sign flipped?
        if (out_pos ^ 0x8000) != out_neg:
            wrong += 1
    print(f"  Odd function (f(-x)=-f(x)): wrong_count={wrong}/1000")

    # Sample the output for a range of positive BF16 values
    print(f"  BF16 values 0.5-4.0 -> output:")
    for inp in [0x3F00, 0x3F80, 0x4000, 0x4040, 0x4080, 0x40C0, 0x4100, 0x4140, 0x4180]:
        out = eval_func(outputs, inp)
        inp_f = bf16_to_float(inp)
        out_f = bf16_to_float(out)
        print(f"    {inp_f:.3f} -> {out_f:.6g} (0x{out:04X})")
