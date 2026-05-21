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
from dataclasses import dataclass
from pathlib import Path

from boolean_fingerprint import append_classification_csv, fingerprint_case, format_fingerprint


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
    PostFlow("sweep_resub6_f1", "resub -K 6 -F 1; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_resub8_n2", "resub -K 8 -N 2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_resub6_n3", "resub -K 6 -N 3; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_dch_if8", "dch; if -K 8; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_dch_if12", "dch; if -K 12; strash; dc2; balance; rewrite -z; refactor -z; balance"),
    PostFlow("sweep_gia_resyn3rs", "&get; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("sweep_gia_dc2", "&get; &dc2; &put; balance; rewrite -z; refactor -z; dc2; balance"),
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


def make_initial_candidates(case: str, table: TruthTable, tmp: Path, seed: int, use_bdd: bool) -> list[InitialCandidate]:
    tmp.mkdir(parents=True, exist_ok=True)
    candidates = [InitialCandidate("abc_truth", "truth", None)]

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
) -> tuple[list[CandidateResult], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    tmp = logs / "tmp" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    initials = make_initial_candidates(case, table, tmp, seed, use_bdd)
    ga_flows = make_ga_flows(case, seed, max(4, max_candidates // 4)) if use_ga else []
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
    parser.add_argument("--analyze-case", help="print truth-table features and exit")
    parser.add_argument("--classify-case", help="print Boolean fingerprint/classification and exit")
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
    parser.add_argument("--report-stats", action="store_true", help="print report-oriented aggregate statistics")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
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
        table = read_truth(truth)
        square_order = detect_unsigned_square(table)
        multiplier_orders = detect_unsigned_multiplier(table)
        signed_multiplier_orders = detect_signed_multiplier(table)
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
            )
            all_results.extend(rows)
            summaries.append(summary)
            selected = next(row for row in rows if row.selected)
            print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    write_results_csv(args.logs / "results.csv", all_results)
    write_summary_csv(args.logs / "summary.csv", summaries)
    if args.report_stats:
        print_report_stats(all_results, summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
