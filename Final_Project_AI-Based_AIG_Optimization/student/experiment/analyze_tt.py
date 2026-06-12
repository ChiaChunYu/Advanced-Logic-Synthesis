#!/usr/bin/env python3
"""Analyze truth table structure of hardest cases."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))
from blif_builder import read_truth

HARD = ["ex252", "ex286", "ex240", "ex250"]
REF = {"ex252": 2603, "ex286": 2376, "ex240": 13299, "ex250": 20355}

for case in HARD:
    truth_path = ROOT / "benchmarks" / f"{case}.truth"
    table = read_truth(truth_path)
    ni = table.num_inputs
    no = table.num_outputs
    n_rows = 2 ** ni

    print(f"\n{'='*50}")
    print(f"Case: {case}  inputs={ni}  outputs={no}  ref_adp={REF.get(case,0)}")

    # Count 1s per output, check for constant outputs
    const0 = const1 = sparse = dense = 0
    for oi in range(no):
        out_bits = table.outputs[oi]
        ones = sum(bin(b).count('1') for b in out_bits)
        density = ones / n_rows
        if ones == 0:
            const0 += 1
        elif ones == n_rows:
            const1 += 1
        elif density < 0.05 or density > 0.95:
            sparse += 1
            print(f"  output {oi}: {ones}/{n_rows} ones ({density:.1%}) *** SPARSE ***")
        else:
            dense += 1

    print(f"  const0={const0}, const1={const1}, sparse={sparse}, dense={dense}")

    # Check how many unique output patterns exist
    patterns = set()
    for oi in range(no):
        bits_tuple = tuple(table.outputs[oi])
        patterns.add(bits_tuple)
    print(f"  unique output bit patterns: {len(patterns)} (of {no} outputs)")

    # Check for output redundancy (same output multiple times)
    neg_patterns = set()
    for oi in range(no):
        neg = bytes(b ^ 0xFF for b in table.outputs[oi])
        neg_patterns.add(bytes(table.outputs[oi]))
        neg_patterns.add(neg)
    print(f"  unique+negated patterns: {len(neg_patterns)//2} distinct functions")

    # What does current AIG look like
    from abc_core import measure_adp
    ABC = ROOT / "student" / "abc"
    aig = ROOT / "output" / f"{case}.aig"
    area, delay, adp = measure_adp(ABC, aig, 30, ROOT)
    print(f"  Current AIG: area={area} delay={delay} ADP={adp}")
    ref = REF.get(case, 0)
    if ref:
        # If ref ADP = area*delay, what combos work?
        print(f"  Ref ADP={ref}. Possible: ", end="")
        for a in range(1, 500):
            if ref % a == 0:
                d = ref // a
                if 1 <= d <= 50:
                    print(f"{a}x{d}", end=" ")
        print()
