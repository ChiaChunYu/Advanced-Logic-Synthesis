#!/usr/bin/env python3
"""Boolean truth-table fingerprinting and circuit-type classification."""

from __future__ import annotations

import csv
import itertools
import math
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TruthTable:
    case: str
    outputs: list[bytearray]
    num_inputs: int
    num_outputs: int
    num_minterms: int
    on_count: int
    off_count: int
    density: float


@dataclass(frozen=True)
class OutputFeatures:
    output_index: int
    on_count: int
    density: float
    support: list[int]
    anf_degree: int
    anf_terms_by_degree: dict[int, int]
    labels: list[str]
    explanations: list[str]
    npn_template: str | None = None
    npn_transform: str | None = None


@dataclass(frozen=True)
class CaseFingerprint:
    table: TruthTable
    effective_support: list[int]
    influences: list[float]
    monotonicity_scores: list[float]
    monotonicity_dirs: list[str]
    shannon_scores: list[float]
    cofactor_complexities: list[float]
    cofactor_similarities: list[float]
    symmetry_groups: list[list[int]]
    outputs: list[OutputFeatures]
    labels: list[str]
    confidence: float
    explanations: list[str]
    recommended_strategy: str


def parse_truth(path: Path) -> TruthTable:
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

    # ABC read_truth stores truth bits most-significant first.  Reverse each
    # output so index 0 corresponds to the all-zero input assignment.
    outputs = [bytearray(reversed(group)) for group in groups]
    on_count = sum(sum(bits) for bits in outputs)
    total = len(outputs) * num_minterms
    return TruthTable(
        case=path.stem,
        outputs=outputs,
        num_inputs=int(math.log2(num_minterms)),
        num_outputs=len(outputs),
        num_minterms=num_minterms,
        on_count=on_count,
        off_count=total - on_count,
        density=on_count / total,
    )


def bit_at(index: int, num_inputs: int, var: int) -> int:
    return (index >> (num_inputs - 1 - var)) & 1


def set_bit(index: int, num_inputs: int, var: int, value: int) -> int:
    bit = 1 << (num_inputs - 1 - var)
    return (index | bit) if value else (index & ~bit)


def binary_entropy(value: float) -> float:
    if value <= 0.0 or value >= 1.0:
        return 0.0
    return -(value * math.log2(value) + (1.0 - value) * math.log2(1.0 - value))


def compute_case_features(table: TruthTable) -> tuple[list[float], list[float], list[str], list[float], list[float], list[float]]:
    influences: list[float] = []
    monotonicity_scores: list[float] = []
    monotonicity_dirs: list[str] = []
    shannon_scores: list[float] = []
    cofactor_complexities: list[float] = []
    cofactor_similarities: list[float] = []

    pair_count = (table.num_minterms // 2) * table.num_outputs
    for var in range(table.num_inputs):
        diff = 0
        ones0 = 0
        ones1 = 0
        nondec = 0
        noninc = 0
        bit_pos = table.num_inputs - 1 - var
        step = 1 << bit_pos
        period = step << 1
        for bits in table.outputs:
            for base in range(0, table.num_minterms, period):
                for offset in range(step):
                    low = bits[base + offset]
                    high = bits[base + offset + step]
                    ones0 += low
                    ones1 += high
                    diff += low ^ high
                    nondec += int(low <= high)
                    noninc += int(low >= high)

        influence = diff / pair_count
        density0 = ones0 / pair_count
        density1 = ones1 / pair_count
        complexity = (binary_entropy(density0) + binary_entropy(density1)) / 2.0
        balance = 1.0 - abs(density0 - density1)
        influences.append(influence)
        cofactor_complexities.append(complexity)
        cofactor_similarities.append(1.0 - influence)
        shannon_scores.append(0.55 * influence + 0.25 * balance + 0.20 * complexity)
        if nondec >= noninc:
            monotonicity_scores.append(nondec / pair_count)
            monotonicity_dirs.append("positive")
        else:
            monotonicity_scores.append(noninc / pair_count)
            monotonicity_dirs.append("negative")

    return influences, monotonicity_scores, monotonicity_dirs, shannon_scores, cofactor_complexities, cofactor_similarities


def output_influences(bits: bytearray, num_inputs: int) -> list[float]:
    values: list[float] = []
    pair_count = len(bits) // 2
    for var in range(num_inputs):
        diff = 0
        bit_pos = num_inputs - 1 - var
        step = 1 << bit_pos
        period = step << 1
        for base in range(0, len(bits), period):
            for offset in range(step):
                diff += bits[base + offset] ^ bits[base + offset + step]
        values.append(diff / pair_count)
    return values


def anf_coefficients(bits: bytearray) -> list[int]:
    coeffs = list(bits)
    size = len(coeffs)
    step = 1
    while step < size:
        for base in range(0, size, step << 1):
            for offset in range(step):
                coeffs[base + step + offset] ^= coeffs[base + offset]
        step <<= 1
    return coeffs


def anf_stats(bits: bytearray) -> tuple[int, dict[int, int]]:
    coeffs = anf_coefficients(bits)
    terms_by_degree: dict[int, int] = {}
    degree = 0
    for mask, value in enumerate(coeffs):
        if not value:
            continue
        term_degree = mask.bit_count()
        degree = max(degree, term_degree)
        terms_by_degree[term_degree] = terms_by_degree.get(term_degree, 0) + 1
    return degree, terms_by_degree


def compressed_bits(bits: bytearray, num_inputs: int, support: list[int]) -> tuple[int, ...]:
    if not support:
        return (bits[0],)
    result: list[int] = []
    for compact_index in range(1 << len(support)):
        original = 0
        for pos, var in enumerate(support):
            if (compact_index >> (len(support) - 1 - pos)) & 1:
                original = set_bit(original, num_inputs, var, 1)
        result.append(bits[original])
    return tuple(result)


def is_symmetric(bits: bytearray, num_inputs: int, support: list[int]) -> tuple[bool, str]:
    if not support:
        return True, "constant over empty support"
    by_weight: dict[int, int] = {}
    for index in range(1 << len(support)):
        original = 0
        weight = 0
        for pos, var in enumerate(support):
            value = (index >> (len(support) - 1 - pos)) & 1
            weight += value
            if value:
                original = set_bit(original, num_inputs, var, 1)
        value = bits[original]
        if weight in by_weight and by_weight[weight] != value:
            return False, ""
        by_weight[weight] = value
    signature = "".join(str(by_weight.get(weight, 0)) for weight in range(len(support) + 1))
    return True, f"depends only on Hamming weight signature {signature}"


def threshold_label_from_symmetric(bits: bytearray, num_inputs: int, support: list[int]) -> tuple[str | None, str | None]:
    by_weight: dict[int, int] = {}
    for index in range(1 << len(support)):
        original = 0
        weight = 0
        for pos, var in enumerate(support):
            value = (index >> (len(support) - 1 - pos)) & 1
            weight += value
            if value:
                original = set_bit(original, num_inputs, var, 1)
        by_weight[weight] = bits[original]
    ones = [weight for weight, value in by_weight.items() if value]
    if not ones:
        return "constant_zero", "all symmetric weight classes are 0"
    if len(ones) == len(support) + 1:
        return "constant_one", "all symmetric weight classes are 1"
    if len(ones) == 1:
        weight = ones[0]
        if weight == 1:
            return "one_hot_exactly_one", "true exactly when one support input is 1"
        return "exact_k", f"true exactly when Hamming weight is {weight}"
    if ones == list(range(min(ones), len(support) + 1)):
        threshold = min(ones)
        if threshold == (len(support) + 1) // 2 and len(support) % 2 == 1:
            return "majority", f"majority threshold weight >= {threshold}"
        return "threshold_positive", f"true for Hamming weight >= {threshold}"
    if ones == list(range(0, max(ones) + 1)):
        return "threshold_negative", f"true for Hamming weight <= {max(ones)}"
    return None, None


def detect_cube(bits: bytearray, num_inputs: int, support: list[int]) -> tuple[bool, str]:
    if not support:
        return False, ""
    fixed: dict[int, int] = {}
    on_indices = [index for index, value in enumerate(bits) if value]
    if not on_indices:
        return False, ""
    for var in support:
        values = {bit_at(index, num_inputs, var) for index in on_indices}
        if len(values) == 1:
            fixed[var] = next(iter(values))
    expected = 1 << (num_inputs - len(fixed))
    if len(on_indices) == expected and len(fixed) == len(support):
        lits = " ".join(f"x{var}={value}" for var, value in fixed.items())
        return True, f"single cube over support literals: {lits}"
    if len(on_indices) <= max(4, 1 << max(0, len(support) // 3)):
        return True, f"sparse decoder-like cover with {len(on_indices)} on minterms"
    return False, ""


def detect_comparator(bits: bytearray, num_inputs: int) -> tuple[str | None, str | None]:
    groupings: list[tuple[str, list[int], list[int]]] = []
    half = num_inputs // 2
    if num_inputs >= 2 and num_inputs % 2 == 0:
        groupings.append(("first_half_vs_second_half", list(range(half)), list(range(half, num_inputs))))
        groupings.append(("first_half_vs_reversed_second_half", list(range(half)), list(reversed(range(half, num_inputs)))))
        groupings.append(("even_vs_odd", list(range(0, num_inputs, 2)), list(range(1, num_inputs, 2))))
    for name, left_vars, right_vars in groupings:
        if len(left_vars) != len(right_vars):
            continue
        matches = {"equality": True, "greater_than": True, "less_than": True}
        inv_matches = {"not_equal": True, "less_or_equal": True, "greater_or_equal": True}
        for index, value in enumerate(bits):
            left = 0
            right = 0
            for var in left_vars:
                left = (left << 1) | bit_at(index, num_inputs, var)
            for var in right_vars:
                right = (right << 1) | bit_at(index, num_inputs, var)
            expected = {
                "equality": int(left == right),
                "greater_than": int(left > right),
                "less_than": int(left < right),
            }
            inv_expected = {
                "not_equal": int(left != right),
                "less_or_equal": int(left <= right),
                "greater_or_equal": int(left >= right),
            }
            for label, exp in expected.items():
                if value != exp:
                    matches[label] = False
            for label, exp in inv_expected.items():
                if value != exp:
                    inv_matches[label] = False
        for label, ok in {**matches, **inv_matches}.items():
            if ok:
                return f"comparator_like_{label}", f"matches {label} under {name}"
    return None, None


def detect_mux_like(bits: bytearray, num_inputs: int, support: list[int]) -> tuple[bool, str]:
    if len(support) < 3:
        return False, ""
    full_support = len(support)
    best: tuple[int, int] | None = None
    for selector in support:
        low_support: set[int] = set()
        high_support: set[int] = set()
        for var in support:
            if var == selector:
                continue
            bit_pos = num_inputs - 1 - var
            step = 1 << bit_pos
            period = step << 1
            low_diff = 0
            high_diff = 0
            for base in range(0, len(bits), period):
                for offset in range(step):
                    low0 = set_bit(base + offset, num_inputs, selector, 0)
                    low1 = set_bit(base + offset + step, num_inputs, selector, 0)
                    high0 = set_bit(base + offset, num_inputs, selector, 1)
                    high1 = set_bit(base + offset + step, num_inputs, selector, 1)
                    low_diff += bits[low0] ^ bits[low1]
                    high_diff += bits[high0] ^ bits[high1]
            if low_diff:
                low_support.add(var)
            if high_diff:
                high_support.add(var)
        reduction = (full_support - 1) * 2 - len(low_support) - len(high_support)
        if best is None or reduction > best[1]:
            best = (selector, reduction)
    if best and best[1] >= max(2, len(support) // 3):
        return True, f"x{best[0]} gives strong Shannon support reduction score {best[1]}"
    return False, ""


def detect_adder_like(labels: list[str], anf_degree: int, terms_by_degree: dict[int, int], support_size: int) -> tuple[str | None, str | None]:
    if "affine" in labels and support_size >= 3:
        return "adder_sum_like", "affine/parity output over at least three inputs"
    if ("majority" in labels or "threshold_positive" in labels) and anf_degree == 2 and support_size in (3, 4):
        return "carry_like", "low-degree threshold output resembles carry logic"
    if terms_by_degree.get(2, 0) >= 3 and support_size >= 3 and anf_degree <= 2:
        return "carry_like", "quadratic ANF terms dominate, resembling carry logic"
    return None, None


def transform_bits(bits: tuple[int, ...], perm: tuple[int, ...], neg_mask: int, out_neg: int) -> str:
    n = len(perm)
    result: list[str] = []
    for new_index in range(1 << n):
        old_index = 0
        for new_pos, old_pos in enumerate(perm):
            value = (new_index >> (n - 1 - new_pos)) & 1
            if (neg_mask >> old_pos) & 1:
                value ^= 1
            if value:
                old_index |= 1 << (n - 1 - old_pos)
        result.append(str(bits[old_index] ^ out_neg))
    return "".join(result)


def npn_canonical(bits: tuple[int, ...]) -> tuple[str, str]:
    n = int(math.log2(len(bits)))
    best = ""
    best_transform = ""
    for perm in itertools.permutations(range(n)):
        for neg_mask in range(1 << n):
            for out_neg in (0, 1):
                image = transform_bits(bits, perm, neg_mask, out_neg)
                transform = f"perm={perm}, neg_mask={neg_mask:0{n}b}, out_neg={out_neg}"
                if not best or image < best:
                    best = image
                    best_transform = transform
    return best, best_transform


def template_bits(name: str, n: int) -> tuple[int, ...] | None:
    if name in {"AND", "NAND", "OR", "NOR", "XOR", "XNOR", "exact-one"}:
        values = []
        for index in range(1 << n):
            weight = index.bit_count()
            if name == "AND":
                value = int(weight == n)
            elif name == "NAND":
                value = int(weight != n)
            elif name == "OR":
                value = int(weight > 0)
            elif name == "NOR":
                value = int(weight == 0)
            elif name == "XOR":
                value = weight & 1
            elif name == "XNOR":
                value = (weight & 1) ^ 1
            else:
                value = int(weight == 1)
            values.append(value)
        return tuple(values)
    if name == "MUX" and n == 3:
        return tuple(((index >> 1) & 1) if ((index >> 2) & 1) == 0 else (index & 1) for index in range(8))
    if name == "MAJ3" and n == 3:
        return tuple(int(index.bit_count() >= 2) for index in range(8))
    if name == "AOI21" and n == 3:
        return tuple(int(not ((((index >> 2) & 1) & ((index >> 1) & 1)) | (index & 1))) for index in range(8))
    if name == "OAI21" and n == 3:
        return tuple(int(not ((((index >> 2) & 1) | ((index >> 1) & 1)) & (index & 1))) for index in range(8))
    if name == "equality" and n % 2 == 0 and n > 0:
        half = n // 2
        values = []
        for index in range(1 << n):
            left = index >> half
            right = index & ((1 << half) - 1)
            values.append(int(left == right))
        return tuple(values)
    if name == "implication" and n == 2:
        return tuple(int((not ((index >> 1) & 1)) or (index & 1)) for index in range(4))
    return None


def npn_template_match(bits: tuple[int, ...]) -> tuple[str | None, str | None]:
    n = int(math.log2(len(bits)))
    if n > 6:
        return None, None
    canon, transform = npn_canonical(bits)
    names = ["AND", "OR", "NAND", "NOR", "XOR", "XNOR", "MUX", "MAJ3", "AOI21", "OAI21", "exact-one", "equality", "implication"]
    for k in range(2, n + 1):
        name = f"at-least-{k}"
        values = tuple(int(index.bit_count() >= k) for index in range(1 << n))
        template_canon, _ = npn_canonical(values)
        if canon == template_canon:
            return name, transform
    for name in names:
        values = template_bits(name, n)
        if values is None:
            continue
        template_canon, _ = npn_canonical(values)
        if canon == template_canon:
            return name, transform
    return None, None


def classify_output(bits: bytearray, table: TruthTable, output_index: int) -> OutputFeatures:
    influences = output_influences(bits, table.num_inputs)
    support = [var for var, value in enumerate(influences) if value > 0.0]
    labels: list[str] = []
    explanations: list[str] = []
    on_count = sum(bits)
    density = on_count / len(bits)
    anf_degree, terms_by_degree = anf_stats(bits)

    if on_count == 0:
        labels.append("constant_zero")
        explanations.append("output is always 0")
    elif on_count == len(bits):
        labels.append("constant_one")
        explanations.append("output is always 1")

    for var in support:
        is_buffer = True
        is_inverter = True
        for index, value in enumerate(bits):
            input_value = bit_at(index, table.num_inputs, var)
            if value != input_value:
                is_buffer = False
            if value != (input_value ^ 1):
                is_inverter = False
            if not is_buffer and not is_inverter:
                break
        if is_buffer:
            labels.append("buffer")
            explanations.append(f"output equals x{var}")
        if is_inverter:
            labels.append("inverter")
            explanations.append(f"output equals not x{var}")

    if anf_degree <= 1 and "constant_zero" not in labels and "constant_one" not in labels:
        labels.append("affine")
        linear_terms = terms_by_degree.get(1, 0)
        if linear_terms >= 2:
            labels.append("parity")
            explanations.append(f"ANF degree 1 with {linear_terms} linear terms")
        else:
            explanations.append("ANF degree <= 1")

    symmetric, sym_reason = is_symmetric(bits, table.num_inputs, support)
    if symmetric and support:
        labels.append("symmetric")
        explanations.append(sym_reason)
        threshold_label, threshold_reason = threshold_label_from_symmetric(bits, table.num_inputs, support)
        if threshold_label:
            labels.append(threshold_label)
            explanations.append(threshold_reason or "")

    cube, cube_reason = detect_cube(bits, table.num_inputs, support)
    if cube:
        labels.append("cube_decoder_like")
        explanations.append(cube_reason)

    comparator_label, comparator_reason = detect_comparator(bits, table.num_inputs)
    if comparator_label:
        labels.append(comparator_label)
        explanations.append(comparator_reason or "")

    mux_like, mux_reason = detect_mux_like(bits, table.num_inputs, support)
    if mux_like:
        labels.append("mux_like")
        explanations.append(mux_reason)

    adder_label, adder_reason = detect_adder_like(labels, anf_degree, terms_by_degree, len(support))
    if adder_label:
        labels.append(adder_label)
        explanations.append(adder_reason or "")

    npn_label = None
    npn_transform = None
    if 1 <= len(support) <= 6:
        compact = compressed_bits(bits, table.num_inputs, support)
        npn_label, npn_transform = npn_template_match(compact)
        if npn_label:
            labels.append(f"npn_{npn_label}")
            explanations.append(f"NPN template match {npn_label}: {npn_transform}")

    deduped_labels = list(dict.fromkeys(labels))
    deduped_explanations = list(dict.fromkeys(item for item in explanations if item))
    return OutputFeatures(
        output_index=output_index,
        on_count=on_count,
        density=density,
        support=support,
        anf_degree=anf_degree,
        anf_terms_by_degree=terms_by_degree,
        labels=deduped_labels,
        explanations=deduped_explanations,
        npn_template=npn_label,
        npn_transform=npn_transform,
    )


def exact_symmetry_groups(table: TruthTable, effective_support: list[int]) -> list[list[int]]:
    parent = {var: var for var in effective_support}

    def find(var: int) -> int:
        while parent[var] != var:
            parent[var] = parent[parent[var]]
            var = parent[var]
        return var

    def union(left: int, right: int) -> None:
        root_l = find(left)
        root_r = find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    def symmetric_pair(left: int, right: int) -> bool:
        left_bit = 1 << (table.num_inputs - 1 - left)
        right_bit = 1 << (table.num_inputs - 1 - right)
        for index in range(table.num_minterms):
            left_value = bool(index & left_bit)
            right_value = bool(index & right_bit)
            if left_value == right_value:
                continue
            swapped = index ^ left_bit ^ right_bit
            for bits in table.outputs:
                if bits[index] != bits[swapped]:
                    return False
        return True

    for i, left in enumerate(effective_support):
        for right in effective_support[i + 1 :]:
            if symmetric_pair(left, right):
                union(left, right)
    groups: dict[int, list[int]] = {}
    for var in effective_support:
        groups.setdefault(find(var), []).append(var)
    return [group for group in groups.values() if len(group) > 1]


def aggregate_labels(outputs: list[OutputFeatures]) -> tuple[list[str], list[str], float]:
    counts: dict[str, int] = {}
    explanations: list[str] = []
    for output in outputs:
        for label in output.labels:
            counts[label] = counts.get(label, 0) + 1
        for explanation in output.explanations[:3]:
            explanations.append(f"y{output.output_index}: {explanation}")
    if not counts:
        return ["general_random"], ["no exact detector matched strongly"], 0.35
    if any(output.labels for output in outputs) and sum(1 for output in outputs if not output.labels) >= len(outputs) // 2:
        counts["mixed_general_logic"] = sum(1 for output in outputs if not output.labels)
    priority = [
        "constant_zero",
        "constant_one",
        "buffer",
        "inverter",
        "affine",
        "parity",
        "symmetric",
        "majority",
        "threshold_positive",
        "threshold_negative",
        "exact_k",
        "one_hot_exactly_one",
        "cube_decoder_like",
        "mux_like",
        "adder_sum_like",
        "carry_like",
    ]
    ordered = sorted(counts, key=lambda label: (-counts[label], priority.index(label) if label in priority else 99, label))
    labels = ordered[:8]
    top_count = counts[labels[0]]
    confidence = min(0.98, 0.35 + 0.55 * (top_count / max(1, len(outputs))) + 0.05 * min(3, len(labels)))
    return labels, list(dict.fromkeys(explanations))[:12], confidence


def recommended_strategy(labels: list[str], effective_support_size: int) -> str:
    label_set = set(labels)
    if "parity" in label_set or "affine" in label_set:
        return "xor_tree_initial_then_balance_rewrite"
    if label_set & {"majority", "threshold_positive", "threshold_negative", "exact_k", "one_hot_exactly_one"}:
        return "threshold_or_popcount_initial"
    if "cube_decoder_like" in label_set:
        return "sop_or_factored_sop_initial"
    if "mux_like" in label_set:
        return "selector_first_shannon_bdd_initial"
    if any(label.startswith("comparator_like") for label in label_set):
        return "comparator_grouped_bdd_initial"
    if any(label.startswith("npn_") for label in label_set) and effective_support_size <= 6:
        return "direct_small_npn_template_initial"
    if "carry_like" in label_set or "adder_sum_like" in label_set:
        return "arithmetic_bdd_or_xor_carry_initial"
    return "abc_portfolio_general_random"


def fingerprint_case(truth: Path) -> CaseFingerprint:
    table = parse_truth(truth)
    influences, monotonicity_scores, monotonicity_dirs, shannon_scores, cofactor_complexities, cofactor_similarities = compute_case_features(table)
    effective_support = [var for var, value in enumerate(influences) if value > 0.0]
    outputs = [classify_output(bits, table, index) for index, bits in enumerate(table.outputs)]
    symmetry_groups = exact_symmetry_groups(table, effective_support)
    labels, explanations, confidence = aggregate_labels(outputs)
    if symmetry_groups:
        labels = list(dict.fromkeys(labels + ["symmetric_variable_groups"]))
        explanations.append("case-level exact symmetry groups: " + "; ".join("{" + ",".join(f"x{v}" for v in group) + "}" for group in symmetry_groups))
        confidence = min(0.99, confidence + 0.03)
    strategy = recommended_strategy(labels, len(effective_support))
    return CaseFingerprint(
        table=table,
        effective_support=effective_support,
        influences=influences,
        monotonicity_scores=monotonicity_scores,
        monotonicity_dirs=monotonicity_dirs,
        shannon_scores=shannon_scores,
        cofactor_complexities=cofactor_complexities,
        cofactor_similarities=cofactor_similarities,
        symmetry_groups=symmetry_groups,
        outputs=outputs,
        labels=labels,
        confidence=confidence,
        explanations=explanations,
        recommended_strategy=strategy,
    )


def format_fingerprint(fp: CaseFingerprint) -> str:
    table = fp.table
    support = ", ".join(f"x{var}" for var in fp.effective_support) or "(none)"
    labels = ", ".join(fp.labels)
    influence = ", ".join(f"x{i}:{value:.4f}" for i, value in enumerate(fp.influences))
    monotone = ", ".join(f"x{i}:{fp.monotonicity_dirs[i]}:{fp.monotonicity_scores[i]:.3f}" for i in range(table.num_inputs))
    shannon = ", ".join(f"x{i}:{fp.shannon_scores[i]:.4f}" for i in range(table.num_inputs))
    cofactor = ", ".join(f"x{i}:complex={fp.cofactor_complexities[i]:.3f},sim={fp.cofactor_similarities[i]:.3f}" for i in range(table.num_inputs))
    symmetry = "; ".join("{" + ", ".join(f"x{var}" for var in group) + "}" for group in fp.symmetry_groups) or "(none)"
    max_degree = max((output.anf_degree for output in fp.outputs), default=0)
    degree_counts: dict[int, int] = {}
    for output in fp.outputs:
        for degree, count in output.anf_terms_by_degree.items():
            degree_counts[degree] = degree_counts.get(degree, 0) + count
    degree_text = ", ".join(f"deg{degree}:{degree_counts[degree]}" for degree in sorted(degree_counts))
    output_lines = []
    for output in fp.outputs[: min(8, len(fp.outputs))]:
        output_lines.append(
            f"  y{output.output_index}: support={len(output.support)}, density={output.density:.4f}, "
            f"anf_degree={output.anf_degree}, labels={','.join(output.labels) or 'general'}"
        )
    if len(fp.outputs) > 8:
        output_lines.append(f"  ... {len(fp.outputs) - 8} more outputs")
    explanation = "\n".join(f"- {item}" for item in fp.explanations) or "- no strong exact detector matched"
    return "\n".join(
        [
            f"case: {table.case}",
            "Feature summary:",
            f"- original inputs: {table.num_inputs}",
            f"- outputs: {table.num_outputs}",
            f"- effective support size: {len(fp.effective_support)}",
            f"- effective support map: {support}",
            f"- on-set count/density: {table.on_count} / {table.density:.6f}",
            f"- off-set count/density: {table.off_count} / {1.0 - table.density:.6f}",
            f"- per-input influence: {influence}",
            f"- monotonicity: {monotone}",
            f"- Shannon split scores: {shannon}",
            f"- cofactor complexity/similarity: {cofactor}",
            f"- symmetry groups: {symmetry}",
            f"- max ANF degree: {max_degree}",
            f"- ANF terms by degree: {degree_text}",
            "Per-output detector summary:",
            *output_lines,
            "Detected labels:",
            f"- {labels}",
            f"Confidence: {fp.confidence:.3f}",
            "Explanations:",
            explanation,
            f"Recommended initial synthesis method: {fp.recommended_strategy}",
        ]
    )


def append_classification_csv(path: Path, fp: CaseFingerprint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_degree = max((output.anf_degree for output in fp.outputs), default=0)
    row = {
        "case": fp.table.case,
        "effective_support": len(fp.effective_support),
        "density": f"{fp.table.density:.6f}",
        "anf_degree": max_degree,
        "labels": "|".join(fp.labels),
        "confidence": f"{fp.confidence:.6f}",
        "explanation": " ; ".join(fp.explanations[:8]),
        "recommended_strategy": fp.recommended_strategy,
    }
    fieldnames = ["case", "effective_support", "density", "anf_degree", "labels", "confidence", "explanation", "recommended_strategy"]
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = [item for item in csv.DictReader(handle) if item.get("case") != fp.table.case]
    existing.append(row)
    existing.sort(key=lambda item: item["case"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing)
