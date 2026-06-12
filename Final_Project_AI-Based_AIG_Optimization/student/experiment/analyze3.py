#!/usr/bin/env python3
"""Targeted deeper analysis based on first findings."""
import struct, math
from collections import Counter

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
        result |= (out_bits[input_val] << (len(outputs) - 1 - i))
    return result

def bf16_to_float(val):
    packed = struct.pack('>I', val << 16)
    return struct.unpack('>f', packed)[0]

def fp16_to_float(val):
    packed = struct.pack('>H', val & 0xFFFF)
    return struct.unpack('>e', packed)[0]

def remap_bits(val, n_bits):
    return int(f'{val:0{n_bits}b}'[::-1], 2)

# =========================================================================
# ex261: Looking at pattern more carefully
# Input 0->512=0b1000000000, 1->256=0b0100000000, 2->768=0b1100000000
# This looks like: output[9:0] = bit_interleave or shuffle of input[9:0]
# Let me check: for input = i, output = i * 512 (mod 1023)?  No...
# 0->512, 1->256, 2->768=512+256... looks like bit-reversed then shifted
# Actually: reverse(0)=0, reverse(1)=512... no
# Let's think: 0b0000000000->0b1000000000
# The output bit pattern seems to be:  input[0] ends up at output[9]...
# Actually wait: input 0 (0b0000000000) -> 512 (0b1000000000)
# That's just output[9] = 1 always? No, because input=31 -> 0.
# Let me look at this differently - output = shuffle(input)?
# =========================================================================
print("=== ex261: Bit Shuffle Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex261')

# Identify which input bit maps to which output bit
print("\nBit mapping analysis (brute force):")
for o_bit in range(n_outputs):
    for i_bit in range(n_inputs):
        # Check if out_bit[o] == in_bit[i_bit] for ALL inputs
        match_same = True
        match_inv = True
        for v in range(1024):
            out_b = (eval_func(outputs, v) >> (n_outputs-1-o_bit)) & 1
            in_b = (v >> (n_inputs-1-i_bit)) & 1
            if out_b != in_b:
                match_same = False
            if out_b != (1-in_b):
                match_inv = False
        if match_same:
            print(f"  out[{o_bit}] == in[{i_bit}]")
        elif match_inv:
            print(f"  out[{o_bit}] == ~in[{i_bit}]")

# Look for linear combinations
print("\nLooking at specific patterns:")
# Input  0 (bits: 00 00 00 00 00) -> output 512 (bits: 10 00 00 00 00)
# Input  1 (bits: 00 00 00 00 01) -> output 256 (bits: 01 00 00 00 00)
# The output always seems to have ONE bit set in the top half, ONE in bottom...
# Actually output has multiple bits set for larger inputs.
# Let me think of it as: the output is obtained by SCRAMBLING the input bits

# Check: is it a linear transform over GF(2)?
# If f(a XOR b) = f(a) XOR f(b) for all a,b, it's linear
is_linear = True
for a in range(min(100, 1024)):
    for b in range(min(100, 1024)):
        fa = eval_func(outputs, a)
        fb = eval_func(outputs, b)
        fab = eval_func(outputs, a ^ b)
        if fab != (fa ^ fb):
            is_linear = False
            break
    if not is_linear:
        break
print(f"Is linear transform: {is_linear}")

# If linear, find the transformation matrix
if is_linear:
    print("Linear transformation matrix (each row = output for unit input):")
    for i in range(n_inputs):
        out = eval_func(outputs, 1 << i)
        print(f"  in[{i}]=1: out = {out:010b} ({out})")

# Special: check if output = bit_reversal_permutation(input)?
# 0 -> 0b1000000000 = the bit reversal of 0b0000000001 = 1...
# Actually 0 -> 512: but reversing 0 gives 0, not 512
# Let me check: for each input value, what is the reversed input?
print("\nChecking specific relationship:")
for inp in [0, 1, 2, 3, 4, 8, 16, 32]:
    out = eval_func(outputs, inp)
    rev = remap_bits(inp, 10)
    print(f"  inp={inp:4d} ({inp:010b}) -> out={out:4d} ({out:010b})  rev(inp)={rev:4d} ({rev:010b})")

# =========================================================================
# ex286: Closer look - notice period 16 had 256/1000 matches
# This means f(x) == f(x+16) for 256/1000 of x values
# Let me check what the non-matching ones are
# =========================================================================
print("\n=== ex286: Period Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex286')

# Check if lower 4 bits determine something specific
print("\nGrouped by lower 4 bits (input mod 16):")
for low4 in range(16):
    outs = [eval_func(outputs, low4 + (k*16)) for k in range(min(20, 8192//16))]
    unique_outs = len(set(outs))
    print(f"  inp & 0xF = {low4:4b}: unique_outputs={unique_outs}, first few: {outs[:8]}")

# Check specific structure: maybe it's a matrix/permutation
print("\nChecking if it might be a bit-permutation:")
is_perm = True
seen = set()
for i in range(8192):
    out = eval_func(outputs, i)
    if out in seen:
        is_perm = False
        break
    seen.add(out)
print(f"  Is bijection (permutation): {is_perm}")

# Check symmetry for specific bit positions
print("\nSplit analysis: trying bit[12:7] and bit[6:0] as two 6-bit fields:")
# 13 bits = 1 + 6 + 6 or similar
for msb_bits in [1, 2, 3, 4, 5, 6]:
    lsb_bits = 13 - msb_bits
    msb_mask = ((1 << msb_bits) - 1) << lsb_bits
    lsb_mask = (1 << lsb_bits) - 1
    # Check if output MSBs depend only on input MSBs
    # i.e., out >> lsb_bits  is a function only of  inp >> lsb_bits
    msb_func = {}
    consistent = True
    for i in range(8192):
        out = eval_func(outputs, i)
        inp_msb = i >> lsb_bits
        out_msb = out >> lsb_bits
        if inp_msb in msb_func:
            if msb_func[inp_msb] != out_msb:
                consistent = False
                break
        else:
            msb_func[inp_msb] = out_msb
    print(f"  msb={msb_bits}bits,lsb={lsb_bits}bits: MSB independent: {consistent}")

# =========================================================================
# ex252: Only 26 unique outputs - what are they?
# =========================================================================
print("\n=== ex252: Limited Output Analysis ===")
n_inputs, n_outputs, outputs = load_truth('ex252')

out_counts = Counter(eval_func(outputs, i) for i in range(65536))
print(f"All {len(out_counts)} unique output values:")
for val in sorted(out_counts.keys()):
    cnt = out_counts[val]
    print(f"  0x{val:02X} ({val:08b}): count={cnt}")

# The last bit is always 0 (from earlier: constant output bit 7 = 0)
# So the output has bit 0 always 0 -> values are all even... no wait bit 7 is the MSB of 8 bits
# With 8 outputs and output[7] (LSB in our bit notation) always 0:
# Actually "constant outputs: [(7, 0)]" means output bit index 7 (the last/LSB) is always 0
# So all output values are EVEN

print(f"\nAre all outputs even (bit 0 = 0)? {all(v % 2 == 0 for v in out_counts)}")

# Map input ranges to outputs
print("\nBF16 ranges -> outputs:")
ranges = {
    'negative_normal': (0x8001, 0xFF7F),
    'positive_normal': (0x0001, 0x7F7F),
    'negative_zero': (0x8000, 0x8000),
    'positive_zero': (0x0000, 0x0000),
    'pos_inf': (0x7F80, 0x7F80),
    'neg_inf': (0xFF80, 0xFF80),
    'pos_nan': (0x7F81, 0x7FFF),
    'neg_nan': (0xFF81, 0xFFFF),
    'pos_subnorm': (0x0001, 0x007F),
    'neg_subnorm': (0x8001, 0x807F),
}
for label, (lo, hi) in ranges.items():
    out_set = set(eval_func(outputs, i) for i in range(lo, min(hi+1, lo+100)))
    print(f"  {label}: outputs = {[hex(v) for v in sorted(out_set)[:5]]}...")

# Check: does the output look like BF16 classification?
# IEEE FP class codes:
# 0=+inf, 1=-inf, 2=+zero, 3=-zero, 4=+subnorm, 5=-subnorm, 6=+normal, 7=-normal, 8=NaN
# But output has 8 bits and 26 unique values...
print("\nChecking BF16 classification hypothesis:")
def bf16_class(val):
    sign = (val >> 15) & 1
    exp = (val >> 7) & 0xFF
    mantissa = val & 0x7F
    if exp == 0xFF:
        if mantissa == 0:
            return 7 if sign else 0  # inf
        else:
            return 8  # NaN
    if exp == 0:
        if mantissa == 0:
            return 3 if sign else 2  # zero
        else:
            return 5 if sign else 4  # subnormal
    return 6  # normal (ignore sign for now)

# What output is produced for each class?
class_outputs = {}
for i in range(65536):
    c = bf16_class(i)
    out = eval_func(outputs, i)
    if c not in class_outputs:
        class_outputs[c] = set()
    class_outputs[c].add(out)

class_names = {0: '+inf', 1: '-inf', 2: '+zero', 3: '-zero', 4: '+subnorm', 5: '-subnorm', 6: 'normal', 8: 'NaN'}
for c, outs in sorted(class_outputs.items()):
    print(f"  BF16 class {class_names.get(c, c)}: unique outputs = {len(outs)}")
    print(f"    values = {[hex(v) for v in sorted(outs)[:8]]}")

# =========================================================================
# ex217/ex219 BF16: Look at the output bit patterns more carefully
# The outputs seem to have the lowest few bits constant (always ends in FD or similar)
# =========================================================================
print("\n=== ex217/ex219: Output bit pattern analysis ===")
for name in ['ex217', 'ex219']:
    n_inputs, n_outputs, outputs = load_truth(name)
    out_counts = Counter(eval_func(outputs, i) for i in range(65536))
    low_byte_counts = Counter(v & 0xFF for v in out_counts)
    print(f"\n{name}: unique outputs = {len(out_counts)}")
    print(f"  Low byte distribution (first 10): {sorted(low_byte_counts.items())[:10]}")
    # Check constant bits in output
    for bit in range(16):
        bit_vals = set((eval_func(outputs, i) >> bit) & 1 for i in range(65536))
        if len(bit_vals) == 1:
            print(f"  Output bit {bit} is always {list(bit_vals)[0]}")

    # What are the unique low bytes?
    low_bytes = set(eval_func(outputs, i) & 0xFF for i in range(65536))
    print(f"  Unique low bytes: {sorted([hex(v) for v in low_bytes])}")

# =========================================================================
# Float conversion: ex246/247/248 - 0xFE is very common, look at FP16 interpretation
# =========================================================================
print("\n=== Float Conversion: FP16 interpretation ===")
for name in ['ex246', 'ex247', 'ex248']:
    print(f"\n--- {name} (FP16 input interpretation) ---")
    n_inputs, n_outputs, outputs = load_truth(name)

    test_vals_fp16 = [
        ('+0_fp16', 0x0000),
        ('-0_fp16', 0x8000),
        ('+1.0_fp16', 0x3C00),
        ('-1.0_fp16', 0xBC00),
        ('+2.0_fp16', 0x4000),
        ('+0.5_fp16', 0x3800),
        ('+max_fp16', 0x7BFF),
        ('+inf_fp16', 0x7C00),
        ('-inf_fp16', 0xFC00),
        ('nan_fp16', 0x7E00),
        ('+3.14_fp16', 0x4248),
    ]
    for label, inp in test_vals_fp16:
        out = eval_func(outputs, inp)
        inp_f = fp16_to_float(inp)
        print(f"  {label:15s}: {inp:04X}({inp_f:.4g}) -> 0x{out:02X} ({out:08b})")

    # Where does FP16 inf map to?
    fp16_inf_out = eval_func(outputs, 0x7C00)
    fp16_ninf_out = eval_func(outputs, 0xFC00)
    fp16_nan_out = eval_func(outputs, 0x7E00)
    fp16_zero_out = eval_func(outputs, 0x0000)
    fp16_one_out = eval_func(outputs, 0x3C00)
    print(f"\n  Key mappings: +inf->0x{fp16_inf_out:02X}, -inf->0x{fp16_ninf_out:02X}, nan->0x{fp16_nan_out:02X}, +0->0x{fp16_zero_out:02X}, +1->0x{fp16_one_out:02X}")

    # Check FP8 E5M2 for FP16 inputs in valid range
    def to_fp8_e5m2_approx(f):
        """Approximate nearest FP8 E5M2 value"""
        if math.isnan(f): return 0x7F
        if math.isinf(f): return 0xFF if f < 0 else 0x7C
        if f == 0: return 0x00
        sign = 1 if f < 0 else 0
        f = abs(f)
        exp = math.floor(math.log2(f)) if f > 0 else -15
        exp_biased = exp + 15
        if exp_biased <= 0:
            # subnormal
            mantissa = round(f / (2**(-14)) * 4)
            mantissa = min(3, max(0, mantissa))
            return (sign << 7) | mantissa
        if exp_biased >= 31:
            return (sign << 7) | 0x7C  # inf
        mantissa = round((f / (2**exp) - 1.0) * 4)
        mantissa = min(3, max(0, mantissa))
        return (sign << 7) | (exp_biased << 2) | mantissa

    print(f"\n  Checking FP16 -> FP8 E5M2 conversion:")
    correct = 0
    total = 200
    for i in range(0x3400, 0x3400 + total):  # FP16 range ~0.3 to ~1.0
        out = eval_func(outputs, i)
        inp_f = fp16_to_float(i)
        expected = to_fp8_e5m2_approx(inp_f)
        if out == expected or out == (expected ^ 0x01):  # allow off-by-1
            correct += 1
    print(f"  FP16->FP8_E5M2 match (range 0x3400-0x3600): {correct}/{total}")
