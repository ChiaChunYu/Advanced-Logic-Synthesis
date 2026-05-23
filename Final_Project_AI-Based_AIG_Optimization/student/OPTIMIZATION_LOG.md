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
