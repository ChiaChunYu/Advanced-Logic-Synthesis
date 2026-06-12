#!/usr/bin/env python3
"""Analyze the hardest cases to understand why TA has much better results."""
import sys, subprocess, tempfile, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "student"))

ABC = ROOT / "student" / "abc"
OUTPUT = ROOT / "output"
BENCHMARKS = ROOT / "benchmarks"

HARD = ["ex252", "ex286"]  # worst ratio cases

def run_abc(script, timeout=60):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout + 5)
    return r.stdout + r.stderr

def get_adp(path):
    out = run_abc(f'read_aiger "{path}"; ps', 30)
    m = re.search(r"and\s*=\s*(\d+).*lev\s*=\s*(\d+)", out)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(1)) * int(m.group(2))
    return 0, 0, 0

REF_ADP = {"ex252": 2603, "ex286": 2376}

for case in HARD:
    print(f"\n{'='*60}")
    print(f"Case: {case}")
    aig = OUTPUT / f"{case}.aig"
    truth = BENCHMARKS / f"{case}.truth"

    area, delay, adp = get_adp(aig)
    print(f"Current: area={area}, delay={delay}, ADP={adp}")
    ref = REF_ADP[case]
    print(f"Reference ADP={ref}, ratio={adp/ref:.2f}x")

    # Try all synthesis flows from truth table
    flows = [
        ("fraig+dc2",     f'read_truth -xf "{truth}"; st; fraig; dc2; balance'),
        ("aig_rewrite",   f'read_truth -xf "{truth}"; st; &get; &syn2 -J 8; &put; balance'),
        ("deep_dc2",      f'read_truth -xf "{truth}"; st; dc2; rewrite -z; refactor -z; dc2; rewrite -z; balance'),
        ("compress2rs",   f'read_truth -xf "{truth}"; st; balance;rewrite;refactor;balance;rewrite;rewrite -z;balance;refactor -z;rewrite -z;balance'),
        ("if_map",        f'read_truth -xf "{truth}"; st; if -K 6 -a; &get; &put; balance'),
        ("mfs",           f'read_truth -xf "{truth}"; st; fraig; dc2; rewrite -z; mfs2; balance'),
        ("tt_strash",     f'read_truth -xf "{truth}"; st; strash; dc2; rewrite; refactor; balance'),
    ]

    with tempfile.TemporaryDirectory() as tmpd:
        tmp = Path(tmpd)
        for name, script in flows:
            out_aig = tmp / f"{case}_{name}.aig"
            full_script = f'{script}; write_aiger -s "{out_aig}"'
            try:
                run_abc(full_script, 60)
                if out_aig.exists():
                    a, d, adp2 = get_adp(out_aig)
                    print(f"  {name:20s}: area={a:4d} delay={d:2d} ADP={adp2:6d}")
                else:
                    print(f"  {name:20s}: no output")
            except Exception as e:
                print(f"  {name:20s}: ERROR {e}")

        # Try deepsyn with -O
        print(f"\n  Deepsyn runs (30s each):")
        for seed in [0, 7, 42]:
            pareto = tmp / f"pareto_{seed}"
            pareto.mkdir()
            script = f'read_truth -xf "{truth}"; st; &get; &my_deepsyn -T 30 -I 4 -S {seed} -O "{pareto}"; &put; ps'
            try:
                run_abc(script, 40)
                best = 0
                best_name = ""
                for f in pareto.glob("*.aig"):
                    a, d, adp2 = get_adp(f)
                    if adp2 and (best == 0 or adp2 < best):
                        best = adp2
                        best_name = f.name
                print(f"  deepsyn seed={seed:2d}:           best ADP={best:6d}  ({best_name})")
            except Exception as e:
                print(f"  deepsyn seed={seed:2d}: ERROR {e}")
