#!/usr/bin/env python3
"""Investigate ex286 structure to understand why TA gets ADP=2376."""
import sys, subprocess, tempfile, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))
from blif_builder import read_truth

ABC = ROOT / "student" / "abc"
BENCH = ROOT / "benchmarks"
OUT = ROOT / "output"

case = "ex286"
truth_path = BENCH / f"{case}.truth"
aig_path = OUT / f"{case}.aig"

table = read_truth(truth_path)
ni, no = table.num_inputs, table.num_outputs
n_rows = 2 ** ni

print(f"ex286: {ni} inputs, {no} outputs = {n_rows} rows")

def run_abc(script, timeout=60):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout+5)
    return r.stdout + r.stderr

def get_adp_from_out(text):
    m = re.search(r"and\s*=\s*(\d+).*lev\s*=\s*(\d+)", text)
    if m:
        a, d = int(m.group(1)), int(m.group(2))
        return a, d, a*d
    return 0, 0, 0

# Analyze the truth table patterns
print("\n=== Output density per output ===")
for oi in range(no):
    out_bits = table.outputs[oi]
    ones = sum(bin(b).count('1') for b in out_bits)
    density = ones / n_rows
    print(f"  out[{oi:2d}]: {ones:5d}/{n_rows} ones ({density:.3f})")

# Check if this might be a permutation / encoding of a smaller function
print("\n=== Checking if outputs are related ===")
out_data = []
for oi in range(no):
    out_bits = bytes(table.outputs[oi])
    ones = sum(bin(b).count('1') for b in out_bits)
    out_data.append((oi, out_bits, ones))

# Check if any two outputs are identical or complementary
for i in range(no):
    for j in range(i+1, no):
        bi = out_data[i][1]
        bj = out_data[j][1]
        bj_neg = bytes(b ^ 0xFF for b in bj)
        if bi == bj:
            print(f"  out[{i}] == out[{j}] *** DUPLICATE ***")
        elif bi == bj_neg:
            print(f"  out[{i}] == ~out[{j}] *** COMPLEMENT ***")

# Investigate: for each output, how many input variables actually matter
print("\n=== Support size per output ===")
for oi in range(no):
    out_bits = table.outputs[oi]
    support = []
    for v in range(ni):
        # Check if variable v influences output oi
        for row in range(n_rows):
            row_neg = row ^ (1 << v)  # flip bit v
            byte_r = row >> 3
            bit_r = row & 7
            byte_rn = row_neg >> 3
            bit_rn = row_neg & 7
            val_r = (out_bits[byte_r] >> bit_r) & 1
            val_rn = (out_bits[byte_rn] >> bit_rn) & 1
            if val_r != val_rn:
                support.append(v)
                break
    print(f"  out[{oi:2d}]: support size={len(support)} vars={support}")

# Check if this looks like an unsigned multiplier by checking output ordering
print("\n=== Testing: is it an unsigned divider quotient? ===")
# Try all permutations: maybe the function is a known function with input permutation
from exact_function_recognition import detect_unsigned_divider_quotient, detect_unsigned_sqrt, detect_unsigned_square
print(f"  unsigned_divider: {detect_unsigned_divider_quotient(table)}")
print(f"  unsigned_sqrt: {detect_unsigned_sqrt(table)}")
print(f"  unsigned_square: {detect_unsigned_square(table)}")

# Try from the existing AIG — maybe it IS already optimal and TA number is wrong?
print("\n=== Current AIG stats ===")
out = run_abc(f'read_aiger "{aig_path}"; ps; print_level', 30)
print(out[:400])

# Try aggressive deepsyn longer (120s) with -O
print("\n=== Trying longer deepsyn (120s) on current AIG ===")
with tempfile.TemporaryDirectory() as tmpd:
    pareto = Path(tmpd) / "pareto"
    pareto.mkdir()
    script = f'read_aiger "{aig_path}"; &get; &my_deepsyn -T 120 -I 16 -S 0 -O "{pareto}"; &put; ps'
    out = run_abc(script, 130)
    print(out[-200:])
    best = 0
    for f in sorted(pareto.glob("*.aig")):
        text = run_abc(f'read_aiger "{f}"; ps', 30)
        a, d, adp = get_adp_from_out(text)
        if adp:
            print(f"  {f.name}: area={a} delay={d} ADP={adp}")
            if best == 0 or adp < best:
                best = adp
    print(f"  Best ADP: {best}")
