#!/usr/bin/env python3
"""Evaluate AIG outputs, working on both Linux/WSL and Windows.

On Linux/WSL: runs evaluate.py directly (abc is a Linux ELF).
On Windows:   delegates to WSL so the Linux abc binary can execute.

Usage:
    python3 student/evaluate.py              # all 100 cases
    python3 student/evaluate.py --case ex240 # single case
    python3 student/evaluate.py --timeout 90 # custom ABC timeout per step
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _win_to_wsl(path: Path) -> str:
    """Convert a Windows absolute path to its /mnt/... WSL equivalent."""
    p = path.resolve()
    drive = p.drive.rstrip(":").lower()
    rest = p.as_posix().split(":", 1)[1]
    return f"/mnt/{drive}{rest}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check equivalence and report ADP for output/exNNN.aig files."
    )
    parser.add_argument("--abc",        type=Path, default=ROOT / "student" / "abc")
    parser.add_argument("--benchmarks", type=Path, default=ROOT / "benchmarks")
    parser.add_argument("--output",     type=Path, default=ROOT / "output")
    parser.add_argument("--case",       help="single case name, e.g. ex200")
    parser.add_argument("--timeout",    type=int,  default=60,
                        help="ABC timeout per step in seconds")
    return parser.parse_args()


def _run_abc(abc: Path, command: str, timeout: int) -> "tuple[int, str]":
    import subprocess
    result = subprocess.run(
        [str(abc), "-c", command],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=timeout,
    )
    return result.returncode, result.stdout


def _is_equivalent(abc: Path, truth: Path, aig: Path, timeout: int) -> "tuple[bool, str]":
    # Paths quoted to handle spaces (e.g. 'Github project' in the repo path).
    cmd = f"read_truth -xf '{truth}'; st; &get; &cec -t '{aig}'"
    code, out = _run_abc(abc, cmd, timeout)
    if code != 0:
        return False, out.strip()
    return "Networks are equivalent" in out, out.strip()


def _measure_adp(abc: Path, aig: Path, timeout: int) -> "tuple[int, int, int]":
    import re
    code, out = _run_abc(abc, f"read '{aig}'; ps", timeout)
    if code != 0:
        raise RuntimeError(out.strip())
    m = re.search(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)", out)
    if not m:
        raise RuntimeError(f"Cannot parse ABC statistics:\n{out}")
    area, delay = int(m.group(1)), int(m.group(2))
    return area, delay, area * delay


def _evaluate_case(abc: Path, truth: Path, output_dir: Path, timeout: int) -> "object":
    import subprocess
    sys.path.insert(0, str(ROOT))
    from evaluate import CaseResult
    case = truth.stem
    aig = output_dir / f"{case}.aig"
    if not aig.is_file():
        return CaseResult(case=case, status="MISSING", message=f"{aig.name} not found")
    try:
        equiv, msg = _is_equivalent(abc, truth, aig, timeout)
    except subprocess.TimeoutExpired:
        return CaseResult(case=case, status="TIMEOUT", message="equivalence check timeout")
    if not equiv:
        return CaseResult(case=case, status="NOT_EQUIV", message=msg.splitlines()[-1] if msg else "")
    try:
        area, delay, adp = _measure_adp(abc, aig, timeout)
    except subprocess.TimeoutExpired:
        return CaseResult(case=case, status="TIMEOUT", message="ADP measurement timeout")
    except RuntimeError as exc:
        return CaseResult(case=case, status="ERROR", message=str(exc))
    return CaseResult(case=case, status="OK", area=area, delay=delay, adp=adp)


def _run_native(args: argparse.Namespace) -> int:
    """Run directly (Linux/WSL environment) with quoted paths for spaces."""
    sys.path.insert(0, str(ROOT))
    import evaluate as _ev

    if not args.abc.is_file():
        print(f"ABC executable not found: {args.abc}", file=sys.stderr)
        return 2
    if not args.benchmarks.is_dir():
        print(f"Benchmark directory not found: {args.benchmarks}", file=sys.stderr)
        return 2

    bad_names = _ev.check_output_filenames(args.output)
    if bad_names:
        print("Invalid output filename(s):")
        for name in bad_names:
            print(f"  {name}")
        print("Expected format: exNNN.aig")
        return 2

    truth_files = (
        [args.benchmarks / f"{args.case}.truth"]
        if args.case
        else sorted(args.benchmarks.glob("ex*.truth"))
    )

    print(f"{'case':<8} {'status':<10} {'area':>10} {'delay':>8} {'adp':>14}")
    print("-" * 54)
    results = []
    for truth in truth_files:
        result = _evaluate_case(args.abc, truth, args.output, args.timeout)
        results.append(result)
        area  = "-" if result.area  is None else str(result.area)
        delay = "-" if result.delay is None else str(result.delay)
        adp   = "-" if result.adp   is None else str(result.adp)
        print(f"{result.case:<8} {result.status:<10} {area:>10} {delay:>8} {adp:>14}")
        if result.message and result.status != "OK":
            print(f"  {result.message}")

    ok = [r for r in results if r.status == "OK"]
    print("-" * 54)
    print(f"Equivalent cases: {len(ok)}/{len(results)}")
    if ok:
        print(f"Total ADP over equivalent cases: {sum(r.adp or 0 for r in ok)}")
    return 0 if len(ok) == len(results) else 1


def _run_via_wsl(args: argparse.Namespace) -> int:
    """Delegate to WSL when running on Windows (abc is a Linux ELF)."""
    root_wsl = _win_to_wsl(ROOT)
    extra = []
    if args.case:
        extra += ["--case", args.case]
    if args.timeout != 60:
        extra += ["--timeout", str(args.timeout)]

    cmd = [
        "wsl", "-d", "Ubuntu-24.04", "--",
        "bash", "-c",
        f"cd '{root_wsl}' && python3 student/evaluate.py " + " ".join(extra),
    ]
    try:
        return subprocess.run(cmd).returncode
    except FileNotFoundError:
        print("ERROR: 'wsl' not found. Install WSL with Ubuntu-24.04.", file=sys.stderr)
        return 2


def main() -> int:
    args = parse_args()
    if sys.platform == "win32":
        return _run_via_wsl(args)
    return _run_native(args)


if __name__ == "__main__":
    raise SystemExit(main())
