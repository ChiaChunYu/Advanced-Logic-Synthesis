#!/usr/bin/env python3
"""Circuit analysis: Boolean truth-table fingerprinting and exact function recognition.

# ── Section 1: Boolean Fingerprint ──────────────────────────────────────────
# Computes truth-table features (influences, entropy, symmetry, ANF, NPN
# canonical forms) and classifies each output as adder/multiplier/comparator/
# threshold etc. Used to steer the synthesis strategy per case.

# ── Section 2: Exact Function Recognition ───────────────────────────────────
# Proof-based detection of known arithmetic functions (adder, multiplier,
# divider, sqrt, square, comparator, popcount, affine, threshold).  A match is
# only reported after checking every row of the truth table; the optimizer uses
# these as safe hints while final AIG replacement still goes through ABC CEC.
"""


# ---------------------------------------------------------------------------
# Section 1: Boolean Fingerprint
# ---------------------------------------------------------------------------

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
    if "monotone_positive_general" in label_set:
        return "monotone_factor_then_delay_area_refine"
    if "constant_output_mixed" in label_set:
        return "constant_aware_multioutput_refine"
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
    if labels == ["general_random"]:
        if monotonicity_scores:
            strong_monotone = [
                index
                for index, score in enumerate(monotonicity_scores)
                if score >= 0.86 and monotonicity_dirs[index] == "positive"
            ]
            if len(strong_monotone) >= max(2, len(effective_support) // 3):
                if "monotone_positive_general" not in labels:
                    labels.append("monotone_positive_general")
                explanations.append(
                    "case-level positive monotone variables: "
                    + ", ".join(f"x{index}" for index in strong_monotone[:12])
                )
                confidence = min(0.99, confidence + 0.08)
    constant_outputs = sum(
        1
        for output in outputs
        if "constant_zero" in output.labels or "constant_one" in output.labels
    )
    if constant_outputs and constant_outputs < len(outputs):
        if "constant_output_mixed" not in labels:
            labels.append("constant_output_mixed")
        explanations.append(f"case-level mixed constant outputs: {constant_outputs}/{len(outputs)}")
        confidence = min(0.99, confidence + 0.02)
    if symmetry_groups:
        if "symmetric_variable_groups" not in labels:
            labels.append("symmetric_variable_groups")
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

# ---------------------------------------------------------------------------
# Section 2: Exact Function Recognition
# ---------------------------------------------------------------------------


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
    from pathlib import Path
    from blif_builder import read_truth
    rows: list[dict[str, str]] = []
    for case in all_cases:
        table = read_truth(benchmarks / f"{case}.truth")
        rows.extend(validate_template_case(case, table))
    matched = [row for row in rows if row["matched"] == "1"]
    print(f"[validate] matched template rows: {len(matched)}")