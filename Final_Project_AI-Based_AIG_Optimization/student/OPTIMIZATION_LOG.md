# Optimization Log

This file records the major optimizer changes and the verified ADP impact.  The
baseline `student/optimizer.py` is kept unchanged; these changes are implemented
in `student/flow_optimizer.py`.

## Git History Reference

The table below is reconstructed from `git log` for the final-project directory.
It connects each commit to the optimizer milestone it introduced.

| Commit | Date | Commit message | Optimization milestone |
| --- | --- | --- | --- |
| `a6fb903` | 2026-05-15 | `feat: add final project` | Added the original project files, evaluator, benchmarks interface, and baseline `student/optimizer.py`. |
| `c890b32` | 2026-05-18 | `feat: add AI-guided ABC flow optimizer` | Added the first separate `student/flow_optimizer.py` and README usage notes for trying multiple ABC command flows. |
| `b1099ef` | 2026-05-19 | `feat: add circuit-type-aware flow optimizer` | Added circuit-type-aware flow selection, truth-table feature extraction, candidate logging, and safer per-candidate equivalence checks. |
| `3bc6711` | 2026-05-20 | `feat: add hybrid synthesis-based AIG optimization` | Reworked the optimizer into a hybrid framework with ABC baseline, SOP/POS, factored SOP, and Shannon/BDD initial synthesis. |
| `11df21b` | 2026-05-20 | `feat: add GA flows and BDD ordering search` | Added deterministic GA-generated ABC flows, additional BDD orderings, and broader bounded candidate search. |
| `f969c14` | 2026-05-21 | `feat: add Boolean fingerprinting and selector BDD ordering` | Added `boolean_fingerprint.py`, `--classify-case`, ANF/features/type detectors, and selector-reduction BDD ordering. |
| `e9fbb20` | 2026-05-21 | `feat: add iterative equivalence-checked AIG polish passes` | Added `--polish-existing` and repeated equivalence-checked in-place polish of generated AIGs. |
| `ef107eb` | 2026-05-21 | `feat: lower ADP with resub-based polish flows` | Added stronger `resub`-based post-polish flows for lower ADP. |
| `e0651a1` | 2026-05-21 | `feat: tune resub polish flows for lower ADP` | Tuned `resub` parameters and flow ordering based on measured ADP results. |
| `666ad7f` | 2026-05-21 | `feat: improve high-ADP cases with orchestrate and GIA polish flows` | Added high-impact `orchestrate`, GIA `&resyn3rs`, and `dchoice/ifraig` polish variants. |
| `5ed4d0a` | 2026-05-21 | `feat: lower ADP with structural multiplier and squarer synthesis` | Added exact unsigned multiplier and unsigned square detection plus structural BLIF generation. |
| `59f929f` | 2026-05-21 | `feat: reduce ADP with structural signed multiplier synthesis` | Added exact signed multiplier detection, signed correction logic, and existing-output ADP protection. |
| `7847bc3` | 2026-05-21 | `docs: record AIG optimization progress` | Added this optimization log and summarized the verified optimization path. |

## 2026-05-21

### Baseline preservation and separate optimizer

- Kept `student/optimizer.py` as the original baseline script.
- Moved all experimental and improved logic into `student/flow_optimizer.py` so
  the teacher-provided baseline remains easy to compare against.
- Added `student/README.md` usage notes for running the improved optimizer,
  evaluating outputs, and using WSL/Linux for the provided ABC binary.

### ABC flow portfolio search

- Replaced the single baseline ABC command sequence with a candidate portfolio.
- Tried multiple post-optimization flows such as rewrite/refactor/balance,
  `dc2`, `drw/drf`, `dch; if`, `fraig`, `resub`, `orchestrate`,
  `dchoice/ifraig`, and GIA `&resyn3rs` variants.
- Added per-candidate equivalence checking before selection.
- Added ADP-based selection so only equivalent candidates with lower
  `area * delay` can become `output/exNNN.aig`.
- Added CSV logging through `student/logs/results.csv` and
  `student/logs/summary.csv`.

### Hybrid initial synthesis framework

- Added support reduction using input influence to identify unused variables.
- Added custom BLIF initial candidates in addition to ABC `read_truth -xf`:
  SOP construction, POS/off-set construction, recursive factored SOP, and
  Shannon/BDD-style synthesis.
- Added multiple BDD variable orderings: original, high-influence-first,
  low-influence-first, balanced-Shannon-score-first, selector-reduction, and
  deterministic random orders.
- Added deterministic GA-style ABC flow generation with insert, delete, replace,
  swap, and crossover mutations.
- Added Pareto frontier tracking by area and delay for equivalent candidates.

### Boolean fingerprinting and type-aware analysis

- Added truth-table fingerprinting in `student/boolean_fingerprint.py`.
- Implemented feature extraction including influence, density, monotonicity,
  symmetry groups, Shannon split scores, cofactor similarity, ANF degree, and
  ANF term counts.
- Added exact detectors for constants, buffers/inverters, affine/parity,
  symmetric/threshold-like functions, cube/decoder-like functions, mux-like
  functions, comparator-like patterns, and small-support NPN templates.
- Added `python3 student/flow_optimizer.py --classify-case exNNN` for report
  support and AI/LLM-inspired circuit-type reasoning.

### Iterative equivalence-checked polish

- Added `--polish-existing` to improve already generated AIGs in place.
- Used repeated cleanup, delay-oriented, area-oriented, and ADP-balanced ABC
  polish passes.
- Verified the whole `output/` directory after polish.  The strongest
  pre-structural-template result recorded during development was:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 13871409
```

### Structural unsigned multiplier synthesis

- Added exact truth-table detection for unsigned multiplication with common
  operand groupings.
- Added BLIF generation from partial products and Wallace-style column
  reduction.
- Affected cases: `ex255` through `ex259`.
- Verified by `evaluate.py`.

### Structural unsigned square synthesis

- Added exact truth-table detection for unsigned squaring.
- Added a dedicated squarer generator that shares symmetric partial products and
  uses Wallace-style column reduction.
- First applied to the high-impact cases `ex273` and `ex274`, then extended to
  the full detected square range `ex270` through `ex274`.
- Verified by `evaluate.py`.

### Verified result after unsigned arithmetic templates

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 12402618
```

### Structural signed multiplier synthesis

- Added exact truth-table detection for signed two's-complement multiplication.
- Reused unsigned partial products, then applied conditional two's-complement
  correction terms for operand sign bits.
- Affected cases: `ex260` through `ex264`.
- Added protection so an existing equivalent `output/exNNN.aig` is preserved if
  it already has lower ADP than the newly searched candidates.
- Verified by `evaluate.py`.

### Verified result after signed multiplier synthesis

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 12030819
```

### Current verified result

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11983541
```

Compared with the previous verified result of `13871409`, the structural
arithmetic templates reduce total ADP by `1887868`.
