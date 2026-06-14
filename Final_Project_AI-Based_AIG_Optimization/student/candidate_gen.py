#!/usr/bin/env python3
"""Initial candidate generation for AIG synthesis.

Builds the initial BLIF candidates that are later post-optimized by ABC
flows.  Imports all structural BLIF writers from blif_builder so there is
no duplication.
"""

from __future__ import annotations

import csv
import math
import random
import re
import shutil
import subprocess
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from blif_builder import (
    BlifBuilder,
    TruthTable,
    collect_all_output_covers,
    detect_unsigned_divider_quotient,
    detect_unsigned_multiplier,
    detect_unsigned_sqrt,
    detect_unsigned_square,
    detect_signed_multiplier,
    emit_and_tree,
    emit_column_outputs,
    emit_or_tree,
    emit_unsigned_greater_equal,
    emit_xor_tree,
    output_support,
    read_truth,
    reduce_weighted_columns,
    selector_reduction_order,
    write_bdd_blif,
    write_complement_truth,
    write_cover_blif,
    write_factored_sop_blif,
    write_signed_multiplier_blif,
    write_signed_multiplier_csa_blif,
    write_unsigned_divider_quotient_blif,
    write_unsigned_multiplier_blif,
    write_unsigned_sqrt_blif,
    write_unsigned_square_blif,
    wrap_inverted_blif_outputs,
)
from abc_core import abc_path, run_abc
from circuit_analysis import (
    ExactFunctionMatch,
    exact_matches_for_truth,
)
from flow_library import POST_FLOWS, PostFlow, TOP_FLOW_NAMES
from result_logging import CandidateResult, ParetoCandidate, read_result_rows, row_int, write_pareto_candidates_csv


@dataclass(frozen=True)
class InitialCandidate:
    method: str
    source_kind: str
    source_path: Path | None


# ---------------------------------------------------------------------------
# Helpers shared across exact-match BLIF writers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Exact-match BLIF writers
# ---------------------------------------------------------------------------

def write_exact_affine_blif(path: Path, model: str, table: TruthTable, matches: list[ExactFunctionMatch]) -> bool:
    grouped = exact_matches_by_output(matches)
    builder = BlifBuilder(table, model)
    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        match = choose_exact_match(
            grouped, output_index,
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
            builder, choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
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
            builder, choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
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
            builder, choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
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
            builder, choose_exact_match(grouped, output_index, {"constant_zero", "constant_one"}),
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


# ---------------------------------------------------------------------------
# High-level candidate builders
# ---------------------------------------------------------------------------

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
        csa_blif = tmp / f"{case}_exact_signed_multiplier_csa.blif"
        write_signed_multiplier_csa_blif(csa_blif, f"{case}_exact_signed_multiplier_csa", table, a_order, b_order)
        candidates.append((InitialCandidate("specialized_exact_signed_multiplier_csa", "blif", csa_blif), "signed_multiplier", "exact_signed_multiplier_csa"))

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
    write_complement_truth=None,
) -> list[InitialCandidate]:
    tmp.mkdir(parents=True, exist_ok=True)
    candidates = [InitialCandidate("abc_truth", "truth", None)]
    if try_complement and write_complement_truth is not None:
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
        csa_blif = tmp / f"{case}_signed_multiplier_csa.blif"
        write_signed_multiplier_csa_blif(csa_blif, f"{case}_signed_multiplier_csa", table, a_order, b_order)
        candidates.append(InitialCandidate("template_signed_multiplier_csa", "blif", csa_blif))

    divider_orders = detect_unsigned_divider_quotient(table)
    if divider_orders is not None:
        divisor_order, dividend_order = divider_orders
        blif = tmp / f"{case}_unsigned_divider_quotient.blif"
        write_unsigned_divider_quotient_blif(blif, f"{case}_unsigned_divider_quotient", table, divisor_order, dividend_order)
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


# ---------------------------------------------------------------------------
# Pareto / candidate-set analysis
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Complement candidates and candidate pairing (moved from flow_optimizer)
# ---------------------------------------------------------------------------

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
    tmp: "Path",
    seed: int,
    use_bdd: bool,
) -> "list[InitialCandidate]":
    from pathlib import Path
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
    initials: "list[InitialCandidate]",
    flows: "list[PostFlow]",
    max_candidates: int,
) -> "list[tuple[InitialCandidate, PostFlow]]":
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


def _write_pareto_candidates_from_results(path: "Path", results: "list[CandidateResult]") -> None:
    rows = build_pareto_candidates(results)
    write_pareto_candidates_csv(path, rows)


def synthesize(
    abc: "Path",
    truth: "Path",
    initial: "InitialCandidate",
    flow: "PostFlow",
    out_aig: "Path",
    timeout: int,
    root: "Path",
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
    abc: "Path",
    source_aig: "Path",
    flow: "PostFlow",
    out_aig: "Path",
    timeout: int,
    root: "Path",
) -> None:
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    command = f"read {abc_path(source_aig, root)}; {flow.commands}; write_aiger -s {abc_path(out_aig, root)}"
    run_abc(abc, command, timeout, root)


def make_circuit_type_seed_candidates(
    case: str,
    table: TruthTable,
    fingerprint,
    family: str,
    tmp: Path,
    seed: int,
    max_seeds: int,
) -> list[InitialCandidate]:
    active = table.active_vars
    candidates: list[InitialCandidate] = [InitialCandidate("ct_truth", "truth", None)]
    if len(active) > 18 or max_seeds <= 1:
        return candidates[:max_seeds]

    order_specs: list[tuple[str, list[int]]] = []
    labels = set(fingerprint.labels)
    if family == "mux_shannon" or "mux_like" in labels:
        order_specs.extend(
            [
                ("ct_bdd_selector", selector_reduction_order(table)),
                ("ct_bdd_shannon", sorted(active, key=lambda var: table.shannon_scores[var], reverse=True)),
            ]
        )
    elif family == "monotone_general":
        order_specs.extend(
            [
                ("ct_bdd_high_influence", sorted(active, key=lambda var: table.influences[var], reverse=True)),
                ("ct_bdd_low_influence", sorted(active, key=lambda var: table.influences[var])),
            ]
        )
    elif family == "constant_mixed":
        order_specs.extend(
            [
                ("ct_bdd_low_influence", sorted(active, key=lambda var: table.influences[var])),
                ("ct_bdd_original", active),
            ]
        )
    elif family == "small_template":
        order_specs.append(("ct_bdd_small", sorted(active, key=lambda var: table.influences[var], reverse=True)))
    else:
        order_specs.extend(
            [
                ("ct_bdd_shannon", sorted(active, key=lambda var: table.shannon_scores[var], reverse=True)),
                ("ct_bdd_high_influence", sorted(active, key=lambda var: table.influences[var], reverse=True)),
            ]
        )

    rng = random.Random(f"{seed}:{case}:circuit_type")
    random_order = active[:]
    rng.shuffle(random_order)
    order_specs.append(("ct_bdd_seeded", random_order))

    seen_orders: set[tuple[int, ...]] = set()
    for name, order in order_specs:
        order_key = tuple(order)
        if order_key in seen_orders:
            continue
        seen_orders.add(order_key)
        try:
            blif = tmp / f"{case}_{name}.blif"
            write_bdd_blif(blif, f"{case}_{name}", table, order, node_limit=160000)
            candidates.append(InitialCandidate(name, "blif", blif))
        except RuntimeError:
            continue
        if len(candidates) >= max_seeds:
            break
    return candidates


def make_history_guided_ga_flows(case: str, logs: Path, seed: int, count: int) -> list[PostFlow]:
    from flow_library import _make_history_guided_ga_flows
    return _make_history_guided_ga_flows(case, logs, seed, count, read_result_rows, row_int)


def bdd_sift_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
) -> list[CandidateResult]:
    from blif_builder import write_bdd_blif
    from abc_core import measure_adp, is_equivalent, prepare_case_temp_dir
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    if len(table.active_vars) > 18:
        return []
    tmp = prepare_case_temp_dir(logs, "tmp_bdd_sift", case)
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
