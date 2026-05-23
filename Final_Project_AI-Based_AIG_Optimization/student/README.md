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
  high-area logic.  Each mockturtle candidate is still polished and verified by
  ABC before it can replace an output.
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

Analyze a benchmark without generating an AIG:

```bash
python3 student/flow_optimizer.py --analyze-case ex200
```

Run precise Boolean fingerprinting/classification without generating an AIG:

```bash
python3 student/flow_optimizer.py --classify-case ex200
```

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
python3 student/flow_optimizer.py --mockturtle-case ex200 --mode xag_xor_heavy --timeout-per-case 120
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
student/logs/template_validation.csv
student/logs/round_robin_summary.csv
student/logs/score_aware_schedule.csv
student/logs/score_aware_summary.csv
student/logs/mockturtle_candidates.csv
```

## Verified Result

The current generated `output/` directory was checked with:

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

Result:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11458971
```

## Notes

- Correctness is mandatory. Non-equivalent candidates are never selected.
- The optimizer does not hardcode benchmark-specific final AIG answers.
- The current best result is reproducible by running the command sequence in
  "Run the current best reproducible flow" from the project root.
- On Windows, the provided `student/abc` is a Linux binary. Use Linux, WSL, or a
  remote Linux environment.
- Before submission, always rerun `python3 evaluate.py`.
