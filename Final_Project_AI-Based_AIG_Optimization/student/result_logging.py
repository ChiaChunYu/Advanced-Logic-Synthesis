#!/usr/bin/env python3
"""Unified CSV logging layer.

All optimization stages append their results through this module.  The shared
_append_csv() helper handles header-on-first-write and missing-field defaults
so callers only specify field names and row dicts.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
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


def append_contest_schedule_csv(path: Path, rows: list[dict[str, object]]) -> None:
    _append_csv(path, [
        "stage", "case", "before_adp", "after_adp", "delta_adp",
        "status", "elapsed_sec", "detail",
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


def run_ablation_report(logs: Path) -> None:
    rows = read_result_rows(logs / "reproduce_candidates.csv")
    if not rows:
        rows = read_result_rows(logs / "results.csv")
    equivalent = [row for row in rows if row.get("equivalent") in ("1", "True", "true") and row.get("adp", "")]
    selected = [row for row in equivalent if row.get("selected") in ("1", "True", "true")]
    if not equivalent:
        raise RuntimeError("no equivalent rows found in student/logs/results.csv or reproduce_candidates.csv")

    wins_by_method = Counter(row.get("initial_method", "") for row in selected)
    wins_by_flow = Counter(row.get("flow_name", "") for row in selected)
    adp_by_method: dict[str, list[int]] = defaultdict(list)
    tried_methods: set[str] = set()
    for row in equivalent:
        method = row.get("initial_method", "")
        tried_methods.add(method)
        adp_by_method[method].append(row_int(row, "adp"))
    selected_methods = set(wins_by_method)
    never_selected = sorted(method for method in tried_methods if method not in selected_methods)

    by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in equivalent:
        by_case[row.get("case", "")].append(row)

    bdd_close: list[str] = []
    template_helped: list[str] = []
    template_failed: list[str] = []
    for case, case_rows in sorted(by_case.items()):
        best_adp = min(row_int(row, "adp", 10**30) for row in case_rows)
        bdd_best = min(
            [row_int(row, "adp", 10**30) for row in case_rows if "bdd" in row.get("initial_method", "")]
            or [10**30]
        )
        if bdd_best < 10**30 and bdd_best <= int(best_adp * 1.05) and bdd_best != best_adp:
            bdd_close.append(f"{case}: bdd_best={bdd_best}, best={best_adp}")
        template_rows = [row for row in case_rows if "template_" in row.get("initial_method", "")]
        if template_rows:
            template_best = min(row_int(row, "adp", 10**30) for row in template_rows)
            selected_row = min(case_rows, key=lambda row: row_int(row, "adp", 10**30))
            if "template_" in selected_row.get("initial_method", ""):
                template_helped.append(f"{case}: {selected_row.get('initial_method')} ADP={best_adp}")
            elif template_best > best_adp:
                template_failed.append(f"{case}: template_best={template_best}, best={best_adp}")

    summary_csv = logs / "ablation_summary.csv"
    summary_csv.parent.mkdir(parents=True, exist_ok=True)
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["section", "key", "value"])
        for key, count in wins_by_method.most_common():
            writer.writerow(["wins_by_initial_method", key, count])
        for key, count in wins_by_flow.most_common():
            writer.writerow(["wins_by_flow_name", key, count])
        for key, values in sorted(adp_by_method.items()):
            writer.writerow(["average_adp_by_method", key, f"{sum(values) / len(values):.2f}"])
        for key in never_selected:
            writer.writerow(["never_selected_method", key, "1"])

    report = logs / "ablation_report.txt"
    lines = ["Ablation Report", "", "Wins by initial_method:"]
    lines.extend(f"- {key}: {count}" for key, count in wins_by_method.most_common())
    lines.append("")
    lines.append("Wins by flow_name:")
    lines.extend(f"- {key}: {count}" for key, count in wins_by_flow.most_common())
    lines.append("")
    lines.append("Average ADP by method:")
    for key, values in sorted(adp_by_method.items()):
        lines.append(f"- {key}: {sum(values) / len(values):.2f}")
    lines.append("")
    lines.append("Methods tried but never selected:")
    lines.extend(f"- {key}" for key in never_selected[:80])
    lines.append("")
    lines.append("BDD/Shannon close to best but not selected:")
    lines.extend(f"- {item}" for item in bdd_close[:80])
    lines.append("")
    lines.append("Custom arithmetic templates helped:")
    lines.extend(f"- {item}" for item in template_helped[:80])
    lines.append("")
    lines.append("Custom templates tried but did not win:")
    lines.extend(f"- {item}" for item in template_failed[:80])
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ablation] wrote {report}")
    print(f"[ablation] wrote {summary_csv}")


def write_final_summary_csv(
    path: "Path",
    results: "list",
    logs: "Path",
    abc: "Path",
    benchmarks: "Path",
    root: "Path",
) -> None:
    import csv
    from abc_core import measure_baseline_truth_case
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_methods = selected_methods_from_logs(logs)
    exact_rows = read_result_rows(logs / "exact_function_matches.csv")
    method_counts = {
        "specialized": count_selected_improvement_cases(logs, "specialized_generators.csv"),
        "mockturtle": count_selected_improvement_cases(logs, "mockturtle_candidates.csv"),
        "exact_npn": count_selected_improvement_cases(logs, "exact_npn_rescue.csv"),
        "transduction": count_selected_improvement_cases(logs, "transduction_rescue.csv"),
        "complement": count_selected_improvement_cases(logs, "complement_candidates.csv"),
    }
    equivalent_count = sum(1 for row in results if row.equivalent)
    total_adp = sum(row.adp or 0 for row in results if row.equivalent)
    fieldnames = [
        "row_type", "case", "baseline_area", "baseline_delay", "baseline_adp",
        "best_area", "best_delay", "best_adp", "improvement_ratio",
        "selected_method", "equivalent", "total_adp", "equivalent_count",
        "exact_function_matches", "specialized_improved_cases",
        "mockturtle_improved_cases", "exact_npn_improved_cases",
        "transduction_improved_cases", "complement_improved_cases",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            assert row.area is not None and row.delay is not None and row.adp is not None
            baseline_area, baseline_delay, baseline_adp = measure_baseline_truth_case(row.case, abc, benchmarks, logs, root)
            writer.writerow({
                "row_type": "case", "case": row.case,
                "baseline_area": baseline_area, "baseline_delay": baseline_delay, "baseline_adp": baseline_adp,
                "best_area": row.area, "best_delay": row.delay, "best_adp": row.adp,
                "improvement_ratio": f"{baseline_adp / row.adp:.6f}" if row.adp else "",
                "selected_method": selected_methods.get(row.case, row.initial_method + "/" + row.flow_name),
                "equivalent": int(row.equivalent),
            })
        writer.writerow({
            "row_type": "aggregate", "case": "ALL",
            "equivalent": int(equivalent_count == len(results)),
            "total_adp": total_adp, "equivalent_count": equivalent_count,
            "exact_function_matches": len(exact_rows),
            "specialized_improved_cases": method_counts["specialized"],
            "mockturtle_improved_cases": method_counts["mockturtle"],
            "exact_npn_improved_cases": method_counts["exact_npn"],
            "transduction_improved_cases": method_counts["transduction"],
            "complement_improved_cases": method_counts["complement"],
        })


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


# ---------------------------------------------------------------------------
# Diagnosis and coverage reporting
# ---------------------------------------------------------------------------

def run_diagnose_results(abc: Path, benchmarks: Path, output: Path, logs: Path, root: Path) -> None:
    from flow_optimizer import ALL_CASES
    from abc_core import measure_adp, diagnose_case
    from blif_builder import read_truth
    candidate_rows = read_result_rows(logs / "reproduce_candidates.csv") or read_result_rows(logs / "results.csv")
    rows_by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidate_rows:
        rows_by_case[row.get("case", "")].append(row)
    out_path = logs / "bottleneck_diagnosis.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case", "area", "delay", "adp", "density", "diagnosis", "notes"],
        )
        writer.writeheader()
        for case in ALL_CASES:
            aig = output / f"{case}.aig"
            table = read_truth(benchmarks / f"{case}.truth")
            area, delay, adp = measure_adp(abc, aig, 120, root)
            diagnosis = diagnose_case(case, area, delay, adp, table, rows_by_case.get(case, []))
            writer.writerow(
                {
                    "case": case,
                    "area": area,
                    "delay": delay,
                    "adp": adp,
                    "density": f"{table.density:.6f}",
                    "diagnosis": diagnosis,
                    "notes": f"inputs={table.num_inputs};outputs={table.num_outputs}",
                }
            )
    print(f"[diagnose] wrote {out_path}")


def rank_current_outputs(abc: Path, output: Path, root: Path) -> list[tuple[str, int, int, int]]:
    from flow_optimizer import ALL_CASES
    from abc_core import measure_adp
    ranked: list[tuple[str, int, int, int]] = []
    for case in ALL_CASES:
        aig = output / f"{case}.aig"
        if not aig.is_file():
            continue
        area, delay, adp = measure_adp(abc, aig, 120, root)
        ranked.append((case, area, delay, adp))
    return sorted(ranked, key=lambda item: item[3], reverse=True)


def build_case_coverage(
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    root: Path,
) -> list[dict[str, str]]:
    from flow_optimizer import ALL_CASES
    from abc_core import measure_adp
    from flow_library import flow_family
    rows = load_candidate_history(logs)
    by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        case = row.get("case", "")
        if case:
            by_case[case].append(row)
    exact_cases = {row.get("case", "") for row in read_result_rows(logs / "exact_function_matches.csv") if row.get("case", "")}
    specialized_cases = {row.get("case", "") for row in read_result_rows(logs / "specialized_generators.csv") if row.get("case", "")}
    mockturtle_cases = {row.get("case", "") for row in read_result_rows(logs / "mockturtle_candidates.csv") if row.get("case", "")}
    exact_npn_cases = {row.get("case", "") for row in read_result_rows(logs / "exact_npn_rescue.csv") if row.get("case", "")}
    complement_cases = {row.get("case", "") for row in read_result_rows(logs / "complement_candidates.csv") if row.get("case", "")}
    transduction_cases = {row.get("case", "") for row in read_result_rows(logs / "transduction_rescue.csv") if row.get("case", "")}
    coverage_rows: list[dict[str, str]] = []
    for case in ALL_CASES:
        case_rows = by_case.get(case, [])
        equivalent_rows = [row for row in case_rows if row.get("equivalent") in ("1", "True", "true")]
        selected_rows = [row for row in case_rows if row.get("selected") in ("1", "True", "true")]
        methods = {row.get("initial_method", "") for row in case_rows if row.get("initial_method", "")}
        families = {
            flow_family(row.get("flow_name", ""), row.get("flow_commands", ""))
            for row in case_rows
            if row.get("flow_name", "") or row.get("flow_commands", "")
        }
        baseline_candidates = [
            row_int(row, "adp", 0)
            for row in equivalent_rows
            if row.get("initial_method") == "abc_truth" and row.get("flow_name") == "identity" and row.get("adp", "")
        ]
        current_aig = output / f"{case}.aig"
        current_area = current_delay = current_adp = 0
        if current_aig.is_file():
            current_area, current_delay, current_adp = measure_adp(abc, current_aig, 120, root)
        baseline_adp = min(baseline_candidates) if baseline_candidates else current_adp
        improvement_ratio = (baseline_adp / current_adp) if current_adp else 0.0
        bdd_tried = any("bdd" in method or "shannon" in method for method in methods)
        sop_pos_tried = any("sop" in method or "pos" in method for method in methods)
        complement_tried = any("complement" in method for method in methods) or case in complement_cases
        exact_match_tried = case in exact_cases
        specialized_tried = case in specialized_cases
        mockturtle_tried = case in mockturtle_cases
        exact_npn_tried = case in exact_npn_cases
        transduction_tried = case in transduction_cases
        area_tried = "area" in families
        delay_tried = "delay" in families
        balanced_tried = "balanced" in families
        under_reasons: list[str] = []
        if len(case_rows) < 50:
            under_reasons.append("candidates_tried<50")
        if len(equivalent_rows) < 10:
            under_reasons.append("equivalent_candidates<10")
        if len(methods) < 4:
            under_reasons.append("initial_methods_tried<4")
        if len(families) < 5:
            under_reasons.append("flow_families_tried<5")
        if not complement_tried:
            under_reasons.append("complement_not_tried")
        if not bdd_tried:
            under_reasons.append("bdd_not_tried")
        if not exact_match_tried:
            under_reasons.append("exact_match_not_tried")
        if improvement_ratio < 1.02:
            under_reasons.append("improvement_ratio<1.02")
        coverage_rows.append(
            {
                "case": case,
                "candidates_tried": str(len(case_rows)),
                "equivalent_candidates": str(len(equivalent_rows)),
                "selected_updates": str(len(selected_rows)),
                "initial_methods_tried": str(len(methods)),
                "flow_families_tried": str(len(families)),
                "methods": "|".join(sorted(methods)),
                "flow_families": "|".join(sorted(families)),
                "bdd_shannon_tried": str(int(bdd_tried)),
                "sop_pos_tried": str(int(sop_pos_tried)),
                "complement_tried": str(int(complement_tried)),
                "area_flow_tried": str(int(area_tried)),
                "delay_flow_tried": str(int(delay_tried)),
                "balanced_flow_tried": str(int(balanced_tried)),
                "exact_match_tried": str(int(exact_match_tried)),
                "specialized_tried": str(int(specialized_tried)),
                "mockturtle_tried": str(int(mockturtle_tried)),
                "exact_npn_tried": str(int(exact_npn_tried)),
                "transduction_tried": str(int(transduction_tried)),
                "baseline_adp": str(baseline_adp),
                "current_area": str(current_area),
                "current_delay": str(current_delay),
                "current_best_adp": str(current_adp),
                "improvement_ratio": f"{improvement_ratio:.6f}",
                "under_covered": str(int(bool(under_reasons))),
                "under_covered_reasons": "|".join(under_reasons),
            }
        )
    return coverage_rows


def write_case_coverage_report(rows: list[dict[str, str]], logs: Path) -> None:
    csv_path = logs / "case_coverage.csv"
    report_path = logs / "case_coverage_report.txt"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    under = [row for row in rows if row["under_covered"] == "1"]
    lines = [
        "Case Coverage Report",
        "",
        f"cases: {len(rows)}",
        f"under_covered_cases: {len(under)}",
        "",
        "Under-covered cases:",
    ]
    for row in under:
        lines.append(
            f"- {row['case']}: candidates={row['candidates_tried']}, "
            f"equiv={row['equivalent_candidates']}, methods={row['initial_methods_tried']}, "
            f"families={row['flow_families_tried']}, ratio={row['improvement_ratio']}, "
            f"reasons={row['under_covered_reasons']}"
        )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[coverage] wrote {csv_path}")
    print(f"[coverage] wrote {report_path}")


def run_case_coverage_report(args: "object", root: Path) -> list[dict[str, str]]:
    rows = build_case_coverage(args.abc, args.benchmarks, args.output, args.logs, root)
    write_case_coverage_report(rows, args.logs)
    return rows
