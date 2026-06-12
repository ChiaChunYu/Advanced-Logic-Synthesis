#!/usr/bin/env python3
"""Shared ABC interaction layer.

All ABC subprocess calls, path quoting, ADP measurement, and equivalence
checking go through this module.  Every other script imports from here
instead of re-implementing the same helpers.
"""

from __future__ import annotations

import csv
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from boolean_fingerprint import TruthTable

PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def resolve_reference_csv(root: Path) -> Path:
    """Return the reference_result.csv path, falling back to student/logs/."""
    primary = root / "reference_result.csv"
    if primary.is_file():
        return primary
    return root / "student" / "logs" / "reference_result.csv"


def abc_quoted_path(path: Path, root: Path) -> str:
    """Return a quoted, root-relative (or absolute) POSIX path for ABC commands."""
    try:
        rel = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel = path.resolve().as_posix()
    return f'"{rel}"'


def abc_path(path: Path, root: Path) -> str:
    """Return an unquoted root-relative (or absolute) POSIX path for ABC commands."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


# ---------------------------------------------------------------------------
# Core ABC runner
# ---------------------------------------------------------------------------

def run_abc(abc: Path, command: str, timeout: int, cwd: Path | None = None) -> str:
    """Run ABC with *command* string.  Raises RuntimeError on failure."""
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
        raise RuntimeError(f"Cannot execute ABC at {abc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"ABC exited with {result.returncode}")
    return result.stdout


def run_abc_script(abc: Path, script: str, timeout: int) -> tuple[int | None, int | None]:
    """Write *script* to a temp file, run ABC with -f, return (area, delay) or (None, None)."""
    with tempfile.NamedTemporaryFile(suffix=".abc", mode="w", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [str(abc), "-f", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout + result.stderr
        m = PS_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2))
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    finally:
        try:
            Path(script_path).unlink()
        except OSError:
            pass
    return None, None


# ---------------------------------------------------------------------------
# High-level ABC operations
# ---------------------------------------------------------------------------

def measure_adp(abc: Path, aig: Path, timeout: int, root: Path) -> tuple[int, int, int]:
    """Return (area, delay, adp) for *aig*.  Raises RuntimeError if ABC fails."""
    output = run_abc(abc, f'read {abc_quoted_path(aig, root)}; ps', timeout, root)
    match = PS_RE.search(output)
    if not match:
        raise RuntimeError(f"Cannot parse ABC ps output:\n{output}")
    area = int(match.group(1))
    delay = int(match.group(2))
    return area, delay, area * delay


def is_equivalent(abc: Path, truth: Path, aig: Path, timeout: int, root: Path) -> bool:
    """Return True iff *aig* is equivalent to the truth table in *truth*."""
    cmd = (
        f"read_truth -xf {abc_quoted_path(truth, root)}; "
        f"st; &get; &cec -t {abc_quoted_path(aig, root)}"
    )
    output = run_abc(abc, cmd, timeout, root)
    return "Networks are equivalent" in output


# ---------------------------------------------------------------------------
# Simple measure helpers used by refine_close / deep_area_opt style scripts
# ---------------------------------------------------------------------------

def measure_aig(abc: Path, aig_path: str | Path) -> tuple[int | None, int | None]:
    """Quick area/delay measurement — returns (None, None) on any failure."""
    try:
        result = subprocess.run(
            [str(abc), "-c", f'read_aiger "{aig_path}"; ps'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        m = PS_RE.search(output)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None, None


def verify_equivalence(abc: Path, truth_path: str | Path, aig_path: str | Path) -> bool:
    """Check equivalence without path quoting (suitable for /tmp-style paths)."""
    try:
        result = subprocess.run(
            [str(abc), "-c",
             f'read_truth -xf "{truth_path}"; st; &get; &cec -t "{aig_path}"'],
            capture_output=True,
            text=True,
            timeout=90,
        )
        return "Networks are equivalent" in (result.stdout + result.stderr)
    except Exception:
        return False


def safe_copy(src: Path | str, dst: Path | str) -> None:
    """Copy *src* to *dst*, skipping silently if they are the same file."""
    try:
        shutil.copy(str(src), str(dst))
    except shutil.SameFileError:
        pass


def prepare_case_temp_dir(logs: Path, stage_dir: str, case: str, *, reset: bool = True) -> Path:
    """Create one stage-local case workspace, optionally clearing old candidates."""
    temp_dir = logs / stage_dir / case
    if reset and temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


# ---------------------------------------------------------------------------
# Baseline measurement and case diagnostics
# ---------------------------------------------------------------------------

def measure_baseline_truth_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    logs: Path,
    root: Path,
) -> tuple[int, int, int]:
    tmp = prepare_case_temp_dir(logs, "tmp_final_summary", case, reset=False)
    truth = benchmarks / f"{case}.truth"
    aig = tmp / f"{case}_abc_truth_baseline.aig"
    run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(aig, root)}", 120, root)
    return measure_adp(abc, aig, 120, root)


def _load_reference_adp(root: Path) -> dict[str, int]:
    """Load reference ADP values from reference_result.csv for ratio computation."""
    ref: dict[str, int] = {}
    csv_path = root / "reference_result.csv"
    if not csv_path.is_file():
        csv_path = root / "student" / "logs" / "reference_result.csv"
    if not csv_path.is_file():
        return ref
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                ref[row["case"]] = int(row["adp"])
            except (KeyError, ValueError):
                pass
    return ref


def diagnose_case(case: str, area: int, delay: int, adp: int, table: TruthTable, rows: list[dict[str, str]]) -> str:
    def _row_int(row: dict[str, str], key: str, default: int = 0) -> int:
        try:
            value = row.get(key, "")
            return int(float(value)) if value != "" else default
        except ValueError:
            return default

    if adp < 5000:
        return "already_good"
    selected = [row for row in rows if row.get("selected") in ("1", "True", "true")]
    selected_method = selected[0].get("initial_method", "") if selected else ""
    template_rows = [row for row in rows if "template_" in row.get("initial_method", "")]
    if template_rows and "template_" not in selected_method:
        template_best = min(_row_int(row, "adp", 10**30) for row in template_rows if row.get("adp", ""))
        best = min([_row_int(row, "adp", 10**30) for row in rows if row.get("adp", "")] or [adp])
        if template_best > best:
            return "template_mismatch"
    bdd_values = [_row_int(row, "adp", 10**30) for row in rows if "bdd" in row.get("initial_method", "") and row.get("adp", "")]
    if bdd_values and min(bdd_values) <= int(adp * 1.08) and "bdd" not in selected_method:
        return "bdd_ordering_sensitive"
    if area > 25000 and delay <= 22:
        return "area_bottleneck"
    if delay > 25 and area < 20000:
        return "delay_bottleneck"
    if table.density < 0.08 or table.density > 0.92:
        return "area_bottleneck"
    return "balanced_bottleneck"


# ---------------------------------------------------------------------------
# Mockturtle interaction helpers
# ---------------------------------------------------------------------------

def run_mockturtle_opt(mockturtle_bin: Path, source_aig: Path, out_aig: Path, mode: str, timeout: int, root: Path) -> None:
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(mockturtle_bin), str(source_aig), str(out_aig), mode],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=True,
    )


def ensure_structural_mockturtle(mockturtle_bin: Path, root: Path) -> tuple[bool, str]:
    binary = mockturtle_bin if mockturtle_bin.is_absolute() else root / mockturtle_bin
    if binary.is_file():
        return True, ""

    source_dir = root / "student" / "mockturtle_opt"
    build_dir = source_dir / "build"
    if not (source_dir / "CMakeLists.txt").is_file():
        return False, f"missing CMake project: {source_dir}"

    try:
        configure = subprocess.run(
            ["cmake", "-S", str(source_dir), "-B", str(build_dir)],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
        )
        if configure.returncode != 0:
            return False, (configure.stderr or configure.stdout).strip()
        build = subprocess.run(
            ["cmake", "--build", str(build_dir), "--target", "mockturtle_opt", "-j2"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
        )
        if build.returncode != 0:
            return False, (build.stderr or build.stdout).strip()
    except FileNotFoundError as exc:
        return False, f"cmake is unavailable: {exc}"
    except subprocess.TimeoutExpired:
        return False, "mockturtle_opt build timed out"

    if binary.is_file():
        return True, ""
    return False, f"build completed but binary was not found at {binary}"


def run_structural_mockturtle_opt(
    mockturtle_bin: Path,
    truth: Path,
    source_aig: Path,
    out_aig: Path,
    mode: str,
    timeout: int,
    root: Path,
) -> None:
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            str(mockturtle_bin),
            "--input-truth",
            str(truth),
            "--input-aig",
            str(source_aig),
            "--output-aig",
            str(out_aig),
            "--mode",
            mode,
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f"mockturtle_opt exited with {result.returncode}").strip()
        raise RuntimeError(message)
