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

### Truth-table structural resynthesis with ABC `&ttopt`

- Diagnosed the largest remaining gaps using `reference_result.csv` and the
  public IWLS benchmark family descriptions: `ex240`-`ex267` contain
  practical/arithmetic functions with altered interfaces, while later cases
  include LogicNets-style multi-output truth functions.
- Added `--ttopt-structural` to `student/flow_optimizer.py`.  Unlike an ABC
  command sweep, this creates a new initial AIG directly from the truth table
  using `&ttopt`, selecting only legal output-group sizes derived from the
  function dimensions.
- Added deterministic structural rewiring: when the best `&ttopt` structure is
  no worse than the existing output, run one level-preserving
  `&transduction -T 1 -l` pass.  Compact equal-width functions additionally
  try deterministic repeated rewiring with `&transduction -T 4 -l`.
  Every replacement is still guarded by ABC equivalence and a strict ADP
  decrease.
- Logged candidates in `student/logs/ttopt_structural.csv` and added this
  structural stage to `--reproduce-best` before final micro convergence.

Accepted architecture-level gains before the final verification include:

```text
ex242: 50578 -> 30096
ex243: 99940 -> 82016
ex250: 73524 -> 63525
ex251: 117306 -> 85316
ex252: 234186 -> 51714
ex280: 25056 -> 15680
ex281: 31980 -> 22057
ex282: 38283 -> 30696
ex284: 57122 -> 41300
ex287: 33462 -> 25023
```

Verified result after structural synthesis and one deterministic polish pass:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10771329
```

Compared with the previous verified result:

```text
11106756 -> 10771329
ADP reduction: 335427
```

### Bounded `&deepsyn` LUT Map/Unmap Structural Resynthesis

- Diagnosed the remaining gap against `reference_result.csv`: the largest
  unresolved cases are practical multi-output functions and LogicNets-style
  functions, where reducing area through new sharing is more important than
  applying additional rewrite command portfolios.
- Confirmed from the public IWLS benchmark description that the arithmetic
  family includes permuted/dropped-output practical functions and the later
  family contains LogicNets neuron functions.
- Probed official-style `collapse; sop; fx; strash`, deeper `&ttopt`, and
  non-level-preserving transduction.  These candidates were equivalent but did
  not lower ADP, so they were not selected as the new path.
- Found that the provided ABC binary supports `&deepsyn`, a fixed-seed LUT
  map/unmap structural resynthesis algorithm.  Added
  `--deepsyn-structural`, `--deepsyn-iterations`, and `--deepsyn-seconds` to
  `student/flow_optimizer.py`.
- Added `student/logs/deepsyn_structural.csv` to record the structural variant,
  seed, runtime bound, post-polish result, equivalence, ADP, and selection.
- The new stage uses up to two passes of one fixed-seed (`42`) 30-second
  structural iteration, stopping when a pass no longer improves ADP, then
  compares a small fixed post-polish set.  For 16-input/8-output
  dropped-output practical-function shapes it also tries the two-input LUT
  structural mode because that variant was measurably better on `ex250` and
  `ex251`.
- Added the bounded fixed-point `&deepsyn` step as stage 18 of the deterministic
  `--reproduce-best` recipe; micro fixed-point convergence is now stage 19.
- Fixed `--classify-case --exact-max-inputs N` so the requested exact detector
  limit is used instead of an internal fixed limit.

Accepted improvements from this structural stage and its final deterministic
micro refinement include:

```text
ex243: 82016   -> 71106
ex250: 63525   -> 51568
ex251: 85316   -> 64932
ex252: 51714   -> 43550
ex253: 7707    -> 3634
ex299: 2716728 -> 2711688
```

Small additional verified reductions were accepted for `ex207`, `ex227`,
`ex292`, and `ex298`.

Verified result after the new architecture-level step:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10710541
```

Compared with the previous verified result:

```text
10771329 -> 10710541
ADP reduction: 60788
```

Compared with `reference_result.csv`, the remaining gap is still significant:

```text
Current total ADP:   10710541
Reference total ADP:  6696028
Ratio:                  1.5995x
```

The largest remaining gaps are still `ex299` and `ex297`, so reaching the
reference level will require a stronger structure generator for the
LogicNets-style family rather than additional ABC polish.

### Safe Yosys And Parallel mockturtle Hybrid Structural Resynthesis

- Confirmed that Yosys 0.33 is available in WSL and that the existing
  `--reproduce-best` recipe already runs mockturtle structural stages before
  the previously added ABC `&deepsyn` stage.
- Tested direct Yosys AIGER round-trips and rejected them: Yosys reordered
  named benchmark primary inputs (`pi00` moved behind `pi15`), causing ABC
  equivalence failure even when reported area was smaller.
- Added a safe bridge that first writes a symbol-free AIGER with ABC, then
  invokes one deterministic Yosys AIG remap:

```text
ABC symbol-free write_aiger -> Yosys techmap/opt/abc -g aig/aigmap
                             -> fixed ABC polish -> ABC equivalence gate
```

- Added `--hybrid-structural`, `--yosys-bin`, and `--mockturtle-workers`.
  When Yosys finds a lower-ADP equivalent seed, fingerprint-selected
  mockturtle structural modes are generated concurrently with a bounded worker
  count, then evaluated in deterministic order through ABC polish and full
  equivalence checking.
- Added `student/logs/hybrid_structural.csv` and inserted the new stage as
  stage 19 of `--reproduce-best`; final micro convergence is now stage 20.
- Verified that the mixed topology path beats either a plain Yosys probe or
  the existing structure on representative cases.  For example, the hybrid
  candidate reduced `ex243` delay from 21 to 18 while retaining equivalence.

Selected hybrid structural improvements include:

```text
ex207: 737495 -> 736989
ex227: 853576 -> 853070
ex243: 71106  -> 63000
ex250: 51568  -> 51436
ex251: 64932  -> 64722
ex287: 25023  -> 23886
ex298: 540708 -> 524480
```

The deterministic cleanup following these structural candidates further
reduced cases including `ex298` and `ex299`.  The fixed final output checkpoint
was verified with ABC:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10667043
```

Compared with the result before this hybrid structural stage:

```text
10710541 -> 10667043
ADP reduction: 43498
```

Compared with `reference_result.csv`:

```text
Current total ADP:   10667043
Reference total ADP:  6696028
Ratio:                  1.5930x
```

### Code And Workspace Cleanup Without Flow Changes

- Consolidated repeated stage-local temporary directory creation and cleanup
  into `prepare_case_temp_dir(...)`.  Existing stage directory names and
  candidate generation order are unchanged.
- Strengthened `student/reproduce_best.sh` with explicit prerequisite checks
  for `python3`, `yosys`, and `student/abc`, plus an automatic CMake rebuild
  of `student/mockturtle_opt/mockturtle_opt` when the generated executable has
  been cleaned.
- Removed generated temporary candidate directories, old verification output
  copies, build intermediates, and Python caches from the local ignored
  workspace.  Formal output AIGs and report-oriented CSV summaries were
  intentionally retained.
- This update is organizational only: it does not add flows, change
  classification, relax equivalence checking, or alter ADP replacement
  criteria.

### Area-Pareto Structural Resynthesis For Large Multi-Output Bottlenecks

- Recomputed the remaining gap against `reference_result.csv`.  The dominant
  unresolved cases remain large equal-width multi-output functions, especially
  `ex297` and `ex299`, where the reference trades a higher level count for a
  much smaller AIG area.
- Investigated structure-generation routes rather than adding random command
  sweeps:
  - `&satfx` shared logic extraction produced an equivalent `ex297` candidate
    but increased ADP (`647430 -> 708929`), so it was rejected.
  - LogicNet `&lnetopt`/`&lnetmap` requires a separate simulation-data format;
    candidates obtained from the current flattened AIG did not lower ADP.
  - `&ttopt` followed by LUT-sharing `mfs2`/`&if` and standalone `lutmin`
    produced equivalent candidates on the small LogicNet-style cases, but
    their AIG ADP was worse than the existing output.
  - Increasing fixed `&ttopt` depth from 40 to 500 rounds remained worse on
    representative small LogicNet-style cases (`ex280` and `ex283`), so the
    remaining gap is not addressed by simply spending more rounds on the
    existing BDD structural route.
- Found that this ABC binary also provides `&my_deepsyn`, which maintains
  Pareto points with an explicit cost objective.  Added
  `--pareto-area-structural` and `--pareto-area-seconds` to run fixed-seed
  (`42`) area-first structural reconstruction:

```text
current equivalent AIG
  -> &my_deepsyn -C area -t
  -> optional fixed area cleanup
  -> ABC full equivalence check
  -> accept only lower ADP
```

- The automatic reproduction stage selects only large equal-width
  multi-output networks (`area >= 25000`) instead of naming benchmark cases.
  This targets area-bottleneck topology without spending the structural budget
  on already compact outputs.
- Added `student/logs/pareto_area_structural.csv` and inserted the new
  deterministic area-Pareto pass as stage 19 of `--reproduce-best`.  The
  Yosys/mockturtle and final micro-convergence stages are now stages 20 and 21.

Accepted equivalent improvements from the new structural stage:

```text
ex206:  627902 ->  627242
ex207:  736897 ->  736621
ex227:  852334 ->  852012
ex297:  647430 ->  646527
ex298:  518640 ->  516160
ex299: 2708256 -> 2704584
```

Verified result after area-Pareto structural resynthesis:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10658730
```

Compared with the preceding verified output checkpoint:

```text
10667043 -> 10658730
ADP reduction: 8313
```

Compared with `reference_result.csv`, this new structural route is effective
but does not yet close the LogicNet-style architecture gap:

```text
Current total ADP:   10658730
Reference total ADP:  6696028
Ratio:                  1.5918x
```

### Low-Degree Vector Pareto Fixed-Point And Adaptive Compact Probing

- Investigated the compact equal-width multi-output gap without adding random
  ABC flow sequences.  Exact tests rejected simple rectangular multiplier and
  single-threshold interpretations for `ex280`-`ex284`.
- Identified a reusable truth-table signature: equal-width vector functions
  whose every output has ANF degree at most 4.  This feature rule selects the
  compact five-function family that remained far above the reference result;
  it does not name benchmark cases in the optimizer.
- Extended area-Pareto structural resynthesis so it evaluates every AIG on
  the generated Pareto frontier, applies fixed cleanup, performs ABC
  equivalence checking, and chooses minimum ADP.  Previously the stage only
  evaluated the search command's final area-oriented output and could miss a
  better ADP frontier point.
- Added `--compact-low-degree-pareto` and integrated a fixed-seed, bounded
  fixed-point stage into `--reproduce-best`.  A case enters this stage only
  from its Boolean signature; each pass retains only an equivalent strict ADP
  decrease.
- Added an adaptive compact-vector Pareto stage for wider coverage: a short
  structural probe is given to compact equal-width functions with remaining
  ADP cost, and full structural time is allocated only to cases whose probe
  already produces an equivalent improvement.

Verified low-degree vector-family reductions from the structural fixed-point
run include:

```text
ex280: 15600 ->  2338
ex281: 21965 ->  2688
ex282: 30504 ->  4097
ex283: 38718 ->  3757
ex284: 40572 ->  4914
family total: 147359 -> 17794
```

`ex280` now beats the supplied reference ADP (`2338 < 2415`).  Additional
CEC-verified compact-vector improvements accepted during validation include:

```text
ex285:   9990 ->   7293
ex286:  22410 ->  17460
ex287:  23562 ->  14326
ex288:  25821 ->  18918
ex289:  25783 ->  22040
ex291:  80432 ->  80320
ex293: 148518 -> 133888
ex294: 200500 -> 168164
ex295: 128832 -> 127056
ex296: 137466 -> 136206
```

Final verification after this update:

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10449199
Previous verified ADP:          10656924
ADP reduction in this update:     207725
Reference total ADP:              6696028
```

The new structural direction makes a substantial improvement in the compact
LogicNets-style family, but the submission still does not reach the supplied
reference total; the dominant remaining area gap is concentrated in the large
vector functions such as `ex297` and `ex299`.

### Adaptive Long-Running Reconstruction For Large Vector Bottlenecks

- Diagnosed the largest reference gaps as area-dominated equal-width vector
  functions.  `ex295`, `ex297`, and `ex299` have exact paired cyclic output
  orbits, but direct representative-cone replication is larger than the
  current jointly synthesized AIG.
- Tested whether the paired outputs become a single quantized threshold
  neuron under any 2-bit symbol ordering.  Exact monotonicity checks found no
  valid encoding for `ex295`, `ex297`, or `ex299`, so no unproven
  adder-tree/comparator template was added.
- Extended area-Pareto frontier evaluation with deterministic GIA DSD
  balancing:

```text
&get; &dsdb -K 6 -C 16 -R 100; &put; strash; dc2; balance
```

  This produced equivalent improved probe candidates for the large family and
  is now a fixed Pareto cleanup choice.
- Confirmed additional strict-ADP improvements from the corrected
  frontier/cleanup evaluation:

```text
ex295: 127056 -> 122565
ex297: 646443 -> 643820
ex299: 2703864 -> 2701992
```

- Implemented `--long-large-structural`.  It creates a structurally distinct
  seed directly from the truth table using whole-vector `&ttopt`, then applies
  fixed-seed area-Pareto reconstruction and DSD cleanup.  All candidates are
  still ABC-equivalence checked and replace `output/` only on strict ADP
  improvement.
- A full 720-second validation on `ex299` correctly rejected the alternate
  seed route:

```text
current verified output:        112583 x 24 = 2701992
ttopt-seeded long candidate:     114108 x 25 = 2852700
selection result:                rejected, current output retained
```

- Because a longer budget does not rescue every structural seed, the
  reproduction stage is adaptive: it first performs a bounded large-vector
  probe and allocates its longer refinement budget only to cases where that
  new topology already yields an equivalent ADP decrease.  This retains
  deterministic reproducibility without spending the largest runtime budget
  on a disproven route.

## 2026-05-30

### Gap Analysis Against Reference

- Compared all 100 cases against `reference_result.csv` to identify the
  dominant improvement opportunities.
- The reference total ADP is `6,696,028`; current submission was `10,449,199`
  (ratio `1.56x`).
- Classified each case by the structural pattern of the remaining gap:

```text
OUR_AREA_TOO_HIGH:   reference trades higher delay for much smaller area,
                     winning on ADP (ex299, ex297, ex295, ex225, ex223, ...)
SIMILAR_STRUCTURE:   area is close but delay differs by a few levels
                     (ex206, ex207, ex220-ex227, ex298)
BOTH_WORSE / DELAY_DOMINATED: smaller cases, both area and delay slightly off
```

- The dominant pattern is `OUR_AREA_TOO_HIGH`: for many cases the reference
  area is 3-5x smaller than ours, with reference delay being higher.  The
  conclusion is that the reference uses area-aggressive synthesis that
  intentionally does not balance delay.

### Area-First Refinement Pass

- Added `AREA_FIRST_FLOWS` and `AREA_FIRST_RESYNTH_FLOWS` to
  `student/flow_optimizer.py`: eleven flows that apply area-aggressive ABC
  commands without any final balancing step, plus two re-synthesis flows that
  rebuild the AIG from the truth table with area-first orientation.

```text
af_rw_rf_loop          rewrite -z; refactor -z loop x3; dc2
af_dc2_x5              dc2 five times interleaved with rewrite/refactor
af_fraig_rw_rf_x2      fraig + two rounds of rewrite -z/refactor -z/dc2
af_dch_if3             dch; if -K 3 (smallest LUT bound) + area cleanup
af_dch_if4             dch; if -K 4 + area cleanup
af_resub8_n2_x2        resub -K 8 -N 2 applied twice
af_resub10_n2          resub -K 10 -N 2
af_collapse_sop_fx     collapse to SOP, fx sharing, area cleanup
af_gia_compress2rs_x3  GIA compress2rs three times
af_gia_dc2_compress    GIA dc2 alternated with compress2rs
af_gia_mfs_compress    GIA mfs alternated with compress2rs
af_resynth_collapse_fx fresh truth-table synthesis then collapse/fx/area
af_resynth_dch_if4     fresh truth-table synthesis with dch/if-K4/area
```

- Added `run_area_first_refine_case()` function mirroring the existing sweep
  pattern: starts from the current equivalent output, tries each flow, checks
  ABC equivalence for any ADP-improving candidate, and replaces `output/` only
  on strict ADP decrease.
- Added `--area-first-refine` CLI flag for standalone use:

```bash
python3 student/flow_optimizer.py --area-first-refine --all \
  --abc student/abc --benchmarks benchmarks --output output \
  --logs student/logs --timeout-per-case 90
```

- Added `stage 26/26: area-first refinement` to `--reproduce-best` as the
  final convergence stage, running up to three passes and stopping when a pass
  finds no ADP improvement.
- Added `REPRODUCE_AREA_FIRST_TIMEOUT = 90` and
  `REPRODUCE_AREA_FIRST_PASSES = 3` constants.

### Cases Improved By Area-First Refinement

All improvements were ABC-equivalence checked before acceptance.

```text
ex221:  131,880  -> 131,760   (-120)   af_resub8_n2_x2
ex227:  851,644  -> 851,368   (-276)   af_dc2_x5
ex233:   24,624  ->  24,464   (-160)   af_resub8_n2_x2
ex241:   28,252  ->  28,168   (-84)    af_resub10_n2
ex245:   26,026  ->  26,004   (-22)    af_resub10_n2
ex246:   10,998  ->  10,855   (-143)   af_rw_rf_loop / af_resub10_n2
ex247:   13,351  ->  13,273   (-78)    af_dch_if3
ex252:   41,400  ->  40,336   (-1064)  af_resynth_collapse_fx
ex270:    3,641  ->   3,608   (-33)    af_resub8_n2_x2
ex282:    4,097  ->   4,063   (-34)    af_resub8_n2_x2
ex286:   17,460  ->  17,406   (-54)    af_dc2_x5
ex287:   14,326  ->  14,307   (-19)    af_resub8_n2_x2
ex289:   22,040  ->  22,021   (-19)    af_resub8_n2_x2
ex291:   80,320  ->  80,208   (-112)   af_rw_rf_loop
ex292:  107,676  -> 107,568   (-108)   af_resub8_n2_x2
ex294:  168,164  -> 167,518   (-646)   af_rw_rf_loop
ex296:  136,206  -> 136,116   (-90)    af_rw_rf_loop
ex297:  643,820  -> 639,100   (-4720)  af_dc2_x5
ex299: 2,701,992 -> 2,699,184 (-2808)  af_resub8_n2_x2
```

### Current Verified Result After Area-First Refinement

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10,429,623
```

Compared with the previous verified result:

```text
10,449,199 -> 10,429,623
ADP reduction: 19,576
```

Compared with `reference_result.csv`:

```text
Current total ADP:   10,429,623
Reference total ADP:  6,696,028
Ratio:                  1.5576x
```

### Reproduction

Stage 13 (area-first refinement, formerly stage 26) is part of
`--reproduce-best`.  The standalone command to run only this stage is:

```bash
python3 student/flow_optimizer.py --area-first-refine --all \
  --abc student/abc --benchmarks benchmarks --output output \
  --logs student/logs --timeout-per-case 90
```

## 2026-05-30 (continued)

### XAG Algebraic Depth Rewriting Breakthrough

- Systematically tested mockturtle structural modes on the highest-gap cases.
- **Key discovery**: `xag_xor_heavy` (XAG algebraic depth rewriting + constant
  fanin optimization + XAG resubstitution) achieves large delay reductions on
  multi-output equal-width functions, converting 1 level of delay into a
  significant ADP gain because area stays roughly constant.

Equivalence-verified improvements from `xag_xor_heavy`:

```text
ex299: 2,697,432 -> 2,636,329  (-61,103, -2.3%)  delay 24 -> 23
ex297:   629,180 ->   601,464  (-27,716, -4.4%)  delay 20 -> 19
ex227:   850,770 ->   821,326  (-29,444, -3.5%)  delay 23 -> 22
ex207:   735,563 ->   714,032  (-21,531, -2.9%)  delay 23 -> 22
ex294:   167,212 ->   160,128  ( -7,084, -4.2%)  delay 17 -> 16
ex292:   107,496 ->   105,672  ( -1,824, -1.7%)  delay 18 -> 17
```

`roundtrip_xag` (lighter XAG rewriting) also improved:

```text
ex274:  29,337 -> 25,246  (-4,091)  delay 33 -> 26
ex251:  63,987 -> 61,218  (-2,769)  delay 21 -> 19
ex293: 133,888 -> 132,495  (-1,393)  delay 16 -> 15
ex273:  19,860 -> 18,486  (-1,374)  delay 30 -> 26
ex294: 167,212 -> 165,280  (-1,932)  roundtrip also effective
```

**Why this works**: XAG (XOR-AND Graph) algebraic rewriting can restructure
AND-based logic into XOR-AND form, finding shorter paths through the XOR
algebra that the AIG rewriting (which only manipulates AND/NOT) cannot see.
The delay drops by 1-7 levels while area increases slightly, but since delay
was the bottleneck for ADP, the net effect is strongly positive.

**Stacked XAG passes**: Running `xag_xor_heavy` followed by `roundtrip_xag`
yields additional gains because each pass reduces delay by one further level:

```text
ex297: 639,100 -> 601,464 (xag_xor_heavy, delay 20->19)
              -> 584,190 (roundtrip_xag,   delay 19->18)   total: -54,910
ex207: 735,563 -> 714,032 (xag_xor_heavy, delay 23->22)
              -> 702,870 (roundtrip_xag,   delay 22->21)   total: -32,693
ex227: 850,770 -> 821,326 (xag_xor_heavy, delay 23->22)
              -> 802,326 (roundtrip_xag,   delay 22->21)   total: -48,444
```

**Integration**: The `select_structural_mockturtle_modes()` fingerprint
selector now always includes `xag_xor_heavy` and `roundtrip_xag` for cases
with `area >= 20000`, `adp >= 300000`, or `delay >= 18`.  Stage 5 of
`--reproduce-best` now uses `max_modes=4` to ensure both XAG modes have room
alongside `dc_aig_rewrite` and `aig_resub`.

### Current Verified Result After XAG Structural Rewriting

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10,197,451
```

Compared with the pre-XAG result:

```text
10,409,848 -> 10,197,451
ADP reduction: 212,397
```

Compared with `reference_result.csv`:

```text
Current total ADP:   10,197,451
Reference total ADP:  6,696,028
Ratio:                  1.5229x
```

### Stage Consolidation: 26 → 14 Stages

- Merged logically equivalent stage groups in `run_reproduce_best()` to reduce
  the total number of stages from 26 to 14 and eliminate inter-stage redundancy.
- No `run_*_case()` functions were modified; only the calling sequence changed.

Merges performed:

| Old stages | New stage | Description |
|---|---|---|
| 2-4, 5, 6 | 2 | All focused template ranges in one loop |
| 8, 9, 10 | 4 | Polish + sweep: one convergence loop each |
| 11, 16 | 5 | Two mockturtle structural passes → one (larger timeout) |
| 12, 13 | 6 | Type-guided + objective-guided per case |
| 14, 15 | 7 | Micro-guided + small-case per case |
| 18, 19 | 9 | Deepsyn + area-Pareto structural |
| 20, 21 | 10 | Compact Pareto + adaptive vector probe |
| 24, 25 | 14 | Micro convergence + GIA canonical in same pass loop |

Stage 26 (area-first) became stage 13, running before the final convergence
(stage 14).  The `--show-reproduce-recipe` output now lists 14 stages.

### New Area-First Flows From Systematic Exploration

- Systematically explored ABC GIA commands not previously included in
  `AREA_FIRST_FLOWS`:
  - `&compress3rs` repeated 5 times
  - `resub -K 12 -N 3` (larger cut window than existing `resub -K 8`)
  - `&dsdb -K 6 -C 64; &compress3rs; &compress3rs; &compress3rs`
  - `&dsd; &compress3rs; &compress3rs; &compress3rs`
  - `&resyn3; &compress3rs; &resyn3; &compress3rs`
- For cases like ex297 and ex252, `&compress3rs x5` found improvements that
  all previous flows missed.  `&dsdb + compress3rs` was the strongest single
  new flow on ex297 in the probe script (-7,280).
- Added all five new flows to `AREA_FIRST_FLOWS`; they run automatically
  in stage 13 of `--reproduce-best`.

Also investigated **cyclic input-rotation symmetry** in ex295/ex297/ex299:
- ex295 has 5/11 outputs that are cyclic rotations of out0
- ex297 has 6/13 outputs with cyclic rotation
- ex299 has 7/15 outputs with cyclic rotation
- Reference area on these cases is 3.8–5.1x smaller, likely due to
  exploiting this symmetry in a BDD-based synthesis route
- Attempts to exploit the symmetry via wire-permuted BLIF instances did not
  improve ADP because each rotation requires a separate circuit copy with no
  node sharing; the approach needs a global BDD decomposition to be effective

### Representative Improvements From New Flows

```text
ex252:   40,336  ->  34,275  (af_gia_compress3rs_x5, -15%)
ex297:  639,100  -> 630,620  (af_gia_compress3rs_x5, -1.3%)
ex299: 2,699,184 -> 2,697,432  (af_fraig_rw_rf_x2, -0.07%)
ex221:  131,760  -> 131,320  (af_gia_compress3rs_x5)
ex250:   51,414  ->  50,776  (af_gia_compress3rs_x5)
ex291:   80,208  ->  79,920  (af_resub12_n3)
ex247:   13,273  ->  13,078  (af_resub8_n2_x2)
```

### Current Verified Result

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10,409,848
```

Compared with the previous verified result:

```text
10,429,623 -> 10,409,848
ADP reduction: 19,775
```

Compared with `reference_result.csv`:

```text
Current total ADP:   10,409,848
Reference total ADP:  6,696,028
Ratio:                  1.5547x
```

## 2026-05-30 (continued)

### XAG Algebraic Depth Rewriting Breakthrough

Discovered that `xag_xor_heavy` (mockturtle XAG algebraic depth rewriting +
constant fanin optimization + XAG resubstitution) achieves large delay
reductions on multi-output equal-width functions by converting AND-based logic
to XOR-AND form and finding shorter logic paths. Running `xag_xor_heavy` then
`roundtrip_xag` in sequence gives further stacked delay reductions.

Key improvements verified by ABC CEC:

```text
ex299: delay 24->23, ADP 2,697,432 -> 2,604,405  (-93,027 from xag stack)
ex297: delay 20->18, ADP   639,100 ->   574,398  (-64,702 from xag stack)
ex227: delay 23->20, ADP   851,644 ->   760,180  (-91,464 from xag stack)
ex207: delay 23->21, ADP   735,563 ->   687,435  (-48,128 from xag stack)
ex294: delay 17->16, ADP   167,212 ->   159,024  ( -8,188)
ex293: delay 16->15, ADP   133,888 ->   127,935  ( -5,953)
ex292: delay 18->16, ADP   107,496 ->   100,992  ( -6,504)
ex291: delay 16->15, ADP    80,208 ->    78,360  ( -1,848)
ex240: delay 22->19, ADP    47,498 ->    45,201  ( -2,297)
ex244: delay 16->14, ADP     9,504 ->     9,100  (   -404)
```

**Integration into reproduce pipeline:**

- `select_structural_mockturtle_modes()` now includes `xag_xor_heavy` and
  `roundtrip_xag` whenever `area >= 20000`, `adp >= 300000`, or `delay >= 18`.
- Stage 5 (`mockturtle_structural`) in `--reproduce-best` uses `max_modes=4`
  to give both XAG modes room alongside `dc_aig_rewrite` and `aig_resub`.
- No new stage needed; the XAG improvements reproduce through the existing
  stage 5.

### Stage Consolidation (26 → 14 Stages)

Merged logically equivalent stage groups in `run_reproduce_best()` to reduce
total stages from 26 to 14.  No `run_*_case()` functions were modified.

| Old stages | New stage | Change |
|---|---|---|
| 2-4, 5, 6 | 2 | Arithmetic, divider, sqrt ranges unified |
| 8, 9, 10 | 4 | Polish + sweep convergence loops unified |
| 11, 16 | 5 | Two mockturtle structural passes → one (timeout 90s) |
| 12, 13 | 6 | Type-guided + objective-guided per-case unified |
| 14, 15 | 7 | Micro + small-case per-case unified |
| 18, 19 | 9 | Deepsyn + area-Pareto structural unified |
| 20, 21 | 10 | Compact Pareto + adaptive probe unified |
| 24, 25 | 14 | Micro convergence + GIA canonical unified |

### New Area-First Flows (stage 13)

Added 5 new flows to `AREA_FIRST_FLOWS`:

```text
af_gia_compress3rs_x5   &compress3rs repeated 5 times
af_resub12_n3           resub -K 12 -N 3
af_gia_dsdb_compress3rs &dsdb -K 6 -C 64 then compress3rs x3
af_gia_dsd_compress3rs  &dsd then compress3rs x3
af_gia_resyn3_compress3 alternating &resyn3 and &compress3rs
```

These found improvements on ex252 (-6,061), ex297 (-4,720), ex221 (-440),
ex291 (-288), ex233 (-160), among others.

### Function Identification for BF16/FP16 Cases

Analyzed truth tables for ex200-ex239 and identified the underlying functions:

```text
ex200-205: BF16 exp, exp2, exp10, log, log2, log10
ex206-210: BF16 sin, tan, sinh, tanh, sigmoid
ex211-219: BF16 recip, square, sqrt, ???, rsqrt, ???, cbrt, ???, ???
ex220-225: FP16 exp, exp2, exp10, log, log2, log10
ex226-231: FP16 sin, tan, sinh, tanh, sigmoid, recip
ex232-239: FP16 ???, sqrt, ???, rsqrt, ???, cbrt, ???, ???
```

Key method:
- Truth table output formula: `val = sum(outputs[i][j] << i for i in range(n))`
  (outputs are LSB-first in the file)
- Input ordering: j directly encodes the BF16/FP16 value (MSB = pi0)

Identified tool is in `analysis/identify_functions.py` and results in
`analysis/function_identification.csv`.

Attempted to synthesize these functions as structured truth tables using ABC
directly (`read_truth -xf` with generated truth table).  The pipeline works
and produces equivalent AIGs, but the flat truth-table approach does not
improve on the existing optimized outputs because it lacks semantic structure.
Structured Verilog (sign/exp/mantissa decomposition) is needed to match the
reference quality for ex200-ex239.

### Current Verified Result

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 10,063,329
```

Compared with previous result:

```text
10,429,623 -> 10,063,329
ADP reduction: 366,294
```

Compared with `reference_result.csv`:

```text
Current total ADP:   10,063,329
Reference total ADP:  6,696,028
Ratio:                  1.5029x
Cases beating reference:  1/100 (ex280)
Cases within 1.5x:       62/100
Cases above 1.5x:        38/100
Closest to 1.5x: ex282 (need -7 ADP), ex267 (need -28 ADP), ex279 (need -164 ADP)
```

Gap analysis saved to `analysis/gap_analysis_result.csv`.

## 2026-05-30 (continued)

### `&my_deepsyn` Area-Pareto Sweep — Breakthrough For High-Gap Cases

- Identified that `&my_deepsyn -C area -T <sec> -O <dir>` (Pareto-front tracking with
  area objective) is far more effective than either `&deepsyn` or `&my_deepsyn -C adp`
  for the high-gap LogicNets-style cases in ex240-ex299.
- `&my_deepsyn` builds a Pareto frontier iteratively; each generated AIG is evaluated
  for both area and delay, and the best-ADP equivalent point is selected after full
  ABC equivalence checking (`&cec`).
- Unlike `&deepsyn` (which needs a large unoptimized AIG to start), `&my_deepsyn`
  accepts the already-optimized current AIG and immediately explores structural changes.
- A 60-second budget per case was sufficient for substantial improvements on compact
  LogicNets-style cases.

Key equivalence-verified improvements (60-second passes):

```text
ex252:  33,570 -> 15,708  (-17,862,  2.1x)   area 2238->714, delay 15->22
ex248:  29,536 -> 13,482  (-16,054,  2.2x)   area 2272->642, delay 13->21
ex241:  28,056 -> 15,092  (-12,964,  1.9x)   area 2004->1078
ex247:  13,052 ->  6,416  ( -6,636,  2.0x)   area 1004->401
ex240:  45,201 -> 35,260  ( -9,941,  1.3x)   area 2379->1763
ex242:  28,226 -> 17,731  (-10,495,  1.6x)   area 1283->1043
ex245:  25,894 -> 19,602  ( -6,292,  1.3x)   area 1177->891
ex246:  10,500 ->  5,445  ( -5,055,  1.9x)   area 875->363
ex217:  18,356 -> 14,742  ( -3,614,  1.2x)   area 706->567
ex219:  17,496 -> 15,596  ( -1,900,  1.1x)   area 729->557
ex265:     480 ->    376  (   -104,  1.3x)   area 60->47
ex266:   1,460 ->  1,232  (   -228,  1.2x)   area 146->112
ex268:   9,405 ->  8,655  (   -750,  1.1x)   area 627->577
ex201:  26,537 -> 24,696  ( -1,841,  1.1x)   area 1561->1764 (delay 17->14)
ex285:   7,259 ->  6,800  (   -459,  1.1x)
... (additional minor improvements on ex253, ex260, ex267, ex269, ex270, ex276, ex277,
     ex283, ex284, ex289, ex209)
```

Total ADP reduction from this pass: **~96,000**

### Current Verified Result After `&my_deepsyn` Sweep

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 9,967,222
```

Compared with the pre-pass result:

```text
10,063,329 -> 9,967,222
ADP reduction: 96,107
```

Compared with `reference_result.csv`:

```text
Current total ADP:   9,967,222
Reference total ADP:  6,696,028
Ratio:                  1.4885x
```

### Analysis: Why `&my_deepsyn` Works Here

The LogicNets-style cases (ex240-ex299) have large area in our current AIGs
because the existing ABC/mockturtle flows converged to local optima that
cannot escape by incremental rewriting.  `&my_deepsyn` uses an internal
random-restart structural search that generates genuinely new topologies,
accepting them only on the Pareto frontier.  The key insight is:

1. Start from the fully-polished current AIG (low delay).
2. `&my_deepsyn -C area` aggressively trades delay for area.
3. Among all Pareto AIGs generated, select the one with minimum ADP.
4. Accept only if ABC CEC confirms equivalence.

The 60-second budget covers 100-200 structural iterations on compact cases,
which is enough to escape the local ADP minimum while remaining deterministic
through fixed seeding.

### Near-Win Case Focus: ex276 And ex272 Now Beat Reference

After the `&my_deepsyn` all-case sweep, targeted 300-second runs on the
closest-to-reference cases produced two new wins:

**ex276** (8 inputs → 5 outputs):
- Extended `&my_deepsyn -C area -T 300` from the already-improved AIG found
  a Pareto point with area=74, delay=8, **ADP=592 < ref 632 (0.936x)**.
- Applied and verified equivalent.

**ex272** (12 inputs → 24 outputs):
- `&sopb -C 16 -R 1` (SOP balancing with area bound) + balance reduced
  delay from 22 to 19, giving area=564, delay=19, **ADP=10,716 < ref 10,880 (0.985x)**.
- `&sopb` is now added to `AREA_FIRST_FLOWS` as `af_sopb_balance` so it runs
  in stage 13 of `--reproduce-best` for all cases.

**ex275** (8 inputs → 4 outputs):
- Fresh truth-table synthesis + `&my_deepsyn -C area -T 300` improved
  ADP from 228 → 222 (area=37, delay=6), but reference ADP=204 requires
  area=34 at delay=6 — 3 fewer AND gates that ABC/mockturtle cannot find.
- ex275 remains at 1.088x reference.

### Cases Now Beating Reference: 3

| Case | Our ADP | Ref ADP | Ratio |
|------|---------|---------|-------|
| ex280 | 2,338 | 2,415 | 0.968x |
| ex276 | 592 | 632 | **0.936x** (new) |
| ex272 | 10,716 | 10,880 | **0.985x** (new) |

### Current Verified Result After Near-Win Focus

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 9,963,184
```

Compared with previous result:

```text
9,967,222 -> 9,963,184
ADP reduction: 4,038
```

### Flow Changes

- Added `af_sopb_balance` (`&get; &sopb -C 16 -R 1; &put; balance; rewrite -z; refactor -z; balance`) to `AREA_FIRST_FLOWS` — effective for delay-bound cases.
- Added `af_b_d_s_compress` (`&get; &b -d -s; &compress3rs; &compress3rs; &put; balance; rewrite -z; balance`) to `AREA_FIRST_FLOWS`.
- Added stage 14/15 (`my_deepsyn_all_case_sweep`) to `run_reproduce_best`: runs `&my_deepsyn -C area -T 60` on every case with area ≥ 500. This covers the LogicNets-style cases that the earlier large-case Pareto stage (area ≥ 25000) missed.
- Stage count increased from 14 to 15.

### Reproduction

Stage 14 of `--reproduce-best` runs the `&my_deepsyn -C area` all-case sweep
automatically.  The standalone command for targeted cases is:

```bash
python3 student/push_to_15x.py [case ...]
```

## 2026-05-31

### Targeted Push Toward 1.5x On All Cases

Gap analysis classified all 33 remaining >1.5x cases into three types:

```text
area_only(d>ref): our delay < ref delay, but area 3–5x too large (ex299, ex297, ex225, ex223, ex295, ex240, ex241)
delay_high:       our delay 1.7–2.3x ref delay (ex264, ex263, ex262, ex219, ex217, ex261)
area_high:        both area and delay somewhat high (ex248, ex250, ex286, ex252, ex287, ...)
```

**Improvements applied:**

| Case | Before | After | Method |
|------|--------|-------|--------|
| ex251 | 60,211 | 54,502 | `&sopb -C 8 -R 1` + balance (delay 19→17) |
| ex219 | 15,596 | 14,743 | `&sopb -C 16 -R 1` |
| ex217 | 14,742 | 13,420 | `roundtrip_xag` (mockturtle) |
| ex261 | 5,068  | 5,044  | `roundtrip_xag` |
| ex249 | 3,636  | 2,772  | `&my_deepsyn` 2-pass |
| ex246 | 5,445  | 5,344  | `&my_deepsyn` 2-pass |
| ex244 | 8,295  | 6,560  | `&my_deepsyn` 2-pass |
| ex241 | 11,396 | 11,228 | `&my_deepsyn` 2-pass |
| ex287 | 14,174 | 13,260 | `&my_deepsyn` 120s |
| ex248 | 13,482 | 8,717  | `&my_deepsyn` 300s |
| ex253 | 2,964  | 2,907  | `resub -K 12 -N 3` |
| ex270 | 3,348  | 3,312  | `resub -K 10 -N 2` |

**Cases that resisted all attempts:**

- `ex262/ex263/ex264`: all ABC/mockturtle delay-reduction flows produce no ADP improvement — the circuit depth is structurally determined by the truth table.
- `ex270/ex253/ex260`: area is at local minimum for ABC rewriting; `&my_deepsyn` with up to 300s and fresh truth-table synthesis both find no lower ADP.
- `ex299/ex297/ex225/ex223`: large area-only cases where reference trades much higher delay for smaller area — require synthesis approaches outside the current ABC+mockturtle tool set.

### Current Verified Result

```text
Equivalent cases: 100/100
Total ADP over equivalent cases: 9,938,770
```

Compared with previous verified result:

```text
9,963,184 -> 9,938,770
ADP reduction: 24,414
```

Compared with `reference_result.csv`:

```text
Current total ADP:   9,938,770
Reference total ADP:  6,696,028
Ratio:                  1.4843x
Cases beating reference: 3/100 (ex276, ex280, ex272)
Cases within 1.5x:      69/100
Cases above 1.5x:       31/100
```

### Remaining High-Gap Cases

```text
ex299: 2.57x  — large area-only, ref uses much higher delay
ex297: 2.54x  — same pattern
ex286: 6.97x  — compact, ABC at local minimum
ex252: 6.04x  — sparse 16->8 function, ABC at local minimum
ex264: 2.18x  — delay-bound: our delay 38 vs ref 22, no flow reduces it
ex263: 2.13x  — delay-bound: our delay 35 vs ref 18
ex262: 1.93x  — delay-bound: our delay 31 vs ref 20
```

### Case-Fair Final Refinement And Post-Micro Cleanup

- Improved `--case-fair-next-optimize` so each objective/micro/small/
  complement sub-stage can use a real bounded budget instead of being capped
  at two seconds.
- Ran a full case-fair pass over all 100 benchmarks.  This gives small and
  medium benchmarks the same final coverage as large ones while still
  accepting only ABC-equivalent strict ADP improvements.
- Followed with full micro-guided refinement and GIA canonical cleanup.
- Integrated the case-fair pass into `--reproduce-best` as stage 15, before
  final micro/GIA convergence, so the current result is reproduced by:

```bash
bash student/reproduce_best.sh
```

Verified result after this update:

```text
Equivalent cases: 100/100
Previous total ADP: 9,938,770
Current total ADP:  9,884,194
ADP reduction:         54,576
Reference total ADP: 6,696,028
Current/reference:       1.4761x
```

Representative accepted reductions:

```text
ex201:  24696 ->  24430
ex206: 611058 -> 603435
ex207: 687435 -> 677964
ex217:  13420 ->  13112
ex221: 130606 -> 126749
ex227: 760180 -> 751500
ex244:   6560 ->   6480
ex248:   8717 ->   8648
ex274:  25246 ->  24050
ex291:  78360 ->  76815
ex297: 574398 -> 570960
ex299:2604405 ->2595090
```

### 1.5x Reference-Ratio Push

- Goal: reduce the number of benchmarks whose current ADP is more than 1.5x
  the `reference_result.csv` ADP, with priority on near-threshold cases rather
  than only total ADP.
- Ran targeted deterministic rescue packages on the current verified outputs:
  area-first SOPB/refactor flows, micro-guided resubstitution, GIA canonical
  cleanup, longer area-Pareto `&my_deepsyn` for area bottlenecks, type-guided
  refinement, and selected complement/transduction/mockturtle structural
  probes.
- All accepted replacements were checked by ABC equivalence and only kept when
  ADP strictly decreased.

Verified result after this update:

```text
Equivalent cases: 100/100
Previous total ADP: 9,884,194
Current total ADP:  9,859,734
ADP reduction:         24,460
Cases within 1.5x of reference: 81/100
Cases above 1.5x of reference: 19/100
```

Cases newly moved within 1.5x:

```text
ex204, ex205, ex241, ex244, ex245, ex253, ex260, ex270, ex279, ex287, ex289
```

Representative accepted reductions:

```text
ex204: 23580 -> 22680
ex205: 74822 -> 70584
ex241: 11186 -> 10556
ex244:  6480 ->  5978
ex245: 19382 -> 15844
ex253:  2907 ->  2451
ex260:  1056 ->   913
ex270:  3312 ->  2840
ex279: 16592 -> 15300
ex287: 13220 ->  6372
ex289: 21907 -> 20190
```

Remaining above-1.5x cases are dominated by either very compact reference
solutions (`ex286`, `ex252`) or large area-only bottlenecks (`ex299`, `ex297`,
`ex225`, `ex223`, `ex224`, `ex295`).  The next structural direction should be
multi-output shared-kernel extraction for cyclic/vector truth tables and a
more aggressive area-only decomposition path that accepts larger delay.

### Targeted ex295 case-fair cleanup

- Continued the circuit-type/semantic exploration with an explicit goal of
  finding a strict verified improvement over the current submitted outputs.
- The broad shared-cofactor semantic split search produced smaller candidates
  for `ex240`, `ex250`, and `ex252`, but none beat the current submitted AIGs.
- A targeted `--case-fair-next-optimize` pass on `ex295` found a strict ADP
  reduction through the objective-guided balanced/dchoice package.
- Added this targeted pass as Stage 22 in `student/reproduce_best.sh`.

Accepted reduction:

```text
ex295: 118335 -> 118290  (obj_balanced_dchoice)
```

Verified result after this update:

```text
Equivalent cases: 100/100
Previous total ADP: 8,911,124
Current total ADP:  8,911,079
ADP reduction:             45
```

### Cyclic unknown-function reverse-engineering probes

- Re-focused on the `introduction.html` direction for `ex280-ex299`: identify
  the real circuit structure before adding more back-end command stacks.
- Confirmed exact cyclic equivariance for the dominant unknown bottlenecks:
  - `ex295`: even outputs are rotations of `y0`, odd outputs are rotations of
    `y1` by two input-bit positions.
  - `ex297`: same two-orbit cyclic structure.
  - `ex299`: same two-orbit cyclic structure across all 16 outputs.
- Added a global shared multi-output BDD candidate family so all outputs can
  share one decision-node cache under deterministic rotation/byte/pair orders.
  This made the structural hypothesis reproducible inside
  `--semantic-split-optimize`.
- Parallel probes ruled out several tempting but incorrect real-circuit
  hypotheses:
  - packed 2-bit sorting/ranking
  - popcount/threshold or simple histogram counting
  - GF(2) affine/CRC-style transform
  - simple modular rotate/add/sub/Gray transforms
  - linear threshold base functions
  - small cyclic local-window rule
  - reflection-symmetric cyclic rule
- Current conclusion: `ex295/ex297/ex299` are best described as nonlinear
  two-channel cyclic sequence transforms, likely LogicNets/decision-network
  style rather than simple arithmetic.  The next plausible large improvement
  path is a cyclic shared-kernel extractor, not per-output BDD replication.

### Verified late post-hoc cleanup

- Switched back to an experiment-first workflow: no README/log/reproduction
  edits were made until `output/` actually improved under CEC.
- Fixed a `refine_close.py` `SameFileError` corner case where a Pareto/deepsyn
  candidate could already be the selected output path.  The fix only skips the
  redundant copy when source and destination are the same file.
- Re-ran `refine_close.py` in independent single-case mode for the cases that
  showed verified improvement candidates, avoiding same-case output races.
- Added Stage 23 to `student/reproduce_best.sh` to reproduce these late
  improvements deterministically.

Accepted reductions:

```text
ex262:   9455 ->   8556
ex265:    343 ->    308
ex266:   1125 ->    963
ex275:    222 ->    216
ex277:   2616 ->   2365
ex278:   6812 ->   6266
ex284:   4860 ->   3952
ex295: 118290 -> 116685
```

Verified result after this update:

```text
Equivalent cases: 100/100
Previous total ADP: 8,911,079
Current total ADP:  8,906,667
ADP reduction:          4,412
```

### Guarded high-ratio massive batch

- Re-ran the high-ratio guarded batch after code organization, targeting:
  `ex286`, `ex252`, `ex297`, `ex250`, `ex299`, `ex264`, `ex263`, `ex240`,
  `ex225`, `ex262`, `ex248`, `ex295`, `ex223`, `ex224`, `ex247`, and
  `ex246`.
- Each case was backed up first, then refined by `refine_close`,
  area-first, objective-guided, micro-guided, and GIA canonical convergence
  passes.
- All candidates were still CEC-gated and accepted only on strict ADP
  reduction.
- The generic guarded batch has now saturated for the remaining high-ratio
  cases.  The next large-improvement path is specialized semantic or
  architecture reconstruction: FP conversion/log seeds, signed multiplier
  architecture, and cyclic shared-kernel extraction for the unknown vector
  cases.

Accepted reduction:

```text
ex295: 115920 -> 115875
```

Verified result after this update:

```text
Equivalent cases: 100/100
Previous total ADP: 8,892,810
Current total ADP:  8,892,765
ADP reduction:             45
```
