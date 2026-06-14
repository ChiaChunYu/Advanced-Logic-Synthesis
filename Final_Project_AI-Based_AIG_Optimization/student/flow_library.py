#!/usr/bin/env python3
"""ABC flow constants and flow-selection helpers.

All PostFlow lists, flow libraries, and the flow-selection logic live here.
flow_optimizer.py imports from this module instead of defining everything inline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PostFlow:
    name: str
    commands: str


# ---------------------------------------------------------------------------
# Basic post-flows
# ---------------------------------------------------------------------------

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

AREA_FIRST_FLOWS = [
    PostFlow("af_rw_rf_loop", "rewrite -z; refactor -z; rewrite -z; refactor -z; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_dc2_x5", "dc2; rewrite -z; dc2; refactor -z; dc2; rewrite -z; dc2; balance"),
    PostFlow("af_fraig_rw_rf_x2", "fraig; rewrite -z; refactor -z; dc2; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_dch_if3", "dch; if -K 3; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_dch_if4", "dch; if -K 4; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_resub8_n2_x2", "resub -K 8 -N 2; rewrite -z; refactor -z; dc2; resub -K 8 -N 2; rewrite -z; dc2; balance"),
    PostFlow("af_resub10_n2", "resub -K 10 -N 2; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_collapse_sop_fx", "collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; rewrite -z; balance"),
    PostFlow("af_gia_compress2rs_x3", "&get; &compress2rs; &compress2rs; &compress2rs; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_gia_dc2_compress", "&get; &dc2; &compress2rs; &dc2; &compress2rs; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_gia_mfs_compress", "&get; &mfs; &compress2rs; &mfs; &compress2rs; &put; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_gia_compress3rs_x5", "&get; &compress3rs; &compress3rs; &compress3rs; &compress3rs; &compress3rs; &put; dc2; balance"),
    PostFlow("af_resub12_n3", "resub -K 12 -N 3; balance; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_gia_dsdb_compress3rs", "&get; &dsdb -K 6 -C 64; &compress3rs; &compress3rs; &compress3rs; &put; dc2; balance"),
    PostFlow("af_gia_dsd_compress3rs", "&get; &dsd; &compress3rs; &compress3rs; &compress3rs; &put; dc2; balance"),
    PostFlow("af_gia_resyn3_compress3", "&get; &resyn3; &compress3rs; &resyn3; &compress3rs; &put; dc2; balance"),
    PostFlow("af_sopb_balance", "&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    PostFlow("af_sopb_c8_balance", "&get; &sopb -C 8 -R 1; &put; balance; rewrite -z; refactor -z; balance"),
    PostFlow("af_b_d_s_compress", "&get; &b -d -s; &compress3rs; &compress3rs; &put; balance; rewrite -z; balance"),
]

AREA_FIRST_RESYNTH_FLOWS = [
    PostFlow("af_resynth_collapse_fx", "collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("af_resynth_dch_if4_area", "dch; if -K 4; strash; rewrite -z; refactor -z; dc2; rewrite -z; balance"),
]

# ---------------------------------------------------------------------------
# Mockturtle / structural modes
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Specialised generator / rescue flows
# ---------------------------------------------------------------------------

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

DEEPSYN_STRUCTURAL_POLISH_FLOWS = [
    PostFlow("deepsyn_base", ""),
    PostFlow("deepsyn_area", "strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("deepsyn_delay", "strash; balance; rewrite; balance; refactor; balance"),
]

PARETO_AREA_STRUCTURAL_POLISH_FLOWS = [
    PostFlow("pareto_raw", ""),
    PostFlow("pareto_area_cleanup", "strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("pareto_dsd_balance", "&get; &dsdb -K 6 -C 16 -R 100; &put; strash; dc2; balance"),
]

HYBRID_YOSYS_POLISH_FLOWS = [
    PostFlow("yosys_base", ""),
    PostFlow("yosys_area", "strash; rewrite -z; refactor -z; dc2; balance"),
    PostFlow("yosys_delay", "strash; balance; rewrite; balance; refactor; balance"),
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

# ---------------------------------------------------------------------------
# Type-guided flow library
# ---------------------------------------------------------------------------

TYPE_GUIDED_FLOW_LIBRARY: dict[str, list[PostFlow]] = {
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
    "monotone_general": [
        PostFlow("type_mono_dch_if6_area", "dch; if -K 6; strash; resub -K 6; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_mono_dch_if10_delay", "dch; if -K 10; strash; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("type_mono_gia_b_sopb", "&get; &b -d -s; &sopb -C 12 -R 1; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_mono_gia_mfs", "&get; &mfs; &compress3rs; &resyn3rs; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
    "constant_mixed": [
        PostFlow("type_const_dchoice_ifraig", "dchoice; ifraig; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("type_const_gia_sopb_c8", "&get; &sopb -C 8 -R 1; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_const_collapse_fx", "collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("type_const_resub4_delay", "resub -K 4; dch; if -K 6; strash; dc2; balance"),
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

# Seed flows — identical commands, different name prefixes for logging clarity.
_SEED_FLOW_SPECS = [
    ("area",    "strash; rewrite -z; refactor -z; dc2; balance"),
    ("delay",   "strash; balance; rewrite; balance; refactor; balance"),
    ("dch_if6", "strash; dch; if -K 6; strash; dc2; balance"),
    ("gia",     "strash; &get; &dc2; &compress3rs; &put; rewrite -z; refactor -z; dc2; balance"),
]
CIRCUIT_TYPE_SEED_FLOWS = [PostFlow(f"ct_seed_{s}", c) for s, c in _SEED_FLOW_SPECS]
SEMANTIC_SPLIT_FLOWS    = [PostFlow(f"sem_{s}", c)     for s, c in _SEED_FLOW_SPECS]

CIRCUIT_TYPE_POLISH_LIBRARY: dict[str, list[PostFlow]] = {
    "xor_affine": TYPE_GUIDED_FLOW_LIBRARY["xor_affine"] + [
        PostFlow("ct_xor_xag_round", "&get; &resyn3rs; &compress3rs; &put; dc2; balance"),
    ],
    "arithmetic": TYPE_GUIDED_FLOW_LIBRARY["arithmetic"] + [
        PostFlow("ct_arith_if12_mfs", "dch; if -K 12; strash; &get; &mfs; &compress3rs; &put; dc2; balance"),
    ],
    "threshold_majority": TYPE_GUIDED_FLOW_LIBRARY["threshold_majority"] + [
        PostFlow("ct_threshold_resub4_if5", "resub -K 4; dch; if -K 5; strash; rewrite -z; dc2; balance"),
    ],
    "mux_shannon": TYPE_GUIDED_FLOW_LIBRARY["mux_shannon"] + [
        PostFlow("ct_mux_selector_if10", "dch; if -K 10; strash; dc2; balance; rewrite -z; refactor -z; balance"),
        PostFlow("ct_mux_sopb_dchoice", "&get; &sopb -C 12 -R 1; &put; dchoice; ifraig; dc2; balance"),
    ],
    "monotone_general": TYPE_GUIDED_FLOW_LIBRARY["monotone_general"] + [
        PostFlow("ct_mono_resub8_if8", "resub -K 8 -N 2; dch; if -K 8; strash; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("ct_mono_sopb_c16", "&get; &sopb -C 16 -R 1; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
    ],
    "constant_mixed": TYPE_GUIDED_FLOW_LIBRARY["constant_mixed"] + [
        PostFlow("ct_const_gia_dsd", "&get; &dsd; &compress3rs; &put; balance; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("ct_const_lowk", "dch; if -K 4; strash; resub -K 4; rewrite -z; dc2; balance"),
    ],
    "small_template": TYPE_GUIDED_FLOW_LIBRARY["small_template"] + [
        PostFlow("ct_small_if4", "dch; if -K 4; strash; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("ct_small_fx_dc2", "collapse; sop; fx; strash; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("ct_small_gia_sopb", "&get; &sopb -C 8 -R 1; &put; rewrite -z; refactor -z; dc2; balance"),
    ],
    "general": TYPE_GUIDED_FLOW_LIBRARY["general"] + [
        PostFlow("ct_general_resub10", "resub -K 10 -N 2; rewrite -z; refactor -z; dc2; balance"),
        PostFlow("ct_general_dsd_sopb", "&get; &dsd; &sopb -C 16 -R 1; &compress3rs; &put; rewrite -z; refactor -z; dc2; balance"),
    ],
}

# ---------------------------------------------------------------------------
# Objective-guided library
# ---------------------------------------------------------------------------

OBJECTIVE_GUIDED_FLOW_LIBRARY: dict[str, list[PostFlow]] = {
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

# ---------------------------------------------------------------------------
# Micro / small / GIA flows
# ---------------------------------------------------------------------------

MICRO_GUIDED_FLOWS = [
    PostFlow("micro_resub4", "resub -K 4; balance; rewrite -z; refactor -z; balance"),
    PostFlow("micro_if3", "dch; if -K 3; strash; dc2; balance"),
    PostFlow("micro_renode", "renode; strash; dc2; rewrite -z; refactor -z; balance"),
]

GIA_CANONICAL_FLOW = PostFlow("gia_canonical", "&get; &put; strash; dc2; balance")

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

# ---------------------------------------------------------------------------
# GA / history-guided pools
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Flow-selection helpers
# ---------------------------------------------------------------------------

def _dedup_flows(flows: list[PostFlow], limit: int) -> list[PostFlow]:
    """Deduplicate flows by command string, keeping the first occurrence, up to *limit*."""
    seen: set[str] = set()
    result: list[PostFlow] = []
    for flow in flows:
        if flow.commands not in seen:
            seen.add(flow.commands)
            result.append(flow)
            if len(result) >= limit:
                break
    return result


def type_guided_family(fingerprint) -> tuple[str, str]:
    """Map a case fingerprint to a TYPE_GUIDED_FLOW_LIBRARY family key."""
    labels = set(fingerprint.labels)
    strategy = fingerprint.recommended_strategy
    if labels & {"parity", "affine", "adder_sum_like"} or "xor" in strategy:
        return "xor_affine", "affine/parity or XOR-heavy fingerprint"
    if labels & {"carry_like"} or "arithmetic" in strategy:
        return "arithmetic", "arithmetic XOR/majority fingerprint"
    if "constant_output_mixed" in labels:
        return "constant_mixed", "multi-output function with some constant outputs"
    if "monotone_positive_general" in labels:
        return "monotone_general", "high-monotonicity general logic fingerprint"
    if labels & {"majority", "threshold_positive", "threshold_negative", "exact_k",
                 "one_hot_exactly_one", "symmetric"}:
        return "threshold_majority", "threshold/majority/symmetric fingerprint"
    if "mux_like" in labels or "shannon" in strategy:
        return "mux_shannon", "mux-like or Shannon selector fingerprint"
    if len(fingerprint.effective_support) <= 6 or any(label.startswith("npn_") for label in labels):
        return "small_template", "small-support/NPN-template fingerprint"
    return "general", "general mixed-logic fingerprint"


def select_type_guided_flows(
    fingerprint, area: int, delay: int, adp: int, limit: int
) -> tuple[str, str, list[PostFlow]]:
    family, reason = type_guided_family(fingerprint)
    flows = list(TYPE_GUIDED_FLOW_LIBRARY[family])
    if delay >= 18:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[0])
    if area >= 5000 or adp >= 100000:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[1])
    if family != "general":
        flows.append(TYPE_GUIDED_FLOW_LIBRARY["general"][0])
    return family, reason, _dedup_flows(flows, limit)


def select_circuit_type_flows(
    fingerprint, area: int, delay: int, adp: int, limit: int
) -> tuple[str, str, list[PostFlow]]:
    family, reason = type_guided_family(fingerprint)
    flows = list(CIRCUIT_TYPE_POLISH_LIBRARY.get(family, CIRCUIT_TYPE_POLISH_LIBRARY["general"]))
    if delay >= 18:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[0])
    if area >= 5000 or adp >= 100000:
        flows.append(TYPE_GUIDED_SHARED_FLOWS[1])
    return family, reason, _dedup_flows(flows, limit)


def select_objective_guided_flows(max_per_objective: int) -> list[tuple[str, PostFlow]]:
    selected: list[tuple[str, PostFlow]] = []
    seen: set[str] = set()
    for objective, flows in OBJECTIVE_GUIDED_FLOW_LIBRARY.items():
        count = 0
        for flow in flows:
            if flow.commands in seen:
                continue
            seen.add(flow.commands)
            selected.append((objective, flow))
            count += 1
            if count >= max_per_objective:
                break
    return selected


def select_micro_guided_flows(max_flows: int) -> list[PostFlow]:
    return _dedup_flows(MICRO_GUIDED_FLOWS + MICRO_COLLAPSE_FLOWS, max_flows)


def select_small_case_flows(max_flows: int) -> list[PostFlow]:
    return _dedup_flows(SMALL_CASE_FLOWS, max_flows)


# ---------------------------------------------------------------------------
# GA / flow mutation helpers
# ---------------------------------------------------------------------------

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


def make_history_guided_ga_flows(
    case: str,
    logs: Path,
    seed: int,
    count: int,
    read_result_rows_fn,
    row_int_fn,
) -> list[PostFlow]:
    """Build history-guided GA flows.

    Callers must pass the read_result_rows and row_int callables to avoid
    a circular import between flow_library and result_logging.
    """
    rows = read_result_rows_fn(logs / "stage_reproduce_log.csv") or read_result_rows_fn(logs / "results.csv")
    equivalent = [row for row in rows if row.get("equivalent") in ("1", "True", "true") and row.get("flow_commands", "")]
    same_case = [row for row in equivalent if row.get("case") == case]
    pool = same_case or equivalent
    pool = sorted(pool, key=lambda row: row_int_fn(row, "adp", 10**30))[: max(4, count)]
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
