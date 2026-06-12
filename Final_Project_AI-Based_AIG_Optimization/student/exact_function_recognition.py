#!/usr/bin/env python3
"""Exact Boolean function recognition for contest-style AIG synthesis.

The detectors in this module are intentionally proof-based: a match is only
reported after checking the full truth table for the selected output bit.  The
optimizer can then use these matches as safe hints for structural generation,
while final AIG replacement still goes through ABC equivalence checking.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from blif_builder import (
    detect_signed_multiplier,
    detect_unsigned_divider_quotient,
    detect_unsigned_multiplier,
    detect_unsigned_sqrt,
    detect_unsigned_square,
)
from boolean_fingerprint import (
    TruthTable,
    anf_coefficients,
    anf_stats,
    bit_at,
    output_influences,
    parse_truth,
)


@dataclass(frozen=True)
class ExactFunctionMatch:
    case: str
    output_index: int
    function_type: str
    bit_index: str
    mapping: str
    signedness: str
    input_order: str
    confidence: float
    evidence: str


MatchKey = tuple[str, int, str, str, str, str, str]


def input_value(index: int, num_inputs: int, order: list[int]) -> int:
    value = 0
    for bit_index, var in enumerate(order):
        value |= bit_at(index, num_inputs, var) << bit_index
    return value


def signed_input_value(index: int, num_inputs: int, order: list[int]) -> int:
    value = input_value(index, num_inputs, order)
    sign = 1 << (len(order) - 1)
    return value - (1 << len(order)) if value & sign else value


def output_value(table: TruthTable, index: int) -> int:
    value = 0
    for output_index, bits in enumerate(table.outputs):
        value |= bits[index] << output_index
    return value


def effective_support(table: TruthTable) -> list[int]:
    influence = [0.0 for _ in range(table.num_inputs)]
    for bits in table.outputs:
        for var, value in enumerate(output_influences(bits, table.num_inputs)):
            influence[var] = max(influence[var], value)
    return [var for var, value in enumerate(influence) if value > 0.0]


def format_order(order: list[int]) -> str:
    return "[" + ",".join(f"x{var}" for var in order) + "]"


def add_match(
    rows: list[ExactFunctionMatch],
    seen: set[MatchKey],
    table: TruthTable,
    output_index: int,
    function_type: str,
    bit_index: int | str,
    mapping: str,
    signedness: str,
    input_order: str,
    evidence: str,
) -> None:
    key = (table.case, output_index, function_type, str(bit_index), mapping, signedness, input_order)
    if key in seen:
        return
    seen.add(key)
    rows.append(
        ExactFunctionMatch(
            case=table.case,
            output_index=output_index,
            function_type=function_type,
            bit_index=str(bit_index),
            mapping=mapping,
            signedness=signedness,
            input_order=input_order,
            confidence=1.0,
            evidence=evidence,
        )
    )


def output_bit_matches(table: TruthTable, output_index: int, predicate) -> bool:
    bits = table.outputs[output_index]
    for index, value in enumerate(bits):
        if value != (predicate(index) & 1):
            return False
    return True


def detect_constants_buffers_affine(table: TruthTable, rows: list[ExactFunctionMatch], seen: set[MatchKey]) -> None:
    for output_index, bits in enumerate(table.outputs):
        on_count = sum(bits)
        if on_count == 0:
            add_match(rows, seen, table, output_index, "constant_zero", "", "single_output", "unsigned", "", "all minterms are 0")
        if on_count == len(bits):
            add_match(rows, seen, table, output_index, "constant_one", "", "single_output", "unsigned", "", "all minterms are 1")

        for var in range(table.num_inputs):
            if output_bit_matches(table, output_index, lambda idx, v=var: bit_at(idx, table.num_inputs, v)):
                add_match(rows, seen, table, output_index, "buffer", "", "single_variable", "unsigned", f"x{var}", "output equals input variable")
            if output_bit_matches(table, output_index, lambda idx, v=var: bit_at(idx, table.num_inputs, v) ^ 1):
                add_match(rows, seen, table, output_index, "inverter", "", "single_variable", "unsigned", f"x{var}", "output equals inverted input variable")

        degree, terms_by_degree = anf_stats(bits)
        if degree <= 1:
            coeffs = anf_coefficients(bits)
            variables = []
            constant = coeffs[0] if coeffs else 0
            for coeff_index, coeff in enumerate(coeffs):
                if coeff and coeff_index and coeff_index.bit_count() == 1:
                    # Truth indices use x0 as the most-significant assignment bit.
                    bit_pos = coeff_index.bit_length() - 1
                    variables.append(table.num_inputs - 1 - bit_pos)
            function_type = "parity" if len(variables) >= 2 else "affine"
            evidence = f"ANF degree={degree}, constant={constant}, linear_terms={len(variables)}"
            add_match(
                rows,
                seen,
                table,
                output_index,
                function_type,
                "",
                "anf_exact",
                "unsigned",
                format_order(sorted(variables)),
                evidence,
            )


def detect_symmetric_thresholds(table: TruthTable, rows: list[ExactFunctionMatch], seen: set[MatchKey]) -> None:
    for output_index, bits in enumerate(table.outputs):
        support = [var for var, value in enumerate(output_influences(bits, table.num_inputs)) if value > 0.0]
        if not support:
            continue
        by_weight: dict[int, int] = {}
        symmetric = True
        for index, value in enumerate(bits):
            weight = sum(bit_at(index, table.num_inputs, var) for var in support)
            if weight in by_weight and by_weight[weight] != value:
                symmetric = False
                break
            by_weight[weight] = value
        if not symmetric:
            continue
        ones = sorted(weight for weight, value in by_weight.items() if value)
        order = format_order(support)
        add_match(rows, seen, table, output_index, "symmetric_function", "", "support_weight", "unsigned", order, f"truth depends only on popcount over {len(support)} inputs")
        if len(ones) == 1:
            k = ones[0]
            label = "one_hot_exactly_one" if k == 1 else "exact_k"
            add_match(rows, seen, table, output_index, label, k, "support_weight", "unsigned", order, f"output is 1 exactly when popcount={k}")
        if ones:
            ge_k = min(ones)
            if ones == list(range(ge_k, len(support) + 1)):
                label = "majority" if ge_k == (len(support) + 1) // 2 else "threshold_ge"
                add_match(rows, seen, table, output_index, label, ge_k, "support_weight", "unsigned", order, f"output is 1 when popcount>={ge_k}")
            le_k = max(ones)
            if ones == list(range(0, le_k + 1)):
                add_match(rows, seen, table, output_index, "threshold_le", le_k, "support_weight", "unsigned", order, f"output is 1 when popcount<={le_k}")
        if sum(bits) == 1:
            minterm = next(index for index, value in enumerate(bits) if value)
            cube = "".join(str(bit_at(minterm, table.num_inputs, var)) for var in support)
            add_match(rows, seen, table, output_index, "decoder_minterm", "", "support_cube", "unsigned", order, f"single on-set minterm cube={cube}")


def operand_mappings(num_inputs: int, support: list[int]) -> list[tuple[str, list[int], list[int]]]:
    variants: list[tuple[str, list[int]]] = [("all", list(range(num_inputs)))]
    if support and support != list(range(num_inputs)):
        variants.append(("support", support[:]))

    mappings: list[tuple[str, list[int], list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for prefix, variables in variants:
        if len(variables) < 2 or len(variables) % 2:
            continue
        half = len(variables) // 2
        group_sets = [
            ("first_second", variables[:half], variables[half:]),
            ("even_odd", variables[0::2], variables[1::2]),
            ("odd_even", variables[1::2], variables[0::2]),
        ]
        for group_name, left_group, right_group in group_sets:
            if len(left_group) != len(right_group):
                continue
            for left_name, left_order in (("le", left_group), ("be", list(reversed(left_group)))):
                for right_name, right_order in (("le", right_group), ("be", list(reversed(right_group)))):
                    for swap_name, a_order, b_order in (("ab", left_order, right_order), ("ba", right_order, left_order)):
                        key = tuple(a_order + [-1] + b_order)
                        if key in seen:
                            continue
                        seen.add(key)
                        mappings.append((f"{prefix}_{group_name}_{left_name}_{right_name}_{swap_name}", a_order[:], b_order[:]))
    return mappings


def unary_orders(num_inputs: int, support: list[int]) -> list[tuple[str, list[int]]]:
    candidates = [
        ("all_le", list(range(num_inputs))),
        ("all_be", list(reversed(range(num_inputs)))),
    ]
    if support:
        candidates.extend(
            [
                ("support_le", support[:]),
                ("support_be", list(reversed(support))),
            ]
        )
    rows: list[tuple[str, list[int]]] = []
    seen: set[tuple[int, ...]] = set()
    for name, order in candidates:
        key = tuple(order)
        if key not in seen:
            seen.add(key)
            rows.append((name, order))
    return rows


def detect_popcount_and_sorter(table: TruthTable, support: list[int], rows: list[ExactFunctionMatch], seen: set[MatchKey]) -> None:
    if not support:
        return
    max_pop_bit = max(1, math.ceil(math.log2(len(support) + 1)))
    order = format_order(support)
    for output_index in range(table.num_outputs):
        for bit_index in range(max_pop_bit):
            if output_bit_matches(table, output_index, lambda idx, b=bit_index: (sum(bit_at(idx, table.num_inputs, var) for var in support) >> b) & 1):
                add_match(rows, seen, table, output_index, "popcount_output_bit", bit_index, "support_popcount", "unsigned", order, "output equals a popcount bit")
        rank = output_index + 1
        if rank <= len(support) and output_bit_matches(table, output_index, lambda idx, r=rank: int(sum(bit_at(idx, table.num_inputs, var) for var in support) >= r)):
            add_match(rows, seen, table, output_index, "sorter_output_bit", rank - 1, "support_sort_desc", "unsigned", order, f"output equals descending sorted bit rank {rank}")


def detect_binary_arithmetic(
    table: TruthTable,
    support: list[int],
    rows: list[ExactFunctionMatch],
    seen: set[MatchKey],
    max_inputs: int,
) -> None:
    if table.num_inputs > max_inputs:
        return
    active_outputs = [index for index, bits in enumerate(table.outputs) if 0 < sum(bits) < len(bits)]
    if not active_outputs:
        return
    for mapping, a_order, b_order in operand_mappings(table.num_inputs, support):
        width = len(a_order)
        input_order = f"a={format_order(a_order)};b={format_order(b_order)}"
        unsigned_mask = (1 << max(1, table.num_outputs)) - 1
        max_product_bits = max(1, 2 * width)
        for output_index in active_outputs:
            comparators = [
                ("comparator_gt", lambda a, b: int(a > b)),
                ("comparator_ge", lambda a, b: int(a >= b)),
                ("comparator_eq", lambda a, b: int(a == b)),
                ("comparator_lt", lambda a, b: int(a < b)),
            ]
            for name, pred in comparators:
                if output_bit_matches(table, output_index, lambda idx, p=pred: p(input_value(idx, table.num_inputs, a_order), input_value(idx, table.num_inputs, b_order))):
                    add_match(rows, seen, table, output_index, name, 0, mapping, "unsigned", input_order, "exact binary comparator output")

            for bit_index in range(min(table.num_outputs + 1, width + 1)):
                if output_bit_matches(table, output_index, lambda idx, b=bit_index: (input_value(idx, table.num_inputs, a_order) + input_value(idx, table.num_inputs, b_order)) >> b):
                    label = "adder_carry_bit" if bit_index >= width else "adder_sum_bit"
                    add_match(rows, seen, table, output_index, label, bit_index, mapping, "unsigned", input_order, "exact adder output bit")

            for bit_index in range(min(max_product_bits, max(table.num_outputs, max_product_bits))):
                if output_bit_matches(table, output_index, lambda idx, b=bit_index: (input_value(idx, table.num_inputs, a_order) * input_value(idx, table.num_inputs, b_order)) >> b):
                    add_match(rows, seen, table, output_index, "unsigned_multiplier_output_bit", bit_index, mapping, "unsigned", input_order, "exact unsigned product bit")
                signed_mask = (1 << max_product_bits) - 1
                if output_bit_matches(table, output_index, lambda idx, b=bit_index: ((signed_input_value(idx, table.num_inputs, a_order) * signed_input_value(idx, table.num_inputs, b_order)) & signed_mask) >> b):
                    add_match(rows, seen, table, output_index, "signed_multiplier_output_bit", bit_index, mapping, "signed_twos_complement", input_order, "exact signed product bit")

            for bit_index in range(width):
                def quotient_bit(idx: int, b: int = bit_index) -> int:
                    divisor = input_value(idx, table.num_inputs, a_order)
                    dividend = input_value(idx, table.num_inputs, b_order)
                    quotient = unsigned_mask if divisor == 0 else dividend // divisor
                    return (quotient >> b) & 1

                if output_bit_matches(table, output_index, quotient_bit):
                    add_match(rows, seen, table, output_index, "divider_quotient_bit", bit_index, mapping, "unsigned_div0_all_ones", input_order, "exact restoring-divider quotient bit")

                remainder_policies = [
                    ("unsigned_div0_dividend", lambda dividend, divisor: dividend if divisor == 0 else dividend % divisor),
                    ("unsigned_div0_zero", lambda dividend, divisor: 0 if divisor == 0 else dividend % divisor),
                    ("unsigned_div0_all_ones", lambda dividend, divisor: unsigned_mask if divisor == 0 else dividend % divisor),
                ]
                for signedness, fn in remainder_policies:
                    if output_bit_matches(
                        table,
                        output_index,
                        lambda idx, b=bit_index, f=fn: (f(input_value(idx, table.num_inputs, b_order), input_value(idx, table.num_inputs, a_order)) >> b) & 1,
                    ):
                        add_match(rows, seen, table, output_index, "divider_remainder_bit", bit_index, mapping, signedness, input_order, "exact divider remainder/modulo bit")
                        add_match(rows, seen, table, output_index, "modulo_remainder_like", bit_index, mapping, signedness, input_order, "exact modulo-style remainder bit")


def detect_unary_arithmetic(
    table: TruthTable,
    support: list[int],
    rows: list[ExactFunctionMatch],
    seen: set[MatchKey],
    max_inputs: int,
) -> None:
    if table.num_inputs > max_inputs:
        return
    active_outputs = [index for index, bits in enumerate(table.outputs) if 0 < sum(bits) < len(bits)]
    if not active_outputs:
        return
    for mapping, order in unary_orders(table.num_inputs, support):
        input_order = f"x={format_order(order)}"
        max_square_bits = max(1, 2 * len(order))
        for output_index in active_outputs:
            for bit_index in range(min(max_square_bits, max(table.num_outputs, max_square_bits))):
                if output_bit_matches(table, output_index, lambda idx, b=bit_index: (input_value(idx, table.num_inputs, order) ** 2) >> b):
                    add_match(rows, seen, table, output_index, "square_output_bit", bit_index, mapping, "unsigned", input_order, "exact square output bit")
            sqrt_bits = max(1, math.ceil(len(order) / 2))
            for bit_index in range(sqrt_bits):
                if output_bit_matches(table, output_index, lambda idx, b=bit_index: math.isqrt(input_value(idx, table.num_inputs, order)) >> b):
                    add_match(rows, seen, table, output_index, "integer_sqrt_output_bit", bit_index, mapping, "unsigned", input_order, "exact integer square-root output bit")


def exact_matches_for_table(table: TruthTable, max_expensive_inputs: int = 16) -> list[ExactFunctionMatch]:
    rows: list[ExactFunctionMatch] = []
    seen: set[MatchKey] = set()
    support = effective_support(table)
    detect_constants_buffers_affine(table, rows, seen)
    detect_symmetric_thresholds(table, rows, seen)
    detect_popcount_and_sorter(table, support, rows, seen)
    detect_binary_arithmetic(table, support, rows, seen, max_expensive_inputs)
    detect_unary_arithmetic(table, support, rows, seen, max_expensive_inputs)
    return rows


def exact_matches_for_truth(path: Path, max_expensive_inputs: int = 16) -> list[ExactFunctionMatch]:
    return exact_matches_for_table(parse_truth(path), max_expensive_inputs=max_expensive_inputs)


def write_exact_function_matches_csv(path: Path, rows: list[ExactFunctionMatch]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case",
                "output_index",
                "function_type",
                "bit_index",
                "mapping",
                "signedness",
                "input_order",
                "confidence",
                "evidence",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case": row.case,
                    "output_index": row.output_index,
                    "function_type": row.function_type,
                    "bit_index": row.bit_index,
                    "mapping": row.mapping,
                    "signedness": row.signedness,
                    "input_order": row.input_order,
                    "confidence": f"{row.confidence:.3f}",
                    "evidence": row.evidence,
                }
            )


def format_exact_matches(rows: list[ExactFunctionMatch], limit: int = 40) -> str:
    if not rows:
        return "Exact function matches: none"
    lines = [f"Exact function matches: {len(rows)}"]
    for row in rows[:limit]:
        lines.append(
            "- "
            f"y{row.output_index}: {row.function_type}"
            f"{' bit=' + row.bit_index if row.bit_index else ''}, "
            f"mapping={row.mapping}, confidence={row.confidence:.3f}, {row.evidence}"
        )
    if len(rows) > limit:
        lines.append(f"- ... {len(rows) - limit} more")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Template validation helpers (moved from flow_optimizer)
# ---------------------------------------------------------------------------

def truth_output_value(table: TruthTable, index: int) -> int:
    value = 0
    for output_index, bits in enumerate(table.outputs):
        value |= bits[index] << output_index
    return value


def truth_input_value(index: int, num_inputs: int, order: list[int]) -> int:
    value = 0
    for bit_index, var in enumerate(order):
        value |= bit_at(index, num_inputs, var) << bit_index
    return value


def _template_operand_mappings(num_inputs: int) -> list[tuple[str, list[int], list[int]]]:
    """Simplified operand mappings used by match_binary_template (no support filtering)."""
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
    for name, a_order, b_order in _template_operand_mappings(table.num_inputs):
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


def run_validate_templates(benchmarks: "Path", logs: "Path", all_cases: "list[str]") -> None:
    import csv
    from pathlib import Path
    from blif_builder import read_truth
    rows: list[dict[str, str]] = []
    for case in all_cases:
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
