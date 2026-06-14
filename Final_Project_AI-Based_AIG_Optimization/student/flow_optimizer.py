#!/usr/bin/env python3
"""Hybrid AIG optimizer for the ALS 2026 final project.

This optimizer tries multiple initial synthesis strategies before ABC
post-optimization: ABC truth synthesis, multi-output SOP/POS BLIF construction,
multi-output Shannon/BDD construction, and a simple recursive SOP factoring
front end.  Every candidate is checked by ABC before it can be selected.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure student/ directory is on the import path
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent))

from circuit_analysis import (
    append_classification_csv,
    fingerprint_case,
    format_fingerprint,
    ExactFunctionMatch,
    exact_matches_for_truth,
    format_exact_matches,
    match_binary_template,
    run_validate_templates,
    truth_input_value,
    truth_output_value,
    validate_template_case,
    write_exact_function_matches_csv,
)

# ---------------------------------------------------------------------------
# Import shared modules (extracted from this file)
# ---------------------------------------------------------------------------
from abc_core import (
    PS_RE,
    _load_reference_adp,
    abc_path,
    abc_quoted_path,
    diagnose_case,
    ensure_structural_mockturtle,
    measure_adp,
    measure_aig,
    measure_baseline_truth_case,
    is_equivalent,
    prepare_case_temp_dir,
    run_abc,
    run_abc_script,
    run_mockturtle_opt,
    run_structural_mockturtle_opt,
    verify_equivalence,
)
from blif_builder import (
    BlifBuilder,
    TruthTable,
    binary_entropy,
    blif_header,
    read_truth,
    write_complement_truth,
    read_blif_interface,
    transduction_variable_order,
    wrap_inverted_blif_outputs,
    wrap_transduction_blif_outputs,
    class_cofactor_bits,
    cofactor_compact,
    cofactor_support,
    collect_all_output_covers,
    collect_cubes,
    collect_support_cubes,
    compact_index_to_original,
    compress_bits,
    detect_signed_multiplier,
    detect_unsigned_divider_quotient,
    detect_unsigned_multiplier,
    detect_unsigned_sqrt,
    detect_unsigned_square,
    emit_and_tree,
    emit_bdd_signal,
    emit_class_decoder,
    emit_column_outputs,
    emit_conditional_subtract_shifted,
    emit_or_tree,
    emit_shared_bdd_signal,
    emit_unsigned_greater_equal,
    emit_unsigned_subtract,
    emit_vector_add,
    emit_xor_tree,
    minterm_cube,
    minterm_cube_for_support,
    output_support,
    reduce_weighted_columns,
    selector_reduction_order,
    semantic_split_specs,
    shared_bdd_order_specs,
    truth_bit,
    tuple_support,
    write_bdd_blif,
    write_class_split_blif,
    write_cover_blif,
    write_factored_sop_blif,
    write_per_output_semantic_split_blif,
    write_shared_multioutput_bdd_blif,
    write_small_support_exact_blif,
    write_signed_multiplier_blif,
    write_signed_multiplier_csa_blif,
    write_unsigned_divider_quotient_blif,
    write_unsigned_multiplier_blif,
    write_unsigned_sqrt_blif,
    write_unsigned_square_blif,
)
from candidate_gen import (
    InitialCandidate,
    _write_pareto_candidates_from_results,
    affine_signal_from_match,
    build_pareto_candidates,
    candidate_source_method,
    choose_candidate_pairs,
    choose_exact_match,
    complement_method_name,
    emit_comparator_outputs,
    emit_constant_bits,
    emit_popcount_bits,
    emit_unsigned_add_bits,
    emit_unsigned_equal,
    emit_unsigned_equal_constant,
    emit_unsigned_ge_constant,
    exact_constant_signal,
    exact_matches_by_output,
    bdd_sift_case,
    make_circuit_type_seed_candidates,
    make_complement_initial_candidates,
    make_exact_specialized_candidates,
    make_history_guided_ga_flows,
    make_initial_candidates,
    pareto_frontier,
    parse_binary_orders,
    parse_var_order,
    polish_aig,
    synthesize,
    write_exact_adder_blif,
    write_exact_affine_blif,
    write_exact_comparator_blif,
    write_exact_popcount_blif,
    write_exact_threshold_blif,
)
from flow_library import (
    AREA_FIRST_FLOWS,
    AREA_FIRST_RESYNTH_FLOWS,
    CIRCUIT_TYPE_POLISH_LIBRARY,
    CIRCUIT_TYPE_SEED_FLOWS,
    DEEPSYN_STRUCTURAL_POLISH_FLOWS,
    EXACT_NPN_RESCUE_FLOWS,
    GA_COMMAND_POOL,
    GIA_CANONICAL_FLOW,
    HYBRID_YOSYS_POLISH_FLOWS,
    MICRO_COLLAPSE_FLOWS,
    MICRO_GUIDED_FLOWS,
    MOCKTURTLE_MODES,
    MOCKTURTLE_POST_FLOW,
    MOCKTURTLE_STRUCTURAL_POLISH_FLOWS,
    OBJECTIVE_GUIDED_FLOW_LIBRARY,
    PARETO_AREA_STRUCTURAL_POLISH_FLOWS,
    POLISH_FLOWS,
    POST_FLOWS,
    PostFlow,
    SEMANTIC_SPLIT_FLOWS,
    SMALL_CASE_FLOWS,
    SPECIALIZED_GENERATOR_FLOWS,
    STRUCTURAL_MOCKTURTLE_MODES,
    SWEEP_FLOWS,
    TOP_FLOW_NAMES,
    TRANSDUCTION_REDUCTION_FLOWS,
    TTOPT_STRUCTURAL_POLISH_FLOWS,
    TYPE_GUIDED_FLOW_LIBRARY,
    TYPE_GUIDED_SHARED_FLOWS,
    _dedup_flows,
    crossover_flow,
    flow_family,
    join_commands,
    make_ga_flows,
    make_history_guided_ga_flows as _make_history_guided_ga_flows,
    mutate_flow,
    select_circuit_type_flows,
    select_objective_guided_flows,
    select_small_case_flows,
    select_type_guided_flows,
    split_commands,
    type_guided_family,
)
# NOTE: select_micro_guided_flows is defined locally with extended signature
# (area, adp, max_flows) that adds MICRO_COLLAPSE_FLOWS for small cases.
# It overrides the simpler version in flow_library that only takes max_flows.
from result_logging import (
    CandidateResult,
    CaseSummary,
    ParetoCandidate,
    _append_csv,
    append_circuit_type_optimize_csv,
    format_case_analysis,
    print_report_stats,
    append_complement_candidates_csv,
    append_deepsyn_structural_csv,
    append_exact_npn_rescue_csv,
    append_gia_canonical_csv,
    append_hybrid_structural_csv,
    append_long_large_structural_csv,
    append_micro_guided_csv,
    append_mockturtle_candidates_csv,
    append_mockturtle_structural_summary_csv,
    append_objective_guided_csv,
    append_pareto_area_structural_csv,
    append_results_csv,
    append_semantic_split_csv,
    append_small_case_csv,
    append_specialized_generators_csv,
    append_transduction_rescue_csv,
    append_ttopt_structural_csv,
    append_type_guided_csv,
    read_result_rows,
    row_int,
    write_pareto_candidates_csv,
    write_results_csv,
    write_summary_csv,
)
from case_runners import (
    exact_type_hints_for_mockturtle,
    select_structural_mockturtle_modes,
    run_circuit_type_optimize_case,
    run_semantic_split_optimize_case,
    select_micro_guided_flows,
    npn_template_summary_for_case,
    run_exact_npn_rescue_case,
    run_transduction_rescue_case,
    run_complement_rescue_case,
    run_specialized_generators_case,
    ttopt_output_groups,
    run_ttopt_structural_case,
    should_run_deepsyn_structural,
    run_deepsyn_structural_case,
    should_run_pareto_area_structural,
    is_low_degree_vector_signature,
    should_run_compact_pareto_structural,
    should_probe_compact_vector_structural,
    should_run_long_large_structural,
    run_pareto_area_structural_case,
    run_long_large_structural_case,
    run_adaptive_compact_vector_pareto,
    resolve_yosys_binary,
    run_yosys_structural_opt,
    run_hybrid_structural_case,
    run_mockturtle_structural_case,
    run_type_guided_refine_case,
    run_objective_guided_refine_case,
    run_micro_guided_refine_case,
    run_gia_canonical_convergence_case,
    run_area_first_refine_case,
    run_convergence_loop_case,
    run_small_case_refine_case,
)

ALL_CASES = [f"ex{i}" for i in range(200, 300)]

# When set via --cases, ALL_CASES iterators in the pipeline use this filter.
_ACTIVE_CASE_FILTER: set[str] | None = None


def _filter_cases(cases: list[str]) -> list[str]:
    if _ACTIVE_CASE_FILTER is None:
        return cases
    return [c for c in cases if c in _ACTIVE_CASE_FILTER]


# ---------------------------------------------------------------------------
# Pipeline configuration — grouped by concern so all tunables are in one place
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InitialSynthesisConfig:
    """Stage 1-3: first-pass synthesis and rescue."""
    seed: int = 42
    main_max_candidates: int = 48
    focused_max_candidates: int = 80
    rescue_max_candidates: int = 120
    rescue_seed: int = 99
    arithmetic_ranges: tuple = (("ex255", "ex259"), ("ex260", "ex264"), ("ex270", "ex274"))
    divider_range: tuple = ("ex265", "ex269")
    sqrt_range: tuple = ("ex275", "ex279")
    rescue_cases: tuple = ("ex252",)


@dataclass(frozen=True)
class RefinementConfig:
    """Stages 4-7: polish/sweep, mockturtle, type-guided, micro, small-case."""
    polish_passes: int = 30
    sweep_passes: int = 3
    final_sweep_passes: int = 3
    front_range: tuple = ("ex200", "ex207")
    mockturtle_structural_timeout: int = 45
    final_advanced_mockturtle_timeout: int = 90
    type_guided_timeout: int = 180
    type_guided_max_flows: int = 8
    objective_guided_timeout: int = 180
    objective_max_per_family: int = 3
    micro_guided_timeout: int = 90
    micro_max_flows: int = 4
    small_case_timeout: int = 35
    small_case_max_flows: int = 5
    small_case_area_threshold: int = 2500
    small_case_adp_threshold: int = 50000


@dataclass(frozen=True)
class StructuralResynthesisConfig:
    """Stages 8-12: ttopt, deepsyn, Pareto, compact-vector, long-large, Yosys."""
    seed: int = 42
    ttopt_structural_timeout: int = 150
    deepsyn_structural_timeout: int = 75
    deepsyn_structural_seconds: int = 30
    deepsyn_structural_passes: int = 2
    deepsyn_min_adp: int = 50000
    deepsyn_min_area: int = 2500
    pareto_area_structural_timeout: int = 140
    pareto_area_seconds: int = 80
    pareto_area_min_area: int = 25000
    compact_pareto_structural_timeout: int = 120
    compact_pareto_seconds: int = 55
    compact_pareto_passes: int = 10
    compact_pareto_min_area: int = 400
    compact_pareto_max_area: int = 25000
    compact_pareto_max_anf_degree: int = 4
    vector_probe_structural_timeout: int = 55
    vector_probe_seconds: int = 15
    vector_refine_structural_timeout: int = 110
    vector_refine_seconds: int = 45
    vector_refine_passes: int = 3
    vector_min_adp: int = 8000
    long_large_probe_seconds: int = 120
    long_large_refine_seconds: int = 360
    long_large_timeout_margin: int = 120
    long_large_min_area: int = 25000
    long_large_min_adp: int = 500000
    long_large_ttopt_rounds: int = 60
    hybrid_structural_timeout: int = 90
    hybrid_workers: int = 2


@dataclass(frozen=True)
class ConvergenceConfig:
    """Stages 13-16: area-first, my_deepsyn sweep, case-fair, micro+GIA convergence."""
    area_first_timeout: int = 90
    area_first_passes: int = 3
    # my_deepsyn two-pass sweep
    my_deepsyn_pass1_seconds: int = 60
    my_deepsyn_pass1_timeout: int = 90
    my_deepsyn_pass1_min_area: int = 500
    my_deepsyn_pass2_seconds: int = 180
    my_deepsyn_pass2_timeout: int = 210
    my_deepsyn_pass2_min_area: int = 2000
    # budget multipliers by ADP ratio tier for my_deepsyn pass 1
    ratio_tier_high_threshold: float = 1.5   # ratio >= this → long budget
    ratio_tier_mid_threshold: float = 1.1    # ratio >= this → medium budget
    ratio_tier_high_extra: int = 60          # extra seconds added for high-ratio cases
    ratio_tier_mid_extra: int = 20           # extra seconds added for mid-ratio cases
    case_fair_timeout: int = 60
    case_fair_stage_timeout: int = 10
    micro_convergence_passes: int = 6
    micro_convergence_timeout: int = 20
    gia_canonical_max_passes: int = 16
    gia_canonical_timeout: int = 30


@dataclass(frozen=True)
class RatioPushConfig:
    """Stage 17: targeted push for cases that remain above 1.5x reference ADP.

    baseline_cases is the original hand-curated list from experiments — these
    always run regardless of their measured ratio.  Any additional case whose
    current ratio >= ratio_threshold at the start of stage 17 is appended on
    top, so the set can only grow, never shrink compared to the baseline.
    """
    baseline_cases: tuple = (
        "ex204", "ex205", "ex217", "ex219", "ex240", "ex241", "ex244", "ex245",
        "ex246", "ex247", "ex248", "ex252", "ex253", "ex260", "ex270", "ex279",
        "ex287", "ex289",
    )
    ratio_threshold: float = 1.5
    # Cases that also get a long Pareto search on top of the standard package.
    pareto_cases: tuple = ("ex205", "ex246", "ex279")
    timeout: int = 180
    micro_timeout: int = 180
    gia_timeout: int = 120
    pareto_timeout: int = 520
    pareto_seconds: int = 420
    type_flows: int = 12
    objective_flows: int = 4
    micro_flows: int = 12


# Module-level singletons — used by should_run_* predicates and REPRODUCE_RECIPE.
_INITIAL_CFG = InitialSynthesisConfig()
_REFINE_CFG = RefinementConfig()
_STRUCT_CFG = StructuralResynthesisConfig()
_CONV_CFG = ConvergenceConfig()
_PUSH_CFG = RatioPushConfig()

# Flat aliases kept for backward compat with should_run_* predicate defaults.
REPRODUCE_SEED = _INITIAL_CFG.seed
REPRODUCE_DEEPSYN_MIN_ADP = _STRUCT_CFG.deepsyn_min_adp
REPRODUCE_DEEPSYN_MIN_AREA = _STRUCT_CFG.deepsyn_min_area
REPRODUCE_PARETO_AREA_MIN_AREA = _STRUCT_CFG.pareto_area_min_area
REPRODUCE_COMPACT_PARETO_MIN_AREA = _STRUCT_CFG.compact_pareto_min_area
REPRODUCE_COMPACT_PARETO_MAX_AREA = _STRUCT_CFG.compact_pareto_max_area
REPRODUCE_COMPACT_PARETO_MAX_ANF_DEGREE = _STRUCT_CFG.compact_pareto_max_anf_degree
REPRODUCE_VECTOR_MIN_ADP = _STRUCT_CFG.vector_min_adp
REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_AREA = _STRUCT_CFG.long_large_min_area
REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_ADP = _STRUCT_CFG.long_large_min_adp
REPRODUCE_SMALL_CASE_AREA_THRESHOLD = _REFINE_CFG.small_case_area_threshold
REPRODUCE_SMALL_CASE_ADP_THRESHOLD = _REFINE_CFG.small_case_adp_threshold
REPRODUCE_GIA_CANONICAL_MAX_PASSES = _CONV_CFG.gia_canonical_max_passes
REPRODUCE_MY_DEEPSYN_PASS1_MIN_AREA = _CONV_CFG.my_deepsyn_pass1_min_area
REPRODUCE_MY_DEEPSYN_PASS2_MIN_AREA = _CONV_CFG.my_deepsyn_pass2_min_area
REPRODUCE_MAIN_MAX_CANDIDATES = _INITIAL_CFG.main_max_candidates
REPRODUCE_CASE_FAIR_STAGE_TIMEOUT = _CONV_CFG.case_fair_stage_timeout
REPRODUCE_VECTOR_PROBE_STRUCTURAL_TIMEOUT = _STRUCT_CFG.vector_probe_structural_timeout
REPRODUCE_VECTOR_PROBE_SECONDS = _STRUCT_CFG.vector_probe_seconds
REPRODUCE_VECTOR_REFINE_PASSES = _STRUCT_CFG.vector_refine_passes
REPRODUCE_VECTOR_REFINE_STRUCTURAL_TIMEOUT = _STRUCT_CFG.vector_refine_structural_timeout
REPRODUCE_VECTOR_REFINE_SECONDS = _STRUCT_CFG.vector_refine_seconds
REPRODUCE_RECIPE = [
    (
        "1",
        "all_case_hybrid_synthesis",
        "Parallel initial synthesis for all 100 cases: multiple front-ends "
        "(abc_truth / BDD / Shannon / SOP / exact structural) x ABC post-flow "
        "portfolio; keep lowest-ADP equivalent candidate.",
        f"max_candidates={REPRODUCE_MAIN_MAX_CANDIDATES}, seed={REPRODUCE_SEED}",
    ),
    (
        "2",
        "focused_template_ranges",
        "Re-run arithmetic template ranges (multiplier/square/divider/sqrt) "
        "with a higher candidate budget to improve exact-structural hit rate.",
        ", ".join(
            f"{s}-{e}"
            for s, e in list(_INITIAL_CFG.arithmetic_ranges) + [_INITIAL_CFG.divider_range, _INITIAL_CFG.sqrt_range]
        ),
    ),
    (
        "3",
        "diagnosis_rescue",
        "High-candidate rescue for diagnosis-sensitive cases using complement "
        "wrapper and history-guided GA flows.",
        ", ".join(_INITIAL_CFG.rescue_cases),
    ),
    (
        "4",
        "polish_and_sweep_convergence",
        "Fixed deterministic polish flows then sweep flows, repeated until ADP "
        "no longer decreases (early-stop per pass).",
        (
            f"polish: up to {_REFINE_CFG.polish_passes} passes; "
            f"sweep: up to {_REFINE_CFG.sweep_passes + _REFINE_CFG.final_sweep_passes} passes"
        ),
    ),
    (
        "5",
        "mockturtle_structural",
        "Fingerprint-guided mockturtle structural resynthesis (AIG/XAG/MIG); "
        "large/high-delay cases always try xag_xor_heavy and roundtrip_xag.",
        f"timeout_per_case={_REFINE_CFG.final_advanced_mockturtle_timeout}, max_modes=4",
    ),
    (
        "6",
        "type_and_objective_guided_refinement",
        "Circuit-family type-guided refinement (fingerprint selects flow set) "
        "followed by area/delay/balanced objective-guided refinement.",
        (
            f"type: max_flows={_REFINE_CFG.type_guided_max_flows}, timeout={_REFINE_CFG.type_guided_timeout}; "
            f"objective: max_per_family={_REFINE_CFG.objective_max_per_family}, timeout={_REFINE_CFG.objective_guided_timeout}"
        ),
    ),
    (
        "7",
        "micro_and_small_case_refinement",
        "Micro-guided low-cost resubstitution flows, then a targeted small-case "
        "package for circuits below the area/ADP threshold.",
        (
            f"micro: max_flows={_REFINE_CFG.micro_max_flows}, timeout={_REFINE_CFG.micro_guided_timeout}; "
            f"small: area<={_REFINE_CFG.small_case_area_threshold} or adp<={_REFINE_CFG.small_case_adp_threshold}"
        ),
    ),
    (
        "8",
        "truth_table_structural_resynthesis",
        "Build shared BDD/MUX structures with ABC &ttopt, then apply "
        "level-preserving transduction to reduce area.",
        f"timeout_per_case={_STRUCT_CFG.ttopt_structural_timeout}",
    ),
    (
        "9",
        "deepsyn_and_pareto_area_structural",
        "Bounded &deepsyn LUT map/unmap structural resynthesis, then area-Pareto "
        "search for large equal-width vector bottlenecks.",
        (
            f"deepsyn: {_STRUCT_CFG.deepsyn_structural_seconds}s x {_STRUCT_CFG.deepsyn_structural_passes} passes; "
            f"pareto: {_STRUCT_CFG.pareto_area_seconds}s, area>={_STRUCT_CFG.pareto_area_min_area}"
        ),
    ),
    (
        "10",
        "compact_vector_pareto_and_adaptive_probe",
        "Area-Pareto fixed-point for compact low-ANF-degree vector circuits, "
        "then adaptive probe: only run full refine when probe finds an improvement.",
        (
            f"compact: {_STRUCT_CFG.compact_pareto_passes} passes, {_STRUCT_CFG.compact_pareto_seconds}s; "
            f"adaptive: probe={_STRUCT_CFG.vector_probe_seconds}s, refine={_STRUCT_CFG.vector_refine_seconds}s"
        ),
    ),
    (
        "11",
        "long_large_alternate_seed_structural",
        "For large equal-width vector bottlenecks: regenerate topology from the "
        "truth table via long ttopt; run full Pareto refine only when probe improves.",
        (
            f"ttopt_rounds={_STRUCT_CFG.long_large_ttopt_rounds}, "
            f"probe={_STRUCT_CFG.long_large_probe_seconds}s -> refine={_STRUCT_CFG.long_large_refine_seconds}s"
        ),
    ),
    (
        "12",
        "yosys_mockturtle_hybrid_structural",
        "Symbol-free AIGER bridge into Yosys AIG remap, then fingerprint-selected "
        "mockturtle resynthesis starting from the improved seed.",
        (
            f"timeout_per_case={_STRUCT_CFG.hybrid_structural_timeout}, "
            f"mockturtle_workers={_STRUCT_CFG.hybrid_workers}"
        ),
    ),
    (
        "13",
        "area_first_refine",
        "Area-aggressive ABC flow suite (resub / dc2 / fraig / dch / if-K3 / sopb) "
        "applied to all cases until convergence.",
        (
            f"max_passes={_CONV_CFG.area_first_passes}, "
            f"timeout_per_case={_CONV_CFG.area_first_timeout}"
        ),
    ),
    (
        "14",
        "my_deepsyn_all_case_sweep",
        "Two-pass &my_deepsyn area-Pareto sweep over all cases. "
        "Pass 1 covers area>=500 with ratio-aware time bonus; "
        "Pass 2 gives a longer budget to area>=2000 cases.",
        (
            f"pass1: area>={_CONV_CFG.my_deepsyn_pass1_min_area}, base={_CONV_CFG.my_deepsyn_pass1_seconds}s, "
            f"high_ratio(>={_CONV_CFG.ratio_tier_high_threshold}x)+{_CONV_CFG.ratio_tier_high_extra}s; "
            f"pass2: area>={_CONV_CFG.my_deepsyn_pass2_min_area}, {_CONV_CFG.my_deepsyn_pass2_seconds}s"
        ),
    ),
    (
        "15",
        "case_fair_final_refinement",
        "Every case runs the same objective/micro/small/complement package once "
        "to ensure no case is skipped before final convergence.",
        (
            f"timeout_per_case={_CONV_CFG.case_fair_timeout}, "
            f"stage_timeout={REPRODUCE_CASE_FAIR_STAGE_TIMEOUT}, "
            "objective=1, micro=1, small=1, complement_budget=2"
        ),
    ),
    (
        "16",
        "final_micro_and_gia_convergence",
        "Interleaved micro-guided resubstitution and GIA canonical cleanup "
        "until ADP no longer decreases (early-stop).",
        (
            f"max_passes={_CONV_CFG.micro_convergence_passes}, "
            f"micro_timeout={_CONV_CFG.micro_convergence_timeout}, "
            f"gia_timeout={_CONV_CFG.gia_canonical_timeout}"
        ),
    ),
    (
        "17",
        "targeted_ratio_push",
        f"Measure ADP/reference ratios for all cases; run full rescue package "
        f"(type/objective/micro/Pareto) on every case above {_PUSH_CFG.ratio_threshold}x.",
        (
            f"ratio_threshold={_PUSH_CFG.ratio_threshold}x; "
            f"timeout={_PUSH_CFG.timeout}; "
            f"pareto_cases={','.join(_PUSH_CFG.pareto_cases)}, pareto_seconds={_PUSH_CFG.pareto_seconds}"
        ),
    ),
]


def format_reproduce_recipe() -> str:
    lines = [
        "Deterministic reproduce-best pipeline",
        "",
        "One-command entry point:",
        "  python3 student/flow_optimizer.py --reproduce-best --abc student/abc --benchmarks benchmarks --output output",
        "",
        "Stages:",
    ]
    for stage_id, name, description, parameters in REPRODUCE_RECIPE:
        lines.append(f"{stage_id}. {name}")
        lines.append(f"   {description}")
        lines.append(f"   Parameters: {parameters}")
    lines.extend(
        [
            "",
            "Safety contract:",
            "- Every replacement candidate is checked by ABC against the original truth table.",
            "- A candidate can overwrite output/exNNN.aig only when it is equivalent and has lower ADP.",
            "- Random-looking components use fixed seeds; the final refinement packages are fixed command sets.",
        ]
    )
    return "\n".join(lines)


def write_reproduce_recipe(logs: Path) -> None:
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reproduce_recipe.txt").write_text(format_reproduce_recipe() + "\n", encoding="utf-8")



def optimize_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    max_candidates: int,
    seed: int,
    timeout_per_case: int,
    root: Path,
    use_ga: bool,
    use_bdd: bool,
    use_polish: bool,
    try_complement: bool = False,
    history_guided_ga: bool = False,
) -> tuple[list[CandidateResult], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    tmp = prepare_case_temp_dir(logs, "tmp", case)

    initials = make_initial_candidates(case, table, tmp, seed, use_bdd, try_complement)
    ga_flows = make_ga_flows(case, seed, max(4, max_candidates // 4)) if use_ga else []
    if use_ga and history_guided_ga:
        ga_flows = make_history_guided_ga_flows(case, logs, seed, max(4, max_candidates // 4)) + ga_flows
    flows = POST_FLOWS + ga_flows
    pairs = choose_candidate_pairs(initials, flows, max(1, max_candidates))
    results: list[CandidateResult] = []
    best: CandidateResult | None = None
    baseline: CandidateResult | None = None
    deadline = time.monotonic() + timeout_per_case

    for index, (initial, flow) in enumerate(pairs):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_{index:03d}_{initial.method}_{flow.name}.aig"
        result = CandidateResult(case, initial.method, flow.name, flow.commands, aig=candidate_aig)
        try:
            synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 120), root)
            result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 120), root)
            if result.equivalent:
                result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 120), root)
                result.status = "OK"
                if initial.method == "abc_truth" and flow.name == "identity":
                    baseline = result
                if best is None or (result.adp is not None and result.adp < (best.adp or 10**30)):
                    best = result
            else:
                result.status = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            result.status = "TIMEOUT"
        except Exception:
            result.status = "ERROR"
        results.append(result)

    if best is None:
        fallback_aig = tmp / f"{case}_fallback_baseline.aig"
        fallback_flow = PostFlow("identity", "")
        fallback_initial = InitialCandidate("abc_truth", "truth", None)
        fallback = CandidateResult(case, "abc_truth", "identity", "", aig=fallback_aig)
        synthesize(abc, truth, fallback_initial, fallback_flow, fallback_aig, 120, root)
        fallback.equivalent = is_equivalent(abc, truth, fallback_aig, 120, root)
        if not fallback.equivalent:
            raise RuntimeError(f"{case}: no equivalent candidate found")
        fallback.area, fallback.delay, fallback.adp = measure_adp(abc, fallback_aig, 120, root)
        fallback.status = "OK"
        results.append(fallback)
        best = fallback
        baseline = fallback

    if baseline is None:
        baseline = best

    existing_aig = output / f"{case}.aig"
    if existing_aig.is_file():
        existing = CandidateResult(
            case,
            "existing_output",
            "current",
            "",
            equivalent=False,
            status="ERROR",
            aig=existing_aig,
        )
        try:
            existing.equivalent = is_equivalent(abc, truth, existing_aig, 120, root)
            if existing.equivalent:
                existing.area, existing.delay, existing.adp = measure_adp(abc, existing_aig, 120, root)
                existing.status = "OK"
                if existing.adp is not None and existing.adp < (best.adp or 10**30):
                    best = existing
            else:
                existing.status = "NOT_EQUIV"
        except Exception:
            existing.status = "ERROR"
        results.append(existing)

    if use_polish:
        polish_source = best
        assert polish_source.aig is not None
        for polish_index, polish_flow in enumerate(POLISH_FLOWS):
            remaining = max(1, int(deadline - time.monotonic()))
            if remaining <= 1:
                break
            candidate_aig = tmp / f"{case}_polish_{polish_index:02d}_{polish_flow.name}.aig"
            result = CandidateResult(
                case,
                f"post_polish_from_{polish_source.initial_method}",
                polish_flow.name,
                polish_flow.commands,
                aig=candidate_aig,
            )
            try:
                polish_aig(abc, polish_source.aig, polish_flow, candidate_aig, min(remaining, 180), root)
                result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 120), root)
                if result.equivalent:
                    result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 120), root)
                    result.status = "OK"
                    if result.adp is not None and result.adp < (best.adp or 10**30):
                        best = result
                        polish_source = result
                else:
                    result.status = "NOT_EQUIV"
            except subprocess.TimeoutExpired:
                result.status = "TIMEOUT"
            except Exception:
                result.status = "ERROR"
            results.append(result)

    best.selected = True
    output.mkdir(parents=True, exist_ok=True)
    final_aig = output / f"{case}.aig"
    if best.aig is not None and best.aig.resolve() != final_aig.resolve():
        shutil.copyfile(best.aig, final_aig)
    assert baseline.area is not None and baseline.delay is not None and baseline.adp is not None
    assert best.area is not None and best.delay is not None and best.adp is not None
    summary = CaseSummary(
        case=case,
        baseline_area=baseline.area,
        baseline_delay=baseline.delay,
        baseline_adp=baseline.adp,
        best_area=best.area,
        best_delay=best.delay,
        best_adp=best.adp,
        improvement_ratio=baseline.adp / best.adp if best.adp else 0.0,
        selected_method=f"{best.initial_method}/{best.flow_name}",
    )
    return results, summary









def inclusive_cases(start_case: str, end_case: str) -> list[str]:
    start = int(start_case.removeprefix("ex"))
    end = int(end_case.removeprefix("ex"))
    return [f"ex{i}" for i in range(start, end + 1)]


def verify_final_outputs(
    cases: list[str],
    abc: Path,
    benchmarks: Path,
    output: Path,
    root: Path,
) -> tuple[list[CandidateResult], list[CaseSummary]]:
    results: list[CandidateResult] = []
    summaries: list[CaseSummary] = []
    for case in cases:
        truth = benchmarks / f"{case}.truth"
        aig = output / f"{case}.aig"
        if not aig.is_file():
            raise RuntimeError(f"missing output AIG: {aig}")
        equivalent = is_equivalent(abc, truth, aig, 120, root)
        if not equivalent:
            raise RuntimeError(f"final output is not equivalent: {case}")
        area, delay, adp = measure_adp(abc, aig, 120, root)
        result = CandidateResult(
            case=case,
            initial_method="final_output",
            flow_name="reproduce_best_verify",
            flow_commands="",
            area=area,
            delay=delay,
            adp=adp,
            equivalent=True,
            selected=True,
            status="OK",
            aig=aig,
        )
        results.append(result)
        summaries.append(
            CaseSummary(
                case=case,
                baseline_area=area,
                baseline_delay=delay,
                baseline_adp=adp,
                best_area=area,
                best_delay=delay,
                best_adp=adp,
                improvement_ratio=1.0,
                selected_method="final_output/reproduce_best_verify",
            )
        )
    return results, summaries


# ---------------------------------------------------------------------------
# Phase 1 (stages 1-3): initial synthesis — full search, template ranges, rescue
# ---------------------------------------------------------------------------

def _run_optimize_case_safe(
    case: str,
    args: argparse.Namespace,
    root: Path,
    max_candidates: int,
    seed: int,
    use_ga: bool,
    use_bdd: bool,
    use_polish: bool,
    try_complement: bool = False,
    history_guided_ga: bool = False,
) -> tuple[str, list[CandidateResult], CandidateResult]:
    """Thread-safe wrapper: runs optimize_case and returns (case, rows, selected)."""
    # Skip cases whose output AIG already exists (resume support).
    existing = args.output / f"{case}.aig"
    if existing.is_file():
        try:
            area, delay, adp = measure_adp(args.abc, existing, 60, root)
            placeholder = CandidateResult(
                case=case, initial_method="existing_output", flow_name="current",
                flow_commands="", area=area, delay=delay, adp=adp,
                equivalent=True, selected=True, status="OK", aig=existing,
            )
            return case, [placeholder], placeholder
        except Exception:
            pass

    # Give each thread its own tmp workspace under logs/tmp_parallel/<case>/
    # so reset=True in prepare_case_temp_dir never races with another thread.
    import types as _types
    thread_args = _types.SimpleNamespace(**vars(args))
    thread_args.logs = args.logs / "tmp_parallel"
    thread_args.logs.mkdir(parents=True, exist_ok=True)

    rows, _summary = optimize_case(
        case, args.abc, args.benchmarks, args.output, thread_args.logs,
        max_candidates, seed, args.timeout_per_case, root,
        use_ga, use_bdd, use_polish, try_complement, history_guided_ga,
    )
    selected = next((r for r in rows if r.selected), rows[0])
    return case, rows, selected


def _phase_initial_synthesis(
    args: argparse.Namespace,
    root: Path,
    cfg: InitialSynthesisConfig,
    workers: int = 6,
) -> list[CandidateResult]:
    # Resolve all paths to absolute so threads don't depend on process cwd.
    import types, threading
    args = types.SimpleNamespace(**vars(args))
    args.abc        = Path(args.abc).resolve()
    args.benchmarks = Path(args.benchmarks).resolve()
    args.output     = Path(args.output).resolve()
    args.logs       = Path(args.logs).resolve()
    root            = root.resolve()

    results: list[CandidateResult] = []
    results_lock = threading.Lock()

    def _collect(case: str, rows: list[CandidateResult], selected: CandidateResult) -> None:
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
        with results_lock:
            results.extend(rows)

    # Stage 1: full hybrid synthesis — all cases in parallel
    print(f"[reproduce] stage 1/17: full hybrid synthesis search (workers={workers})")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_optimize_case_safe, case, args, root,
                cfg.main_max_candidates, cfg.seed,
                True, True, False,
            ): case
            for case in _filter_cases(ALL_CASES)
        }
        for future in as_completed(futures):
            case = futures[future]
            try:
                c, rows, selected = future.result()
                _collect(c, rows, selected)
            except Exception as exc:
                print(f"[{case}] ERROR in stage 1: {exc}")

    # Stage 2: focused arithmetic / divider / sqrt — parallel within each range
    print("[reproduce] stage 2/17: focused arithmetic, divider, and sqrt template ranges")
    focused_ranges = list(cfg.arithmetic_ranges) + [cfg.divider_range, cfg.sqrt_range]
    focused_cases = [
        case
        for start_case, end_case in focused_ranges
        for case in inclusive_cases(start_case, end_case)
    ]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _run_optimize_case_safe, case, args, root,
                cfg.focused_max_candidates, cfg.seed,
                False, True, False,
            ): case
            for case in focused_cases
        }
        for future in as_completed(futures):
            case = futures[future]
            try:
                c, rows, selected = future.result()
                _collect(c, rows, selected)
            except Exception as exc:
                print(f"[{case}] ERROR in stage 2: {exc}")

    # Stage 3: rescue cases — sequential (small list, high candidate count)
    print("[reproduce] stage 3/17: diagnosis-driven rescue")
    for case in cfg.rescue_cases:
        print(f"[{case}] optimizing rescue case")
        try:
            c, rows, selected = _run_optimize_case_safe(
                case, args, root,
                cfg.rescue_max_candidates, cfg.rescue_seed,
                True, True, True, True, True,
            )
            _collect(c, rows, selected)
        except Exception as exc:
            print(f"[{case}] ERROR in stage 3: {exc}")

    return results


# ---------------------------------------------------------------------------
# Phase 2 (stages 4-7): refinement — polish/sweep, mockturtle, type/objective,
#                        micro/small
# ---------------------------------------------------------------------------

def _phase_convergence_and_structural(
    args: argparse.Namespace,
    root: Path,
    ref_adp: dict[str, int],
    workers_a: int = 16,
    workers_b: int = 4,
) -> None:
    """Convergence loop (Stage A, parallel) + heavy structural (Stage B, parallel).

    workers_a: parallel workers for Stage A convergence loop (all 100 cases).
    workers_b: parallel workers for Stage B pareto/deepsyn (heavy, fewer workers
               to avoid ABC memory contention on large cases).
    """
    import threading

    # Resolve paths so threads don't depend on process cwd.
    import types as _types
    args = _types.SimpleNamespace(**vars(args))
    args.abc        = Path(args.abc).resolve()
    args.benchmarks = Path(args.benchmarks).resolve()
    args.output     = Path(args.output).resolve()
    args.logs       = Path(args.logs).resolve()
    root            = root.resolve()

    backup_dir = args.logs / "backup_before_new_pipeline"
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Backup stage-1 outputs before touching anything.
    for case in _filter_cases(ALL_CASES):
        src = args.output / f"{case}.aig"
        if src.is_file():
            shutil.copyfile(src, backup_dir / f"{case}.aig")

    # ------------------------------------------------------------------ Stage A
    print(f"[new-pipeline] stage A: convergence loop (all cases, workers={workers_a})")
    summaries_lock = threading.Lock()
    summaries_a: list[CaseSummary] = []

    def _run_convergence(case: str) -> CaseSummary:
        return run_convergence_loop_case(
            case, args.abc, args.benchmarks, args.output, args.logs,
            timeout_per_case=300, root=root, max_passes=40,
        )

    with ThreadPoolExecutor(max_workers=workers_a) as pool:
        futures = {pool.submit(_run_convergence, case): case for case in _filter_cases(ALL_CASES)}
        for future in as_completed(futures):
            case = futures[future]
            try:
                summary = future.result()
                with summaries_lock:
                    summaries_a.append(summary)
            except Exception as exc:
                print(f"[{case}] stage A ERROR: {exc}")

    total_before   = sum(s.baseline_adp for s in summaries_a)
    total_after_a  = sum(s.best_adp     for s in summaries_a)
    print(f"[new-pipeline] stage A done: {total_before:,} -> {total_after_a:,} "
          f"({(1 - total_after_a / max(total_before, 1)) * 100:.1f}% reduction)")

    # ------------------------------------------------------------------ Stage B
    heavy_cases = [c for c in _filter_cases(ALL_CASES) if c in _HEAVY_STRUCTURAL_CASES]
    print(f"[new-pipeline] stage B: heavy structural ({len(heavy_cases)} cases, workers={workers_b})")

    def _run_heavy(case: str) -> None:
        table = read_truth(args.benchmarks / f"{case}.truth")
        area, _d, adp = measure_adp(args.abc, args.output / f"{case}.aig", 60, root)

        if should_run_pareto_area_structural(table, area):
            print(f"[{case}] pareto structural")
            run_pareto_area_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                _STRUCT_CFG.pareto_area_structural_timeout, root,
                _STRUCT_CFG.seed, _STRUCT_CFG.pareto_area_seconds,
            )

        if should_run_deepsyn_structural(table, area, adp):
            print(f"[{case}] deepsyn structural")
            run_deepsyn_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                _STRUCT_CFG.deepsyn_structural_timeout, root,
                _STRUCT_CFG.seed, 1, _STRUCT_CFG.deepsyn_structural_seconds,
            )

        # Polish structural result with convergence loop.
        run_convergence_loop_case(
            case, args.abc, args.benchmarks, args.output, args.logs,
            timeout_per_case=180, root=root, max_passes=20,
        )

    with ThreadPoolExecutor(max_workers=workers_b) as pool:
        futures = {pool.submit(_run_heavy, case): case for case in heavy_cases}
        for future in as_completed(futures):
            case = futures[future]
            try:
                future.result()
            except Exception as exc:
                print(f"[{case}] stage B ERROR: {exc}")

    # ------------------------------------------------------------------ Rollback
    rolled_back = []
    for case in _filter_cases(ALL_CASES):
        backup  = backup_dir / f"{case}.aig"
        current = args.output / f"{case}.aig"
        if not backup.is_file() or not current.is_file():
            continue
        try:
            _, _, cur_adp = measure_adp(args.abc, current, 30, root)
            _, _, bak_adp = measure_adp(args.abc, backup,  30, root)
            if cur_adp > bak_adp:
                shutil.copyfile(backup, current)
                rolled_back.append(case)
        except Exception:
            pass

    if rolled_back:
        print(f"[new-pipeline] rolled back {len(rolled_back)} cases: {rolled_back}")

    total_after_b = sum(
        measure_adp(args.abc, args.output / f"{case}.aig", 30, root)[2]
        for case in _filter_cases(ALL_CASES)
    )
    print(f"[new-pipeline] final total ADP: {total_after_b:,} "
          f"(vs stage-A: {total_after_a:,})")


# ---------------------------------------------------------------------------
# Phase 6: targeted boost for lagging cases (ratio > 1.5)
# Runs AFTER all other phases; has per-case rollback so it cannot hurt.
# ---------------------------------------------------------------------------

def _phase_targeted_boost(args: argparse.Namespace, root: Path, ref_adp: dict[str, int]) -> None:
    """Extra optimisation for cases that still lag the reference by > 1.5x.

    Three sub-passes, each with rollback protection:
      C1 – signed-multiplier template + CSA seed for ex262/263/264 (and any
           other case whose exact type is signed_mult)
      C2 – deepsyn for small/medium cases (area 500-2000) that pass2 skipped
      C3 – longer deepsyn (300 s) for large cases (area >= 10000) still > 1.5x
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    abc        = Path(args.abc).resolve()
    benchmarks = Path(args.benchmarks).resolve()
    output     = Path(args.output).resolve()
    logs       = Path(args.logs).resolve()
    root       = root.resolve()

    def _cur_adp(case: str) -> tuple[int, int, int]:
        return measure_adp(abc, output / f"{case}.aig", 60, root)

    def _ratio(case: str) -> float:
        ref = ref_adp.get(case, 0)
        if not ref:
            return 0.0
        _, _, adp = _cur_adp(case)
        return adp / ref if adp else 999.0

    def _safe_replace(case: str, candidate: Path, backup: Path) -> bool:
        """Replace output only if candidate is better; always rollback-safe."""
        try:
            _, _, cand_adp = measure_adp(abc, candidate, 30, root)
            _, _, cur_adp  = measure_adp(abc, output / f"{case}.aig", 30, root)
            if cand_adp and cand_adp < cur_adp:
                if is_equivalent(abc, benchmarks / f"{case}.truth", candidate, 120, root):
                    shutil.copyfile(candidate, output / f"{case}.aig")
                    print(f"[targeted-boost] {case}: {cur_adp:,} → {cand_adp:,} *** IMPROVED ***")
                    return True
        except Exception as exc:
            print(f"[targeted-boost] {case}: error {exc}")
        return False

    lagging = [
        c for c in _filter_cases(ALL_CASES)
        if (output / f"{c}.aig").is_file() and _ratio(c) > 1.5
    ]
    print(f"[targeted-boost] {len(lagging)} cases with ratio > 1.5: {lagging}")

    # ── C1: signed-multiplier template seed ──────────────────────────────────
    print("[targeted-boost] C1: signed-multiplier template candidates")
    import tempfile as _tempfile
    signed_mult_cases = []
    for case in lagging:
        truth = benchmarks / f"{case}.truth"
        table = read_truth(truth)
        orders = detect_signed_multiplier(table)
        if orders is not None:
            signed_mult_cases.append((case, table, orders))

    for case, table, (a_order, b_order) in signed_mult_cases:
        backup = logs / f"boost_c1_backup_{case}.aig"
        shutil.copyfile(output / f"{case}.aig", backup)
        with _tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            truth = benchmarks / f"{case}.truth"
            for blif_name, write_fn in [
                ("signed_mult", write_signed_multiplier_blif),
                ("signed_mult_csa", write_signed_multiplier_csa_blif),
            ]:
                blif = tmp / f"{case}_{blif_name}.blif"
                write_fn(blif, f"{case}_{blif_name}", table, a_order, b_order)
                for flow_name, flow_cmds in [
                    ("balance", "balance"),
                    ("dc2", "strash; dc2; balance"),
                    ("rw_rf", "strash; rewrite -z; refactor -z; dc2; balance"),
                    ("resub", "strash; resub -K 6; rewrite -z; refactor -z; dc2; balance"),
                ]:
                    cand = tmp / f"{case}_{blif_name}_{flow_name}.aig"
                    try:
                        run_abc_script(
                            abc,
                            f'read_blif "{blif}"; {flow_cmds}; write_aiger -s "{cand}"',
                            180,
                        )
                        _safe_replace(case, cand, backup)
                    except Exception:
                        pass
        # rollback if worse
        try:
            _, _, new_adp = _cur_adp(case)
            _, _, bak_adp = measure_adp(abc, backup, 30, root)
            if new_adp > bak_adp:
                shutil.copyfile(backup, output / f"{case}.aig")
        except Exception:
            pass

    # ── C2: deepsyn for small/medium cases skipped by pass2 (area 500-2000) ──
    print("[targeted-boost] C2: deepsyn for small/medium high-ratio cases")
    c2_cases = []
    for case in lagging:
        area, _, _ = _cur_adp(case)
        if area and 500 <= area < 2000:
            c2_cases.append(case)
    print(f"[targeted-boost] C2 cases: {c2_cases}")

    def _run_c2(case: str) -> None:
        backup = logs / f"boost_c2_backup_{case}.aig"
        aig = output / f"{case}.aig"
        shutil.copyfile(aig, backup)
        # Try a suite of synthesis flows directly on the existing AIG
        with _tempfile.TemporaryDirectory() as tmp_str:
            tmp = Path(tmp_str)
            for fname, fcmds in [
                ("dc2x3",    "dc2; dc2; dc2; balance"),
                ("rwz_rfz",  "rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
                ("syn2",     "&get; &syn2 -J 8; &put; balance"),
                ("syn3",     "&get; &syn3; &put; balance"),
                ("dch",      "&get; &dch; &put; balance"),
                ("dc2_syn2", "dc2; &get; &syn2 -J 8; &put; dc2; balance"),
                ("b_dc2_b",  "balance; dc2; balance; rewrite -z; balance"),
            ]:
                cand = tmp / f"{case}_c2_{fname}.aig"
                try:
                    run_abc_script(
                        abc,
                        f'read_aiger "{aig}"; {fcmds}; write_aiger -s "{cand}"',
                        120,
                    )
                    _safe_replace(case, cand, backup)
                except Exception:
                    pass
        run_pareto_area_structural_case(
            case, abc, benchmarks, output, logs,
            timeout_per_case=300, root=root, seed=42, search_seconds=120,
        )
        # rollback if worse
        try:
            _, _, new_adp = _cur_adp(case)
            _, _, bak_adp = measure_adp(abc, backup, 30, root)
            if new_adp > bak_adp:
                shutil.copyfile(backup, aig)
                print(f"[targeted-boost] C2 {case}: rolled back")
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_run_c2, c): c for c in c2_cases}
        for f in _as_completed(futs):
            c = futs[f]
            try:
                f.result()
            except Exception as exc:
                print(f"[targeted-boost] C2 {c} ERROR: {exc}")

    # ── C3: longer deepsyn for large cases still lagging ─────────────────────
    print("[targeted-boost] C3: longer deepsyn for large high-ratio cases")
    c3_cases = []
    for case in _filter_cases(ALL_CASES):
        if not (output / f"{case}.aig").is_file():
            continue
        area, _, _ = _cur_adp(case)
        if area and area >= 10000 and _ratio(case) > 1.5:
            c3_cases.append(case)
    print(f"[targeted-boost] C3 cases: {c3_cases}")

    def _run_c3(case: str) -> None:
        backup = logs / f"boost_c3_backup_{case}.aig"
        shutil.copyfile(output / f"{case}.aig", backup)
        run_pareto_area_structural_case(
            case, abc, benchmarks, output, logs,
            timeout_per_case=360, root=root, seed=42, search_seconds=300,
        )
        run_convergence_loop_case(
            case, abc, benchmarks, output, logs,
            timeout_per_case=180, root=root, max_passes=20,
        )
        # rollback if worse
        try:
            _, _, new_adp = _cur_adp(case)
            _, _, bak_adp = measure_adp(abc, backup, 30, root)
            if new_adp > bak_adp:
                shutil.copyfile(backup, output / f"{case}.aig")
                print(f"[targeted-boost] C3 {case}: rolled back")
        except Exception:
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(_run_c3, c): c for c in c3_cases}
        for f in _as_completed(futs):
            c = futs[f]
            try:
                f.result()
            except Exception as exc:
                print(f"[targeted-boost] C3 {c} ERROR: {exc}")

    # ── C4: mockturtle structural for all still-lagging cases ─────────────────
    mt_bin = getattr(args, "mockturtle_structural_bin", None)
    if mt_bin is not None and Path(mt_bin).is_file():
        # re-check lagging after C1/C2/C3
        lagging_c4 = [
            c for c in _filter_cases(ALL_CASES)
            if (output / f"{c}.aig").is_file() and _ratio(c) > 1.5
        ]
        print(f"[targeted-boost] C4: mockturtle for {len(lagging_c4)} still-lagging cases")

        def _run_c4(case: str) -> None:
            backup = logs / f"boost_c4_backup_{case}.aig"
            shutil.copyfile(output / f"{case}.aig", backup)
            try:
                run_mockturtle_structural_case(
                    case, abc, benchmarks, output, logs,
                    timeout_per_case=300,
                    root=root,
                    mockturtle_bin=Path(mt_bin),
                    max_modes=4,
                    exact_max_inputs=12,
                )
            except Exception as exc:
                print(f"[targeted-boost] C4 {case}: {exc}")
            # rollback if worse
            try:
                _, _, new_adp = _cur_adp(case)
                _, _, bak_adp = measure_adp(abc, backup, 30, root)
                if new_adp > bak_adp:
                    shutil.copyfile(backup, output / f"{case}.aig")
                    print(f"[targeted-boost] C4 {case}: rolled back")
            except Exception:
                pass

        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {pool.submit(_run_c4, c): c for c in lagging_c4}
            for f in _as_completed(futs):
                c = futs[f]
                try:
                    f.result()
                except Exception as exc:
                    print(f"[targeted-boost] C4 {c} ERROR: {exc}")

    print("[targeted-boost] done.")


# ---------------------------------------------------------------------------
# Top-level entry point — thin orchestrator that calls the phases in order
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase 4: re-synthesis competition — re-run the full initial-synthesis search
# from the truth table with a much larger candidate budget, competing against
# the existing output AIG (optimize_case only replaces on strict improvement).
# ---------------------------------------------------------------------------

_RESYNTH_LARGE_CASES = {"ex297", "ex299", "ex226", "ex206", "ex220", "ex221", "ex222", "ex230"}


def _phase_resynth_competition(
    args: argparse.Namespace,
    root: Path,
    *,
    max_candidates: int = 120,
    timeout_per_case: int = 600,
    seed: int = 0,
    workers: int = 6,
) -> None:
    print(f"[reproduce] phase 4: re-synthesis competition "
          f"(candidates={max_candidates}, timeout={timeout_per_case}s, workers={workers})")

    def _cur_adp(case: str) -> int | None:
        aig = args.output / f"{case}.aig"
        if not aig.is_file():
            return None
        try:
            return measure_adp(args.abc, aig, 60, root)[2]
        except Exception:
            return None

    def _run(case: str) -> None:
        before = _cur_adp(case)
        aig = args.output / f"{case}.aig"
        backup = args.logs / f"resynth_backup_{case}.aig"
        if aig.is_file():
            shutil.copyfile(aig, backup)
        try:
            optimize_case(
                case, args.abc, args.benchmarks, args.output,
                args.logs / "tmp_resynth",
                max_candidates, seed, timeout_per_case, root,
                use_ga=True, use_bdd=True, use_polish=True,
                try_complement=True, history_guided_ga=False,
            )
        except Exception as exc:
            print(f"[{case}] resynth ERROR: {exc}")
        after = _cur_adp(case)
        # safety rollback: optimize_case should never regress, but guarantee it
        if before is not None and after is not None and after > before and backup.is_file():
            shutil.copyfile(backup, aig)
            after = before
        tag = ""
        if before is not None and after is not None and after < before:
            tag = f"  *** IMPROVED -{before - after} ***"
        print(f"[{case}] resynth {before} -> {after}{tag}")

    cases = [c for c in _filter_cases(ALL_CASES) if (args.benchmarks / f"{c}.truth").is_file()]
    small = [c for c in cases if c not in _RESYNTH_LARGE_CASES]
    large = [c for c in cases if c in _RESYNTH_LARGE_CASES]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed({pool.submit(_run, c): c for c in small}):
            fut.result()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for fut in as_completed({pool.submit(_run, c): c for c in large}):
            fut.result()


def run_reproduce_best(args: argparse.Namespace, root: Path) -> tuple[list[CandidateResult], list[CaseSummary]]:
    write_reproduce_recipe(args.logs)
    print(format_reproduce_recipe())
    print("")

    ref_adp = _load_reference_adp(root)
    step_results: list[CandidateResult] = []

    # Phase 1: initial synthesis (unchanged — stages 1-3)
    step_results.extend(_phase_initial_synthesis(args, root, _INITIAL_CFG, workers=16))

    # Phase 2: new simplified convergence loop + structural (replaces stages 4-17)
    _phase_convergence_and_structural(args, root, ref_adp)

    # Phase 3: targeted boost for lagging cases (ratio > 1.5x reference)
    _phase_targeted_boost(args, root, ref_adp)

    # Phase 4: re-synthesis competition with a larger candidate budget
    _phase_resynth_competition(args, root)

    write_results_csv(args.logs / "stage_reproduce_log.csv", step_results)
    final_results, final_summaries = verify_final_outputs(
        selected_cases_from_args(args), args.abc, args.benchmarks, args.output, root,
    )
    equivalent_count = sum(1 for row in final_results if row.equivalent)
    total_adp = sum(row.adp or 0 for row in final_results if row.equivalent)
    print("------------------------------------------------------")
    print(f"Equivalent cases: {equivalent_count}/{len(final_results)}")
    print(f"Total ADP over equivalent cases: {total_adp}")
    return final_results, final_summaries


def polish_existing_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    try_mockturtle: bool = False,
    mockturtle_bin: Path | None = None,
) -> tuple[list[CandidateResult], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_polish", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    results = [
        CandidateResult(
            case=case,
            initial_method="existing_output",
            flow_name="current",
            flow_commands="",
            area=base_area,
            delay=base_delay,
            adp=base_adp,
            equivalent=True,
            status="OK",
            aig=source,
        )
    ]
    best = results[0]
    deadline = time.monotonic() + timeout_per_case
    for index, flow in enumerate(POLISH_FLOWS):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        result = CandidateResult(
            case=case,
            initial_method="existing_output_polish",
            flow_name=flow.name,
            flow_commands=flow.commands,
            aig=candidate_aig,
        )
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 180), root)
            result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 120), root)
            if result.equivalent:
                result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 120), root)
                result.status = "OK"
                if result.adp is not None and result.adp < (best.adp or 10**30):
                    best = result
            else:
                result.status = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            result.status = "TIMEOUT"
        except Exception:
            result.status = "ERROR"
        results.append(result)

    best.selected = True
    if best.aig is not None and best.aig != source:
        shutil.copyfile(best.aig, source)
    assert best.area is not None and best.delay is not None and best.adp is not None
    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best.area,
        best_delay=best.delay,
        best_adp=best.adp,
        improvement_ratio=base_adp / best.adp if best.adp else 0.0,
        selected_method=f"{best.initial_method}/{best.flow_name}",
    )
    return results, summary


def sweep_existing_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    try_mockturtle: bool = False,
    mockturtle_bin: Path | None = None,
) -> tuple[list[CandidateResult], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_sweep", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    results = [
        CandidateResult(
            case=case,
            initial_method="existing_output",
            flow_name="current",
            flow_commands="",
            area=base_area,
            delay=base_delay,
            adp=base_adp,
            equivalent=True,
            status="OK",
            aig=source,
        )
    ]
    best = results[0]
    deadline = time.monotonic() + timeout_per_case

    if try_mockturtle and mockturtle_bin is not None and mockturtle_bin.is_file():
        for mode in MOCKTURTLE_MODES:
            remaining = max(1, int(deadline - time.monotonic()))
            if remaining <= 1:
                break
            assert best.aig is not None
            raw_aig = tmp / f"{case}_mockturtle_{mode}_raw.aig"
            candidate_aig = tmp / f"{case}_mockturtle_{mode}.aig"
            result = CandidateResult(
                case=case,
                initial_method="existing_output_mockturtle",
                flow_name=f"mockturtle_{mode}_abc_cleanup",
                flow_commands=f"mockturtle:{mode}; {MOCKTURTLE_POST_FLOW.commands}",
                aig=candidate_aig,
            )
            try:
                run_mockturtle_opt(mockturtle_bin, best.aig, raw_aig, mode, min(remaining, 120), root)
                polish_aig(abc, raw_aig, MOCKTURTLE_POST_FLOW, candidate_aig, min(remaining, 120), root)
                result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                if result.equivalent:
                    result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                    result.status = "OK"
                    if result.adp is not None and result.adp < (best.adp or 10**30):
                        best = result
                else:
                    result.status = "NOT_EQUIV"
            except subprocess.TimeoutExpired:
                result.status = "TIMEOUT"
            except Exception:
                result.status = "ERROR"
            results.append(result)

    for index, flow in enumerate(SWEEP_FLOWS):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        result = CandidateResult(
            case=case,
            initial_method="existing_output_sweep",
            flow_name=flow.name,
            flow_commands=flow.commands,
            aig=candidate_aig,
        )
        try:
            assert best.aig is not None
            polish_aig(abc, best.aig, flow, candidate_aig, min(remaining, 120), root)
            result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            if result.equivalent:
                result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                result.status = "OK"
                if result.adp is not None and result.adp < (best.adp or 10**30):
                    best = result
            else:
                result.status = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            result.status = "TIMEOUT"
        except Exception:
            result.status = "ERROR"
        results.append(result)

    best.selected = True
    if best.aig is not None and best.aig != source:
        shutil.copyfile(best.aig, source)
    assert best.area is not None and best.delay is not None and best.adp is not None
    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best.area,
        best_delay=best.delay,
        best_adp=best.adp,
        improvement_ratio=base_adp / best.adp if best.adp else 0.0,
        selected_method=f"{best.initial_method}/{best.flow_name}",
    )
    return results, summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hybrid AIG optimizer")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", help="run one benchmark, for example ex200")
    group.add_argument("--all", action="store_true", help="run ex200 through ex299")
    group.add_argument("--range", nargs=2, metavar=("START", "END"), help="run an inclusive case range")
    group.add_argument("--reproduce-best", action="store_true", help="run the full deterministic best-result workflow")
    parser.add_argument("--cases", nargs="+", metavar="CASE", help="filter pipeline to only these cases (combinable with --reproduce-best)")
    parser.add_argument("--show-reproduce-recipe", action="store_true", help="print the deterministic reproduce-best stage recipe and exit")
    parser.add_argument("--analyze-case", help="print truth-table features and exit")
    parser.add_argument("--classify-case", help="print Boolean fingerprint/classification and exit")
    parser.add_argument("--exact-function-report", action="store_true", help="write exact function recognition matches and exit")
    parser.add_argument("--exact-match-all", action="store_true", help="alias for exact function recognition over the selected cases")
    parser.add_argument("--verify-final", action="store_true", help="verify current output AIGs and refresh results/summary logs")
    parser.add_argument("--exact-max-inputs", type=int, default=14, help="maximum input count for expensive exact arithmetic detectors")
    parser.add_argument("--abc", type=Path, default=Path("student/abc"))
    parser.add_argument("--benchmarks", type=Path, default=Path("benchmarks"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--logs", type=Path, default=Path("student/logs"))
    parser.add_argument("--max-candidates", type=int, default=48)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout-per-case", type=int, default=300)
    parser.add_argument("--no-ga", action="store_true", help="disable deterministic GA-generated ABC flows")
    parser.add_argument("--no-bdd", action="store_true", help="disable custom BDD/Shannon initial synthesis")
    parser.add_argument("--polish-after-synthesis", action="store_true", help="try final polish flows immediately after synthesis search")
    parser.add_argument("--polish-existing", action="store_true", help="polish existing AIGs in --output in place")
    parser.add_argument("--polish-passes", type=int, default=1, help="number of in-place polish passes when --polish-existing is used")
    parser.add_argument("--sweep-existing", action="store_true", help="run deterministic per-case hill-climb sweep on existing AIGs")
    parser.add_argument("--sweep-passes", type=int, default=1, help="number of sweep passes when --sweep-existing is used")
    parser.add_argument("--try-mockturtle", action="store_true", help="try optional mockturtle AIG rewrites during existing-output sweep")
    parser.add_argument("--mockturtle-bin", type=Path, default=Path("student/mockturtle"), help="path to optional mockturtle optimizer binary")
    parser.add_argument("--mockturtle-structural", action="store_true", help="try fingerprint-guided structural mockturtle resynthesis")
    parser.add_argument("--mockturtle-case", help="run structural mockturtle resynthesis on one case")
    parser.add_argument("--mode", choices=STRUCTURAL_MOCKTURTLE_MODES, help="explicit structural mockturtle mode for --mockturtle-case")
    parser.add_argument("--mockturtle-max-modes", type=int, default=2, help="maximum fingerprint-selected mockturtle modes per case")
    parser.add_argument("--mockturtle-workers", type=int, default=2, help="maximum parallel mockturtle structural candidates in hybrid mode")
    parser.add_argument(
        "--mockturtle-structural-bin",
        type=Path,
        default=Path("student/mockturtle_opt/mockturtle_opt"),
        help="path to the structural mockturtle optimizer binary",
    )
    parser.add_argument("--report-stats", action="store_true", help="print report-oriented aggregate statistics")
    parser.add_argument("--complement-rescue", action="store_true", help="run generic complement synthesis wrapper candidates")
    parser.add_argument("--complement-budget", type=int, default=16, help="maximum complement wrapper candidates per case")
    parser.add_argument("--validate-templates", action="store_true", help="write exact arithmetic/template validation CSV")
    parser.add_argument("--case-fair-next-optimize", action="store_true", help="run the next deterministic fair refinement package on every selected case")
    parser.add_argument("--case-fair-stage-timeout", type=int, default=12, help="maximum seconds for each sub-stage in --case-fair-next-optimize")
    parser.add_argument("--type-guided-refine", action="store_true", help="classify every selected case and run a fixed type-specific refinement package")
    parser.add_argument("--type-guided-max-flows", type=int, default=5, help="maximum type-guided ABC refinement flows per case")
    parser.add_argument("--circuit-type-optimize", action="store_true", help="run circuit-family-specific polish plus truth-seed refinement")
    parser.add_argument("--circuit-type-max-flows", type=int, default=8, help="maximum current-AIG polish flows for --circuit-type-optimize")
    parser.add_argument("--circuit-type-max-seeds", type=int, default=3, help="maximum type-selected truth/BDD seeds for --circuit-type-optimize")
    parser.add_argument("--semantic-split-optimize", action="store_true", help="run exponent/class split BLIF front-end reconstruction candidates")
    parser.add_argument("--semantic-max-splits", type=int, default=3, help="maximum class-split structures per case")
    parser.add_argument("--semantic-max-flows", type=int, default=3, help="maximum cleanup flows per semantic split")
    parser.add_argument("--objective-guided-refine", action="store_true", help="try fixed area-first, delay-first, and balanced refinement packages per case")
    parser.add_argument("--objective-max-per-family", type=int, default=3, help="maximum objective-guided flows from each objective family")
    parser.add_argument("--micro-guided-refine", action="store_true", help="try small-circuit micro refinement flows on every selected case")
    parser.add_argument("--micro-max-flows", type=int, default=4, help="maximum micro-guided refinement flows per case")
    parser.add_argument("--gia-canonical-converge", action="store_true", help="repeat deterministic GIA canonical cleanup while it lowers ADP")
    parser.add_argument("--gia-canonical-max-passes", type=int, default=16, help="maximum GIA canonical cleanup passes per case")
    parser.add_argument("--area-first-refine", action="store_true", help="apply area-aggressive flows (resub/dc2/fraig/dch-if) to all selected cases")
    parser.add_argument("--small-case-refine", action="store_true", help="run a small-case-only refinement package selected by current area/ADP")
    parser.add_argument("--specialized-generators", action="store_true", help="run exact-match structural generators and accept only ADP improvements")
    parser.add_argument("--specialized-generate", action="store_true", help="alias for --specialized-generators")
    parser.add_argument("--ttopt-structural", action="store_true", help="run truth-table BDD/MUX structural synthesis with ABC &ttopt")
    parser.add_argument("--deepsyn-structural", action="store_true", help="run bounded deterministic LUT map/unmap structural resynthesis with ABC &deepsyn")
    parser.add_argument("--deepsyn-iterations", type=int, default=1, help="number of bounded &deepsyn iterations per selected case")
    parser.add_argument("--deepsyn-seconds", type=int, default=30, help="per-iteration search seconds for --deepsyn-structural")
    parser.add_argument("--pareto-area-structural", action="store_true", help="run deterministic area-first Pareto structural resynthesis with ABC &my_deepsyn")
    parser.add_argument("--pareto-area-seconds", type=int, default=80, help="search seconds for --pareto-area-structural")
    parser.add_argument("--long-large-structural", action="store_true", help="run long alternate-seed Pareto reconstruction for large vector cases")
    parser.add_argument("--long-large-seconds", type=int, default=600, help="area-Pareto search seconds for --long-large-structural")
    parser.add_argument("--long-large-min-area", type=int, default=25000, help="minimum current area selected automatically for --long-large-structural")
    parser.add_argument("--long-large-min-adp", type=int, default=500000, help="minimum current ADP selected automatically for --long-large-structural")
    parser.add_argument("--ttopt-seed-rounds", type=int, default=60, help="truth-table topology synthesis rounds for --long-large-structural")
    parser.add_argument("--compact-low-degree-pareto", action="store_true", help="run area-Pareto structural resynthesis only on compact low-ANF-degree vector functions")
    parser.add_argument("--compact-vector-pareto-probe", action="store_true", help="probe compact equal-width vector functions and structurally refine only verified improvers")
    parser.add_argument("--hybrid-structural", action="store_true", help="run safe Yosys AIG remapping followed by conditional mockturtle structural resynthesis")
    parser.add_argument("--yosys-bin", type=Path, default=Path("yosys"), help="path or command name for Yosys used by --hybrid-structural")
    parser.add_argument("--exact-npn-rescue", action="store_true", help="run exact small-support/NPN-style rescue candidates")
    parser.add_argument("--npn-max-support", type=int, default=6, help="maximum per-output support for exact small-support rescue")
    parser.add_argument("--npn-max-flows", type=int, default=4, help="maximum ABC reductions for exact small-support rescue")
    parser.add_argument("--transduction-rescue", action="store_true", help="run bounded equivalent expansion/reduction rescue")
    parser.add_argument("--transduction-budget", type=int, default=12, help="maximum transduction candidates per case")
    parser.add_argument("--small-max-flows", type=int, default=5, help="maximum small-case refinement flows per selected case")
    parser.add_argument("--small-area-threshold", type=int, default=2500, help="treat current outputs with area at or below this as small cases")
    parser.add_argument("--small-adp-threshold", type=int, default=50000, help="treat current outputs with ADP at or below this as small cases")
    # Block D optimizer (merged from optimize.py)
    parser.add_argument("--optimize", action="store_true", help="run Block D equivalence-gated backend sweep (flows/resynth/deepsyn/mockturtle)")
    parser.add_argument("--strategies", nargs="*", default=["flows", "resynth", "deepsyn", "mockturtle"],
                        help="subset/order of Block D strategies")
    parser.add_argument("--optimize-deepsyn-seconds", type=int, default=90, help="per-seed &my_deepsyn seconds for --optimize")
    parser.add_argument("--seeds", type=int, nargs="*", default=[0, 42], help="random seeds for --optimize deepsyn")
    parser.add_argument("--workers", type=int, default=6, help="parallel workers for --optimize")
    parser.add_argument("--above-ratio", type=float, default=None,
                        help="--optimize: only cases with ADP/reference >= this ratio")
    parser.add_argument("--no-refresh", action="store_true", help="skip recipe refresh after --optimize")
    return parser.parse_args()


def selected_cases_from_args(args: argparse.Namespace, override_case: str | None = None) -> list[str]:
    if override_case:
        return [override_case]
    if args.case:
        return [args.case]
    if getattr(args, "cases", None):
        return list(args.cases)
    if args.range:
        start = int(args.range[0].removeprefix("ex"))
        end = int(args.range[1].removeprefix("ex"))
        return [f"ex{i}" for i in range(start, end + 1)]
    return ALL_CASES


def print_summary_totals(prefix: str, summaries: list[CaseSummary]) -> None:
    baseline_total = sum(row.baseline_adp for row in summaries)
    best_total = sum(row.best_adp for row in summaries)
    print(f"[{prefix}] total ADP {baseline_total} -> {best_total}")


def run_verify_final(args: argparse.Namespace, root: Path, write_final_summary: bool = False) -> tuple[list[CandidateResult], list[CaseSummary]]:
    cases = selected_cases_from_args(args)
    results, summaries = verify_final_outputs(cases, args.abc, args.benchmarks, args.output, root)
    write_results_csv(args.logs / "results.csv", results)
    write_summary_csv(args.logs / "summary.csv", summaries)
    _write_pareto_candidates_from_results(args.logs / "stage_pareto_log.csv", results)
    equivalent_count = sum(1 for row in results if row.equivalent)
    total_adp = sum(row.adp or 0 for row in results if row.equivalent)
    print("------------------------------------------------------")
    print(f"Equivalent cases: {equivalent_count}/{len(results)}")
    print(f"Total ADP over equivalent cases: {total_adp}")
    return results, summaries




# ---------------------------------------------------------------------------
# Block D optimizer (merged from optimize.py)
# Equivalence-gated, rollback-safe per-case backend sweep.
# Strategies: resynth | flows | deepsyn | mockturtle
# ---------------------------------------------------------------------------

_OPT_LARGE_CASES = {"ex297", "ex299", "ex226", "ex206", "ex220", "ex221", "ex222", "ex230"}

_OPT_ABC_FLOWS = [
    ("dc2x3",    "dc2; dc2; dc2; balance"),
    ("rwz_rfz",  "rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
    ("syn2",     "&get; &syn2 -J 8; &put; balance"),
    ("syn3",     "&get; &syn3; &put; balance"),
    ("dch",      "&get; &dch; &put; balance"),
    ("dch_syn2", "&get; &dch; &syn2 -J 8; &put; balance"),
    ("dc2_syn2", "dc2; &get; &syn2 -J 8; &put; dc2; balance"),
    ("resub_dc2","resub -K 8; dc2; rewrite -z; balance"),
    ("fraig_dc2","fraig; dc2; rewrite -z; balance"),
    ("mfs",      "dc2; &get; &mfs; &put; balance"),
    ("mfs_w4",   "&get; &dch; &mfs -W 4; &put; dc2; balance"),
    ("dc2_mfs",  "dc2; &get; &mfs -W 4 -M 5000; &put; dc2; balance"),
    ("mfs_w6",   "&get; &mfs -W 6 -M 8000; &put; dc2; balance"),
    ("dchf_mfs", "&get; &dch -f; &mfs; &put; dc2; balance"),
]


def _opt_cur_adp(case: str, output: Path, abc: Path, root: Path) -> int | None:
    aig = output / f"{case}.aig"
    if not aig.is_file():
        return None
    try:
        return measure_adp(abc, aig, 60, root)[2]
    except Exception:
        return None


def _opt_adopt(case: str, cand: Path, best: int, abc: Path, benchmarks: Path, output: Path, root: Path) -> tuple[bool, int]:
    try:
        _, _, adp = measure_adp(abc, cand, 60, root)
    except Exception:
        return False, best
    if adp >= best:
        return False, best
    if not is_equivalent(abc, benchmarks / f"{case}.truth", cand, 180, root):
        return False, best
    import shutil as _shutil
    _shutil.copyfile(cand, output / f"{case}.aig")
    return True, adp


def _opt_strat_resynth(case: str, best: int, abc: Path, benchmarks: Path, output: Path, logs: Path, root: Path, timeout: int) -> int:
    try:
        optimize_case(
            case, abc, benchmarks, output, logs / "tmp_optimize",
            120, 0, timeout, root,
            use_ga=True, use_bdd=True, use_polish=True, try_complement=True,
        )
    except Exception as exc:
        print(f"  [{case}] resynth error: {exc}", flush=True)
    return _opt_cur_adp(case, output, abc, root) or best


def _opt_strat_flows(case: str, best: int, abc: Path, benchmarks: Path, output: Path, root: Path, timeout: int) -> int:
    import tempfile as _tempfile, shutil as _shutil
    aig = output / f"{case}.aig"
    with _tempfile.TemporaryDirectory(prefix=f"opt_{case}_") as tmp_str:
        tmp = Path(tmp_str)
        for name, flow in _OPT_ABC_FLOWS:
            cand = tmp / f"{case}_{name}.aig"
            try:
                run_abc_script(abc, f'read_aiger "{aig}"; {flow}; write_aiger -s "{cand}"', timeout)
            except Exception:
                continue
            adopted, best = _opt_adopt(case, cand, best, abc, benchmarks, output, root)
            if adopted:
                print(f"  [{case}] flows/{name}: ADP={best:,}", flush=True)
    return best


def _opt_strat_deepsyn(case: str, best: int, abc: Path, benchmarks: Path, output: Path, root: Path, seconds: int, seeds: list[int]) -> int:
    import tempfile as _tempfile
    aig = output / f"{case}.aig"
    with _tempfile.TemporaryDirectory(prefix=f"opt_ds_{case}_") as tmp_str:
        tmp = Path(tmp_str)
        for cost in ("adp", "area"):
            for seed in seeds:
                pareto = tmp / f"p_{cost}_{seed}"
                pareto.mkdir(parents=True, exist_ok=True)
                try:
                    run_abc_script(
                        abc,
                        f'read_aiger "{aig}"; dc2; dc2; '
                        f'&get; &my_deepsyn -T {seconds} -S {seed} -O "{pareto}" -C {cost}; &put',
                        seconds + 120,
                    )
                except Exception:
                    continue
                for cand in sorted(pareto.glob("*.aig")):
                    adopted, best = _opt_adopt(case, cand, best, abc, benchmarks, output, root)
                    if adopted:
                        print(f"  [{case}] deepsyn/{cost}/{seed}: ADP={best:,}", flush=True)
    return best


def _opt_strat_mockturtle(case: str, best: int, abc: Path, benchmarks: Path, output: Path, logs: Path, root: Path, timeout: int, mockturtle_bin: Path) -> int:
    import shutil as _shutil
    if not mockturtle_bin.is_file():
        return best
    backup = logs / f"opt_mt_{case}.aig"
    _shutil.copyfile(output / f"{case}.aig", backup)
    try:
        run_mockturtle_structural_case(
            case, abc, benchmarks, output, logs,
            timeout_per_case=timeout, root=root,
            mockturtle_bin=mockturtle_bin, max_modes=4, exact_max_inputs=12,
        )
    except Exception as exc:
        print(f"  [{case}] mockturtle error: {exc}", flush=True)
    new = _opt_cur_adp(case, output, abc, root) or best
    if new > best:
        _shutil.copyfile(backup, output / f"{case}.aig")
        return best
    return new


def run_block_d_optimize(
    cases: list[str],
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    root: Path,
    strategies: list[str],
    timeout: int = 200,
    deepsyn_seconds: int = 90,
    seeds: list[int] | None = None,
    workers: int = 6,
    mockturtle_bin: Path | None = None,
) -> None:
    """Block D backend sweep: equivalence-gated, rollback-safe, parallel.

    Usage (from reproduce_best.sh):
      python3 student/flow_optimizer.py --optimize --all \\
        --strategies flows resynth deepsyn mockturtle \\
        --timeout 200 --deepsyn-seconds 90 --seeds 0 42 --workers 6
    """
    if seeds is None:
        seeds = [0, 42]
    if mockturtle_bin is None:
        mockturtle_bin = root / "student" / "mockturtle_opt" / "mockturtle_opt"

    def _one(case: str) -> dict:
        if not (output / f"{case}.aig").is_file():
            return {"case": case, "start": None, "final": None}
        start = _opt_cur_adp(case, output, abc, root)
        best = start
        print(f"[{case}] start ADP={start:,}", flush=True)
        for name in strategies:
            if name == "resynth":
                best = _opt_strat_resynth(case, best, abc, benchmarks, output, logs, root, timeout)
            elif name == "flows":
                best = _opt_strat_flows(case, best, abc, benchmarks, output, root, min(timeout, 120))
            elif name == "deepsyn":
                best = _opt_strat_deepsyn(case, best, abc, benchmarks, output, root, deepsyn_seconds, seeds)
            elif name == "mockturtle":
                best = _opt_strat_mockturtle(case, best, abc, benchmarks, output, logs, root, min(timeout, 240), mockturtle_bin)
        if best < start:
            print(f"[{case}] {start:,} -> {best:,} (-{start - best:,})", flush=True)
        return {"case": case, "start": start, "final": best}

    small = [c for c in cases if c not in _OPT_LARGE_CASES]
    large = [c for c in cases if c in _OPT_LARGE_CASES]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, c): c for c in small}
        for f in as_completed(futs):
            results.append(f.result())
    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = {pool.submit(_one, c): c for c in large}
        for f in as_completed(futs):
            results.append(f.result())

    improved = [r for r in results if r["start"] and r["final"] and r["final"] < r["start"]]
    saved = sum(r["start"] - r["final"] for r in improved)
    print(f"\n=== Block D: {len(improved)}/{len(results)} improved, saved {saved:,} ADP ===")
    for r in sorted(improved, key=lambda x: x["start"] - x["final"], reverse=True):
        print(f"  {r['case']}: {r['start']:,} -> {r['final']:,} (-{r['start']-r['final']:,})")


# ---------------------------------------------------------------------------
# main() dispatch helpers
# ---------------------------------------------------------------------------

def _run_reproduce_modes(args: object, root: Path) -> int | None:
    if args.show_reproduce_recipe:
        print(format_reproduce_recipe())
        return 0
    if args.reproduce_best:
        all_results, summaries = run_reproduce_best(args, root)
        write_results_csv(args.logs / "results.csv", all_results)
        _write_pareto_candidates_from_results(args.logs / "stage_pareto_log.csv", all_results)
        write_summary_csv(args.logs / "summary.csv", summaries)
        if args.report_stats:
            print_report_stats(all_results, summaries)
        return 0
    if getattr(args, "optimize", False):
        import csv as _csv
        cases = selected_cases_from_args(args)
        if getattr(args, "above_ratio", None) is not None:
            ref: dict[str, int] = {}
            p = root / "reference_result.csv"
            if p.exists():
                with p.open(newline="", encoding="utf-8") as fh:
                    for row in _csv.DictReader(fh):
                        ref[row["case"]] = int(row["adp"])
            cases = [c for c in cases
                     if ref.get(c) and (_opt_cur_adp(c, args.output, args.abc, root) or 0) / ref[c] >= args.above_ratio]
        if not cases:
            print("no cases selected")
            return 0
        print(f"[optimize] {len(cases)} cases, strategies={args.strategies}")
        run_block_d_optimize(
            cases=cases,
            abc=args.abc,
            benchmarks=args.benchmarks,
            output=args.output,
            logs=args.logs,
            root=root,
            strategies=args.strategies,
            timeout=args.timeout_per_case,
            deepsyn_seconds=args.optimize_deepsyn_seconds,
            seeds=args.seeds,
            workers=args.workers,
        )
        return 0
    return None


def _run_all_modes(args: object, root: Path) -> int | None:
    # ── reporting / analysis ─────────────────────────────────────────────────
    if args.verify_final:
        run_verify_final(args, root)
        return 0
    if args.analyze_case:
        truth = args.benchmarks / f"{args.analyze_case}.truth"
        table = read_truth(truth)
        print(format_case_analysis(args.analyze_case, table))
        return 0
    if args.classify_case:
        truth = args.benchmarks / f"{args.classify_case}.truth"
        fingerprint = fingerprint_case(truth)
        append_classification_csv(args.logs / "classification.csv", fingerprint)
        print(format_fingerprint(fingerprint))
        exact_rows = exact_matches_for_truth(truth, max_expensive_inputs=args.exact_max_inputs)
        write_exact_function_matches_csv(args.logs / "exact_function_matches.csv", exact_rows)
        print("")
        print(format_exact_matches(exact_rows))
        return 0
    if args.exact_function_report or args.exact_match_all:
        cases = selected_cases_from_args(args)
        exact_rows = []
        for case in cases:
            exact_rows.extend(exact_matches_for_truth(
                args.benchmarks / f"{case}.truth",
                max_expensive_inputs=args.exact_max_inputs,
            ))
        write_exact_function_matches_csv(args.logs / "exact_function_matches.csv", exact_rows)
        print(f"[exact] wrote {args.logs / 'exact_function_matches.csv'}")
        print(f"[exact] matched rows: {len(exact_rows)}")
        return 0
    if args.validate_templates:
        run_validate_templates(args.benchmarks, args.logs, ALL_CASES)
        return 0
    # ── scheduling ───────────────────────────────────────────────────────────
    if args.case_fair_next_optimize:
        run_case_fair_next_optimize(args, root)
        return 0
    # ── refinement ───────────────────────────────────────────────────────────
    if args.type_guided_refine:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] type-guided refine")
            _rows, summary = run_type_guided_refine_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.type_guided_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("type-guided", summaries)
        return 0
    if args.circuit_type_optimize:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] circuit-type optimize")
            _rows, summary = run_circuit_type_optimize_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.circuit_type_max_flows,
                args.circuit_type_max_seeds, args.seed,
            )
            summaries.append(summary)
        print_summary_totals("circuit-type", summaries)
        return 0
    if args.semantic_split_optimize:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] semantic split optimize")
            _rows, summary = run_semantic_split_optimize_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.semantic_max_splits,
                args.semantic_max_flows, args.seed,
            )
            summaries.append(summary)
        print_summary_totals("semantic-split", summaries)
        return 0
    if args.objective_guided_refine:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] objective-guided refine")
            _rows, summary = run_objective_guided_refine_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.objective_max_per_family,
            )
            summaries.append(summary)
        print_summary_totals("objective-guided", summaries)
        return 0
    if args.micro_guided_refine:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] micro-guided refine")
            _rows, summary = run_micro_guided_refine_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.micro_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("micro-guided", summaries)
        return 0
    if args.gia_canonical_converge:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] GIA canonical convergence")
            _rows, summary = run_gia_canonical_convergence_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.gia_canonical_max_passes,
            )
            summaries.append(summary)
        print_summary_totals("gia-canonical", summaries)
        return 0
    if args.area_first_refine:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] area-first refine")
            _rows, summary = run_area_first_refine_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root,
            )
            summaries.append(summary)
        print_summary_totals("area-first", summaries)
        return 0
    if args.small_case_refine:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] small-case refine")
            _rows, summary = run_small_case_refine_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.small_max_flows,
                args.small_area_threshold, args.small_adp_threshold,
            )
            summaries.append(summary)
        print_summary_totals("small-case", summaries)
        return 0
    # ── rescue / structural exploration ──────────────────────────────────────
    if args.exact_npn_rescue:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] exact/NPN rescue")
            _rows, summary = run_exact_npn_rescue_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.npn_max_support, args.npn_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("exact-npn", summaries)
        return 0
    if args.transduction_rescue:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] transduction rescue")
            _rows, summary = run_transduction_rescue_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.transduction_budget, args.seed,
            )
            summaries.append(summary)
        print_summary_totals("transduction", summaries)
        return 0
    if args.complement_rescue:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] complement rescue")
            _rows, summary = run_complement_rescue_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.seed, args.complement_budget, not args.no_bdd,
            )
            summaries.append(summary)
        print_summary_totals("complement", summaries)
        return 0
    if args.specialized_generators or args.specialized_generate:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] specialized structural generators")
            _rows, summary = run_specialized_generators_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.exact_max_inputs,
            )
            summaries.append(summary)
        print_summary_totals("specialized", summaries)
        return 0
    if args.ttopt_structural:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] ttopt structural")
            _rows, summary = run_ttopt_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root,
            )
            summaries.append(summary)
        print_summary_totals("ttopt-structural", summaries)
        return 0
    if args.deepsyn_structural:
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] bounded deepsyn structural")
            _rows, summary = run_deepsyn_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.seed,
                args.deepsyn_iterations, args.deepsyn_seconds,
            )
            summaries.append(summary)
        print_summary_totals("deepsyn-structural", summaries)
        return 0
    if args.long_large_structural:
        cases = selected_cases_from_args(args)
        if not args.case and not args.range:
            selected_ll: list[str] = []
            for case in cases:
                table = read_truth(args.benchmarks / f"{case}.truth")
                area, _delay, adp = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)
                if should_run_long_large_structural(table, area, adp, args.long_large_min_area, args.long_large_min_adp):
                    selected_ll.append(case)
            cases = selected_ll
        summaries = []
        for case in cases:
            print(f"[{case}] long large alternate-seed structural")
            summary = run_long_large_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.seed,
                args.long_large_seconds, args.ttopt_seed_rounds,
            )
            summaries.append(summary)
        print_summary_totals("long-large-structural", summaries)
        return 0
    if args.compact_vector_pareto_probe:
        cases = selected_cases_from_args(args)
        summaries = run_adaptive_compact_vector_pareto(
            cases, args.abc, args.benchmarks, args.output, args.logs, root, args.seed,
            force_cases=bool(args.case or args.range),
        )
        print_summary_totals("compact-vector-pareto", summaries)
        return 0
    if args.pareto_area_structural or args.compact_low_degree_pareto:
        cases = selected_cases_from_args(args)
        if not args.case and not args.range:
            selected_pa: list[str] = []
            for case in cases:
                table = read_truth(args.benchmarks / f"{case}.truth")
                area, _delay, _adp = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)
                eligible = (
                    should_run_compact_pareto_structural(table, area)
                    if args.compact_low_degree_pareto
                    else should_run_pareto_area_structural(table, area)
                )
                if eligible:
                    selected_pa.append(case)
            cases = selected_pa
        summaries = []
        for case in cases:
            label = "compact low-degree Pareto structural" if args.compact_low_degree_pareto else "area-Pareto structural"
            print(f"[{case}] {label}")
            _rows, summary = run_pareto_area_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.seed, args.pareto_area_seconds,
            )
            summaries.append(summary)
        print_summary_totals(
            "compact-low-degree-pareto" if args.compact_low_degree_pareto else "pareto-area-structural",
            summaries,
        )
        return 0
    if args.hybrid_structural:
        yosys_bin, error = resolve_yosys_binary(args.yosys_bin)
        if yosys_bin is None:
            print(f"[hybrid-structural] unavailable, skipping: {error}")
            return 0
        mockturtle_bin: Path | None = None
        mockturtle_ok, mockturtle_error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)
        if mockturtle_ok:
            mockturtle_bin = args.mockturtle_structural_bin
        else:
            print(f"[hybrid-structural] mockturtle unavailable; running Yosys-only candidates: {mockturtle_error}")
        cases = selected_cases_from_args(args)
        summaries = []
        for case in cases:
            print(f"[{case}] Yosys/mockturtle hybrid structural")
            _rows, summary = run_hybrid_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, yosys_bin, mockturtle_bin,
                args.mockturtle_workers, args.mockturtle_max_modes, args.exact_max_inputs,
            )
            summaries.append(summary)
        print_summary_totals("hybrid-structural", summaries)
        return 0
    if args.mockturtle_structural or args.mockturtle_case:
        ok, error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)
        if not ok:
            print(f"[mockturtle-structural] unavailable, skipping: {error}")
            return 0
        cases = selected_cases_from_args(args, args.mockturtle_case)
        for case in cases:
            print(f"[{case}] mockturtle structural")
            run_mockturtle_structural_case(
                case, args.abc, args.benchmarks, args.output, args.logs,
                args.timeout_per_case, root, args.mockturtle_structural_bin,
                args.mode, args.mockturtle_max_modes, args.exact_max_inputs,
            )
        return 0
    return None


def main() -> int:
    global _ACTIVE_CASE_FILTER
    args = parse_args()
    root = Path.cwd()

    if getattr(args, "cases", None):
        _ACTIVE_CASE_FILTER = set(args.cases)

    for _handler in (_run_reproduce_modes, _run_all_modes):
        result = _handler(args, root)
        if result is not None:
            return result

    print("No mode selected. Use --reproduce-best, --optimize, --classify-case, or another flag.", file=__import__('sys').stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
