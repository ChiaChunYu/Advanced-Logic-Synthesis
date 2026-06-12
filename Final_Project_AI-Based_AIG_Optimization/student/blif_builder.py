#!/usr/bin/env python3
"""BLIF generation layer for AIG synthesis.

All BLIF file construction goes through this module: SOP covers, BDD-based
netlists, class-split netlists, and structural arithmetic circuits.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# TruthTable (duplicated here for standalone use; flow_optimizer imports it too)
# ---------------------------------------------------------------------------

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


def binary_entropy(value: float) -> float:
    if value <= 0.0 or value >= 1.0:
        return 0.0
    return -(value * math.log2(value) + (1.0 - value) * math.log2(1.0 - value))


def read_truth(path: Path) -> "TruthTable":
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


def write_complement_truth(path: Path, table: "TruthTable") -> None:
    groups = []
    for bits in table.outputs:
        groups.append("".join(str(bit ^ 1) for bit in reversed(bits)))
    path.write_text("\n".join(groups) + "\n", encoding="ascii")


# ---------------------------------------------------------------------------
# Header / cube helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SOP / cover BLIF
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# BlifBuilder — structural netlist construction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Factored SOP
# ---------------------------------------------------------------------------

def emit_cube(builder: BlifBuilder, active_vars: list[int], cube: tuple[int, ...]) -> str:
    signal = builder.const1
    for var, bit in zip(active_vars, cube):
        if bit < 0:
            continue
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


# ---------------------------------------------------------------------------
# BDD support helpers
# ---------------------------------------------------------------------------

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


def compact_index_to_original(compact_index: int, support: list[int], num_inputs: int) -> int:
    original = 0
    width = len(support)
    for pos, var in enumerate(support):
        if (compact_index >> (width - 1 - pos)) & 1:
            original |= 1 << (num_inputs - 1 - var)
    return original


# ---------------------------------------------------------------------------
# BDD BLIF writers
# ---------------------------------------------------------------------------

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


def emit_bdd_signal(
    builder: BlifBuilder,
    bits: tuple[int, ...],
    support: list[int],
    order: list[int],
    node_limit: int,
) -> str:
    if not any(bits):
        return builder.const0
    if all(bits):
        return builder.const1
    support_to_pos = {var: pos for pos, var in enumerate(support)}
    compact_order = [support_to_pos[var] for var in order if var in support_to_pos]
    compact_order.extend(pos for pos in range(len(support)) if pos not in compact_order)
    variables = tuple(range(len(support)))
    cache: dict[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]], str] = {}

    def build(values: tuple[int, ...], vars_left: tuple[int, ...], order_left: tuple[int, ...]) -> str:
        if not any(values):
            return builder.const0
        if all(values):
            return builder.const1
        if not order_left:
            raise RuntimeError("non-constant terminal without variables")
        key = (values, vars_left, order_left)
        if key in cache:
            return cache[key]
        if builder.counter > node_limit:
            raise RuntimeError("class-split BDD node limit exceeded")
        var_pos = order_left[0]
        split_index = vars_left.index(var_pos)
        low_bits, high_bits = cofactor_compact(values, split_index, len(vars_left))
        next_vars = tuple(var for var in vars_left if var != var_pos)
        next_order = tuple(var for var in order_left if var != var_pos)
        low_signal = build(low_bits, next_vars, next_order)
        high_signal = build(high_bits, next_vars, next_order)
        signal = builder.emit_mux(support[var_pos], low_signal, high_signal)
        cache[key] = signal
        return signal

    return build(bits, variables, tuple(compact_order))


def emit_shared_bdd_signal(
    builder: BlifBuilder,
    bits: tuple[int, ...],
    support: list[int],
    compact_order: tuple[int, ...],
    cache: dict[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]], str],
    node_limit: int,
) -> str:
    if not any(bits):
        return builder.const0
    if all(bits):
        return builder.const1
    variables = tuple(range(len(support)))

    def build(values: tuple[int, ...], vars_left: tuple[int, ...], order_left: tuple[int, ...]) -> str:
        if not any(values):
            return builder.const0
        if all(values):
            return builder.const1
        if not order_left:
            raise RuntimeError("non-constant terminal without variables")
        key = (values, vars_left, order_left)
        if key in cache:
            return cache[key]
        inverted = tuple(1 - bit for bit in values)
        inverted_key = (inverted, vars_left, order_left)
        if inverted_key in cache:
            signal = builder.emit_not(cache[inverted_key])
            cache[key] = signal
            return signal
        if builder.counter > node_limit:
            raise RuntimeError("shared BDD node limit exceeded")
        var_pos = order_left[0]
        split_index = vars_left.index(var_pos)
        low_bits, high_bits = cofactor_compact(values, split_index, len(vars_left))
        next_vars = tuple(var for var in vars_left if var != var_pos)
        next_order = tuple(var for var in order_left if var != var_pos)
        low_signal = build(low_bits, next_vars, next_order)
        high_signal = build(high_bits, next_vars, next_order)
        signal = builder.emit_mux(support[var_pos], low_signal, high_signal)
        cache[key] = signal
        return signal

    return build(bits, variables, compact_order)


def write_shared_multioutput_bdd_blif(
    path: Path,
    model: str,
    table: TruthTable,
    order: list[int],
    node_limit: int,
) -> tuple[bool, str]:
    support = table.active_vars
    if len(support) > 16:
        return False, f"support {len(support)} exceeds shared BDD limit"
    support_to_pos = {var: pos for pos, var in enumerate(support)}
    compact_order = [support_to_pos[var] for var in order if var in support_to_pos]
    compact_order.extend(pos for pos in range(len(support)) if pos not in compact_order)
    compact_order_tuple = tuple(compact_order)
    index_map = [compact_index_to_original(i, support, table.num_inputs) for i in range(1 << len(support))]
    cache: dict[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]], str] = {}
    builder = BlifBuilder(table, model)
    signals: list[str] = []
    for output_index in range(table.num_outputs):
        bits = tuple(table.outputs[output_index][orig] for orig in index_map)
        signals.append(emit_shared_bdd_signal(builder, bits, support, compact_order_tuple, cache, node_limit))
    builder.finish(signals, path)
    return True, f"shared_nodes={len(cache)}, order={','.join(f'x{support[pos]}' for pos in compact_order_tuple)}"


# ---------------------------------------------------------------------------
# Class-split BLIF
# ---------------------------------------------------------------------------

def emit_class_decoder(builder: BlifBuilder, class_vars: list[int], class_value: int) -> str:
    signal = builder.const1
    width = len(class_vars)
    for pos, var in enumerate(class_vars):
        bit = (class_value >> (width - 1 - pos)) & 1
        literal = f"x{var}" if bit else builder.emit_not(f"x{var}")
        signal = builder.emit_and(signal, literal)
    return signal


def class_cofactor_bits(
    table: TruthTable,
    output_index: int,
    class_vars: list[int],
    class_value: int,
    residual_vars: list[int],
) -> tuple[int, ...]:
    values: list[int] = []
    class_width = len(class_vars)
    residual_width = len(residual_vars)
    class_base = 0
    for pos, var in enumerate(class_vars):
        if (class_value >> (class_width - 1 - pos)) & 1:
            class_base |= 1 << (table.num_inputs - 1 - var)
    for residual_index in range(1 << residual_width):
        original = class_base | compact_index_to_original(residual_index, residual_vars, table.num_inputs)
        values.append(table.outputs[output_index][original])
    return tuple(values)


def write_class_split_blif(
    path: Path,
    model: str,
    table: TruthTable,
    class_vars: list[int],
    order: list[int],
    node_limit: int,
    max_classes: int,
) -> tuple[bool, str]:
    class_vars = [var for var in class_vars if var in table.active_vars]
    if not class_vars or len(class_vars) > 8:
        return False, "class split needs 1..8 active class variables"
    residual_vars = [var for var in table.active_vars if var not in set(class_vars)]
    if len(residual_vars) > 12:
        return False, f"residual support {len(residual_vars)} exceeds limit"
    class_count = 1 << len(class_vars)
    if class_count > max_classes:
        return False, f"class count {class_count} exceeds limit {max_classes}"

    builder = BlifBuilder(table, model)
    decoders = [emit_class_decoder(builder, class_vars, value) for value in range(class_count)]
    residual_order = [var for var in order if var in residual_vars]
    residual_order.extend(var for var in residual_vars if var not in residual_order)
    residual_cache: dict[tuple[int, ...], str] = {}
    reused = 0
    complemented = 0

    def residual_signal(bits: tuple[int, ...]) -> str:
        nonlocal reused, complemented
        if bits in residual_cache:
            reused += 1
            return residual_cache[bits]
        inverted = tuple(1 - bit for bit in bits)
        if inverted in residual_cache:
            complemented += 1
            signal = builder.emit_not(residual_cache[inverted])
            residual_cache[bits] = signal
            return signal
        signal = emit_bdd_signal(builder, bits, residual_vars, residual_order, node_limit)
        residual_cache[bits] = signal
        return signal

    outputs: list[str] = []
    for output_index in range(table.num_outputs):
        terms: list[str] = []
        for class_value, decoder in enumerate(decoders):
            bits = class_cofactor_bits(table, output_index, class_vars, class_value, residual_vars)
            if not any(bits):
                continue
            if all(bits):
                terms.append(decoder)
                continue
            signal = residual_signal(bits)
            terms.append(builder.emit_and(decoder, signal))
        outputs.append(emit_or_tree(builder, terms))
    builder.finish(outputs, path)
    return (
        True,
        f"class_vars={','.join(f'x{var}' for var in class_vars)}, residual={len(residual_vars)}, "
        f"shared_cofactors={len(residual_cache)}, reused={reused}, complemented={complemented}",
    )


def tuple_support(bits: tuple[int, ...], support: list[int]) -> list[int]:
    if not any(bits) or all(bits):
        return []
    active: list[int] = []
    width = len(support)
    for pos, var in enumerate(support):
        bit_pos = width - 1 - pos
        step = 1 << bit_pos
        period = step << 1
        depends = False
        for base in range(0, len(bits), period):
            for offset in range(step):
                if bits[base + offset] != bits[base + offset + step]:
                    depends = True
                    break
            if depends:
                break
        if depends:
            active.append(var)
    return active


def estimate_output_split_cost(table: TruthTable, output_index: int, class_vars: list[int]) -> tuple[int, int]:
    residual_vars = [var for var in table.active_vars if var not in set(class_vars)]
    class_count = 1 << len(class_vars)
    cost = class_count * max(1, len(class_vars))
    nonconstant = 0
    for class_value in range(class_count):
        bits = class_cofactor_bits(table, output_index, class_vars, class_value, residual_vars)
        if not any(bits) or all(bits):
            cost += 1
            continue
        nonconstant += 1
        support_size = len(tuple_support(bits, residual_vars))
        cost += 1 << min(support_size, 12)
    return cost, nonconstant


def choose_output_class_vars(
    case: str,
    table: TruthTable,
    output_index: int,
    seed: int,
) -> tuple[str, list[int], list[int], str]:
    support = output_support(table, output_index)
    if len(support) <= 6:
        order = sorted(support, key=lambda var: table.influences[var], reverse=True)
        return "small_support", [], order, f"support={len(support)}"

    candidates = semantic_split_specs(case, table, seed, 8)
    high_influence = sorted(support, key=lambda var: table.influences[var], reverse=True)
    shannon_order = sorted(support, key=lambda var: table.shannon_scores[var], reverse=True)
    for width in (3, 4, 5):
        candidates.append((f"y{output_index}_shannon{width}", shannon_order[: min(width, len(shannon_order))], shannon_order))
        candidates.append((f"y{output_index}_influence{width}", high_influence[: min(width, len(high_influence))], high_influence))

    best: tuple[int, int, str, list[int], list[int]] | None = None
    seen: set[tuple[int, ...]] = set()
    for name, class_vars, order in candidates:
        filtered = [var for var in class_vars if var in support]
        if not filtered or len(filtered) > 8:
            continue
        residual = [var for var in support if var not in set(filtered)]
        if len(residual) > 12:
            continue
        key = tuple(filtered)
        if key in seen:
            continue
        seen.add(key)
        cost, nonconstant = estimate_output_split_cost(table, output_index, filtered)
        rank = (cost, nonconstant, name, filtered, order)
        if best is None or rank[:2] < best[:2]:
            best = rank
    if best is None:
        return "bdd_whole_output", [], shannon_order, f"support={len(support)}"
    cost, nonconstant, name, class_vars, order = best
    return name, class_vars, order, f"support={len(support)}, estimated_cost={cost}, nonconstant_classes={nonconstant}"


def write_per_output_semantic_split_blif(
    path: Path,
    model: str,
    table: TruthTable,
    case: str,
    seed: int,
    node_limit: int,
) -> tuple[bool, str]:
    builder = BlifBuilder(table, model)
    decoder_cache: dict[tuple[tuple[int, ...], int], str] = {}
    residual_cache: dict[tuple[tuple[int, ...], tuple[int, ...], tuple[int, ...]], str] = {}
    residual_reused = 0
    residual_complemented = 0
    outputs: list[str] = []
    messages: list[str] = []

    def decoder(class_vars: list[int], class_value: int) -> str:
        key = (tuple(class_vars), class_value)
        if key not in decoder_cache:
            decoder_cache[key] = emit_class_decoder(builder, class_vars, class_value)
        return decoder_cache[key]

    def cached_bdd(bits: tuple[int, ...], support: list[int], order: list[int]) -> str:
        nonlocal residual_reused, residual_complemented
        key = (tuple(support), tuple(order), bits)
        if key in residual_cache:
            residual_reused += 1
            return residual_cache[key]
        inverted = tuple(1 - bit for bit in bits)
        inverted_key = (tuple(support), tuple(order), inverted)
        if inverted_key in residual_cache:
            residual_complemented += 1
            signal = builder.emit_not(residual_cache[inverted_key])
            residual_cache[key] = signal
            return signal
        signal = emit_bdd_signal(builder, bits, support, order, node_limit)
        residual_cache[key] = signal
        return signal

    for output_index, bits_array in enumerate(table.outputs):
        bits = tuple(bits_array)
        if not any(bits):
            outputs.append(builder.const0)
            messages.append(f"y{output_index}:const0")
            continue
        if all(bits):
            outputs.append(builder.const1)
            messages.append(f"y{output_index}:const1")
            continue
        split_name, class_vars, order, reason = choose_output_class_vars(case, table, output_index, seed)
        if not class_vars:
            support = output_support(table, output_index)
            compact = tuple(bits[compact_index_to_original(index, support, table.num_inputs)] for index in range(1 << len(support)))
            signal = cached_bdd(compact, support, order)
            outputs.append(signal)
            messages.append(f"y{output_index}:{split_name}({reason})")
            continue

        residual_vars = [var for var in output_support(table, output_index) if var not in set(class_vars)]
        residual_order = [var for var in order if var in residual_vars]
        residual_order.extend(var for var in residual_vars if var not in residual_order)
        terms: list[str] = []
        for class_value in range(1 << len(class_vars)):
            co_bits = class_cofactor_bits(table, output_index, class_vars, class_value, residual_vars)
            if not any(co_bits):
                continue
            dec = decoder(class_vars, class_value)
            if all(co_bits):
                terms.append(dec)
            else:
                signal = cached_bdd(co_bits, residual_vars, residual_order)
                terms.append(builder.emit_and(dec, signal))
        outputs.append(emit_or_tree(builder, terms))
        messages.append(f"y{output_index}:{split_name}({reason})")

    builder.finish(outputs, path)
    messages.append(
        f"shared_cofactors={len(residual_cache)}, reused={residual_reused}, complemented={residual_complemented}"
    )
    return True, "; ".join(messages[:9])


# ---------------------------------------------------------------------------
# XOR / AND / OR tree helpers (used by exact-match candidate generation)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Semantic-split spec generators (used by blif and candidate generation)
# ---------------------------------------------------------------------------

def semantic_split_specs(case: str, table: TruthTable, seed: int, max_splits: int) -> list[tuple[str, list[int], list[int]]]:
    active = table.active_vars
    active_set = set(active)
    specs: list[tuple[str, list[int], list[int]]] = []
    seen_keys: set[tuple[int, ...]] = set()

    def add(name: str, class_vars: list[int], order: list[int]) -> None:
        filtered_class = [var for var in class_vars if var in active_set]
        if not filtered_class:
            return
        if len(filtered_class) > 8:
            filtered_class = filtered_class[:8]
        residual = [var for var in active if var not in set(filtered_class)]
        if len(residual) > 12:
            return
        key = tuple(filtered_class)
        if key in seen_keys:
            return
        seen_keys.add(key)
        specs.append((name, filtered_class, order))

    case_num = int(case.removeprefix("ex"))
    high_influence = sorted(active, key=lambda var: table.influences[var], reverse=True)
    shannon_order = sorted(active, key=lambda var: table.shannon_scores[var], reverse=True)
    low_influence = sorted(active, key=lambda var: table.influences[var])

    if table.num_inputs == 16:
        if 200 <= case_num <= 219:
            add("bf16_exp", list(range(1, 8)), high_influence)
            add("bf16_sign_exp", list(range(0, 8)), high_influence)
            add("bf16_low_byte", list(range(8, 16)), shannon_order)
        elif 220 <= case_num <= 239:
            add("fp16_exp", list(range(1, 6)), high_influence)
            add("fp16_sign_exp", list(range(0, 6)), high_influence)
            add("fp16_high_byte", list(range(0, 8)), shannon_order)
        elif 240 <= case_num <= 254:
            add("float_convert_exp", list(range(1, 8)), high_influence)
            add("float_convert_high_byte", list(range(0, 8)), shannon_order)
            add("float_convert_low_byte", list(range(8, 16)), low_influence)
            add("float_pair_high_nibbles", [0, 1, 2, 3, 8, 9, 10, 11], shannon_order)
            add("float_pair_low_nibbles", [4, 5, 6, 7, 12, 13, 14, 15], low_influence)
        else:
            add("high_byte", list(range(0, 8)), shannon_order)
            add("low_byte", list(range(8, 16)), high_influence)
            add("paired_high_nibbles", [0, 1, 2, 3, 8, 9, 10, 11], shannon_order)
            add("paired_low_nibbles", [4, 5, 6, 7, 12, 13, 14, 15], low_influence)
    elif table.num_inputs >= 12:
        add("top_half", active[: min(8, len(active) // 2)], shannon_order)
        add("high_influence_class", high_influence[: min(6, max(1, len(active) - 8))], shannon_order)

    add("shannon_class4", shannon_order[: min(4, len(shannon_order))], shannon_order)
    add("influence_class4", high_influence[: min(4, len(high_influence))], high_influence)

    rng = random.Random(f"{seed}:{case}:semantic_split")
    shuffled = active[:]
    rng.shuffle(shuffled)
    add("seeded_class4", shuffled[: min(4, len(shuffled))], shannon_order)
    return specs[:max_splits]


def shared_bdd_order_specs(case: str, table: TruthTable, seed: int, max_orders: int) -> list[tuple[str, list[int]]]:
    active = table.active_vars
    specs: list[tuple[str, list[int]]] = []
    seen_keys: set[tuple[int, ...]] = set()

    def add(name: str, order: list[int]) -> None:
        filtered = [var for var in order if var in active]
        filtered.extend(var for var in active if var not in filtered)
        if not filtered:
            return
        key = tuple(filtered)
        if key in seen_keys:
            return
        seen_keys.add(key)
        specs.append((name, filtered))

    case_num = int(case.removeprefix("ex"))
    high_influence = sorted(active, key=lambda var: table.influences[var], reverse=True)
    shannon_order = sorted(active, key=lambda var: table.shannon_scores[var], reverse=True)
    add("shared_bdd_shannon", shannon_order)
    add("shared_bdd_influence", high_influence)
    add("shared_bdd_original", active)
    add("shared_bdd_reverse", list(reversed(active)))
    if table.num_inputs == 16:
        add("shared_bdd_adjacent_pairs", [var for pair in zip(range(0, 16, 2), range(1, 16, 2)) for var in pair])
        add("shared_bdd_byte_pairs", [var for pair in zip(range(8), range(8, 16)) for var in pair])
        add("shared_bdd_even_odd", list(range(0, 16, 2)) + list(range(1, 16, 2)))
    elif 280 <= case_num <= 299:
        add("shared_bdd_even_odd", [var for var in active if var % 2 == 0] + [var for var in active if var % 2 == 1])
    rng = random.Random(f"{seed}:{case}:shared_bdd")
    shuffled = active[:]
    rng.shuffle(shuffled)
    add("shared_bdd_seeded", shuffled)
    return specs[:max_orders]


# ---------------------------------------------------------------------------
# Arithmetic circuit detection
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Arithmetic structural BLIF generators
# ---------------------------------------------------------------------------

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


def emit_signed_product_bits_csa(
    builder: BlifBuilder,
    a_order: list[int],
    b_order: list[int],
    output_count: int,
) -> list[str]:
    width = len(a_order)
    columns: list[list[str]] = [[] for _ in range(output_count + len(a_order) + len(b_order) + 4)]
    for left, a_var in enumerate(a_order):
        for right, b_var in enumerate(b_order):
            columns[left + right].append(builder.emit_and(f"x{a_var}", f"x{b_var}"))

    def add_conditional_twos_complement(control: str, bits: list[str], shift: int) -> None:
        for bit_index in range(output_count):
            source_index = bit_index - shift
            if 0 <= source_index < len(bits):
                columns[bit_index].append(builder.emit_and(control, builder.emit_not(bits[source_index])))
            else:
                columns[bit_index].append(control)
        columns[0].append(control)

    a_bits = [f"x{var}" for var in a_order]
    b_bits = [f"x{var}" for var in b_order]
    add_conditional_twos_complement(a_bits[-1], b_bits, width)
    add_conditional_twos_complement(b_bits[-1], a_bits, width)
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


def write_signed_multiplier_csa_blif(path: Path, model: str, table: TruthTable, a_order: list[int], b_order: list[int]) -> None:
    builder = BlifBuilder(table, model)
    outputs = emit_signed_product_bits_csa(builder, a_order, b_order, table.num_outputs)
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
