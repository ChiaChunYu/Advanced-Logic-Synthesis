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
| working tree | 2026-05-21 | `feat: add focused GIA MFS polish flows` | Added focused GIA `&mfs`/`&compress3rs` polish flows and applied them to high-ADP cases that improved under equivalence checking. |
| working tree | 2026-05-22 | `feat: broaden high-ADP polish search` | Tested additional structural detectors and deeper ABC/GIA flows; kept only equivalence-checked `dch; if -K` and GIA `&dc2/&dch` improvements. |
| working tree | 2026-05-22 | `feat: add reproducible all-case sweep mode` | Added `--sweep-existing` to reproduce the deterministic per-case hill-climb sweep that improves many small and medium cases. |

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

### Verified result after full structural arithmetic sweep

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11983541
```

Compared with the previous verified result of `13871409`, the structural
arithmetic templates reduce total ADP by `1887868`.

### Focused GIA/MFS polish

- Probed additional high-ADP cases after the structural arithmetic templates.
- Exact divider and additional unary/product-formula detectors were tested, but
  no new safe structural template beat the current outputs.
- Added two equivalence-checked polish flows:
  - `polish_gia_resyn3_mfs_compress`
  - `polish_gia_mfs_compress`
- Applied focused polish to high-ADP cases where the probe showed improvement,
  including `ex207`, `ex220`, `ex222`, `ex223`, `ex225`, `ex226`, `ex227`,
  `ex252`, `ex297`, and `ex298`.
- Verified by `evaluate.py`.

### Current verified result after focused polish

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11943313
```

Compared with `11983541`, the focused polish pass reduced total ADP by `40228`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `1928096`.

## 2026-05-22

### 10% improvement attempt

- Targeted an additional 10% reduction from `11943313`, which would require
  roughly `1.19M` more ADP improvement.
- Deep-tested the largest remaining ADP cases, especially `ex299`, `ex227`,
  `ex207`, `ex226`, `ex297`, `ex206`, and `ex298`.
- Tried additional exact structural detectors:
  - quotient/remainder concatenation
  - flexible output bit-order arithmetic formulas
  - unary arithmetic patterns
  - product-derived formulas such as `a*b+a`, `a^2+b^2`, `(a+b)^2`
  - output splitting and clustering probes
- Tried deeper ABC/GIA reconstruction flows:
  - larger single-case hybrid search for `ex299`
  - GIA `&syn2`, `&syn3`, `&syn4`
  - GIA `&dc2`, `&dch`
  - LUT reconstruction with `if -K 4..16`
  - map/amap reconstruction probes
- No new safe structural template or deep reconstruction flow produced a 10%
  improvement.  The largest remaining cases appear to be resistant to the
  current template library.

### Broader high-ADP polish

- Added additional equivalence-checked polish flows:
  - `polish_dch_if8`
  - `polish_dch_if9`
  - `polish_dch_if11`
  - `polish_dch_if12`
  - `polish_dch_if13`
  - `polish_dch_if14`
  - `polish_gia_dc2`
  - `polish_gia_dch`
- Applied only candidates that were already checked equivalent and had lower
  ADP, mainly on `ex206`, `ex207`, `ex220`, `ex222`, `ex223`, `ex225`,
  `ex226`, `ex227`, `ex252`, `ex298`, and `ex299`.
- Verified by `evaluate.py`.

### Current verified result after broader polish

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11935020
```

Compared with `11943313`, this broader polish pass reduced total ADP by `8293`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `1936389`.

### Reproducible all-case sweep

- Moved the temporary all-case hill-climb script into `student/flow_optimizer.py`
  as a formal CLI mode:

```bash
python3 student/flow_optimizer.py --all --sweep-existing --sweep-passes 2 --timeout-per-case 180
```

- The sweep starts from the current `output/exNNN.aig`, applies a deterministic
  set of polish flows, checks equivalence for every candidate, and only replaces
  the output if ADP is lower.
- Two sweep passes improved 80 cases in the first pass and 61 cases in the
  second pass.
- Verified by `evaluate.py`.

### Current verified result after all-case sweep

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11847618
```

Compared with `11935020`, the two-pass all-case sweep reduced total ADP by
`87402`.  Compared with the pre-structural-template result of `13871409`, the
current total ADP is lower by `2023791`.
