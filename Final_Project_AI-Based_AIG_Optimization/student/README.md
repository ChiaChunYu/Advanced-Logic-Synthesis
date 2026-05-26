# Hybrid AIG Optimizer

This directory contains the submitted optimizer for the AI-Based AIG
Optimization final project.

## Files

- `optimizer.py`: original baseline optimizer, kept unchanged.
- `flow_optimizer.py`: current hybrid structural optimizer.
- `boolean_fingerprint.py`: truth-table feature extraction and classification.
- `exact_function_recognition.py`: exact function/template recognition.
- `reproduce_best.sh`: deterministic full regeneration command.
- `OPTIMIZATION_LOG.md`: development history and per-update experiment record.

## Objective And Safety

For every benchmark `benchmarks/ex200.truth` through `benchmarks/ex299.truth`,
the optimizer produces `output/exNNN.aig` and minimizes:

```text
ADP = area * delay
```

Correctness is mandatory. Every replacement candidate is checked against the
original truth table using ABC equivalence checking. A candidate replaces the
current output only when:

```text
equivalent == true and candidate_ADP < current_ADP
```

No benchmark-specific final AIG is hardcoded, and `student/optimizer.py` is not
modified.

## Current Optimization Framework

The current optimizer is a hybrid synthesis pipeline. It does not depend on
one ABC flow or random command sweeping.

### 1. Function Analysis

`boolean_fingerprint.py` analyzes each truth table before selecting candidate
structures:

- effective support and input influence
- density, monotonicity, symmetry, and Shannon split behavior
- ANF degree and small-function templates
- circuit-type hints such as affine/parity, threshold, mux-like, comparator,
  arithmetic-like, and general multi-output logic

### 2. Multiple Initial Structures

`flow_optimizer.py` constructs several structurally different initial
candidates:

- ABC truth-table baseline synthesis
- SOP/POS and factored SOP construction
- Shannon/BDD construction with several deterministic variable orderings
- complement-first synthesis
- exact recognized templates for affine, popcount/threshold, comparator,
  adder, multiplier, square, divider quotient, and integer square-root
  functions
- optional mockturtle structural candidates for AIG/XAG/MIG/XMG-oriented
  rewriting

### 3. Truth-Table Structural Resynthesis

The main architecture-level addition is ABC `&ttopt` structural synthesis:

```text
truth table -> shared BDD/MUX-style AIG -> ABC polish -> equivalence/ADP selection
```

For practical multi-output functions, `&ttopt` generates a new network from
the full truth table instead of only rewriting an existing AIG. The optimizer:

- derives legal output-group sizes from each function's output count
- tries fixed, deterministic `&ttopt` configurations
- applies a small ADP-oriented polish set
- applies level-preserving `&transduction -T 1 -l` to improved structures
- for compact equal-width networks, also tries repeated level-preserving
  `&transduction -T 4 -l`

This structural route produced the largest improvements in the current result,
including practical-function and LogicNets-style cases.

### 4. Bounded Deep Structural Resynthesis

For high-cost multi-output functions and 16-input/8-output dropped-output
practical-function shapes, the optimizer also uses ABC `&deepsyn`:

```text
current equivalent AIG -> fixed-seed LUT map/unmap resynthesis -> ABC polish
                         -> equivalence/ADP selection
```

This stage is deterministic (`seed=42`) and bounded to up to two passes of one
30-second structural iteration per selected case, stopping when a pass makes
no improvement.  For the dropped-output practical
shape it additionally tries the two-input LUT structural mode.  It is not a
random command sweep: candidates are new structures produced by LUT
decomposition and re-synthesis, and each is independently checked for
equivalence before replacement.

### 5. Yosys And mockturtle Hybrid Resynthesis

The latest structural stage mixes the installed Yosys and mockturtle engines
without accepting unverified rewrites:

```text
current AIG -> ABC symbol-free AIGER bridge -> Yosys AIG remap
            -> fixed ABC polish -> optional fingerprint-selected mockturtle
            -> fixed ABC polish -> equivalence/ADP selection
```

The symbol-free bridge is required because a direct Yosys AIGER round trip
reorders the named primary inputs in these benchmark files.  Removing symbols
before Yosys preserves the positional interface checked against the truth
table.

Yosys uses one fixed `abc -g aig` structural remap.  mockturtle is only
invoked from an improved Yosys seed and only in modes selected by the
fingerprint classifier.  Independent mockturtle candidates can be generated
in parallel with `--mockturtle-workers N`; the candidate order and final
selection remain deterministic.

### 6. Final ADP Refinement

Equivalent candidates are compared by ADP. Selected outputs may then receive
fixed deterministic refinement packages:

- area-oriented, delay-oriented, and balanced ABC polishing
- micro-guided refinement for compact or nearly converged circuits
- final fixed-point convergence passes

The optimizer always retains the lower-ADP equivalent output.

## Current Verified Result

The current `output/` directory was verified with:

```bash
python3 student/flow_optimizer.py --write-final-summary \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs
```

Verified result:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10667043
```

Representative improvements from the structural synthesis paths:

```text
ex242: 50578  -> 30096
ex243: 99940  -> 82016
ex250: 73524  -> 63525
ex251: 117306 -> 85316
ex252: 234186 -> 51714
ex280: 25056  -> 15680
ex281: 31980  -> 22057
ex282: 38283  -> 30696
ex284: 57122  -> 41300
ex287: 33462  -> 25023
ex243: 82016  -> 71106
ex250: 63525  -> 51568
ex251: 85316  -> 64932
ex252: 51714  -> 43550
ex253: 7707   -> 3634
ex243: 71106  -> 63000
ex250: 51568  -> 51436
ex251: 64932  -> 64722
ex298: 540708 -> 518640
ex299: 2711688 -> 2708256
```

The later `ex243` and `ex250`-`ex253` improvements above came from bounded
`&deepsyn` plus final micro refinement.  The final `ex243`, `ex250`, `ex251`,
`ex298`, and `ex299` reductions include the Yosys/mockturtle hybrid seed and
its deterministic final cleanup.  The detailed history is recorded in
`OPTIMIZATION_LOG.md`,
not in this README.

## Reproduce The Result

Run commands from the project root in Linux or WSL because `student/abc` is a
Linux executable.

### Full Deterministic Regeneration

The full pipeline entry point is:

```bash
bash student/reproduce_best.sh
```

It runs the deterministic synthesis recipe, writes AIG files to `output/`, and
then runs the evaluator. The complete flow is intentionally long because it
includes all-case synthesis, structural resynthesis, equivalence checks, and
final convergence passes.  The recipe includes the adaptive bounded
`&deepsyn` stage for remaining expensive multi-output structures and the safe
Yosys/mockturtle hybrid structural stage.

To inspect the fixed recipe:

```bash
python3 student/flow_optimizer.py --show-reproduce-recipe
```

### Verify Existing Generated Outputs

To verify already generated `output/exNNN.aig` files:

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

To refresh the report-oriented summary:

```bash
python3 student/flow_optimizer.py --write-final-summary \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs
```

### Run The New Structural Stage Alone

To apply only the current truth-table structural resynthesis method on existing
outputs:

```bash
python3 student/flow_optimizer.py --ttopt-structural --all \
  --timeout-per-case 150 \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs

python3 student/flow_optimizer.py --micro-guided-refine --all \
  --micro-max-flows 4 --timeout-per-case 30 \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs

python3 student/flow_optimizer.py --deepsyn-structural --range ex250 ex254 \
  --seed 42 --deepsyn-iterations 1 --deepsyn-seconds 30 \
  --timeout-per-case 100 \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs

python3 student/flow_optimizer.py --hybrid-structural --all \
  --yosys-bin yosys --mockturtle-workers 2 --mockturtle-max-modes 2 \
  --timeout-per-case 90 \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs

python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

This incremental command sequence is useful when `output/` already contains
the previous best equivalent AIGs. It is not a from-scratch replacement for
`reproduce_best.sh`.

## Output And Logs

Required submission outputs:

```text
output/ex200.aig ... output/ex299.aig
```

Main report files:

```text
student/logs/results.csv
student/logs/summary.csv
student/logs/final_summary.csv
student/logs/ttopt_structural.csv
student/logs/deepsyn_structural.csv
student/logs/hybrid_structural.csv
student/logs/classification.csv
student/logs/exact_function_matches.csv
```

`ttopt_structural.csv` records the new architecture-level candidate search:

```text
case,input_support,output_group,rounds,flow_name,flow_commands,
generated,equivalent,area,delay,adp,improved,selected,error
```

`deepsyn_structural.csv` records the fixed-seed LUT map/unmap candidates:

```text
case,variant,seed,iterations,search_seconds,flow_name,flow_commands,
generated,equivalent,area,delay,adp,improved,selected,error
```

`hybrid_structural.csv` records safe Yosys remaps and conditional
Yosys-then-mockturtle candidates:

```text
case,chain,mode,flow_name,flow_commands,generated,equivalent,
area,delay,adp,improved,selected,error
```

## Useful Diagnostic Commands

```bash
python3 student/flow_optimizer.py --classify-case ex200
python3 student/flow_optimizer.py --exact-function-report --all
python3 student/flow_optimizer.py --diagnose-results
python3 student/flow_optimizer.py --ablation-report
python3 student/flow_optimizer.py --case-coverage-report
```

These commands produce analysis logs; they are not required to generate final
AIG outputs.
