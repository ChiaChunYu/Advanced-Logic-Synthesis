# Hybrid AIG Optimizer

This directory contains the submitted optimizer for the AI-Based AIG
Optimization final project.

## What To Run

Use this command to regenerate all submitted AIGs and verify them:

```bash
bash student/reproduce_best.sh
```

`reproduce_best.sh` is the single reproduction entry point.  It checks the
required tools, builds the mockturtle helper if needed, invokes:

```bash
python3 student/flow_optimizer.py --reproduce-best \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output \
  --logs student/logs
```

and then runs:

```bash
python3 evaluate.py \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output
```

`flow_optimizer.py` contains the actual optimization implementation.
Individual `flow_optimizer.py` options are useful for analysis and testing a
single stage, but `reproduce_best.sh` is the command to use for complete
result reproduction.

Complete regeneration is intentionally long-running: the pipeline runs
the deterministic core stages plus targeted verified cleanup stages covering
hybrid synthesis, structural resynthesis
(ttopt, deepsyn, Pareto, mockturtle, Yosys hybrid), area-first refinement,
`&my_deepsyn` all-case sweep, case-fair final refinement, and final
convergence passes.

## Required Environment

Run the project in Linux or WSL because `student/abc` is a Linux executable.

Required tools:

```text
python3
yosys
student/abc
```

When `student/mockturtle_opt/mockturtle_opt` is not already built, complete
regeneration also requires:

```text
cmake
a C++ compiler
student/mockturtle_src/
```

## Objective And Safety

For each truth table from `benchmarks/ex200.truth` through
`benchmarks/ex299.truth`, the optimizer generates:

```text
output/ex200.aig ... output/ex299.aig
```

The objective is:

```text
ADP = area * delay
```

Every candidate must pass ABC equivalence checking against its original truth
table.  A generated AIG replaces the current output only when it is:

```text
equivalent and lower in ADP
```

`student/optimizer.py` is the original baseline and remains unchanged.  The
submission does not hardcode final benchmark AIG answers.

## Current Optimization Method

The submitted method is a deterministic hybrid structural synthesis pipeline.
It constructs and tests several equivalent network representations, then
keeps the lowest-ADP verified result.

### 1. Boolean Function Analysis

`boolean_fingerprint.py` and `exact_function_recognition.py` analyze truth
tables to identify useful structure:

- effective support, input influence, density, monotonicity, and symmetry
- Shannon decomposition behavior and ANF properties
- exact recognized templates such as affine/parity, threshold/popcount,
  comparator, adder, multiplier, square, divider quotient, and integer square
  root when proven by the truth table
- refined case-level labels for monotone-positive general logic and
  mixed constant-output functions; these prevent visually similar
  general-random cases from all using the same ABC strategy package
- semantic class-split reconstruction for float-like and unknown cases:
  candidate class variables model sign/exponent/high-byte selectors, and each
  class synthesizes only the residual mantissa/low-bit function
- field-pair semantic reconstruction for 16-bit conversion/unknown functions:
  paired high-nibble and paired low-nibble splits model circuits whose two
  logical operands are packed into the high and low byte fields.  This gives a
  different front-end topology from a plain byte split and is logged separately
  as `float_pair_high_nibbles` / `float_pair_low_nibbles`.
- shared-cofactor semantic reconstruction: class-split BLIF generation caches
  residual BDDs across all outputs and all class values.  Duplicate residual
  cofactors are emitted once, and complemented cofactors reuse the cached
  signal through a single inverter.  This targets multi-output functions whose
  outputs are not equal globally but share many local decision subfunctions.
- shared multi-output decision graphs: semantic reconstruction also tries
  global BDD candidates where all outputs share one decision-node cache under
  several deterministic variable orders.  This is aimed at the
  `ex280-ex299` unknown-function group described as class/rotation/split
  structured in `introduction.html`.

### 2. Initial Structural Candidates

`flow_optimizer.py` generates structurally different candidates from:

- ABC truth-table synthesis
- SOP/POS and factored SOP forms
- Shannon/BDD structures with deterministic variable orders
- complement-first synthesis
- exact specialized templates when an exact function match is available

### 3. Structural Resynthesis Engines

The pipeline then attempts deterministic architecture-level transformations:

- fingerprint-selected mockturtle AIG/XAG/MIG/XMG resynthesis
- ABC `&ttopt` truth-table structural synthesis with level-preserving
  transduction
- bounded fixed-seed ABC `&deepsyn` LUT map/unmap resynthesis
- fixed-seed ABC `&my_deepsyn -C area` Pareto resynthesis for large
  equal-width multi-output area bottlenecks
- low-ANF-degree vector-function detection followed by iterative Pareto
  structural resynthesis for compact LogicNets-style functions
- an adaptive compact-vector probe that expands structural budget only after
  an equivalent lower-ADP probe candidate is found
- long-running large-vector rescue: a new `&ttopt` shared-topology seed is
  synthesized from the truth table, then optimized by fixed-seed
  area-Pareto search and DSD balancing; longer refinement is spent only on
  topology seeds whose bounded probe already lowers verified ADP
- safe Yosys-to-mockturtle hybrid resynthesis
- area-first refinement: area-aggressive flows (`resub -K 10`, `dc2` loops,
  `fraig`, `dch; if -K 3/4`, GIA `compress2rs`, `&sopb -C 16 -R 1`,
  `&b -d -s`) applied to all cases, plus two fresh truth-table re-synthesis
  candidates; accepts only equivalence-checked strict ADP decreases
- `&my_deepsyn -C area` all-case Pareto sweep: runs on every case with
  area ≥ 500, covering LogicNets-style compact functions that benefit from
  structural-restart search

For the Pareto structural stages, the optimizer measures every generated
frontier AIG after fixed cleanup and selects by ADP.  It does not assume that
the smallest-area frontier point is the best submitted point.

The area-first refinement stage (stage 13) runs before the final convergence
pass.  It is also available as a standalone command:

```bash
python3 student/flow_optimizer.py --area-first-refine --all \
  --abc student/abc --benchmarks benchmarks --output output \
  --logs student/logs --timeout-per-case 90
```

The Yosys hybrid route uses:

```text
current AIG
  -> ABC symbol-free AIGER bridge
  -> Yosys AIG remap
  -> fixed ABC polish
  -> fingerprint-selected mockturtle resynthesis, when useful
  -> fixed ABC polish
  -> equivalence and ADP selection
```

The symbol-free bridge preserves primary-input ordering when AIGER files pass
through Yosys.  Independent mockturtle candidate generations may run in
parallel, but selection remains deterministic and equivalence gated.

### 4. Final Deterministic Refinement

After structural candidates settle:

- area-first flows (`resub -K 10`, `dc2` loops, `fraig`, `dch; if -K 3/4`,
  GIA `compress2rs`, `&sopb`, `&b -d -s`) and two fresh truth-table
  re-synthesis candidates are tried on every case (stage 13)
- `&my_deepsyn -C area` Pareto sweep on all cases with area ≥ 500 (stage 14)
- case-fair final refinement gives every case the same objective/micro/small/
  complement package before final convergence (stage 15)
- interleaved micro-guided resubstitution and GIA canonical cleanup until no
  further ADP improvement (stage 16)
- targeted 1.5x-ratio push refinement revisits cases that stayed above the
  reference-ratio threshold during experiments, using the same
  equivalence-gated area/type/objective/micro/GIA package that produced the
  current outputs (stage 17)
- type-guided refinement distinguishes monotone-positive general logic from
  true threshold/majority logic.  This is important for cases such as ex250
  and ex286, where symmetry groups exist but the outputs are not simple
  threshold functions; they now try a separate monotone delay/area flow
  package.  Mixed constant-output cases such as ex252 use a constant-aware
  flow family instead of the generic package.
- exact signed multiplier reconstruction now includes a carry-save correction
  template.  Instead of building an unsigned multiplier followed by two
  ripple sign-correction subtractors, the sign-extension correction terms are
  compressed together with the partial products.  This gives a distinct
  low-delay Pareto seed for signed multiplier cases such as ex262-ex264.
- factored SOP emission now preserves don't-care literals introduced during
  recursive factoring.  This keeps front-end BLIF reconstruction faithful to
  the intended cover before ABC cleanup and CEC selection.
- class-split BLIFs now report `shared_cofactors`, `reused`, and
  `complemented` in `student/logs/semantic_split_candidates.csv`, making the
  front-end sharing effect auditable and reproducible.

The core pipeline is followed by deterministic targeted cleanup stages in
`reproduce_best.sh`.  Use `--show-reproduce-recipe` to print the core stage
list with parameters.

After the core pipeline, these additional stages run automatically:

- **Stage 18** (`flow_optimizer.py --semantic-split-optimize`): deterministic
  semantic front-end reconstruction on representative float/arithmetic
  bottlenecks.  It tries per-output hybrid BDDs, exponent/class split BLIF
  structures, and paired-nibble field splits for 16-bit conversion/unknown
  circuits.  It also tries global shared multi-output BDDs before the class
  split candidates.  The wider `--semantic-max-splits 8` setting is intentional: it
  allows the paired-field candidates to be reached after the classic
  exponent/high-byte/low-byte candidates.  The `--semantic-max-flows 4`
  setting includes the GIA cleanup pass, which is often the strongest cleanup
  for shared-cofactor BLIFs.  All equivalent candidates are recorded in
  `student/logs/semantic_split_candidates.csv`; only strict ADP decreases are
  copied into `output/`.
- **Stage 19** (`flow_optimizer.py --circuit-type-optimize`): deterministic
  circuit-family refinement on the structurally ambiguous bottleneck set
  (`ex223`, `ex225`, `ex250`, `ex252`, `ex262`, `ex263`, `ex264`, `ex286`,
  `ex297`, `ex299`).  Each case is fingerprinted first, then optimized with
  a family-specific mix of current-AIG polish flows and truth-table BDD seeds.
  This stage records every accepted and rejected candidate in
  `student/logs/circuit_type_optimize.csv`.
- **Stage 20** (`refine_close.py`): parallel ABC flow search
  (`&resyn3rs`, `&sopb`, `resub -K N`, `dch+if`, `&compress2rs`, etc.)
  applied to every case above the reference ADP.  Each case iterates
  until no flow yields a strictly lower verified ADP.  Its temporary
  directory is derived from Python's platform temp directory so the same
  script works in both `/tmp`-based Unix shells and Windows Python setups.
- **Stage 21** (`reproduce_top3.sh`): re-seeds ex272/ex276/ex280 from
  the current output and re-verifies the top-3 improvements.
- **Stage 22** (`flow_optimizer.py --case ex295 --case-fair-next-optimize`):
  targeted final cleanup for the newly verified ex295 improvement.  The
  accepted candidate is produced by the objective-guided balanced/dchoice
  package and kept only after equivalence and strict ADP checks.
- **Stage 23** (`refine_close.py --cases ...`): targeted post-hoc cleanup for
  the late verified improvements on `ex262`, `ex265`, `ex266`, `ex275`,
  `ex277`, `ex278`, `ex284`, and `ex295`.  It reruns each case independently
  to avoid cross-case file races and keeps only CEC-checked strict ADP
  decreases.
- **Stage 24** (`deep_area_opt.py`): area-first `&my_deepsyn` pass for
  high-ratio cases.  It writes to `output/` only after strict verified ADP
  improvement.
- **Stage 25** (`refine_close.py --cases ex219 ex247 ex261`): cleanup after
  the area-first pass exposes new local minima.
- **Stage 26** (`specialized_semantic_generators.py --case ex261` plus
  `refine_close.py --cases ex261`): decoded semantic probe and final ex261
  cleanup.

Stage 5 (`mockturtle_structural`) now includes `xag_xor_heavy` and
`roundtrip_xag` for all cases with large area, high ADP, or high delay (≥18
levels).  These XAG algebraic depth-rewriting modes reduce delay by 1–3 levels
on multi-output equal-width functions, yielding ADP gains of 5–10% on the
largest bottleneck cases.

## Final Verified Result

The current submitted outputs have been checked with `evaluate.py`:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 8892765
```

The latest per-case comparison is written to
`student/logs/current_results_with_reference_updated.csv`.
`current_results_with_reference.csv` may be locked by spreadsheet/IDE preview
tools on Windows; the updated copy under `student/logs/` is kept so result
regeneration is still auditable.
The reference comparison baseline remains at project root as
`reference_result.csv`.

| Case  | My ADP  | Ref ADP | Ratio  |
|-------|--------:|--------:|-------:|
| ex276 |     576 |     632 | 0.9114 |
| ex284 |   3,952 |   4,240 | 0.9321 |
| ex265 |     308 |     322 | 0.9565 |
| ex280 |   2,310 |   2,415 | 0.9565 |
| ex272 |  10,507 |  10,880 | 0.9657 |
| ex287 |   5,586 |   5,782 | 0.9661 |
| ex231 |  13,740 |  14,066 | 0.9768 |
| ex207 | 614,916 | 627,817 | 0.9795 |
| ex227 | 708,377 | 721,639 | 0.9816 |

Development history, per-stage experiments, and prior result comparisons are
recorded separately in `student/OPTIMIZATION_LOG.md`.

## Implementation Files

The complete result is generated by these submitted source files:

```text
student/reproduce_best.sh               single reproduction command
student/flow_optimizer.py               deterministic optimization pipeline
student/boolean_fingerprint.py          truth-table structure analysis
student/exact_function_recognition.py   exact template detection
student/deep_area_opt.py                verified high-ratio area-first cleanup
student/specialized_semantic_generators.py
                                         decoded semantic cleanup candidates
student/refine_close.py                 post-hoc ABC flow refinement
student/reproduce_top3.sh               top-3 seed verification
student/mockturtle_opt/                 mockturtle structural resynthesis tool
```

`student/optimizer.py` is retained only as the provided baseline; it is not
called by the final reproduction command.

Exploratory scripts are intentionally separated under:

```text
student/experiment/
```

Those scripts document failed probes and focused searches used during
development, but the final reproduction command does not depend on them.
Development history is documented separately in `student/OPTIMIZATION_LOG.md`.

Report-ready logs are written under `student/logs/`, including:

```text
current_results.csv
current_results_with_reference_updated.csv
results.csv
summary.csv
final_summary.csv
classification.csv
exact_function_matches.csv
ttopt_structural.csv
deepsyn_structural.csv
pareto_area_structural.csv
long_large_structural.csv
gia_canonical_convergence.csv
hybrid_structural.csv
```

## Verification Only

To verify existing generated outputs without rerunning optimization:

```bash
python3 evaluate.py \
  --abc student/abc \
  --benchmarks benchmarks \
  --output output
```

To inspect the deterministic stages executed by the reproduction command:

```bash
python3 student/flow_optimizer.py --show-reproduce-recipe
```
