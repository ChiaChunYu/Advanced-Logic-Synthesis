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
15 deterministic stages covering hybrid synthesis, structural resynthesis
(ttopt, deepsyn, Pareto, mockturtle, Yosys hybrid), area-first refinement,
`&my_deepsyn` all-case sweep, and final convergence passes.

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
- interleaved micro-guided resubstitution and GIA canonical cleanup until no
  further ADP improvement (stage 15)

The pipeline runs **15 stages** in total.  Use `--show-reproduce-recipe` to
print the full stage list with parameters.

Stage 5 (`mockturtle_structural`) now includes `xag_xor_heavy` and
`roundtrip_xag` for all cases with large area, high ADP, or high delay (≥18
levels).  These XAG algebraic depth-rewriting modes reduce delay by 1–3 levels
on multi-output equal-width functions, yielding ADP gains of 5–10% on the
largest bottleneck cases.

## Final Verified Result

The current submitted outputs have been checked with `evaluate.py`:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 9963184
```

3 cases beat the reference result (ex276, ex280, ex272).

Development history, per-stage experiments, and prior result comparisons are
recorded separately in `student/OPTIMIZATION_LOG.md`.

## Implementation Files

The complete result is generated by these submitted source files:

```text
student/reproduce_best.sh               single reproduction command
student/flow_optimizer.py               deterministic optimization pipeline
student/boolean_fingerprint.py          truth-table structure analysis
student/exact_function_recognition.py   exact template detection
student/mockturtle_opt/                 mockturtle structural resynthesis tool
student/area_first_experiment.py        standalone area-first experiment script
```

`student/optimizer.py` is retained only as the provided baseline; it is not
called by the final reproduction command.  `student/area_first_experiment.py`
is the standalone experiment script used to develop the area-first flows; its
logic is incorporated into `flow_optimizer.py` stage 13 for reproducibility.
Development history is documented separately in `student/OPTIMIZATION_LOG.md`.

Report-ready logs are written under `student/logs/`, including:

```text
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
