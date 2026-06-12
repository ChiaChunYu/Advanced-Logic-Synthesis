#!/usr/bin/env python3
"""Overnight full optimization: all cases, multiple seeds, save best results.
Run via: wsl -e python3 student/overnight_opt.py
"""
import sys, os, subprocess, tempfile, shutil, re, csv
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path("/mnt/c/Users/Chun_yu/Desktop/Github project/Advanced-Logic-Synthesis/Final_Project_AI-Based_AIG_Optimization")
BENCH = ROOT / "benchmarks"
OUT_DIR = ROOT / "output"
STUDENT = ROOT / "student"
ABC = STUDENT / "abc"
LOG_DIR = STUDENT / "logs"
PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")

# All 100 cases with per-case timeout (seconds per deepsyn run)
# Higher ratio -> more budget
ALL_CASES = [
    ("ex286", 180), ("ex252", 180), ("ex219", 120), ("ex261", 120),
    ("ex297", 120), ("ex250", 120), ("ex299", 120), ("ex264", 90),
    ("ex217", 90),  ("ex263", 90),  ("ex240", 90),  ("ex247", 60),
    ("ex225", 90),  ("ex262", 60),  ("ex248", 60),  ("ex295", 90),
    ("ex223", 90),  ("ex224", 90),  ("ex246", 45),  ("ex205", 60),
    ("ex204", 60),  ("ex241", 60),  ("ex289", 60),  ("ex201", 45),
    ("ex256", 45),  ("ex245", 60),  ("ex270", 45),  ("ex279", 60),
    ("ex200", 60),  ("ex251", 60),  ("ex280", 60),  ("ex284", 60),
    ("ex265", 45),  ("ex266", 45),  ("ex277", 45),  ("ex275", 45),
    ("ex295", 60),  ("ex207", 60),  ("ex227", 60),  ("ex231", 45),
    ("ex272", 45),  ("ex287", 45),  ("ex276", 45),
]

# Also add remaining cases from benchmarks not yet covered
def get_all_benchmark_cases():
    cases = set(c for c, _ in ALL_CASES)
    extra = []
    for f in sorted(BENCH.glob("*.truth")):
        c = f.stem
        if c not in cases:
            extra.append((c, 30))
    return ALL_CASES + extra

SEEDS = [0, 7, 42, 99]

def run_abc(script, timeout=200):
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        sp = f.name
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

def get_current_adp(case):
    aig = OUT_DIR / f"{case}.aig"
    if not aig.exists():
        return None, None, float("inf")
    a, d = run_abc(f'read_aiger "{aig}"\nprint_stats\n', 30)
    return a, d, (a * d) if a else float("inf")

def check_pareto(pareto_dir, best_adp, case):
    best = best_adp
    best_file = None
    for pf in sorted(Path(pareto_dir).glob("*.aig")):
        m = re.search(r'_(\d+)_(\d+)\.aig$', pf.name)
        if m:
            pd, pa = int(m.group(1)), int(m.group(2))
            padp = pa * pd
            if padp < best:
                best = padp
                best_file = str(pf)
                print(f"[{case}] pareto {pa}x{pd}={padp:,} ***BEST***", flush=True)
    return best, best_file

def opt_case(case, run_timeout):
    truth = BENCH / f"{case}.truth"
    aig = OUT_DIR / f"{case}.aig"

    cur_a, cur_d, cur_adp = get_current_adp(case)
    best_adp = cur_adp
    best_file = None

    print(f"[{case}] start {cur_a}x{cur_d}={cur_adp:,}", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        for seed in SEEDS:
            for src, cost in [("tt", "area"), ("tt", "adp"), ("aig", "area"), ("aig", "adp")]:
                if src == "tt" and not truth.exists():
                    continue
                if src == "aig" and not aig.exists():
                    continue

                pdir = tmp / f"p_{src}_{seed}_{cost}"
                pdir.mkdir()
                out_tmp = tmp / f"{case}_{src}_{seed}_{cost}.aig"

                if src == "tt":
                    script = (
                        f'read_truth -xf "{truth}"\n'
                        f'st; &get; &my_deepsyn -T {run_timeout} -I 8 -S {seed} '
                        f'-O "{pdir}" -C {cost}; &put; '
                        f'write_aiger -s "{out_tmp}"\nprint_stats\n'
                    )
                else:
                    script = (
                        f'read_aiger "{aig}"\n'
                        f'&get; &my_deepsyn -T {run_timeout} -I 8 -S {seed} '
                        f'-O "{pdir}" -C {cost}; &put; '
                        f'write_aiger -s "{out_tmp}"\nprint_stats\n'
                    )

                a, d = run_abc(script, run_timeout + 30)
                if a and d:
                    adp = a * d
                    tag = ""
                    if adp < best_adp:
                        best_adp = adp
                        best_file = str(out_tmp)
                        tag = " ***BEST***"
                    print(f"[{case}] {src} s={seed} {cost}: {a}x{d}={adp:,}{tag}", flush=True)

                b, bf = check_pareto(pdir, best_adp, case)
                if b < best_adp:
                    best_adp = b
                    best_file = bf

        if best_file and best_adp < cur_adp and Path(best_file).exists():
            shutil.copy2(best_file, aig)
            pct = (1 - best_adp / cur_adp) * 100
            print(f"[{case}] IMPROVED {cur_adp:,} -> {best_adp:,} ({pct:.1f}%)", flush=True)
            return case, True, cur_adp, best_adp
        else:
            print(f"[{case}] no_improvement best={best_adp:,}", flush=True)
            return case, False, cur_adp, best_adp


def main():
    cases = get_all_benchmark_cases()
    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for c, t in cases:
        if c not in seen:
            seen.add(c)
            deduped.append((c, t))
    cases = deduped

    print(f"Overnight opt: {len(cases)} cases, 4 workers", flush=True)
    print(f"Seeds: {SEEDS}", flush=True)

    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(opt_case, c, t): c for c, t in cases}
        for f in as_completed(futs):
            results.append(f.result())

    print("\n=== FINAL SUMMARY ===", flush=True)
    improved = [(c, old, new) for c, ok, old, new in results if ok]
    not_improved = [(c, new) for c, ok, old, new in results if not ok]

    total_saved = sum(old - new for _, old, new in improved)
    print(f"Improved: {len(improved)} cases, total ADP saved: {total_saved:,}", flush=True)
    for c, old, new in sorted(improved, key=lambda x: x[1]-x[2], reverse=True):
        print(f"  {c}: {old:,} -> {new:,} (saved {old-new:,})", flush=True)

    print(f"\nNo improvement: {len(not_improved)} cases", flush=True)
    print("Done.", flush=True)


if __name__ == "__main__":
    main()
