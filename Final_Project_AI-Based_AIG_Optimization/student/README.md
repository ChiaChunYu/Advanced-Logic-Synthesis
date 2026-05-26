# Hybrid Flow Optimizer Usage

This folder keeps the original baseline optimizer and the improved optimizer
separate.

## Files

- `optimizer.py`: original baseline script. It is kept unchanged as the simple
  reference implementation.
- `flow_optimizer.py`: hybrid AIG optimizer. It tries multiple initial synthesis
  strategies, runs ABC post-optimization, checks equivalence, and keeps the
  equivalent candidate with the lowest ADP.

## Optimization Strategy

`flow_optimizer.py` uses several initial construction methods before ABC
optimization:

- ABC baseline synthesis from `read_truth -xf`.
- Support reduction by detecting zero-influence variables during custom
  synthesis.
- SOP construction for sparse functions.
- POS-style construction for dense functions by synthesizing the off-set and
  inverting the output.
- Shannon/BDD-style construction with multiple variable orderings, including
  original order, high-influence-first, low-influence-first,
  balanced-Shannon-score-first, and deterministic random orders.
- Boolean fingerprinting and circuit-type classification to infer constants,
  affine/parity, symmetric/threshold, mux-like, comparator-like, arithmetic-like,
  and small-support NPN-template functions.
- Structural arithmetic template synthesis for exact unsigned multipliers,
  signed two's-complement multipliers, unsigned squarers, unsigned divider
  quotient functions, and unsigned integer square-root functions.  These cases
  are generated from arithmetic structures
  before ABC post-optimization, so the initial circuit is no longer the generic
  `read_truth -xf` result.
- Truth-table structural resynthesis through ABC `&ttopt` for practical
  multi-output functions.  This creates a new shared BDD/MUX-style structure
  from the full truth table, then applies deterministic level-preserving
  `&transduction`; compact equal-width networks may receive a repeated
  transduction pass before ADP selection.
- Selector-reduction BDD ordering for mux-like functions, based on Shannon
  cofactor support reduction.
- Recursive factoring of SOP cubes when the cover is small enough.
- Deterministic GA-generated ABC post-optimization flows using insert, delete,
  replace, swap, and crossover mutations over ABC commands.
- Iterative in-place polish passes using equivalence-checked cleanup,
  `dch/if/strash`, `fraig`, `resub` parameter variants, `orchestrate`,
  `dchoice/ifraig`, GIA `&resyn3rs`, and rewrite/refactor loops.
- Fingerprint-guided mockturtle structural resynthesis.  The optimizer selects
  at most two structural modes per case, such as XAG rewriting for XOR-heavy
  logic, MIG rewriting for majority/threshold logic, XMG rewriting for mixed
  arithmetic logic, and AIG resubstitution/functional reduction for general
  high-area logic.  It also includes structural cut rewriting, don't-care AIG
  rewriting, XAG multiplicative-complexity reduction, Akers-style MIG cut
  rewriting, and mixed XMG resubstitution.  Each mockturtle candidate is still
  polished and verified by ABC before it can replace an output.
- Pareto frontier tracking for equivalent candidates by area and delay.

Each initial circuit is written as BLIF or generated through ABC, then optimized
with several post-flows such as area-oriented, delay-oriented, ADP-balanced,
LLM-inspired, and GA-generated ABC command sequences.  A candidate is selected
only if ABC proves it equivalent to the original truth table.

## Basic Commands

Run one benchmark:

```bash
python3 student/flow_optimizer.py --case ex200
python3 evaluate.py --case ex200
```

Run all 100 benchmarks:

```bash
python3 student/flow_optimizer.py --all
python3 evaluate.py
```

Run the current best reproducible flow:

```bash
bash student/reproduce_best.sh
```

This is the preferred one-command reproduction entry point.  It runs the fixed
deterministic recipe, verifies all 100 final outputs, and rewrites
`student/logs/results.csv`, `student/logs/summary.csv`, and
`student/logs/reproduce_recipe.txt`.

```bash
python3 student/flow_optimizer.py --show-reproduce-recipe
```

The recipe is fixed, not a random command sweep:

- all-case hybrid synthesis with seed `42`
- focused arithmetic template ranges
- focused divider and square-root template ranges
- diagnosis-driven rescue for known sensitive cases
- equivalence-checked polish packages
- deterministic all-case refinement packages
- fingerprint-guided mockturtle structural resynthesis
- final type-guided circuit-family refinement for every case
- final objective-guided area/delay/balanced refinement for every case
- micro-guided per-case refinement for small and stubborn cases
- small-case targeted refinement for compact or low-ADP functions
- final advanced mockturtle structural refinement on the fully refined outputs
- truth-table structural resynthesis with `&ttopt` followed by deterministic
  level-preserving transduction, with repeated rewiring for compact
  equal-width networks
- final deterministic micro-guided fixed-point convergence passes

The old experimental subcommands are still available for research, but the
submission flow should use `bash student/reproduce_best.sh`.

For the largest arithmetic-template gains, the following focused ranges are
included in the current best recipe and are also useful during experimentation:

```bash
python3 student/flow_optimizer.py --range ex255 ex259 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex260 ex264 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex265 ex269 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex270 ex274 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex275 ex279 --max-candidates 80 --no-ga
python3 evaluate.py
```

Run a smaller inclusive range for testing:

```bash
python3 student/flow_optimizer.py --range ex200 ex209
```

Run the new truth-table structural synthesis stage alone:

```bash
python3 student/flow_optimizer.py --ttopt-structural --all --timeout-per-case 150
python3 evaluate.py
```

The stage uses only legal output-group sizes for each truth table, verifies
every generated AIG with ABC, and never replaces a current output unless ADP
strictly decreases.

Latest verified result after this structural stage and deterministic polish:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10771329
```

Analyze a benchmark without generating an AIG:

```bash
python3 student/flow_optimizer.py --analyze-case ex200
```

Run precise Boolean fingerprinting/classification without generating an AIG:

```bash
python3 student/flow_optimizer.py --classify-case ex200
```

Write exact, proof-based function matches without generating an AIG:

```bash
python3 student/flow_optimizer.py --exact-function-report --case ex200
python3 student/flow_optimizer.py --exact-function-report --all
python3 student/flow_optimizer.py --exact-match-all
```

This writes `student/logs/exact_function_matches.csv`.  Matches have
confidence `1.000` only when the detector checks the complete truth table.

Run exact-match structural generators:

```bash
python3 student/flow_optimizer.py --specialized-generators --case ex255
python3 student/flow_optimizer.py --specialized-generators --all --timeout-per-case 120
python3 student/flow_optimizer.py --specialized-generate --case ex255
```

This pass uses exact function matches to build structural BLIF candidates such
as affine/XOR trees, popcount/threshold/sorter structures, adders,
comparators, multipliers, squares, divider quotients, and integer square-root
structures.  Every generated candidate is converted by ABC, checked for
equivalence, measured by ADP, and accepted only if it improves the current
output.  Logs are written to `student/logs/specialized_generators.csv`.

Run small-support exact/NPN-style rescue:

```bash
python3 student/flow_optimizer.py --exact-npn-rescue --case ex255 --npn-max-support 8
python3 student/flow_optimizer.py --exact-npn-rescue --all --npn-max-support 6
```

This pass generates exact small-support covers when the whole function is small
enough, then applies a bounded set of reductions.  It writes
`student/logs/exact_npn_rescue.csv` and only accepts equivalent lower-ADP
candidates.

Run bounded transduction-inspired expansion/reduction:

```bash
python3 student/flow_optimizer.py --transduction-rescue --case ex200 --transduction-budget 12 --seed 0
python3 student/flow_optimizer.py --transduction-rescue --all --transduction-budget 12 --seed 0
```

This pass wraps existing outputs in safe identities such as
`(f & g) | (f & ~g)` or `~~f`, then lets ABC reduction try to recover a better
structure.  It writes `student/logs/transduction_rescue.csv`.

Run generic complement synthesis rescue:

```bash
python3 student/flow_optimizer.py --complement-rescue --case ex200 --complement-budget 16
python3 student/flow_optimizer.py --complement-rescue --all --complement-budget 16
```

This pass synthesizes the complement function through ABC/BDD/SOP/template
routes, wraps the outputs back to the original polarity, and accepts only
equivalent lower-ADP candidates.  It writes
`student/logs/complement_candidates.csv`.

Run the fair contest-style scheduler:

```bash
python3 student/flow_optimizer.py --contest-optimize --seed 0 --time-budget 3600
```

This scheduler visits every selected case in staged rounds: exact matching,
base coverage, complement rescue, specialized generation, mockturtle structural
resynthesis, exact/NPN rescue, and transduction rescue.  It writes
`student/logs/contest_optimize_schedule.csv` and refreshes
`student/logs/case_coverage.csv`.

Run the next deterministic case-fair improvement package:

```bash
python3 student/flow_optimizer.py --case-fair-next-optimize --all --seed 42 --timeout-per-case 30 --time-budget 3600
python3 student/flow_optimizer.py --case-fair-next-optimize --case ex200 --timeout-per-case 120 --time-budget 180
```

This is a single-command follow-up refinement pass for outputs already created
by the fingerprint/type-guided main pipeline.  To remain practical on all 100
cases, it reuses those typed outputs instead of recomputing expensive full
fingerprints, then tries objective-guided, micro-guided, small-case,
complement, and optional mockturtle structural rescue stages.  Each
stage still overwrites `output/exNNN.aig` only when ABC proves equivalence and
the ADP is lower.  It writes `student/logs/case_fair_next_optimize.csv`, then
refreshes `results.csv`, `summary.csv`, `pareto_candidates.csv`, and
`final_summary.csv`. `--timeout-per-case` bounds the complete package for one
case and `--time-budget` bounds the complete invocation; progress is saved
after each completed case.

Mockturtle is opt-in for this final follow-up pass because its structural mode
selection repeats fingerprint analysis:

```bash
python3 student/flow_optimizer.py --case-fair-next-optimize --case ex200 --try-mockturtle --timeout-per-case 120 --time-budget 180
```

Write or locate the contest plan and refresh final verification logs:

```bash
python3 student/flow_optimizer.py --write-contest-plan
python3 student/flow_optimizer.py --verify-final
python3 student/flow_optimizer.py --write-final-summary
```

`--verify-final` reads the current `output/exNNN.aig` files, reruns ABC
equivalence/ADP measurement, and refreshes `student/logs/results.csv`,
`student/logs/summary.csv`, and `student/logs/pareto_candidates.csv`.
`--write-final-summary` also writes `student/logs/final_summary.csv` for the
report.

If your path contains spaces, run from the project root and pass relative paths:

```bash
python3 student/flow_optimizer.py --all --abc student/abc --benchmarks benchmarks --output output
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

## Useful Options

Limit the number of initial/flow candidate pairs per case:

```bash
python3 student/flow_optimizer.py --all --max-candidates 48
```

Use a deterministic random seed:

```bash
python3 student/flow_optimizer.py --all --seed 42
```

Set a per-case timeout:

```bash
python3 student/flow_optimizer.py --all --timeout-per-case 240
```

Disable optional search components:

```bash
python3 student/flow_optimizer.py --all --no-ga
python3 student/flow_optimizer.py --all --no-bdd
```

Print report-oriented aggregate statistics:

```bash
python3 student/flow_optimizer.py --all --report-stats
```

Reproduce the current best result with one command:

```bash
bash student/reproduce_best.sh
```

Generate diagnosis reports for deciding the next optimization direction:

```bash
python3 student/flow_optimizer.py --ablation-report
python3 student/flow_optimizer.py --diagnose-results
python3 student/flow_optimizer.py --validate-templates
python3 student/flow_optimizer.py --case-coverage-report
```

Run focused rescue on the current worst ADP cases.  This keeps the existing
output unless a candidate is equivalent and has lower ADP:

```bash
python3 student/flow_optimizer.py --rescue-worst 5 --max-candidates 80 --timeout-per-case 300 --seed 42
python3 student/flow_optimizer.py --rescue-worst 3 --max-candidates 80 --try-complement --history-guided-ga --bdd-sift
```

Give all under-covered cases a fair candidate package instead of ranking only by
ADP:

```bash
python3 student/flow_optimizer.py --complete-all-cases --min-candidates 50 --seed 0
python3 student/flow_optimizer.py --round-robin-optimize --rounds 5 --candidates-per-round 10 --seed 0
python3 student/flow_optimizer.py --score-aware-optimize --total-budget 5000 --seed 0
```

Polish already generated AIGs in place.  This only accepts candidates that are
equivalent and have lower ADP, so it can be run after the main synthesis search:

```bash
python3 student/flow_optimizer.py --all --polish-existing --polish-passes 30
```

Run the deterministic all-case hill-climb sweep used for the latest outputs:

```bash
python3 student/flow_optimizer.py --all --sweep-existing --sweep-passes 3 --timeout-per-case 180
python3 student/flow_optimizer.py --range ex200 ex207 --sweep-existing --sweep-passes 3 --timeout-per-case 180
```

Optionally enable the mockturtle AIG runner during the existing-output sweep.
This requires a local `student/mockturtle_src/` checkout and a C++ compiler in WSL:

```bash
bash student/build_mockturtle_opt.sh
python3 student/flow_optimizer.py --all --sweep-existing --try-mockturtle --timeout-per-case 240
```

If `student/mockturtle` is not built, the optimizer prints a warning and
continues without the optional mockturtle candidates.

Run the newer structural mockturtle engine.  This is not a random sweep: the
Boolean fingerprint selects at most two modes per case, then ABC runs a small
fixed polish set and accepts only equivalent lower-ADP candidates:

```bash
# Requires local mockturtle headers under student/mockturtle_src/
cmake -S student/mockturtle_opt -B student/mockturtle_opt/build
cmake --build student/mockturtle_opt/build --target mockturtle_opt -j2
python3 student/flow_optimizer.py --mockturtle-structural --timeout-per-case 45
python3 student/flow_optimizer.py --mockturtle-structural --mockturtle-max-modes 3 --timeout-per-case 45
python3 student/flow_optimizer.py --mockturtle-case ex200 --mode xag_xor_heavy --timeout-per-case 120
```

Run the final type-guided refinement package.  Every selected case is
fingerprinted first, assigned to a circuit family, then optimized with a small
fixed package for that family:

```bash
python3 student/flow_optimizer.py --type-guided-refine --type-guided-max-flows 8 --timeout-per-case 180
```

The families are `xor_affine`, `threshold_majority`, `mux_shannon`,
`arithmetic`, `small_template`, and `general`.

Run the objective-guided refinement package.  Every case tries fixed
area-first, delay-first, and balanced packages, then keeps the equivalent
candidate with the lowest ADP:

```bash
python3 student/flow_optimizer.py --objective-guided-refine --objective-max-per-family 3 --timeout-per-case 180
```

Run the micro-guided refinement package.  This pass still visits every case,
but adds low-cost flows that are especially useful for small circuits and
near-converged cases:

```bash
python3 student/flow_optimizer.py --micro-guided-refine --micro-max-flows 4 --timeout-per-case 90
```

Run the small-case targeted refinement package.  This scans all selected cases,
but only spends the small-flow package on compact outputs, so low-ADP cases also
receive dedicated coverage:

```bash
python3 student/flow_optimizer.py --small-case-refine --small-max-flows 5 --small-area-threshold 2500 --small-adp-threshold 50000 --timeout-per-case 35
```

## Outputs

Final selected AIGs are written to:

```text
output/exNNN.aig
```

The main CSV log is written to:

```text
student/logs/results.csv
```

The CSV records:

```text
case, initial_method, flow_name, flow_commands, area, delay, adp, equivalent, selected
```

The internal Pareto candidate pool is:

```text
student/logs/pareto_candidates.csv
```

It keeps equivalent non-dominated area/delay candidates plus the best
representative from important source families such as ABC baseline, BDD,
SOP/POS, complement, arithmetic templates, mockturtle, exact/NPN, and
transduction-inspired candidates.  The submitted output is still the minimum
ADP equivalent candidate.

The summary CSV is:

```text
student/logs/summary.csv
```

It records:

```text
case, baseline_area, baseline_delay, baseline_adp, best_area, best_delay, best_adp, improvement_ratio, selected_method
```

Diagnosis and validation reports are written to:

```text
student/logs/ablation_report.txt
student/logs/ablation_summary.csv
student/logs/bottleneck_diagnosis.csv
student/logs/case_coverage.csv
student/logs/case_coverage_report.txt
student/logs/coverage_candidates.csv
student/logs/rescue_worst_summary.csv
student/logs/bdd_sifting.csv
student/logs/exact_function_matches.csv
student/logs/template_validation.csv
student/logs/specialized_generators.csv
student/logs/mockturtle_structural_summary.csv
student/logs/exact_npn_rescue.csv
student/logs/transduction_rescue.csv
student/logs/complement_candidates.csv
student/logs/contest_optimize_schedule.csv
student/logs/round_robin_summary.csv
student/logs/score_aware_schedule.csv
student/logs/score_aware_summary.csv
student/logs/mockturtle_candidates.csv
student/logs/type_guided_refine.csv
student/logs/objective_guided_refine.csv
student/logs/micro_guided_refine.csv
student/logs/small_case_refine.csv
student/logs/final_summary.csv
student/logs/case_fair_next_optimize.csv
```

## Verified Result

The current generated `output/` directory was checked with:

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

Result:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11106756
```

The one-command reproduction recipe now includes the deterministic
micro-guided convergence passes that produced the latest post-phase
improvements:

```bash
bash student/reproduce_best.sh
```

## Notes

- Correctness is mandatory. Non-equivalent candidates are never selected.
- The optimizer does not hardcode benchmark-specific final AIG answers.
- The current best result is reproducible by running the command sequence in
  "Run the current best reproducible flow" from the project root.
- On Windows, the provided `student/abc` is a Linux binary. Use Linux, WSL, or a
  remote Linux environment.
- Before submission, always rerun `python3 evaluate.py`.
