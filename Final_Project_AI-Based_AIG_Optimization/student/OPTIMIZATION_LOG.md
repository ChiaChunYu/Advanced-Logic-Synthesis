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
| working tree | 2026-05-22 | `feat: add structural divider quotient synthesis` | Added exact unsigned divider-quotient detection and restoring-divider BLIF generation for architecture-level optimization. |
| working tree | 2026-05-22 | `feat: add integer square-root architecture detection` | Added exact unsigned square-root detection and a restoring square-root structural candidate; kept only the cases that improved after equivalence checking. |
| working tree | 2026-05-22 | `feat: add diagnosis-driven optimization reports` | Added ablation, bottleneck diagnosis, template validation, rescue-worst, complement-first, BDD sift, and history-guided GA entry points. |
| working tree | 2026-05-22 | `feat: add focused ex252 rescue stage` | Used diagnosis-guided rescue to find a better ex252 BDD/Shannon candidate and added the reproducible stage to `--reproduce-best`. |
| working tree | 2026-05-22 | `feat: add fair per-case coverage scheduler` | Added case coverage reporting plus complete-all, round-robin, and score-aware schedulers so small cases are not starved by high-ADP rescue. |
| working tree | 2026-05-23 | `feat: add fingerprint-guided mockturtle structural resynthesis` | Added a CMake-built mockturtle structural engine, fingerprint-to-mode mapping, ABC-polished mockturtle candidates, and a final `--reproduce-best` structural stage. |
| working tree | 2026-05-24 | `feat: add micro-guided per-case ADP refinement` | Added a low-cost all-case refinement stage for small and near-converged cases using guarded resubstitution, low-K mapping, renode, and collapse/factorization flows. |
| working tree | 2026-05-24 | `feat: refine compact cases with small-circuit flows` | Added a small-case-only refinement package that targets compact or low-ADP outputs with low-K mapping, SOP/factorization, fraiging, and GIA SOP balancing. |
| working tree | 2026-05-24 | `feat: lower ADP with advanced mockturtle structural modes` | Added cut-level AIG/XAG NPN rewriting, don't-care AIG rewriting, XAG min-MC reduction, MIG Akers cut rewriting, and XMG mixed resubstitution. |

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
- Three full sweep passes improved many small and medium cases, not only the
  largest high-ADP benchmarks.  The first two passes improved 80 cases and 61
  cases respectively; the third pass continued lowering additional cases.
- A longer fourth full sweep was tested but did not finish cleanly within the
  working window, so the accepted reproducible version replaces it with a
  focused deterministic range sweep on `ex200` through `ex207`.
- The focused front-range sweep is also exposed through the normal CLI:

```bash
python3 student/flow_optimizer.py --range ex200 ex207 --sweep-existing --sweep-passes 3 --timeout-per-case 180
```

- Verified by `evaluate.py`.

### Current verified result after all-case and focused sweeps

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11821986
```

Compared with `11935020`, the reproducible sweep sequence reduced total ADP by
`113034`.  Compared with the pre-structural-template result of `13871409`, the
current total ADP is lower by `2049423`.

### Current reproducible command sequence

The current output can be reproduced from the project root with one command:

```bash
python3 student/flow_optimizer.py --reproduce-best
```

This command is a wrapper around the full deterministic sequence:

```bash
python3 student/flow_optimizer.py --all --max-candidates 48 --seed 42
python3 student/flow_optimizer.py --range ex255 ex259 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex260 ex264 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex265 ex269 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex270 ex274 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --range ex275 ex279 --max-candidates 80 --no-ga
python3 student/flow_optimizer.py --case ex252 --max-candidates 120 --timeout-per-case 240 --seed 99 --try-complement --history-guided-ga --polish-after-synthesis
python3 student/flow_optimizer.py --all --polish-existing --polish-passes 30
python3 student/flow_optimizer.py --all --sweep-existing --sweep-passes 3 --timeout-per-case 180
python3 student/flow_optimizer.py --range ex200 ex207 --sweep-existing --sweep-passes 3 --timeout-per-case 180
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- `--reproduce-best` uses fixed internal search settings for the known best
  flow: `48` main candidates, `80` focused arithmetic candidates, seed `42`,
  `30` polish passes, and `3` sweep passes.
- The command finishes by verifying all 100 outputs through ABC and printing
  the total ADP, so the result can be reproduced without manually copying the
  multi-line command sequence.

### Structural unsigned divider quotient synthesis

- Added an exact truth-table detector for unsigned quotient functions:
  `quotient = dividend / divisor`, with divisor zero mapped to all-one output.
- Added a restoring-divider BLIF generator using structural compare, subtract,
  mux, and quotient-bit extraction logic.
- This is an architecture-level initial synthesis method rather than another
  ABC sweep command.  The template is only considered when the full truth table
  exactly matches the quotient function, then ABC still checks equivalence
  before any output is selected.
- Detected range: `ex265` through `ex269`.
- Existing-output ADP protection kept the smaller current results for
  `ex265` through `ex268`, while `ex269` improved with
  `template_unsigned_divider_quotient/llm_mix_2`.

### Current verified result after divider quotient template

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11820308
```

Compared with `11821986`, the divider quotient template reduced total ADP by
`1678`.  Compared with the pre-structural-template result of `13871409`, the
current total ADP is lower by `2051101`.

### Structural unsigned square-root detection

- Added an exact detector for `floor(sqrt(input_word))` functions.
- Detected range: `ex275` through `ex279`.
- Added a restoring square-root BLIF generator, but the structural candidate did
  not beat the current outputs on the larger square-root cases.
- The focused range search still found a better equivalent BDD-based result for
  `ex275`, reducing that case ADP from `336` to `294`.
- Larger architecture probes were also tested and rejected because they made the
  high-ADP cases worse:
  - per-output cone decomposition for `ex297`, `ex298`, and `ex299`
  - output-polarity phase-normalized synthesis
  - sign-bit factoring for floating-like `sin/tan`-style cases

### Current verified result after square-root range

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11820266
```

Compared with `11820308`, the square-root range reduced total ADP by `42`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `2051143`.

### Diagnosis-driven optimizer instrumentation

- Added ablation reporting:

```bash
python3 student/flow_optimizer.py --ablation-report
```

  This reads candidate history from `student/logs/reproduce_candidates.csv` or
  `student/logs/results.csv`, then reports wins by initial method, wins by ABC
  flow, average ADP per method, never-selected methods, near-miss BDD/Shannon
  cases, arithmetic-template wins, and template failures.

- Added bottleneck diagnosis:

```bash
python3 student/flow_optimizer.py --diagnose-results
```

  This measures the current `output/` AIGs and classifies each case as
  `area_bottleneck`, `delay_bottleneck`, `balanced_bottleneck`,
  `template_mismatch`, `bdd_ordering_sensitive`, or `already_good`.

- Added focused rescue mode:

```bash
python3 student/flow_optimizer.py --rescue-worst 5 --max-candidates 80 --timeout-per-case 300 --seed 42
```

  This ranks current cases by ADP, reruns focused candidate search only on the
  top `K`, and keeps the old output unless an equivalent lower-ADP candidate is
  found.

- Added optional rescue aids:
  - `--try-complement`: tries complement-first ABC truth synthesis and then
    wraps outputs back to the original phase.
  - `--bdd-sift`: tries adjacent-swap local search for BDD variable order during
    rescue.
  - `--history-guided-ga`: seeds GA flows from historical equivalent winners
    instead of starting only from random mutations.

- Added exact template validation:

```bash
python3 student/flow_optimizer.py --validate-templates
```

  This records matched unsigned multiplier, signed multiplier, square, divider
  quotient/remainder, integer square-root, comparator, and adder-like formulas
  under common operand mappings.

- Smoke tests completed:
  - `python3 -m py_compile student/flow_optimizer.py student/boolean_fingerprint.py student/optimizer.py`
  - `python3 student/flow_optimizer.py --validate-templates`
  - `python3 student/flow_optimizer.py --diagnose-results`
  - `python3 student/flow_optimizer.py --ablation-report`
  - isolated `ex200` run with `--try-complement --history-guided-ga`, followed
    by `python3 evaluate.py --case ex200`, passed equivalence.

### Focused ex252 rescue

- Used bottleneck diagnosis to move beyond the top-five worst cases after
  `ex299`, `ex227`, `ex207`, `ex226`, and `ex206` did not improve under rescue.
- Ran focused rescue on medium high-ADP cases with complement-first synthesis,
  history-guided GA, and post-synthesis polish enabled.
- The only accepted improvement was `ex252`, where a BDD/Shannon candidate with
  seed `99` and `llm_mix_2` reduced ADP:

```text
ex252: 347650 -> 320658
```

- The improvement is reproducible from scratch with:

```bash
python3 student/flow_optimizer.py --case ex252 --max-candidates 120 --timeout-per-case 240 --seed 99 --try-complement --history-guided-ga --polish-after-synthesis
```

### Current verified result after focused rescue

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11793274
```

Compared with `11820266`, the focused rescue stage reduced total ADP by
`26992`.  Compared with the pre-structural-template result of `13871409`, the
current total ADP is lower by `2078135`.

### Fair per-case coverage scheduling

- Added a case coverage report:

```bash
python3 student/flow_optimizer.py --case-coverage-report
```

  It records candidates tried, equivalent candidates, selected updates, method
  diversity, flow-family diversity, whether BDD/SOP/complement were tried, and
  baseline/current ADP ratio for every benchmark.

- Added under-covered case detection using the contract:
  - fewer than `50` candidates
  - fewer than `10` equivalent candidates
  - fewer than `4` initial methods
  - fewer than `5` flow families
  - no complement synthesis
  - no BDD/Shannon synthesis
  - improvement ratio below `1.02`

- Added fair scheduling modes:

```bash
python3 student/flow_optimizer.py --complete-all-cases --min-candidates 50 --seed 0
python3 student/flow_optimizer.py --round-robin-optimize --rounds 5 --candidates-per-round 10 --seed 0
python3 student/flow_optimizer.py --score-aware-optimize --total-budget 5000 --seed 0
```

- These modes append candidate history to `student/logs/coverage_candidates.csv`
  so later coverage reports can see progress across multiple passes.
- Smoke tests completed on both a small case and the largest remaining case:
  - `ex200` kept the current equivalent output at ADP `63252`
  - `ex299` kept the current equivalent output at ADP `2740464`

### Current verified result after fair coverage scheduler smoke

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11793022
```

Compared with the focused-rescue result of `11793274`, the current checked
outputs are lower by `252`.  Compared with the pre-structural-template result of
`13871409`, the current total ADP is lower by `2078387`.

### All-case low-K mapping refinement

- Added `sweep_lowk_if4` to the deterministic existing-output sweep:

```text
dch; if -K 4; strash; dc2; balance
```

- The purpose is to give every benchmark, including small cases, a low-fanin
  remapping attempt instead of only spending time on the largest ADP cases.
- This is still selected by the same safety rule: the output is overwritten only
  when ABC confirms equivalence and the measured ADP is lower.
- The full sweep improved both small and large cases, including:

```text
ex200: 63252 -> 63126
ex203: 82026 -> 81984
ex208: 34646 -> 34595
ex240: 51313 -> 49565
ex252: 320658 -> 264875
ex269: 22842 -> 21014
ex275: 294 -> 280
ex298: 577192 -> 574442
ex299: 2740464 -> 2740344
```

### Current verified result after all-case low-K refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11723588
```

Compared with the previous `11793022`, this sweep reduced total ADP by `69434`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `2147821`.

### Optional mockturtle integration

- Added `student/mockturtle_opt.cpp`, a small mockturtle runner that can read an
  AIG, apply lightweight AIG balance and SOP refactoring modes, and write a new
  AIG.
- Added `student/build_mockturtle_opt.sh` to build the runnable
  `student/mockturtle` binary when WSL has `g++` or `clang++` installed.
- Added `--try-mockturtle` and `--mockturtle-bin` to `flow_optimizer.py`.
  During `--sweep-existing`, the optimizer can run mockturtle candidates first,
  then pass them through ABC cleanup, equivalence checking, ADP measurement, and
  the usual lower-ADP-only replacement rule.
- Current WSL environment did not have a C++ compiler, so the build script
  correctly stopped with:

```text
No C++ compiler found. Install g++ or clang++ in WSL, then rerun this script.
```

- The `--try-mockturtle` smoke path was still tested without a binary. It safely
  skipped mockturtle candidates and continued the normal sweep. That pass found
  one additional equivalent ABC sweep improvement:

```text
ex200: 63126 -> 63090
```

### Current verified result after mockturtle hook smoke

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11723552
```

Compared with the previous `11723588`, the checked outputs are lower by `36`.

### Multi-pass all-case convergence sweep

- Re-ran the integrated existing-output sweep over all `ex200`-`ex299` cases for
  several passes.  Each pass revisits every benchmark, so the search is not
  limited to the largest ADP cases.
- Added the same final all-case convergence sweep stage to `--reproduce-best`
  so this extra search is part of the reproducible workflow.
- `--try-mockturtle` was included in the sweep command.  Because
  `student/mockturtle` is not built yet in this WSL environment, the
  optimizer printed a warning and safely skipped mockturtle candidates.  The
  ABC/GIA sweep flows still found additional equivalent improvements.
- Key accepted improvements included:

```text
ex205: 81228 -> 80934
ex206: 658030 -> 656167
ex207: 775248 -> 772824
ex223: 238671 -> 236371
ex225: 249297 -> 248078
ex227: 864202 -> 860844
ex242: 51813 -> 50920
ex250: 75020 -> 73854
ex252: 264875 -> 243648
ex291: 96102 -> 95437
ex292: 120340 -> 113297
ex294: 211302 -> 200500
ex298: 574442 -> 569338
ex299: 2740344 -> 2733744
```

### Current verified result after multi-pass convergence

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11653116
```

Compared with `11723552`, the convergence sweep reduced total ADP by `70436`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `2218293`.

### Mixed ABC and mockturtle sweep

- Rebuilt the optional `student/mockturtle` executable from
  `student/mockturtle_src/` after installing `g++`.
- Fixed the build script include/link setup for bundled mockturtle dependencies:
  `nauty`, `abcsat`, `abcesop`, and header-only `fmt`.
- Ran mixed sweeps using:

```bash
python3 student/flow_optimizer.py --all --sweep-existing --sweep-passes 1 --timeout-per-case 240 --try-mockturtle
```

- In this mode, each case tries mockturtle `light`, `refactor`, and `balance`
  candidates first, then ABC cleanup, equivalence checking, and ADP selection.
- The mockturtle candidates were equivalent but did not beat the current best
  AIGs in the latest pass.  The same mixed loop still found additional ABC/GIA
  improvements, including:

```text
ex207: 772824 -> 771912
ex223: 236371 -> 235888
ex225: 248078 -> 247802
ex227: 860844 -> 857463
ex250: 73854 -> 73634
ex252: 243648 -> 242760
ex298: 569338 -> 568612
ex299: 2733744 -> 2728776
```

### Current verified result after mixed ABC/mockturtle sweeps

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11641063
```

Compared with `11653116`, the mixed sweep stage reduced total ADP by `12053`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `2230346`.

### Fingerprint-guided mockturtle structural resynthesis

- Inspected the local `student/mockturtle_src/` headers and wrote the supported
  API findings to `student/MOCKTURTLE_PLAN.md`.
- Added `student/mockturtle_opt/`, a CMake-built structural mockturtle tool with
  modes for XAG, MIG, XMG, AIG resubstitution, functional reduction, and
  XAG/MIG/XMG round-trips.
- Added `--mockturtle-structural` and `--mockturtle-case` to
  `student/flow_optimizer.py`.
- The new path uses Boolean fingerprint labels to select at most two modes per
  case instead of randomly sweeping commands:

```text
parity/affine           -> xag_xor_heavy, roundtrip_xag
majority/threshold      -> mig_majority, roundtrip_mig
arithmetic XOR+majority -> xmg_arithmetic, roundtrip_xmg
large/general AIG       -> aig_resub, functional_reduction
```

- Every mockturtle output is polished by a small fixed ABC set, checked for
  equivalence against the original truth table, measured with ABC `ps`, and
  accepted only when ADP is lower than the current output.
- Added the structural mockturtle pass to the final stage of
  `--reproduce-best`.  If the C++ tool cannot be built, this stage prints a
  warning and leaves the existing verified outputs unchanged.
- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --mockturtle-structural --timeout-per-case 45
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex200: 62982 -> 60588
ex201: 28080 -> 26605
ex206: 656167 -> 639870
ex220: 229108 -> 221100
ex226: 701778 -> 678510
ex256: 2869 -> 2652
ex259: 13888 -> 11726
ex269: 20856 -> 17930
ex274: 45156 -> 31325
ex299: 2728776 -> 2727672
```

### Current verified result after structural mockturtle pass

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11458971
```

Compared with `11641063`, the structural mockturtle stage reduced total ADP by
`182092`.  Compared with the pre-structural-template result of `13871409`, the
current total ADP is lower by `2412438`.

### Reproducible one-command pipeline cleanup

- Added `student/reproduce_best.sh` as the main one-command reproduction entry
  point:

```bash
bash student/reproduce_best.sh
```

- Added `--show-reproduce-recipe` to print the deterministic stage recipe
  without generating AIGs.
- `--reproduce-best` now writes `student/logs/reproduce_recipe.txt` at the
  beginning of a run, so the exact stage order is recorded next to the result
  CSVs.
- Renamed console messages for the final fixed ABC/GIA packages from generic
  "sweep" language to "deterministic refinement package" language.  The code
  still uses the old helper internally, but the user-facing flow now makes clear
  that these are fixed, seeded, reproducible candidate packages rather than
  random command sweeps.

### Final type-guided circuit-family refinement

- Added `--type-guided-refine`, which revisits every case instead of ranking
  only by total ADP.
- Each case is fingerprinted first, then assigned to one fixed refinement
  family:

```text
xor_affine
threshold_majority
mux_shannon
arithmetic
small_template
general
```

- Each family has a small hand-curated ABC package.  Examples:
  low-`K` mapping for threshold/majority-like functions, `dchoice/ifraig` and
  higher-`K` decomposition for mux/Shannon-like functions, GIA `&mfs`/
  `&compress3rs` for arithmetic-like functions, and compact rewrite/resub
  flows for small-template logic.
- Added the type-guided refinement stage to `--reproduce-best` after
  mockturtle structural resynthesis.
- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --type-guided-refine --type-guided-max-flows 5 --timeout-per-case 120
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex200: 60588 -> 60010
ex209: 10740 -> 10470
ex220: 221100 -> 219177
ex229: 74917 -> 73036
ex241: 50201 -> 48603
ex254: 54264 -> 51600
ex264: 21736 -> 21166
ex270: 3784 -> 3674
ex291: 91962 -> 90000
ex299: 2727672 -> 2724432
```

### Current verified result after type-guided refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11439516
```

Compared with `11458971`, the type-guided stage reduced total ADP by `19455`.
Compared with the pre-structural-template result of `13871409`, the current
total ADP is lower by `2431893`.

### Independent-source type-guided candidate selection

- Changed the type-guided refinement loop so every family-specific flow starts
  from the same current output AIG instead of chaining candidates sequentially.
  This prevents an early small rewrite from destroying the structure needed by a
  later, more suitable circuit-family flow.
- Expanded the `general` family package with deterministic structural GIA
  candidates:

```text
&sopb -C 16 -R 1
&dsd
&b -d -s
&resyn3; &mfs; &compress3rs; &resyn3rs; &compress3rs
```

- Increased the reproducible type-guided package to eight flows per case.  The
  package still visits every case, checks every candidate with ABC, and accepts
  only equivalent lower-ADP outputs.
- Tested ABC `&rrr` SAT resubstitution on the largest bottlenecks, but it was
  too slow/unstable for the deterministic reproduction path and was not added.
- Representative accepted improvements:

```text
ex207: 770712 -> 741382
ex220: 219177 -> 218988
ex221: 133620 -> 133240
ex252: 242688 -> 238556
ex283: 52750 -> 52248
ex292: 113240 -> 110142
ex293: 169974 -> 162298
ex298: 542220 -> 542010
```

### Current verified result after independent-source type-guided refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11363459
```

Compared with `11439516`, this refinement reduced total ADP by `76057`.

### Objective-guided area/delay/balanced refinement

- Added `--objective-guided-refine`, which gives every selected case three
  independent optimization families:

```text
area-first
delay-first
balanced ADP
```

- Each flow starts from the current output AIG, so area-priority and
  delay-priority candidates compete fairly instead of being chained together.
- Added this objective-guided pass as the final stage of `--reproduce-best`.
- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --objective-guided-refine --objective-max-per-family 3 --timeout-per-case 180
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex200: 60010 -> 59687
ex207: 741382 -> 738530
ex221: 133240 -> 132640
ex234: 18620 -> 17850
ex252: 238556 -> 235497
ex253: 8820 -> 8316
ex268: 9936 -> 9712
ex292: 110142 -> 108342
ex298: 542010 -> 541023
```

### Current verified result after objective-guided refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11347482
```

Compared with `11363459`, this refinement reduced total ADP by `15977`.

### Micro-guided per-case refinement

- Added `--micro-guided-refine`, a deterministic pass that still visits every
  case instead of ranking only by total ADP.
- The pass starts from the current equivalent output and tries a small set of
  low-cost flows:

```text
micro_resub4
micro_if3
micro_renode
micro_collapse_sop
```

- `micro_collapse_sop` is guarded so it is only used on compact or low-ADP
  functions, where collapsing and refactoring can help without exploding
  runtime.
- Added this micro-guided pass as the final stage of `--reproduce-best`, after
  the objective-guided area/delay/balanced pass.
- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --micro-guided-refine --micro-max-flows 4 --timeout-per-case 90
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex200: 59687 -> 59534
ex202: 61472 -> 60367
ex203: 81092 -> 78508
ex204: 25584 -> 24976
ex205: 76684 -> 75392
ex206: 639870 -> 629244
ex222: 217413 -> 214641
ex223: 225036 -> 222432
ex249: 6669 -> 5715
ex290: 59232 -> 58352
ex293: 162298 -> 161139
ex299: 2724432 -> 2723448
```

### Current verified result after micro-guided refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11294764
```

Compared with `11347482`, this refinement reduced total ADP by `52718`.

### Small-case targeted refinement

- Added `--small-case-refine`, which scans the requested cases but only spends
  the small-flow package when the current output is compact enough:

```text
area <= 2500 or ADP <= 50000
```

- This was added because optimizing only the total ADP tends to favor large
  arithmetic cases.  The new pass explicitly gives low-ADP and compact cases
  another chance with flows that are better suited to small Boolean functions:

```text
small_if4
small_fx_dc2
small_fraig_dc2
small_if5
small_gia_sopb
```

- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --small-case-refine --small-max-flows 5 --small-area-threshold 2500 --small-adp-threshold 50000 --timeout-per-case 35
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex239: 44583 -> 41800
ex241: 30240 -> 29708
ex246: 13090 -> 12712
ex247: 16366 -> 14911
ex248: 36765 -> 34080
ex249: 5715 -> 4654
ex276: 1100 -> 1080
ex283: 51336 -> 51129
ex287: 35302 -> 35283
```

### Current verified result after small-case targeted refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11237685
```

Compared with `11294764`, this refinement reduced total ADP by `57079` while
focusing on compact and low-ADP cases.

### Advanced mockturtle structural refinement

- Extended `student/mockturtle_opt/mockturtle_opt.cpp` with deterministic
  structural modes from the mockturtle investigation:

```text
cut4_aig_xag_npn
cut5_aig_xag_npn_depth
dc_aig_rewrite
xag_area_minmc
mig_akers_cut4
xmg_mixed_resub
```

- Updated the fingerprint selector in `student/flow_optimizer.py` so:
  - XOR/affine cases try XAG min-MC and XAG structural rewriting.
  - Majority/threshold/carry-like cases try Akers-style MIG cut rewriting.
  - Mixed arithmetic cases try XMG algebraic rewriting and resubstitution.
  - Mux/high-area cases try depth-preserving larger cuts or don't-care AIG
    rewriting.
  - Compact cases try 4-input AIG/XAG NPN cut rewriting.
- Added this advanced mockturtle pass as the final stage of `--reproduce-best`,
  after small-case targeted refinement, because the best improvements appear
  when the structural engine starts from the fully refined AIGs.
- Full pass command used for the latest result:

```bash
python3 student/flow_optimizer.py --mockturtle-structural --timeout-per-case 90
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

- Representative accepted improvements:

```text
ex204: 24976 -> 24315
ex208: 32928 -> 32085
ex222: 214641 -> 211820
ex228: 122835 -> 120870
ex230: 136040 -> 133095
ex239: 41800 -> 40451
ex248: 34080 -> 32410
ex249: 4654 -> 4440
ex272: 13076 -> 12000
ex274: 31185 -> 29700
ex283: 51129 -> 49412
ex287: 35283 -> 34506
ex299: 2723448 -> 2722296
```

### Current verified result after advanced mockturtle structural refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11210243
```

Compared with `11237685`, this refinement reduced total ADP by `27442`.

## Contest-style Phase 1/2 infrastructure

Implemented the first two steps from `AGENTS.md` without changing the baseline
`student/optimizer.py`.

### Phase 1: internal Pareto candidate pool

- Added a per-case Pareto candidate pool in `student/flow_optimizer.py`.
- The optimizer now writes:

```text
student/logs/pareto_candidates.csv
```

- Only equivalent candidates enter the pool.
- The CSV marks the true area/delay Pareto frontier, min-area, min-delay,
  min-ADP, and final selected candidate.
- The pool also keeps the best representative from important source families:
  ABC baseline, BDD/Shannon, SOP/POS/factored SOP, complement synthesis,
  arithmetic templates, mockturtle XAG/MIG, exact/NPN, and
  transduction-inspired candidates.
- Final `output/exNNN.aig` selection remains unchanged: the selected output is
  still the equivalent candidate with minimum ADP.

Smoke test:

```bash
python3 student/flow_optimizer.py --case ex200 --max-candidates 2 --timeout-per-case 120 --no-ga --no-bdd
```

Generated `student/logs/pareto_candidates.csv` with the ABC baseline and the
current selected `ex200` output.

### Phase 2: exact function recognition

- Added `student/exact_function_recognition.py`.
- Added:

```bash
python3 student/flow_optimizer.py --exact-function-report --case ex200
python3 student/flow_optimizer.py --exact-function-report --all
```

- The exact detector writes:

```text
student/logs/exact_function_matches.csv
```

- Matches are logged with confidence `1.000` only after checking the complete
  truth table.
- Current detector coverage includes constants, buffers/inverters, affine and
  parity outputs, symmetric/threshold/exact-k/one-hot/decoder-like functions,
  popcount and sorter output bits, comparator bits, adder sum/carry bits,
  unsigned and signed multiplier bits, square bits, divider quotient bits,
  divider remainder/modulo-like bits, and integer square-root bits.
- Input mappings include first-half/second-half, even/odd interleaving,
  reversed endian orders, swapped operands, and active-support variants.

Smoke test:

```bash
python3 student/flow_optimizer.py --exact-function-report --case ex200
```

Result:

```text
matched rows: 2
```

`--classify-case ex200` now also prints a quick exact-match summary.

## Contest-style Phase 3/4 infrastructure

Implemented the next two steps from `AGENTS.md` as optional, safety-gated
passes.  The deterministic `--reproduce-best` recipe is not changed yet; these
passes can be run independently first and added to the recipe only after they
show useful improvements.

### Phase 3: exact-match structural generators

- Added exact-match structural generator support in `student/flow_optimizer.py`.
- New CLI:

```bash
python3 student/flow_optimizer.py --specialized-generators --case ex255
python3 student/flow_optimizer.py --specialized-generators --all --timeout-per-case 120
```

- New log:

```text
student/logs/specialized_generators.csv
```

- Implemented BLIF generators for:
  - affine/parity/simple output functions
  - popcount output bits
  - threshold/exact-k/one-hot/sorter bits
  - adder sum/carry bits
  - comparator bits
  - whole-table multiplier, signed multiplier, square, divider quotient, and
    integer square-root structures
- Each generated BLIF is converted through ABC, checked against the original
  truth table, measured for area/delay/ADP, and accepted only if ADP improves.

Smoke tests:

```bash
python3 student/flow_optimizer.py --specialized-generators --case ex200 --logs student/logs_phase34_smoke --timeout-per-case 120 --exact-max-inputs 12
python3 student/flow_optimizer.py --specialized-generators --case ex255 --logs student/logs_phase34_smoke --timeout-per-case 180 --exact-max-inputs 12
```

Results:

```text
ex200: no complete exact-match structural generator available
ex255: exact_unsigned_multiplier generated 4 equivalent candidates, current output remained better
```

### Phase 4: mockturtle structural resynthesis cleanup

- Added exact-match hints to mockturtle mode selection.
- Added `--mockturtle-max-modes N` so the structural pass can try 1, 2, or 3
  fingerprint-selected modes without becoming an uncontrolled sweep.
- Added:

```text
student/logs/mockturtle_structural_summary.csv
```

- The summary records base/best area, delay, ADP, mode list, exact type hints,
  generated candidates, and equivalent candidates.

Smoke tests:

```bash
python3 student/flow_optimizer.py --mockturtle-case ex200 --mode cut4_aig_xag_npn --mockturtle-max-modes 1 --logs student/logs_phase34_smoke --timeout-per-case 120 --exact-max-inputs 12
python3 student/flow_optimizer.py --mockturtle-case ex255 --mockturtle-max-modes 3 --logs student/logs_phase34_smoke --timeout-per-case 120 --exact-max-inputs 12
```

Results:

```text
ex200: 3/3 mockturtle candidates equivalent, no ADP improvement
ex255: 9/9 mockturtle candidates equivalent, no ADP improvement
```

Final safety smoke check:

```bash
./student/abc -c 'read_truth -xf benchmarks/ex200.truth; st; &get; &cec -t output/ex200.aig'
./student/abc -c 'read_truth -xf benchmarks/ex255.truth; st; &get; &cec -t output/ex255.aig'
```

Both reported:

```text
Networks are equivalent.
```

## Contest-style Phase 5/6 infrastructure

Implemented the next two steps from `AGENTS.md` as bounded, equivalence-gated
passes.

### Phase 5: small-support exact/NPN rescue

- Added:

```bash
python3 student/flow_optimizer.py --exact-npn-rescue --case ex255 --npn-max-support 8
python3 student/flow_optimizer.py --exact-npn-rescue --all --npn-max-support 6
```

- New log:

```text
student/logs/exact_npn_rescue.csv
```

- The rescue pass generates exact small-support BLIF candidates when the whole
  multi-output function support is within the configured support bound.
- It also reports skipped cases when the support is too large.
- Candidates are reduced with fixed ABC flows and accepted only after full ABC
  equivalence and lower ADP.

Smoke tests:

```bash
python3 student/flow_optimizer.py --exact-npn-rescue --case ex200 --logs student/logs_phase56_smoke --timeout-per-case 120 --npn-max-support 6
python3 student/flow_optimizer.py --exact-npn-rescue --case ex255 --logs student/logs_phase56_smoke4 --timeout-per-case 120 --npn-max-support 8
```

Results:

```text
ex200: skipped, largest output support 16 exceeds limit 6
ex255: generated 4 equivalent exact-cover candidates, current output remained better
```

### Phase 6: transduction-inspired expansion/reduction

- Added:

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
- `g` is selected deterministically from high-influence and high-Shannon-score
  primary inputs.
- Fixed ABC-generated BLIF continuation handling so multi-line `.inputs` and
  `.outputs` directives are wrapped correctly.

Accepted improvement:

```text
ex200: 59534 -> 59517
```

Full internal verification after the replacement:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11210226
```

## Contest-style Phase 7/8 infrastructure

Implemented the next two steps from `AGENTS.md`.

### Phase 7: complement synthesis wrapper

- Added:

```bash
python3 student/flow_optimizer.py --complement-rescue --case ex200 --complement-budget 16
python3 student/flow_optimizer.py --complement-rescue --all --complement-budget 16
```

- New log:

```text
student/logs/complement_candidates.csv
```

- Complement rescue now generates complement-first candidates from:
  - ABC truth synthesis
  - BDD/Shannon when enabled
  - SOP/POS/factored SOP when applicable
  - structural template generators when the complement truth table matches
- Added `blif_complement` synthesis support: optimize the complement BLIF,
  write BLIF, invert outputs back to original polarity, convert to AIG, then
  run full ABC equivalence.
- Updated the BLIF output wrapper so multi-line ABC `.outputs` continuation
  directives are handled correctly.

Smoke test:

```bash
python3 student/flow_optimizer.py --complement-rescue --case ex200 --logs student/logs_phase78_smoke --timeout-per-case 120 --complement-budget 4 --no-bdd
```

Result:

```text
ex200: complement candidates were equivalent, current output remained better
```

### Phase 8: per-case fair contest scheduler

- Added:

```bash
python3 student/flow_optimizer.py --contest-optimize --seed 0 --time-budget 3600
```

- New log:

```text
student/logs/contest_optimize_schedule.csv
```

- The scheduler visits every selected case by stage rather than ranking only by
  total ADP:
  1. exact matching
  2. base coverage
  3. complement rescue
  4. specialized structural generation
  5. mockturtle structural resynthesis
  6. exact/NPN rescue
  7. transduction rescue
- `case_coverage.csv` now records additional coverage bits:
  `exact_match_tried`, `specialized_tried`, `mockturtle_tried`,
  `exact_npn_tried`, and `transduction_tried`.

Smoke test:

```bash
python3 student/flow_optimizer.py --contest-optimize --case ex200 --logs student/logs_phase78_smoke --time-budget 90 --timeout-per-case 40 --max-candidates 8 --min-candidates 8 --complement-budget 3 --transduction-budget 3 --mockturtle-max-modes 1 --npn-max-support 6 --seed 0
```

Result:

```text
schedule stages completed: exact_match, base_coverage, complement, specialized, mockturtle
ex200 remained equivalent at ADP 59517
```

## Contest Plan Phase 9-11 Completion

Finished the remaining plan wiring from `AGENTS.md` without changing
`student/optimizer.py` or rewriting final AIGs.

Added CLI aliases and reproducibility helpers:

```bash
python3 student/flow_optimizer.py --write-contest-plan
python3 student/flow_optimizer.py --exact-match-all
python3 student/flow_optimizer.py --specialized-generate --case ex255
python3 student/flow_optimizer.py --verify-final
python3 student/flow_optimizer.py --write-final-summary
```

What changed:

- `--exact-match-all` is a clear alias for the proof-based exact function
  matcher.
- `--specialized-generate` is a clear alias for exact-match structural
  generation.
- `--verify-final` verifies the current `output/exNNN.aig` files and refreshes
  `student/logs/results.csv`, `student/logs/summary.csv`, and
  `student/logs/pareto_candidates.csv`.
- `--write-final-summary` also writes `student/logs/final_summary.csv`, which
  is easier to use in the final report because it combines per-case baseline,
  current ADP, improvement ratios, selected-method hints, method improvement
  counts, exact-match counts, equivalent-case count, and total ADP.
- `student/README.md` and `student/CONTEST_OPT_PLAN.md` now document the new
  commands.

## Post-Phase 11 Case-Fair Refinement Entry Point

Added a new deterministic optimizer command for the next real improvement pass:

```bash
python3 student/flow_optimizer.py --case-fair-next-optimize --all --seed 42 --timeout-per-case 30 --time-budget 3600
```

Purpose:

- Give every selected benchmark a balanced package instead of focusing only on
  high-ADP cases.
- Reuse existing verified structural stages in one reproducible command:
  objective-guided refine, micro-guided refine, small-case refine, complement
  rescue, and optional mockturtle structural resynthesis.
- Keep the safety rule unchanged: overwrite `output/exNNN.aig` only when ABC
  proves equivalence and the ADP is lower.

New log:

```text
student/logs/case_fair_next_optimize.csv
```

The command also refreshes final verification logs through
`--write-final-summary` behavior.

Runtime fix after smoke testing:

- The first all-case attempt exposed that each substage was receiving the full
  per-case timeout, making the combined command impractically long.
- `--timeout-per-case` now caps the total package for one case.
- `--time-budget` now caps the entire case-fair invocation.
- `case_fair_next_optimize.csv` is checkpointed after every completed case.
- The fair pass uses a compact deterministic package and divides each case
  budget across method families, so a single type-guided stage cannot consume
  the entire case allowance.
- Candidate counts and per-stage time are deliberately kept small in this
  post-phase pass; it is a coverage-oriented probe over all cases rather than
  another unbounded sweep.
- Removed repeated `type_guided` execution from this follow-up command after
  testing showed that recomputing full truth-table fingerprints can consume
  most of a case budget.  The existing main pipeline already applies
  fingerprint/type-guided synthesis before this final refinement pass.
- Made mockturtle opt-in under this final follow-up command with
  `--try-mockturtle`, since mode selection also invokes fingerprint analysis.
- During the initial attempt, already accepted candidates remained valid; full
  verification reported `100/100` equivalent and reduced total ADP from
  `11210226` to `11173589`.

### Current verified result after case-fair follow-up execution

The completed follow-up work retained only ABC-equivalent improvements and
finished with:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11165011
```

Compared with the pre-follow-up result:

```text
11210226 -> 11165011
ADP reduction: 45215
```

The all-case run checkpointed progress through `ex270`; the remaining
`ex271` through `ex299` range was run afterward and the final full
`--write-final-summary` verification restored the 100-case report logs.

### Final micro-guided convergence refinement

After the case-fair run, repeated deterministic micro-guided refinement proved
effective on both large and small cases:

```bash
python3 student/flow_optimizer.py --micro-guided-refine --all --micro-max-flows 4 --timeout-per-case 20
python3 student/flow_optimizer.py --write-final-summary
```

The accepted improvements primarily came from:

- `micro_resub4`: repeated local resubstitution and cleanup.
- `micro_if3`: compact low-cut remapping for selected cases.
- `micro_renode`: alternative local representation cleanup where it reduced
  ADP.

During testing, an older timed-out `case-fair-next-optimize` process was found
still running in WSL and modifying outputs concurrently.  It was stopped
before the final clean verification, so the result below has no active
optimizer process writing to `output/`.

Final verified result:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 11106756
```

Improvement relative to the pre-follow-up result:

```text
11210226 -> 11106756
ADP reduction: 103470
```

Reproduction update:

- Added `micro_guided_fixed_point_convergence` as stage 17 of
  `--reproduce-best`.
- It runs up to six deterministic all-case `micro_resub4` / `micro_if3` /
  `micro_renode` convergence passes and stops early when a pass finds no ADP
  improvement.
- This is required because `output/` is ignored by Git; the late convergence
  gains must be regenerated by the submitted command, not merely remain in a
  local output folder.
