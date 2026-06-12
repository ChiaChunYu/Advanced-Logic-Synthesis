#!/usr/bin/env python3
"""Quick test: run &my_deepsyn directly on ex286 for 30 seconds and see if it helps."""
import subprocess, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABC = ROOT / "student" / "abc"
OUTPUT = ROOT / "output"
LOGS = ROOT / "student" / "logs"
LOGS.mkdir(parents=True, exist_ok=True)

case = "ex286"
aig = OUTPUT / f"{case}.aig"

def run_script(script: str, timeout: int) -> str:
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sf = f.name
    try:
        r = subprocess.run([str(ABC), "-f", sf], capture_output=True, text=True, timeout=timeout + 5)
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "(timeout)"
    except Exception as e:
        return f"ERROR: {e}"

def measure(path: Path) -> int:
    import re
    out = run_script(f'read_aiger "{path}"; ps', 30)
    m = re.search(r"and\s*=\s*(\d+).*lev\s*=\s*(\d+)", out)
    if m:
        return int(m.group(1)) * int(m.group(2))
    return 0

print(f"Current ADP: {measure(aig):,}")

with tempfile.TemporaryDirectory() as tmpd:
    tmp = Path(tmpd)
    # Try deepsyn for 60s (with -O pareto dir)
    pareto60 = tmp / "pareto60"
    pareto60.mkdir()
    script = (
        f'read_aiger "{aig}"; '
        f'&get; &my_deepsyn -T 60 -I 8 -S 0 -O "{pareto60}"; '
        f'&put; ps'
    )
    print("Running deepsyn 60s seed 0...", flush=True)
    log = run_script(script, 70)
    print(log[:500])
    best = 0
    for f in sorted(pareto60.glob("*.aig")):
        adp = measure(f)
        print(f"  {f.name}: ADP={adp:,}")
        if adp and (best == 0 or adp < best):
            best = adp
    print(f"  Best from pareto: {best:,}")

    # Try from truth table
    truth = ROOT / "benchmarks" / f"{case}.truth"
    pareto_tt = tmp / "pareto_tt"
    pareto_tt.mkdir()
    script_tt = (
        f'read_truth -xf "{truth}"; st; '
        f'&get; &my_deepsyn -T 60 -I 8 -S 7 -O "{pareto_tt}"; '
        f'&put; ps'
    )
    print("\nRunning deepsyn 60s seed 7 from truth table...", flush=True)
    log2 = run_script(script_tt, 70)
    print(log2[:500])
    best_tt = 0
    for f in sorted(pareto_tt.glob("*.aig")):
        adp = measure(f)
        print(f"  {f.name}: ADP={adp:,}")
        if adp and (best_tt == 0 or adp < best_tt):
            best_tt = adp
    print(f"  Best from pareto: {best_tt:,}")
