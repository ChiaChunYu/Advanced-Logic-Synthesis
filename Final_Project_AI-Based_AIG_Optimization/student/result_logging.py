#!/usr/bin/env python3
"""Unified CSV logging layer.

All optimization stages append their results through this module.  The shared
_append_csv() helper handles header-on-first-write and missing-field defaults
so callers only specify field names and row dicts.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Dataclasses shared across modules
# ---------------------------------------------------------------------------

@dataclass
class CandidateResult:
    case: str
    initial_method: str
    flow_name: str
    flow_commands: str
    area: int | None = None
    delay: int | None = None
    adp: int | None = None
    equivalent: bool = False
    selected: bool = False
    status: str = "ERROR"
    aig: Path | None = None


@dataclass(frozen=True)
class CaseSummary:
    case: str
    baseline_area: int
    baseline_delay: int
    baseline_adp: int
    best_area: int
    best_delay: int
    best_adp: int
    improvement_ratio: float
    selected_method: str


@dataclass(frozen=True)
class ParetoCandidate:
    case: str
    candidate_id: str
    source_method: str
    area: int
    delay: int
    adp: int
    is_pareto: bool
    is_min_area: bool
    is_min_delay: bool
    is_min_adp: bool
    selected_final: bool
    file_path: str


# ---------------------------------------------------------------------------
# Core helper
# ---------------------------------------------------------------------------

def _append_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


# ---------------------------------------------------------------------------
# Per-stage CSV appenders
# ---------------------------------------------------------------------------

def append_mockturtle_candidates_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "mode", "fingerprint_reason", "generated", "equivalent",
        "area", "delay", "adp", "improved", "error",
    ], rows)


def append_mockturtle_structural_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "base_area", "base_delay", "base_adp",
        "best_area", "best_delay", "best_adp",
        "improvement", "modes", "exact_types", "generated", "equivalent",
    ], rows)


_TYPE_GUIDED_CSV_FIELDS = [
    "case", "family", "labels", "reason",
    "flow_name", "flow_commands", "area", "delay", "adp",
    "equivalent", "improved", "selected", "status",
]


def append_type_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, _TYPE_GUIDED_CSV_FIELDS, rows)


_CIRCUIT_TYPE_CSV_FIELDS = [
    "case", "family", "labels", "reason",
    "candidate_kind", "seed_name", "flow_name", "flow_commands",
    "area", "delay", "adp", "equivalent", "improved", "selected", "status",
]


def append_circuit_type_optimize_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, _CIRCUIT_TYPE_CSV_FIELDS, rows)


_SEMANTIC_SPLIT_CSV_FIELDS = [
    "case", "split_name", "class_vars", "message",
    "flow_name", "flow_commands", "generated", "equivalent",
    "area", "delay", "adp", "improved", "selected", "status",
]


def append_semantic_split_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, _SEMANTIC_SPLIT_CSV_FIELDS, rows)


def append_objective_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "objective", "flow_name", "flow_commands",
        "area", "delay", "adp", "equivalent", "improved", "selected", "status",
    ], rows)


def append_micro_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "flow_name", "flow_commands",
        "area", "delay", "adp", "equivalent", "improved", "selected", "status",
    ], rows)


def append_small_case_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "labels", "recommended_strategy",
        "base_area", "base_delay", "base_adp",
        "flow_name", "flow_commands",
        "area", "delay", "adp", "equivalent", "improved", "selected", "status",
    ], rows)


def append_specialized_generators_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "function_type", "generator",
        "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_ttopt_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "input_support", "output_group", "rounds",
        "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_gia_canonical_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "pass_index", "flow_commands",
        "area", "delay", "adp", "equivalent", "improved", "selected", "status",
    ], rows)


def append_deepsyn_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    """Append with schema-migration for old files that lack the 'variant' column."""
    fieldnames = [
        "case", "variant", "seed", "iterations", "search_seconds",
        "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        with path.open("r", newline="", encoding="utf-8") as handle:
            existing_values = list(csv.reader(handle))
        if existing_values and existing_values[0] != fieldnames:
            migrated: list[dict[str, object]] = []
            for values in existing_values[1:]:
                if len(values) == len(fieldnames) - 1:
                    values = values[:1] + ["standard"] + values[1:]
                if len(values) == len(fieldnames):
                    migrated.append(dict(zip(fieldnames, values)))
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in migrated + rows:
                    writer.writerow({name: row.get(name, "") for name in fieldnames})
            return
    _append_csv(path, fieldnames, rows)


def append_pareto_area_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "seed", "search_seconds",
        "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_long_large_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "seed", "ttopt_rounds", "search_seconds", "initial_method",
        "generated", "equivalent",
        "baseline_area", "baseline_delay", "baseline_adp",
        "area", "delay", "adp", "improved", "selected", "error",
    ], rows)


def append_exact_npn_rescue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "support_size", "method", "template", "flow_name",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_transduction_rescue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "expansion_type", "g_source", "flow_name",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_complement_candidates_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "method", "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


def append_hybrid_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "case", "chain", "mode", "flow_name", "flow_commands",
        "generated", "equivalent", "area", "delay", "adp",
        "improved", "selected", "error",
    ], rows)


# ---------------------------------------------------------------------------
# Typed-row appenders
# ---------------------------------------------------------------------------

def append_results_csv(path: Path, rows: list[CandidateResult]) -> None:
    fieldnames = [
        "case", "initial_method", "flow_name", "flow_commands",
        "area", "delay", "adp", "equivalent", "selected", "status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({
                "case": row.case,
                "initial_method": row.initial_method,
                "flow_name": row.flow_name,
                "flow_commands": row.flow_commands,
                "area": row.area if row.area is not None else "",
                "delay": row.delay if row.delay is not None else "",
                "adp": row.adp if row.adp is not None else "",
                "equivalent": int(row.equivalent),
                "selected": int(row.selected),
                "status": row.status,
            })


def write_summary_csv(path: Path, rows: list[CaseSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "case", "baseline_area", "baseline_delay", "baseline_adp",
            "best_area", "best_delay", "best_adp",
            "improvement_ratio", "selected_method",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "case": row.case,
                "baseline_area": row.baseline_area,
                "baseline_delay": row.baseline_delay,
                "baseline_adp": row.baseline_adp,
                "best_area": row.best_area,
                "best_delay": row.best_delay,
                "best_adp": row.best_adp,
                "improvement_ratio": f"{row.improvement_ratio:.6f}",
                "selected_method": row.selected_method,
            })


def write_results_csv(path: Path, rows: list[CandidateResult]) -> None:
    """Overwrite *path* with a fresh CSV of all candidate results (not append)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case", "initial_method", "flow_name", "flow_commands",
        "area", "delay", "adp", "equivalent", "selected", "status",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "case": row.case,
                "initial_method": row.initial_method,
                "flow_name": row.flow_name,
                "flow_commands": row.flow_commands,
                "area": row.area if row.area is not None else "",
                "delay": row.delay if row.delay is not None else "",
                "adp": row.adp if row.adp is not None else "",
                "equivalent": int(row.equivalent),
                "selected": int(row.selected),
                "status": row.status,
            })


def write_pareto_candidates_csv(path: Path, pareto_rows: list[ParetoCandidate]) -> None:
    """Write a fresh Pareto-candidate CSV (not append)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case", "candidate_id", "source_method",
        "area", "delay", "adp",
        "is_pareto", "is_min_area", "is_min_delay", "is_min_adp",
        "selected_final", "file_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in pareto_rows:
            writer.writerow({
                "case": row.case,
                "candidate_id": row.candidate_id,
                "source_method": row.source_method,
                "area": row.area,
                "delay": row.delay,
                "adp": row.adp,
                "is_pareto": int(row.is_pareto),
                "is_min_area": int(row.is_min_area),
                "is_min_delay": int(row.is_min_delay),
                "is_min_adp": int(row.is_min_adp),
                "selected_final": int(row.selected_final),
                "file_path": row.file_path,
            })


# ---------------------------------------------------------------------------
# CSV reading / reporting helpers
# ---------------------------------------------------------------------------

def read_result_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def row_int(row: dict[str, str], key: str, default: int = 0) -> int:
    try:
        value = row.get(key, "")
        return int(float(value)) if value != "" else default
    except ValueError:
        return default



def format_case_analysis(case: str, table: object) -> str:
    influence_text = ", ".join(f"x{i}:{v:.4f}" for i, v in enumerate(table.influences))
    score_text = ", ".join(f"x{i}:{v:.4f}" for i, v in enumerate(table.shannon_scores))
    active_text = ", ".join(f"x{i}" for i in table.active_vars) or "(none)"
    return "\n".join([
        f"case: {case}", f"inputs: {table.num_inputs}", f"outputs: {table.num_outputs}",
        f"minterms/output: {table.num_minterms}", f"on_count: {table.on_count}",
        f"off_count: {table.off_count}", f"density: {table.density:.6f}",
        f"active_vars: {active_text}", f"influences: {influence_text}",
        f"balanced_shannon_scores: {score_text}",
    ])


def print_report_stats(results: list, summaries: list) -> None:
    from candidate_gen import pareto_frontier
    selected = [row for row in results if row.selected]
    frontier_size = sum(len(pareto_frontier([row for row in results if row.case == s.case])) for s in summaries)
    method_counts: dict[str, int] = {}
    for row in selected:
        key = f"{row.initial_method}/{row.flow_name}"
        method_counts[key] = method_counts.get(key, 0) + 1
    total_baseline = sum(row.baseline_adp for row in summaries)
    total_best = sum(row.best_adp for row in summaries)
    print("[report] cases:", len(summaries))
    print("[report] baseline_total_adp:", total_baseline)
    print("[report] best_total_adp:", total_best)
    if total_best:
        print("[report] total_improvement_ratio:", f"{total_baseline / total_best:.4f}")
    print("[report] pareto_frontier_candidates:", frontier_size)
    print("[report] selected_methods:")
    for method, count in sorted(method_counts.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {method}: {count}")

