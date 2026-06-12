#!/usr/bin/env python3
"""Parallel optimizer: run opt_single.py for multiple cases concurrently."""
import sys
import os
import subprocess
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).resolve().parent.parent
STUDENT = ROOT / "student"

CASES = [
    ("ex286", 300),  # ratio 5.99x - HIGHEST priority
    ("ex252", 300),  # ratio 4.92x
    ("ex219", 240),  # ratio 2.46x
    ("ex217", 240),  # ratio 2.13x
    ("ex261", 240),  # ratio 2.41x
    ("ex250", 240),  # ratio 2.23x
    ("ex297", 240),  # ratio 2.33x
    ("ex299", 240),  # ratio 2.21x
    ("ex240", 240),  # ratio 2.10x
    ("ex263", 180),  # ratio 2.13x
    ("ex264", 180),  # ratio 2.17x
    ("ex262", 180),  # ratio 1.93x
    ("ex224", 180),  # ratio 1.67x
    ("ex223", 180),  # ratio 1.69x
    ("ex225", 180),  # ratio 1.82x
    ("ex248", 180),  # ratio 1.72x
    ("ex247", 180),  # ratio 1.86x
    ("ex246", 180),  # ratio 1.63x
    ("ex295", 180),  # ratio 1.74x
]

MAX_WORKERS = 4  # ABC is CPU-heavy, limit parallelism


def run_case(case: str, budget: int) -> str:
    script = STUDENT / "opt_single.py"
    log = STUDENT / "logs" / f"opt_{case}.txt"
    log.parent.mkdir(exist_ok=True)

    start = time.time()
    try:
        result = subprocess.run(
            ["python3", str(script), case, str(budget)],
            capture_output=True, text=True, timeout=budget + 60
        )
        elapsed = time.time() - start
        output = result.stdout + result.stderr
        last_line = [l for l in output.strip().splitlines() if l][-1] if output.strip() else "no output"
        return f"[{case}] ({elapsed:.0f}s) {last_line}"
    except subprocess.TimeoutExpired:
        return f"[{case}] TIMEOUT"
    except Exception as e:
        return f"[{case}] ERROR: {e}"


def main():
    print(f"Starting parallel optimization for {len(CASES)} cases ({MAX_WORKERS} workers)")
    print("=" * 70)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(run_case, case, budget): case for case, budget in CASES}

        for future in as_completed(futures):
            case = futures[future]
            try:
                result = future.result()
                print(result)
            except Exception as e:
                print(f"[{case}] EXCEPTION: {e}")

    print("=" * 70)
    print("Done. Check student/logs/opt_<case>.txt for details.")
    print("Run: python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output")


if __name__ == "__main__":
    main()
