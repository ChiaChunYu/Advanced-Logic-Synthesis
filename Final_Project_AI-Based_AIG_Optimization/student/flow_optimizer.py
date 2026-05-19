#!/usr/bin/env python3
"""Circuit-type-aware AIG optimizer for the ALS 2026 final project.

The flow is AI/LLM-inspired in the sense that it uses interpretable truth-table
features to classify each benchmark, then chooses ABC optimization scripts that
fit the predicted circuit type.  Every generated candidate is checked for
functional equivalence before it can be selected.
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
from dataclasses import dataclass
from pathlib import Path


PS_RE = re.compile(r"and\s*=\s*(\d+)\s+lev\s*=\s*(\d+)")


@dataclass(frozen=True)
class Flow:
    flow_id: str
    commands: str
    tags: tuple[str, ...]


@dataclass
class TruthFeatures:
    num_inputs: int
    num_outputs: int
    num_minterms: int
    on_count: int
    off_count: int
    density: float
    influences: list[float]
    avg_influence: float
    max_influence: float
    min_influence: float
    symmetry_score: float
    monotonicity_scores: list[float]
    monotonicity_dirs: list[str]
    shannon_complexities: list[float]


@dataclass
class Classification:
    labels: list[str]
    reasons: list[str]


@dataclass
class CandidateResult:
    case: str
    labels: list[str]
    flow_id: str
    flow_commands: str
    area: int | None = None
    delay: int | None = None
    adp: int | None = None
    equivalent: bool = False
    selected: bool = False
    status: str = "ERROR"
    message: str = ""
    aig: Path | None = None


FLOW_LIBRARY = [
    Flow("baseline", "st", ("fallback",)),
    Flow("rewrite_balance", "st; balance; rewrite; refactor; balance", ("rewrite", "fallback")),
    Flow("rewrite_zero", "st; rewrite -z; refactor -z; balance", ("rewrite", "parity_like", "fallback")),
    Flow(
        "rewrite_refactor_zero",
        "st; balance; rewrite; refactor; rewrite -z; refactor -z; balance",
        ("rewrite", "refactor", "fallback"),
    ),
    Flow("zero_then_rewrite", "st; rewrite -z; balance; rewrite; refactor; balance", ("rewrite", "parity_like")),
    Flow(
        "zero_two_rounds",
        "st; rewrite -z; refactor -z; balance; rewrite -z; refactor -z; balance",
        ("rewrite", "parity_like", "random_like"),
    ),
    Flow(
        "zero_three_rounds",
        "st; rewrite -z; refactor -z; balance; rewrite -z; refactor -z; balance; "
        "rewrite -z; refactor -z; balance",
        ("rewrite", "parity_like", "random_like"),
    ),
    Flow("dc2", "st; dc2", ("dc2", "decompose", "fallback")),
    Flow("dc2_rewrite_zero", "st; dc2; rewrite -z; refactor -z; balance", ("dc2", "rewrite", "fallback")),
    Flow("rewrite_refactor_dc2", "st; balance; rewrite; refactor; balance; dc2", ("dc2", "refactor")),
    Flow("refactor_heavy", "st; balance; refactor; rewrite; refactor -z; rewrite -z; balance", ("refactor",)),
    Flow("drw", "st; drw; balance", ("decompose", "mux_like")),
    Flow("drw_drf", "st; drw; drf; balance", ("decompose", "mux_like", "arithmetic_like")),
    Flow("dc2_drw_rewrite", "st; dc2; drw; rewrite -z; refactor -z; balance", ("dc2", "decompose", "mux_like")),
    Flow("dc2_drw_drf_rewrite", "st; dc2; drw; drf; rewrite -z; refactor -z; balance", ("dc2", "decompose", "mux_like")),
    Flow(
        "mix_rewrite_drw_drf_dc2",
        "st; rewrite; drw; drf; dc2; refactor; dc2; balance",
        ("promoted", "threshold_like", "symmetric_like", "monotone_like"),
    ),
    Flow(
        "mix_zero_refactor_drf_drw",
        "st; rewrite -z; refactor; drf; drw; drw; dc2; balance",
        ("promoted", "threshold_like", "symmetric_like", "monotone_like"),
    ),
    Flow(
        "mix_rewrite_drf_zero_dc2",
        "st; rewrite; drf; rewrite -z; dc2; balance",
        ("promoted", "threshold_like", "symmetric_like", "monotone_like"),
    ),
    Flow("dc2_three_rounds", "st; dc2; dc2; dc2; balance", ("promoted", "symmetric_like")),
    Flow(
        "zero_balance_dc2_rewrite",
        "st; rewrite -z; refactor -z; balance; dc2; rewrite; balance",
        ("promoted", "threshold_like", "monotone_like"),
    ),
    Flow("dc2_drf_zero_drf", "st; dc2; drf; rewrite -z; drf; balance", ("promoted", "threshold_like")),
    Flow("dc2_balance_drf_dc2", "st; dc2; balance; drf; dc2; balance", ("promoted", "threshold_like", "monotone_like")),
    Flow("rewrite_dc2_balance_dc2", "st; rewrite; dc2; balance; dc2; balance", ("promoted", "threshold_like", "monotone_like")),
    Flow(
        "balance_refactor_dc2_refactor",
        "st; balance; refactor; refactor; dc2; refactor; balance; balance",
        ("promoted", "threshold_like", "monotone_like"),
    ),
    Flow("rewrite_dc2_dc2", "st; rewrite; dc2; dc2; balance", ("promoted", "threshold_like", "symmetric_like")),
    Flow(
        "zero_refactor_dc2_zero",
        "st; refactor -z; dc2; rewrite -z; refactor; balance",
        ("promoted", "symmetric_like"),
    ),
    Flow("double_refactor_dc2_drw", "st; refactor -z; refactor -z; dc2; drw; balance", ("promoted", "monotone_like")),
    Flow("dc2_drf_drw_rewrite", "st; dc2; dc2; drf; drw; rewrite; balance", ("promoted", "monotone_like")),
    Flow("drf_balance_dc2_refactor", "st; drf; balance; dc2; balance; refactor -z; balance", ("promoted", "sparse", "monotone_like")),
    Flow(
        "drw_dc2_rewrite_drw",
        "st; drw; dc2; rewrite; drw; rewrite -z; drw; balance",
        ("promoted", "threshold_like", "symmetric_like"),
    ),
    Flow(
        "refactor_drf_zero_drf_dc2",
        "st; refactor; drf; refactor -z; drf; rewrite; dc2; balance",
        ("promoted", "symmetric_like"),
    ),
    Flow("arith_drw_drf_dc2", "st; drw; drf; drf; dc2; drw; dc2; balance", ("promoted_v2", "arithmetic_like")),
    Flow(
        "arith_rewrite_refactor_dc2_drf",
        "st; rewrite; refactor; refactor -z; dc2; drf; refactor -z; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow("arith_dc2_refactor_drw_drf", "st; dc2; refactor; drw; dc2; balance; drf; balance", ("promoted_v2", "arithmetic_like")),
    Flow(
        "random_rewrite_zero_refactor_dc2_drf",
        "st; rewrite; rewrite -z; refactor -z; dc2; drf; balance",
        ("promoted_v2", "random_like"),
    ),
    Flow(
        "random_refactor_stack_dc2",
        "st; refactor -z; refactor -z; drf; refactor -z; rewrite -z; dc2; balance",
        ("promoted_v2", "random_like"),
    ),
    Flow("random_dc2_drf_balance", "st; dc2; balance; drf; balance", ("promoted_v2", "random_like")),
    Flow(
        "arith_refactor_dc2_dc2_rewrite",
        "st; refactor -z; dc2; dc2; balance; rewrite; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow(
        "arith_double_rewrite_dc2_zero",
        "st; rewrite; rewrite; refactor -z; dc2; rewrite -z; refactor -z; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow("arith_drf_rewrite_dc2_zero", "st; drf; rewrite; dc2; rewrite -z; balance", ("promoted_v2", "arithmetic_like")),
    Flow(
        "arith_balance_refactor_dc2_drw",
        "st; balance; refactor -z; dc2; balance; rewrite; drw; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow(
        "arith_rewrite_dc2_refactor_zero",
        "st; rewrite; dc2; refactor -z; refactor -z; rewrite -z; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow(
        "arith_drw_dc2_dc2_drf_refactor",
        "st; drw; dc2; dc2; drf; balance; refactor; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow("arith_dc2_rewrite_dc2", "st; dc2; rewrite; dc2; balance", ("promoted_v2", "arithmetic_like")),
    Flow(
        "arith_dc2_rewrite_refactor_dc2",
        "st; dc2; rewrite; refactor; dc2; dc2; refactor; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow(
        "arith_refactor_drf_dc2_drw",
        "st; refactor; refactor; drf; dc2; drw; dc2; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow(
        "arith_refactor_zero_dc2_rewrite",
        "st; refactor; rewrite -z; refactor; dc2; rewrite; rewrite -z; balance",
        ("promoted_v2", "arithmetic_like"),
    ),
    Flow("arith_balance_dc2_dc2_drw", "st; balance; dc2; dc2; drw; balance; balance", ("promoted_v2", "arithmetic_like")),
    Flow("arith_refactor_zero_dc2_dc2", "st; refactor -z; dc2; dc2; balance", ("promoted_v2", "arithmetic_like")),
    Flow(
        "sym_refactor_dc2_drf_stack",
        "st; refactor -z; refactor -z; dc2; drf; dc2; drf; balance",
        ("promoted_v3", "symmetric_like"),
    ),
    Flow(
        "threshold_rewrite_dc2_refactor_stack",
        "st; rewrite; dc2; refactor -z; dc2; dc2; balance",
        ("promoted_v3", "threshold_like"),
    ),
    Flow(
        "random_balance_drw_drf_dc2",
        "st; balance; drw; drf; dc2; dc2; balance",
        ("promoted_v3", "random_like"),
    ),
    Flow(
        "sparse_dc2_rewrite_stack",
        "st; dc2; rewrite; dc2; dc2; rewrite; balance",
        ("promoted_v3", "sparse", "monotone_like"),
    ),
    Flow(
        "random_dc2_zero_refactor_stack",
        "st; dc2; rewrite -z; refactor -z; dc2; rewrite -z; dc2; balance",
        ("promoted_v4", "random_like"),
    ),
    Flow("resyn", "st; resyn", ("resyn", "random_like")),
    Flow("resyn2", "st; resyn2", ("resyn", "random_like")),
    Flow("resyn2_cleanup", "st; resyn2; rewrite -z; refactor -z; balance", ("resyn", "rewrite", "random_like")),
    Flow("dch_if_k6", "st; resyn2; dch; if -K 6; strash; resyn2", ("resyn", "decompose", "random_like")),
]

CORE_FLOW_IDS = [
    "baseline",
    "rewrite_balance",
    "rewrite_zero",
    "rewrite_refactor_zero",
    "zero_then_rewrite",
    "zero_two_rounds",
    "dc2",
    "dc2_rewrite_zero",
    "rewrite_refactor_dc2",
]

PROMOTED_FLOW_IDS = [
    "mix_rewrite_drw_drf_dc2",
    "mix_zero_refactor_drf_drw",
    "mix_rewrite_drf_zero_dc2",
    "dc2_three_rounds",
    "zero_balance_dc2_rewrite",
    "dc2_drf_zero_drf",
    "dc2_balance_drf_dc2",
    "rewrite_dc2_balance_dc2",
    "balance_refactor_dc2_refactor",
    "rewrite_dc2_dc2",
    "zero_refactor_dc2_zero",
    "double_refactor_dc2_drw",
    "dc2_drf_drw_rewrite",
    "drf_balance_dc2_refactor",
    "drw_dc2_rewrite_drw",
    "refactor_drf_zero_drf_dc2",
    "arith_drw_drf_dc2",
    "arith_rewrite_refactor_dc2_drf",
    "arith_dc2_refactor_drw_drf",
    "random_rewrite_zero_refactor_dc2_drf",
    "random_refactor_stack_dc2",
    "random_dc2_drf_balance",
    "arith_refactor_dc2_dc2_rewrite",
    "arith_double_rewrite_dc2_zero",
    "arith_drf_rewrite_dc2_zero",
    "arith_balance_refactor_dc2_drw",
    "arith_rewrite_dc2_refactor_zero",
    "arith_drw_dc2_dc2_drf_refactor",
    "arith_dc2_rewrite_dc2",
    "arith_dc2_rewrite_refactor_dc2",
    "arith_refactor_drf_dc2_drw",
    "arith_refactor_zero_dc2_rewrite",
    "arith_balance_dc2_dc2_drw",
    "arith_refactor_zero_dc2_dc2",
    "sym_refactor_dc2_drf_stack",
    "threshold_rewrite_dc2_refactor_stack",
    "random_balance_drw_drf_dc2",
    "sparse_dc2_rewrite_stack",
    "random_dc2_zero_refactor_stack",
]

RANDOM_COMMAND_POOL = [
    "balance",
    "rewrite",
    "rewrite -z",
    "refactor",
    "refactor -z",
    "dc2",
    "drw",
    "drf",
]


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
        raise RuntimeError(
            f"Cannot execute ABC at {abc}. Use Linux/WSL, or pass a compatible executable with --abc."
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"ABC exited with {result.returncode}")
    return result.stdout


def read_truth_outputs(truth: Path) -> list[bytearray]:
    text = truth.read_text(encoding="ascii", errors="ignore")
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
        raise ValueError(f"No truth-table bits found in {truth}")
    lengths = {len(bits) for bits in groups}
    if len(lengths) != 1:
        raise ValueError(f"Inconsistent output truth-table lengths in {truth}: {sorted(lengths)}")
    length = lengths.pop()
    if length & (length - 1):
        raise ValueError(f"Truth-table output length is not a power of two: {truth}")
    return groups


def binary_entropy(value: float) -> float:
    if value <= 0.0 or value >= 1.0:
        return 0.0
    return -(value * math.log2(value) + (1.0 - value) * math.log2(1.0 - value))


def cofactor_counts(bits: bytearray, var: int) -> tuple[int, int, int]:
    step = 1 << var
    period = step << 1
    ones0 = 0
    ones1 = 0
    diff = 0
    for base in range(0, len(bits), period):
        for offset in range(step):
            a = bits[base + offset]
            b = bits[base + offset + step]
            ones0 += a
            ones1 += b
            diff += a ^ b
    return ones0, ones1, diff


def extract_features(truth: Path) -> TruthFeatures:
    outputs = read_truth_outputs(truth)
    num_outputs = len(outputs)
    num_minterms = len(outputs[0])
    num_inputs = int(math.log2(num_minterms))
    total_bits = num_outputs * num_minterms
    on_count = sum(sum(bits) for bits in outputs)
    off_count = total_bits - on_count
    density = on_count / total_bits
    pair_count = num_minterms // 2

    influences: list[float] = []
    monotonicity_scores: list[float] = []
    monotonicity_dirs: list[str] = []
    shannon_complexities: list[float] = []

    for var in range(num_inputs):
        total_ones0 = 0
        total_ones1 = 0
        total_diff = 0
        total_non_decreasing = 0
        total_non_increasing = 0
        for bits in outputs:
            ones0, ones1, diff = cofactor_counts(bits, var)
            total_ones0 += ones0
            total_ones1 += ones1
            total_diff += diff

            step = 1 << var
            period = step << 1
            for base in range(0, num_minterms, period):
                for offset in range(step):
                    a = bits[base + offset]
                    b = bits[base + offset + step]
                    total_non_decreasing += int(a <= b)
                    total_non_increasing += int(a >= b)

        total_pairs = pair_count * num_outputs
        influence = total_diff / total_pairs
        influences.append(influence)

        dec_score = total_non_decreasing / total_pairs
        inc_score = total_non_increasing / total_pairs
        if dec_score >= inc_score:
            monotonicity_scores.append(dec_score)
            monotonicity_dirs.append("nondecreasing")
        else:
            monotonicity_scores.append(inc_score)
            monotonicity_dirs.append("nonincreasing")

        density0 = total_ones0 / total_pairs
        density1 = total_ones1 / total_pairs
        shannon_complexities.append(0.5 * influence + 0.25 * binary_entropy(density0) + 0.25 * binary_entropy(density1))

    avg_influence = sum(influences) / len(influences)
    max_influence = max(influences)
    min_influence = min(influences)

    similar_pairs = 0
    total_pairs = 0
    for i in range(num_inputs):
        for j in range(i + 1, num_inputs):
            total_pairs += 1
            influence_close = abs(influences[i] - influences[j]) <= 0.05
            monotone_close = abs(monotonicity_scores[i] - monotonicity_scores[j]) <= 0.05
            similar_pairs += int(influence_close and monotone_close)
    symmetry_score = similar_pairs / total_pairs if total_pairs else 1.0

    return TruthFeatures(
        num_inputs=num_inputs,
        num_outputs=num_outputs,
        num_minterms=num_minterms,
        on_count=on_count,
        off_count=off_count,
        density=density,
        influences=influences,
        avg_influence=avg_influence,
        max_influence=max_influence,
        min_influence=min_influence,
        symmetry_score=symmetry_score,
        monotonicity_scores=monotonicity_scores,
        monotonicity_dirs=monotonicity_dirs,
        shannon_complexities=shannon_complexities,
    )


def classify_features(features: TruthFeatures) -> Classification:
    labels: list[str] = []
    reasons: list[str] = []

    density = features.density
    influence_span = features.max_influence - features.min_influence
    monotone_avg = sum(features.monotonicity_scores) / len(features.monotonicity_scores)
    high_influence_vars = sum(1 for value in features.influences if value >= 0.45)
    low_influence_vars = sum(1 for value in features.influences if value <= 0.08)
    complex_vars = sum(1 for value in features.shannon_complexities if value >= 0.65)

    if density <= 0.12:
        labels.append("sparse")
        reasons.append(f"density {density:.3f} <= 0.12")
    if density >= 0.88:
        labels.append("dense")
        reasons.append(f"density {density:.3f} >= 0.88")
    if 0.35 <= density <= 0.65 and features.avg_influence >= 0.42 and influence_span <= 0.18:
        labels.append("parity_like")
        reasons.append(
            f"balanced density {density:.3f}, high avg influence {features.avg_influence:.3f}, "
            f"small influence span {influence_span:.3f}"
        )
    if features.max_influence >= 0.35 and low_influence_vars >= max(2, features.num_inputs // 4) and influence_span >= 0.25:
        labels.append("mux_like")
        reasons.append(f"uneven variable influence span {influence_span:.3f} with {low_influence_vars} low-influence vars")
    if 0.20 <= density <= 0.80 and monotone_avg >= 0.88:
        labels.append("threshold_like")
        reasons.append(f"high average monotonicity {monotone_avg:.3f} with non-extreme density")
    if features.symmetry_score >= 0.70:
        labels.append("symmetric_like")
        reasons.append(f"symmetry score {features.symmetry_score:.3f} >= 0.70")
    if monotone_avg >= 0.92:
        labels.append("monotone_like")
        reasons.append(f"average monotonicity {monotone_avg:.3f} >= 0.92")
    if complex_vars >= max(4, features.num_inputs // 3) and 0.15 <= density <= 0.85:
        labels.append("arithmetic_like")
        reasons.append(f"{complex_vars} variables have high Shannon split complexity")
    if not labels or (features.avg_influence >= 0.25 and features.symmetry_score < 0.45 and monotone_avg < 0.86):
        labels.append("random_like")
        reasons.append(
            f"default/broad search: avg influence {features.avg_influence:.3f}, "
            f"symmetry {features.symmetry_score:.3f}, monotonicity {monotone_avg:.3f}"
        )

    return Classification(labels=labels, reasons=reasons)


def make_random_flows(rng: random.Random, count: int) -> list[Flow]:
    flows: list[Flow] = []
    seen: set[str] = set()
    attempts = 0
    while len(flows) < count and attempts < count * 20:
        attempts += 1
        length = rng.randint(3, 6)
        commands = ["st"]
        commands.extend(rng.choice(RANDOM_COMMAND_POOL) for _ in range(length))
        commands.append("balance")
        command_text = "; ".join(commands)
        if command_text in seen:
            continue
        seen.add(command_text)
        flows.append(Flow(f"random_{len(flows):02d}", command_text, ("random_search",)))
    return flows


def select_flows(labels: list[str], max_candidates: int, rng: random.Random) -> list[Flow]:
    by_id = {flow.flow_id: flow for flow in FLOW_LIBRARY}
    selected: list[Flow] = [by_id[flow_id] for flow_id in CORE_FLOW_IDS]
    selected.extend(
        by_id[flow_id]
        for flow_id in PROMOTED_FLOW_IDS
        if any(label in by_id[flow_id].tags for label in labels)
    )

    label_to_ids = {
        "sparse": ["dc2", "dc2_rewrite_zero", "rewrite_refactor_dc2"],
        "dense": ["dc2", "dc2_rewrite_zero", "rewrite_refactor_dc2"],
        "parity_like": ["zero_two_rounds", "zero_three_rounds", "refactor_heavy"],
        "mux_like": ["drw", "drw_drf", "dc2_drw_rewrite", "dc2_drw_drf_rewrite"],
        "threshold_like": ["rewrite_balance", "rewrite_refactor_zero", "dc2_rewrite_zero"],
        "symmetric_like": ["rewrite_balance", "zero_then_rewrite", "dc2_rewrite_zero"],
        "monotone_like": ["rewrite_balance", "rewrite_refactor_zero", "dc2"],
        "arithmetic_like": ["drw_drf", "dc2_drw_rewrite", "rewrite_refactor_dc2"],
        "random_like": ["zero_three_rounds", "refactor_heavy", "resyn", "resyn2", "resyn2_cleanup", "dch_if_k6"],
    }

    for label in labels:
        for flow_id in label_to_ids.get(label, []):
            selected.append(by_id[flow_id])

    deduped: list[Flow] = []
    seen_ids: set[str] = set()
    for flow in selected:
        if flow.flow_id not in seen_ids:
            deduped.append(flow)
            seen_ids.add(flow.flow_id)

    random_budget = max(0, max_candidates - len(deduped))
    if random_budget:
        deduped.extend(make_random_flows(rng, random_budget))
    return deduped[:max_candidates]


def synthesize_candidate(abc: Path, truth: Path, aig: Path, flow: Flow, timeout: int, root: Path) -> None:
    aig.parent.mkdir(parents=True, exist_ok=True)
    command = (
        f"read_truth -xf {abc_path(truth, root)}; {flow.commands}; "
        f"write_aiger -s {abc_path(aig, root)}"
    )
    run_abc(abc, command, timeout, root)


def is_equivalent(abc: Path, truth: Path, aig: Path, timeout: int, root: Path) -> tuple[bool, str]:
    command = f"read_truth -xf {abc_path(truth, root)}; st; &get; &cec -t {abc_path(aig, root)}"
    output = run_abc(abc, command, timeout, root)
    return "Networks are equivalent" in output, output.strip()


def measure_adp(abc: Path, aig: Path, timeout: int, root: Path) -> tuple[int, int, int]:
    output = run_abc(abc, f"read {abc_path(aig, root)}; ps", timeout, root)
    match = PS_RE.search(output)
    if not match:
        raise RuntimeError(f"Cannot parse ABC statistics:\n{output.strip()}")
    area = int(match.group(1))
    delay = int(match.group(2))
    return area, delay, area * delay


def evaluate_flow(
    abc: Path,
    truth: Path,
    flow: Flow,
    candidate_aig: Path,
    labels: list[str],
    timeout: int,
    root: Path,
) -> CandidateResult:
    case = truth.stem
    try:
        synthesize_candidate(abc, truth, candidate_aig, flow, timeout, root)
        equivalent, message = is_equivalent(abc, truth, candidate_aig, timeout, root)
        if not equivalent:
            return CandidateResult(
                case=case,
                labels=labels,
                flow_id=flow.flow_id,
                flow_commands=flow.commands,
                equivalent=False,
                status="NOT_EQUIV",
                message=message.splitlines()[-1] if message else "not equivalent",
                aig=candidate_aig,
            )
        area, delay, adp = measure_adp(abc, candidate_aig, timeout, root)
        return CandidateResult(
            case=case,
            labels=labels,
            flow_id=flow.flow_id,
            flow_commands=flow.commands,
            area=area,
            delay=delay,
            adp=adp,
            equivalent=True,
            status="OK",
            aig=candidate_aig,
        )
    except subprocess.TimeoutExpired:
        return CandidateResult(case, labels, flow.flow_id, flow.commands, status="TIMEOUT", message="ABC timeout")
    except RuntimeError as exc:
        return CandidateResult(case, labels, flow.flow_id, flow.commands, status="ERROR", message=str(exc).splitlines()[-1])


def choose_best(results: list[CandidateResult]) -> CandidateResult | None:
    ok = [result for result in results if result.equivalent and result.adp is not None]
    if not ok:
        return None
    return min(ok, key=lambda result: (result.adp or sys.maxsize, result.area or sys.maxsize))


def format_features(features: TruthFeatures) -> str:
    lines = [
        f"num_inputs: {features.num_inputs}",
        f"num_outputs: {features.num_outputs}",
        f"num_minterms: {features.num_minterms}",
        f"on_count: {features.on_count}",
        f"off_count: {features.off_count}",
        f"density: {features.density:.6f}",
        f"avg_influence: {features.avg_influence:.6f}",
        f"max_influence: {features.max_influence:.6f}",
        f"min_influence: {features.min_influence:.6f}",
        f"symmetry_score: {features.symmetry_score:.6f}",
        "per_input_influence: " + ", ".join(f"{v:.4f}" for v in features.influences),
        "monotonicity_scores: " + ", ".join(f"{v:.4f}" for v in features.monotonicity_scores),
        "monotonicity_dirs: " + ", ".join(features.monotonicity_dirs),
        "shannon_complexities: " + ", ".join(f"{v:.4f}" for v in features.shannon_complexities),
    ]
    return "\n".join(lines)


def write_case_log(
    logs_dir: Path,
    case: str,
    features: TruthFeatures,
    classification: Classification,
    flows: list[Flow],
    results: list[CandidateResult],
    best: CandidateResult | None,
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"case: {case}",
        "",
        "[features]",
        format_features(features),
        "",
        "[classification]",
        "labels: " + ", ".join(classification.labels),
        "reasons:",
    ]
    lines.extend(f"- {reason}" for reason in classification.reasons)
    lines.extend(["", "[candidate_flows]"])
    lines.extend(f"- {flow.flow_id}: {flow.commands}" for flow in flows)
    lines.extend(["", "[results]"])
    for result in results:
        metric = f"area={result.area} delay={result.delay} adp={result.adp}" if result.equivalent else result.status
        lines.append(f"- {result.flow_id}: {metric}")
    lines.extend(["", "[selected]", best.flow_id if best else "NONE"])
    if best:
        lines.append(f"selected_adp: {best.adp}")
    (logs_dir / f"{case}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_results_csv(csv_path: Path, results: list[CandidateResult]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "case",
                "labels",
                "flow_id",
                "flow_commands",
                "area",
                "delay",
                "adp",
                "equivalent",
                "selected",
            ],
        )
        if not exists:
            writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "case": result.case,
                    "labels": "|".join(result.labels),
                    "flow_id": result.flow_id,
                    "flow_commands": result.flow_commands,
                    "area": "" if result.area is None else result.area,
                    "delay": "" if result.delay is None else result.delay,
                    "adp": "" if result.adp is None else result.adp,
                    "equivalent": int(result.equivalent),
                    "selected": int(result.selected),
                }
            )


def optimize_case(
    abc: Path,
    truth: Path,
    output_dir: Path,
    logs_dir: Path,
    temp_dir: Path,
    max_candidates: int,
    seed: int,
    timeout_per_case: int,
    root: Path,
) -> CandidateResult | None:
    start = time.monotonic()
    features = extract_features(truth)
    classification = classify_features(features)
    rng = random.Random(f"{seed}:{truth.stem}:{','.join(classification.labels)}")
    flows = select_flows(classification.labels, max_candidates, rng)

    case_temp = temp_dir / truth.stem
    if case_temp.exists():
        shutil.rmtree(case_temp)
    case_temp.mkdir(parents=True, exist_ok=True)

    results: list[CandidateResult] = []
    print(f"[CASE] {truth.stem} labels={','.join(classification.labels)}")
    for index, flow in enumerate(flows):
        elapsed = time.monotonic() - start
        remaining = timeout_per_case - elapsed
        if timeout_per_case > 0 and remaining <= 0:
            print("  case timeout reached")
            break
        abc_timeout = max(1, min(90, int(remaining))) if timeout_per_case > 0 else 90
        candidate_aig = case_temp / f"{index:02d}_{flow.flow_id}.aig"
        print(f"  trying {flow.flow_id:<22}", end="", flush=True)
        result = evaluate_flow(abc, truth, flow, candidate_aig, classification.labels, abc_timeout, root)
        results.append(result)
        if result.equivalent:
            print(f" area={result.area} delay={result.delay} adp={result.adp}")
        else:
            print(f" {result.status}")

    best = choose_best(results)
    if best and best.aig:
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(best.aig, output_dir / f"{truth.stem}.aig")
        best.selected = True
        print(f"[BEST] {truth.stem}: {best.flow_id} area={best.area} delay={best.delay} adp={best.adp}")
    else:
        print(f"[FAIL] {truth.stem}: no equivalent candidate")

    write_case_log(logs_dir, truth.stem, features, classification, flows, results, best)
    append_results_csv(logs_dir / "results.csv", results)
    return best


def select_truth_files(benchmarks: Path, case: str | None, run_all: bool) -> list[Path]:
    if case:
        return [benchmarks / f"{case}.truth"]
    if run_all:
        return sorted(benchmarks.glob("ex*.truth"))
    return sorted(benchmarks.glob("ex*.truth"))


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Circuit-type-aware AIG optimizer.")
    parser.add_argument("--abc", type=Path, default=Path(__file__).resolve().with_name("abc"))
    parser.add_argument("--benchmarks", type=Path, default=root / "benchmarks")
    parser.add_argument("--output", type=Path, default=root / "output")
    parser.add_argument("--logs", type=Path, default=Path(__file__).resolve().parent / "logs")
    parser.add_argument("--case", help="Optimize one case, for example ex200.")
    parser.add_argument("--all", action="store_true", help="Optimize all exNNN.truth benchmarks.")
    parser.add_argument("--max-candidates", type=int, default=32)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--timeout-per-case", type=int, default=900)
    parser.add_argument("--analyze-case", help="Print truth-table features for one case and exit.")
    parser.add_argument("--classify-case", help="Print classification labels/reasons for one case and exit.")
    parser.add_argument("--keep-temp", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    abc = args.abc.resolve()
    benchmarks = args.benchmarks.resolve()
    output_dir = args.output.resolve()
    logs_dir = args.logs.resolve()
    temp_dir = output_dir / ".optimizer_tmp"

    if args.max_candidates < 1:
        print("--max-candidates must be at least 1", file=sys.stderr)
        return 2
    if not benchmarks.is_dir():
        print(f"Benchmark directory not found: {benchmarks}", file=sys.stderr)
        return 2
    if not abc.is_file() and not (args.analyze_case or args.classify_case):
        print(f"ABC executable not found: {abc}", file=sys.stderr)
        return 2

    if args.analyze_case or args.classify_case:
        case = args.analyze_case or args.classify_case
        truth = benchmarks / f"{case}.truth"
        if not truth.is_file():
            print(f"Missing benchmark: {truth}", file=sys.stderr)
            return 2
        features = extract_features(truth)
        print(format_features(features))
        if args.classify_case:
            classification = classify_features(features)
            print("\nlabels: " + ", ".join(classification.labels))
            print("reasons:")
            for reason in classification.reasons:
                print(f"- {reason}")
        return 0

    if logs_dir.exists():
        results_csv = logs_dir / "results.csv"
        if results_csv.exists():
            results_csv.unlink()
    logs_dir.mkdir(parents=True, exist_ok=True)

    truth_files = select_truth_files(benchmarks, args.case, args.all)
    if not truth_files:
        print("No benchmark truth files found.", file=sys.stderr)
        return 2

    failures = 0
    total_adp = 0
    for truth in truth_files:
        if not truth.is_file():
            print(f"Missing benchmark: {truth}", file=sys.stderr)
            return 2
        best = optimize_case(
            abc=abc,
            truth=truth,
            output_dir=output_dir,
            logs_dir=logs_dir,
            temp_dir=temp_dir,
            max_candidates=args.max_candidates,
            seed=args.seed,
            timeout_per_case=args.timeout_per_case,
            root=root,
        )
        if best is None:
            failures += 1
        else:
            total_adp += best.adp or 0

    if not args.keep_temp and temp_dir.exists():
        shutil.rmtree(temp_dir)

    generated = len(truth_files) - failures
    print(f"Generated {generated}/{len(truth_files)} AIG file(s) in {output_dir}")
    print(f"Wrote logs to {logs_dir}")
    print(f"Total ADP over generated cases: {total_adp}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
