# Contest-Style AIG Optimization Plan

This document completes **PHASE 0** from `AGENTS.md`: inspect the current
project, inspect local mockturtle support, and define a safe incremental
contest-inspired optimization path.  No final `output/exNNN.aig` files are
modified by this phase.

## Current Project Snapshot

Important files:

- `student/optimizer.py`
  - Original baseline; must remain unchanged.
  - Baseline flow is `read_truth -xf; st; write_aiger`.
- `student/flow_optimizer.py`
  - Main optimizer.
  - Current features include hybrid initial synthesis, BDD/Shannon, SOP/POS,
    arithmetic templates, ABC polish/refinement, mockturtle structural modes,
    reproduce-best workflow, and safety checks.
- `student/boolean_fingerprint.py`
  - Truth-table parser and Boolean fingerprint/classification module.
  - Already computes support, influence, monotonicity, Shannon/cofactor data,
    ANF data, labels, and recommended strategy.
- `evaluate.py`
  - Performs ABC equivalence checking and reports area, delay, and ADP.
- `student/mockturtle_opt/mockturtle_opt.cpp`
  - Optional C++ structural resynthesis tool.
- `student/logs/`
  - Existing candidate/result logs, temporary candidate directories, and
    verification reports.
- `output/`
  - Contains 100 final AIG files, `ex200.aig` through `ex299.aig`.

Current verified result recorded in `student/OPTIMIZATION_LOG.md`:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11106756
```

Recent baseline comparison log:

- `student/logs/baseline_vs_current_verify.csv`
- baseline total ADP: `180343842`
- current total ADP: `11106756`
- all 100 cases improved over baseline

## Local Mockturtle Availability

Local source tree:

```text
student/mockturtle_src/
```

Local C++ tool:

```text
student/mockturtle_opt/mockturtle_opt
student/mockturtle_opt/mockturtle_opt.cpp
student/mockturtle_opt/CMakeLists.txt
```

Build command:

```bash
cmake --build student/mockturtle_opt/build --target mockturtle_opt -j2
```

The current build succeeds.  Warnings come from third-party SAT headers, not
from project code.

## API Availability Matrix

| Feature | Local source/header | Network type | Status | Expected benefit | Target cases | Difficulty | Integration plan |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AIG network | `mockturtle/networks/aig.hpp` | `aig_network` | Available | area/delay | general AIG candidates | Low | Read current AIG, apply AIG-specific structural recipes, write AIGER |
| XAG network | `mockturtle/networks/xag.hpp` | `xag_network` | Available | area for XOR-heavy, delay after balancing | affine/parity, sum bits, arithmetic XOR cones | Medium | Convert/read AIG as XAG, run XAG modes, convert to AIG |
| MIG network | `mockturtle/networks/mig.hpp` | `mig_network` | Available | delay and area for majority/carry | threshold, carry, comparator, monotone | Medium | Convert/read AIG as MIG, run Akers/MIG rewriting, convert to AIG |
| XMG network | `mockturtle/networks/xmg.hpp` | `xmg_network` | Available | both for XOR+majority | mixed arithmetic | Medium | Convert/read AIG as XMG, run XMG rewriting/resub, convert to AIG |
| AIGER read | `mockturtle/io/aiger_reader.hpp`, Lorina | any supported network | Available | infrastructure | all | Low | `lorina::read_aiger(path, aiger_reader(ntk))` |
| AIGER write | `mockturtle/io/write_aiger.hpp` | AIG or converted AIG | Available | infrastructure | all | Low | `cleanup_dangling<Ntk, aig_network>` then `write_aiger` |
| Cleanup | `mockturtle/algorithms/cleanup.hpp` | generic | Available | area cleanup | all generated candidates | Low | Run after each structural transformation |
| AIG balancing | `mockturtle/algorithms/aig_balancing.hpp` | AIG | Available | delay, sometimes ADP | high-delay AIG | Low | `aig_balance` before/after structural passes |
| Generic balancing | `mockturtle/algorithms/balancing.hpp` | generic | Available | delay | general | Medium | Use later for custom balance functions |
| Cut rewriting | `mockturtle/algorithms/cut_rewriting.hpp` | generic | Available | area or delay | small/medium cuts, mux/random/arithmetic cones | Medium | Use NPN/Akers/exact resynthesis functions; bound cut sizes |
| Refactoring | `mockturtle/algorithms/refactoring.hpp` | generic | Available | area | SOP/factorable cones | Medium | Use `sop_factoring` with optional don't-care mode |
| Resubstitution | `mockturtle/algorithms/resubstitution.hpp` | generic | Available | area, ADP | reconvergent logic | Medium | Use bounded `max_pis`, `max_inserts`, `preserve_depth` |
| AIG resubstitution | `mockturtle/algorithms/aig_resub.hpp` | AIG-like | Available | area | AIG candidates | Medium | Already used in `aig_resub`; tune only with fixed modes |
| Functional reduction | `mockturtle/algorithms/functional_reduction.hpp` | generic with fanout | Available | area via SAT sweeping | redundant/generated structures | Medium | Run as post-step for structural candidates |
| XAG algebraic rewriting | `mockturtle/algorithms/xag_algebraic_rewriting.hpp` | XAG | Available | delay | XOR-heavy | Medium | Use selective/aggressive mode variants |
| XAG balancing | `mockturtle/algorithms/xag_balancing.hpp` | XAG | Available | delay/ADP | XOR-heavy | Low | Run before/after XAG rewriting |
| XAG optimization | `mockturtle/algorithms/xag_optimization.hpp` | XAG | Available | area | XOR-heavy/min-MC | Medium | Use `xag_constant_fanin_optimization`, `xag_dont_cares_optimization`, exact linear resynthesis |
| XAG DC resub | `mockturtle/algorithms/xag_resub_withDC.hpp` | XAG-like | Available | area | XOR-heavy with local DCs | Medium | Use `resubstitution_minmc_withDC` behind timeout |
| MIG algebraic rewriting | `mockturtle/algorithms/mig_algebraic_rewriting.hpp` | MIG | Available | delay | majority/carry | Medium | Use `mig_algebraic_depth_rewriting` |
| MIG resubstitution | `mockturtle/algorithms/mig_resub.hpp` | MIG-like | Available | area | majority/carry | Medium | Use `mig_resubstitution`, `mig_resubstitution2` |
| Akers synthesis | `mockturtle/algorithms/akers_synthesis.hpp`, `node_resynthesis/akers.hpp` | MIG/XMG/generic | Available | area/delay for small cuts | majority/threshold/small cuts | Medium | Use for MIG cut rewriting and small truth-table synthesis |
| XMG algebraic rewriting | `mockturtle/algorithms/xmg_algebraic_rewriting.hpp` | XMG | Available | delay | XOR+majority | Medium | Use selective mode for arithmetic |
| XMG optimization | `mockturtle/algorithms/xmg_optimization.hpp` | XMG | Available | area via DCs | XOR+majority | Medium | Use `xmg_dont_cares_optimization` |
| XMG resubstitution | `mockturtle/algorithms/xmg_resub.hpp` | XMG-like | Available | area | mixed arithmetic | Medium | Use `xmg_resubstitution` |
| Exact MC synthesis | `mockturtle/algorithms/exact_mc_synthesis.hpp` | XAG default | Available | area for small support | effective support <= 6/7 | High | Use only bounded by support/conflict limit |
| Percy | `student/mockturtle_src/lib/percy/percy/percy.hpp` | exact synthesis backend | Available | exact small circuits | small support/cuts | High | Prefer mockturtle wrappers first |
| Choice view | `mockturtle/views/choice_view.hpp` | generic | Available | representation diversity | Pareto candidates | High | Start with external candidate pool before full choice network |

Unsupported or deferred:

- Full unsafe approximate logic is not allowed.
- Full random transduction is deferred until a safe expansion/reduction wrapper
  is built.
- Direct final-output replacement from mockturtle alone is disallowed; ABC must
  approve equivalence.

## Current Implemented Mockturtle Modes

`student/mockturtle_opt/mockturtle_opt.cpp` currently supports:

```text
xag_xor_heavy
mig_majority
xmg_arithmetic
aig_resub
functional_reduction
roundtrip_xag
roundtrip_mig
roundtrip_xmg
cut4_aig_xag_npn
cut5_aig_xag_npn_depth
dc_aig_rewrite
xag_area_minmc
mig_akers_cut4
xmg_mixed_resub
```

These are not random sweeps.  They are deterministic structural recipes chosen
by Boolean fingerprinting in `student/flow_optimizer.py`.

## Phase-by-Phase Implementation Plan

### Phase 1: Internal Pareto Candidate Pool

Goal:

- Keep multiple equivalent non-dominated candidates per case by `(area, delay)`.
- Still output the minimum-ADP candidate.

Implementation details:

- Add a lightweight `ParetoCandidate` dataclass.
- Add helper:

```text
add_to_pareto_pool(case, candidate)
dominates(a, b)
write_pareto_candidates_csv(...)
```

- Candidate enters pool only after ABC equivalence and ADP measurement.
- Use file references to temporary candidate AIGs.
- Always mark:
  - min area
  - min delay
  - min ADP
  - selected final

Log:

```text
student/logs/pareto_candidates.csv
```

Expected benefit:

- Better report support.
- Enables later structural choice and final selection beyond a single greedy
  best candidate.

Risk:

- Low if implemented as logging/selection support first.

### Phase 2: Cirbo-Style Exact Function Recognition

Goal:

- Replace hardcoded case-range assumptions with exact truth-table proof.

Current status:

- `student/boolean_fingerprint.py` already detects constants, buffer/inverter,
  affine/parity, symmetry, threshold-like, cube/decoder-like, comparator-like,
  mux-like, adder-like, and NPN templates for small support.
- `student/flow_optimizer.py` already has detectors for unsigned multiplier,
  signed multiplier, square, divider quotient, and integer sqrt.

Next implementation:

- Move arithmetic/template detectors into a shared exact-match module or expose
  a unified `exact_match_case` API.
- Add detectors for:
  - popcount output bits
  - comparator variants `>`, `>=`, `==`, `<`
  - adder sum/carry bits
  - divider remainder
  - modulo/remainder-like
  - sorting-network output bits
- Try input mappings:
  - first-half/second-half little endian
  - first-half/second-half big endian
  - reversed groups
  - even/odd interleaving
  - swapped operands
  - active-support-only variants

Log:

```text
student/logs/exact_function_matches.csv
```

Expected benefit:

- More architecture-level candidates.
- Stronger report story: every template is exact, not guessed.

Risk:

- Medium.  Detectors must be exact and bounded.

### Phase 3: Specialized Structural Generators

Goal:

- Generate structured candidates from exact matches before ABC/mockturtle
  minimization.

Candidate generators:

- affine/parity: XOR tree / XAG route
- comparator: prefix comparator
- popcount: balanced adder/compressor tree
- threshold/exact-k: popcount then compare
- multiplier: partial products + balanced compressor tree
- square: exploit symmetry
- divider/remainder/sqrt: only when exact match proves function
- one-hot/decoder/exact-one: factored SOP / exact-k

Log:

```text
student/logs/specialized_generators.csv
```

Expected benefit:

- Big gains when a truth table is a practical arithmetic/symmetric function.

Risk:

- High for complex multi-output generators.
- Mitigate by generating one output bit first, then expanding.

### Phase 4: Mockturtle Structural Resynthesis

Current status:

- Implemented and working.
- Current advanced structural pass reduced ADP from `11237685` to `11210243`
  while keeping 100/100 equivalence.

Next improvement:

- Split current `--mockturtle-structural` into:
  - first-pass structural mode
  - final-pass structural mode
  - explicit `--mockturtle-max-modes`
- Add per-mode summary:

```text
student/logs/mockturtle_structural_summary.csv
```

Expected benefit:

- Better mode pruning and reproducibility.

Risk:

- Low; current system already has safety checks.

### Phase 5: Small-Support Exact/NPN Rescue

Goal:

- Use exact/NPN synthesis where whole function or output support is small.

Implementation:

- For effective support <= 6:
  - use existing NPN canonical matching where available.
  - add direct template BLIF generation for matched functions.
- For effective support <= 7:
  - try mockturtle `exact_mc_synthesis` with conflict limit.
- For small cuts:
  - use mockturtle cut rewriting with exact/NPN resynthesis.

Log:

```text
student/logs/exact_npn_rescue.csv
```

Expected benefit:

- More improvements on small cases where ABC is already near local optimum.

Risk:

- Medium/high for exact synthesis runtime.
- Keep strict timeout and support-size guard.

### Phase 6: Transduction-Inspired Expansion/Reduction

Goal:

- Escape local optima using safe equivalent expansions followed by reduction.

Allowed expansions:

```text
f = (f & g) | (f & ~g)
f = (f | g) & (f | ~g)
f = mux(g, f, f)
f = ~~f
```

Reduction:

- mockturtle functional reduction
- cut rewriting
- resubstitution
- refactoring
- balancing
- small fixed ABC polish

CLI:

```text
--transduction-rescue
--transduction-budget N
--seed S
```

Log:

```text
student/logs/transduction_rescue.csv
```

Expected benefit:

- Potential escape hatch for cases that are stuck under direct rewriting.

Risk:

- Medium/high because expansions can increase size.
- Must be bounded and final ABC equivalence-gated.

### Phase 7: Complement Synthesis Wrapper

Current status:

- Some complement support already exists in candidate generation.

Next improvement:

- Normalize complement candidate logging across:
  - ABC truth
  - BDD/Shannon
  - SOP/POS/factored
  - specialized generator
  - XAG/MIG mockturtle route

Log:

```text
student/logs/complement_candidates.csv
```

Expected benefit:

- Some AIGs are smaller when synthesized as complement plus output inversion.

Risk:

- Low, because final equivalence check catches issues.

### Phase 8: Per-Case Fair Optimization

Current status:

- `--case-coverage-report`
- `--complete-all-cases`
- `--round-robin-optimize`
- `--score-aware-optimize`
- `--small-case-refine`

Next implementation:

- Add `--contest-optimize --seed 0 --time-budget <seconds>`.
- Combine existing coverage scheduler with:
  - exact matching
  - specialized generation
  - mockturtle structural
  - small exact/NPN
  - transduction rescue
  - complement candidates

Log:

```text
student/logs/contest_optimize_schedule.csv
student/logs/case_coverage.csv
```

Expected benefit:

- Prevents only large ADP cases from getting attention.

Risk:

- Low/medium; mostly scheduling around existing safe candidate checks.

### Phase 9: CLI Support

Commands to add or keep:

```bash
python3 student/flow_optimizer.py --write-contest-plan
python3 student/flow_optimizer.py --exact-match-all
python3 student/flow_optimizer.py --specialized-generate
python3 student/flow_optimizer.py --mockturtle-structural
python3 student/flow_optimizer.py --exact-npn-rescue
python3 student/flow_optimizer.py --transduction-rescue --transduction-budget 50 --seed 0
python3 student/flow_optimizer.py --try-complement
python3 student/flow_optimizer.py --contest-optimize --seed 0 --time-budget 3600
python3 student/flow_optimizer.py --reproduce-best
```

Do not break:

```bash
bash student/reproduce_best.sh
python3 student/flow_optimizer.py --reproduce-best
```

### Phase 10: Safety and Verification

Every phase must pass:

```bash
python3 -m py_compile student/flow_optimizer.py student/boolean_fingerprint.py
python3 evaluate.py --case ex200 --abc student/abc --benchmarks benchmarks --output output
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

Acceptance rules:

- `student/optimizer.py` must not be modified.
- No hardcoded final AIG outputs.
- No approximate candidate accepted.
- No candidate accepted without ABC equivalence.
- No overwrite unless ADP improves.
- If a mode fails, log and skip.

### Phase 11: Report Support

Target report-ready files:

```text
student/logs/pareto_candidates.csv
student/logs/exact_function_matches.csv
student/logs/specialized_generators.csv
student/logs/mockturtle_candidates.csv
student/logs/exact_npn_rescue.csv
student/logs/transduction_rescue.csv
student/logs/complement_candidates.csv
student/logs/case_coverage.csv
student/logs/final_summary.csv
```

Final summary should include:

- baseline ADP
- best ADP
- improvement ratio per case
- selected method per case
- number of cases improved by each method
- number of exact function matches
- number of mockturtle improvements
- number of small exact/NPN improvements
- number of transduction-inspired improvements
- final total ADP
- equivalence count

The submission reproduction pipeline also ends with a deterministic
micro-guided fixed-point convergence phase, so the late ADP reductions are
part of `bash student/reproduce_best.sh` rather than only existing in the
current ignored `output/` directory.

## Implementation Status

### Phase 1 Complete

- Added `ParetoCandidate` and Pareto-pool CSV generation in
  `student/flow_optimizer.py`.
- Wrote `student/logs/pareto_candidates.csv` from normal optimization and
  `--reproduce-best` runs.
- The pool is per-case and only includes equivalent candidates.
- It records true non-dominated area/delay points plus representative best
  candidates from key source families.
- Final output selection remains minimum ADP.

### Phase 2 Complete

- Added `student/exact_function_recognition.py`.
- Added `--exact-function-report` to write
  `student/logs/exact_function_matches.csv`.
- Added quick exact-match output to `--classify-case`.
- Detectors use complete truth-table equality for confidence `1.000`.
- Covered constants, buffer/inverter, affine/parity, symmetric threshold and
  exact-k, one-hot/decoder-like, popcount/sorter bits, comparator bits, adder
  bits, multiplier bits, square bits, divider quotient/remainder bits,
  modulo-like bits, and integer square-root bits.

### Phase 3 Complete

- Added exact-match structural generator support to `student/flow_optimizer.py`.
- New CLI:

```bash
python3 student/flow_optimizer.py --specialized-generators --case ex255
python3 student/flow_optimizer.py --specialized-generators --all
```

- New log:

```text
student/logs/specialized_generators.csv
```

- Implemented structural BLIF generation for:
  - complete affine/parity/simple-output functions
  - popcount output bits
  - threshold, exact-k, one-hot, and sorter output bits
  - unsigned adders and carry bits
  - unsigned comparators
  - exact whole-table multiplier, signed multiplier, square, divider quotient,
    and integer square-root structures
- Every candidate is still converted by ABC, checked for equivalence, measured
  by ADP, and accepted only if it improves current output.

### Phase 4 Complete

- Existing mockturtle structural resynthesis is now cleaner and more
  diagnosis-driven.
- `select_structural_mockturtle_modes` now accepts exact-match hints in
  addition to Boolean fingerprints.
- Added:

```bash
python3 student/flow_optimizer.py --mockturtle-structural --mockturtle-max-modes 3
```

- New summary log:

```text
student/logs/mockturtle_structural_summary.csv
```

- The summary records base/best area, delay, ADP, selected modes, exact type
  hints, generated candidate count, and equivalent candidate count.
- `--reproduce-best` remains unchanged and keeps the current deterministic
  safety contract.

### Phase 5 Complete

- Added exact small-support/NPN-style rescue to `student/flow_optimizer.py`.
- New CLI:

```bash
python3 student/flow_optimizer.py --exact-npn-rescue --case ex255 --npn-max-support 8
python3 student/flow_optimizer.py --exact-npn-rescue --all --npn-max-support 6
```

- New log:

```text
student/logs/exact_npn_rescue.csv
```

- The pass generates exact small-support BLIF candidates when the whole
  multi-output function support is within the support bound.  It can also
  report why a case is skipped when the support is too large.
- Candidates are reduced with a small fixed set of ABC flows, then accepted only
  after full equivalence and lower ADP.

### Phase 6 Complete

- Added bounded transduction-inspired expansion/reduction to
  `student/flow_optimizer.py`.
- New CLI:

```bash
python3 student/flow_optimizer.py --transduction-rescue --case ex200 --transduction-budget 12 --seed 0
python3 student/flow_optimizer.py --transduction-rescue --all --transduction-budget 12 --seed 0
```

- New log:

```text
student/logs/transduction_rescue.csv
```

- Implemented safe equivalent wrappers:
  - `(f & g) | (f & ~g)`
  - `(f | g) & (f | ~g)`
  - `mux(g, f, f)`
  - `~~f`
- Fixed BLIF continuation-line handling for ABC-generated `.inputs` and
  `.outputs` lines so wrapped multi-output BLIFs remain well-formed.
- Smoke test accepted one equivalent improvement:

```text
ex200: ADP 59534 -> 59517
```

- Full internal verification after the accepted replacement:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11210226
```

### Phase 7 Complete

- Added generic complement synthesis rescue.
- New CLI:

```bash
python3 student/flow_optimizer.py --complement-rescue --case ex200 --complement-budget 16
python3 student/flow_optimizer.py --complement-rescue --all --complement-budget 16
```

- New log:

```text
student/logs/complement_candidates.csv
```

- Complement candidates now include:
  - `abc_truth_complement`
  - BDD/Shannon complement variants when enabled
  - SOP/POS/factored complement variants
  - template/specialized complement variants when the complement truth table
    matches those generators
- Added `blif_complement` synthesis support so BLIF-based complement candidates
  can be optimized, output-inverted, and converted back to AIG.
- Updated BLIF output-inversion wrapper to handle ABC continuation lines in
  multi-line `.outputs` directives.

### Phase 8 Complete

- Added fair contest-style optimizer.
- New CLI:

```bash
python3 student/flow_optimizer.py --contest-optimize --seed 0 --time-budget 3600
```

- New log:

```text
student/logs/contest_optimize_schedule.csv
```

- The scheduler visits every selected case through staged rounds:
  1. exact matching
  2. base coverage with BDD/complement enabled
  3. complement rescue
  4. specialized structural generators
  5. mockturtle structural resynthesis when available
  6. exact/NPN rescue
  7. transduction rescue
- `case_coverage.csv` now also records whether exact matching, specialized
  generators, mockturtle, exact/NPN, and transduction have been tried.
- The scheduler is bounded by `--time-budget`, uses fixed seeds, logs every
  stage, and every replacement remains equivalence-gated.

### Phase 9 Complete

- Added CLI aliases requested by the contest plan:

```bash
python3 student/flow_optimizer.py --write-contest-plan
python3 student/flow_optimizer.py --exact-match-all
python3 student/flow_optimizer.py --specialized-generate --case ex255
```

- The aliases keep the existing commands working, so older workflows using
  `--exact-function-report` and `--specialized-generators` are unchanged.
- `--write-contest-plan` gives a stable command for locating this phase plan.

### Phase 10 Complete

- Added final-output verification entry point:

```bash
python3 student/flow_optimizer.py --verify-final
```

- This command reads the current `output/ex200.aig` through `output/ex299.aig`,
  checks each one against its truth table through ABC, refreshes
  `student/logs/results.csv`, `student/logs/summary.csv`, and
  `student/logs/pareto_candidates.csv`, then prints the equivalence count and
  total ADP.
- It does not modify final AIGs.

### Phase 11 Complete

- Added report-ready final summary generation:

```bash
python3 student/flow_optimizer.py --write-final-summary
```

- This runs the same final verification and also writes:

```text
student/logs/final_summary.csv
```

- The final summary includes per-case baseline/current ADP, improvement ratio,
  selected-method hints from logs, exact-match counts, method-level improvement
  counts, total ADP, and equivalent-case count.

## Next Step

All `AGENTS.md` implementation phases are now wired into the optimizer.  The
next practical optimization step is to run the case-fair refinement package:

```bash
python3 student/flow_optimizer.py --case-fair-next-optimize --all --seed 42 --timeout-per-case 30 --time-budget 3600
python3 student/flow_optimizer.py --write-final-summary
```

then use the refreshed CSVs and this plan in the final report.

## Post-Phase 11 Improvement Pass

Added a single-command deterministic refinement entry point:

```bash
python3 student/flow_optimizer.py --case-fair-next-optimize --all --seed 42 --timeout-per-case 30 --time-budget 3600
```

This pass is intended for the post-phase optimization loop after the
fingerprint/type-guided construction stages have already produced the current
outputs.  It visits every selected case and runs a balanced follow-up package:

1. objective-guided area/delay/balanced refinement
2. micro-guided refinement for near-converged circuits
3. small-case refinement for compact functions
4. complement rescue
5. optional mockturtle structural resynthesis only when `--try-mockturtle` is
   explicitly requested

Every replacement is still guarded by ABC equivalence and lower ADP.  The pass
writes:

```text
student/logs/case_fair_next_optimize.csv
student/logs/final_summary.csv
```

The package now treats `--timeout-per-case` as a total per-case budget, applies
`--time-budget` to the whole run, and checkpoints its CSV after each completed
case so an interrupted search does not lose the record.  It intentionally does
not recompute full truth-table fingerprints in this follow-up pass because
that analysis was already used upstream and can dominate runtime on large
cases.
