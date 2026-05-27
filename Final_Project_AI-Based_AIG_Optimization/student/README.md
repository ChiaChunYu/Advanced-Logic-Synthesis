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

Complete regeneration is intentionally long-running: the final method
includes bounded fixed-point Pareto structural passes for compact vector
functions and adaptive follow-up only for probe cases that first improve.

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
- safe Yosys-to-mockturtle hybrid resynthesis

For the Pareto structural stages, the optimizer measures every generated
frontier AIG after fixed cleanup and selects by ADP.  It does not assume that
the smallest-area frontier point is the best submitted point.

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

After structural candidates settle, fixed area-oriented, delay-oriented, and
balanced ABC refinement packages are tried.  A final micro-guided fixed-point
pass retains only verified ADP decreases.

## Final Verified Result

The current submitted outputs have been checked with `evaluate.py`:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10449199
```

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
```

`student/optimizer.py` is retained only as the provided baseline; it is not
called by the final reproduction command.  Development history is documented
separately in `student/OPTIMIZATION_LOG.md`.

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
