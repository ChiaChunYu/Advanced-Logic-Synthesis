#!/usr/bin/env python3
"""Check if outputs of ex286 are affine (XOR of inputs)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))
from blif_builder import read_truth

CASES = ["ex286", "ex252", "ex240", "ex250", "ex223", "ex224", "ex225"]

for case in CASES:
    truth_path = ROOT / "benchmarks" / f"{case}.truth"
    table = read_truth(truth_path)
    ni, no = table.num_inputs, table.num_outputs
    n_rows = 2 ** ni

    print(f"\n{case}: {ni}in {no}out")

    def get_bit(oi, row):
        return (table.outputs[oi][row >> 3] >> (row & 7)) & 1

    affine_count = 0
    for oi in range(no):
        # Try to find if out[oi] = XOR of some subset of inputs (+ constant)
        # This means: f(x XOR y) = f(x) XOR f(y) XOR f(0) for all x,y
        # Equivalently: f is affine if f(0) + f(ei) + f(ej) + f(ei+ej) = 0 for all i,j
        is_affine = True
        f0 = get_bit(oi, 0)
        for i in range(ni):
            ei = 1 << i
            for j in range(i+1, ni):
                ej = 1 << j
                if get_bit(oi, ei) ^ get_bit(oi, ej) ^ get_bit(oi, ei^ej) ^ f0 != 0:
                    is_affine = False
                    break
            if not is_affine:
                break

        if is_affine:
            # Find the linear part
            f0 = get_bit(oi, 0)
            coeffs = [get_bit(oi, 1 << v) ^ f0 for v in range(ni)]
            print(f"  out[{oi}] is AFFINE: const={f0} + XOR of inputs {[v for v,c in enumerate(coeffs) if c]}")
            affine_count += 1

    if affine_count > 0:
        print(f"  => {affine_count} affine outputs!")
    else:
        print(f"  no affine outputs")

    # Check for quadratic (degree-2 ANF)
    quad_count = 0
    for oi in range(no):
        f0 = get_bit(oi, 0)
        linear_coeffs = [get_bit(oi, 1 << v) ^ f0 for v in range(ni)]
        # subtract the linear part
        is_quad = True
        for i in range(ni):
            for j in range(i+1, ni):
                for k in range(j+1, ni):
                    ei, ej, ek = 1<<i, 1<<j, 1<<k
                    # Check if there's any degree-3 term
                    mobius = (get_bit(oi,0) ^ get_bit(oi,ei) ^ get_bit(oi,ej) ^ get_bit(oi,ek)
                              ^ get_bit(oi,ei^ej) ^ get_bit(oi,ei^ek) ^ get_bit(oi,ej^ek)
                              ^ get_bit(oi,ei^ej^ek))
                    if mobius:
                        is_quad = False
                        break
                if not is_quad:
                    break
            if not is_quad:
                break
        if is_quad:
            quad_count += 1

    print(f"  quadratic (degree<=2) outputs: {quad_count}/{no}")
