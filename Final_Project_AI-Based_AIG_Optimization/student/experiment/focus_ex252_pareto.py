#!/usr/bin/env python3
"""Focused ex252 Pareto search.

This keeps the run narrow enough to inspect and only copies a candidate into
output/ex252.aig after ABC equivalence and strict ADP improvement.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
ABC = ROOT / "student" / "abc"
BENCH = ROOT / "benchmarks"
OUT = ROOT / "output"
PS_RE = re.compile(r"and\s*=\s*(\d+).*?lev\s*=\s*(\d+)", re.S)


def run_abc(command: str, timeout: int) -> str:
    result = subprocess.run(
        [str(ABC), "-c", command],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stdout)
    return result.stdout


def measure(path: Path) -> tuple[int, int, int]:
    match = PS_RE.search(run_abc(f'read_aiger "{path}"; ps', 60))
    if not match:
        raise RuntimeError(f"cannot parse stats for {path}")
    area = int(match.group(1))
    delay = int(match.group(2))
    return area, delay, area * delay


def equivalent(case: str, path: Path) -> bool:
    truth = BENCH / f"{case}.truth"
    output = run_abc(f'read_truth -xf "{truth}"; st; &get; &cec -t "{path}"', 120)
    return "Networks are equivalent" in output


def main() -> int:
    case = "ex252"
    current = OUT / f"{case}.aig"
    cur_area, cur_delay, cur_adp = measure(current)
    best = (cur_adp, cur_area, cur_delay, current, "current")
    print(f"[{case}] start {cur_area}x{cur_delay}={cur_adp}", flush=True)

    seeds = [0, 1, 2, 3, 5, 7, 11, 13, 17, 23, 42, 99]
    with tempfile.TemporaryDirectory(prefix="focus_ex252_") as tmp_name:
        tmp = Path(tmp_name)
        for base in ["current", "truth"]:
            for cost in ["area", "adp"]:
                for seed in seeds:
                    pareto = tmp / f"p_{base}_{cost}_{seed}"
                    pareto.mkdir()
                    cand = tmp / f"{base}_{cost}_{seed}.aig"
                    if base == "current":
                        prefix = f'read_aiger "{current}"; &get; '
                    else:
                        prefix = f'read_truth -xf "{BENCH / f"{case}.truth"}"; st; &get; '
                    command = (
                        prefix
                        + f'&my_deepsyn -T 90 -I 8 -S {seed} -O "{pareto}" -C {cost}; '
                        + f'&put; strash; dc2; balance; write_aiger -s "{cand}"'
                    )
                    try:
                        run_abc(command, 140)
                    except Exception as exc:
                        print(f"[{case}] error {base} {cost} seed={seed}: {str(exc)[:100]}", flush=True)
                        continue

                    files = list(pareto.glob("*.aig"))
                    if cand.exists():
                        files.append(cand)
                    for path in files:
                        try:
                            area, delay, adp = measure(path)
                        except Exception:
                            continue
                        tag = ""
                        if adp < best[0] and equivalent(case, path):
                            best = (adp, area, delay, path, f"{base}_{cost}_{seed}_{path.name}")
                            tag = " BEST"
                        if adp < 16000:
                            print(f"[{case}] {base} {cost} seed={seed} {path.name}: {area}x{delay}={adp}{tag}", flush=True)

        if best[3] != current:
            shutil.copy2(best[3], current)
            print(f"[{case}] IMPROVED {cur_adp} -> {best[1]}x{best[2]}={best[0]} via {best[4]}", flush=True)
        else:
            print(f"[{case}] no improvement, best remains {cur_adp}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
