#!/usr/bin/env python3
"""Aggressive parallel optimizer — must be run via: wsl -e python3 student/aggressive_opt.py"""
import sys, os, subprocess, tempfile, time, shutil, re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "benchmarks"
OUT_DIR = ROOT / "output"
STUDENT = ROOT / "student"
ABC = STUDENT / "abc"
PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")

CASES_BUDGET = [
    ("ex286", 600), ("ex252", 600), ("ex219", 400), ("ex261", 400),
    ("ex250", 400), ("ex299", 400), ("ex297", 400), ("ex217", 300),
    ("ex240", 300), ("ex263", 300), ("ex264", 300), ("ex262", 300),
    ("ex224", 300), ("ex223", 300), ("ex225", 300),
]

FLOWS = [
    ("ds60",      'read_aiger "{aig}"\n&get; &deepsyn -T 60 -I 4; &put; write_aiger -s "{out}"\nprint_stats', 75),
    ("ds120",     'read_aiger "{aig}"\n&get; &deepsyn -T 120 -I 6; &put; write_aiger -s "{out}"\nprint_stats', 140),
    ("ds180",     'read_aiger "{aig}"\n&get; &deepsyn -T 180 -I 8; &put; write_aiger -s "{out}"\nprint_stats', 200),
    ("tt_ds60",   'read_truth -f "{truth}"\nst; &get; &deepsyn -T 60 -I 4; &put; write_aiger -s "{out}"\nprint_stats', 75),
    ("tt_ds120",  'read_truth -f "{truth}"\nst; &get; &deepsyn -T 120 -I 6; &put; write_aiger -s "{out}"\nprint_stats', 140),
    ("tt_ds180",  'read_truth -f "{truth}"\nst; &get; &deepsyn -T 180 -I 8; &put; write_aiger -s "{out}"\nprint_stats', 200),
    ("aig_if16",  'read_aiger "{aig}"\ndch; if -K 16; strash; dc2; rewrite -z; refactor -z; dc2; balance; write_aiger -s "{out}"\nprint_stats', 60),
    ("aig_dch3",  'read_aiger "{aig}"\ndch; if -K 12; dch; if -K 14; dch; if -K 16; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats', 90),
    ("aig_rsub",  'read_aiger "{aig}"\nresub -K 10 -N 2; dc2; dch; if -K 12; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats', 60),
    ("aig_mfs2",  'read_aiger "{aig}"\nmfs2; dch; if -K 12; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats', 60),
    ("gia_r3rs",  'read_aiger "{aig}"\n&get; &resyn3rs; &put; dch; if -K 8; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats', 60),
    ("gia_crs",   'read_aiger "{aig}"\n&get; &compress2rs; &put; dch; if -K 8; strash; dc2; balance; write_aiger -s "{out}"\nprint_stats', 60),
]

def run_abc(script, timeout=120):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script); sp = f.name
    try:
        r = subprocess.run([str(ABC), "-f", sp], capture_output=True, text=True, timeout=timeout)
        m = PS_RE.search(r.stdout + r.stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        print(f"  run_abc error: {e}", file=sys.stderr)
    finally:
        try: os.unlink(sp)
        except: pass
    return None, None

def opt_case(case, budget):
    truth = BENCH / f"{case}.truth"
    aig = OUT_DIR / f"{case}.aig"
    log_f = STUDENT / "logs" / f"agg_{case}.txt"

    cur_area, cur_delay = run_abc(f'read_aiger "{aig}"\nprint_stats\n', 30) if aig.exists() else (None, None)
    cur_adp = (cur_area * cur_delay) if cur_area else float("inf")
    best_adp = cur_adp

    lines = [f"=== {case} cur_area={cur_area} cur_delay={cur_delay} cur_adp={cur_adp:,} ==="]
    start = time.time()

    with tempfile.TemporaryDirectory() as tmp:
        for name, tmpl, to in FLOWS:
            elapsed = time.time() - start
            if elapsed > budget:
                lines.append("TIME BUDGET EXCEEDED")
                break
            if "{aig}" in tmpl and not aig.exists():
                continue

            out_tmp = Path(tmp) / f"{case}_{name}.aig"
            script = tmpl.replace("{truth}", str(truth)).replace("{aig}", str(aig)).replace("{out}", str(out_tmp))

            area, delay = run_abc(script, to + 15)
            if area and delay:
                adp = area * delay
                tag = ""
                if adp < best_adp:
                    best_adp = adp
                    tag = " *** BEST ***"
                    if out_tmp.exists():
                        shutil.copy2(out_tmp, aig)
                lines.append(f"  {name:20s}: {area}x{delay}={adp:,}{tag}")
            else:
                lines.append(f"  {name:20s}: FAILED/TIMEOUT")

    if best_adp < cur_adp:
        result = f"IMPROVED {cur_adp:,}->{best_adp:,} ({(1-best_adp/cur_adp)*100:.1f}%)"
    else:
        result = f"no_improvement(best={best_adp:,})"
    lines.append(result)
    log_f.write_text("\n".join(lines))
    return f"[{case}] {result}"


def main():
    print(f"Aggressive parallel opt: {len(CASES_BUDGET)} cases, 4 workers")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(opt_case, c, b): c for c, b in CASES_BUDGET}
        for f in as_completed(futs):
            print(f.result())
    print("Done.")


if __name__ == "__main__":
    main()
