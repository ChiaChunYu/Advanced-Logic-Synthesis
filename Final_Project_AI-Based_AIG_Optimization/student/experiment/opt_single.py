#!/usr/bin/env python3
"""Single-case optimizer. Usage: python3 opt_single.py <case> [time_budget]"""
import sys
import os
import subprocess
import tempfile
import time
import shutil
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
OUT_DIR = ROOT / "output"
STUDENT = ROOT / "student"
ABC = STUDENT / "abc"

PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")


def run_abc(script: str, timeout: int = 120) -> tuple:
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False, dir=tempfile.gettempdir()) as f:
        f.write(script)
        sp = f.name
    try:
        result = subprocess.run([str(ABC), "-f", sp], capture_output=True, text=True, timeout=timeout)
        out = result.stdout + result.stderr
        m = PS_RE.search(out)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    finally:
        try:
            os.unlink(sp)
        except Exception:
            pass
    return None, None


FLOWS = [
    ("tt_deepsyn_60",   'read_truth -f "{truth}"\nst; &get; &deepsyn -T 60 -I 4 -C 1000; &put; write_aiger -s "{out}"\nprint_stats'),
    ("tt_deepsyn_120",  'read_truth -f "{truth}"\nst; &get; &deepsyn -T 120 -I 6 -C 2000; &put; write_aiger -s "{out}"\nprint_stats'),
    ("tt_ttopt_K6",     'read_truth -f "{truth}"\nst; &get; &ttopt -C 5000 -K 6; &put; write_aiger -s "{out}"\nprint_stats'),
    ("tt_ttopt_K8",     'read_truth -f "{truth}"\nst; &get; &ttopt -C 10000 -K 8; &put; write_aiger -s "{out}"\nprint_stats'),
    ("tt_dch_if8",      'read_truth -f "{truth}"\nst; dch; if -K 8; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"\nprint_stats'),
    ("tt_dch_if10",     'read_truth -f "{truth}"\nst; dch; if -K 10; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"\nprint_stats'),
    ("tt_dch_if12",     'read_truth -f "{truth}"\nst; dch; if -K 12; strash; dc2; rewrite -z; refactor -z; balance; write_aiger -s "{out}"\nprint_stats'),
    ("tt_brev_dc2_K6",  'read_truth -f "{truth}"\nst; &get; brev10; dc2; dch; if -K 6; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats'),
    ("aig_deepsyn_90",  'read_aiger "{aig}"\n&get; &deepsyn -T 90 -I 5 -C 1500; &put; write_aiger -s "{out}"\nprint_stats'),
    ("aig_ttopt_K8",    'read_aiger "{aig}"\n&get; &ttopt -C 8000 -K 8; &put; write_aiger -s "{out}"\nprint_stats'),
    ("aig_dch_if12",    'read_aiger "{aig}"\ndch; if -K 12; strash; dc2; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"\nprint_stats'),
    ("aig_dch_if14",    'read_aiger "{aig}"\ndch; if -K 14; strash; dc2; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"\nprint_stats'),
    ("aig_resub8_dch",  'read_aiger "{aig}"\nresub -K 8 -N 2; dc2; dch; if -K 8; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats'),
    ("aig_sopb_deep",   'read_aiger "{aig}"\n&get; &sopb; &deepsyn -T 60 -I 4; &put; write_aiger -s "{out}"\nprint_stats'),
]


def main():
    if len(sys.argv) < 2:
        print("Usage: opt_single.py <case> [time_budget_sec]")
        sys.exit(1)

    case = sys.argv[1]
    time_budget = int(sys.argv[2]) if len(sys.argv) > 2 else 300

    truth_path = BENCH / f"{case}.truth"
    current_aig = OUT_DIR / f"{case}.aig"
    result_file = STUDENT / "logs" / f"opt_{case}.txt"
    result_file.parent.mkdir(exist_ok=True)

    log = open(result_file, "w", buffering=1)

    def say(msg):
        print(msg)
        log.write(msg + "\n")

    say(f"=== opt_single {case} (budget={time_budget}s) ===")

    if not truth_path.exists():
        say("ERROR: truth table not found")
        return

    cur_adp = float("inf")
    if current_aig.exists():
        cur_area, cur_delay = run_abc(f'read_aiger "{current_aig}"\nprint_stats', 30)
        if cur_area and cur_delay:
            cur_adp = cur_area * cur_delay
            say(f"Current: area={cur_area} delay={cur_delay} ADP={cur_adp:,}")

    best_adp = cur_adp
    start = time.time()

    with tempfile.TemporaryDirectory(dir=tempfile.gettempdir()) as tmpdir:
        for flow_name, template in FLOWS:
            elapsed = time.time() - start
            if elapsed > time_budget:
                say("Time budget exceeded")
                break

            if "{aig}" in template and not current_aig.exists():
                continue

            tmp_out = Path(tmpdir) / f"{case}_{flow_name}.aig"
            script = template.format(
                truth=str(truth_path).replace("\\", "/"),
                aig=str(current_aig).replace("\\", "/") if current_aig.exists() else "",
                out=str(tmp_out).replace("\\", "/"),
            )

            try:
                area, delay = run_abc(script, timeout=150)
                if area and delay:
                    adp = area * delay
                    tag = ""
                    if adp < best_adp:
                        best_adp = adp
                        tag = " *** BEST ***"
                        if tmp_out.exists():
                            shutil.copy2(tmp_out, current_aig)
                    say(f"  {flow_name:30s}: area={area:6d} delay={delay:3d} ADP={adp:10,}{tag}")
            except Exception as e:
                say(f"  {flow_name}: ERROR {e}")

    if best_adp < cur_adp:
        say(f"RESULT: {cur_adp:,} -> {best_adp:,} ({(1-best_adp/cur_adp)*100:.1f}% improvement)")
    else:
        say(f"RESULT: No improvement (best={best_adp:,})")

    log.close()


if __name__ == "__main__":
    main()
