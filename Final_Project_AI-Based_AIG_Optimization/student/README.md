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
  signed two's-complement multipliers, and unsigned squarers.  These cases are
  generated as partial-product networks with Wallace-style column reduction
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
python3 student/flow_optimizer.py --reproduce-best
```

This single command expands to the deterministic sequence below, then verifies
all 100 final outputs and rewrites `student/logs/results.csv` plus
`student/logs/summary.csv`:

```bash
python3 student/flow_optimizer.py --all --max-candidates 48 --seed 42
python3 student/flow_optimizer.py --range ex255 ex259 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex260 ex264 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex270 ex274 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --all --polish-existing --polish-passes 30
python3 student/flow_optimizer.py --all --sweep-existing --sweep-passes 3 --timeout-per-case 180
python3 student/flow_optimizer.py --range ex200 ex207 --sweep-existing --sweep-passes 3 --timeout-per-case 180
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

For the largest arithmetic-template gains, the following focused ranges are
included in the current best flow and are also useful during experimentation:

```bash
python3 student/flow_optimizer.py --range ex255 ex259 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex260 ex264 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex270 ex274 --max-candidates 80 --no-ga
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
python3 student/flow_optimizer.py --reproduce-best
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

## Verified Result

The current generated `output/` directory was checked with:

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

Result:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11821986
```

## Notes

- Correctness is mandatory. Non-equivalent candidates are never selected.
- The optimizer does not hardcode benchmark-specific final AIG answers.
- The current best result is reproducible by running the command sequence in
  "Run the current best reproducible flow" from the project root.
- On Windows, the provided `student/abc` is a Linux binary. Use Linux, WSL, or a
  remote Linux environment.
- Before submission, always rerun `python3 evaluate.py`.
