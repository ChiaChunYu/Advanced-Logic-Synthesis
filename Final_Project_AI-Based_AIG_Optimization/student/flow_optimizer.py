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
    area: int | None = None
    delay: int | None = None
    adp: int | None = None
    equivalent: bool = False
    selected: bool = False
    status: str = "ERROR"
    aig: Path | None = None


POST_FLOWS = [
    PostFlow("identity", ""),
    PostFlow("area_dc2", "dc2; rewrite -z; refactor -z; balance"),
    PostFlow("delay_balance", "balance; rewrite; balance; refactor; balance"),
    PostFlow("adp_balanced", "rewrite; refactor; dc2; rewrite -z; refactor -z; balance"),
    PostFlow("drw_drf", "drw; drf; dc2; balance"),
    PostFlow("llm_mix_1", "rewrite -z; refactor -z; dc2; rewrite -z; balance"),
    PostFlow("llm_mix_2", "dc2; drw; drf; rewrite; dc2; balance"),
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
        raise RuntimeError(f"Cannot execute ABC at {abc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or f"ABC exited with {result.returncode}")
    return result.stdout


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
    active_vars: list[int] = []
    for var in range(num_inputs):
        bit_pos = num_inputs - 1 - var
        step = 1 << bit_pos
        period = step << 1
        diff = 0
        for bits in outputs:
            for base in range(0, num_minterms, period):
                for offset in range(step):
                    diff += bits[base + offset] ^ bits[base + offset + step]
        influence = diff / ((num_minterms // 2) * num_outputs)
        influences.append(influence)
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


def make_initial_candidates(case: str, table: TruthTable, tmp: Path, seed: int) -> list[InitialCandidate]:
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

    active = table.active_vars
    if len(active) <= 18:
        orders = [
            ("bdd_original", active),
            ("bdd_high_influence", sorted(active, key=lambda var: table.influences[var], reverse=True)),
            ("bdd_low_influence", sorted(active, key=lambda var: table.influences[var])),
        ]
        rng = random.Random(f"{seed}:{case}:bdd")
        random_order = active[:]
        rng.shuffle(random_order)
        orders.append(("bdd_random_seeded", random_order))
        for name, order in orders:
            try:
                blif = tmp / f"{case}_{name}.blif"
                write_bdd_blif(blif, f"{case}_{name}", table, order, node_limit=120000)
                candidates.append(InitialCandidate(name, "blif", blif))
            except RuntimeError:
                continue
    return candidates


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
) -> list[CandidateResult]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    tmp = logs / "tmp" / case
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)

    initials = make_initial_candidates(case, table, tmp, seed)
    pairs = [(initial, flow) for initial in initials for flow in POST_FLOWS][:max_candidates]
    results: list[CandidateResult] = []
    best: CandidateResult | None = None
    deadline = time.monotonic() + timeout_per_case

    for index, (initial, flow) in enumerate(pairs):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_{index:03d}_{initial.method}_{flow.name}.aig"
        result = CandidateResult(case, initial.method, flow.name, aig=candidate_aig)
        try:
            synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 120), root)
            result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 120), root)
            if result.equivalent:
                result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 120), root)
                result.status = "OK"
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
        raise RuntimeError(f"{case}: no equivalent candidate found")
    best.selected = True
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(best.aig, output / f"{case}.aig")
    return results


def write_results_csv(path: Path, rows: list[CandidateResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["case", "initial_method", "flow_name", "area", "delay", "adp", "equivalent", "selected", "status"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "case": row.case,
                    "initial_method": row.initial_method,
                    "flow_name": row.flow_name,
                    "area": row.area if row.area is not None else "",
                    "delay": row.delay if row.delay is not None else "",
                    "adp": row.adp if row.adp is not None else "",
                    "equivalent": int(row.equivalent),
                    "selected": int(row.selected),
                    "status": row.status,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hybrid AIG optimizer")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--case", help="run one benchmark, for example ex200")
    group.add_argument("--all", action="store_true", help="run ex200 through ex299")
    group.add_argument("--range", nargs=2, metavar=("START", "END"), help="run an inclusive case range")
    parser.add_argument("--abc", type=Path, default=Path("student/abc"))
    parser.add_argument("--benchmarks", type=Path, default=Path("benchmarks"))
    parser.add_argument("--output", type=Path, default=Path("output"))
    parser.add_argument("--logs", type=Path, default=Path("student/logs"))
    parser.add_argument("--max-candidates", type=int, default=24)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--timeout-per-case", type=int, default=300)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    if args.case:
        cases = [args.case]
    elif args.range:
        start = int(args.range[0].removeprefix("ex"))
        end = int(args.range[1].removeprefix("ex"))
        cases = [f"ex{i}" for i in range(start, end + 1)]
    else:
        cases = [f"ex{i}" for i in range(200, 300)]

    all_results: list[CandidateResult] = []
    for case in cases:
        print(f"[{case}] optimizing")
        rows = optimize_case(
            case,
            args.abc,
            args.benchmarks,
            args.output,
            args.logs,
            args.max_candidates,
            args.seed,
            args.timeout_per_case,
            root,
        )
        all_results.extend(rows)
        selected = next(row for row in rows if row.selected)
        print(f"[{case}] selected {selected.initial_method}/{selected.flow_name} ADP={selected.adp}")

    write_results_csv(args.logs / "results.csv", all_results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
