#!/usr/bin/env python3
"""Targeted optimizer for highest-ratio cases using aggressive ABC flows.

Focuses on ex252 (ratio 4.92x) and ex286 (ratio 5.99x).
Tries multiple ABC strategies and keeps the best result.
"""
import sys
import os
import subprocess
import tempfile
import time
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
OUT_DIR = ROOT / "output"
STUDENT = ROOT / "student"
ABC = STUDENT / "abc"

CASES = [
    "ex286",  # ratio 5.99x, 2376 ref, 14252 current
    "ex252",  # ratio 4.92x, 2603 ref, 12801 current
    "ex219",  # ratio 2.46x, 5640 ref, 13869 current
    "ex217",  # ratio 2.13x, 5785 ref, 12340 current
    "ex261",  # ratio 2.41x, 2041 ref, 4914 current
    "ex250",  # ratio 2.23x, 20355 ref, 45296 current
    "ex299",  # ratio 2.21x, 1013807 ref, 2240860 current
    "ex297",  # ratio 2.33x, 225900 ref, 525623 current
]

PS_RE = __import__("re").compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")


def run_abc(script: str, timeout: int = 120) -> tuple[int | None, int | None]:
    """Run ABC script and return (area, delay)."""
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False, dir=tempfile.gettempdir()) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [str(ABC), "-f", script_path],
            capture_output=True, text=True, timeout=timeout
        )
        out = result.stdout + result.stderr
        m = PS_RE.search(out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass
    return None, None


def get_truth_path(case: str) -> Path:
    return BENCH / f"{case}.truth"


def get_current_aig(case: str) -> Path:
    return OUT_DIR / f"{case}.aig"


def verify_aig(aig_path: Path, case: str) -> bool:
    """Verify AIG against truth table using ABC CEC."""
    truth_path = get_truth_path(case)
    script = f"""read_truth -f "{truth_path}"
st; &get; &cec -t
"""
    # Actually need to compare against the AIG
    script2 = f"""read_aiger "{aig_path}"
read_truth -f "{truth_path}"
cec
"""
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False, dir=tempfile.gettempdir()) as f:
        f.write(script2)
        sp = f.name
    try:
        result = subprocess.run(
            [str(ABC), "-f", sp],
            capture_output=True, text=True, timeout=60
        )
        out = result.stdout + result.stderr
        return "equivalent" in out.lower() or "networks are equivalent" in out.lower()
    except Exception:
        return False
    finally:
        try:
            os.unlink(sp)
        except Exception:
            pass


# Aggressive ABC flows to try
FLOWS = [
    # From-truth flows
    ("tt_deepsyn", """read_truth -f "{truth}"
st; &get; &deepsyn -T 60 -I 4 -C 1000; &put; write_aiger -s "{out}"
print_stats"""),
    ("tt_deepsyn_long", """read_truth -f "{truth}"
st; &get; &deepsyn -T 120 -I 6 -C 2000; &put; write_aiger -s "{out}"
print_stats"""),
    ("tt_ttopt", """read_truth -f "{truth}"
st; &get; &ttopt -C 10000 -K 8; &put; write_aiger -s "{out}"
print_stats"""),
    ("tt_ttopt_K6", """read_truth -f "{truth}"
st; &get; &ttopt -C 5000 -K 6; &put; write_aiger -s "{out}"
print_stats"""),
    ("tt_dch_if8", """read_truth -f "{truth}"
st; dch; if -K 8; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"
print_stats"""),
    ("tt_dch_if6", """read_truth -f "{truth}"
st; dch; if -K 6; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"
print_stats"""),
    ("tt_dch_if10", """read_truth -f "{truth}"
st; dch; if -K 10; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"
print_stats"""),
    ("tt_orchestrate", """read_truth -f "{truth}"
st; &get; &orchestrate -K 8 -N 2; &put; dc2; balance; write_aiger -s "{out}"
print_stats"""),
    # From existing AIG, try more aggressive flows
    ("aig_deepsyn", """read_aiger "{aig}"
&get; &deepsyn -T 90 -I 5 -C 1500; &put; write_aiger -s "{out}"
print_stats"""),
    ("aig_ttopt_K8", """read_aiger "{aig}"
&get; &ttopt -C 8000 -K 8; &put; write_aiger -s "{out}"
print_stats"""),
    ("aig_sopb_deepsyn", """read_aiger "{aig}"
&get; &sopb; &deepsyn -T 60 -I 4; &put; write_aiger -s "{out}"
print_stats"""),
    ("aig_dch_if12", """read_aiger "{aig}"
dch; if -K 12; strash; dc2; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"
print_stats"""),
    ("aig_dch_if14", """read_aiger "{aig}"
dch; if -K 14; strash; dc2; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"
print_stats"""),
    ("aig_resub_deep", """read_aiger "{aig}"
resub -K 8 -N 2; dc2; resub -K 6; balance; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"
print_stats"""),
]


def optimize_case(case: str, time_budget: int = 300) -> dict:
    truth_path = get_truth_path(case)
    current_aig = get_current_aig(case)
    best_aig = OUT_DIR / f"{case}.aig"

    if not truth_path.exists():
        print(f"  [{case}] truth table not found, skipping")
        return {}

    # Get current ADP
    cur_area, cur_delay = None, None
    if current_aig.exists():
        script = f'read_aiger "{current_aig}"\nprint_stats'
        cur_area, cur_delay = run_abc(script, timeout=30)

    if cur_area and cur_delay:
        cur_adp = cur_area * cur_delay
        print(f"  [{case}] current: area={cur_area} delay={cur_delay} ADP={cur_adp:,}")
    else:
        cur_adp = float("inf")
        print(f"  [{case}] no current AIG found")

    start = time.time()
    best_adp = cur_adp
    best_area, best_delay = cur_area, cur_delay
    results = []

    with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as tmpdir:
        for flow_name, flow_template in FLOWS:
            elapsed = time.time() - start
            if elapsed > time_budget:
                print(f"  [{case}] Time budget exceeded, stopping")
                break

            # Decide which base to use
            if "{aig}" in flow_template and not current_aig.exists():
                continue

            tmp_out = Path(tmpdir) / f"{case}_{flow_name}.aig"

            script = flow_template.format(
                truth=str(truth_path).replace("\\", "/"),
                aig=str(current_aig).replace("\\", "/") if current_aig.exists() else "",
                out=str(tmp_out).replace("\\", "/"),
            )

            try:
                area, delay = run_abc(script, timeout=150)
                if area and delay:
                    adp = area * delay
                    indicator = ""
                    if adp < best_adp:
                        indicator = " *** NEW BEST ***"
                        best_adp = adp
                        best_area = area
                        best_delay = delay
                        if tmp_out.exists():
                            shutil.copy2(tmp_out, best_aig)
                    results.append((flow_name, area, delay, adp))
                    print(f"    {flow_name:30s}: area={area:6d} delay={delay:3d} ADP={adp:10,}{indicator}")
            except Exception as e:
                print(f"    {flow_name}: ERROR {e}")

    if best_adp < cur_adp:
        improvement = (1 - best_adp / cur_adp) * 100
        print(f"  [{case}] IMPROVED: {cur_adp:,} -> {best_adp:,} ({improvement:.1f}% better)")
    else:
        print(f"  [{case}] No improvement found (best={best_adp:,})")

    return {"case": case, "best_adp": best_adp, "best_area": best_area, "best_delay": best_delay}


def main():
    print("=" * 70)
    print("  Targeted optimizer for highest-ratio cases")
    print("=" * 70)

    for case in CASES:
        print(f"\n[{case}]")
        optimize_case(case, time_budget=300)

    print("\nDone. Run evaluate.py to see updated scores.")


if __name__ == "__main__":
    main()
