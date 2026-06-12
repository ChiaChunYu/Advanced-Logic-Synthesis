#!/usr/bin/env python3
"""Fix ex252: 5 outputs are constant 0, 4 outputs are degree<=2.
Build a minimal BLIF directly."""
import sys, subprocess, tempfile, shutil, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))
from blif_builder import read_truth
from abc_core import is_equivalent, measure_adp

ABC = ROOT / "student" / "abc"
BENCH = ROOT / "benchmarks"
OUT = ROOT / "output"

case = "ex252"
truth_path = BENCH / f"{case}.truth"
aig_path = OUT / f"{case}.aig"

table = read_truth(truth_path)
ni, no = table.num_inputs, table.num_outputs
n_rows = 2 ** ni

print(f"{case}: {ni}in {no}out")

def get_bit(oi, row):
    return (table.outputs[oi][row >> 3] >> (row & 7)) & 1

def run_abc(script, timeout=60):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout+5)
    return r.stdout + r.stderr

def get_adp(path):
    return measure_adp(ABC, path, 30, ROOT)

# Analyze each output
print("\nOutput analysis:")
output_types = []
for oi in range(no):
    ones = sum(bin(b).count('1') for b in table.outputs[oi])
    if ones == 0:
        output_types.append(('const0', None))
        print(f"  out[{oi}]: CONSTANT 0")
    elif ones == n_rows:
        output_types.append(('const1', None))
        print(f"  out[{oi}]: CONSTANT 1")
    else:
        # Check if affine (linear)
        f0 = get_bit(oi, 0)
        coeffs = [get_bit(oi, 1 << v) ^ f0 for v in range(ni)]
        is_affine = True
        for row in range(n_rows):
            expected = f0
            for v in range(ni):
                if (row >> v) & 1:
                    expected ^= coeffs[v]
            if expected != get_bit(oi, row):
                is_affine = False
                break
        if is_affine:
            active = [v for v, c in enumerate(coeffs) if c]
            output_types.append(('affine', (f0, active)))
            print(f"  out[{oi}]: AFFINE const={f0} XOR inputs {active}")
        else:
            output_types.append(('complex', None))
            print(f"  out[{oi}]: complex (ones={ones})")

# For affine outputs = constant 0 (f0=0, no active vars): these are truly constant 0
# Let's verify the affine ones
for oi, (typ, data) in enumerate(output_types):
    if typ == 'affine' and data:
        f0, active = data
        if len(active) == 0:
            output_types[oi] = ('const0', None)
            print(f"  [corrected] out[{oi}] is actually CONSTANT {f0}")

# Build BLIF with correct outputs
print("\nBuilding BLIF with structural knowledge...")
with tempfile.TemporaryDirectory() as tmpd:
    tmp = Path(tmpd)
    blif = tmp / f"{case}_fixed.blif"

    with open(blif, 'w') as f:
        f.write(f".model {case}_fixed\n")
        f.write(f".inputs {' '.join(f'i{v}' for v in range(ni))}\n")
        f.write(f".outputs {' '.join(f'o{oi}' for oi in range(no))}\n\n")

        for oi, (typ, data) in enumerate(output_types):
            if typ == 'const0':
                f.write(f".names o{oi}\n")
                f.write(f"0\n\n")
            elif typ == 'const1':
                f.write(f".names o{oi}\n")
                f.write(f"1\n\n")
            elif typ == 'affine':
                f0, active = data
                if not active:
                    val = '1' if f0 else '0'
                    f.write(f".names o{oi}\n")
                    f.write(f"{val}\n\n")
                else:
                    # Build XOR chain: use intermediates
                    prev = f"i{active[0]}"
                    for k, v in enumerate(active[1:]):
                        nxt = f"xor_{oi}_{k}"
                        f.write(f".names {prev} i{v} {nxt}\n")
                        f.write(f"01 1\n10 1\n\n")
                        prev = nxt
                    if f0:
                        # XOR with constant 1 = NOT
                        f.write(f".names {prev} o{oi}\n")
                        f.write(f"0 1\n\n")
                    else:
                        f.write(f".names {prev} o{oi}\n")
                        f.write(f"1 1\n\n")
            else:
                # Complex: emit truth table directly for small support
                # First find the effective support
                support = []
                for v in range(ni):
                    differs = False
                    for row in range(n_rows):
                        row2 = row ^ (1 << v)
                        if get_bit(oi, row) != get_bit(oi, row2):
                            differs = True
                            break
                    if differs:
                        support.append(v)

                print(f"  out[{oi}] support: {len(support)} vars {support}")

                f.write(f".names {' '.join(f'i{v}' for v in support)} o{oi}\n")
                for minterm in range(2**len(support)):
                    # Map support vars back to full row
                    row = 0
                    for k, v in enumerate(support):
                        if (minterm >> k) & 1:
                            row |= (1 << v)
                    if get_bit(oi, row):
                        pattern = ''.join('1' if (minterm >> k) & 1 else '0' for k in range(len(support)))
                        f.write(f"{pattern} 1\n")
                f.write("\n")

        f.write(".end\n")

    print(f"\nBLIF written: {blif}")

    # Synthesize
    best_adp = get_adp(aig_path)[2]
    print(f"Current AIG ADP: {best_adp:,}")

    flows = [
        ("balance",  "balance"),
        ("dc2",      "dc2; balance"),
        ("rwz",      "rewrite -z; refactor -z; dc2; balance"),
        ("syn2",     "&get; &syn2 -J 8; &put; balance"),
        ("deep",     "dc2; rewrite -z; refactor -z; dc2; rewrite -z; balance"),
    ]

    for fname, fcmds in flows:
        out_aig = tmp / f"{case}_{fname}.aig"
        script = f'read_blif "{blif}"; {fcmds}; write_aiger -s "{out_aig}"'
        try:
            run_abc(script, 120)
            if out_aig.exists():
                a, d, adp = get_adp(out_aig)
                print(f"  {fname:10s}: area={a:4d} delay={d:2d} ADP={adp:6d}")
                if adp and adp < best_adp:
                    if is_equivalent(ABC, truth_path, out_aig, 120, ROOT):
                        best_adp = adp
                        shutil.copyfile(out_aig, aig_path)
                        print(f"  *** IMPROVED to {adp} ***")
                    else:
                        print(f"  NOT EQUIVALENT!")
        except Exception as e:
            print(f"  {fname}: ERROR {e}")

print(f"\nFinal ADP: {get_adp(aig_path)[2]:,}")
