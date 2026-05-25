# Mockturtle Advanced Structural Optimization Plan

This note records mockturtle methods that can move the project beyond ABC
command sweeping.  It is a planning document only: no final `output/exNNN.aig`
files are modified by this investigation.

Project guardrails:

- Inputs are `benchmarks/ex200.truth` through `benchmarks/ex299.truth`.
- Final outputs remain `output/exNNN.aig`.
- `student/optimizer.py` stays unchanged.
- All generated candidates must be checked by ABC against the original truth
  table before they can replace an output.
- The objective is `ADP = area * delay`, measured by ABC `ps`.
- The current optimizer already has ABC sweeps, BDD/Shannon, SOP/POS,
  arithmetic templates, Boolean fingerprinting, and a basic mockturtle bridge.

## Sources Checked

Local checkout:

- `student/mockturtle_src/include/mockturtle/algorithms/cut_rewriting.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/refactoring.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/resubstitution.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/aig_resub.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/functional_reduction.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/aig_balancing.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/balancing.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xag_balancing.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xag_optimization.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xag_resub.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xag_resub_withDC.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xag_algebraic_rewriting.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/mig_algebraic_rewriting.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/mig_resub.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xmg_algebraic_rewriting.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xmg_optimization.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/xmg_resub.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/akers_synthesis.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/exact_mc_synthesis.hpp`
- `student/mockturtle_src/include/mockturtle/algorithms/node_resynthesis/*.hpp`
- `student/mockturtle_src/include/mockturtle/io/aiger_reader.hpp`
- `student/mockturtle_src/include/mockturtle/io/write_aiger.hpp`
- `student/mockturtle_src/test/algorithms/*.cpp`
- `student/mockturtle_opt/mockturtle_opt.cpp`

Online documentation checked:

- mockturtle main documentation and algorithm index:
  https://mockturtle.readthedocs.io/en/stable/index.html
- mockturtle XAG optimization documentation:
  https://mockturtle.readthedocs.io/en/stable/algorithms/xag_optimization.html
- mockturtle resubstitution documentation:
  https://mockturtle.readthedocs.io/en/stable/algorithms/resubstitution.html
- mockturtle Lorina reader documentation:
  https://mockturtle.readthedocs.io/en/stable/io/lorina_readers.html
- percy exact synthesis documentation:
  https://percy.readthedocs.io/en/latest/introduction.html

## Current Mockturtle Tool Status

Existing file:

- `student/mockturtle_opt/mockturtle_opt.cpp`

Existing modes:

- `aig_resub`
- `functional_reduction`
- `xag_xor_heavy`
- `roundtrip_xag`
- `mig_majority`
- `roundtrip_mig`
- `xmg_arithmetic`
- `roundtrip_xmg`

Current implementation already uses:

- AIGER read/write through Lorina and mockturtle:
  `lorina::read_aiger`, `mockturtle::aiger_reader`, `mockturtle::write_aiger`
- Network conversion through `cleanup_dangling<Ntk, aig_network>`
- AIG balancing, cut rewriting, SOP refactoring, AIG resubstitution
- XAG balancing, XAG algebraic depth rewriting, XAG constant-fanin
  optimization, XAG resubstitution
- MIG algebraic depth rewriting and MIG resubstitution
- XMG algebraic depth rewriting and XMG don't-care optimization
- Functional reduction

The current tool is a good base, but it is still mostly a fixed mode runner.
The next improvement should turn it into a structural candidate generator with
several representation-specific recipes and per-case mode selection.

## Safety Contract

Every method below must follow the same wrapper:

1. Generate a temporary candidate AIG.
2. Run ABC equivalence:

   ```text
   read_truth -xf benchmarks/exNNN.truth; st; &get; &cec -t candidate.aig
   ```

3. Measure candidate area/delay/ADP using ABC `ps`.
4. Replace `output/exNNN.aig` only if:
   - candidate is equivalent, and
   - candidate ADP is lower than the current output ADP.
5. Log generated, equivalent, area, delay, ADP, improvement, mode, and reason.

This makes even aggressive don't-care and exact-rewrite experiments safe.

## Method 1: DAG-Aware Synthesis Orchestration

### Found APIs

Local headers:

- `mockturtle/algorithms/cut_rewriting.hpp`
  - `cut_rewriting_params`
  - `cut_rewriting<Ntk>(ntk, rewriting_fn, params)`
  - Important params:
    - `cut_enumeration_ps.cut_size`
    - `cut_enumeration_ps.cut_limit`
    - `use_dont_cares`
    - `preserve_depth`
    - `allow_zero_gain`
    - `candidate_selection_strategy`
- `mockturtle/algorithms/refactoring.hpp`
  - `refactoring_params`
  - `refactoring<Ntk>(ntk, refactoring_fn, params)`
  - Important params:
    - `max_pis`
    - `use_reconvergence_cut`
    - `use_dont_cares`
- `mockturtle/algorithms/resubstitution.hpp`
  - `resubstitution_params`
  - `default_resubstitution<Ntk>`
  - Important params:
    - `max_pis`
    - `max_divisors`
    - `max_inserts`
    - `use_dont_cares`
    - `preserve_depth`
    - `odc_levels`
- `mockturtle/algorithms/aig_balancing.hpp`
  - `aig_balancing_params`
  - `aig_balance<Ntk>(ntk, params)`
- `mockturtle/algorithms/cleanup.hpp`
  - `cleanup_dangling`

Node resynthesis functions seen in tests:

- `xag_npn_resynthesis<aig_network>`
- `mig_npn_resynthesis`
- `xmg_npn_resynthesis`
- `akers_resynthesis<mig_network>`
- `sop_factoring<Ntk>`
- `exact_resynthesis`

### Network Type

- Primary: `aig_network`
- Alternative resynthesis targets: `mig_network`, `xag_network`, `xmg_network`
- Use `depth_view` and `fanout_view` when algorithms require level/fanout data.

### Expected Benefit

- Area: refactoring and resubstitution can remove nodes.
- Delay: balancing and preserve-depth cut rewriting can reduce levels.
- Both: build several non-random structural candidates and select by ADP.

### Target Circuit Types

- General random-like logic
- Mux-like logic with reconvergence
- Medium/large logic where ABC sweep has plateaued
- Any case with high current area or high delay

### Implementation Difficulty

Medium.  Most APIs are already included in the current C++ tool.  The main work
is to expose more deterministic recipes and log per-step network statistics.

### Integration Plan

Add C++ modes:

- `dag_area_oriented`
  - read AIG into `aig_network`
  - `cut_rewriting` with `cut_size=4`, area-oriented NPN resyn
  - `refactoring` with `sop_factoring`
  - `aig_resubstitution2` or `default_resubstitution`
  - `cleanup_dangling`
- `dag_delay_oriented`
  - `aig_balance(minimize_levels=true)`
  - `cut_rewriting(preserve_depth=true, cut_size=5)`
  - `aig_balance(fast_mode=true)`
- `dag_adp_oriented`
  - area pass, delay pass, functional reduction, final balancing

Add Python wrapper in `student/flow_optimizer.py`:

- Select `dag_area_oriented` for area bottlenecks.
- Select `dag_delay_oriented` for delay bottlenecks.
- Select `dag_adp_oriented` for balanced bottlenecks.
- Keep at most one candidate per recipe; this is structural orchestration, not a
  command sweep.

### Safety

Use ABC equivalence and ADP selection.  Internal mockturtle transformations are
expected to be function-preserving, but ABC is the final authority.

## Method 2: Don't-Care Rewriting

### Found APIs

Local headers:

- `cut_rewriting_params::use_dont_cares`
- `refactoring_params::use_dont_cares`
- `resubstitution_params::use_dont_cares`
- `resubstitution_params::odc_levels`
- `mockturtle/algorithms/xag_optimization.hpp`
  - `xag_dont_cares_optimization(xag_network const&)`
- `mockturtle/algorithms/xmg_optimization.hpp`
  - `xmg_dont_cares_optimization(xmg_network const&)`
- `mockturtle/algorithms/xag_resub_withDC.hpp`
  - `resubstitution_minmc_withDC<Ntk>`

Online docs confirm:

- XAG optimization has `xag_dont_cares_optimization`, which can replace some
  AND gates when satisfiability don't-cares allow it.
- Resubstitution supports window-based don't-cares and simulation-guided
  workflows.

### Network Type

- AIG for generic don't-care cut rewriting/refactoring/resubstitution
- XAG for XOR-heavy functions and `resubstitution_minmc_withDC`
- XMG for XOR-majority mixed functions and `xmg_dont_cares_optimization`

### Expected Benefit

- Area: can replace subgraphs with smaller equivalent-in-context logic.
- Delay: can simplify critical subgraphs if combined with depth-aware rewriting.
- Best for cases stuck because local exact function is over-constrained by
  global equivalence, while local context has observability don't-cares.

### Target Circuit Types

- Arithmetic-like functions with large internal don't-care contexts
- Comparator-like functions
- Mux-like functions
- Dense/random-like functions where window-level replacements help

### Implementation Difficulty

Medium to high.  The APIs exist, but don't-care parameters can be expensive.
Runtime must be bounded per candidate.

### Safe Approximation if Direct DC Is Unstable

If a direct don't-care API gives compile or runtime issues:

- Run a candidate with local DC enabled in a temporary network.
- Export AIG.
- Let ABC reject any non-equivalent result.
- Limit to small windows:
  - `max_pis <= 6`
  - `cut_size <= 5`
  - `odc_levels` small, e.g. `1` or `2`
  - short timeout per mode

### Integration Plan

Add C++ modes:

- `dc_aig_rewrite`
  - `cut_rewriting(use_dont_cares=true, preserve_depth=true, cut_size=4/5)`
  - `refactoring(use_dont_cares=true, max_pis=6)`
  - `default_resubstitution(use_dont_cares=true, preserve_depth=true)`
- `dc_xag_minmc`
  - read AIG as XAG
  - `xag_dont_cares_optimization`
  - `resubstitution_minmc_withDC`
  - `xag_balance`
- `dc_xmg`
  - read AIG as XMG
  - `xmg_dont_cares_optimization`
  - `xmg_algebraic_depth_rewriting`

Python selection:

- Use for `arithmetic_like`, `mux_like`, `random_like`, or high area
  bottlenecks.
- Do not run on every small case by default.

### Safety

Because don't-care rewriting may be aggressive, every candidate must pass ABC
`&cec` before selection.  A failed candidate is logged and discarded.

## Method 3: Exact Synthesis / Exact Rewriting

### Found APIs

Local headers:

- `mockturtle/algorithms/exact_mc_synthesis.hpp`
  - `exact_mc_synthesis<Ntk>(truth_table, params)`
  - `exact_mc_synthesis_multiple<Ntk>(truth_table, num_solutions, params)`
  - Important params:
    - `min_and_gates`
    - `conflict_limit`
    - symmetry breaking options
    - optional XOR bound
- `mockturtle/algorithms/node_resynthesis/exact.hpp`
  - `exact_resynthesis`
- `mockturtle/algorithms/node_resynthesis/xag_npn.hpp`
- `mockturtle/algorithms/node_resynthesis/xmg_npn.hpp`
- `mockturtle/algorithms/node_resynthesis/mig_npn.hpp`
- `mockturtle/algorithms/cut_rewriting.hpp`
  - works with exact/NPN resynthesis functions
- `student/mockturtle_src/lib/percy/percy/percy.hpp`
  - percy is present locally

Online docs:

- percy provides SAT-based exact synthesis engines and Boolean chains.
- It supports specifications, encoders, solvers, and synthesizers, and can be
  used for cut-level resynthesis.

### Network Type

- Small whole functions: `xag_network` using `exact_mc_synthesis`
- Small cuts: AIG/XAG/MIG/XMG through `cut_rewriting` plus exact/NPN
  resynthesis
- Candidate outputs still exported as AIGER

### Expected Benefit

- Area: strong on small support and small cuts.
- Delay: useful if exact network is smaller and then rebalanced.
- Not a good fit for large whole truth tables unless effective support is small.

### Target Circuit Types

- Effective support <= 6 whole-output functions
- Small NPN template cases
- Small arithmetic output bits
- Decoder/cube/exact-one functions
- Small critical cuts in larger designs

### Implementation Difficulty

High for whole-network exact synthesis with percy directly; medium for using
mockturtle's existing `exact_mc_synthesis` and exact/NPN node-resynthesis
wrappers.

### Integration Plan

Add C++ modes:

- `exact_whole_xag`
  - Parse `.truth` in C++ or pass a temporary PLA/BLIF from Python.
  - Build `kitty::dynamic_truth_table`.
  - If effective support <= 6 or <= 8 with strict conflict limit:
    - call `exact_mc_synthesis<xag_network>`
    - convert to AIGER
- `exact_cut_xag4`
  - read current AIG as `aig_network` or `xag_network`
  - `cut_rewriting` with `cut_size=4`
  - use `xag_npn_resynthesis<aig_network>` or exact resynthesis
- `exact_cut_xag5`
  - same but `cut_size=5`, tighter timeout and preserve-depth

Python selection:

- Use for `small_template`, `cube_decoder_like`, `affine`, `parity`, and
  `effective_support <= 6`.
- Also use on compact outputs identified by `--small-case-refine`.

### Safety

Limit exact modes by support size and conflict limit.  ABC equivalence must
still gate selection.

## Method 4: XAG-Specific Optimization

### Found APIs

Local headers:

- `mockturtle/networks/xag.hpp`
- `mockturtle/algorithms/xag_balancing.hpp`
  - `xag_balance<Ntk>`
- `mockturtle/algorithms/xag_algebraic_rewriting.hpp`
  - `xag_algebraic_depth_rewriting<Ntk>`
  - strategies: `dfs`, `aggressive`, `selective`
  - params include `overhead`, `allow_area_increase`, `allow_rare_rules`
- `mockturtle/algorithms/xag_optimization.hpp`
  - `xag_constant_fanin_optimization`
  - `xag_dont_cares_optimization`
  - `linear_resynthesis_optimization`
  - `exact_linear_resynthesis_optimization`
- `mockturtle/algorithms/xag_resub.hpp`
  - `xag_resubstitution<Ntk>`
- `mockturtle/algorithms/xag_resub_withDC.hpp`
  - `resubstitution_minmc_withDC<Ntk>`

### Network Type

- `xag_network`
- Read AIGER into XAG with `aiger_reader(xag)`.
- Convert back with `cleanup_dangling<xag_network, aig_network>`.

### Expected Benefit

- Area: reduces AND gates in XOR-heavy networks.
- Delay: XAG balancing and algebraic depth rewriting can reduce XOR/AND depth.
- Both: exact linear resynthesis can improve XOR cones that ABC AIG flows do
  not see directly.

### Target Circuit Types

- `affine`, `parity`, `adder_sum_like`
- XOR-heavy arithmetic output bits
- Some multiplier/square output bits with XOR-rich partial product structure

### Implementation Difficulty

Medium.  Current tool already has `xag_xor_heavy`; it should be expanded into
distinct modes with explicit goals.

### Integration Plan

Add C++ modes:

- `xag_area_minmc`
  - `xag_constant_fanin_optimization`
  - `resubstitution_minmc_withDC`
  - `xag_resubstitution(max_inserts=1)`
  - `xag_balance(minimize_levels=false)`
- `xag_delay_depth`
  - `xag_balance(minimize_levels=true)`
  - `xag_algebraic_depth_rewriting(strategy=selective)`
  - `xag_algebraic_depth_rewriting(strategy=aggressive, overhead=1.2)`
- `xag_exact_linear`
  - `exact_linear_resynthesis_optimization(conflict_limit=bounded)`
  - `xag_balance`

Python selection:

- Use when fingerprint labels include `affine`, `parity`, `adder_sum_like`,
  `arithmetic_like`, or high ANF odd-degree/XOR score.

### Safety

Export candidate AIG, ABC-equivalence check, ABC ADP measurement.

## Method 5: MIG / Majority Optimization

### Found APIs

Local headers:

- `mockturtle/networks/mig.hpp`
- `mockturtle/algorithms/akers_synthesis.hpp`
  - `akers_synthesis<mig_network>(func, care)`
  - also supports synthesis into an existing network with leaves
- `mockturtle/algorithms/mig_algebraic_rewriting.hpp`
  - `mig_algebraic_depth_rewriting<Ntk>`
  - strategies: `dfs`, `aggressive`, `selective`
- `mockturtle/algorithms/mig_resub.hpp`
  - `mig_resubstitution<Ntk>`
  - `mig_resubstitution2<Ntk>`
- `mockturtle/algorithms/node_resynthesis/mig_npn.hpp`
- `mockturtle/algorithms/node_resynthesis/akers.hpp`

### Network Type

- `mig_network`
- Optional `depth_view` and `fanout_view`

### Expected Benefit

- Delay: majority associativity and balancing can reduce carry/threshold depth.
- Area: resubstitution can replace majority structures with fewer nodes.
- ADP: useful when ABC AIG representation obscures majority/carry shape.

### Target Circuit Types

- `threshold_like`
- `majority`
- `carry_like`
- comparator-like
- monotone symmetric logic

### Implementation Difficulty

Medium.  Current tool already reads AIG as MIG and applies algebraic rewriting.
New value comes from Akers/cut-based majority resynthesis and parameterized
depth strategies.

### Integration Plan

Add C++ modes:

- `mig_akers_cut4`
  - `cut_rewriting` on MIG using `akers_resynthesis<mig_network>`
  - `cut_size=4`
  - `preserve_depth=true`
- `mig_npn_cut5`
  - `cut_rewriting` using `mig_npn_resynthesis`
  - `cut_size=5`
- `mig_depth_selective`
  - `mig_algebraic_depth_rewriting(strategy=selective)`
  - `mig_resubstitution(max_inserts=1, preserve_depth=true)`
- `mig_area_resub`
  - `mig_resubstitution2`
  - cleanup

Python selection:

- Use when labels include `threshold_like`, `symmetric_like`, `majority`,
  `carry_like`, `comparator_like`, or monotone positive.

### Safety

MIG candidates are converted to AIG and checked by ABC.

## Method 6: XMG Optimization

### Found APIs

Local headers:

- `mockturtle/networks/xmg.hpp`
- `mockturtle/algorithms/xmg_algebraic_rewriting.hpp`
  - `xmg_algebraic_depth_rewriting<Ntk>`
  - strategies: `dfs`, `aggressive`, `selective`
- `mockturtle/algorithms/xmg_optimization.hpp`
  - `xmg_dont_cares_optimization`
- `mockturtle/algorithms/xmg_resub.hpp`
  - `xmg_resubstitution<Ntk>`
- `mockturtle/algorithms/node_resynthesis/xmg_npn.hpp`
- `mockturtle/algorithms/node_resynthesis/xmg3_npn.hpp`

### Network Type

- `xmg_network`

### Expected Benefit

- Area: XMG can compact XOR-majority mixed functions.
- Delay: XMG algebraic rewriting has critical-path strategies.
- ADP: promising for arithmetic logic with both sum and carry behavior.

### Target Circuit Types

- Mixed XOR/majority arithmetic
- adder sum/carry-like outputs
- multiplier/square mid bits
- comparator-adder hybrids

### Implementation Difficulty

Medium to high.  Current tool only uses `xmg_dont_cares_optimization` and
algebraic rewriting.  Adding XMG resubstitution and XMG NPN cut rewriting is the
next step.

### Integration Plan

Add C++ modes:

- `xmg_mixed_resub`
  - `xmg_algebraic_depth_rewriting(strategy=selective)`
  - `xmg_resubstitution(max_pis=8, max_inserts=1)`
  - `xmg_dont_cares_optimization`
- `xmg_cut_npn4`
  - `cut_rewriting` with `xmg_npn_resynthesis`
  - `cut_size=4`
- `xmg_cut_xmg3`
  - `cut_rewriting` with `xmg3_npn_resynthesis`
  - use for 3-input majority/xor local cuts

Python selection:

- Use when labels include both XOR-like and majority/carry-like indicators:
  `adder_sum_like`, `carry_like`, `arithmetic_like`, `xmg_arithmetic`.

### Safety

Export to AIGER, then ABC equivalence and ADP measurement.

## Method 7: Functional Reduction / SAT Sweeping

### Found APIs

Local headers:

- `mockturtle/algorithms/functional_reduction.hpp`
  - `functional_reduction<Ntk>(ntk, params)`
  - params:
    - `max_iterations`
    - `num_patterns`
    - `max_patterns`
    - `conflict_limit`
    - `max_TFI_nodes`
    - `skip_fanout_limit`
- `mockturtle/algorithms/equivalence_classes.hpp`
- `mockturtle/algorithms/equivalence_checking.hpp`

### Network Type

- Generic `Ntk` with fanin/fanout traversal and substitution support
- Use mainly on `aig_network`, `xag_network`, `mig_network`, `xmg_network`

### Expected Benefit

- Area: merges functionally equivalent nodes and constants.
- Delay: indirect, by removing redundant nodes before balancing.
- Very useful after structural generators create redundant alternatives.

### Target Circuit Types

- Any candidate from BDD/SOP/templates/mockturtle roundtrip
- Large generated arithmetic candidates
- Cases with high redundancy after representation conversion

### Implementation Difficulty

Low.  Already implemented as `functional_reduction` mode.  Needs better use as
a post-pass after every representation-specific structural mode.

### Integration Plan

Add functional reduction as an optional post-step inside C++ modes:

- `--fr` or mode suffix `_fr`
- `functional_reduction(max_iterations=3, conflict_limit=100)`
- `cleanup_dangling`
- representation-specific balance

Python selection:

- Always allow one functional-reduction candidate after a structural candidate,
  but cap the number of modes per case.

### Safety

ABC equivalence and ADP check.

## Method 8: Cut Rewriting with Larger Cuts

### Found APIs

Local headers:

- `cut_rewriting_params`
  - default `cut_size=6`
  - default `cut_limit=12`
  - `min_cand_cut_size`
  - `preserve_depth`
  - `use_dont_cares`
- Resynthesis functions:
  - `xag_npn_resynthesis<aig_network>`
  - `mig_npn_resynthesis`
  - `xmg_npn_resynthesis`
  - `xmg3_npn_resynthesis`
  - `akers_resynthesis<mig_network>`
  - `exact_resynthesis`

### Network Type

- AIG, XAG, MIG, XMG depending on resynthesis function

### Expected Benefit

- Area: larger cuts can find replacements missed by 4-input cuts.
- Delay: preserve-depth mode can avoid area wins that hurt levels.
- ADP: 4/5-input cut modes are a good bounded structural search.

### Target Circuit Types

- Small and medium cases
- Mux-like and random-like local cones
- Arithmetic local cones where small exact cuts appear often

### Implementation Difficulty

Medium.  Need compile-time wiring of resynthesis functions and careful runtime
limits.

### Integration Plan

Add C++ modes:

- `cut4_aig_xag_npn`
  - AIG target, `xag_npn_resynthesis<aig_network>`, `cut_size=4`
- `cut5_aig_xag_npn_depth`
  - AIG target, `cut_size=5`, `preserve_depth=true`
- `cut4_mig_akers`
  - MIG target, Akers resynthesis
- `cut4_xmg_npn`
  - XMG target, XMG NPN resynthesis
- `cut6_exact_limited`
  - only on small networks or short timeout

Python selection:

- `cut4_*` can be tried broadly.
- `cut5_*` only when current ADP is not already tiny.
- `cut6_exact_limited` only for effective support <= 8 or compact output.

### Safety

All candidates must pass ABC.  Large cut modes should write failure reason if
timeout occurs.

## Method 9: Structural Choice / Representation Diversity

### Found APIs

Local headers:

- `mockturtle/views/choice_view.hpp`
- `mockturtle/algorithms/equivalence_classes.hpp`
- `mockturtle/algorithms/cleanup.hpp`
- `mockturtle/algorithms/functional_reduction.hpp`
- `mockturtle/io/write_aiger.hpp`

### Network Type

- AIG as final carrier
- XAG/MIG/XMG as temporary candidate representations

### Expected Benefit

- Both area and delay.
- The same function can have very different structure in AIG, XAG, MIG, and
  XMG.  ABC may optimize each differently after conversion.

### Target Circuit Types

- All cases, but mode selection should be fingerprint-driven:
  - XAG for XOR-heavy
  - MIG for threshold/carry/monotone
  - XMG for mixed XOR-majority
  - AIG for general

### Implementation Difficulty

Medium.  The simplest version does not need a full `choice_view`; just preserve
multiple equivalent candidate AIGs and let Python select by ADP.  A full choice
network is more complex and may not export to AIGER as intended.

### Integration Plan

In `flow_optimizer.py`, add a structural candidate manager:

- For each case, compute fingerprint once.
- Pick at most 3 representation routes:
  - `aig_dag_*`
  - `xag_*`
  - `mig_*`
  - `xmg_*`
- Each route emits one temporary AIG.
- Each temporary AIG receives the same small ABC polish set:
  - `strash; dc2; balance`
  - `strash; rewrite -z; refactor -z; dc2; balance`
  - `strash; dch; if -K 6; strash; dc2; balance`
- Equivalent candidates enter a Pareto set by area/delay.
- Final output is minimum ADP.

This is not a random sweep; it is representation diversity with fixed,
fingerprint-selected candidates.

### Safety

The current Python safety machinery is enough:

- generate temp AIG
- ABC equivalence
- ABC ADP
- replace only if lower ADP

## Recommended Implementation Roadmap

### Phase A: Extend C++ Tool Modes

Add deterministic modes to `student/mockturtle_opt/mockturtle_opt.cpp`:

```text
dag_area_oriented
dag_delay_oriented
dag_adp_oriented
dc_aig_rewrite
dc_xag_minmc
xag_area_minmc
xag_delay_depth
xag_exact_linear
mig_akers_cut4
mig_depth_selective
xmg_mixed_resub
xmg_cut_npn4
cut4_aig_xag_npn
cut5_aig_xag_npn_depth
functional_reduce_fr
```

Each mode should:

- read `--input-aig`
- run exactly one structural recipe
- write `--output-aig`
- return nonzero on unsupported/failed API

### Phase B: Add Python Structural Planner

Add to `student/flow_optimizer.py`:

```text
--mockturtle-advanced-structural
--mockturtle-advanced-case exNNN
--mockturtle-max-structural-modes N
```

Selection logic:

- `affine` or `parity`: `xag_exact_linear`, `xag_area_minmc`,
  `cut4_aig_xag_npn`
- `threshold`, `majority`, `carry_like`: `mig_akers_cut4`,
  `mig_depth_selective`, `dc_xmg`
- `arithmetic_like` mixed: `xmg_mixed_resub`, `xag_area_minmc`,
  `functional_reduce_fr`
- `mux_like` or `random_like`: `dag_adp_oriented`, `dc_aig_rewrite`,
  `cut5_aig_xag_npn_depth`
- compact/low-ADP cases: `exact_cut_xag4`, `cut4_aig_xag_npn`,
  `functional_reduce_fr`

### Phase C: Measure and Integrate

Add logs:

```text
student/logs/mockturtle_advanced_candidates.csv
student/logs/mockturtle_advanced_summary.csv
```

Candidate columns:

```text
case, labels, mode, reason, generated, equivalent, area, delay, adp, improved, error
```

Summary columns:

```text
case, current_adp, best_adp, selected_mode, improvement
```

### Phase D: Promote Safe Winners

Only after a full experimental pass:

- keep modes that improve at least one case
- remove modes that always timeout or never generate equivalent candidates
- add the best stable mode package to `--reproduce-best`

## Priority Ranking

Highest priority:

1. `cut4_aig_xag_npn` and `cut5_aig_xag_npn_depth`
2. `dc_aig_rewrite`
3. `xag_area_minmc`
4. `mig_akers_cut4`
5. `xmg_mixed_resub`
6. representation-diversity planner in Python

Reason:

- Cut rewriting with 4/5-input cuts is structurally different from ABC command
  sweeping but still bounded.
- Don't-care rewriting is a clear next lever for stuck local cones.
- XAG/MIG/XMG modes align with the existing Boolean fingerprint labels.
- Functional reduction is cheap and should be used as a post-step.

## Risks

- Some mockturtle algorithms require `depth_view`, `fanout_view`, or a specific
  network interface.  Compile errors should disable only that mode.
- Larger exact synthesis can explode.  Keep exact modes behind support/cut-size
  and conflict-limit guards.
- Don't-care modes can be aggressive.  ABC equivalence filtering is mandatory.
- Network conversion can increase area before ABC polish.  Do not judge the raw
  mockturtle result; always measure after a small fixed ABC polish.

## Bottom Line

The most promising non-sweep direction is a structural mockturtle candidate
generator:

```text
truth/fingerprint -> choose AIG/XAG/MIG/XMG structural recipe
                  -> mockturtle candidate
                  -> fixed tiny ABC polish
                  -> ABC equivalence
                  -> ABC ADP selection
```

This keeps the project reproducible and safe while adding genuinely different
optimization mechanisms: cut-level exact/NPN rewriting, don't-care rewriting,
XAG multiplicative-complexity reduction, MIG majority resynthesis, XMG mixed
rewriting, and SAT-based functional reduction.
