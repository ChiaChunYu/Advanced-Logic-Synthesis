#!/usr/bin/env python3
"""Analyze ex286 circuit in detail."""
import sys, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

from blif_builder import read_truth
from exact_function_recognition import (
    detect_signed_multiplier, detect_unsigned_multiplier,
    detect_unsigned_divider_quotient, detect_unsigned_sqrt, detect_unsigned_square
)
from boolean_fingerprint import format_fingerprint, fingerprint_case

ABC = ROOT / "student" / "abc"
case = "ex286"
truth_path = ROOT / "benchmarks" / f"{case}.truth"
aig_path = ROOT / "output" / f"{case}.aig"

table = read_truth(truth_path)
print(f"inputs={table.num_inputs}, outputs={table.num_outputs}")
print(f"signed_mult: {detect_signed_multiplier(table)}")
print(f"unsigned_mult: {detect_unsigned_multiplier(table)}")
try:
    print(f"unsigned_sqrt: {detect_unsigned_sqrt(table)}")
except Exception as e:
    print(f"unsigned_sqrt: error={e}")
try:
    print(f"unsigned_square: {detect_unsigned_square(table)}")
except Exception as e:
    print(f"unsigned_square: error={e}")
try:
    print(f"unsigned_divider: {detect_unsigned_divider_quotient(table)}")
except Exception as e:
    print(f"unsigned_divider: error={e}")

try:
    fp = fingerprint_case(truth_path)
    print(f"family: {fp.family}")
    print(f"strategy: {fp.strategy}")
    print(f"fingerprint: {format_fingerprint(fp)[:300]}")
except Exception as e:
    print(f"fingerprint error: {e}")

# Look at the AIG stats
def run_abc(script, timeout=30):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout+5)
    return r.stdout + r.stderr

out = run_abc(f'read_aiger "{aig_path}"; ps; print_level; print_stats')
print("\nABC ps output:")
print(out[:600])

# Try what the existing AIG looks like structurally
out2 = run_abc(f'read_aiger "{aig_path}"; ps; strash; ps; balance; ps')
print("\nAfter strash+balance:")
print(out2[:400])

# Look at truth table first few lines
print(f"\nFirst 5 lines of truth table:")
with open(truth_path) as f:
    for i, line in enumerate(f):
        print(f"  {line.rstrip()}")
        if i >= 4:
            break
