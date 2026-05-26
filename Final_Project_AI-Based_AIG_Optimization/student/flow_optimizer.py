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
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from boolean_fingerprint import append_classification_csv, fingerprint_case, format_fingerprint
from exact_function_recognition import (
    ExactFunctionMatch,
    exact_matches_for_truth,
    format_exact_matches,
    write_exact_function_matches_csv,
)


PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")


@dataclass(frozen=True)
class TruthTable:
    outputs: list[bytearray]
    num_inputs: int
    num_outputs: int
    num_minterms: int
    on_count: int
    off_count: int
    density: float
    influences: list[float]
    active_vars: list[int]
    shannon_scores: list[float]


@dataclass(frozen=True)
class InitialCandidate:
    method: str
    source_kind: str
    source_path: Path | None


@dataclass(frozen=True)
class PostFlow:
    name: str
    commands: str


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


POST_FLOWS = [
    PostFlow("identity", ""),
    PostFlow("area_dc2", "dc2; rewrite -z; refactor -z; balance"),
    PostFlow("delay_balance", "balance; rewrite; balance; refactor; balance"),
    PostFlow("adp_balanced", "rewrite; refactor; dc2; rewrite -z; refactor -z; balance"),
    PostFlow("drw_drf", "drw; drf; dc2; balance"),
    PostFlow("llm_mix_1", "rewrite -z; refactor -z; dc2; rewrite -z; balance"),
    PostFlow("llm_mix_2", "dc2; drw; drf; rewrite; dc2; balance"),
]

POLISH_FLOWS = [
    PostFlow("polish_cleanup_deep", "balance; rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_dch_if6", "dch; if -K 6; strash; dc2; balance"),
    PostFlow("polish_fraig_dc2", "fraig; dc2; rewrite -z; balance"),
    PostFlow("polish_resub6", "resub -K 6; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dc2_dch_if6", "dc2; dch; if -K 6; strash; rewrite -z; dc2; balance"),
    PostFlow("polish_dch_if5", "dch; if -K 5; strash; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if8", "dch; if -K 8; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if9", "dch; if -K 9; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_rw_rf_loop", "rewrite; rewrite -z; refactor; refactor -z; balance; dc2; balance"),
    PostFlow("polish_resub6_f1", "resub -K 6 -F 1; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_resub6_f2", "resub -K 6 -F 2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_resub8_n2", "resub -K 8 -N 2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_resub6_n3", "resub -K 6 -N 3; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_resub8_dc2", "resub -K 8; dc2; resub -K 6; balance"),
    PostFlow("polish_dc2_resub8_dch", "dc2; resub -K 8; dch; if -K 6; strash; dc2; balance"),
    PostFlow("polish_delay_if10", "dch; if -K 10; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if11", "dch; if -K 11; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if12", "dch; if -K 12; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if13", "dch; if -K 13; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_dch_if14", "dch; if -K 14; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_orchestrate_k12n2f1", "orchestrate -K 12 -N 2 -F 1; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_gia_resyn3rs", "&get; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_dchoice_ifraig", "dchoice; ifraig; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("polish_gia_resyn3_mfs_compress", "&get; &resyn3; &mfs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_gia_mfs_compress", "&get; &mfs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_gia_dc2", "&get; &dc2; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("polish_gia_dch", "&get; &dch; &put; balance; rewrite -z; refactor -z; dc2; balance"),
]

SWEEP_FLOWS = [
    PostFlow("sweep_dc2_rw", "dc2; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_fraig_dc2", "fraig; dc2; rewrite -z; balance"),
    PostFlow("sweep_lowk_if4", "dch; if -K 4; strash; dc2; balance"),
    PostFlow("sweep_resub6_f1", "resub -K 6 -F 1; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_resub8_n2", "resub -K 8 -N 2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_resub6_n3", "resub -K 6 -N 3; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_dch_if8", "dch; if -K 8; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_dch_if12", "dch; if -K 12; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_gia_resyn3rs", "&get; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("sweep_gia_dc2", "&get; &dc2; &put; balance; rewrite -z; refactor -z; dc2; balance"),
]

MOCKTURTLE_MODES = ["light", "refactor", "balance"]
MOCKTURTLE_POST_FLOW = PostFlow("mockturtle_abc_cleanup", "dc2; rewrite -z; refactor -z; balance")
STRUCTURAL_MOCKTURTLE_MODES = [
    "xag_xor_heavy",
    "mig_majority",
    "xmg_arithmetic",
    "aig_resub",
    "functional_reduction",
    "roundtrip_xag",
    "roundtrip_mig",
    "roundtrip_xmg",
    "cut4_aig_xag_npn",
    "cut5_aig_xag_npn_depth",
    "dc_aig_rewrite",
    "xag_area_minmc",
    "mig_akers_cut4",
    "xmg_mixed_resub",
]
MOCKTURTLE_STRUCTURAL_POLISH_FLOWS = [
    PostFlow("mt_dc2_balance", "strash; dc2; balance"),
    PostFlow("mt_rw_rf_dc2", "strash; rewrite -z; refactor -z; dc2"),
    PostFlow("mt_balance_rw_balance", "strash; balance; rewrite; balance"),
]

SPECIALIZED_GENERATOR_FLOWS = [
    PostFlow("specialized_identity", ""),
    PostFlow("specialized_adp", "strash; rewrite; refactor; dc2; rewrite -z; refactor -z; balance"),
    PostFlow("specialized_area", "strash; dc2; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("specialized_delay", "strash; balance; rewrite; balance; refactor; balance"),
]

TTOPT_STRUCTURAL_POLISH_FLOWS = [
    PostFlow("ttopt_adp", "strash; balance; rewrite; refactor; dc2; balance"),
    PostFlow("ttopt_area", "strash; dc2; balance"),
]

EXACT_NPN_RESCUE_FLOWS = [
    PostFlow("npn_identity", ""),
    PostFlow("npn_area", "strash; collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("npn_cut", "strash; dch; if -K 5; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("npn_resub", "strash; resub -K 4; balance; rewrite -z; refactor -z; dc2; balance"),
]

TRANSDUCTION_REDUCTION_FLOWS = [
    PostFlow("trans_fraig_dc2", "strash; fraig; dc2; balance"),
    PostFlow("trans_rw_rf_dc2", "strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("trans_resub_rewrite", "strash; resub -K 6; rewrite -z; refactor -z; dc2; balance"),
]

TYPE_GUIDED_FLOW_LIBRARY = {
    "xor_affine": [
        PostFlow("type_xor_balance_rewrite", "balance; rewrite -z; balance; dc2; balance"),
        PostFlow("type_xor_gia_resyn", "&get; &resyn3rs; &compress3rs; &put; balance; rewrite -z; dc2; balance"),
        PostFlow("type_xor_resub6", "resub -K 6 -F 1; balance; rewrite -z; dc2; balance"),
    ],
    "threshold_majority": [
        PostFlow("type_maj_lowk_if4", "dch; if -K 4; strash; rewrite -z; dc2; balance"),
        PostFlow("type_maj_lowk_if5", "dch; if -K 5; strash; rewrite -z; refactor -z; balance"),
        PostFlow("type_maj_gia_dch", "&get; &dch; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
    "mux_shannon": [
        PostFlow("type_mux_dch_if8", "dch; if -K 8; strash; dc2; balance; rewrite -z; balance"),
        PostFlow("type_mux_dch_if12", "dch; if -K 12; strash; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("type_mux_dchoice_ifraig", "dchoice; ifraig; dc2; balance; rewrite -z; refactor -z; balance"),
    ],
    "arithmetic": [
        PostFlow("type_arith_gia_mfs", "&get; &mfs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_arith_gia_resyn_mfs", "&get; &resyn3; &mfs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_arith_dch_if14", "dch; if -K 14; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    ],
    "small_template": [
        PostFlow("type_small_rewrite_refactor", "rewrite; rewrite -z; refactor; refactor -z; balance; dc2; balance"),
        PostFlow("type_small_resub4", "resub -K 4; balance; rewrite -z; refactor -z; balance"),
        PostFlow("type_small_fraig", "fraig; dc2; rewrite -z; balance"),
    ],
    "general": [
        PostFlow("type_general_dc2", "dc2; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_general_dchoice", "dchoice; ifraig; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("type_general_gia_sopb", "&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_general_gia_dsd", "&get; &dsd; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_general_gia_b_delay", "&get; &b -d -s; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_general_gia_deep", "&get; &resyn3; &mfs; &compress3rs; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_general_gia_dc2", "&get; &dc2; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
}

TYPE_GUIDED_SHARED_FLOWS = [
    PostFlow("type_shared_delay_if10", "dch; if -K 10; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("type_shared_area_orchestrate", "orchestrate -K 12 -N 2 -F 1; balance; rewrite -z; refactor -z; dc2; balance"),
]

OBJECTIVE_GUIDED_FLOW_LIBRARY = {
    "area": [
        PostFlow("obj_area_dc2_loop", "dc2; rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; balance"),
        PostFlow("obj_area_gia_dc2", "&get; &dc2; &compress3rs; &put; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("obj_area_fraig", "fraig; dc2; rewrite -z; refactor -z; balance"),
    ],
    "delay": [
        PostFlow("obj_delay_if6", "dch; if -K 6; strash; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("obj_delay_if10", "dch; if -K 10; strash; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("obj_delay_gia_b", "&get; &b -d -s; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("obj_delay_sopb", "&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
    "balanced": [
        PostFlow("obj_balanced_dchoice", "dchoice; ifraig; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("obj_balanced_orchestrate", "orchestrate -K 12 -N 2 -F 1; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("obj_balanced_gia_deep", "&get; &resyn3; &mfs; &compress3rs; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
}

MICRO_GUIDED_FLOWS = [
    PostFlow("micro_resub4", "resub -K 4; balance; rewrite -z; refactor -z; balance"),
    PostFlow("micro_if3", "dch; if -K 3; strash; dc2; balance"),
    PostFlow("micro_renode", "renode; strash; dc2; rewrite -z; refactor -z; balance"),
]

MICRO_COLLAPSE_FLOWS = [
    PostFlow("micro_collapse_sop", "collapse; sop; fx; strash; dc2; balance"),
]

SMALL_CASE_FLOWS = [
    PostFlow("small_if4", "dch; if -K 4; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("small_fx_dc2", "collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("small_fraig_dc2", "fraig; dc2; rewrite -z; refactor -z; balance"),
    PostFlow("small_if5", "dch; if -K 5; strash; dc2; rewrite -z; refactor -z; balance"),
    PostFlow("small_gia_sopb", "&get; &sopb -C 8 -R 1; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("small_renode_fx", "renode; collapse; sop; fx; strash; dc2; balance"),
    PostFlow("small_resub3", "resub -K 3; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("small_gia_dsd", "&get; &dsd; &compress2rs; &put; rewrite -z; refactor -z; dc2; balance"),
]

GA_COMMAND_POOL = [
    "balance",
    "rewrite",
    "rewrite -z",
    "refactor",
    "refactor -z",
    "dc2",
    "drw",
    "drf",
]

TOP_FLOW_NAMES = [
    "llm_mix_1",
    "llm_mix_2",
    "area_dc2",
    "adp_balanced",
    "drw_drf",
]

ALL_CASES = [f"ex{i}" for i in range(200, 300)]
REPRODUCE_MAIN_MAX_CANDIDATES = 48
REPRODUCE_FOCUSED_MAX_CANDIDATES = 80
REPRODUCE_SEED = 42
REPRODUCE_ARITHMETIC_RANGES = [("ex255", "ex259"), ("ex260", "ex264"), ("ex270", "ex274")]
REPRODUCE_DIVIDER_RANGE = ("ex265", "ex269")
REPRODUCE_SQRT_RANGE = ("ex275", "ex279")
REPRODUCE_RESCUE_CASES = ["ex252"]
REPRODUCE_RESCUE_MAX_CANDIDATES = 120
REPRODUCE_RESCUE_SEED = 99
REPRODUCE_POLISH_PASSES = 30
REPRODUCE_SWEEP_PASSES = 3
REPRODUCE_FINAL_SWEEP_PASSES = 3
REPRODUCE_FRONT_RANGE = ("ex200", "ex207")
REPRODUCE_MOCKTURTLE_STRUCTURAL_TIMEOUT = 45
REPRODUCE_FINAL_ADVANCED_MOCKTURTLE_TIMEOUT = 90
REPRODUCE_TYPE_GUIDED_TIMEOUT = 180
REPRODUCE_TYPE_GUIDED_MAX_FLOWS = 8
REPRODUCE_OBJECTIVE_GUIDED_TIMEOUT = 180
REPRODUCE_OBJECTIVE_MAX_PER_FAMILY = 3
REPRODUCE_MICRO_GUIDED_TIMEOUT = 90
REPRODUCE_MICRO_MAX_FLOWS = 4
REPRODUCE_MICRO_CONVERGENCE_PASSES = 6
REPRODUCE_MICRO_CONVERGENCE_TIMEOUT = 20
REPRODUCE_SMALL_CASE_TIMEOUT = 35
REPRODUCE_SMALL_CASE_MAX_FLOWS = 5
REPRODUCE_SMALL_CASE_AREA_THRESHOLD = 2500
REPRODUCE_SMALL_CASE_ADP_THRESHOLD = 50000
REPRODUCE_TTOPT_STRUCTURAL_TIMEOUT = 150
REPRODUCE_RECIPE = [
    (
        "1",
        "all_case_hybrid_synthesis",
        "Run the hybrid initial generators and fixed ABC post-flow portfolio on every case.",
        f"all cases, max_candidates={REPRODUCE_MAIN_MAX_CANDIDATES}, seed={REPRODUCE_SEED}",
    ),
    (
        "2-4",
        "arithmetic_template_ranges",
        "Revisit exact multiplier/square arithmetic ranges with deterministic template-heavy candidates.",
        ", ".join(f"{start}-{end}" for start, end in REPRODUCE_ARITHMETIC_RANGES),
    ),
    (
        "5",
        "divider_template_range",
        "Revisit exact unsigned divider quotient candidates.",
        f"{REPRODUCE_DIVIDER_RANGE[0]}-{REPRODUCE_DIVIDER_RANGE[1]}",
    ),
    (
        "6",
        "sqrt_template_range",
        "Revisit exact integer square-root candidates.",
        f"{REPRODUCE_SQRT_RANGE[0]}-{REPRODUCE_SQRT_RANGE[1]}",
    ),
    (
        "7",
        "diagnosis_rescue",
        "Run bounded rescue on known diagnosis-sensitive cases using complement and history-guided GA.",
        ", ".join(REPRODUCE_RESCUE_CASES),
    ),
    (
        "8",
        "equivalence_checked_polish",
        "Run fixed deterministic ABC cleanup packages on existing equivalent outputs.",
        f"{REPRODUCE_POLISH_PASSES} passes, stops early on convergence",
    ),
    (
        "9",
        "all_case_refinement_package",
        "Run a fixed all-case ABC/GIA refinement package.  This is deterministic, not a random sweep.",
        f"{REPRODUCE_SWEEP_PASSES} passes, stops early on convergence",
    ),
    (
        "10",
        "final_all_case_refinement_package",
        "Run the final fixed all-case refinement package for convergence.",
        f"{REPRODUCE_FINAL_SWEEP_PASSES} passes, stops early on convergence",
    ),
    (
        "11",
        "fingerprint_guided_mockturtle_structural",
        "Select at most two mockturtle structural modes per case from Boolean fingerprints, then ABC-polish and verify.",
        f"timeout_per_case={REPRODUCE_MOCKTURTLE_STRUCTURAL_TIMEOUT}",
    ),
    (
        "12",
        "type_guided_final_refinement",
        "Classify every case again and run a fixed circuit-family-specific ABC refinement package.",
        f"max_flows={REPRODUCE_TYPE_GUIDED_MAX_FLOWS}, timeout_per_case={REPRODUCE_TYPE_GUIDED_TIMEOUT}",
    ),
    (
        "13",
        "objective_guided_area_delay_refinement",
        "Run fixed area-first, delay-first, and balanced packages on every case and select by ADP.",
        f"max_per_family={REPRODUCE_OBJECTIVE_MAX_PER_FAMILY}, timeout_per_case={REPRODUCE_OBJECTIVE_GUIDED_TIMEOUT}",
    ),
    (
        "14",
        "micro_guided_per_case_refinement",
        "Run low-cost small-circuit refinement flows on every case, including collapse/factorization for compact functions.",
        f"max_flows={REPRODUCE_MICRO_MAX_FLOWS}, timeout_per_case={REPRODUCE_MICRO_GUIDED_TIMEOUT}",
    ),
    (
        "15",
        "small_case_targeted_refinement",
        "Run the small-case-only package for compact or low-ADP functions so small benchmarks are not starved.",
        (
            f"max_flows={REPRODUCE_SMALL_CASE_MAX_FLOWS}, timeout_per_case={REPRODUCE_SMALL_CASE_TIMEOUT}, "
            f"area_threshold={REPRODUCE_SMALL_CASE_AREA_THRESHOLD}, adp_threshold={REPRODUCE_SMALL_CASE_ADP_THRESHOLD}"
        ),
    ),
    (
        "16",
        "final_advanced_mockturtle_structural",
        "Re-run fingerprint-selected advanced mockturtle structural modes on the final refined outputs.",
        f"timeout_per_case={REPRODUCE_FINAL_ADVANCED_MOCKTURTLE_TIMEOUT}",
    ),
    (
        "17",
        "truth_table_structural_resynthesis",
        "Build shared BDD/MUX structures with ABC ttopt, then apply deterministic level-preserving transduction.",
        f"all cases, timeout_per_case={REPRODUCE_TTOPT_STRUCTURAL_TIMEOUT}, fixed output groups only",
    ),
    (
        "18",
        "micro_guided_fixed_point_convergence",
        "Repeat the deterministic low-cost resubstitution/remapping package after all structural generators have settled.",
        (
            f"max_passes={REPRODUCE_MICRO_CONVERGENCE_PASSES}, "
            f"max_flows={REPRODUCE_MICRO_MAX_FLOWS}, "
            f"timeout_per_case={REPRODUCE_MICRO_CONVERGENCE_TIMEOUT}, stops early on convergence"
        ),
    ),
]


def split_commands(commands: str) -> list[str]:
    return [part.strip() for part in commands.split(";") if part.strip()]


def join_commands(commands: list[str]) -> str:
    return "; ".join(commands)


def mutate_flow(commands: list[str], rng: random.Random) -> list[str]:
    child = commands[:]
    if not child:
        child = [rng.choice(GA_COMMAND_POOL)]
    operation = rng.choice(["insert", "delete", "replace", "swap"])
    if operation == "insert" and len(child) < 8:
        child.insert(rng.randrange(len(child) + 1), rng.choice(GA_COMMAND_POOL))
    elif operation == "delete" and len(child) > 2:
        del child[rng.randrange(len(child))]
    elif operation == "replace":
        child[rng.randrange(len(child))] = rng.choice(GA_COMMAND_POOL)
    elif operation == "swap" and len(child) > 1:
        pos = rng.randrange(len(child) - 1)
        child[pos], child[pos + 1] = child[pos + 1], child[pos]
    if child[-1] != "balance":
        child.append("balance")
    return child[:8]


def crossover_flow(left: list[str], right: list[str], rng: random.Random) -> list[str]:
    if not left:
        return right[:]
    if not right:
        return left[:]
    left_cut = rng.randrange(1, len(left) + 1)
    right_cut = rng.randrange(0, len(right))
    child = left[:left_cut] + right[right_cut:]
    if len(child) > 8:
        child = child[:8]
    if child and child[-1] != "balance":
        child.append("balance")
    return child or [rng.choice(GA_COMMAND_POOL), "balance"]


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


def make_ga_flows(case: str, seed: int, count: int) -> list[PostFlow]:
    rng = random.Random(f"{seed}:{case}:ga")
    parents = [split_commands(flow.commands) for flow in POST_FLOWS if flow.commands]
    flows: list[PostFlow] = []
    seen = {flow.commands for flow in POST_FLOWS}
    attempts = 0
    while len(flows) < count and attempts < count * 40:
        attempts += 1
        if rng.random() < 0.35 and len(parents) >= 2:
            left, right = rng.sample(parents, 2)
            child = crossover_flow(left, right, rng)
        else:
            child = mutate_flow(rng.choice(parents), rng)
        command_text = join_commands(child)
        if command_text in seen:
            continue
        seen.add(command_text)
        parents.append(child)
        flows.append(PostFlow(f"ga_{len(flows):02d}", command_text))
    return flows


def abc_path(path: Path, root: Path) -> str:
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
        raise RuntimeError(f"Cannot execute ABC at {abc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"ABC exited with {result.returncode}")
    return result.stdout


def binary_entropy(value: float) -> float:
    if value <= 0.0 or value >= 1.0:
        return 0.0
    return -(value * math.log2(value) + (1.0 - value) * math.log2(1.0 - value))


def read_truth(path: Path) -> TruthTable:
    text = path.read_text(encoding="ascii", errors="ignore")
    groups: list[bytearray] = []
    current: list[int] = []
    for char in text:
        if char in "01":
            current.append(1 if char == "1" else 0)
        elif current:
            groups.append(bytearray(current))
            current = []
    if current:
        groups.append(bytearray(current))
    if not groups:
        raise ValueError(f"no truth-table bits found in {path}")

    lengths = {len(group) for group in groups}
    if len(lengths) != 1:
        raise ValueError(f"inconsistent truth-table group lengths: {sorted(lengths)}")
    num_minterms = lengths.pop()
    if num_minterms & (num_minterms - 1):
        raise ValueError(f"truth-table length is not a power of two: {path}")

    # ABC read_truth uses most-significant truth bit first.  For custom
    # construction, reverse each output into canonical assignment order where
    # index 0 is all-zero inputs.
    outputs = [bytearray(reversed(group)) for group in groups]
    num_inputs = int(math.log2(num_minterms))
    num_outputs = len(outputs)
    on_count = sum(sum(bits) for bits in outputs)
    total = num_outputs * num_minterms

    influences: list[float] = []
    shannon_scores: list[float] = []
    active_vars: list[int] = []
    for var in range(num_inputs):
        bit_pos = num_inputs - 1 - var
        step = 1 << bit_pos
        period = step << 1
        diff = 0
        ones0 = 0
        ones1 = 0
        for bits in outputs:
            for base in range(0, num_minterms, period):
                for offset in range(step):
                    low = bits[base + offset]
                    high = bits[base + offset + step]
                    ones0 += low
                    ones1 += high
                    diff += low ^ high
        pair_count = (num_minterms // 2) * num_outputs
        influence = diff / pair_count
        density0 = ones0 / pair_count
        density1 = ones1 / pair_count
        balance = 1.0 - abs(density0 - density1)
        score = 0.55 * influence + 0.25 * balance + 0.20 * (binary_entropy(density0) + binary_entropy(density1)) / 2.0
        influences.append(influence)
        shannon_scores.append(score)
        if influence > 0.0:
            active_vars.append(var)

    return TruthTable(
        outputs=outputs,
        num_inputs=num_inputs,
        num_outputs=num_outputs,
        num_minterms=num_minterms,
        on_count=on_count,
        off_count=total - on_count,
        density=on_count / total,
        influences=influences,
        active_vars=active_vars,
        shannon_scores=shannon_scores,
    )


def blif_header(model: str, table: TruthTable) -> list[str]:
    # ABC compares AIG inputs by CI order.  read_truth creates the lowest-index
    # truth variable last in BLIF-style input order, so emit inputs reversed.
    inputs = " ".join(f"x{i}" for i in reversed(range(table.num_inputs)))
    outputs = " ".join(f"y{i}" for i in range(table.num_outputs))
    return [f".model {model}", f".inputs {inputs}", f".outputs {outputs}"]


def minterm_cube(index: int, table: TruthTable) -> tuple[int, ...]:
    return tuple(1 if (index >> (table.num_inputs - 1 - var)) & 1 else 0 for var in table.active_vars)


def minterm_cube_for_support(index: int, table: TruthTable, support: list[int]) -> tuple[int, ...]:
    return tuple(1 if (index >> (table.num_inputs - 1 - var)) & 1 else 0 for var in support)


def collect_cubes(table: TruthTable, output_index: int, value: int, limit: int) -> list[tuple[int, ...]] | None:
    cubes: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for index, bit in enumerate(table.outputs[output_index]):
        if bit != value:
            continue
        cube = minterm_cube(index, table)
        if cube in seen:
            continue
        seen.add(cube)
        cubes.append(cube)
        if len(cubes) > limit:
            return None
    return cubes


def output_support(table: TruthTable, output_index: int) -> list[int]:
    bits = table.outputs[output_index]
    support: list[int] = []
    for var in range(table.num_inputs):
        differs = False
        for index in range(table.num_minterms):
            other = index ^ (1 << (table.num_inputs - 1 - var))
            if index < other and bits[index] != bits[other]:
                differs = True
                break
        if differs:
            support.append(var)
    return support


def collect_support_cubes(
    table: TruthTable,
    output_index: int,
    support: list[int],
    value: int,
    limit: int,
) -> list[tuple[int, ...]] | None:
    cubes: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for index, bit in enumerate(table.outputs[output_index]):
        if bit != value:
            continue
        cube = minterm_cube_for_support(index, table, support)
        if cube in seen:
            continue
        seen.add(cube)
        cubes.append(cube)
        if len(cubes) > limit:
            return None
    return cubes


def collect_all_output_covers(table: TruthTable, value: int, limit_per_output: int) -> list[list[tuple[int, ...]]] | None:
    covers: list[list[tuple[int, ...]]] = []
    for output_index in range(table.num_outputs):
        cubes = collect_cubes(table, output_index, value, limit_per_output)
        if cubes is None:
            return None
        covers.append(cubes)
    return covers


def write_cover_blif(
    path: Path,
    model: str,
    table: TruthTable,
    covers: list[list[tuple[int, ...]]],
    invert: bool,
) -> None:
    lines = blif_header(model, table)
    active_names = [f"x{i}" for i in table.active_vars]
    for output_index, cubes in enumerate(covers):
        out = f"y{output_index}"
        cover_signal = f"cover{output_index}" if invert else out
        if active_names:
            lines.append(f".names {' '.join(active_names)} {cover_signal}")
            for cube in cubes:
                lines.append("".join("1" if bit else "0" for bit in cube) + " 1")
        else:
            lines.append(f".names {cover_signal}")
            if cubes:
                lines.append("1")
        if invert:
            lines.append(f".names {cover_signal} {out}")
            lines.append("0 1")
    lines.append(".end")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


class BlifBuilder:
    def __init__(self, table: TruthTable, model: str):
        self.table = table
        self.lines = blif_header(model, table)
        self.counter = 0
        self.const0 = self.new_name()
        self.const1 = self.new_name()
        self.lines.append(f".names {self.const0}")
        self.lines.append(f".names {self.const1}")
        self.lines.append("1")

    def new_name(self) -> str:
        name = f"n{self.counter}"
        self.counter += 1
        return name

    def emit_not(self, signal: str) -> str:
        out = self.new_name()
        self.lines.append(f".names {signal} {out}")
        self.lines.append("0 1")
        return out

    def emit_and(self, left: str, right: str) -> str:
        if left == self.const0 or right == self.const0:
            return self.const0
        if left == self.const1:
            return right
        if right == self.const1:
            return left
        out = self.new_name()
        self.lines.append(f".names {left} {right} {out}")
        self.lines.append("11 1")
        return out

    def emit_or(self, left: str, right: str) -> str:
        if left == self.const1 or right == self.const1:
            return self.const1
        if left == self.const0:
            return right
        if right == self.const0:
            return left
        out = self.new_name()
        self.lines.append(f".names {left} {right} {out}")
        self.lines.append("1- 1")
        self.lines.append("-1 1")
        return out

    def emit_xor(self, left: str, right: str) -> str:
        if left == self.const0:
            return right
        if right == self.const0:
            return left
        if left == self.const1:
            return self.emit_not(right)
        if right == self.const1:
            return self.emit_not(left)
        if left == right:
            return self.const0
        out = self.new_name()
        self.lines.append(f".names {left} {right} {out}")
        self.lines.append("01 1")
        self.lines.append("10 1")
        return out

    def emit_half_adder(self, left: str, right: str) -> tuple[str, str]:
        return self.emit_xor(left, right), self.emit_and(left, right)

    def emit_full_adder(self, left: str, middle: str, right: str) -> tuple[str, str]:
        partial = self.emit_xor(left, middle)
        summation = self.emit_xor(partial, right)
        carry = self.emit_or(
            self.emit_or(self.emit_and(left, middle), self.emit_and(left, right)),
            self.emit_and(middle, right),
        )
        return summation, carry

    def emit_mux(self, sel_var: int, low: str, high: str) -> str:
        if low == high:
            return low
        out = self.new_name()
        self.lines.append(f".names x{sel_var} {low} {high} {out}")
        self.lines.append("01- 1")
        self.lines.append("1-1 1")
        return out

    def emit_mux_signal(self, select: str, low: str, high: str) -> str:
        if low == high:
            return low
        if select == self.const0:
            return low
        if select == self.const1:
            return high
        out = self.new_name()
        self.lines.append(f".names {select} {low} {high} {out}")
        self.lines.append("01- 1")
        self.lines.append("1-1 1")
        return out

    def finish(self, signals: list[str], path: Path) -> None:
        for output_index, signal in enumerate(signals):
            self.lines.append(f".names {signal} y{output_index}")
            self.lines.append("1 1")
        self.lines.append(".end")
        path.write_text("\n".join(self.lines) + "\n", encoding="ascii")


def emit_cube(builder: BlifBuilder, active_vars: list[int], cube: tuple[int, ...]) -> str:
    signal = builder.const1
    for var, bit in zip(active_vars, cube):
        literal = f"x{var}" if bit else builder.emit_not(f"x{var}")
        signal = builder.emit_and(signal, literal)
    return signal


def emit_or_tree(builder: BlifBuilder, signals: list[str]) -> str:
    if not signals:
        return builder.const0
    while len(signals) > 1:
        merged: list[str] = []
        for index in range(0, len(signals), 2):
            if index + 1 < len(signals):
                merged.append(builder.emit_or(signals[index], signals[index + 1]))
            else:
                merged.append(signals[index])
        signals = merged
    return signals[0]


def factor_cover(builder: BlifBuilder, active_vars: list[int], cubes: list[tuple[int, ...]]) -> str:
    active_count = len(active_vars)

    def factor(subcubes: list[tuple[int, ...]], available: tuple[int, ...]) -> str:
        if not subcubes:
            return builder.const0
        if any(all(bit < 0 for bit in cube) for cube in subcubes):
            return builder.const1
        if not available or len(subcubes) <= 3:
            return emit_or_tree(builder, [emit_cube(builder, active_vars, cube) for cube in subcubes])

        best_pos = -1
        best_value = -1
        best_count = 1
        for pos in available:
            for value in (0, 1):
                count = sum(1 for cube in subcubes if cube[pos] == value)
                if count > best_count:
                    best_pos, best_value, best_count = pos, value, count
        if best_pos < 0 or best_count == len(subcubes):
            return emit_or_tree(builder, [emit_cube(builder, active_vars, cube) for cube in subcubes])

        with_lit: list[tuple[int, ...]] = []
        without_lit: list[tuple[int, ...]] = []
        for cube in subcubes:
            if cube[best_pos] == best_value:
                stripped = list(cube)
                stripped[best_pos] = -1
                with_lit.append(tuple(stripped))
            else:
                without_lit.append(cube)
        literal = f"x{active_vars[best_pos]}"
        if best_value == 0:
            literal = builder.emit_not(literal)
        next_available = tuple(pos for pos in available if pos != best_pos)
        factored = builder.emit_and(literal, factor(with_lit, next_available))
        rest = factor(without_lit, available)
        return builder.emit_or(factored, rest)

    return factor(cubes, tuple(range(active_count)))


def write_small_support_exact_blif(
    path: Path,
    model: str,
    table: TruthTable,
    max_support: int,
) -> tuple[bool, int, str]:
    if len(table.active_vars) <= max_support:
        covers = collect_all_output_covers(table, 1, 1 << max_support)
        if covers is None:
            return False, len(table.active_vars), f"whole-function cover exceeded {1 << max_support}"
        write_cover_blif(path, model, table, covers, invert=False)
        return True, len(table.active_vars), "whole-function support synthesized from exact cover"

    supports = [output_support(table, output_index) for output_index in range(table.num_outputs)]
    largest_support = max((len(support) for support in supports), default=0)
    if largest_support > max_support:
        return False, largest_support, f"largest output support {largest_support} exceeds limit {max_support}"

    builder = BlifBuilder(table, model)
    outputs: list[str] = []
    cover_limit = 1 << max_support
    for output_index, support in enumerate(supports):
        bits = table.outputs[output_index]
        on_count = sum(bits)
        if on_count == 0:
            outputs.append(builder.const0)
            continue
        if on_count == len(bits):
            outputs.append(builder.const1)
            continue
        value = 1 if on_count <= len(bits) - on_count else 0
        cubes = collect_support_cubes(table, output_index, support, value, cover_limit)
        if cubes is None:
            return False, largest_support, f"output y{output_index} cover exceeded {cover_limit}"
        signal = factor_cover(builder, support, cubes)
        outputs.append(signal if value == 1 else builder.emit_not(signal))
    builder.finish(outputs, path)
    return True, largest_support, "all outputs synthesized from exact small-support covers"


def write_factored_sop_blif(path: Path, model: str, table: TruthTable, covers: list[list[tuple[int, ...]]]) -> None:
    builder = BlifBuilder(table, model)
    signals = [factor_cover(builder, table.active_vars, cubes) for cubes in covers]
    builder.finish(signals, path)


def compress_bits(table: TruthTable, bits: bytearray) -> tuple[int, ...]:
    if len(table.active_vars) == table.num_inputs:
        return tuple(bits)
    compact: list[int] = []
    for compact_index in range(1 << len(table.active_vars)):
        original = 0
        for pos, var in enumerate(table.active_vars):
            if (compact_index >> (len(table.active_vars) - 1 - pos)) & 1:
                original |= 1 << (table.num_inputs - 1 - var)
        compact.append(bits[original])
    return tuple(compact)


def cofactor_compact(bits: tuple[int, ...], split_index: int, var_count: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    bit_pos = var_count - 1 - split_index
    step = 1 << bit_pos
    period = step << 1
    low: list[int] = []
    high: list[int] = []
    for base in range(0, len(bits), period):
        low.extend(bits[base : base + step])
        high.extend(bits[base + step : base + period])
    return tuple(low), tuple(high)


def truth_bit(index: int, num_inputs: int, var: int) -> int:
    return (index >> (num_inputs - 1 - var)) & 1


def force_truth_bit(index: int, num_inputs: int, var: int, value: int) -> int:
    bit = 1 << (num_inputs - 1 - var)
    return (index | bit) if value else (index & ~bit)


def cofactor_support(bits: bytearray, num_inputs: int, active: list[int], selector: int, selector_value: int) -> set[int]:
    support: set[int] = set()
    for var in active:
        if var == selector:
            continue
        bit = 1 << (num_inputs - 1 - var)
        depends = False
        for index in range(len(bits)):
            if truth_bit(index, num_inputs, selector) != selector_value or (index & bit):
                continue
            if bits[index] != bits[index | bit]:
                depends = True
                break
        if depends:
            support.add(var)
    return support


def selector_reduction_order(table: TruthTable) -> list[int]:
    """Order variables by how much a Shannon split reduces cofactor support."""
    active = table.active_vars
    if len(active) < 3:
        return active[:]
    scores = {var: 0.0 for var in active}
    for bits in table.outputs:
        full_support = len(active)
        for selector in active:
            low = cofactor_support(bits, table.num_inputs, active, selector, 0)
            high = cofactor_support(bits, table.num_inputs, active, selector, 1)
            reduction = 2 * (full_support - 1) - len(low) - len(high)
            scores[selector] += max(0, reduction)
    return sorted(active, key=lambda var: (scores[var], table.shannon_scores[var], table.influences[var]), reverse=True)


def write_bdd_blif(path: Path, model: str, table: TruthTable, order: list[int], node_limit: int) -> None:
    active_to_pos = {var: pos for pos, var in enumerate(table.active_vars)}
    compact_order = [active_to_pos[var] for var in order if var in active_to_pos]
    compact_vars = tuple(range(len(table.active_vars)))
    builder = BlifBuilder(table, model)
    cache: dict[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]], str] = {}

    def build(bits: tuple[int, ...], variables: tuple[int, ...], remaining_order: tuple[int, ...]) -> str:
        if not any(bits):
            return builder.const0
        if all(bits):
            return builder.const1
        if not remaining_order:
            raise RuntimeError("non-constant terminal without variables")
        key = (bits, variables, remaining_order)
        if key in cache:
            return cache[key]
        if builder.counter > node_limit:
            raise RuntimeError("BDD node limit exceeded")
        var_pos = remaining_order[0]
        split_index = variables.index(var_pos)
        low_bits, high_bits = cofactor_compact(bits, split_index, len(variables))
        next_variables = tuple(var for var in variables if var != var_pos)
        next_order = tuple(var for var in remaining_order if var != var_pos)
        low_signal = build(low_bits, next_variables, next_order)
        high_signal = build(high_bits, next_variables, next_order)
        signal = builder.emit_mux(table.active_vars[var_pos], low_signal, high_signal)
        cache[key] = signal
        return signal

    signals = [
        build(compress_bits(table, bits), compact_vars, tuple(compact_order))
        for bits in table.outputs
    ]
    builder.finish(signals, path)


def detect_unsigned_square(table: TruthTable) -> list[int] | None:
    if table.num_outputs != 2 * table.num_inputs:
        return None

    def output_value(index: int) -> int:
        value = 0
        for output_index, bits in enumerate(table.outputs):
            value |= bits[index] << output_index
        return value

    for order in (list(reversed(range(table.num_inputs))), list(range(table.num_inputs))):
        matches = True
        for index in range(table.num_minterms):
            value = 0
            for bit_index, var in enumerate(order):
                value |= truth_bit(index, table.num_inputs, var) << bit_index
            if output_value(index) != value * value:
                matches = False
                break
        if matches:
            return order
    return None


def detect_unsigned_multiplier(table: TruthTable) -> tuple[list[int], list[int]] | None:
    if table.num_inputs % 2 != 0 or table.num_outputs != table.num_inputs:
        return None

    half = table.num_inputs // 2
    group_candidates = [
        (list(range(half)), list(range(half, table.num_inputs))),
        (list(range(0, table.num_inputs, 2)), list(range(1, table.num_inputs, 2))),
        (list(range(1, table.num_inputs, 2)), list(range(0, table.num_inputs, 2))),
    ]

    def output_value(index: int) -> int:
        value = 0
        for output_index, bits in enumerate(table.outputs):
            value |= bits[index] << output_index
        return value

    def input_value(index: int, order: list[int]) -> int:
        value = 0
        for bit_index, var in enumerate(order):
            value |= truth_bit(index, table.num_inputs, var) << bit_index
        return value

    mask = (1 << table.num_outputs) - 1
    for left_group, right_group in group_candidates:
        for left_order in (left_group, list(reversed(left_group))):
            for right_order in (right_group, list(reversed(right_group))):
                for a_order, b_order in ((left_order, right_order), (right_order, left_order)):
                    matches = True
                    for index in range(table.num_minterms):
                        product = input_value(index, a_order) * input_value(index, b_order)
                        if output_value(index) != (product & mask):
                            matches = False
                            break
                    if matches:
                        return a_order, b_order
    return None


def detect_signed_multiplier(table: TruthTable) -> tuple[list[int], list[int]] | None:
    if table.num_inputs % 2 != 0 or table.num_outputs != table.num_inputs:
        return None

    half = table.num_inputs // 2
    group_candidates = [
        (list(range(half)), list(range(half, table.num_inputs))),
        (list(range(0, table.num_inputs, 2)), list(range(1, table.num_inputs, 2))),
        (list(range(1, table.num_inputs, 2)), list(range(0, table.num_inputs, 2))),
    ]

    def output_value(index: int) -> int:
        value = 0
        for output_index, bits in enumerate(table.outputs):
            value |= bits[index] << output_index
        return value

    def signed_input_value(index: int, order: list[int]) -> int:
        value = 0
        for bit_index, var in enumerate(order):
            value |= truth_bit(index, table.num_inputs, var) << bit_index
        sign_bit = 1 << (len(order) - 1)
        return value - (1 << len(order)) if value & sign_bit else value

    mask = (1 << table.num_outputs) - 1
    for left_group, right_group in group_candidates:
        for left_order in (left_group, list(reversed(left_group))):
            for right_order in (right_group, list(reversed(right_group))):
                for a_order, b_order in ((left_order, right_order), (right_order, left_order)):
                    matches = True
                    for index in range(table.num_minterms):
                        product = signed_input_value(index, a_order) * signed_input_value(index, b_order)
                        if output_value(index) != (product & mask):
                            matches = False
                            break
                    if matches:
                        return a_order, b_order
    return None


def detect_unsigned_divider_quotient(table: TruthTable) -> tuple[list[int], list[int]] | None:
    if table.num_inputs % 2 != 0 or table.num_outputs != table.num_inputs // 2:
        return None

    half = table.num_inputs // 2
    group_candidates = [
        (list(range(half)), list(range(half, table.num_inputs))),
        (list(range(0, table.num_inputs, 2)), list(range(1, table.num_inputs, 2))),
        (list(range(1, table.num_inputs, 2)), list(range(0, table.num_inputs, 2))),
    ]

    def output_value(index: int) -> int:
        value = 0
        for output_index, bits in enumerate(table.outputs):
            value |= bits[index] << output_index
        return value

    def input_value(index: int, order: list[int]) -> int:
        value = 0
        for bit_index, var in enumerate(order):
            value |= truth_bit(index, table.num_inputs, var) << bit_index
        return value

    mask = (1 << table.num_outputs) - 1
    for left_group, right_group in group_candidates:
        for left_order in (left_group, list(reversed(left_group))):
            for right_order in (right_group, list(reversed(right_group))):
                for divisor_order, dividend_order in ((left_order, right_order), (right_order, left_order)):
                    matches = True
                    for index in range(table.num_minterms):
                        divisor = input_value(index, divisor_order)
                        dividend = input_value(index, dividend_order)
                        quotient = mask if divisor == 0 else dividend // divisor
                        if output_value(index) != (quotient & mask):
                            matches = False
                            break
                    if matches:
                        return divisor_order, dividend_order
    return None


def detect_unsigned_sqrt(table: TruthTable) -> list[int] | None:
    if table.num_inputs != 2 * table.num_outputs:
        return None

    def output_value(index: int) -> int:
        value = 0
        for output_index, bits in enumerate(table.outputs):
            value |= bits[index] << output_index
        return value

    def input_value(index: int, order: list[int]) -> int:
        value = 0
        for bit_index, var in enumerate(order):
            value |= truth_bit(index, table.num_inputs, var) << bit_index
        return value

    candidates = [
        list(range(table.num_inputs)),
        list(reversed(range(table.num_inputs))),
    ]
    seen: set[tuple[int, ...]] = set()
    for order in candidates:
        key = tuple(order)
        if key in seen:
            continue
        seen.add(key)
        matches = True
        for index in range(table.num_minterms):
            value = input_value(index, order)
            if output_value(index) != math.isqrt(value):
                matches = False
                break
        if matches:
            return order
    return None


def reduce_weighted_columns(builder: BlifBuilder, columns: list[list[str]]) -> list[list[str]]:
    while any(len(column) > 2 for column in columns):
        next_columns: list[list[str]] = [[] for _ in range(len(columns) + 1)]
        for column_index, column_terms in enumerate(columns):
            terms = column_terms[:]
            while len(terms) >= 3:
                a = terms.pop()
                b = terms.pop()
                c = terms.pop()
                summation, carry = builder.emit_full_adder(a, b, c)
                next_columns[column_index].append(summation)
                next_columns[column_index + 1].append(carry)
            next_columns[column_index].extend(terms)
        columns = next_columns
    return columns


def emit_column_outputs(builder: BlifBuilder, columns: list[list[str]], output_count: int) -> list[str]:
    outputs: list[str] = []
    carry = builder.const0
    for column in range(output_count):
        terms = columns[column][:]
        if carry != builder.const0:
            terms.append(carry)
        if not terms:
            outputs.append(builder.const0)
            carry = builder.const0
        elif len(terms) == 1:
            outputs.append(terms[0])
            carry = builder.const0
        elif len(terms) == 2:
            outputs.append(builder.emit_xor(terms[0], terms[1]))
            carry = builder.emit_and(terms[0], terms[1])
        else:
            summation, carry = builder.emit_full_adder(terms[0], terms[1], terms[2])
            outputs.append(summation)
    return outputs


def emit_unsigned_product_bits(
    builder: BlifBuilder,
    a_order: list[int],
    b_order: list[int],
    output_count: int,
) -> list[str]:
    columns: list[list[str]] = [[] for _ in range(output_count + len(a_order) + len(b_order) + 2)]
    for left, a_var in enumerate(a_order):
        for right, b_var in enumerate(b_order):
            columns[left + right].append(builder.emit_and(f"x{a_var}", f"x{b_var}"))
    columns = reduce_weighted_columns(builder, columns)
    return emit_column_outputs(builder, columns, output_count)


def emit_vector_add(builder: BlifBuilder, left: list[str], right: list[str], carry_in: str) -> list[str]:
    outputs: list[str] = []
    carry = carry_in
    for left_bit, right_bit in zip(left, right):
        if carry == builder.const0:
            summation, carry = builder.emit_half_adder(left_bit, right_bit)
        else:
            summation, carry = builder.emit_full_adder(left_bit, right_bit, carry)
        outputs.append(summation)
    return outputs


def emit_unsigned_greater_equal(builder: BlifBuilder, left: list[str], right: list[str]) -> str:
    assert len(left) == len(right)
    equal = builder.const1
    greater = builder.const0
    for left_bit, right_bit in zip(reversed(left), reversed(right)):
        left_gt_right = builder.emit_and(left_bit, builder.emit_not(right_bit))
        greater = builder.emit_or(greater, builder.emit_and(equal, left_gt_right))
        equal = builder.emit_and(equal, builder.emit_not(builder.emit_xor(left_bit, right_bit)))
    return builder.emit_or(greater, equal)


def emit_unsigned_subtract(builder: BlifBuilder, left: list[str], right: list[str]) -> list[str]:
    assert len(left) == len(right)
    outputs: list[str] = []
    borrow = builder.const0
    for left_bit, right_bit in zip(left, right):
        difference = builder.emit_xor(builder.emit_xor(left_bit, right_bit), borrow)
        borrow_from_left = builder.emit_and(builder.emit_not(left_bit), builder.emit_or(right_bit, borrow))
        borrow_from_terms = builder.emit_and(right_bit, borrow)
        borrow = builder.emit_or(borrow_from_left, borrow_from_terms)
        outputs.append(difference)
    return outputs


def emit_conditional_subtract_shifted(
    builder: BlifBuilder,
    minuend: list[str],
    subtrahend: list[str],
    shift: int,
    control: str,
) -> list[str]:
    # Add conditional two's-complement of (subtrahend << shift).  This avoids
    # building a separate signed multiplier while keeping the netlist structural.
    add_bits: list[str] = []
    for bit_index in range(len(minuend)):
        source_index = bit_index - shift
        if 0 <= source_index < len(subtrahend):
            add_bits.append(builder.emit_and(control, builder.emit_not(subtrahend[source_index])))
        else:
            add_bits.append(control)
    return emit_vector_add(builder, minuend, add_bits, control)


def write_unsigned_square_blif(path: Path, model: str, table: TruthTable, lsb_order: list[int]) -> None:
    builder = BlifBuilder(table, model)
    width = len(lsb_order)
    columns: list[list[str]] = [[] for _ in range(table.num_outputs + width + 2)]

    for left in range(width):
        left_signal = f"x{lsb_order[left]}"
        for right in range(left, width):
            if left == right:
                columns[left + right].append(left_signal)
            else:
                product = builder.emit_and(left_signal, f"x{lsb_order[right]}")
                columns[left + right + 1].append(product)

    columns = reduce_weighted_columns(builder, columns)
    outputs = emit_column_outputs(builder, columns, table.num_outputs)
    builder.finish(outputs, path)


def write_unsigned_multiplier_blif(path: Path, model: str, table: TruthTable, a_order: list[int], b_order: list[int]) -> None:
    builder = BlifBuilder(table, model)
    outputs = emit_unsigned_product_bits(builder, a_order, b_order, table.num_outputs)
    builder.finish(outputs, path)


def write_signed_multiplier_blif(path: Path, model: str, table: TruthTable, a_order: list[int], b_order: list[int]) -> None:
    builder = BlifBuilder(table, model)
    width = len(a_order)
    outputs = emit_unsigned_product_bits(builder, a_order, b_order, table.num_outputs)
    a_bits = [f"x{var}" for var in a_order]
    b_bits = [f"x{var}" for var in b_order]
    outputs = emit_conditional_subtract_shifted(builder, outputs, b_bits, width, a_bits[-1])
    outputs = emit_conditional_subtract_shifted(builder, outputs, a_bits, width, b_bits[-1])
    builder.finish(outputs, path)


def write_unsigned_divider_quotient_blif(
    path: Path,
    model: str,
    table: TruthTable,
    divisor_order: list[int],
    dividend_order: list[int],
) -> None:
    builder = BlifBuilder(table, model)
    width = len(dividend_order)
    dividend_bits = [f"x{var}" for var in dividend_order]
    divisor_bits = [f"x{var}" for var in divisor_order]
    divisor_extended = divisor_bits + [builder.const0]
    remainder = [builder.const0 for _ in range(width + 1)]
    quotient = [builder.const0 for _ in range(width)]

    for bit_index in reversed(range(width)):
        remainder = [dividend_bits[bit_index]] + remainder[:-1]
        take_subtract = emit_unsigned_greater_equal(builder, remainder, divisor_extended)
        difference = emit_unsigned_subtract(builder, remainder, divisor_extended)
        remainder = [
            builder.emit_mux_signal(take_subtract, keep_bit, diff_bit)
            for keep_bit, diff_bit in zip(remainder, difference)
        ]
        quotient[bit_index] = take_subtract

    builder.finish(quotient[: table.num_outputs], path)


def write_unsigned_sqrt_blif(path: Path, model: str, table: TruthTable, radicand_order: list[int]) -> None:
    builder = BlifBuilder(table, model)
    width = table.num_outputs
    rem_width = table.num_inputs + 2
    radicand_bits = [f"x{var}" for var in radicand_order]
    remainder = [builder.const0 for _ in range(rem_width)]
    root = [builder.const0 for _ in range(width)]

    for bit_index in reversed(range(width)):
        pair = [radicand_bits[2 * bit_index], radicand_bits[2 * bit_index + 1]]
        remainder = pair + remainder[: rem_width - 2]
        trial = [builder.const1, builder.const0] + root
        if len(trial) < rem_width:
            trial += [builder.const0 for _ in range(rem_width - len(trial))]
        else:
            trial = trial[:rem_width]
        take_subtract = emit_unsigned_greater_equal(builder, remainder, trial)
        difference = emit_unsigned_subtract(builder, remainder, trial)
        remainder = [
            builder.emit_mux_signal(take_subtract, keep_bit, diff_bit)
            for keep_bit, diff_bit in zip(remainder, difference)
        ]
        root = ([take_subtract] + root)[:width]

    builder.finish(root[: table.num_outputs], path)


def parse_var_order(text: str) -> list[int]:
    return [int(match) for match in re.findall(r"x(\d+)", text)]


def parse_binary_orders(text: str) -> tuple[list[int], list[int]] | None:
    match = re.search(r"a=\[([^\]]*)\];b=\[([^\]]*)\]", text)
    if not match:
        return None
    return parse_var_order(match.group(1)), parse_var_order(match.group(2))


def exact_matches_by_output(matches: list[ExactFunctionMatch]) -> dict[int, list[ExactFunctionMatch]]:
    grouped: dict[int, list[ExactFunctionMatch]] = defaultdict(list)
    for match in matches:
        grouped[match.output_index].append(match)
    return grouped


def choose_exact_match(
    grouped: dict[int, list[ExactFunctionMatch]],
    output_index: int,
    function_types: set[str],
) -> ExactFunctionMatch | None:
    for match in grouped.get(output_index, []):
        if match.function_type in function_types:
            return match
    return None


def exact_constant_signal(builder: BlifBuilder, match: ExactFunctionMatch | None) -> str | None:
    if match is None:
        return None
    if match.function_type == "constant_zero":
        return builder.const0
    if match.function_type == "constant_one":
        return builder.const1
    return None


def emit_xor_tree(builder: BlifBuilder, signals: list[str], invert: bool = False) -> str:
    result = builder.const0
    for signal in signals:
        result = builder.emit_xor(result, signal)
    return builder.emit_not(result) if invert else result


def emit_and_tree(builder: BlifBuilder, signals: list[str]) -> str:
    if not signals:
        return builder.const1
    result = signals[0]
    for signal in signals[1:]:
        result = builder.emit_and(result, signal)
    return result


def emit_unsigned_equal(builder: BlifBuilder, left: list[str], right: list[str]) -> str:
    assert len(left) == len(right)
    equal_terms = [builder.emit_not(builder.emit_xor(l_bit, r_bit)) for l_bit, r_bit in zip(left, right)]
    return emit_and_tree(builder, equal_terms)


def emit_constant_bits(builder: BlifBuilder, value: int, width: int) -> list[str]:
    return [builder.const1 if (value >> bit) & 1 else builder.const0 for bit in range(width)]


def emit_popcount_bits(builder: BlifBuilder, input_signals: list[str], width: int) -> list[str]:
    columns: list[list[str]] = [[] for _ in range(width + len(input_signals) + 2)]
    columns[0] = input_signals[:]
    columns = reduce_weighted_columns(builder, columns)
    return emit_column_outputs(builder, columns, width)


def emit_unsigned_equal_constant(builder: BlifBuilder, bits: list[str], value: int) -> str:
    if value < 0 or value >= (1 << len(bits)):
        return builder.const0
    return emit_unsigned_equal(builder, bits, emit_constant_bits(builder, value, len(bits)))


def emit_unsigned_ge_constant(builder: BlifBuilder, bits: list[str], value: int) -> str:
    if value <= 0:
        return builder.const1
    if value >= (1 << len(bits)):
        return builder.const0
    return emit_unsigned_greater_equal(builder, bits, emit_constant_bits(builder, value, len(bits)))


def emit_unsigned_add_bits(builder: BlifBuilder, a_order: list[int], b_order: list[int]) -> list[str]:
    outputs: list[str] = []
    carry = builder.const0
    for a_var, b_var in zip(a_order, b_order):
        a_bit = f"x{a_var}"
        b_bit = f"x{b_var}"
        if carry == builder.const0:
            summation, carry = builder.emit_half_adder(a_bit, b_bit)
        else:
            summation, carry = builder.emit_full_adder(a_bit, b_bit, carry)
        outputs.append(summation)
    outputs.append(carry)
    return outputs


def emit_comparator_outputs(builder: BlifBuilder, a_order: list[int], b_order: list[int]) -> dict[str, str]:
    a_bits = [f"x{var}" for var in a_order]
    b_bits = [f"x{var}" for var in b_order]
    ge = emit_unsigned_greater_equal(builder, a_bits, b_bits)
    eq = emit_unsigned_equal(builder, a_bits, b_bits)
    gt = builder.emit_and(ge, builder.emit_not(eq))
    lt = builder.emit_not(ge)
    return {
        "comparator_gt": gt,
        "comparator_ge": ge,
        "comparator_eq": eq,
        "comparator_lt": lt,
    }


def affine_signal_from_match(builder: BlifBuilder, match: ExactFunctionMatch) -> str | None:
    if match.function_type == "constant_zero":
        return builder.const0
    if match.function_type == "constant_one":
        return builder.const1
    if match.function_type == "buffer":
        order = parse_var_order(match.input_order)
        return f"x{order[0]}" if order else None
    if match.function_type == "inverter":
        order = parse_var_order(match.input_order)
        return builder.emit_not(f"x{order[0]}") if order else None
    if match.function_type in {"affine", "parity"}:
        order = parse_var_order(match.input_order)
        const_match = re.search(r"constant=(\d+)", match.evidence)
        invert = bool(const_match and const_match.group(1) == "1")
        return emit_xor_tree(builder, [f"x{var}" for var in order], invert=invert)
    return None


def write_exact_affine_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    builder = BlifBuilder(table, model)
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        match = choose_exact_match(
            grouped,
            output_index,
            {"constant_zero", "constant_one", "buffer", "inverter", "affine", "parity"},
        )
        if match is None:
            return False
        signal = affine_signal_from_match(builder, match)
        if signal is None:
            return False
        outputs.append(signal)
    builder.finish(outputs, path)
    return True


def write_exact_popcount_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    pop_matches = [match for match in matches if match.function_type == "popcount_output_bit"]
    if not pop_matches:
        return False
    order = parse_var_order(pop_matches[0].input_order)
    if not order or any(parse_var_order(match.input_order) != order for match in pop_matches):
        return False
    max_bit = max(int(match.bit_index) for match in pop_matches if match.bit_index.isdigit())
    builder = BlifBuilder(table, model)
    pop_bits = emit_popcount_bits(builder, [f"x{var}" for var in order], max(table.num_outputs, max_bit + 1))
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        constant = exact_constant_signal(
            builder,
            choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
        )
        if constant is not None:
            outputs.append(constant)
            continue
        match = choose_exact_match(grouped, output_index, {"popcount_output_bit"})
        if match is None or parse_var_order(match.input_order) != order or not match.bit_index.isdigit():
            return False
        outputs.append(pop_bits[int(match.bit_index)] if int(match.bit_index) < len(pop_bits) else builder.const0)
    builder.finish(outputs, path)
    return True


def write_exact_threshold_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    threshold_types = {"majority", "threshold_ge", "threshold_le", "exact_k", "one_hot_exactly_one", "sorter_output_bit"}
    threshold_matches = [match for match in matches if match.function_type in threshold_types]
    if not threshold_matches:
        return False
    order = parse_var_order(threshold_matches[0].input_order)
    if not order or any(parse_var_order(match.input_order) != order for match in threshold_matches):
        return False
    width = max(1, math.ceil(math.log2(len(order) + 1)))
    builder = BlifBuilder(table, model)
    pop_bits = emit_popcount_bits(builder, [f"x{var}" for var in order], width)
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        constant = exact_constant_signal(
            builder,
            choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
        )
        if constant is not None:
            outputs.append(constant)
            continue
        match = choose_exact_match(grouped, output_index, threshold_types)
        if match is None or parse_var_order(match.input_order) != order:
            return False
        if match.function_type in {"majority", "threshold_ge"}:
            outputs.append(emit_unsigned_ge_constant(builder, pop_bits, int(match.bit_index)))
        elif match.function_type == "threshold_le":
            outputs.append(builder.emit_not(emit_unsigned_ge_constant(builder, pop_bits, int(match.bit_index) + 1)))
        elif match.function_type in {"exact_k", "one_hot_exactly_one"}:
            outputs.append(emit_unsigned_equal_constant(builder, pop_bits, int(match.bit_index or "1")))
        elif match.function_type == "sorter_output_bit":
            outputs.append(emit_unsigned_ge_constant(builder, pop_bits, int(match.bit_index) + 1))
    builder.finish(outputs, path)
    return True


def write_exact_adder_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    adder_matches = [match for match in matches if match.function_type in {"adder_sum_bit", "adder_carry_bit"}]
    if not adder_matches:
        return False
    orders = parse_binary_orders(adder_matches[0].input_order)
    if orders is None:
        return False
    a_order, b_order = orders
    if any(parse_binary_orders(match.input_order) != orders for match in adder_matches):
        return False
    builder = BlifBuilder(table, model)
    add_bits = emit_unsigned_add_bits(builder, a_order, b_order)
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        constant = exact_constant_signal(
            builder,
            choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
        )
        if constant is not None:
            outputs.append(constant)
            continue
        match = choose_exact_match(grouped, output_index, {"adder_sum_bit", "adder_carry_bit"})
        if match is None or parse_binary_orders(match.input_order) != orders or not match.bit_index.isdigit():
            return False
        bit_index = int(match.bit_index)
        outputs.append(add_bits[bit_index] if bit_index < len(add_bits) else builder.const0)
    builder.finish(outputs, path)
    return True


def write_exact_comparator_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    comparator_types = {"comparator_gt", "comparator_ge", "comparator_eq", "comparator_lt"}
    comparator_matches = [match for match in matches if match.function_type in comparator_types]
    if not comparator_matches:
        return False
    orders = parse_binary_orders(comparator_matches[0].input_order)
    if orders is None:
        return False
    if any(parse_binary_orders(match.input_order) != orders for match in comparator_matches):
        return False
    builder = BlifBuilder(table, model)
    comp = emit_comparator_outputs(builder, *orders)
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        constant = exact_constant_signal(
            builder,
            choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
        )
        if constant is not None:
            outputs.append(constant)
            continue
        match = choose_exact_match(grouped, output_index, comparator_types)
        if match is None or parse_binary_orders(match.input_order) != orders:
            return False
        outputs.append(comp[match.function_type])
    builder.finish(outputs, path)
    return True


def make_exact_specialized_candidates(
    case: str,
    table: TruthTable,
    truth: Path,
    tmp: Path,
    exact_max_inputs: int,
) -> list[tuple[InitialCandidate, str, str]]:
    matches = exact_matches_for_truth(truth, max_expensive_inputs=exact_max_inputs)
    candidates: list[tuple[InitialCandidate, str, str]] = []

    def add_blif(generator: str, function_type: str, writer) -> None:
        blif = tmp / f"{case}_{generator}.blif"
        try:
            if writer(blif, f"{case}_{generator}", table, matches):
                candidates.append((InitialCandidate(f"specialized_{generator}", "blif", blif), function_type, generator))
        except Exception:
            if blif.exists():
                blif.unlink()

    add_blif("exact_affine", "affine_parity", write_exact_affine_blif)
    add_blif("exact_popcount", "popcount", write_exact_popcount_blif)
    add_blif("exact_threshold", "threshold_exact_k_sorter", write_exact_threshold_blif)
    add_blif("exact_adder", "adder", write_exact_adder_blif)
    add_blif("exact_comparator", "comparator", write_exact_comparator_blif)

    square_order = detect_unsigned_square(table)
    if square_order is not None:
        blif = tmp / f"{case}_exact_unsigned_square.blif"
        write_unsigned_square_blif(blif, f"{case}_exact_unsigned_square", table, square_order)
        candidates.append((InitialCandidate("specialized_exact_unsigned_square", "blif", blif), "square", "exact_unsigned_square"))

    multiplier_orders = detect_unsigned_multiplier(table)
    if multiplier_orders is not None:
        a_order, b_order = multiplier_orders
        blif = tmp / f"{case}_exact_unsigned_multiplier.blif"
        write_unsigned_multiplier_blif(blif, f"{case}_exact_unsigned_multiplier", table, a_order, b_order)
        candidates.append((InitialCandidate("specialized_exact_unsigned_multiplier", "blif", blif), "unsigned_multiplier", "exact_unsigned_multiplier"))

    signed_multiplier_orders = detect_signed_multiplier(table)
    if signed_multiplier_orders is not None:
        a_order, b_order = signed_multiplier_orders
        blif = tmp / f"{case}_exact_signed_multiplier.blif"
        write_signed_multiplier_blif(blif, f"{case}_exact_signed_multiplier", table, a_order, b_order)
        candidates.append((InitialCandidate("specialized_exact_signed_multiplier", "blif", blif), "signed_multiplier", "exact_signed_multiplier"))

    divider_orders = detect_unsigned_divider_quotient(table)
    if divider_orders is not None:
        divisor_order, dividend_order = divider_orders
        blif = tmp / f"{case}_exact_unsigned_divider_quotient.blif"
        write_unsigned_divider_quotient_blif(blif, f"{case}_exact_unsigned_divider_quotient", table, divisor_order, dividend_order)
        candidates.append((InitialCandidate("specialized_exact_unsigned_divider_quotient", "blif", blif), "divider_quotient", "exact_unsigned_divider_quotient"))

    sqrt_order = detect_unsigned_sqrt(table)
    if sqrt_order is not None:
        blif = tmp / f"{case}_exact_unsigned_sqrt.blif"
        write_unsigned_sqrt_blif(blif, f"{case}_exact_unsigned_sqrt", table, sqrt_order)
        candidates.append((InitialCandidate("specialized_exact_unsigned_sqrt", "blif", blif), "integer_sqrt", "exact_unsigned_sqrt"))

    return candidates


def make_initial_candidates(
    case: str,
    table: TruthTable,
    tmp: Path,
    seed: int,
    use_bdd: bool,
    try_complement: bool = False,
) -> list[InitialCandidate]:
    tmp.mkdir(parents=True, exist_ok=True)
    candidates = [InitialCandidate("abc_truth", "truth", None)]
    if try_complement:
        complement_truth = tmp / f"{case}_abc_truth_complement.truth"
        write_complement_truth(complement_truth, table)
        candidates.append(InitialCandidate("abc_truth_complement", "truth_complement", complement_truth))

    cover_limit = 4096
    factor_limit = 1024
    sop_covers = collect_all_output_covers(table, 1, cover_limit)
    pos_covers = collect_all_output_covers(table, 0, cover_limit)
    if sop_covers is not None and table.density <= 0.45:
        blif = tmp / f"{case}_sop.blif"
        write_cover_blif(blif, f"{case}_sop", table, sop_covers, invert=False)
        candidates.append(InitialCandidate("sop_onset", "blif", blif))
    if pos_covers is not None and table.density >= 0.55:
        blif = tmp / f"{case}_pos.blif"
        write_cover_blif(blif, f"{case}_pos", table, pos_covers, invert=True)
        candidates.append(InitialCandidate("pos_offset_inverted", "blif", blif))
    if sop_covers is not None and max(len(cubes) for cubes in sop_covers) <= factor_limit:
        blif = tmp / f"{case}_factored_sop.blif"
        write_factored_sop_blif(blif, f"{case}_factored_sop", table, sop_covers)
        candidates.append(InitialCandidate("recursive_factored_sop", "blif", blif))

    square_order = detect_unsigned_square(table)
    if square_order is not None:
        blif = tmp / f"{case}_unsigned_square.blif"
        write_unsigned_square_blif(blif, f"{case}_unsigned_square", table, square_order)
        candidates.append(InitialCandidate("template_unsigned_square", "blif", blif))

    multiplier_orders = detect_unsigned_multiplier(table)
    if multiplier_orders is not None:
        a_order, b_order = multiplier_orders
        blif = tmp / f"{case}_unsigned_multiplier.blif"
        write_unsigned_multiplier_blif(blif, f"{case}_unsigned_multiplier", table, a_order, b_order)
        candidates.append(InitialCandidate("template_unsigned_multiplier", "blif", blif))

    signed_multiplier_orders = detect_signed_multiplier(table)
    if signed_multiplier_orders is not None:
        a_order, b_order = signed_multiplier_orders
        blif = tmp / f"{case}_signed_multiplier.blif"
        write_signed_multiplier_blif(blif, f"{case}_signed_multiplier", table, a_order, b_order)
        candidates.append(InitialCandidate("template_signed_multiplier", "blif", blif))

    divider_orders = detect_unsigned_divider_quotient(table)
    if divider_orders is not None:
        divisor_order, dividend_order = divider_orders
        blif = tmp / f"{case}_unsigned_divider_quotient.blif"
        write_unsigned_divider_quotient_blif(
            blif,
            f"{case}_unsigned_divider_quotient",
            table,
            divisor_order,
            dividend_order,
        )
        candidates.append(InitialCandidate("template_unsigned_divider_quotient", "blif", blif))

    sqrt_order = detect_unsigned_sqrt(table)
    if sqrt_order is not None:
        blif = tmp / f"{case}_unsigned_sqrt.blif"
        write_unsigned_sqrt_blif(blif, f"{case}_unsigned_sqrt", table, sqrt_order)
        candidates.append(InitialCandidate("template_unsigned_sqrt", "blif", blif))

    active = table.active_vars
    if use_bdd and len(active) <= 18:
        orders = [
            ("bdd_original", active),
            ("bdd_high_influence", sorted(active, key=lambda var: table.influences[var], reverse=True)),
            ("bdd_selector_reduction", selector_reduction_order(table)),
            ("bdd_low_influence", sorted(active, key=lambda var: table.influences[var])),
            ("bdd_balanced_shannon", sorted(active, key=lambda var: table.shannon_scores[var], reverse=True)),
        ]
        rng = random.Random(f"{seed}:{case}:bdd")
        for index in range(3):
            random_order = active[:]
            rng.shuffle(random_order)
            orders.append((f"bdd_random_seeded_{index}", random_order))
        for name, order in orders:
            try:
                blif = tmp / f"{case}_{name}.blif"
                write_bdd_blif(blif, f"{case}_{name}", table, order, node_limit=120000)
                candidates.append(InitialCandidate(name, "blif", blif))
            except RuntimeError:
                continue
    return candidates


def complement_method_name(method: str) -> str:
    if method == "abc_truth":
        return "abc_truth_complement"
    if "bdd" in method:
        return f"bdd_complement_{method}"
    if "factored" in method:
        return "factored_sop_complement"
    if "sop" in method:
        return "sop_complement"
    if "pos" in method:
        return "pos_complement"
    if "template" in method or "exact" in method:
        return f"specialized_complement_{method}"
    return f"{method}_complement"


def make_complement_initial_candidates(
    case: str,
    table: TruthTable,
    tmp: Path,
    seed: int,
    use_bdd: bool,
) -> list[InitialCandidate]:
    tmp.mkdir(parents=True, exist_ok=True)
    complement_truth = tmp / f"{case}_complement.truth"
    write_complement_truth(complement_truth, table)
    complement_table = read_truth(complement_truth)
    candidates = [InitialCandidate("abc_truth_complement", "truth_complement", complement_truth)]
    generated_dir = tmp / "generated"
    for initial in make_initial_candidates(f"{case}_complement", complement_table, generated_dir, seed, use_bdd, False):
        if initial.method == "abc_truth" or initial.source_path is None:
            continue
        if initial.source_kind == "blif":
            candidates.append(
                InitialCandidate(
                    complement_method_name(initial.method),
                    "blif_complement",
                    initial.source_path,
                )
            )
    return candidates


def choose_candidate_pairs(
    initials: list[InitialCandidate],
    flows: list[PostFlow],
    max_candidates: int,
) -> list[tuple[InitialCandidate, PostFlow]]:
    by_flow = {flow.name: flow for flow in flows}
    abc_initials = [initial for initial in initials if initial.method == "abc_truth"]
    custom_initials = [initial for initial in initials if initial.method != "abc_truth"]
    ga_names = [flow.name for flow in flows if flow.name.startswith("ga_")]
    priority_names = TOP_FLOW_NAMES + ga_names[:2]

    ordered: list[tuple[InitialCandidate, PostFlow]] = []

    def add(initial: InitialCandidate, flow: PostFlow) -> None:
        pair = (initial, flow)
        if pair not in ordered:
            ordered.append(pair)

    for initial in abc_initials:
        for flow in POST_FLOWS:
            add(initial, flow)
    for initial in custom_initials:
        for name in priority_names:
            if name in by_flow:
                add(initial, by_flow[name])
    for initial in custom_initials:
        for flow in POST_FLOWS:
            add(initial, flow)
    for initial in initials:
        for flow in flows:
            add(initial, flow)

    return ordered[:max_candidates]


def pareto_frontier(results: list[CandidateResult]) -> list[CandidateResult]:
    equivalent = [row for row in results if row.equivalent and row.area is not None and row.delay is not None]
    frontier: list[CandidateResult] = []
    for row in equivalent:
        dominated = False
        for other in equivalent:
            if other is row or other.area is None or other.delay is None or row.area is None or row.delay is None:
                continue
            no_worse = other.area <= row.area and other.delay <= row.delay
            strictly_better = other.area < row.area or other.delay < row.delay
            if no_worse and strictly_better:
                dominated = True
                break
        if not dominated:
            frontier.append(row)
    return frontier


def candidate_source_method(row: CandidateResult) -> str:
    text = f"{row.initial_method}/{row.flow_name}".lower()
    if row.initial_method == "abc_truth" and row.flow_name == "identity":
        return "abc_baseline"
    if "bdd" in text or "shannon" in text:
        return "bdd_shannon"
    if any(token in text for token in ("sop", "pos", "factored")):
        return "sop_pos_factored"
    if "complement" in text:
        return "complement"
    if any(token in text for token in ("template", "multiplier", "square", "divider", "sqrt", "adder", "carry")):
        return "arithmetic_template"
    if "npn" in text or "exact" in text:
        return "exact_npn"
    if "mockturtle" in text and "xag" in text:
        return "mockturtle_xag"
    if "mockturtle" in text and "mig" in text:
        return "mockturtle_mig"
    if "transduction" in text or "dontcare" in text or "dc_" in text:
        return "transduction_inspired"
    if "existing_output" in text:
        return "existing_output"
    if "post_polish" in text:
        return "post_polish"
    return "other"


def build_pareto_candidates(results: list[CandidateResult]) -> list[ParetoCandidate]:
    equivalent = [
        row
        for row in results
        if row.equivalent and row.area is not None and row.delay is not None and row.adp is not None
    ]
    if not equivalent:
        return []

    rows: list[ParetoCandidate] = []
    counters: dict[str, int] = defaultdict(int)
    by_case: dict[str, list[CandidateResult]] = defaultdict(list)
    for row in equivalent:
        by_case[row.case].append(row)

    for case in sorted(by_case):
        case_rows = by_case[case]
        frontier = set(id(row) for row in pareto_frontier(case_rows))
        min_area = min(row.area for row in case_rows if row.area is not None)
        min_delay = min(row.delay for row in case_rows if row.delay is not None)
        min_adp = min(row.adp for row in case_rows if row.adp is not None)
        keep_ids: set[int] = set(frontier)

        for source in [
            "abc_baseline",
            "bdd_shannon",
            "sop_pos_factored",
            "complement",
            "arithmetic_template",
            "mockturtle_xag",
            "mockturtle_mig",
            "exact_npn",
            "transduction_inspired",
        ]:
            source_rows = [row for row in case_rows if candidate_source_method(row) == source]
            if source_rows:
                keep_ids.add(id(min(source_rows, key=lambda row: row.adp if row.adp is not None else 10**30)))

        for row in case_rows:
            if row.selected:
                keep_ids.add(id(row))

        for row in case_rows:
            if id(row) not in keep_ids:
                continue
            counters[row.case] += 1
            assert row.area is not None and row.delay is not None and row.adp is not None
            rows.append(
                ParetoCandidate(
                    case=row.case,
                    candidate_id=f"{row.case}_pareto_{counters[row.case]:04d}",
                    source_method=candidate_source_method(row),
                    area=row.area,
                    delay=row.delay,
                    adp=row.adp,
                    is_pareto=id(row) in frontier,
                    is_min_area=row.area == min_area,
                    is_min_delay=row.delay == min_delay,
                    is_min_adp=row.adp == min_adp,
                    selected_final=row.selected,
                    file_path=str(row.aig or ""),
                )
            )
    return rows


def write_pareto_candidates_csv(path: Path, results: list[CandidateResult]) -> None:
    rows = build_pareto_candidates(results)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case",
                "candidate_id",
                "source_method",
                "area",
                "delay",
                "adp",
                "is_pareto",
                "is_min_area",
                "is_min_delay",
                "is_min_adp",
                "selected_final",
                "file_path",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
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
                }
            )


def synthesize(
    abc: Path,
    truth: Path,
    initial: InitialCandidate,
    flow: PostFlow,
    out_aig: Path,
    timeout: int,
    root: Path,
) -> None:
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    if initial.source_kind == "truth":
        commands = "st"
        if flow.commands:
            commands += "; " + flow.commands
        command = f"read_truth -xf {abc_path(truth, root)}; {commands}; write_aiger -s {abc_path(out_aig, root)}"
    elif initial.source_kind == "truth_complement":
        assert initial.source_path is not None
        commands = "st"
        if flow.commands:
            commands += "; " + flow.commands
        raw_blif = out_aig.with_suffix(".complement_raw.blif")
        wrapped_blif = out_aig.with_suffix(".complement_wrapped.blif")
        command = f"read_truth -xf {abc_path(initial.source_path, root)}; {commands}; write_blif {abc_path(raw_blif, root)}"
        run_abc(abc, command, timeout, root)
        wrap_inverted_blif_outputs(raw_blif, wrapped_blif)
        command = f"read_blif {abc_path(wrapped_blif, root)}; strash; write_aiger -s {abc_path(out_aig, root)}"
        run_abc(abc, command, timeout, root)
        return
    elif initial.source_kind == "blif_complement":
        assert initial.source_path is not None
        commands = "strash"
        if flow.commands:
            commands += "; " + flow.commands
        raw_blif = out_aig.with_suffix(".blif_complement_raw.blif")
        wrapped_blif = out_aig.with_suffix(".blif_complement_wrapped.blif")
        command = f"read_blif {abc_path(initial.source_path, root)}; {commands}; write_blif {abc_path(raw_blif, root)}"
        run_abc(abc, command, timeout, root)
        wrap_inverted_blif_outputs(raw_blif, wrapped_blif)
        command = f"read_blif {abc_path(wrapped_blif, root)}; strash; write_aiger -s {abc_path(out_aig, root)}"
        run_abc(abc, command, timeout, root)
        return
    else:
        assert initial.source_path is not None
        commands = "strash"
        if flow.commands:
            commands += "; " + flow.commands
        command = f"read_blif {abc_path(initial.source_path, root)}; {commands}; write_aiger -s {abc_path(out_aig, root)}"
    run_abc(abc, command, timeout, root)


def polish_aig(
    abc: Path,
    source_aig: Path,
    flow: PostFlow,
    out_aig: Path,
    timeout: int,
    root: Path,
) -> None:
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    command = f"read {abc_path(source_aig, root)}; {flow.commands}; write_aiger -s {abc_path(out_aig, root)}"
    run_abc(abc, command, timeout, root)


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


def append_mockturtle_candidates_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = ["case", "mode", "fingerprint_reason", "generated", "equivalent", "area", "delay", "adp", "improved", "error"]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_mockturtle_structural_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "base_area",
        "base_delay",
        "base_adp",
        "best_area",
        "best_delay",
        "best_adp",
        "improvement",
        "modes",
        "exact_types",
        "generated",
        "equivalent",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def exact_type_hints_for_mockturtle(matches: list[ExactFunctionMatch]) -> set[str]:
    return {match.function_type for match in matches}


def select_structural_mockturtle_modes(
    fingerprint,
    current_area: int,
    current_delay: int,
    current_adp: int,
    exact_types: set[str] | None = None,
    max_modes: int = 2,
) -> tuple[list[str], str]:
    labels = set(fingerprint.labels)
    strategy = fingerprint.recommended_strategy
    exact_types = exact_types or set()
    modes: list[str] = []
    reasons: list[str] = []

    def add(mode: str, reason: str) -> None:
        if mode not in modes:
            modes.append(mode)
            reasons.append(reason)

    if (
        labels & {"parity", "affine", "adder_sum_like"}
        or exact_types & {"affine", "parity", "adder_sum_bit", "popcount_output_bit"}
        or "xor" in strategy
    ):
        add("xag_area_minmc", "XOR/affine fingerprint")
        add("xag_xor_heavy", "XOR/affine fingerprint")
    if (
        labels & {"majority", "threshold_positive", "threshold_negative", "exact_k", "carry_like", "symmetric", "symmetric_variable_groups"}
        or exact_types
        & {
            "majority",
            "threshold_ge",
            "threshold_le",
            "exact_k",
            "one_hot_exactly_one",
            "sorter_output_bit",
            "comparator_gt",
            "comparator_ge",
            "comparator_eq",
            "comparator_lt",
            "adder_carry_bit",
        }
    ):
        add("mig_akers_cut4", "majority/threshold/symmetric fingerprint")
        add("mig_majority", "majority/threshold/symmetric fingerprint")
    if (
        labels & {"carry_like", "adder_sum_like"}
        or exact_types
        & {
            "adder_sum_bit",
            "adder_carry_bit",
            "unsigned_multiplier_output_bit",
            "signed_multiplier_output_bit",
            "square_output_bit",
            "divider_quotient_bit",
            "divider_remainder_bit",
            "modulo_remainder_like",
            "integer_sqrt_output_bit",
        }
        or "arithmetic" in strategy
    ):
        add("xmg_mixed_resub", "mixed XOR/majority arithmetic fingerprint")
        add("xmg_arithmetic", "mixed XOR/majority arithmetic fingerprint")
    if "mux_like" in labels:
        add("cut5_aig_xag_npn_depth", "mux-like Shannon structure")
        add("roundtrip_xag", "mux-like Shannon structure")
    if current_area >= 20000 or current_adp >= 300000:
        add("dc_aig_rewrite", "large structural AIG after previous synthesis")
        add("aig_resub", "large structural AIG after previous synthesis")
    if current_area <= 2500 or current_adp <= 50000:
        add("cut4_aig_xag_npn", "compact small-case cut rewriting")
    target_modes = max(1, max_modes)
    if current_delay >= 18 and len(modes) < target_modes:
        add("roundtrip_mig", "delay-oriented majority roundtrip")
    if len(modes) < target_modes:
        add("functional_reduction", "redundancy-oriented fallback")
    if len(modes) < target_modes:
        add("roundtrip_xag", "XAG roundtrip fallback")

    return modes[:target_modes], "; ".join(reasons[:target_modes])


def type_guided_family(fingerprint) -> tuple[str, str]:
    labels = set(fingerprint.labels)
    strategy = fingerprint.recommended_strategy
    if labels & {"parity", "affine", "adder_sum_like"} or "xor" in strategy:
        return "xor_affine", "affine/parity or XOR-heavy fingerprint"
    if labels & {"carry_like"} or "arithmetic" in strategy:
        return "arithmetic", "arithmetic XOR/majority fingerprint"
    if labels & {"majority", "threshold_positive", "threshold_negative", "exact_k", "one_hot_exactly_one", "symmetric", "symmetric_variable_groups"}:
        return "threshold_majority", "threshold/majority/symmetric fingerprint"
    if "mux_like" in labels or "shannon" in strategy:
        return "mux_shannon", "mux-like or Shannon selector fingerprint"
    if len(fingerprint.effective_support) <= 6 or any(label.startswith("npn_") for label in labels):
        return "small_template", "small-support/NPN-template fingerprint"
    return "general", "general mixed-logic fingerprint"


def select_type_guided_flows(fingerprint, area: int, delay: int, adp: int, limit: int) -> tuple[str, str, list[PostFlow]]:
    family, reason = type_guided_family(fingerprint)
    flows = list(TYPE_GUIDED_FLOW_LIBRARY[family])
    if delay >= 18:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[0])
    if area >= 5000 or adp >= 100000:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[1])
    if family != "general":
        flows.append(TYPE_GUIDED_FLOW_LIBRARY["general"][0])

    deduped: list[PostFlow] = []
    seen: set[str] = set()
    for flow in flows:
        if flow.commands in seen:
            continue
        seen.add(flow.commands)
        deduped.append(flow)
        if len(deduped) >= limit:
            break
    return family, reason, deduped


def append_type_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "family",
        "labels",
        "reason",
        "flow_name",
        "flow_commands",
        "area",
        "delay",
        "adp",
        "equivalent",
        "improved",
        "selected",
        "status",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def select_objective_guided_flows(max_per_objective: int) -> list[tuple[str, PostFlow]]:
    selected: list[tuple[str, PostFlow]] = []
    seen: set[str] = set()
    for objective in ("area", "delay", "balanced"):
        for flow in OBJECTIVE_GUIDED_FLOW_LIBRARY[objective][:max_per_objective]:
            if flow.commands in seen:
                continue
            seen.add(flow.commands)
            selected.append((objective, flow))
    return selected


def append_objective_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "objective",
        "flow_name",
        "flow_commands",
        "area",
        "delay",
        "adp",
        "equivalent",
        "improved",
        "selected",
        "status",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def select_micro_guided_flows(area: int, adp: int, max_flows: int) -> list[PostFlow]:
    flows = list(MICRO_GUIDED_FLOWS)
    if area <= 1000 or adp <= 10000:
        flows.extend(MICRO_COLLAPSE_FLOWS)
    return flows[:max_flows]


def append_micro_guided_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "flow_name",
        "flow_commands",
        "area",
        "delay",
        "adp",
        "equivalent",
        "improved",
        "selected",
        "status",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def select_small_case_flows(max_flows: int) -> list[PostFlow]:
    return SMALL_CASE_FLOWS[:max_flows]


def append_small_case_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "labels",
        "recommended_strategy",
        "base_area",
        "base_delay",
        "base_adp",
        "flow_name",
        "flow_commands",
        "area",
        "delay",
        "adp",
        "equivalent",
        "improved",
        "selected",
        "status",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_specialized_generators_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "function_type",
        "generator",
        "flow_name",
        "flow_commands",
        "generated",
        "equivalent",
        "area",
        "delay",
        "adp",
        "improved",
        "selected",
        "error",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_ttopt_structural_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "input_support",
        "output_group",
        "rounds",
        "flow_name",
        "flow_commands",
        "generated",
        "equivalent",
        "area",
        "delay",
        "adp",
        "improved",
        "selected",
        "error",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_exact_npn_rescue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "support_size",
        "method",
        "template",
        "flow_name",
        "generated",
        "equivalent",
        "area",
        "delay",
        "adp",
        "improved",
        "selected",
        "error",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_transduction_rescue_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "expansion_type",
        "g_source",
        "flow_name",
        "generated",
        "equivalent",
        "area",
        "delay",
        "adp",
        "improved",
        "selected",
        "error",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def append_complement_candidates_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "case",
        "method",
        "flow_name",
        "flow_commands",
        "generated",
        "equivalent",
        "area",
        "delay",
        "adp",
        "improved",
        "selected",
        "error",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def is_equivalent(abc: Path, truth: Path, aig: Path, timeout: int, root: Path) -> bool:
    output = run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; &get; &cec -t {abc_path(aig, root)}", timeout, root)
    return "Networks are equivalent" in output


def measure_adp(abc: Path, aig: Path, timeout: int, root: Path) -> tuple[int, int, int]:
    output = run_abc(abc, f"read {abc_path(aig, root)}; ps", timeout, root)
    match = PS_RE.search(output)
    if not match:
        raise RuntimeError(f"Cannot parse ABC ps output:\n{output}")
    area = int(match.group(1))
    delay = int(match.group(2))
    return area, delay, area * delay


def npn_template_summary_for_case(truth: Path) -> str:
    try:
        fingerprint = fingerprint_case(truth)
    except Exception:
        return ""
    counts = Counter(output.npn_template for output in fingerprint.outputs if output.npn_template)
    if not counts:
        return ""
    return ";".join(f"{name}:{count}" for name, count in sorted(counts.items()))


def run_exact_npn_rescue_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_support: int,
    max_flows: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")

    tmp = logs / "tmp_exact_npn" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    template = npn_template_summary_for_case(truth)

    blif = tmp / f"{case}_small_support_exact.blif"
    generated, support_size, message = write_small_support_exact_blif(
        blif,
        f"{case}_small_support_exact",
        table,
        max_support,
    )
    if not generated:
        rows.append(
            {
                "case": case,
                "support_size": support_size,
                "method": "small_support_factored_truth",
                "template": template,
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": message,
            }
        )
        append_exact_npn_rescue_csv(logs / "exact_npn_rescue.csv", rows)
        print(f"[{case}] exact/NPN skipped: {message}")
        return rows, CaseSummary(
            case=case,
            baseline_area=base_area,
            baseline_delay=base_delay,
            baseline_adp=base_adp,
            best_area=base_area,
            best_delay=base_delay,
            best_adp=base_adp,
            improvement_ratio=1.0,
            selected_method="exact_npn_skipped",
        )

    initial = InitialCandidate("exact_npn_small_support", "blif", blif)
    deadline = time.monotonic() + timeout_per_case
    for flow in EXACT_NPN_RESCUE_FLOWS[:max(1, max_flows)]:
        remaining = max(1, int(deadline - time.monotonic()))
        row: dict[str, object] = {
            "case": case,
            "support_size": support_size,
            "method": "small_support_factored_truth",
            "template": template,
            "flow_name": flow.name,
            "generated": 1,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
        }
        if remaining <= 1:
            row["error"] = "case timeout before synthesis"
            rows.append(row)
            break
        candidate_aig = tmp / f"{case}_{flow.name}.aig"
        try:
            synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 120), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["error"] = "not equivalent"
        except subprocess.TimeoutExpired:
            row["error"] = "timeout"
        except Exception as exc:
            row["error"] = str(exc)[:500]
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_exact_npn_rescue_csv(logs / "exact_npn_rescue.csv", rows)
    if best_adp < base_adp:
        flow_name = selected_row.get("flow_name", "exact_npn") if selected_row else "exact_npn"
        print(f"[{case}] exact/NPN improved ADP {base_adp} -> {best_adp} via {flow_name}")
    else:
        print(f"[{case}] exact/NPN kept current ADP {base_adp}")

    return rows, CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="exact_npn_rescue" if best_adp < base_adp else "exact_npn_no_improvement",
    )


def transduction_variable_order(table: TruthTable, seed: int, case: str) -> list[int | None]:
    ranked: list[int | None] = []
    for var in sorted(range(table.num_inputs), key=lambda item: table.influences[item], reverse=True):
        if var not in ranked:
            ranked.append(var)
        if len([item for item in ranked if item is not None]) >= 3:
            break
    for var in sorted(range(table.num_inputs), key=lambda item: table.shannon_scores[item], reverse=True):
        if var not in ranked:
            ranked.append(var)
        if len([item for item in ranked if item is not None]) >= 5:
            break
    rng = random.Random(f"{seed}:{case}:transduction")
    remaining = [var for var in range(table.num_inputs) if var not in ranked]
    rng.shuffle(remaining)
    ranked.extend(remaining[:2])
    ranked.append(None)
    return ranked


def read_blif_interface(path: Path) -> tuple[list[str], list[str]]:
    input_names: list[str] = []
    output_names: list[str] = []
    logical = ""
    for physical in path.read_text(encoding="ascii", errors="ignore").splitlines():
        stripped = physical.rstrip()
        if stripped.endswith("\\"):
            logical += stripped[:-1] + " "
            continue
        line = logical + stripped
        logical = ""
        if line.startswith(".inputs "):
            input_names = line.split()[1:]
        elif line.startswith(".outputs "):
            output_names = line.split()[1:]
    return input_names, output_names


def wrap_transduction_blif_outputs(
    source: Path,
    target: Path,
    expansion_type: str,
    g_index: int | None,
) -> tuple[bool, str]:
    lines = source.read_text(encoding="ascii", errors="ignore").splitlines()
    input_names, output_names = read_blif_interface(source)
    if not output_names:
        return False, "cannot find BLIF outputs"
    if expansion_type != "double_not" and not input_names:
        return False, "cannot choose g from BLIF without inputs"
    g_name = "" if g_index is None else input_names[g_index % len(input_names)]
    new_outputs = [f"td_out{i}" for i in range(len(output_names))]
    wrapped: list[str] = []
    inserted = False
    skip_output_continuation = False

    for line in lines:
        if skip_output_continuation:
            skip_output_continuation = line.rstrip().endswith("\\")
            continue
        if line.startswith(".outputs "):
            wrapped.append(".outputs " + " ".join(new_outputs))
            skip_output_continuation = line.rstrip().endswith("\\")
            continue
        if line.startswith(".end"):
            if expansion_type in {"and_or", "or_and"}:
                not_g = "td_not_g"
                wrapped.append(f".names {g_name} {not_g}")
                wrapped.append("0 1")
            for index, (old, new) in enumerate(zip(output_names, new_outputs)):
                prefix = f"td_{index}_{expansion_type}"
                if expansion_type == "double_not":
                    inv = f"{prefix}_not"
                    wrapped.append(f".names {old} {inv}")
                    wrapped.append("0 1")
                    wrapped.append(f".names {inv} {new}")
                    wrapped.append("0 1")
                elif expansion_type == "and_or":
                    left = f"{prefix}_and_g"
                    right = f"{prefix}_and_not_g"
                    wrapped.append(f".names {old} {g_name} {left}")
                    wrapped.append("11 1")
                    wrapped.append(f".names {old} td_not_g {right}")
                    wrapped.append("11 1")
                    wrapped.append(f".names {left} {right} {new}")
                    wrapped.append("1- 1")
                    wrapped.append("-1 1")
                elif expansion_type == "or_and":
                    left = f"{prefix}_or_g"
                    right = f"{prefix}_or_not_g"
                    wrapped.append(f".names {old} {g_name} {left}")
                    wrapped.append("1- 1")
                    wrapped.append("-1 1")
                    wrapped.append(f".names {old} td_not_g {right}")
                    wrapped.append("1- 1")
                    wrapped.append("-1 1")
                    wrapped.append(f".names {left} {right} {new}")
                    wrapped.append("11 1")
                elif expansion_type == "mux":
                    wrapped.append(f".names {g_name} {old} {new}")
                    wrapped.append("01 1")
                    wrapped.append("11 1")
                else:
                    return False, f"unsupported expansion type: {expansion_type}"
            wrapped.append(".end")
            inserted = True
            continue
        wrapped.append(line)

    if not inserted:
        return False, "cannot find BLIF .end"
    target.write_text("\n".join(wrapped) + "\n", encoding="ascii")
    g_text = "none" if g_index is None else f"{g_name}@{g_index}"
    return True, g_text


def run_transduction_rescue_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    budget: int,
    seed: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")

    tmp = logs / "tmp_transduction" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    raw_blif = tmp / f"{case}_source.blif"
    run_abc(abc, f"read {abc_path(source, root)}; write_blif {abc_path(raw_blif, root)}", 120, root)

    variables = transduction_variable_order(table, seed, case)
    expansion_types = ["and_or", "or_and", "mux", "double_not"]
    tasks: list[tuple[str, int | None, PostFlow]] = []
    for expansion_type in expansion_types:
        for variable in variables:
            if expansion_type == "double_not" and variable is not None:
                continue
            if expansion_type != "double_not" and variable is None:
                continue
            for flow in TRANSDUCTION_REDUCTION_FLOWS:
                tasks.append((expansion_type, variable, flow))
    tasks = tasks[: max(1, budget)]
    deadline = time.monotonic() + timeout_per_case

    for index, (expansion_type, variable, flow) in enumerate(tasks):
        remaining = max(1, int(deadline - time.monotonic()))
        row: dict[str, object] = {
            "case": case,
            "expansion_type": expansion_type,
            "g_source": f"x{variable}" if variable is not None else "none",
            "flow_name": flow.name,
            "generated": 0,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
        }
        if remaining <= 1:
            row["error"] = "case timeout before expansion"
            rows.append(row)
            break

        expanded_blif = tmp / f"{case}_{index:02d}_{expansion_type}.blif"
        ok, g_text = wrap_transduction_blif_outputs(raw_blif, expanded_blif, expansion_type, variable)
        row["g_source"] = g_text
        if not ok:
            row["error"] = g_text
            rows.append(row)
            continue
        row["generated"] = 1

        initial = InitialCandidate(f"transduction_{expansion_type}", "blif", expanded_blif)
        candidate_aig = tmp / f"{case}_{index:02d}_{expansion_type}_{flow.name}.aig"
        try:
            synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 150), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["error"] = "not equivalent"
        except subprocess.TimeoutExpired:
            row["error"] = "timeout"
        except Exception as exc:
            row["error"] = str(exc)[:500]
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_transduction_rescue_csv(logs / "transduction_rescue.csv", rows)
    if best_adp < base_adp:
        expansion = selected_row.get("expansion_type", "transduction") if selected_row else "transduction"
        print(f"[{case}] transduction improved ADP {base_adp} -> {best_adp} via {expansion}")
    else:
        print(f"[{case}] transduction kept current ADP {base_adp}")

    return rows, CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="transduction_rescue" if best_adp < base_adp else "transduction_no_improvement",
    )


def run_complement_rescue_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    seed: int,
    budget: int,
    use_bdd: bool,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        source.parent.mkdir(parents=True, exist_ok=True)
        run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(source, root)}", 120, root)

    tmp = logs / "tmp_complement" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    initials = make_complement_initial_candidates(case, table, tmp, seed, use_bdd)
    pairs = choose_candidate_pairs(initials, POST_FLOWS, max(1, budget))
    if not pairs:
        rows.append(
            {
                "case": case,
                "method": "none",
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": "no complement candidates generated",
            }
        )

    for index, (initial, flow) in enumerate(pairs):
        remaining = max(1, int(deadline - time.monotonic()))
        row: dict[str, object] = {
            "case": case,
            "method": initial.method,
            "flow_name": flow.name,
            "flow_commands": flow.commands,
            "generated": 1,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
        }
        if remaining <= 1:
            row["error"] = "case timeout before synthesis"
            rows.append(row)
            break
        candidate_aig = tmp / f"{case}_{index:03d}_{initial.method}_{flow.name}.aig"
        try:
            synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 150), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["error"] = "not equivalent"
        except subprocess.TimeoutExpired:
            row["error"] = "timeout"
        except Exception as exc:
            row["error"] = str(exc)[:500]
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_complement_candidates_csv(logs / "complement_candidates.csv", rows)
    if best_adp < base_adp:
        method = selected_row.get("method", "complement") if selected_row else "complement"
        print(f"[{case}] complement improved ADP {base_adp} -> {best_adp} via {method}")
    else:
        print(f"[{case}] complement kept current ADP {base_adp}")

    return rows, CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method=(
            f"complement/{selected_row.get('method')}/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "complement_no_improvement"
        ),
    )


def run_specialized_generators_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    exact_max_inputs: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        source.parent.mkdir(parents=True, exist_ok=True)
        run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(source, root)}", 120, root)

    tmp = logs / "tmp_specialized_generators" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    generated = make_exact_specialized_candidates(case, table, truth, tmp, exact_max_inputs)
    if not generated:
        rows.append(
            {
                "case": case,
                "function_type": "none",
                "generator": "none",
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": "no complete exact-match structural generator available",
            }
        )

    for initial, function_type, generator in generated:
        for flow in SPECIALIZED_GENERATOR_FLOWS:
            remaining = max(1, int(deadline - time.monotonic()))
            row: dict[str, object] = {
                "case": case,
                "function_type": function_type,
                "generator": generator,
                "flow_name": flow.name,
                "flow_commands": flow.commands,
                "generated": 1,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
            }
            if remaining <= 1:
                row["error"] = "case timeout before synthesis"
                rows.append(row)
                break
            candidate_aig = tmp / f"{case}_{generator}_{flow.name}.aig"
            try:
                synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 150), root)
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if equivalent:
                    area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                    improved = adp < best_adp
                    row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                    if improved:
                        best_area, best_delay, best_adp = area, delay, adp
                        best_aig = candidate_aig
                else:
                    row["error"] = "not equivalent"
            except subprocess.TimeoutExpired:
                row["error"] = "timeout"
            except Exception as exc:
                row["error"] = str(exc)[:500]
            rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_specialized_generators_csv(logs / "specialized_generators.csv", rows)
    if best_adp < base_adp:
        print(f"[{case}] specialized improved ADP {base_adp} -> {best_adp}")
    else:
        print(f"[{case}] specialized kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method=(
            f"specialized/{selected_row.get('generator')}/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "specialized/no_improvement"
        ),
    )
    return rows, summary


def ttopt_output_groups(num_outputs: int) -> list[int]:
    groups = [num_outputs]
    for group in (4, 2, 1):
        if group < num_outputs and num_outputs % group == 0:
            groups.append(group)
    return groups


def run_ttopt_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        source.parent.mkdir(parents=True, exist_ok=True)
        run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(source, root)}", 120, root)

    tmp = logs / "tmp_ttopt_structural" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    best_group: int | None = None
    best_rounds: int | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    for group in ttopt_output_groups(table.num_outputs):
        rounds = 40 if group == table.num_outputs or group == 4 else 20
        for flow in TTOPT_STRUCTURAL_POLISH_FLOWS:
            remaining = max(1, int(deadline - time.monotonic()))
            row: dict[str, object] = {
                "case": case,
                "input_support": table.num_inputs,
                "output_group": group,
                "rounds": rounds,
                "flow_name": flow.name,
                "flow_commands": flow.commands,
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
            }
            if remaining <= 1:
                row["error"] = "case timeout before synthesis"
                rows.append(row)
                break
            candidate_aig = tmp / f"{case}_i{table.num_inputs}_o{group}_x{rounds}_{flow.name}.aig"
            command = (
                f"read_truth -xf {abc_path(truth, root)}; st; &get; "
                f"&ttopt -I {table.num_inputs} -O {group} -X {rounds}; &put; "
                f"{flow.commands}; write_aiger -s {abc_path(candidate_aig, root)}"
            )
            try:
                run_abc(abc, command, min(remaining, 240), root)
                row["generated"] = 1
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if equivalent:
                    area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                    improved = adp < best_adp
                    row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                    if adp <= best_adp:
                        if improved:
                            best_area, best_delay, best_adp = area, delay, adp
                        best_aig = candidate_aig
                        best_group = group
                        best_rounds = rounds
                else:
                    row["error"] = "not equivalent"
            except subprocess.TimeoutExpired:
                row["error"] = "timeout"
            except Exception as exc:
                row["error"] = str(exc)[:500]
            rows.append(row)

    remaining = max(1, int(deadline - time.monotonic()))
    if best_aig is not None and remaining > 1:
        candidate_aig = tmp / f"{case}_ttopt_best_transduction_level.aig"
        row = {
            "case": case,
            "input_support": table.num_inputs,
            "output_group": best_group if best_group is not None else "",
            "rounds": best_rounds if best_rounds is not None else "",
            "flow_name": "ttopt_level_preserving_transduction",
            "flow_commands": "&transduction -T 1 -S 0 -I 0 -R 0 -V 0 -l; strash; dc2; balance",
            "generated": 0,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
        }
        command = (
            f"read {abc_path(best_aig, root)}; &get; "
            "&transduction -T 1 -S 0 -I 0 -R 0 -V 0 -l; &put; "
            f"strash; dc2; balance; write_aiger -s {abc_path(candidate_aig, root)}"
        )
        try:
            run_abc(abc, command, min(remaining, 240), root)
            row["generated"] = 1
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["error"] = "not equivalent"
        except subprocess.TimeoutExpired:
            row["error"] = "timeout"
        except Exception as exc:
            row["error"] = str(exc)[:500]
        rows.append(row)

    remaining = max(1, int(deadline - time.monotonic()))
    repeat_source = best_aig if best_aig is not None else source
    if (
        table.num_inputs == table.num_outputs
        and best_area <= 3000
        and remaining > 1
    ):
        candidate_aig = tmp / f"{case}_ttopt_repeat_transduction_level.aig"
        row = {
            "case": case,
            "input_support": table.num_inputs,
            "output_group": best_group if best_group is not None else "",
            "rounds": best_rounds if best_rounds is not None else "",
            "flow_name": "ttopt_repeated_level_preserving_transduction",
            "flow_commands": "&transduction -T 4 -S 0 -I 0 -R 0 -V 0 -l; strash; dc2; balance",
            "generated": 0,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
        }
        command = (
            f"read {abc_path(repeat_source, root)}; &get; "
            "&transduction -T 4 -S 0 -I 0 -R 0 -V 0 -l; &put; "
            f"strash; dc2; balance; write_aiger -s {abc_path(candidate_aig, root)}"
        )
        try:
            run_abc(abc, command, min(remaining, 240), root)
            row["generated"] = 1
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["error"] = "not equivalent"
        except subprocess.TimeoutExpired:
            row["error"] = "timeout"
        except Exception as exc:
            row["error"] = str(exc)[:500]
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_ttopt_structural_csv(logs / "ttopt_structural.csv", rows)
    if best_adp < base_adp:
        print(f"[{case}] ttopt structural improved ADP {base_adp} -> {best_adp}")
    else:
        print(f"[{case}] ttopt structural kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method=(
            f"ttopt_structural/o{selected_row.get('output_group')}/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "ttopt_structural/no_improvement"
        ),
    )
    return rows, summary


def run_mockturtle_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    mockturtle_bin: Path,
    explicit_mode: str | None = None,
    max_modes: int = 2,
    exact_max_inputs: int = 12,
) -> list[dict[str, object]]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        source.parent.mkdir(parents=True, exist_ok=True)
        run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(source, root)}", 120, root)

    tmp = logs / "tmp_mockturtle_structural" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    fingerprint = fingerprint_case(truth)
    exact_matches = exact_matches_for_truth(truth, max_expensive_inputs=exact_max_inputs)
    exact_types = exact_type_hints_for_mockturtle(exact_matches)
    if explicit_mode is not None:
        modes = [explicit_mode]
        fingerprint_reason = f"explicit mode; labels={','.join(fingerprint.labels) or 'general'}"
    else:
        modes, fingerprint_reason = select_structural_mockturtle_modes(
            fingerprint,
            base_area,
            base_delay,
            base_adp,
            exact_types,
            max_modes,
        )

    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case
    for mode in modes:
        if mode not in STRUCTURAL_MOCKTURTLE_MODES:
            rows.append(
                {
                    "case": case,
                    "mode": mode,
                    "fingerprint_reason": fingerprint_reason,
                    "generated": 0,
                    "equivalent": 0,
                    "improved": 0,
                    "error": f"unsupported mode: {mode}",
                }
            )
            continue

        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            rows.append(
                {
                    "case": case,
                    "mode": mode,
                    "fingerprint_reason": fingerprint_reason,
                    "generated": 0,
                    "equivalent": 0,
                    "improved": 0,
                    "error": "case timeout before mockturtle generation",
                }
            )
            break

        raw_aig = tmp / f"{case}_{mode}_raw.aig"
        try:
            run_structural_mockturtle_opt(mockturtle_bin, truth, source, raw_aig, mode, min(remaining, 180), root)
        except subprocess.TimeoutExpired:
            rows.append(
                {
                    "case": case,
                    "mode": mode,
                    "fingerprint_reason": fingerprint_reason,
                    "generated": 0,
                    "equivalent": 0,
                    "improved": 0,
                    "error": "mockturtle generation timeout",
                }
            )
            continue
        except Exception as exc:
            rows.append(
                {
                    "case": case,
                    "mode": mode,
                    "fingerprint_reason": fingerprint_reason,
                    "generated": 0,
                    "equivalent": 0,
                    "improved": 0,
                    "error": str(exc)[:500],
                }
            )
            continue

        for flow in MOCKTURTLE_STRUCTURAL_POLISH_FLOWS:
            remaining = max(1, int(deadline - time.monotonic()))
            row: dict[str, object] = {
                "case": case,
                "mode": f"{mode}+{flow.name}",
                "fingerprint_reason": fingerprint_reason,
                "generated": 1,
                "equivalent": 0,
                "improved": 0,
            }
            if remaining <= 1:
                row["error"] = "case timeout before ABC polish"
                rows.append(row)
                break

            candidate_aig = tmp / f"{case}_{mode}_{flow.name}.aig"
            try:
                polish_aig(abc, raw_aig, flow, candidate_aig, min(remaining, 120), root)
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if equivalent:
                    area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                    improved = adp < best_adp
                    row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                    if improved:
                        shutil.copyfile(candidate_aig, source)
                        best_area, best_delay, best_adp = area, delay, adp
                else:
                    row["error"] = "not equivalent"
            except subprocess.TimeoutExpired:
                row["error"] = "ABC polish/check timeout"
            except Exception as exc:
                row["error"] = str(exc)[:500]
            rows.append(row)

    append_mockturtle_candidates_csv(logs / "mockturtle_candidates.csv", rows)
    append_mockturtle_structural_summary_csv(
        logs / "mockturtle_structural_summary.csv",
        [
            {
                "case": case,
                "base_area": base_area,
                "base_delay": base_delay,
                "base_adp": base_adp,
                "best_area": best_area,
                "best_delay": best_delay,
                "best_adp": best_adp,
                "improvement": base_adp - best_adp,
                "modes": ";".join(modes),
                "exact_types": ";".join(sorted(exact_types))[:500],
                "generated": sum(int(row.get("generated", 0)) for row in rows),
                "equivalent": sum(int(row.get("equivalent", 0)) for row in rows),
            }
        ],
    )
    if best_adp < base_adp:
        print(f"[{case}] mockturtle structural improved ADP {base_adp} -> {best_adp} ({best_area}/{best_delay})")
    else:
        print(f"[{case}] mockturtle structural kept current ADP {base_adp}")
    return rows


def run_type_guided_refine_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_flows: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = logs / "tmp_type_guided" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    fingerprint = fingerprint_case(truth)
    family, reason, flows = select_type_guided_flows(fingerprint, base_area, base_delay, base_adp, max_flows)
    labels = "|".join(fingerprint.labels)
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    for index, flow in enumerate(flows):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            rows.append(
                {
                    "case": case,
                    "family": family,
                    "labels": labels,
                    "reason": reason,
                    "flow_name": flow.name,
                    "flow_commands": flow.commands,
                    "equivalent": 0,
                    "improved": 0,
                    "selected": 0,
                    "status": "TIMEOUT",
                }
            )
            break
        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        row: dict[str, object] = {
            "case": case,
            "family": family,
            "labels": labels,
            "reason": reason,
            "flow_name": flow.name,
            "flow_commands": flow.commands,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
            "status": "ERROR",
        }
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 120), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "status": "OK"})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception:
            row["status"] = "ERROR"
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_type_guided_csv(logs / "type_guided_refine.csv", rows)
    if best_adp < base_adp:
        flow_name = selected_row.get("flow_name", "type_guided") if selected_row else "type_guided"
        print(f"[{case}] {family} improved ADP {base_adp} -> {best_adp} via {flow_name}")
    else:
        print(f"[{case}] {family} kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method=f"type_guided/{family}",
    )
    return rows, summary


def run_objective_guided_refine_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_per_objective: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = logs / "tmp_objective_guided" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    for index, (objective, flow) in enumerate(select_objective_guided_flows(max_per_objective)):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            rows.append(
                {
                    "case": case,
                    "objective": objective,
                    "flow_name": flow.name,
                    "flow_commands": flow.commands,
                    "equivalent": 0,
                    "improved": 0,
                    "selected": 0,
                    "status": "TIMEOUT",
                }
            )
            break

        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        row: dict[str, object] = {
            "case": case,
            "objective": objective,
            "flow_name": flow.name,
            "flow_commands": flow.commands,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
            "status": "ERROR",
        }
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 150), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "status": "OK"})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception:
            row["status"] = "ERROR"
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_objective_guided_csv(logs / "objective_guided_refine.csv", rows)
    if best_adp < base_adp:
        flow_name = selected_row.get("flow_name", "objective_guided") if selected_row else "objective_guided"
        objective = selected_row.get("objective", "objective") if selected_row else "objective"
        print(f"[{case}] {objective} improved ADP {base_adp} -> {best_adp} via {flow_name}")
    else:
        print(f"[{case}] objective-guided kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="objective_guided",
    )
    return rows, summary


def run_micro_guided_refine_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_flows: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = logs / "tmp_micro_guided" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    for index, flow in enumerate(select_micro_guided_flows(base_area, base_adp, max_flows)):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            rows.append(
                {
                    "case": case,
                    "flow_name": flow.name,
                    "flow_commands": flow.commands,
                    "equivalent": 0,
                    "improved": 0,
                    "selected": 0,
                    "status": "TIMEOUT",
                }
            )
            break

        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        row: dict[str, object] = {
            "case": case,
            "flow_name": flow.name,
            "flow_commands": flow.commands,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
            "status": "ERROR",
        }
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 90), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 60), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 60), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "status": "OK"})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception:
            row["status"] = "ERROR"
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_micro_guided_csv(logs / "micro_guided_refine.csv", rows)
    if best_adp < base_adp:
        flow_name = selected_row.get("flow_name", "micro_guided") if selected_row else "micro_guided"
        print(f"[{case}] micro improved ADP {base_adp} -> {best_adp} via {flow_name}")
    else:
        print(f"[{case}] micro-guided kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="micro_guided",
    )
    return rows, summary


def run_small_case_refine_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_flows: int,
    area_threshold: int,
    adp_threshold: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = logs / "tmp_small_case" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    fingerprint = fingerprint_case(truth)
    labels = "|".join(fingerprint.labels) or "general"
    strategy = fingerprint.recommended_strategy
    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    rows: list[dict[str, object]] = []

    is_small = base_area <= area_threshold or base_adp <= adp_threshold
    if not is_small:
        rows.append(
            {
                "case": case,
                "labels": labels,
                "recommended_strategy": strategy,
                "base_area": base_area,
                "base_delay": base_delay,
                "base_adp": base_adp,
                "equivalent": 1,
                "improved": 0,
                "selected": 0,
                "status": "SKIPPED_NOT_SMALL",
            }
        )
        append_small_case_csv(logs / "small_case_refine.csv", rows)
        summary = CaseSummary(
            case=case,
            baseline_area=base_area,
            baseline_delay=base_delay,
            baseline_adp=base_adp,
            best_area=base_area,
            best_delay=base_delay,
            best_adp=base_adp,
            improvement_ratio=1.0,
            selected_method="small_case_skipped",
        )
        return rows, summary

    deadline = time.monotonic() + timeout_per_case
    for index, flow in enumerate(select_small_case_flows(max_flows)):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            rows.append(
                {
                    "case": case,
                    "labels": labels,
                    "recommended_strategy": strategy,
                    "base_area": base_area,
                    "base_delay": base_delay,
                    "base_adp": base_adp,
                    "flow_name": flow.name,
                    "flow_commands": flow.commands,
                    "equivalent": 0,
                    "improved": 0,
                    "selected": 0,
                    "status": "TIMEOUT",
                }
            )
            break

        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        row: dict[str, object] = {
            "case": case,
            "labels": labels,
            "recommended_strategy": strategy,
            "base_area": base_area,
            "base_delay": base_delay,
            "base_adp": base_adp,
            "flow_name": flow.name,
            "flow_commands": flow.commands,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
            "status": "ERROR",
        }
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 90), root)
            equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 60), root)
            row["equivalent"] = int(equivalent)
            if equivalent:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 60), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "status": "OK"})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception:
            row["status"] = "ERROR"
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_small_case_csv(logs / "small_case_refine.csv", rows)
    if best_adp < base_adp:
        flow_name = selected_row.get("flow_name", "small_case") if selected_row else "small_case"
        print(f"[{case}] small-case improved ADP {base_adp} -> {best_adp} via {flow_name}")
    else:
        print(f"[{case}] small-case kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="small_case_refine",
    )
    return rows, summary


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
    tmp = logs / "tmp" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

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


def write_results_csv(path: Path, rows: list[CandidateResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case",
                "initial_method",
                "flow_name",
                "flow_commands",
                "area",
                "delay",
                "adp",
                "equivalent",
                "selected",
                "status",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
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
                }
            )


def append_results_csv(path: Path, rows: list[CandidateResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case",
                "initial_method",
                "flow_name",
                "flow_commands",
                "area",
                "delay",
                "adp",
                "equivalent",
                "selected",
                "status",
            ],
        )
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(
                {
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
                }
            )


def write_summary_csv(path: Path, rows: list[CaseSummary]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case",
                "baseline_area",
                "baseline_delay",
                "baseline_adp",
                "best_area",
                "best_delay",
                "best_adp",
                "improvement_ratio",
                "selected_method",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case": row.case,
                    "baseline_area": row.baseline_area,
                    "baseline_delay": row.baseline_delay,
                    "baseline_adp": row.baseline_adp,
                    "best_area": row.best_area,
                    "best_delay": row.best_delay,
                    "best_adp": row.best_adp,
                    "improvement_ratio": f"{row.improvement_ratio:.6f}",
                    "selected_method": row.selected_method,
                }
            )


def measure_baseline_truth_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    logs: Path,
    root: Path,
) -> tuple[int, int, int]:
    tmp = logs / "tmp_final_summary" / case
    tmp.mkdir(parents=True, exist_ok=True)
    truth = benchmarks / f"{case}.truth"
    aig = tmp / f"{case}_abc_truth_baseline.aig"
    run_abc(abc, f"read_truth -xf {abc_path(truth, root)}; st; write_aiger -s {abc_path(aig, root)}", 120, root)
    return measure_adp(abc, aig, 120, root)


def selected_methods_from_logs(logs: Path) -> dict[str, str]:
    selected: dict[str, str] = {}
    for row in load_candidate_history(logs):
        if row.get("selected") in ("1", "True", "true"):
            case = row.get("case", "")
            method = row.get("initial_method", "")
            flow = row.get("flow_name", "")
            if case:
                selected[case] = f"{method}/{flow}".strip("/")
    method_logs = [
        ("specialized", "specialized_generators.csv", ("generator", "flow_name")),
        ("mockturtle", "mockturtle_candidates.csv", ("mode", "")),
        ("exact_npn", "exact_npn_rescue.csv", ("method", "flow_name")),
        ("transduction", "transduction_rescue.csv", ("expansion_type", "flow_name")),
        ("complement", "complement_candidates.csv", ("method", "flow_name")),
    ]
    for prefix, filename, keys in method_logs:
        for row in read_result_rows(logs / filename):
            if row.get("selected") in ("1", "True", "true"):
                case = row.get("case", "")
                left = row.get(keys[0], "") if keys[0] else ""
                right = row.get(keys[1], "") if keys[1] else ""
                if case:
                    selected[case] = f"{prefix}/{left}/{right}".strip("/")
    return selected


def count_selected_improvement_cases(logs: Path, filename: str) -> int:
    cases: set[str] = set()
    for row in read_result_rows(logs / filename):
        if row.get("selected") in ("1", "True", "true") or row.get("improved") in ("1", "True", "true"):
            case = row.get("case", "")
            if case:
                cases.add(case)
    return len(cases)


def write_final_summary_csv(
    path: Path,
    results: list[CandidateResult],
    logs: Path,
    abc: Path,
    benchmarks: Path,
    root: Path,
) -> None:
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
        "row_type",
        "case",
        "baseline_area",
        "baseline_delay",
        "baseline_adp",
        "best_area",
        "best_delay",
        "best_adp",
        "improvement_ratio",
        "selected_method",
        "equivalent",
        "total_adp",
        "equivalent_count",
        "exact_function_matches",
        "specialized_improved_cases",
        "mockturtle_improved_cases",
        "exact_npn_improved_cases",
        "transduction_improved_cases",
        "complement_improved_cases",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            assert row.area is not None and row.delay is not None and row.adp is not None
            baseline_area, baseline_delay, baseline_adp = measure_baseline_truth_case(row.case, abc, benchmarks, logs, root)
            writer.writerow(
                {
                    "row_type": "case",
                    "case": row.case,
                    "baseline_area": baseline_area,
                    "baseline_delay": baseline_delay,
                    "baseline_adp": baseline_adp,
                    "best_area": row.area,
                    "best_delay": row.delay,
                    "best_adp": row.adp,
                    "improvement_ratio": f"{baseline_adp / row.adp:.6f}" if row.adp else "",
                    "selected_method": selected_methods.get(row.case, row.initial_method + "/" + row.flow_name),
                    "equivalent": int(row.equivalent),
                }
            )
        writer.writerow(
            {
                "row_type": "aggregate",
                "case": "ALL",
                "equivalent": int(equivalent_count == len(results)),
                "total_adp": total_adp,
                "equivalent_count": equivalent_count,
                "exact_function_matches": len(exact_rows),
                "specialized_improved_cases": method_counts["specialized"],
                "mockturtle_improved_cases": method_counts["mockturtle"],
                "exact_npn_improved_cases": method_counts["exact_npn"],
                "transduction_improved_cases": method_counts["transduction"],
                "complement_improved_cases": method_counts["complement"],
            }
        )


def format_case_analysis(case: str, table: TruthTable) -> str:
    influence_text = ", ".join(f"x{i}:{value:.4f}" for i, value in enumerate(table.influences))
    score_text = ", ".join(f"x{i}:{value:.4f}" for i, value in enumerate(table.shannon_scores))
    active_text = ", ".join(f"x{i}" for i in table.active_vars) or "(none)"
    return "\n".join(
        [
            f"case: {case}",
            f"inputs: {table.num_inputs}",
            f"outputs: {table.num_outputs}",
            f"minterms/output: {table.num_minterms}",
            f"on_count: {table.on_count}",
            f"off_count: {table.off_count}",
            f"density: {table.density:.6f}",
            f"active_vars: {active_text}",
            f"influences: {influence_text}",
            f"balanced_shannon_scores: {score_text}",
        ]
    )


def print_report_stats(results: list[CandidateResult], summaries: list[CaseSummary]) -> None:
    selected = [row for row in results if row.selected]
    frontier_size = sum(len(pareto_frontier([row for row in results if row.case == summary.case])) for summary in summaries)
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


def truth_output_value(table: TruthTable, index: int) -> int:
    value = 0
    for output_index, bits in enumerate(table.outputs):
        value |= bits[index] << output_index
    return value


def truth_input_value(index: int, num_inputs: int, order: list[int]) -> int:
    value = 0
    for bit_index, var in enumerate(order):
        value |= truth_bit(index, num_inputs, var) << bit_index
    return value


def operand_mappings(num_inputs: int) -> list[tuple[str, list[int], list[int]]]:
    if num_inputs % 2:
        return []
    half = num_inputs // 2
    base = [
        ("half", list(range(half)), list(range(half, num_inputs))),
        ("even_odd", list(range(0, num_inputs, 2)), list(range(1, num_inputs, 2))),
        ("odd_even", list(range(1, num_inputs, 2)), list(range(0, num_inputs, 2))),
    ]
    mappings: list[tuple[str, list[int], list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for prefix, left_group, right_group in base:
        for left_name, left_order in (("le", left_group), ("be", list(reversed(left_group)))):
            for right_name, right_order in (("le", right_group), ("be", list(reversed(right_group)))):
                for swap_name, a_order, b_order in (
                    ("ab", left_order, right_order),
                    ("ba", right_order, left_order),
                ):
                    key = tuple(a_order + [-1] + b_order)
                    if key in seen:
                        continue
                    seen.add(key)
                    mappings.append((f"{prefix}_{left_name}_{right_name}_{swap_name}", a_order[:], b_order[:]))
    return mappings


def match_binary_template(
    table: TruthTable,
    predicate,
) -> tuple[str, list[int], list[int]] | None:
    if table.num_inputs % 2:
        return None
    mask = (1 << table.num_outputs) - 1
    for name, a_order, b_order in operand_mappings(table.num_inputs):
        matches = True
        for index in range(table.num_minterms):
            a_value = truth_input_value(index, table.num_inputs, a_order)
            b_value = truth_input_value(index, table.num_inputs, b_order)
            if truth_output_value(table, index) != (predicate(a_value, b_value, len(a_order)) & mask):
                matches = False
                break
        if matches:
            return name, a_order, b_order
    return None


def validate_template_case(case: str, table: TruthTable) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    def add(template: str, mapping: str, detail: str) -> None:
        rows.append({"case": case, "template": template, "matched": "1", "mapping": mapping, "detail": detail})

    unsigned_mul = detect_unsigned_multiplier(table)
    if unsigned_mul is not None:
        add("unsigned_multiplier", "detector", f"a={unsigned_mul[0]};b={unsigned_mul[1]}")
    signed_mul = detect_signed_multiplier(table)
    if signed_mul is not None:
        add("signed_multiplier", "detector", f"a={signed_mul[0]};b={signed_mul[1]}")
    square = detect_unsigned_square(table)
    if square is not None:
        add("unsigned_square", "detector", f"x={square}")
    divider = detect_unsigned_divider_quotient(table)
    if divider is not None:
        add("divider_quotient", "detector", f"divisor={divider[0]};dividend={divider[1]}")
    sqrt_order = detect_unsigned_sqrt(table)
    if sqrt_order is not None:
        add("integer_sqrt", "detector", f"x={sqrt_order}")

    if table.num_inputs % 2 == 0:
        width = table.num_inputs // 2
        out_mask = (1 << table.num_outputs) - 1
        validators = [
            ("adder_sum", lambda a, b, w: a + b),
            ("adder_carry_mask", lambda a, b, w: out_mask if a + b >= (1 << w) else 0),
            ("divider_remainder_sat", lambda a, b, w: out_mask if b == 0 else a % b),
            ("comparator_eq_mask", lambda a, b, w: out_mask if a == b else 0),
            ("comparator_lt_mask", lambda a, b, w: out_mask if a < b else 0),
            ("comparator_le_mask", lambda a, b, w: out_mask if a <= b else 0),
        ]
        for template, fn in validators:
            match = match_binary_template(table, fn)
            if match is not None:
                mapping, a_order, b_order = match
                add(template, mapping, f"a={a_order};b={b_order}")
    if not rows:
        rows.append({"case": case, "template": "none", "matched": "0", "mapping": "", "detail": ""})
    return rows


def write_complement_truth(path: Path, table: TruthTable) -> None:
    groups = []
    for bits in table.outputs:
        groups.append("".join(str(bit ^ 1) for bit in reversed(bits)))
    path.write_text("\n".join(groups) + "\n", encoding="ascii")


def wrap_inverted_blif_outputs(source: Path, target: Path) -> None:
    lines = source.read_text(encoding="ascii", errors="ignore").splitlines()
    _input_names, output_names = read_blif_interface(source)
    if not output_names:
        raise RuntimeError(f"cannot find BLIF outputs in {source}")
    new_outputs = [f"y{i}" for i in range(len(output_names))]
    wrapped: list[str] = []
    skip_output_continuation = False
    for line in lines:
        if skip_output_continuation:
            skip_output_continuation = line.rstrip().endswith("\\")
            continue
        if line.startswith(".outputs "):
            wrapped.append(".outputs " + " ".join(new_outputs))
            skip_output_continuation = line.rstrip().endswith("\\")
        elif line.startswith(".end"):
            for old, new in zip(output_names, new_outputs):
                wrapped.append(f".names {old} {new}")
                wrapped.append("0 1")
            wrapped.append(".end")
        else:
            wrapped.append(line)
    target.write_text("\n".join(wrapped) + "\n", encoding="ascii")


def run_validate_templates(benchmarks: Path, logs: Path) -> None:
    rows: list[dict[str, str]] = []
    for case in ALL_CASES:
        table = read_truth(benchmarks / f"{case}.truth")
        rows.extend(validate_template_case(case, table))
    path = logs / "template_validation.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case", "template", "matched", "mapping", "detail"])
        writer.writeheader()
        writer.writerows(rows)
    matched = [row for row in rows if row["matched"] == "1"]
    print(f"[validate] wrote {path}")
    print(f"[validate] matched template rows: {len(matched)}")


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


def diagnose_case(case: str, area: int, delay: int, adp: int, table: TruthTable, rows: list[dict[str, str]]) -> str:
    if adp < 5000:
        return "already_good"
    selected = [row for row in rows if row.get("selected") in ("1", "True", "true")]
    selected_method = selected[0].get("initial_method", "") if selected else ""
    template_rows = [row for row in rows if "template_" in row.get("initial_method", "")]
    if template_rows and "template_" not in selected_method:
        template_best = min(row_int(row, "adp", 10**30) for row in template_rows if row.get("adp", ""))
        best = min([row_int(row, "adp", 10**30) for row in rows if row.get("adp", "")] or [adp])
        if template_best > best:
            return "template_mismatch"
    bdd_values = [row_int(row, "adp", 10**30) for row in rows if "bdd" in row.get("initial_method", "") and row.get("adp", "")]
    if bdd_values and min(bdd_values) <= int(adp * 1.08) and "bdd" not in selected_method:
        return "bdd_ordering_sensitive"
    if area > 25000 and delay <= 22:
        return "area_bottleneck"
    if delay > 25 and area < 20000:
        return "delay_bottleneck"
    if table.density < 0.08 or table.density > 0.92:
        return "area_bottleneck"
    return "balanced_bottleneck"


def run_diagnose_results(abc: Path, benchmarks: Path, output: Path, logs: Path, root: Path) -> None:
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
    ranked: list[tuple[str, int, int, int]] = []
    for case in ALL_CASES:
        aig = output / f"{case}.aig"
        if not aig.is_file():
            continue
        area, delay, adp = measure_adp(abc, aig, 120, root)
        ranked.append((case, area, delay, adp))
    return sorted(ranked, key=lambda item: item[3], reverse=True)


def run_rescue_worst(args: argparse.Namespace, root: Path) -> None:
    ranked = rank_current_outputs(args.abc, args.output, root)[: max(1, args.rescue_worst)]
    rows: list[dict[str, str]] = []
    for case, before_area, before_delay, before_adp in ranked:
        print(f"[rescue] {case} before ADP={before_adp}")
        candidates, summary = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            args.max_candidates,
            args.seed,
            args.timeout_per_case,
            root,
            True,
            not args.no_bdd,
            args.polish_after_synthesis,
            args.try_complement,
            args.history_guided_ga,
        )
        if args.bdd_sift:
            sift_rows = bdd_sift_case(case, args.abc, args.benchmarks, args.output, args.logs, args.timeout_per_case, root)
            candidates.extend(sift_rows)
        after_area, after_delay, after_adp = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)
        rows.append(
            {
                "case": case,
                "before_area": str(before_area),
                "before_delay": str(before_delay),
                "before_adp": str(before_adp),
                "after_area": str(after_area),
                "after_delay": str(after_delay),
                "after_adp": str(after_adp),
                "delta_adp": str(before_adp - after_adp),
                "selected_method": summary.selected_method,
            }
        )
        print(f"[rescue] {case} after ADP={after_adp} delta={before_adp - after_adp}")
    path = args.logs / "rescue_worst_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["case"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[rescue] wrote {path}")


def make_history_guided_ga_flows(case: str, logs: Path, seed: int, count: int) -> list[PostFlow]:
    rows = read_result_rows(logs / "reproduce_candidates.csv") or read_result_rows(logs / "results.csv")
    equivalent = [row for row in rows if row.get("equivalent") in ("1", "True", "true") and row.get("flow_commands", "")]
    same_case = [row for row in equivalent if row.get("case") == case]
    pool = same_case or equivalent
    pool = sorted(pool, key=lambda row: row_int(row, "adp", 10**30))[: max(4, count)]
    rng = random.Random(f"{seed}:{case}:history_ga")
    flows: list[PostFlow] = []
    seen: set[str] = set()
    parents = [split_commands(row.get("flow_commands", "")) for row in pool if row.get("flow_commands", "")]
    if not parents:
        return []
    attempts = 0
    while len(flows) < count and attempts < count * 30:
        attempts += 1
        parent = rng.choice(parents)
        child = mutate_flow(parent, rng)
        if rng.random() < 0.25 and len(parents) > 1:
            child = crossover_flow(child, rng.choice(parents), rng)
        commands = join_commands(child)
        if commands and commands not in seen:
            seen.add(commands)
            flows.append(PostFlow(f"history_ga_{len(flows)}", commands))
    return flows


def bdd_sift_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
) -> list[CandidateResult]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    if len(table.active_vars) > 18:
        return []
    tmp = logs / "tmp_bdd_sift" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    current_aig = output / f"{case}.aig"
    best_area, best_delay, best_adp = measure_adp(abc, current_aig, 120, root)
    order = sorted(table.active_vars, key=lambda var: table.shannon_scores[var], reverse=True)
    rows: list[CandidateResult] = []
    deadline = time.monotonic() + timeout_per_case
    improved = True
    while improved and time.monotonic() < deadline:
        improved = False
        for pos in range(len(order) - 1):
            if time.monotonic() >= deadline:
                break
            trial = order[:]
            trial[pos], trial[pos + 1] = trial[pos + 1], trial[pos]
            blif = tmp / f"{case}_sift_{len(rows):03d}.blif"
            result = CandidateResult(case, "bdd_sift", f"swap_{pos}_{pos + 1}", "llm_mix_1", aig=tmp / f"{case}_sift_{len(rows):03d}.aig")
            try:
                write_bdd_blif(blif, f"{case}_bdd_sift", table, trial, node_limit=160000)
                synthesize(abc, truth, InitialCandidate("bdd_sift", "blif", blif), PostFlow("llm_mix_1", "rewrite -z; refactor -z; dc2; rewrite -z; balance"), result.aig, 120, root)
                result.equivalent = is_equivalent(abc, truth, result.aig, 90, root)
                if result.equivalent:
                    result.area, result.delay, result.adp = measure_adp(abc, result.aig, 90, root)
                    result.status = "OK"
                    if result.adp is not None and result.adp < best_adp:
                        shutil.copyfile(result.aig, current_aig)
                        best_area, best_delay, best_adp = result.area, result.delay, result.adp
                        order = trial
                        result.selected = True
                        improved = True
                else:
                    result.status = "NOT_EQUIV"
            except subprocess.TimeoutExpired:
                result.status = "TIMEOUT"
            except Exception:
                result.status = "ERROR"
            rows.append(result)
            if improved:
                break
    path = logs / "bdd_sifting.csv"
    existing = path.is_file()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case", "flow_name", "area", "delay", "adp", "equivalent", "selected", "status"])
        if not existing:
            writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case": row.case,
                    "flow_name": row.flow_name,
                    "area": row.area if row.area is not None else "",
                    "delay": row.delay if row.delay is not None else "",
                    "adp": row.adp if row.adp is not None else "",
                    "equivalent": int(row.equivalent),
                    "selected": int(row.selected),
                    "status": row.status,
                }
            )
    return rows


def flow_family(flow_name: str, commands: str) -> str:
    text = f"{flow_name} {commands}".lower()
    if "history_ga" in text or "ga_" in text:
        return "ga"
    if "dch" in text or "if -" in text:
        return "delay"
    if "dc2" in text or "resub" in text or "mfs" in text:
        return "area"
    if "balance" in text and ("rewrite" in text or "refactor" in text):
        return "balanced"
    if "fraig" in text or "choice" in text:
        return "fraig_choice"
    if flow_name == "identity":
        return "baseline"
    return "other"


def load_candidate_history(logs: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name in ("reproduce_candidates.csv", "coverage_candidates.csv", "results.csv"):
        for row in read_result_rows(logs / name):
            rows.append(row)
    return rows


def build_case_coverage(
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    root: Path,
) -> list[dict[str, str]]:
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


def run_case_coverage_report(args: argparse.Namespace, root: Path) -> list[dict[str, str]]:
    rows = build_case_coverage(args.abc, args.benchmarks, args.output, args.logs, root)
    write_case_coverage_report(rows, args.logs)
    return rows


def run_complete_all_cases(args: argparse.Namespace, root: Path) -> None:
    rounds = 0
    while True:
        coverage = build_case_coverage(args.abc, args.benchmarks, args.output, args.logs, root)
        under = [row for row in coverage if row["under_covered"] == "1"]
        if not under:
            print("[complete] all cases satisfy coverage contract")
            write_case_coverage_report(coverage, args.logs)
            return
        rounds += 1
        if rounds > 3:
            print("[complete] stopping after 3 passes; remaining under-covered cases are recorded")
            write_case_coverage_report(coverage, args.logs)
            return
        print(f"[complete] pass {rounds}: {len(under)} under-covered cases")
        for row in under:
            case = row["case"]
            print(f"[complete] {case}: {row['under_covered_reasons']}")
            case_rows, _ = optimize_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                max(args.min_candidates, args.max_candidates),
                args.seed + rounds,
                args.timeout_per_case,
                root,
                True,
                True,
                True,
                True,
                args.history_guided_ga,
            )
            append_results_csv(args.logs / "coverage_candidates.csv", case_rows)


def run_round_robin_optimize(args: argparse.Namespace, root: Path) -> None:
    rows: list[dict[str, str]] = []
    for round_index in range(max(1, args.rounds)):
        family = ["abc_portfolio", "bdd_shannon", "sop_pos_complement", "history_guided_ga", "near_miss_rescue"][round_index % 5]
        print(f"[round-robin] round {round_index + 1}/{args.rounds}: {family}")
        for case in ALL_CASES:
            before = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)[2] if (args.output / f"{case}.aig").is_file() else 0
            use_bdd = family in ("bdd_shannon", "history_guided_ga", "near_miss_rescue")
            use_ga = family in ("abc_portfolio", "history_guided_ga", "near_miss_rescue")
            try_complement = family in ("sop_pos_complement", "history_guided_ga", "near_miss_rescue")
            use_polish = family == "near_miss_rescue"
            case_rows, _ = optimize_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                max(1, args.candidates_per_round),
                args.seed + round_index,
                args.timeout_per_case,
                root,
                use_ga,
                use_bdd,
                use_polish,
                try_complement,
                family == "history_guided_ga",
            )
            append_results_csv(args.logs / "coverage_candidates.csv", case_rows)
            after = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)[2]
            rows.append({"round": str(round_index + 1), "case": case, "family": family, "before_adp": str(before), "after_adp": str(after), "delta_adp": str(before - after)})
    path = args.logs / "round_robin_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["round", "case", "family", "before_adp", "after_adp", "delta_adp"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"[round-robin] wrote {path}")


def run_score_aware_optimize(args: argparse.Namespace, root: Path) -> None:
    total_budget = max(1, args.total_budget)
    base_budget = 30
    max_per_case = max(base_budget, total_budget // 10)
    coverage = build_case_coverage(args.abc, args.benchmarks, args.output, args.logs, root)
    scores: list[tuple[float, str, dict[str, str]]] = []
    max_adp = max(int(row["current_best_adp"]) for row in coverage if row["current_best_adp"]) or 1
    for row in coverage:
        ratio = float(row["improvement_ratio"])
        low_ratio = max(0.0, 1.05 - ratio)
        low_coverage = max(0.0, (50 - int(row["candidates_tried"])) / 50)
        low_diversity = max(0.0, (5 - int(row["flow_families_tried"])) / 5)
        high_adp = int(row["current_best_adp"]) / max_adp
        score = 3.0 * low_ratio + 2.0 * low_coverage + 1.5 * low_diversity + high_adp
        scores.append((score, row["case"], row))
    scores.sort(reverse=True)
    budgets = {case: base_budget for _, case, _ in scores}
    remaining = max(0, total_budget - base_budget * len(scores))
    index = 0
    while remaining > 0 and scores:
        _, case, _ = scores[index % len(scores)]
        if budgets[case] < max_per_case:
            budgets[case] += 1
            remaining -= 1
        index += 1
        if index > total_budget * 2:
            break
    schedule_path = args.logs / "score_aware_schedule.csv"
    summary_path = args.logs / "score_aware_summary.csv"
    args.logs.mkdir(parents=True, exist_ok=True)
    with schedule_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "budget", "priority_score"])
        for score, case, _ in scores:
            writer.writerow([case, budgets[case], f"{score:.6f}"])
    summary_rows = []
    for score, case, _ in scores:
        budget = budgets[case]
        if budget <= 0:
            continue
        before = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)[2] if (args.output / f"{case}.aig").is_file() else 0
        case_rows, _ = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            min(budget, max_per_case),
            args.seed,
            args.timeout_per_case,
            root,
            True,
            True,
            True,
            True,
            args.history_guided_ga,
        )
        append_results_csv(args.logs / "coverage_candidates.csv", case_rows)
        after = measure_adp(args.abc, args.output / f"{case}.aig", 120, root)[2]
        summary_rows.append({"case": case, "budget": str(budget), "before_adp": str(before), "after_adp": str(after), "delta_adp": str(before - after)})
    with summary_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case", "budget", "before_adp", "after_adp", "delta_adp"])
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"[score-aware] wrote {schedule_path}")
    print(f"[score-aware] wrote {summary_path}")


def append_contest_schedule_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file()
    fieldnames = [
        "stage",
        "case",
        "before_adp",
        "after_adp",
        "delta_adp",
        "status",
        "elapsed_sec",
        "detail",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def current_case_adp(abc: Path, output: Path, case: str, root: Path) -> int:
    aig = output / f"{case}.aig"
    if not aig.is_file():
        return 0
    return measure_adp(abc, aig, 120, root)[2]


def run_contest_optimize(args: argparse.Namespace, root: Path) -> None:
    cases = selected_cases_from_args(args)
    deadline = time.monotonic() + max(1, args.time_budget)
    schedule_path = args.logs / "contest_optimize_schedule.csv"
    if schedule_path.exists():
        schedule_path.unlink()

    def remaining() -> int:
        return max(1, int(deadline - time.monotonic()))

    def run_stage(stage: str, case: str, fn) -> None:
        if time.monotonic() >= deadline:
            return
        before = current_case_adp(args.abc, args.output, case, root)
        start = time.monotonic()
        status = "OK"
        detail = ""
        try:
            detail = fn(case)
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
        except Exception as exc:
            status = "ERROR"
            detail = str(exc)[:500]
        after = current_case_adp(args.abc, args.output, case, root)
        append_contest_schedule_csv(
            schedule_path,
            [
                {
                    "stage": stage,
                    "case": case,
                    "before_adp": before,
                    "after_adp": after,
                    "delta_adp": before - after,
                    "status": status,
                    "elapsed_sec": f"{time.monotonic() - start:.2f}",
                    "detail": detail,
                }
            ],
        )

    print(f"[contest] cases={len(cases)}, time_budget={args.time_budget}s")

    exact_rows = []
    for case in cases:
        if time.monotonic() >= deadline:
            break

        def exact_stage(current_case: str) -> str:
            matches = exact_matches_for_truth(args.benchmarks / f"{current_case}.truth", max_expensive_inputs=args.exact_max_inputs)
            exact_rows.extend(matches)
            return f"matches={len(matches)}"

        run_stage("exact_match", case, exact_stage)
    if exact_rows:
        write_exact_function_matches_csv(args.logs / "exact_function_matches.csv", exact_rows)

    fair_stages = [
        "base_coverage",
        "complement",
        "specialized",
        "mockturtle",
        "exact_npn",
        "transduction",
    ]
    ok_mockturtle, mockturtle_error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)

    for stage in fair_stages:
        for case in cases:
            if time.monotonic() >= deadline:
                break
            stage_timeout = min(args.timeout_per_case, max(15, remaining() // max(1, len(cases))))
            if stage == "base_coverage":
                def base_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows, _summary = optimize_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        max(8, min(args.min_candidates, args.max_candidates)),
                        args.seed,
                        timeout,
                        root,
                        True,
                        True,
                        False,
                        True,
                        args.history_guided_ga,
                    )
                    append_results_csv(args.logs / "coverage_candidates.csv", rows)
                    return f"rows={len(rows)}"

                run_stage(stage, case, base_stage)
            elif stage == "complement":
                def complement_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows, _summary = run_complement_rescue_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        timeout,
                        root,
                        args.seed,
                        args.complement_budget,
                        not args.no_bdd,
                    )
                    return f"rows={len(rows)}"

                run_stage(stage, case, complement_stage)
            elif stage == "specialized":
                def specialized_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows, _summary = run_specialized_generators_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        timeout,
                        root,
                        args.exact_max_inputs,
                    )
                    return f"rows={len(rows)}"

                run_stage(stage, case, specialized_stage)
            elif stage == "mockturtle":
                if not ok_mockturtle:
                    append_contest_schedule_csv(
                        schedule_path,
                        [
                            {
                                "stage": stage,
                                "case": case,
                                "status": "SKIPPED",
                                "detail": mockturtle_error,
                            }
                        ],
                    )
                    continue

                def mockturtle_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows = run_mockturtle_structural_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        timeout,
                        root,
                        args.mockturtle_structural_bin,
                        None,
                        args.mockturtle_max_modes,
                        args.exact_max_inputs,
                    )
                    return f"rows={len(rows)}"

                run_stage(stage, case, mockturtle_stage)
            elif stage == "exact_npn":
                def npn_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows, _summary = run_exact_npn_rescue_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        timeout,
                        root,
                        args.npn_max_support,
                        args.npn_max_flows,
                    )
                    return f"rows={len(rows)}"

                run_stage(stage, case, npn_stage)
            elif stage == "transduction":
                def transduction_stage(current_case: str, timeout: int = stage_timeout) -> str:
                    rows, _summary = run_transduction_rescue_case(
                        current_case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        timeout,
                        root,
                        args.transduction_budget,
                        args.seed,
                    )
                    return f"rows={len(rows)}"

                run_stage(stage, case, transduction_stage)

    coverage = build_case_coverage(args.abc, args.benchmarks, args.output, args.logs, root)
    write_case_coverage_report(coverage, args.logs)
    print(f"[contest] wrote {schedule_path}")


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


def run_reproduce_best(args: argparse.Namespace, root: Path) -> tuple[list[CandidateResult], list[CaseSummary]]:
    step_results: list[CandidateResult] = []
    write_reproduce_recipe(args.logs)
    print(format_reproduce_recipe())
    print("")
    print("[reproduce] stage 1/18: full hybrid synthesis search")
    for case in ALL_CASES:
        print(f"[{case}] optimizing")
        rows, summary = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_MAIN_MAX_CANDIDATES,
            REPRODUCE_SEED,
            args.timeout_per_case,
            root,
            True,
            True,
            False,
        )
        step_results.extend(rows)
        selected = next(row for row in rows if row.selected)
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    for range_index, (start_case, end_case) in enumerate(REPRODUCE_ARITHMETIC_RANGES, start=2):
        print(f"[reproduce] stage {range_index}/18: focused arithmetic range {start_case}-{end_case}")
        for case in inclusive_cases(start_case, end_case):
            print(f"[{case}] optimizing focused range")
            rows, summary = optimize_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                REPRODUCE_FOCUSED_MAX_CANDIDATES,
                REPRODUCE_SEED,
                args.timeout_per_case,
                root,
                False,
                True,
                False,
            )
            step_results.extend(rows)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    print(
        f"[reproduce] stage 5/18: focused divider quotient range "
        f"{REPRODUCE_DIVIDER_RANGE[0]}-{REPRODUCE_DIVIDER_RANGE[1]}"
    )
    for case in inclusive_cases(*REPRODUCE_DIVIDER_RANGE):
        print(f"[{case}] optimizing focused divider range")
        rows, summary = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_FOCUSED_MAX_CANDIDATES,
            REPRODUCE_SEED,
            args.timeout_per_case,
            root,
            False,
            True,
            False,
        )
        step_results.extend(rows)
        selected = next(row for row in rows if row.selected)
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    print(
        f"[reproduce] stage 6/18: focused square-root range "
        f"{REPRODUCE_SQRT_RANGE[0]}-{REPRODUCE_SQRT_RANGE[1]}"
    )
    for case in inclusive_cases(*REPRODUCE_SQRT_RANGE):
        print(f"[{case}] optimizing focused sqrt range")
        rows, summary = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_FOCUSED_MAX_CANDIDATES,
            REPRODUCE_SEED,
            args.timeout_per_case,
            root,
            False,
            True,
            False,
        )
        step_results.extend(rows)
        selected = next(row for row in rows if row.selected)
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    print("[reproduce] stage 7/18: focused diagnosis-driven rescue cases")
    for case in REPRODUCE_RESCUE_CASES:
        print(f"[{case}] optimizing focused rescue case")
        rows, summary = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_RESCUE_MAX_CANDIDATES,
            REPRODUCE_RESCUE_SEED,
            args.timeout_per_case,
            root,
            True,
            True,
            True,
            True,
            True,
        )
        step_results.extend(rows)
        selected = next(row for row in rows if row.selected)
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    print("[reproduce] stage 8/18: equivalence-checked polish passes")
    for pass_index in range(REPRODUCE_POLISH_PASSES):
        pass_summaries: list[CaseSummary] = []
        print(f"[polish] pass {pass_index + 1}/{REPRODUCE_POLISH_PASSES}")
        for case in ALL_CASES:
            print(f"[{case}] polishing existing output")
            rows, summary = polish_existing_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.try_mockturtle,
                args.mockturtle_bin,
            )
            step_results.extend(rows)
            pass_summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
        baseline_total = sum(row.baseline_adp for row in pass_summaries)
        best_total = sum(row.best_adp for row in pass_summaries)
        print(f"[polish] pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
        if best_total >= baseline_total:
            print("[polish] converged: no pass-level ADP improvement")
            break

    print("[reproduce] stage 9/18: deterministic all-case refinement package")
    for pass_index in range(REPRODUCE_SWEEP_PASSES):
        pass_summaries = []
        print(f"[refine] all cases pass {pass_index + 1}/{REPRODUCE_SWEEP_PASSES}")
        for case in ALL_CASES:
            print(f"[{case}] sweeping existing output")
            rows, summary = sweep_existing_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.try_mockturtle,
                args.mockturtle_bin,
            )
            step_results.extend(rows)
            pass_summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
        baseline_total = sum(row.baseline_adp for row in pass_summaries)
        best_total = sum(row.best_adp for row in pass_summaries)
        print(f"[refine] all cases pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
        if best_total >= baseline_total:
            print("[refine] converged: no pass-level ADP improvement")
            break

    front_cases = inclusive_cases(*REPRODUCE_FRONT_RANGE)
    for pass_index in range(REPRODUCE_SWEEP_PASSES):
        pass_summaries = []
        print(f"[refine] focused {REPRODUCE_FRONT_RANGE[0]}-{REPRODUCE_FRONT_RANGE[1]} pass {pass_index + 1}/{REPRODUCE_SWEEP_PASSES}")
        for case in front_cases:
            print(f"[{case}] sweeping existing output")
            rows, summary = sweep_existing_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
            )
            step_results.extend(rows)
            pass_summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
        baseline_total = sum(row.baseline_adp for row in pass_summaries)
        best_total = sum(row.best_adp for row in pass_summaries)
        print(f"[refine] focused pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
        if best_total >= baseline_total:
            print("[refine] focused range converged: no pass-level ADP improvement")
            break

    print("[reproduce] stage 10/18: final all-case deterministic refinement package")
    for pass_index in range(REPRODUCE_FINAL_SWEEP_PASSES):
        pass_summaries = []
        print(f"[refine] final all cases pass {pass_index + 1}/{REPRODUCE_FINAL_SWEEP_PASSES}")
        for case in ALL_CASES:
            print(f"[{case}] sweeping existing output")
            rows, summary = sweep_existing_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.try_mockturtle,
                args.mockturtle_bin,
            )
            step_results.extend(rows)
            pass_summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
        baseline_total = sum(row.baseline_adp for row in pass_summaries)
        best_total = sum(row.best_adp for row in pass_summaries)
        print(f"[refine] final pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
        if best_total >= baseline_total:
            print("[refine] final all-case package converged: no pass-level ADP improvement")
            break

    print("[reproduce] stage 11/18: fingerprint-guided mockturtle structural resynthesis")
    ok, error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)
    if not ok:
        print(f"[mockturtle-structural] unavailable, skipping: {error}")
    else:
        for case in ALL_CASES:
            print(f"[{case}] mockturtle structural")
            run_mockturtle_structural_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                REPRODUCE_MOCKTURTLE_STRUCTURAL_TIMEOUT,
                root,
                args.mockturtle_structural_bin,
                None,
            )

    print("[reproduce] stage 12/18: final type-guided circuit-family refinement")
    for case in ALL_CASES:
        print(f"[{case}] type-guided refine")
        run_type_guided_refine_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_TYPE_GUIDED_TIMEOUT,
            root,
            REPRODUCE_TYPE_GUIDED_MAX_FLOWS,
        )

    print("[reproduce] stage 13/18: objective-guided area/delay/balanced refinement")
    for case in ALL_CASES:
        print(f"[{case}] objective-guided refine")
        run_objective_guided_refine_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_OBJECTIVE_GUIDED_TIMEOUT,
            root,
            REPRODUCE_OBJECTIVE_MAX_PER_FAMILY,
        )

    print("[reproduce] stage 14/18: micro-guided per-case refinement")
    for case in ALL_CASES:
        print(f"[{case}] micro-guided refine")
        run_micro_guided_refine_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_MICRO_GUIDED_TIMEOUT,
            root,
            REPRODUCE_MICRO_MAX_FLOWS,
        )

    print("[reproduce] stage 15/18: small-case targeted refinement")
    for case in ALL_CASES:
        print(f"[{case}] small-case refine")
        run_small_case_refine_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_SMALL_CASE_TIMEOUT,
            root,
            REPRODUCE_SMALL_CASE_MAX_FLOWS,
            REPRODUCE_SMALL_CASE_AREA_THRESHOLD,
            REPRODUCE_SMALL_CASE_ADP_THRESHOLD,
        )

    print("[reproduce] stage 16/18: final advanced mockturtle structural refinement")
    ok, error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)
    if not ok:
        print(f"[mockturtle-structural] unavailable, skipping: {error}")
    else:
        for case in ALL_CASES:
            print(f"[{case}] final advanced mockturtle structural")
            run_mockturtle_structural_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                REPRODUCE_FINAL_ADVANCED_MOCKTURTLE_TIMEOUT,
                root,
                args.mockturtle_structural_bin,
                None,
            )

    print("[reproduce] stage 17/18: truth-table structural resynthesis and level-preserving transduction")
    for case in ALL_CASES:
        print(f"[{case}] ttopt structural")
        run_ttopt_structural_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            REPRODUCE_TTOPT_STRUCTURAL_TIMEOUT,
            root,
        )

    print("[reproduce] stage 18/18: deterministic micro-guided fixed-point convergence")
    for pass_index in range(REPRODUCE_MICRO_CONVERGENCE_PASSES):
        pass_summaries: list[CaseSummary] = []
        print(f"[micro-converge] pass {pass_index + 1}/{REPRODUCE_MICRO_CONVERGENCE_PASSES}")
        for case in ALL_CASES:
            print(f"[{case}] micro-guided convergence")
            _rows, summary = run_micro_guided_refine_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                REPRODUCE_MICRO_CONVERGENCE_TIMEOUT,
                root,
                REPRODUCE_MICRO_MAX_FLOWS,
            )
            pass_summaries.append(summary)
        baseline_total = sum(row.baseline_adp for row in pass_summaries)
        best_total = sum(row.best_adp for row in pass_summaries)
        print(f"[micro-converge] pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
        if best_total >= baseline_total:
            print("[micro-converge] converged: no pass-level ADP improvement")
            break

    write_results_csv(args.logs / "reproduce_candidates.csv", step_results)
    final_results, final_summaries = verify_final_outputs(ALL_CASES, args.abc, args.benchmarks, args.output, root)
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
) -> tuple[list[CandidateResult], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = logs / "tmp_polish" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

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
    tmp = logs / "tmp_sweep" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

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
    parser.add_argument("--show-reproduce-recipe", action="store_true", help="print the deterministic reproduce-best stage recipe and exit")
    parser.add_argument("--write-contest-plan", action="store_true", help="write or locate the contest optimization plan and exit")
    parser.add_argument("--analyze-case", help="print truth-table features and exit")
    parser.add_argument("--classify-case", help="print Boolean fingerprint/classification and exit")
    parser.add_argument("--exact-function-report", action="store_true", help="write exact function recognition matches and exit")
    parser.add_argument("--exact-match-all", action="store_true", help="alias for exact function recognition over the selected cases")
    parser.add_argument("--verify-final", action="store_true", help="verify current output AIGs and refresh results/summary logs")
    parser.add_argument("--write-final-summary", action="store_true", help="verify current outputs and write report-ready final_summary.csv")
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
    parser.add_argument(
        "--mockturtle-structural-bin",
        type=Path,
        default=Path("student/mockturtle_opt/mockturtle_opt"),
        help="path to the structural mockturtle optimizer binary",
    )
    parser.add_argument("--report-stats", action="store_true", help="print report-oriented aggregate statistics")
    parser.add_argument("--ablation-report", action="store_true", help="summarize candidate history and method wins")
    parser.add_argument("--diagnose-results", action="store_true", help="classify current outputs by likely optimization bottleneck")
    parser.add_argument("--rescue-worst", type=int, metavar="K", help="rerun focused rescue on the K highest-ADP current outputs")
    parser.add_argument("--try-complement", action="store_true", help="try complement-first synthesis candidates")
    parser.add_argument("--complement-rescue", action="store_true", help="run generic complement synthesis wrapper candidates")
    parser.add_argument("--complement-budget", type=int, default=16, help="maximum complement wrapper candidates per case")
    parser.add_argument("--bdd-sift", action="store_true", help="try local adjacent-swap BDD order search during rescue")
    parser.add_argument("--validate-templates", action="store_true", help="write exact arithmetic/template validation CSV")
    parser.add_argument("--history-guided-ga", action="store_true", help="seed GA flows from historical winning flows")
    parser.add_argument("--case-coverage-report", action="store_true", help="write per-case optimization coverage report")
    parser.add_argument("--complete-all-cases", action="store_true", help="optimize every under-covered case until coverage improves")
    parser.add_argument("--min-candidates", type=int, default=50, help="minimum candidates per under-covered case")
    parser.add_argument("--round-robin-optimize", action="store_true", help="visit every case in family-rotating rounds")
    parser.add_argument("--rounds", type=int, default=5, help="number of round-robin optimization rounds")
    parser.add_argument("--candidates-per-round", type=int, default=10, help="candidate budget per case per round")
    parser.add_argument("--score-aware-optimize", action="store_true", help="allocate candidate budget from coverage and ADP diagnostics")
    parser.add_argument("--total-budget", type=int, default=5000, help="total candidate budget for score-aware scheduling")
    parser.add_argument("--contest-optimize", action="store_true", help="run fair contest-style scheduler over all selected cases")
    parser.add_argument("--case-fair-next-optimize", action="store_true", help="run the next deterministic fair refinement package on every selected case")
    parser.add_argument("--time-budget", type=int, default=3600, help="wall-clock time budget in seconds for --contest-optimize")
    parser.add_argument("--type-guided-refine", action="store_true", help="classify every selected case and run a fixed type-specific refinement package")
    parser.add_argument("--type-guided-max-flows", type=int, default=5, help="maximum type-guided ABC refinement flows per case")
    parser.add_argument("--objective-guided-refine", action="store_true", help="try fixed area-first, delay-first, and balanced refinement packages per case")
    parser.add_argument("--objective-max-per-family", type=int, default=3, help="maximum objective-guided flows from each objective family")
    parser.add_argument("--micro-guided-refine", action="store_true", help="try small-circuit micro refinement flows on every selected case")
    parser.add_argument("--micro-max-flows", type=int, default=4, help="maximum micro-guided refinement flows per case")
    parser.add_argument("--small-case-refine", action="store_true", help="run a small-case-only refinement package selected by current area/ADP")
    parser.add_argument("--specialized-generators", action="store_true", help="run exact-match structural generators and accept only ADP improvements")
    parser.add_argument("--specialized-generate", action="store_true", help="alias for --specialized-generators")
    parser.add_argument("--ttopt-structural", action="store_true", help="run truth-table BDD/MUX structural synthesis with ABC &ttopt")
    parser.add_argument("--exact-npn-rescue", action="store_true", help="run exact small-support/NPN-style rescue candidates")
    parser.add_argument("--npn-max-support", type=int, default=6, help="maximum per-output support for exact small-support rescue")
    parser.add_argument("--npn-max-flows", type=int, default=4, help="maximum ABC reductions for exact small-support rescue")
    parser.add_argument("--transduction-rescue", action="store_true", help="run bounded equivalent expansion/reduction rescue")
    parser.add_argument("--transduction-budget", type=int, default=12, help="maximum transduction candidates per case")
    parser.add_argument("--small-max-flows", type=int, default=5, help="maximum small-case refinement flows per selected case")
    parser.add_argument("--small-area-threshold", type=int, default=2500, help="treat current outputs with area at or below this as small cases")
    parser.add_argument("--small-adp-threshold", type=int, default=50000, help="treat current outputs with ADP at or below this as small cases")
    return parser.parse_args()


def selected_cases_from_args(args: argparse.Namespace, override_case: str | None = None) -> list[str]:
    if override_case:
        return [override_case]
    if args.case:
        return [args.case]
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
    write_pareto_candidates_csv(args.logs / "pareto_candidates.csv", results)
    if write_final_summary:
        write_final_summary_csv(args.logs / "final_summary.csv", results, args.logs, args.abc, args.benchmarks, root)
    equivalent_count = sum(1 for row in results if row.equivalent)
    total_adp = sum(row.adp or 0 for row in results if row.equivalent)
    print("------------------------------------------------------")
    print(f"Equivalent cases: {equivalent_count}/{len(results)}")
    print(f"Total ADP over equivalent cases: {total_adp}")
    if write_final_summary:
        print(f"[final-summary] wrote {args.logs / 'final_summary.csv'}")
    return results, summaries


def write_contest_plan_file(root: Path) -> Path:
    path = root / "student" / "CONTEST_OPT_PLAN.md"
    if not path.is_file():
        path.write_text(
            "\n".join(
                [
                    "# Contest-Style AIG Optimization Plan",
                    "",
                    "The full contest-style plan is normally maintained in this file.",
                    "Run the optimizer phases with equivalence-gated candidates only.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    return path


def run_case_fair_next_optimize(args: argparse.Namespace, root: Path) -> None:
    """Run one deterministic, case-fair improvement package over selected cases."""
    cases = selected_cases_from_args(args)
    args.logs.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    mockturtle_ok, mockturtle_error = (False, "not requested in case-fair follow-up pass")
    if args.try_mockturtle:
        mockturtle_ok, mockturtle_error = ensure_structural_mockturtle(args.mockturtle_structural_bin, root)
    global_deadline = time.monotonic() + max(1, args.time_budget)
    result_path = args.logs / "case_fair_next_optimize.csv"
    fieldnames = [
        "case",
        "stage",
        "status",
        "before_area",
        "before_delay",
        "before_adp",
        "after_area",
        "after_delay",
        "after_adp",
        "improved",
        "error",
    ]

    def write_progress() -> None:
        with result_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    def measure_current(case: str) -> tuple[int, int, int]:
        aig = args.output / f"{case}.aig"
        return measure_adp(args.abc, aig, 120, root)

    for case in cases:
        if time.monotonic() >= global_deadline:
            print("[case-fair] global time budget reached")
            break
        print(f"[{case}] case-fair next optimize")
        case_deadline = min(global_deadline, time.monotonic() + max(1, args.timeout_per_case))
        try:
            start_area, start_delay, start_adp = measure_current(case)
        except Exception as exc:
            rows.append(
                {
                    "case": case,
                    "stage": "initial_measure",
                    "status": "ERROR",
                    "before_adp": "",
                    "after_adp": "",
                    "improved": 0,
                    "error": str(exc)[:500],
                }
            )
            write_progress()
            continue

        stages: list[tuple[str, object, dict[str, object]]] = [
            (
                "objective_guided",
                run_objective_guided_refine_case,
                {
                    "max_per_objective": min(1, max(1, args.objective_max_per_family)),
                },
            ),
            (
                "micro_guided",
                run_micro_guided_refine_case,
                {
                    "max_flows": 1,
                },
            ),
            (
                "small_case",
                run_small_case_refine_case,
                {
                    "max_flows": 1,
                    "area_threshold": args.small_area_threshold,
                    "adp_threshold": args.small_adp_threshold,
                },
            ),
            (
                "complement",
                run_complement_rescue_case,
                {
                    "seed": args.seed,
                    "budget": min(2, max(1, args.complement_budget)),
                    "use_bdd": not args.no_bdd,
                },
            ),
        ]

        for stage_index, (stage_name, stage_func, extra) in enumerate(stages):
            remaining = int(case_deadline - time.monotonic())
            if remaining <= 2:
                rows.append(
                    {
                        "case": case,
                        "stage": stage_name,
                        "status": "SKIP_TIMEOUT",
                        "before_adp": measure_current(case)[2],
                        "after_adp": "",
                        "improved": 0,
                        "error": "case time budget reached",
                    }
                )
                continue
            stages_left = len(stages) - stage_index + (1 if args.try_mockturtle and mockturtle_ok and args.mockturtle_max_modes > 0 else 0)
            stage_timeout = min(2, max(1, remaining // max(1, stages_left)))
            before_area, before_delay, before_adp = measure_current(case)
            try:
                if stage_name == "objective_guided":
                    _stage_rows, _summary = stage_func(
                        case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        stage_timeout,
                        root,
                        extra["max_per_objective"],
                    )
                elif stage_name == "micro_guided":
                    _stage_rows, _summary = stage_func(
                        case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        stage_timeout,
                        root,
                        extra["max_flows"],
                    )
                elif stage_name == "small_case":
                    _stage_rows, _summary = stage_func(
                        case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        stage_timeout,
                        root,
                        extra["max_flows"],
                        extra["area_threshold"],
                        extra["adp_threshold"],
                    )
                else:
                    _stage_rows, _summary = stage_func(
                        case,
                        args.abc,
                        args.benchmarks,
                        args.output,
                        args.logs,
                        stage_timeout,
                        root,
                        extra["seed"],
                        extra["budget"],
                        extra["use_bdd"],
                    )
                after_area, after_delay, after_adp = measure_current(case)
                rows.append(
                    {
                        "case": case,
                        "stage": stage_name,
                        "status": "OK",
                        "before_area": before_area,
                        "before_delay": before_delay,
                        "before_adp": before_adp,
                        "after_area": after_area,
                        "after_delay": after_delay,
                        "after_adp": after_adp,
                        "improved": int(after_adp < before_adp),
                        "error": "",
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "case": case,
                        "stage": stage_name,
                        "status": "ERROR",
                        "before_area": before_area,
                        "before_delay": before_delay,
                        "before_adp": before_adp,
                        "after_area": "",
                        "after_delay": "",
                        "after_adp": "",
                        "improved": 0,
                        "error": str(exc)[:500],
                    }
                )

        remaining = int(case_deadline - time.monotonic())
        if args.try_mockturtle and mockturtle_ok and args.mockturtle_max_modes > 0 and remaining > 2:
            before_area, before_delay, before_adp = measure_current(case)
            try:
                run_mockturtle_structural_case(
                    case,
                    args.abc,
                    args.benchmarks,
                    args.output,
                    args.logs,
                    remaining,
                    root,
                    args.mockturtle_structural_bin,
                    None,
                    1,
                    args.exact_max_inputs,
                )
                after_area, after_delay, after_adp = measure_current(case)
                rows.append(
                    {
                        "case": case,
                        "stage": "mockturtle_structural",
                        "status": "OK",
                        "before_area": before_area,
                        "before_delay": before_delay,
                        "before_adp": before_adp,
                        "after_area": after_area,
                        "after_delay": after_delay,
                        "after_adp": after_adp,
                        "improved": int(after_adp < before_adp),
                        "error": "",
                    }
                )
            except Exception as exc:
                rows.append(
                    {
                        "case": case,
                        "stage": "mockturtle_structural",
                        "status": "ERROR",
                        "before_area": before_area,
                        "before_delay": before_delay,
                        "before_adp": before_adp,
                        "after_area": "",
                        "after_delay": "",
                        "after_adp": "",
                        "improved": 0,
                        "error": str(exc)[:500],
                    }
                )
        elif args.try_mockturtle and not mockturtle_ok:
            rows.append(
                {
                    "case": case,
                    "stage": "mockturtle_structural",
                    "status": "SKIP",
                    "before_adp": start_adp,
                    "after_adp": "",
                    "improved": 0,
                    "error": mockturtle_error,
                }
            )
        elif args.try_mockturtle:
            rows.append(
                {
                    "case": case,
                    "stage": "mockturtle_structural",
                    "status": "SKIP_TIMEOUT",
                    "before_adp": measure_current(case)[2],
                    "after_adp": "",
                    "improved": 0,
                    "error": "case time budget reached",
                }
            )

        final_area, final_delay, final_adp = measure_current(case)
        print(f"[{case}] case-fair ADP {start_adp} -> {final_adp}")
        rows.append(
            {
                "case": case,
                "stage": "case_total",
                "status": "OK",
                "before_area": start_area,
                "before_delay": start_delay,
                "before_adp": start_adp,
                "after_area": final_area,
                "after_delay": final_delay,
                "after_adp": final_adp,
                "improved": int(final_adp < start_adp),
                "error": "",
            }
        )
        write_progress()

    write_progress()
    run_verify_final(args, root, write_final_summary=True)


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    if args.show_reproduce_recipe:
        print(format_reproduce_recipe())
        return 0
    if args.write_contest_plan:
        plan_path = write_contest_plan_file(root)
        print(f"[contest-plan] {plan_path}")
        return 0
    if args.verify_final or args.write_final_summary:
        run_verify_final(args, root, args.write_final_summary)
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
        exact_rows = exact_matches_for_truth(truth, max_expensive_inputs=12)
        write_exact_function_matches_csv(args.logs / "exact_function_matches.csv", exact_rows)
        print("")
        print(format_exact_matches(exact_rows))
        table = read_truth(truth)
        square_order = detect_unsigned_square(table)
        multiplier_orders = detect_unsigned_multiplier(table)
        signed_multiplier_orders = detect_signed_multiplier(table)
        divider_orders = detect_unsigned_divider_quotient(table)
        sqrt_order = detect_unsigned_sqrt(table)
        if square_order is not None:
            order_text = ", ".join(f"x{var}" for var in square_order)
            print("\nStructural arithmetic detector:")
            print(f"- unsigned_square: confidence=1.000, lsb_to_msb_order={order_text}")
            print("- recommended_strategy: template_unsigned_square + ABC post-optimization")
        if multiplier_orders is not None:
            a_order, b_order = multiplier_orders
            a_text = ", ".join(f"x{var}" for var in a_order)
            b_text = ", ".join(f"x{var}" for var in b_order)
            print("\nStructural arithmetic detector:")
            print(f"- unsigned_multiplier: confidence=1.000, a_lsb_to_msb={a_text}, b_lsb_to_msb={b_text}")
            print("- recommended_strategy: template_unsigned_multiplier + ABC post-optimization")
        if signed_multiplier_orders is not None:
            a_order, b_order = signed_multiplier_orders
            a_text = ", ".join(f"x{var}" for var in a_order)
            b_text = ", ".join(f"x{var}" for var in b_order)
            print("\nStructural arithmetic detector:")
            print(f"- signed_multiplier: confidence=1.000, a_lsb_to_msb={a_text}, b_lsb_to_msb={b_text}")
            print("- recommended_strategy: template_signed_multiplier + ABC post-optimization")
        if divider_orders is not None:
            divisor_order, dividend_order = divider_orders
            divisor_text = ", ".join(f"x{var}" for var in divisor_order)
            dividend_text = ", ".join(f"x{var}" for var in dividend_order)
            print("\nStructural arithmetic detector:")
            print(
                "- unsigned_divider_quotient: confidence=1.000, "
                f"divisor_lsb_to_msb={divisor_text}, dividend_lsb_to_msb={dividend_text}"
            )
            print("- recommended_strategy: template_unsigned_divider_quotient + ABC post-optimization")
        if sqrt_order is not None:
            order_text = ", ".join(f"x{var}" for var in sqrt_order)
            print("\nStructural arithmetic detector:")
            print(f"- unsigned_sqrt: confidence=1.000, radicand_lsb_to_msb={order_text}")
            print("- recommended_strategy: template_unsigned_sqrt + ABC post-optimization")
        return 0

    if args.exact_function_report or args.exact_match_all:
        cases = selected_cases_from_args(args)
        exact_rows = []
        for case in cases:
            exact_rows.extend(exact_matches_for_truth(args.benchmarks / f"{case}.truth", max_expensive_inputs=args.exact_max_inputs))
        write_exact_function_matches_csv(args.logs / "exact_function_matches.csv", exact_rows)
        print(f"[exact] wrote {args.logs / 'exact_function_matches.csv'}")
        print(f"[exact] matched rows: {len(exact_rows)}")
        return 0

    if args.ablation_report:
        run_ablation_report(args.logs)
        return 0
    if args.diagnose_results:
        run_diagnose_results(args.abc, args.benchmarks, args.output, args.logs, root)
        return 0
    if args.validate_templates:
        run_validate_templates(args.benchmarks, args.logs)
        return 0
    if args.rescue_worst is not None:
        run_rescue_worst(args, root)
        return 0
    if args.case_coverage_report:
        run_case_coverage_report(args, root)
        return 0
    if args.complete_all_cases:
        run_complete_all_cases(args, root)
        return 0
    if args.round_robin_optimize:
        run_round_robin_optimize(args, root)
        return 0
    if args.score_aware_optimize:
        run_score_aware_optimize(args, root)
        return 0
    if args.contest_optimize:
        run_contest_optimize(args, root)
        return 0
    if args.case_fair_next_optimize:
        run_case_fair_next_optimize(args, root)
        return 0
    if args.type_guided_refine:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] type-guided refine")
            _rows, summary = run_type_guided_refine_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.type_guided_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("type-guided", summaries)
        return 0
    if args.objective_guided_refine:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] objective-guided refine")
            _rows, summary = run_objective_guided_refine_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.objective_max_per_family,
            )
            summaries.append(summary)
        print_summary_totals("objective-guided", summaries)
        return 0
    if args.micro_guided_refine:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] micro-guided refine")
            _rows, summary = run_micro_guided_refine_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.micro_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("micro-guided", summaries)
        return 0
    if args.small_case_refine:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        active_cases = 0
        for case in cases:
            print(f"[{case}] small-case refine")
            _rows, summary = run_small_case_refine_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.small_max_flows,
                args.small_area_threshold,
                args.small_adp_threshold,
            )
            if summary.selected_method != "small_case_skipped":
                active_cases += 1
            summaries.append(summary)
        print(f"[small-case] active cases {active_cases}/{len(summaries)}")
        print_summary_totals("small-case", summaries)
        return 0
    if args.exact_npn_rescue:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] exact/NPN rescue")
            _rows, summary = run_exact_npn_rescue_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.npn_max_support,
                args.npn_max_flows,
            )
            summaries.append(summary)
        print_summary_totals("exact-npn", summaries)
        return 0
    if args.transduction_rescue:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] transduction rescue")
            _rows, summary = run_transduction_rescue_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.transduction_budget,
                args.seed,
            )
            summaries.append(summary)
        print_summary_totals("transduction", summaries)
        return 0
    if args.complement_rescue:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] complement rescue")
            _rows, summary = run_complement_rescue_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.seed,
                args.complement_budget,
                not args.no_bdd,
            )
            summaries.append(summary)
        print_summary_totals("complement", summaries)
        return 0
    if args.specialized_generators or args.specialized_generate:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] specialized structural generators")
            _rows, summary = run_specialized_generators_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.exact_max_inputs,
            )
            summaries.append(summary)
        print_summary_totals("specialized", summaries)
        return 0
    if args.ttopt_structural:
        cases = selected_cases_from_args(args)
        summaries: list[CaseSummary] = []
        for case in cases:
            print(f"[{case}] ttopt structural")
            _rows, summary = run_ttopt_structural_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
            )
            summaries.append(summary)
        print_summary_totals("ttopt-structural", summaries)
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
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.timeout_per_case,
                root,
                args.mockturtle_structural_bin,
                args.mode,
                args.mockturtle_max_modes,
                args.exact_max_inputs,
            )
        return 0

    if args.reproduce_best:
        all_results, summaries = run_reproduce_best(args, root)
        write_results_csv(args.logs / "results.csv", all_results)
        write_pareto_candidates_csv(args.logs / "pareto_candidates.csv", all_results)
        write_summary_csv(args.logs / "summary.csv", summaries)
        if args.report_stats:
            print_report_stats(all_results, summaries)
        return 0

    if args.case:
        cases = [args.case]
    elif args.range:
        start = int(args.range[0].removeprefix("ex"))
        end = int(args.range[1].removeprefix("ex"))
        cases = [f"ex{i}" for i in range(start, end + 1)]
    else:
        cases = [f"ex{i}" for i in range(200, 300)]

    all_results: list[CandidateResult] = []
    summaries: list[CaseSummary] = []
    if args.sweep_existing:
        if args.try_mockturtle and not args.mockturtle_bin.is_file():
            print(f"[mockturtle] binary not found at {args.mockturtle_bin}; skipping optional mockturtle sweep")
        sweep_passes = max(1, args.sweep_passes)
        for pass_index in range(sweep_passes):
            pass_results: list[CandidateResult] = []
            pass_summaries: list[CaseSummary] = []
            print(f"[sweep] pass {pass_index + 1}/{sweep_passes}")
            for case in cases:
                print(f"[{case}] sweeping existing output")
                rows, summary = sweep_existing_case(
                    case,
                    args.abc,
                    args.benchmarks,
                    args.output,
                    args.logs,
                    args.timeout_per_case,
                    root,
                    args.try_mockturtle,
                    args.mockturtle_bin,
                )
                pass_results.extend(rows)
                pass_summaries.append(summary)
                selected = next(row for row in rows if row.selected)
                print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
            baseline_total = sum(row.baseline_adp for row in pass_summaries)
            best_total = sum(row.best_adp for row in pass_summaries)
            print(f"[sweep] pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
            all_results = pass_results
            summaries = pass_summaries
            if best_total >= baseline_total:
                print("[sweep] converged: no pass-level ADP improvement")
                break
    elif args.polish_existing:
        polish_passes = max(1, args.polish_passes)
        for pass_index in range(polish_passes):
            pass_results: list[CandidateResult] = []
            pass_summaries: list[CaseSummary] = []
            print(f"[polish] pass {pass_index + 1}/{polish_passes}")
            for case in cases:
                print(f"[{case}] polishing existing output")
                rows, summary = polish_existing_case(
                    case,
                    args.abc,
                    args.benchmarks,
                    args.output,
                    args.logs,
                    args.timeout_per_case,
                    root,
                )
                pass_results.extend(rows)
                pass_summaries.append(summary)
                selected = next(row for row in rows if row.selected)
                print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")
            baseline_total = sum(row.baseline_adp for row in pass_summaries)
            best_total = sum(row.best_adp for row in pass_summaries)
            print(f"[polish] pass {pass_index + 1} total ADP {baseline_total} -> {best_total}")
            all_results = pass_results
            summaries = pass_summaries
            if best_total >= baseline_total:
                print("[polish] converged: no pass-level ADP improvement")
                break
    else:
        for case in cases:
            print(f"[{case}] optimizing")
            rows, summary = optimize_case(
                case,
                args.abc,
                args.benchmarks,
                args.output,
                args.logs,
                args.max_candidates,
                args.seed,
                args.timeout_per_case,
                root,
                not args.no_ga,
                not args.no_bdd,
                args.polish_after_synthesis,
                args.try_complement,
                args.history_guided_ga,
            )
            all_results.extend(rows)
            summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    write_results_csv(args.logs / "results.csv", all_results)
    write_pareto_candidates_csv(args.logs / "pareto_candidates.csv", all_results)
    write_summary_csv(args.logs / "summary.csv", summaries)
    if args.report_stats:
        print_report_stats(all_results, summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
