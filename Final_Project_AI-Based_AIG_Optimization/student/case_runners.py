"""Case-level optimization runners extracted from flow_optimizer.py."""
from __future__ import annotations

import csv
import shutil
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent))

from abc_core import (
    abc_path,
    is_equivalent,
    measure_adp,
    prepare_case_temp_dir,
    run_abc,
    run_abc_script,
    run_mockturtle_opt,
    ensure_structural_mockturtle,
    run_structural_mockturtle_opt,
)
from blif_builder import (
    TruthTable,
    read_truth,
    transduction_variable_order,
    wrap_transduction_blif_outputs,
    write_bdd_blif,
    write_per_output_semantic_split_blif,
    write_shared_multioutput_bdd_blif,
    write_class_split_blif,
    write_small_support_exact_blif,
    semantic_split_specs,
    shared_bdd_order_specs,
)
from circuit_analysis import fingerprint_case, format_fingerprint, append_classification_csv
from candidate_gen import (
    InitialCandidate,
    make_circuit_type_seed_candidates,
    make_complement_initial_candidates,
    make_exact_specialized_candidates,
    make_initial_candidates,
    pareto_frontier,
    polish_aig,
    synthesize,
    build_pareto_candidates,
    _write_pareto_candidates_from_results,
    choose_candidate_pairs,
)
from circuit_analysis import (
    ExactFunctionMatch,
    exact_matches_for_truth,
    format_exact_matches,
    truth_input_value,
    truth_output_value,
    write_exact_function_matches_csv,
)
from flow_library import (
    AREA_FIRST_FLOWS,
    AREA_FIRST_RESYNTH_FLOWS,
    CIRCUIT_TYPE_POLISH_LIBRARY,
    CIRCUIT_TYPE_SEED_FLOWS,
    DEEPSYN_STRUCTURAL_POLISH_FLOWS,
    EXACT_NPN_RESCUE_FLOWS,
    GIA_CANONICAL_FLOW,
    HYBRID_YOSYS_POLISH_FLOWS,
    MICRO_COLLAPSE_FLOWS,
    MICRO_GUIDED_FLOWS,
    MOCKTURTLE_MODES,
    MOCKTURTLE_POST_FLOW,
    MOCKTURTLE_STRUCTURAL_POLISH_FLOWS,
    PARETO_AREA_STRUCTURAL_POLISH_FLOWS,
    POST_FLOWS,
    PostFlow,
    SEMANTIC_SPLIT_FLOWS,
    SMALL_CASE_FLOWS,
    SPECIALIZED_GENERATOR_FLOWS,
    STRUCTURAL_MOCKTURTLE_MODES,
    TRANSDUCTION_REDUCTION_FLOWS,
    TTOPT_STRUCTURAL_POLISH_FLOWS,
    TYPE_GUIDED_FLOW_LIBRARY,
    TYPE_GUIDED_SHARED_FLOWS,
    _dedup_flows,
    select_circuit_type_flows,
    select_objective_guided_flows,
    select_small_case_flows,
    select_type_guided_flows,
    type_guided_family,
)
from result_logging import (
    CandidateResult,
    CaseSummary,
    ParetoCandidate,
    append_circuit_type_optimize_csv,
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
    append_semantic_split_csv,
    append_small_case_csv,
    append_specialized_generators_csv,
    append_transduction_rescue_csv,
    append_ttopt_structural_csv,
    append_type_guided_csv,
    write_pareto_candidates_csv,
)
# ---------------------------------------------------------------------------
# Constants (aliases from flow_optimizer config dataclasses)
# ---------------------------------------------------------------------------
# These must stay in sync with the values in flow_optimizer.py
REPRODUCE_DEEPSYN_MIN_ADP = 50000
REPRODUCE_DEEPSYN_MIN_AREA = 2500
REPRODUCE_PARETO_AREA_MIN_AREA = 25000
REPRODUCE_COMPACT_PARETO_MIN_AREA = 400
REPRODUCE_COMPACT_PARETO_MAX_AREA = 25000
REPRODUCE_COMPACT_PARETO_MAX_ANF_DEGREE = 4
REPRODUCE_VECTOR_MIN_ADP = 8000
REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_AREA = 25000
REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_ADP = 500000
REPRODUCE_VECTOR_PROBE_STRUCTURAL_TIMEOUT = 55
REPRODUCE_VECTOR_PROBE_SECONDS = 15
REPRODUCE_VECTOR_REFINE_PASSES = 3
REPRODUCE_VECTOR_REFINE_STRUCTURAL_TIMEOUT = 110
REPRODUCE_VECTOR_REFINE_SECONDS = 45


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
        add("xag_xor_heavy", "large AIG: XAG algebraic depth rewriting reduces delay")
        add("roundtrip_xag", "large AIG: XAG roundtrip for delay reduction")
    if current_area <= 2500 or current_adp <= 50000:
        add("cut4_aig_xag_npn", "compact small-case cut rewriting")
    target_modes = max(1, max_modes)
    if current_delay >= 18 and len(modes) < target_modes:
        add("roundtrip_mig", "delay-oriented majority roundtrip")
        add("xag_xor_heavy", "delay>=18: XAG algebraic depth rewriting")
        add("roundtrip_xag", "delay>=18: XAG roundtrip for depth reduction")
    if len(modes) < target_modes:
        add("functional_reduction", "redundancy-oriented fallback")
    if len(modes) < target_modes:
        add("roundtrip_xag", "XAG roundtrip fallback")

    return modes[:target_modes], "; ".join(reasons[:target_modes])


def run_circuit_type_optimize_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_flows: int,
    max_seeds: int,
    seed: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_circuit_type_optimize", case)

    table = read_truth(truth)
    fingerprint = fingerprint_case(truth)
    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    family, reason, polish_flows = select_circuit_type_flows(fingerprint, base_area, base_delay, base_adp, max_flows)
    seed_candidates = make_circuit_type_seed_candidates(case, table, fingerprint, family, tmp, seed, max_seeds)
    labels = "|".join(fingerprint.labels) or "general"
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    work_items: list[tuple[str, InitialCandidate | None, PostFlow]] = []
    for flow in polish_flows:
        work_items.append(("polish", None, flow))
    seed_flow_budget = max(1, max_flows // max(1, len(seed_candidates)))
    for initial in seed_candidates:
        for flow in CIRCUIT_TYPE_SEED_FLOWS[:seed_flow_budget]:
            work_items.append(("seed", initial, flow))

    def _run_one_circuit_type(
        index: int,
        kind: str,
        initial: InitialCandidate | None,
        flow: PostFlow,
    ) -> dict[str, object]:
        seed_name = initial.method if initial is not None else "current_output"
        row: dict[str, object] = {
            "case": case, "family": family, "labels": labels, "reason": reason,
            "candidate_kind": kind, "seed_name": seed_name,
            "flow_name": flow.name, "flow_commands": flow.commands,
            "equivalent": 0, "improved": 0, "selected": 0, "status": "ERROR",
        }
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            row["status"] = "TIMEOUT"
            return row
        candidate_aig = tmp / f"{case}_{index:02d}_{kind}_{seed_name}_{flow.name}.aig"
        try:
            if kind == "polish":
                polish_aig(abc, source, flow, candidate_aig, min(remaining, 120), root)
            else:
                assert initial is not None
                synthesize(abc, truth, initial, flow, candidate_aig, min(remaining, 180), root)
            equiv = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equiv)
            if equiv:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                row.update({"area": area, "delay": delay, "adp": adp, "status": "OK"})
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception as exc:
            row["status"] = f"ERROR:{type(exc).__name__}"
        return row

    workers = min(len(work_items), max(1, len(work_items)))
    with ThreadPoolExecutor(max_workers=workers) as _pool:
        futures = {
            _pool.submit(_run_one_circuit_type, i, kind, initial, flow): i
            for i, (kind, initial, flow) in enumerate(work_items)
        }
        partial_rows: list[tuple[int, dict[str, object]]] = []
        for fut in as_completed(futures):
            partial_rows.append((futures[fut], fut.result()))

    partial_rows.sort(key=lambda x: x[0])
    for idx, row in partial_rows:
        if row.get("equivalent") and row.get("adp") is not None:
            adp = row["adp"]
            improved = adp < best_adp
            row["improved"] = int(improved)
            if improved:
                candidate_aig = tmp / f"{case}_{idx:02d}_{row['candidate_kind']}_{row['seed_name']}_{row['flow_name']}.aig"
                if candidate_aig.is_file():
                    best_area, best_delay, best_adp = row["area"], row["delay"], adp
                    best_aig = candidate_aig
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_circuit_type_optimize_csv(logs / "stage_circuit_type_log.csv", rows)
    if best_adp < base_adp:
        name = selected_row.get("flow_name", "circuit_type") if selected_row else "circuit_type"
        seed_name = selected_row.get("seed_name", "unknown") if selected_row else "unknown"
        print(f"[{case}] {family} improved ADP {base_adp} -> {best_adp} via {seed_name}/{name}")
    else:
        print(f"[{case}] {family} kept current ADP {base_adp}")

    return rows, CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method=f"circuit_type/{family}",
    )


def run_semantic_split_optimize_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_splits: int,
    max_flows: int,
    seed: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_semantic_split", case)
    table = read_truth(truth)
    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = source
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    # --- Phase 1: generate all BLIF files (sequential, fast) ---
    # Each entry: (sort_key, row_template, candidate_aig_path | None, initial | None)
    _sem_work: list[tuple[tuple[int, int], dict[str, object], Path | None, InitialCandidate | None]] = []

    for order_index, (order_name, order) in enumerate(shared_bdd_order_specs(case, table, seed, max(1, min(max_splits, 6)))):
        blif = tmp / f"{case}_{order_index:02d}_{order_name}.blif"
        generated = False
        message = ""
        try:
            generated, message = write_shared_multioutput_bdd_blif(blif, f"{case}_{order_name}", table, order, node_limit=320000)
        except RuntimeError as exc:
            message = str(exc)
        if not generated:
            rows.append({"case": case, "split_name": order_name, "class_vars": "shared-output",
                         "message": message, "generated": 0, "equivalent": 0, "improved": 0, "selected": 0, "status": "SKIPPED"})
            continue
        initial = InitialCandidate(f"semantic_{order_name}", "blif", blif)
        for flow_index, flow in enumerate(SEMANTIC_SPLIT_FLOWS[:max_flows]):
            candidate_aig = tmp / f"{case}_shared_{order_index:02d}_{flow_index:02d}_{order_name}_{flow.name}.aig"
            row_tmpl: dict[str, object] = {
                "case": case, "split_name": order_name, "class_vars": "shared-output",
                "message": message, "flow_name": flow.name, "flow_commands": flow.commands,
                "generated": 1, "equivalent": 0, "improved": 0, "selected": 0, "status": "ERROR",
            }
            _sem_work.append(((order_index, flow_index), row_tmpl, candidate_aig, initial))

    hybrid_blif = tmp / f"{case}_per_output_hybrid.blif"
    hybrid_generated = False
    hybrid_message = ""
    try:
        hybrid_generated, hybrid_message = write_per_output_semantic_split_blif(
            hybrid_blif, f"{case}_per_output_hybrid", table, case, seed, node_limit=260000)
    except RuntimeError as exc:
        hybrid_message = str(exc)
    if hybrid_generated:
        h_initial = InitialCandidate("semantic_per_output_hybrid", "blif", hybrid_blif)
        for flow_index, flow in enumerate(SEMANTIC_SPLIT_FLOWS[:max_flows]):
            candidate_aig = tmp / f"{case}_hybrid_{flow_index:02d}_{flow.name}.aig"
            row_tmpl = {
                "case": case, "split_name": "per_output_hybrid", "class_vars": "per-output",
                "message": hybrid_message, "flow_name": flow.name, "flow_commands": flow.commands,
                "generated": 1, "equivalent": 0, "improved": 0, "selected": 0, "status": "ERROR",
            }
            _sem_work.append(((100, flow_index), row_tmpl, candidate_aig, h_initial))
    else:
        rows.append({"case": case, "split_name": "per_output_hybrid", "class_vars": "per-output",
                     "message": hybrid_message, "generated": 0, "equivalent": 0, "improved": 0, "selected": 0, "status": "SKIPPED"})

    for split_index, (split_name, class_vars, order) in enumerate(semantic_split_specs(case, table, seed, max_splits)):
        blif = tmp / f"{case}_{split_index:02d}_{split_name}.blif"
        generated = False
        message = ""
        try:
            generated, message = write_class_split_blif(blif, f"{case}_{split_name}", table, class_vars, order, node_limit=220000, max_classes=256)
        except RuntimeError as exc:
            message = str(exc)
        if not generated:
            rows.append({"case": case, "split_name": split_name, "class_vars": ",".join(f"x{var}" for var in class_vars),
                         "message": message, "generated": 0, "equivalent": 0, "improved": 0, "selected": 0, "status": "SKIPPED"})
            continue
        c_initial = InitialCandidate(f"semantic_{split_name}", "blif", blif)
        for flow_index, flow in enumerate(SEMANTIC_SPLIT_FLOWS[:max_flows]):
            candidate_aig = tmp / f"{case}_{split_index:02d}_{flow_index:02d}_{split_name}_{flow.name}.aig"
            row_tmpl = {
                "case": case, "split_name": split_name, "class_vars": ",".join(f"x{var}" for var in class_vars),
                "message": message, "flow_name": flow.name, "flow_commands": flow.commands,
                "generated": 1, "equivalent": 0, "improved": 0, "selected": 0, "status": "ERROR",
            }
            _sem_work.append(((200 + split_index, flow_index), row_tmpl, candidate_aig, c_initial))

    # --- Phase 2: run all (synthesize + cec + measure) in parallel ---
    def _run_one_semantic(
        sort_key: tuple[int, int],
        row_tmpl: dict[str, object],
        candidate_aig: Path,
        initial: InitialCandidate,
    ) -> tuple[tuple[int, int], dict[str, object], Path]:
        row = dict(row_tmpl)
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            row["status"] = "TIMEOUT"
            return sort_key, row, candidate_aig
        flow_cmds = row["flow_commands"]
        flow_name = row["flow_name"]
        try:
            synthesize(abc, truth, initial, PostFlow(str(flow_name), str(flow_cmds)), candidate_aig, min(remaining, 180), root)
            equiv = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
            row["equivalent"] = int(equiv)
            if equiv:
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                row.update({"area": area, "delay": delay, "adp": adp, "status": "OK"})
            else:
                row["status"] = "NOT_EQUIV"
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
        except Exception as exc:
            row["status"] = f"ERROR:{type(exc).__name__}"
        return sort_key, row, candidate_aig

    with ThreadPoolExecutor(max_workers=len(_sem_work) or 1) as _pool:
        _sem_futures = {
            _pool.submit(_run_one_semantic, sk, rt, caig, init): sk
            for sk, rt, caig, init in _sem_work
        }
        _sem_results: list[tuple[tuple[int, int], dict[str, object], Path]] = []
        for fut in as_completed(_sem_futures):
            _sem_results.append(fut.result())

    _sem_results.sort(key=lambda x: x[0])
    for _sk, row, candidate_aig in _sem_results:
        if row.get("equivalent") and row.get("adp") is not None:
            adp = row["adp"]
            improved = adp < best_adp
            row["improved"] = int(improved)
            if improved and candidate_aig.is_file():
                best_area, best_delay, best_adp = row["area"], row["delay"], adp
                best_aig = candidate_aig
        rows.append(row)

    selected_row: dict[str, object] | None = None
    if best_aig is not None and best_aig != source and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        for row in rows:
            if row.get("adp") == best_adp:
                row["selected"] = 1
                selected_row = row
                break

    append_semantic_split_csv(logs / "stage_semantic_split_log.csv", rows)
    if best_adp < base_adp:
        split = selected_row.get("split_name", "semantic_split") if selected_row else "semantic_split"
        flow_name = selected_row.get("flow_name", "semantic") if selected_row else "semantic"
        print(f"[{case}] semantic split improved ADP {base_adp} -> {best_adp} via {split}/{flow_name}")
    else:
        print(f"[{case}] semantic split kept current ADP {base_adp}")

    return rows, CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="semantic_split",
    )


def select_micro_guided_flows(area: int, adp: int, max_flows: int) -> list[PostFlow]:
    flows = list(MICRO_GUIDED_FLOWS)
    if area <= 1000 or adp <= 10000:
        flows.extend(MICRO_COLLAPSE_FLOWS)
    return flows[:max_flows]


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

    tmp = prepare_case_temp_dir(logs, "tmp_exact_npn", case)

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
        append_exact_npn_rescue_csv(logs / "stage_exact_npn_log.csv", rows)
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

    append_exact_npn_rescue_csv(logs / "stage_exact_npn_log.csv", rows)
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

    tmp = prepare_case_temp_dir(logs, "tmp_transduction", case)

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

    append_transduction_rescue_csv(logs / "stage_transduction_log.csv", rows)
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

    tmp = prepare_case_temp_dir(logs, "tmp_complement", case)

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

    append_complement_candidates_csv(logs / "stage_complement_log.csv", rows)
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

    tmp = prepare_case_temp_dir(logs, "tmp_specialized_generators", case)

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

    append_specialized_generators_csv(logs / "stage_specialized_log.csv", rows)
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

    tmp = prepare_case_temp_dir(logs, "tmp_ttopt_structural", case)

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

    append_ttopt_structural_csv(logs / "stage_ttopt_log.csv", rows)
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


def should_run_deepsyn_structural(
    table: TruthTable,
    area: int,
    adp: int,
    min_adp: int = REPRODUCE_DEEPSYN_MIN_ADP,
    min_area: int = REPRODUCE_DEEPSYN_MIN_AREA,
) -> bool:
    """Select costly multi-output functions for bounded structural rebuilding."""
    dropped_output_practical_shape = table.num_inputs == 16 and table.num_outputs == 8
    return table.num_outputs > 1 and (
        dropped_output_practical_shape or adp >= min_adp or area >= min_area
    )


def run_deepsyn_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    seed: int,
    iterations: int,
    search_seconds: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")

    tmp = prepare_case_temp_dir(logs, "tmp_deepsyn_structural", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case
    actual_iterations = max(1, iterations)
    actual_seconds = max(1, min(search_seconds, max(1, timeout_per_case - 10)))
    actual_seed = seed % 101
    variants = [("standard", "")]
    if table.num_inputs == 16 and table.num_outputs == 8:
        variants.append(("two_input_lut", "-t"))

    for variant, option in variants:
        raw_aig = tmp / f"{case}_deepsyn_{variant}_i{actual_iterations}_t{actual_seconds}_s{actual_seed}.aig"
        option_text = f" {option}" if option else ""
        common_commands = (
            f"&deepsyn -I {actual_iterations} -T {actual_seconds} -S {actual_seed} -o{option_text}; "
            "&put; strash; dc2; balance"
        )
        generation_error = ""
        try:
            remaining = max(1, int(deadline - time.monotonic()))
            run_abc(
                abc,
                f"read {abc_path(source, root)}; &get; {common_commands}; "
                f"write_aiger -s {abc_path(raw_aig, root)}",
                min(remaining, actual_seconds * actual_iterations + 30),
                root,
            )
        except subprocess.TimeoutExpired:
            generation_error = "deepsyn timeout"
        except Exception as exc:
            generation_error = str(exc)[:500]

        for index, flow in enumerate(DEEPSYN_STRUCTURAL_POLISH_FLOWS):
            row: dict[str, object] = {
                "case": case,
                "variant": variant,
                "seed": actual_seed,
                "iterations": actual_iterations,
                "search_seconds": actual_seconds,
                "flow_name": flow.name,
                "flow_commands": f"{common_commands}; {flow.commands}".strip("; "),
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": generation_error,
            }
            if generation_error or not raw_aig.is_file():
                rows.append(row)
                continue
            candidate_aig = raw_aig
            if flow.commands:
                candidate_aig = tmp / f"{case}_{variant}_{index:02d}_{flow.name}.aig"
                try:
                    remaining = max(1, int(deadline - time.monotonic()))
                    polish_aig(abc, raw_aig, flow, candidate_aig, min(remaining, 90), root)
                except subprocess.TimeoutExpired:
                    row["error"] = "post-polish timeout"
                    rows.append(row)
                    continue
                except Exception as exc:
                    row["error"] = str(exc)[:500]
                    rows.append(row)
                    continue
            row["generated"] = 1
            try:
                remaining = max(1, int(deadline - time.monotonic()))
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if not equivalent:
                    row["error"] = "not equivalent"
                    rows.append(row)
                    continue
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            except subprocess.TimeoutExpired:
                row["error"] = "verification timeout"
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

    append_deepsyn_structural_csv(logs / "stage_deepsyn_log.csv", rows)
    if best_adp < base_adp:
        print(f"[{case}] deepsyn structural improved ADP {base_adp} -> {best_adp}")
    else:
        print(f"[{case}] deepsyn structural kept current ADP {base_adp}")

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
            f"deepsyn_structural/{selected_row.get('variant')}/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "deepsyn_structural/no_improvement"
        ),
    )
    return rows, summary


def should_run_pareto_area_structural(
    table: TruthTable,
    area: int,
    min_area: int = REPRODUCE_PARETO_AREA_MIN_AREA,
) -> bool:
    """Select large equal-width truth functions whose remaining gap is area dominated."""
    return (
        table.num_inputs == table.num_outputs
        and table.num_outputs > 1
        and area >= min_area
    )


def is_low_degree_vector_signature(table: TruthTable, max_degree: int) -> bool:
    """Return true only when every output has algebraic degree at most max_degree."""
    for bits in table.outputs:
        coefficients = list(bits)
        step = 1
        while step < len(coefficients):
            for base in range(0, len(coefficients), 2 * step):
                for offset in range(step):
                    coefficients[base + step + offset] ^= coefficients[base + offset]
            step *= 2
        if any(value and index.bit_count() > max_degree for index, value in enumerate(coefficients)):
            return False
    return True


def should_run_compact_pareto_structural(table: TruthTable, area: int) -> bool:
    """Select compact equal-width low-degree vector functions missed by the large-area gate."""
    return (
        table.num_inputs == table.num_outputs
        and table.num_outputs >= 8
        and REPRODUCE_COMPACT_PARETO_MIN_AREA <= area < REPRODUCE_COMPACT_PARETO_MAX_AREA
        and is_low_degree_vector_signature(table, REPRODUCE_COMPACT_PARETO_MAX_ANF_DEGREE)
    )


def should_probe_compact_vector_structural(table: TruthTable, area: int, adp: int) -> bool:
    """Provide fair, bounded structural coverage to compact vector functions."""
    return (
        table.num_inputs == table.num_outputs
        and table.num_outputs >= 8
        and REPRODUCE_COMPACT_PARETO_MIN_AREA <= area < REPRODUCE_COMPACT_PARETO_MAX_AREA
        and adp >= REPRODUCE_VECTOR_MIN_ADP
    )


def should_run_long_large_structural(
    table: TruthTable,
    area: int,
    adp: int,
    min_area: int = REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_AREA,
    min_adp: int = REPRODUCE_LONG_LARGE_STRUCTURAL_MIN_ADP,
) -> bool:
    """Select expensive equal-width vector cases for alternate-seed reconstruction."""
    return (
        table.num_inputs == table.num_outputs
        and table.num_outputs >= 8
        and area >= min_area
        and adp >= min_adp
    )


def run_pareto_area_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    seed: int,
    search_seconds: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")

    tmp = prepare_case_temp_dir(logs, "tmp_pareto_area_structural", case)
    pareto_dir = tmp / "pareto"
    pareto_dir.mkdir(parents=True, exist_ok=True)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case
    actual_seconds = max(1, min(search_seconds, max(1, timeout_per_case - 20)))
    actual_seed = seed % 101
    raw_aig = tmp / f"{case}_pareto_area_t{actual_seconds}_s{actual_seed}.aig"
    generator_commands = (
        f"&my_deepsyn -I 1 -J 1000 -T {actual_seconds} -S {actual_seed} "
        f"-O {abc_path(pareto_dir, root)} -C area -t; &put"
    )
    generation_error = ""
    try:
        run_abc(
            abc,
            f"read {abc_path(source, root)}; &get; {generator_commands}; "
            f"write_aiger -s {abc_path(raw_aig, root)}",
            min(timeout_per_case, actual_seconds + 45),
            root,
        )
    except subprocess.TimeoutExpired:
        generation_error = "area-Pareto search timeout"
    except Exception as exc:
        generation_error = str(exc)[:500]

    structural_seeds: list[tuple[str, Path]] = []
    if raw_aig.is_file():
        structural_seeds.append(("search_final", raw_aig))
    for frontier_aig in sorted(pareto_dir.glob("*.aig")):
        if raw_aig.is_file() and frontier_aig.resolve() == raw_aig.resolve():
            continue
        structural_seeds.append((frontier_aig.stem, frontier_aig))

    if not structural_seeds:
        rows.append(
            {
                "case": case,
                "seed": actual_seed,
                "search_seconds": actual_seconds,
                "flow_name": "none",
                "flow_commands": generator_commands,
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": generation_error or "no Pareto candidate generated",
            }
        )

    for seed_index, (frontier_name, frontier_aig) in enumerate(structural_seeds):
        for flow_index, flow in enumerate(PARETO_AREA_STRUCTURAL_POLISH_FLOWS):
            qualified_flow = f"{frontier_name}__{flow.name}"
            row: dict[str, object] = {
                "case": case,
                "seed": actual_seed,
                "search_seconds": actual_seconds,
                "flow_name": qualified_flow,
                "flow_commands": f"{generator_commands}; frontier={frontier_name}; {flow.commands}".strip("; "),
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": generation_error,
            }
            candidate_aig = frontier_aig
            if flow.commands:
                candidate_aig = tmp / f"{case}_{seed_index:02d}_{flow_index:02d}_{qualified_flow}.aig"
                try:
                    remaining = max(1, int(deadline - time.monotonic()))
                    polish_aig(abc, frontier_aig, flow, candidate_aig, min(remaining, 90), root)
                except subprocess.TimeoutExpired:
                    row["error"] = "post-polish timeout"
                    rows.append(row)
                    continue
                except Exception as exc:
                    row["error"] = str(exc)[:500]
                    rows.append(row)
                    continue
            row["generated"] = 1
            try:
                remaining = max(1, int(deadline - time.monotonic()))
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if not equivalent:
                    row["error"] = "not equivalent"
                    rows.append(row)
                    continue
                area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                improved = adp < best_adp
                row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "error": ""})
                if improved:
                    best_area, best_delay, best_adp = area, delay, adp
                    best_aig = candidate_aig
            except subprocess.TimeoutExpired:
                row["error"] = "verification timeout"
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

    append_pareto_area_structural_csv(logs / "stage_pareto_area_log.csv", rows)
    if best_adp < base_adp:
        print(f"[{case}] area-Pareto structural improved ADP {base_adp} -> {best_adp}")
    else:
        print(f"[{case}] area-Pareto structural kept current ADP {base_adp}")

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
            f"pareto_area_structural/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "pareto_area_structural/no_improvement"
        ),
    )
    return rows, summary


def run_long_large_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    seed: int,
    search_seconds: int,
    ttopt_rounds: int,
) -> CaseSummary:
    """Try a long Pareto search from a truth-table-derived shared-topology seed."""
    truth = benchmarks / f"{case}.truth"
    table = read_truth(truth)
    source = output / f"{case}.aig"
    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    tmp = prepare_case_temp_dir(logs, "tmp_long_large_structural", case)
    seed_output = tmp / "seed_output"
    seed_output.mkdir(parents=True, exist_ok=True)
    seed_aig = seed_output / f"{case}.aig"
    row: dict[str, object] = {
        "case": case,
        "seed": seed % 101,
        "ttopt_rounds": ttopt_rounds,
        "search_seconds": search_seconds,
        "initial_method": "ttopt_shared_seed_then_area_pareto",
        "generated": 0,
        "equivalent": 0,
        "baseline_area": base_area,
        "baseline_delay": base_delay,
        "baseline_adp": base_adp,
        "improved": 0,
        "selected": 0,
        "error": "",
    }

    seed_command = (
        f"read_truth -xf {abc_path(truth, root)}; st; &get; "
        f"&ttopt -I {table.num_inputs} -O {table.num_outputs} -X {ttopt_rounds}; &put; "
        f"strash; dc2; balance; write_aiger -s {abc_path(seed_aig, root)}"
    )
    try:
        run_abc(abc, seed_command, min(timeout_per_case, max(180, search_seconds // 2)), root)
        row["generated"] = 1
        if not is_equivalent(abc, truth, seed_aig, min(timeout_per_case, 120), root):
            row["error"] = "ttopt seed is not equivalent"
            append_long_large_structural_csv(logs / "stage_long_large_log.csv", [row])
            return CaseSummary(case, base_area, base_delay, base_adp, base_area, base_delay, base_adp, 1.0, "long_large_structural/invalid_seed")
    except subprocess.TimeoutExpired:
        row["error"] = "ttopt seed timeout"
        append_long_large_structural_csv(logs / "stage_long_large_log.csv", [row])
        return CaseSummary(case, base_area, base_delay, base_adp, base_area, base_delay, base_adp, 1.0, "long_large_structural/timeout")
    except Exception as exc:
        row["error"] = str(exc)[:500]
        append_long_large_structural_csv(logs / "stage_long_large_log.csv", [row])
        return CaseSummary(case, base_area, base_delay, base_adp, base_area, base_delay, base_adp, 1.0, "long_large_structural/error")

    try:
        run_pareto_area_structural_case(
            case,
            abc,
            benchmarks,
            seed_output,
            tmp / "nested_area_pareto",
            max(timeout_per_case, search_seconds + 90),
            root,
            seed,
            search_seconds,
        )
        area, delay, adp = measure_adp(abc, seed_aig, 120, root)
        equivalent = is_equivalent(abc, truth, seed_aig, 120, root)
        row.update({"equivalent": int(equivalent), "area": area, "delay": delay, "adp": adp})
        if equivalent and adp < base_adp:
            shutil.copyfile(seed_aig, source)
            row.update({"improved": 1, "selected": 1})
            print(f"[{case}] long large structural improved ADP {base_adp} -> {adp}")
            summary = CaseSummary(
                case, base_area, base_delay, base_adp, area, delay, adp,
                base_adp / adp, "long_large_structural/ttopt_seed_area_pareto",
            )
        else:
            print(f"[{case}] long large structural kept current ADP {base_adp}")
            summary = CaseSummary(
                case, base_area, base_delay, base_adp, base_area, base_delay, base_adp,
                1.0, "long_large_structural/no_improvement",
            )
    except subprocess.TimeoutExpired:
        row["error"] = "area-Pareto search timeout"
        summary = CaseSummary(case, base_area, base_delay, base_adp, base_area, base_delay, base_adp, 1.0, "long_large_structural/timeout")
    except Exception as exc:
        row["error"] = str(exc)[:500]
        summary = CaseSummary(case, base_area, base_delay, base_adp, base_area, base_delay, base_adp, 1.0, "long_large_structural/error")
    append_long_large_structural_csv(logs / "stage_long_large_log.csv", [row])
    return summary


def run_adaptive_compact_vector_pareto(
    cases: list[str],
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    root: Path,
    seed: int,
    force_cases: bool = False,
) -> list[CaseSummary]:
    """Probe compact vector functions cheaply and spend full budget only on winners."""
    probe_cases: list[str] = []
    for case in cases:
        table = read_truth(benchmarks / f"{case}.truth")
        area, _delay, adp = measure_adp(abc, output / f"{case}.aig", 120, root)
        if force_cases or should_probe_compact_vector_structural(table, area, adp):
            probe_cases.append(case)

    active_cases: list[str] = []
    summaries: list[CaseSummary] = []
    print(f"[vector-pareto] probing {len(probe_cases)} compact vector cases")
    for case in probe_cases:
        print(f"[{case}] compact vector Pareto probe")
        _rows, summary = run_pareto_area_structural_case(
            case,
            abc,
            benchmarks,
            output,
            logs,
            REPRODUCE_VECTOR_PROBE_STRUCTURAL_TIMEOUT,
            root,
            seed,
            REPRODUCE_VECTOR_PROBE_SECONDS,
        )
        summaries.append(summary)
        if summary.best_adp < summary.baseline_adp:
            active_cases.append(case)

    print(f"[vector-pareto] expanding budget for {len(active_cases)} verified improvers")
    for pass_index in range(REPRODUCE_VECTOR_REFINE_PASSES):
        next_active: list[str] = []
        print(f"[vector-pareto] refine pass {pass_index + 1}/{REPRODUCE_VECTOR_REFINE_PASSES}")
        for case in active_cases:
            print(f"[{case}] compact vector Pareto refine")
            _rows, summary = run_pareto_area_structural_case(
                case,
                abc,
                benchmarks,
                output,
                logs,
                REPRODUCE_VECTOR_REFINE_STRUCTURAL_TIMEOUT,
                root,
                seed,
                REPRODUCE_VECTOR_REFINE_SECONDS,
            )
            summaries.append(summary)
            if summary.best_adp < summary.baseline_adp:
                next_active.append(case)
        active_cases = next_active
        if not active_cases:
            break
    return summaries


def resolve_yosys_binary(yosys_bin: Path) -> tuple[Path | None, str]:
    if yosys_bin.is_file():
        return yosys_bin, ""
    resolved = shutil.which(str(yosys_bin))
    if resolved:
        return Path(resolved), ""
    return None, f"Yosys executable not found: {yosys_bin}"


def run_yosys_structural_opt(
    yosys_bin: Path,
    abc: Path,
    source_aig: Path,
    out_aig: Path,
    timeout: int,
    root: Path,
) -> None:
    """Remap an AIG through Yosys while preserving the original CI order.

    Yosys sorts AIGER symbol-named inputs when round-tripping these benchmarks.
    Stripping symbols with ABC first preserves the positional truth-table
    interface that the evaluator checks.
    """
    out_aig.parent.mkdir(parents=True, exist_ok=True)
    symbol_free_aig = out_aig.with_suffix(".nosym_input.aig")
    run_abc(
        abc,
        f"read {abc_path(source_aig, root)}; write_aiger {abc_path(symbol_free_aig, root)}",
        min(timeout, 120),
        root,
    )
    script = (
        f"read_aiger {abc_path(symbol_free_aig, root)}; "
        "techmap; opt; abc -g aig; aigmap; opt_clean; "
        f"write_aiger {abc_path(out_aig, root)}"
    )
    result = subprocess.run(
        [str(yosys_bin), "-q", "-p", script],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Yosys structural remap failed").strip())


def run_hybrid_structural_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    yosys_bin: Path,
    mockturtle_bin: Path | None,
    mockturtle_workers: int,
    mockturtle_max_modes: int,
    exact_max_inputs: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    """Try Yosys remapping, then parallel mockturtle resynthesis from a new winner."""
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_hybrid_structural", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    best_aig: Path | None = None
    selected_row: dict[str, object] | None = None
    rows: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout_per_case

    raw_yosys = tmp / f"{case}_yosys_aig_raw.aig"
    try:
        run_yosys_structural_opt(
            yosys_bin,
            abc,
            source,
            raw_yosys,
            max(1, min(timeout_per_case, int(deadline - time.monotonic()))),
            root,
        )
        for flow in HYBRID_YOSYS_POLISH_FLOWS:
            remaining = max(1, int(deadline - time.monotonic()))
            candidate_aig = raw_yosys if not flow.commands else tmp / f"{case}_{flow.name}.aig"
            row: dict[str, object] = {
                "case": case,
                "chain": "yosys",
                "mode": "aig_remap",
                "flow_name": flow.name,
                "flow_commands": flow.commands,
                "generated": 1,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": "",
            }
            try:
                if flow.commands:
                    polish_aig(abc, raw_yosys, flow, candidate_aig, min(remaining, 90), root)
                equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                row["equivalent"] = int(equivalent)
                if not equivalent:
                    row["error"] = "not equivalent"
                else:
                    area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                    improved = adp < best_adp
                    row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved)})
                    if improved:
                        best_area, best_delay, best_adp = area, delay, adp
                        best_aig = candidate_aig
                        selected_row = row
            except subprocess.TimeoutExpired:
                row["error"] = "Yosys candidate check timeout"
            except Exception as exc:
                row["error"] = str(exc)[:500]
            rows.append(row)
    except subprocess.TimeoutExpired:
        rows.append(
            {
                "case": case,
                "chain": "yosys",
                "mode": "aig_remap",
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": "Yosys generation timeout",
            }
        )
    except Exception as exc:
        rows.append(
            {
                "case": case,
                "chain": "yosys",
                "mode": "aig_remap",
                "generated": 0,
                "equivalent": 0,
                "improved": 0,
                "selected": 0,
                "error": str(exc)[:500],
            }
        )

    # Only spend mockturtle effort when Yosys exposes a genuinely better seed.
    if best_aig is not None and best_adp < base_adp and mockturtle_bin is not None:
        fingerprint = fingerprint_case(truth)
        exact_types = exact_type_hints_for_mockturtle(
            exact_matches_for_truth(truth, max_expensive_inputs=exact_max_inputs)
        )
        modes, fingerprint_reason = select_structural_mockturtle_modes(
            fingerprint, best_area, best_delay, best_adp, exact_types, mockturtle_max_modes
        )

        def generate_mode(mode: str) -> tuple[str, Path, str]:
            raw_aig = tmp / f"{case}_yosys_then_{mode}_raw.aig"
            try:
                remaining = max(1, int(deadline - time.monotonic()))
                run_structural_mockturtle_opt(
                    mockturtle_bin, truth, best_aig, raw_aig, mode, min(remaining, 180), root
                )
                return mode, raw_aig, ""
            except Exception as exc:
                return mode, raw_aig, str(exc)[:500]

        generated: dict[str, tuple[Path, str]] = {}
        workers = max(1, min(mockturtle_workers, len(modes)))
        if workers > 1 and len(modes) > 1:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(generate_mode, mode): mode for mode in modes}
                for future in as_completed(futures):
                    mode, raw_aig, error = future.result()
                    generated[mode] = (raw_aig, error)
        else:
            for mode in modes:
                _mode, raw_aig, error = generate_mode(mode)
                generated[_mode] = (raw_aig, error)

        for mode in modes:
            raw_aig, error = generated[mode]
            if error:
                rows.append(
                    {
                        "case": case,
                        "chain": "yosys_then_mockturtle",
                        "mode": mode,
                        "flow_name": "",
                        "flow_commands": fingerprint_reason,
                        "generated": 0,
                        "equivalent": 0,
                        "improved": 0,
                        "selected": 0,
                        "error": error,
                    }
                )
                continue
            for flow in MOCKTURTLE_STRUCTURAL_POLISH_FLOWS:
                candidate_aig = tmp / f"{case}_yosys_then_{mode}_{flow.name}.aig"
                row = {
                    "case": case,
                    "chain": "yosys_then_mockturtle",
                    "mode": mode,
                    "flow_name": flow.name,
                    "flow_commands": flow.commands,
                    "generated": 1,
                    "equivalent": 0,
                    "improved": 0,
                    "selected": 0,
                    "error": "",
                }
                try:
                    remaining = max(1, int(deadline - time.monotonic()))
                    polish_aig(abc, raw_aig, flow, candidate_aig, min(remaining, 90), root)
                    equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 90), root)
                    row["equivalent"] = int(equivalent)
                    if not equivalent:
                        row["error"] = "not equivalent"
                    else:
                        area, delay, adp = measure_adp(abc, candidate_aig, min(remaining, 90), root)
                        improved = adp < best_adp
                        row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved)})
                        if improved:
                            best_area, best_delay, best_adp = area, delay, adp
                            best_aig = candidate_aig
                            selected_row = row
                except Exception as exc:
                    row["error"] = str(exc)[:500]
                rows.append(row)

    if best_aig is not None and best_adp < base_adp:
        shutil.copyfile(best_aig, source)
        if selected_row is not None:
            selected_row["selected"] = 1
        print(f"[{case}] hybrid structural improved ADP {base_adp} -> {best_adp} ({best_area}/{best_delay})")
    else:
        print(f"[{case}] hybrid structural kept current ADP {base_adp}")

    append_hybrid_structural_csv(logs / "stage_hybrid_log.csv", rows)
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
            f"{selected_row.get('chain')}/{selected_row.get('mode')}/{selected_row.get('flow_name')}"
            if selected_row is not None
            else "hybrid_structural/no_improvement"
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

    tmp = prepare_case_temp_dir(logs, "tmp_mockturtle_structural", case)

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

    append_mockturtle_candidates_csv(logs / "stage_mockturtle_log.csv", rows)
    append_mockturtle_structural_summary_csv(
        logs / "stage_mockturtle_summary_log.csv",
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
    tmp = prepare_case_temp_dir(logs, "tmp_type_guided", case)

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

    append_type_guided_csv(logs / "stage_type_guided_log.csv", rows)
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
    tmp = prepare_case_temp_dir(logs, "tmp_objective_guided", case)

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

    append_objective_guided_csv(logs / "stage_objective_log.csv", rows)
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
    tmp = prepare_case_temp_dir(logs, "tmp_micro_guided", case)

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

    append_micro_guided_csv(logs / "stage_micro_guided_log.csv", rows)
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


def run_gia_canonical_convergence_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_pass: int,
    root: Path,
    max_passes: int,
) -> tuple[list[dict[str, object]], CaseSummary]:
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    if not source.is_file():
        raise RuntimeError(f"missing existing AIG: {source}")
    tmp = prepare_case_temp_dir(logs, "tmp_gia_canonical", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 120, root)
    best_area, best_delay, best_adp = base_area, base_delay, base_adp
    rows: list[dict[str, object]] = []

    for pass_index in range(max_passes):
        candidate_aig = tmp / f"{case}_pass_{pass_index + 1:02d}.aig"
        row: dict[str, object] = {
            "case": case,
            "pass_index": pass_index + 1,
            "flow_commands": GIA_CANONICAL_FLOW.commands,
            "equivalent": 0,
            "improved": 0,
            "selected": 0,
            "status": "ERROR",
        }
        try:
            polish_aig(abc, source, GIA_CANONICAL_FLOW, candidate_aig, timeout_per_pass, root)
            equivalent = is_equivalent(abc, truth, candidate_aig, timeout_per_pass, root)
            row["equivalent"] = int(equivalent)
            if not equivalent:
                row["status"] = "NOT_EQUIV"
                rows.append(row)
                break
            area, delay, adp = measure_adp(abc, candidate_aig, timeout_per_pass, root)
            improved = adp < best_adp
            row.update({"area": area, "delay": delay, "adp": adp, "improved": int(improved), "status": "OK"})
            if not improved:
                rows.append(row)
                break
            shutil.copyfile(candidate_aig, source)
            best_area, best_delay, best_adp = area, delay, adp
            row["selected"] = 1
        except subprocess.TimeoutExpired:
            row["status"] = "TIMEOUT"
            rows.append(row)
            break
        except Exception:
            row["status"] = "ERROR"
            rows.append(row)
            break
        rows.append(row)

    append_gia_canonical_csv(logs / "stage_gia_log.csv", rows)
    if best_adp < base_adp:
        print(f"[{case}] GIA canonical improved ADP {base_adp} -> {best_adp}")
    else:
        print(f"[{case}] GIA canonical kept current ADP {base_adp}")

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best_area,
        best_delay=best_delay,
        best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 0.0,
        selected_method="gia_canonical_fixed_point",
    )
    return rows, summary


def run_area_first_refine_case(
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
    tmp = prepare_case_temp_dir(logs, "tmp_area_first", case)

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

    # Phase 1: apply area-first flows to existing AIG
    for index, flow in enumerate(AREA_FIRST_FLOWS):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_{index:02d}_{flow.name}.aig"
        result = CandidateResult(
            case=case,
            initial_method="existing_output_area_first",
            flow_name=flow.name,
            flow_commands=flow.commands,
            aig=candidate_aig,
        )
        try:
            polish_aig(abc, source, flow, candidate_aig, min(remaining, 60), root)
            result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 60), root)
            if result.equivalent:
                result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 30), root)
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

    # Phase 2: re-synthesize from truth table with area-first flows
    for index, flow in enumerate(AREA_FIRST_RESYNTH_FLOWS):
        remaining = max(1, int(deadline - time.monotonic()))
        if remaining <= 1:
            break
        candidate_aig = tmp / f"{case}_resynth_{index:02d}_{flow.name}.aig"
        result = CandidateResult(
            case=case,
            initial_method="resynth_area_first",
            flow_name=flow.name,
            flow_commands=flow.commands,
            aig=candidate_aig,
        )
        try:
            cmd = f"read_truth -xf {abc_path(truth, root)}; st; {flow.commands}; write_aiger -s {abc_path(candidate_aig, root)}"
            run_abc(abc, cmd, min(remaining, 60), root)
            if candidate_aig.exists():
                result.equivalent = is_equivalent(abc, truth, candidate_aig, min(remaining, 60), root)
                if result.equivalent:
                    result.area, result.delay, result.adp = measure_adp(abc, candidate_aig, min(remaining, 30), root)
                    result.status = "OK"
                    if result.adp is not None and result.adp < (best.adp or 10**30):
                        best = result
                else:
                    result.status = "NOT_EQUIV"
            else:
                result.status = "ERROR"
        except subprocess.TimeoutExpired:
            result.status = "TIMEOUT"
        except Exception:
            result.status = "ERROR"
        results.append(result)

    # Write best result if improved
    if best.adp is not None and best.adp < base_adp:
        shutil.copyfile(best.aig, source)
        best.selected = True
        print(f"[{case}] area_first improved ADP {base_adp} -> {best.adp} via {best.flow_name}")
    else:
        results[0].selected = True

    summary = CaseSummary(
        case=case,
        baseline_area=base_area,
        baseline_delay=base_delay,
        baseline_adp=base_adp,
        best_area=best.area or base_area,
        best_delay=best.delay or base_delay,
        best_adp=best.adp or base_adp,
        improvement_ratio=base_adp / (best.adp or base_adp),
        selected_method=f"area_first/{best.flow_name}",
    )
    return results, summary


# ---------------------------------------------------------------------------
# Core convergence loop — replaces the multi-stage polish/sweep/micro/gia pile
# ---------------------------------------------------------------------------

# The four flows that account for the vast majority of improvements across all
# cases, ranked by how many times they produced a selected improvement in logs:
#   1. resub -K 4 loop  (481 improvements)
#   2. dch; if -K 3     ( 99 improvements)
#   3. &dc2 + compress  ( 22 improvements)
#   4. orchestrate      ( 28 improvements)
_CORE_FLOWS = [
    PostFlow("core_resub4",       "resub -K 4; balance; rewrite -z; refactor -z; balance"),
    PostFlow("core_if3",          "dch; if -K 3; strash; dc2; balance"),
    PostFlow("core_gia_dc2",      "&get; &dc2; &compress3rs; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("core_orchestrate",  "orchestrate -K 12 -N 2 -F 1; balance; rewrite -z; refactor -z; dc2; balance"),
]


def run_convergence_loop_case(
    case: str,
    abc: Path,
    benchmarks: Path,
    output: Path,
    logs: Path,
    timeout_per_case: int,
    root: Path,
    max_passes: int = 40,
) -> CaseSummary:
    """Repeatedly apply the 4 core flows until no flow improves ADP.

    Each pass tries all four flows on the current best AIG.  If at least one
    improves ADP the loop continues; otherwise it stops.  This naturally
    replaces the fixed-pass-count approach used by the old polish/sweep/micro/
    area-first/gia stages while using far fewer ABC commands.
    """
    truth = benchmarks / f"{case}.truth"
    source = output / f"{case}.aig"
    tmp = prepare_case_temp_dir(logs, "tmp_convergence_loop", case)

    base_area, base_delay, base_adp = measure_adp(abc, source, 60, root)
    best_adp = base_adp
    deadline = time.monotonic() + timeout_per_case

    for pass_idx in range(max_passes):
        improved_this_pass = False
        for flow in _CORE_FLOWS:
            remaining = max(1, int(deadline - time.monotonic()))
            if remaining <= 2:
                break
            candidate = tmp / f"{case}_p{pass_idx:02d}_{flow.name}.aig"
            try:
                polish_aig(abc, source, flow, candidate, min(remaining, 60), root)
                if not candidate.is_file():
                    continue
                equiv = is_equivalent(abc, truth, candidate, min(remaining, 60), root)
                if not equiv:
                    continue
                area, delay, adp = measure_adp(abc, candidate, min(remaining, 30), root)
                if adp < best_adp:
                    shutil.copyfile(candidate, source)
                    best_adp = adp
                    improved_this_pass = True
            except subprocess.TimeoutExpired:
                continue
            except Exception:
                continue

        if not improved_this_pass:
            break

    best_area, best_delay, _ = measure_adp(abc, source, 60, root)
    if best_adp < base_adp:
        print(f"[{case}] convergence loop: {base_adp} -> {best_adp} "
              f"({(1 - best_adp/base_adp)*100:.1f}% reduction, {pass_idx+1} passes)")
    else:
        print(f"[{case}] convergence loop: no improvement ({base_adp})")

    return CaseSummary(
        case=case,
        baseline_area=base_area, baseline_delay=base_delay, baseline_adp=base_adp,
        best_area=best_area, best_delay=best_delay, best_adp=best_adp,
        improvement_ratio=base_adp / best_adp if best_adp else 1.0,
        selected_method="convergence_loop",
    )


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
    tmp = prepare_case_temp_dir(logs, "tmp_small_case", case)

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
        append_small_case_csv(logs / "stage_small_case_log.csv", rows)
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

    append_small_case_csv(logs / "stage_small_case_log.csv", rows)
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
