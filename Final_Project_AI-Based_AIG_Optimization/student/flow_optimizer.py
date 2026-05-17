#!/usr/bin/env python3
"""AI/LLM-guided ABC flow search for the ALS 2026 final project.

The optimizer tries a compact set of ABC command sequences suggested during
LLM-assisted exploration, validates every candidate with ABC equivalence
checking, measures area-delay product (ADP), and keeps only the best equivalent
AIG for each benchmark.
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")


@dataclass(frozen=True)
class Flow:
    name: str
    commands: str


@dataclass
class CandidateResult:
    flow: str
    status: str
    area: int | None = None
    delay: int | None = None
    adp: int | None = None
    aig: Path | None = None
    message: str = ""


# Compact candidate set chosen for a 30-minute-style run.  The baseline is kept
# first so every case has a simple, reliable fallback before stronger flows run.
FLOW_CANDIDATES = [
    Flow("baseline_st", "st"),
    Flow("rewrite_balance", "st; balance; rewrite; refactor; balance"),
    Flow("rewrite_zero", "st; rewrite -z; refactor -z; balance"),
    Flow("resyn", "st; resyn"),
    Flow("resyn2", "st; resyn2"),
    Flow("resyn2_cleanup", "st; resyn2; rewrite -z; refactor -z; balance"),
    Flow("dch_if_k6", "st; resyn2; dch; if -K 6; strash; resyn2"),
    Flow("dch_if_k8", "st; resyn2; dch; if -K 8; strash; resyn2"),
]


def abc_path(path: Path, root: Path) -> str:
    """Return a short path for ABC commands, avoiding absolute paths with spaces."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def run_abc(abc: Path, command: str, timeout: int, cwd: Path) -> str:
    try:
        result = subprocess.run(
            [str(abc), "-c", command],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except OSError as exc:
        raise RuntimeError(
            f"Cannot execute ABC at {abc}. If you are on Windows, run this "
            "project in Linux/WSL or use a Windows ABC executable."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"ABC exited with {result.returncode}")
    return result.stdout


def synthesize_candidate(
    abc: Path,
    truth: Path,
    aig: Path,
    flow: Flow,
    timeout: int,
    root: Path,
) -> None:
    aig.parent.mkdir(parents=True, exist_ok=True)
    truth_arg = abc_path(truth, root)
    aig_arg = abc_path(aig, root)
    command = f"read_truth -xf {truth_arg}; {flow.commands}; write_aiger -s {aig_arg}"
    run_abc(abc, command, timeout, root)


def is_equivalent(abc: Path, truth: Path, aig: Path, timeout: int, root: Path) -> tuple[bool, str]:
    truth_arg = abc_path(truth, root)
    aig_arg = abc_path(aig, root)
    command = f"read_truth -xf {truth_arg}; st; &get; &cec -t {aig_arg}"
    output = run_abc(abc, command, timeout, root)
    return "Networks are equivalent" in output, output.strip()


def measure_adp(abc: Path, aig: Path, timeout: int, root: Path) -> tuple[int, int, int]:
    aig_arg = abc_path(aig, root)
    output = run_abc(abc, f"read {aig_arg}; ps", timeout, root)
    match = PS_RE.search(output)
    if not match:
        raise RuntimeError(f"Cannot parse ABC statistics:\n{output.strip()}")
    area = int(match.group(1))
    delay = int(match.group(2))
    return area, delay, area * delay


def evaluate_candidate(
    abc: Path,
    truth: Path,
    aig: Path,
    flow: Flow,
    timeout: int,
    root: Path,
) -> CandidateResult:
    try:
        synthesize_candidate(abc, truth, aig, flow, timeout, root)
        equivalent, message = is_equivalent(abc, truth, aig, timeout, root)
        if not equivalent:
            tail = message.splitlines()[-1] if message else "not equivalent"
            return CandidateResult(flow.name, "NOT_EQUIV", aig=aig, message=tail)
        area, delay, adp = measure_adp(abc, aig, timeout, root)
        return CandidateResult(flow.name, "OK", area, delay, adp, aig)
    except subprocess.TimeoutExpired:
        return CandidateResult(flow.name, "TIMEOUT", aig=aig, message="ABC timeout")
    except RuntimeError as exc:
        return CandidateResult(flow.name, "ERROR", aig=aig, message=str(exc).splitlines()[-1])


def choose_best(results: list[CandidateResult]) -> CandidateResult | None:
    ok = [result for result in results if result.status == "OK" and result.adp is not None]
    if not ok:
        return None
    return min(ok, key=lambda result: (result.adp or sys.maxsize, result.area or sys.maxsize))


def optimize_case(
    abc: Path,
    truth: Path,
    output_dir: Path,
    temp_dir: Path,
    flows: list[Flow],
    timeout: int,
    root: Path,
) -> tuple[CandidateResult | None, list[CandidateResult]]:
    case_temp = temp_dir / truth.stem
    if case_temp.exists():
        shutil.rmtree(case_temp)
    case_temp.mkdir(parents=True, exist_ok=True)

    results: list[CandidateResult] = []
    for index, flow in enumerate(flows):
        candidate_aig = case_temp / f"{index:02d}_{flow.name}.aig"
        print(f"  trying {flow.name:<16}", end="", flush=True)
        result = evaluate_candidate(abc, truth, candidate_aig, flow, timeout, root)
        results.append(result)
        if result.status == "OK":
            print(f" area={result.area} delay={result.delay} adp={result.adp}")
        else:
            print(f" {result.status}")

    best = choose_best(results)
    if best and best.aig:
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best.aig, output_dir / f"{truth.stem}.aig")
    return best, results


def write_summary_csv(csv_path: Path, rows: list[dict[str, object]]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["case", "status", "best_flow", "area", "delay", "adp", "tried_flows"]
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def select_truth_files(benchmarks: Path, case: str | None) -> list[Path]:
    if case:
        return [benchmarks / f"{case}.truth"]
    return sorted(benchmarks.glob("ex*.truth"))


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Search ABC optimization flows and keep the best equivalent AIG."
    )
    parser.add_argument(
        "--abc",
        type=Path,
        default=Path(__file__).resolve().with_name("abc"),
        help="Path to the ABC executable.",
    )
    parser.add_argument(
        "--benchmarks",
        type=Path,
        default=repo_root / "benchmarks",
        help="Directory containing exNNN.truth files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=repo_root / "output",
        help="Directory where best exNNN.aig files will be written.",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=Path(__file__).resolve().with_name("results.csv"),
        help="CSV summary path for report/reproducibility.",
    )
    parser.add_argument("--case", help="Optional single case name, for example ex200.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="ABC timeout in seconds for each synthesis/check/measurement step.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Try only the first four quick flows for faster debugging.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary candidate AIGs under output/.optimizer_tmp.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    abc = args.abc.resolve()
    benchmarks = args.benchmarks.resolve()
    output_dir = args.output.resolve()
    temp_dir = output_dir / ".optimizer_tmp"
    flows = FLOW_CANDIDATES[:4] if args.fast else FLOW_CANDIDATES

    if not abc.is_file():
        print(f"ABC executable not found: {abc}", file=sys.stderr)
        return 2
    if not benchmarks.is_dir():
        print(f"Benchmark directory not found: {benchmarks}", file=sys.stderr)
        return 2

    truth_files = select_truth_files(benchmarks, args.case)
    if not truth_files:
        print("No benchmark truth files found.", file=sys.stderr)
        return 2

    rows: list[dict[str, object]] = []
    failures = 0
    for truth in truth_files:
        if not truth.is_file():
            print(f"Missing benchmark: {truth}", file=sys.stderr)
            return 2
        print(f"[CASE] {truth.stem}")
        best, results = optimize_case(abc, truth, output_dir, temp_dir, flows, args.timeout, root)
        if best:
            print(
                f"[BEST] {truth.stem}: {best.flow} "
                f"area={best.area} delay={best.delay} adp={best.adp}"
            )
            rows.append(
                {
                    "case": truth.stem,
                    "status": "OK",
                    "best_flow": best.flow,
                    "area": best.area,
                    "delay": best.delay,
                    "adp": best.adp,
                    "tried_flows": len(results),
                }
            )
        else:
            failures += 1
            print(f"[FAIL] {truth.stem}: no equivalent candidate")
            rows.append(
                {
                    "case": truth.stem,
                    "status": "FAIL",
                    "best_flow": "",
                    "area": "",
                    "delay": "",
                    "adp": "",
                    "tried_flows": len(results),
                }
            )

    write_summary_csv(args.results, rows)
    if not args.keep_temp and temp_dir.exists():
        shutil.rmtree(temp_dir)

    ok_rows = [row for row in rows if row["status"] == "OK"]
    total_adp = sum(int(row["adp"]) for row in ok_rows)
    print(f"Generated {len(ok_rows)}/{len(rows)} AIG file(s) in {output_dir}")
    print(f"Wrote summary CSV: {args.results}")
    if ok_rows:
        print(f"Total ADP over generated cases: {total_adp}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
