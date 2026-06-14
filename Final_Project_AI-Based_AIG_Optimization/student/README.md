# Hybrid AIG Optimizer

Submitted optimizer for the AI-Based AIG Optimization final project.
Optimizes 100 Boolean circuits (`ex200`–`ex299`) by minimizing ADP = area × delay.

## Quick Start

```bash
bash student/reproduce_best.sh      # full pipeline, ~6–10 hours
python3 student/evaluate.py         # evaluate current output/ (minutes)
```

## Safety Contract

Every candidate AIG must pass two gates before replacing `output/<case>.aig`:

1. **ABC CEC equivalence** — proven identical to the original truth table
2. **Strict ADP decrease** — `new_area × new_delay < current_area × current_delay`

No candidate is ever adopted without both conditions satisfied.

---

## Optimization Pipeline

### Core Pipeline — Stages 1–17 (`flow_optimizer.py --reproduce-best`)

Runs deterministically over all 100 cases. Each stage tries a different
synthesis approach; only CEC-verified strict ADP improvements are kept.

| Stage | Method | Description |
|------:|--------|-------------|
| 1 | Boolean fingerprinting | Compute truth-table features: effective support, per-input influence, density, monotonicity, symmetry groups, Shannon split scores, ANF degree. Produce per-case labels used to select strategy in later stages. |
| 2 | Exact function recognition | Prove bit-exact matches against arithmetic templates: adder, multiplier, signed multiplier, square, divider quotient, integer square root. Confirmed matches unlock template-based initial candidates. |
| 3 | Initial candidate synthesis | Generate structurally diverse starting AIGs from truth table: ABC truth synthesis, SOP/POS covers, factored SOP, Shannon/BDD structures with deterministic variable orders, complement-first synthesis, arithmetic template seeds when exact match exists. |
| 4 | mockturtle structural resynthesis | Fingerprint-selected AIG/XAG/MIG/XMG algebraic rewriting via mockturtle. XAG modes (`xag_xor_heavy`, `roundtrip_xag`) reduce delay for high-delay multi-output cases. |
| 5 | ABC `&ttopt` synthesis | Truth-table structural synthesis with level-preserving transduction. Generates new AIG topology from truth table rather than rewriting the existing one. |
| 6 | Bounded `&deepsyn` resynthesis | Fixed-seed LUT map/unmap resynthesis. Bounded to stay deterministic. |
| 7 | `&my_deepsyn` area-Pareto | Area-first Pareto resynthesis for large equal-width multi-output cases (area ≥ 500). Sweeps the Pareto frontier and selects by ADP after fixed cleanup. |
| 8 | Yosys hybrid resynthesis | Route current AIG through Yosys AIG remap, then optionally through fingerprint-selected mockturtle resynthesis, then fixed ABC polish. Symbol-free AIGER bridge preserves primary-input ordering. |
| 9 | Compact vector Pareto probe | Detect low-ANF-degree compact vector functions; run iterative Pareto structural resynthesis. Expands budget only after a verified improvement is found. |
| 10 | Long-large structural rescue | For large-area high-ADP cases: synthesize new `&ttopt` topology seed from truth table, optimize with area-Pareto + DSD balancing. Longer search only if bounded probe already improves ADP. |
| 11 | Transduction rescue | Bounded equivalent expansion/reduction candidates. |
| 12 | Re-synthesis competition | 120-candidate budget: truth/SOP/factored-SOP/BDD/template seeds × ABC post-flows, competing against current `output/` AIG. Recovered 40 cases for −2,577 total ADP. |
| 13 | Complement-first synthesis | Synthesize complement of each output, negate; sometimes exposes smaller AIG topology. |
| 14 | Area-first refinement | Aggressive area flows applied to every case: `resub -K 10`, `dc2` loops, `fraig`, `dch; if -K 3/4`, GIA `compress2rs`, `&sopb -C 16 -R 1`, `&b -d -s`, plus two fresh truth-table re-synthesis candidates. |
| 15 | `&my_deepsyn -C area` all-case sweep | Area-first Pareto on every case with area ≥ 500. Covers LogicNets-style compact functions that benefit from structural-restart search. |
| 16 | Case-fair final refinement | Every case receives the same objective/micro/small/complement package, preventing any case from being systematically under-optimized. |
| 17 | GIA canonical convergence | Interleaved micro-guided resubstitution and GIA canonical cleanup, iterated until no further ADP improvement. |

---

### Block A — Semantic Front-End Reconstruction

Runs after the core pipeline on cases where structural optimization is
insufficient; targets arithmetic and float-like circuits.

**A1: Semantic split reconstruction** (`--semantic-split-optimize`)

Cases: `ex200 ex201 ex202 ex203 ex220 ex240 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex298 ex299`

Decomposes the circuit into sub-functions by splitting on candidate class
variables (sign bit, exponent byte, high nibble). Strategies tried per case:

- **Exponent/class split**: cofactor on each candidate class variable; synthesize
  each residual sub-function independently; merge into BLIF.
- **Field-pair split**: treat the two 8-bit operands as high-nibble + low-nibble
  pairs; synthesize paired residuals. Targets 16-bit conversion and unknown
  circuits whose two operands are packed byte-wise.
- **Shared-cofactor BDD**: cache residual BDDs across all outputs and all class
  values; duplicate residuals are emitted once and complemented copies reuse the
  cached signal through a single inverter.
- **Global shared multi-output BDD**: all outputs share one decision-node cache
  under several deterministic variable orders.

All equivalent candidates are logged to `student/logs/stage_semantic_split_log.csv`;
only strict ADP decreases are copied into `output/`.

**A2: Circuit-family refinement** (`--circuit-type-optimize`)

Cases: `ex223 ex225 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex299`

Fingerprints each case and applies a family-specific flow package:
- Threshold/majority logic uses delay-first flows distinct from general logic.
- Monotone-positive general logic uses a monotone delay/area package.
- Mixed constant-output cases (e.g. ex252) use a constant-aware flow family.
- Ambiguous cases get truth-table BDD seeds as alternative front-ends.

---

### Block B — Back-End Flow Refinement (`post_optimize.py`)

Equivalence-gated ABC flow search; adopts only strict ADP decreases.

| Step | Command | Cases | Description |
|------|---------|-------|-------------|
| B1 | `refine --case-workers 8` | all above-reference | Parallel ABC flow suite: `&resyn3rs`, `&sopb`, `resub -K N`, `dch+if`, `&compress2rs`, etc. Each case iterates until no flow yields improvement. |
| B2 | `refine --cases ex262` | ex262 | Targeted cleanup after B1 improved ex262. |
| B3 | `advanced --mode deepsyn` | high-ratio cases | Area-first `&my_deepsyn` pass for cases with high ADP ratio vs reference. |
| B4 | `refine --cases ex219 ex247 ex261` | ex219, ex247, ex261 | Cleanup after area-first pass exposes new local minima. |
| B5 | `advanced --mode semantic --case ex261` + refine | ex261 | Decoded semantic probe + cleanup for the signed 5×5 multiplier case. |
| B6 | Pareto → refine → area-first → objective → refine | ex295 | Full guarded cleanup tail for this persistently hard case (1.70x ratio). |

---

### Block C — Word-Level Semantic Reconstruction (`rtl_synth.py`)

For circuits whose arithmetic function was identified bit-exactly:
hand-write the Verilog, synthesize through Yosys + ABC + `&my_deepsyn -C adp`,
CEC-check against the original truth table, adopt only on strict improvement.

| Step | Family | Cases | Note |
|------|--------|-------|------|
| C1 | FP8 | ex240 (e4m3 add), ex241 (e4m3 mul), ex245 (e5m2 add) | ex240 and ex245 win vs structural AIG; ex241 identified but RTL loses |
| C2 | Signed multiplier | ex261 (5×5), ex262 (6×6), ex263 (7×7), ex264 (8×8) | Carry-save correction compresses sign terms with partial products |
| C3 | Integer isqrt | ex279 (16-bit) | Digit-by-digit non-restoring algorithm |

Cases in `IDENTIFIED_NONWINNING`: semantics confirmed, RTL synthesized and
CEC-verified, but structural AIG beats RTL on ADP — not run by default.

---

### Block D — Final Back-End Sweep (`flow_optimizer.py --optimize`)

Strongest equivalence-gated back-end search applied after all front-end
reconstruction stages. Four strategies tried in order per case:

- **flows**: broad ABC flow suite (14 flow combinations)
- **resynth**: truth-table re-synthesis competition (fresh candidates vs current AIG)
- **deepsyn**: `&my_deepsyn` ADP+area Pareto search
- **mockturtle**: structural AIG/XAG/MIG resynthesis

**D: All cases** — 90-second deepsyn budget, seeds {0, 42}, 6 parallel workers.

**D2: Long-search-sensitive cases** — 480-second deepsyn budget, seeds {0, 42, 7, 11}:
`ex242 ex243 ex247 ex248 ex249 ex251 ex262 ex289 ex205 ex264 ex263`

These cases only break through under a long multi-seed randomized search
(e.g. ex242 dropped from 15,285 to 11,040 found only at 480 s × 4 seeds).

---

### Block E — Evaluate, Verify, Record

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
python3 student/pipeline_bookend.py verify
python3 student/pipeline_bookend.py recipe --refresh
```

- **evaluate.py**: ABC CEC on all 100 cases + total ADP report.
- **verify**: compare `output/` against `best_output/`; non-zero exit if any
  case regressed. Because `reproduce_best.sh` uses `set -euo pipefail`, any
  regression aborts the entire pipeline.
- **recipe --refresh**: write `student/case_recipes/<case>.json` for each case
  with circuit-family labels, winning synthesis method, reference ratio, best
  area/delay/ADP with date, and append-only ADP history.

---

## Verification

```bash
# Full equivalence + ADP check (all 100 cases, ~5 min)
python3 student/evaluate.py

# Single case
python3 student/evaluate.py --case ex240

# Confirm no regression vs best_output/
python3 student/pipeline_bookend.py verify

# Print per-case recipe table sorted by ratio
python3 student/pipeline_bookend.py recipe --summary

# Print the 17-stage core pipeline description
python3 student/flow_optimizer.py --show-reproduce-recipe

# Boolean fingerprint + exact function analysis for one case
python3 student/flow_optimizer.py --classify-case ex240 \
  --abc student/abc --benchmarks benchmarks --output output --logs student/logs
```

---

## Results vs TA Reference

**Total ADP: 8,731,655 / Reference: 6,696,028 — overall ratio: 1.304×**

All 100 cases are equivalent (100/100 CEC pass).

### Distribution vs reference

| Category | Cases | Description |
|----------|------:|-------------|
| Beat reference (< 1.0×) | **15** | Strictly better than TA reference ADP |
| Within 5% (1.00–1.05×) | 11 | Very close to reference |
| Within 10% (1.05–1.10×) | 17 | Close to reference |
| 1.10–1.20× | 28 | Moderate gap |
| 1.20–1.50× | 17 | Significant gap |
| Above 1.50× | **12** | Hard cases — structural optimization insufficient |

### Cases beating the reference (15 total)

| Case | My ADP | Ref ADP | Ratio | Method |
|------|-------:|--------:|------:|--------|
| ex272 | 9,671 | 10,880 | 0.889 | structural deepsyn |
| ex276 | 576 | 632 | 0.911 | structural deepsyn |
| ex242 | 11,040 | 11,900 | 0.928 | Block D2 long deepsyn (480s) |
| ex284 | 3,936 | 4,240 | 0.928 | structural deepsyn |
| ex240 | 12,614 | 13,299 | 0.948 | Block C FP8 e4m3 add RTL |
| ex265 | 308 | 322 | 0.957 | structural deepsyn |
| ex280 | 2,310 | 2,415 | 0.957 | structural deepsyn |
| ex287 | 5,572 | 5,782 | 0.964 | structural deepsyn |
| ex245 | 10,659 | 11,050 | 0.965 | Block C FP8 e5m2 add RTL |
| ex243 | 51,680 | 53,227 | 0.971 | Block D2 long deepsyn (480s) |
| ex231 | 13,692 | 14,066 | 0.973 | structural deepsyn |
| ex207 | 614,916 | 627,817 | 0.979 | structural deepsyn |
| ex227 | 707,446 | 721,639 | 0.980 | structural deepsyn |
| ex298 | 436,696 | 442,296 | 0.987 | structural deepsyn |
| ex268 | 7,423 | 7,446 | 0.997 | structural deepsyn |

### Hard cases above 1.5× (12 total)

`ex286` (5.99×), `ex252` (4.81×), `ex250` (2.22×), `ex297` (2.21×),
`ex299` (2.21×), `ex225` (1.74×), `ex295` (1.70×), `ex223` (1.69×),
`ex248` (1.67×), `ex247` (1.63×), `ex246` (1.63×), `ex224` (1.60×)

These cases resist all applied strategies. `ex286` and `ex252` appear to
require a semantic front-end decomposition that has not yet been identified.
`ex297`/`ex299` are the two largest circuits (area > 25k) where even 480-second
deepsyn search yields no improvement.

---

## File Structure

```
student/reproduce_best.sh       entry point — runs full pipeline
student/flow_optimizer.py       core pipeline CLI (stages 1–17, Block A, Block D)
student/case_runners.py         per-stage optimization runners
student/blif_builder.py         BLIF/BDD generation from truth tables
student/candidate_gen.py        initial candidate synthesis
student/flow_library.py         ABC flow definitions and selection
student/result_logging.py       CSV logging for all stages
student/circuit_analysis.py     Boolean fingerprinting + exact function recognition
student/post_optimize.py        Block B: ABC flow refinement + area-first cleanup
student/rtl_synth.py            Block C: FP8 / signed multiplier / isqrt RTL
student/pipeline_bookend.py     Block E: verify (no regression) + recipe refresh
student/evaluate.py             evaluate output/ AIGs (works on Windows + WSL)
student/abc_core.py             ABC subprocess wrappers (CEC, measure_adp)
student/mockturtle_opt/         C++ mockturtle structural resynthesis binary
```

### Runtime-generated (not tracked in git)

```
output/ex2xx.aig                optimized AIG outputs
best_output/ex2xx.aig           best-known AIG for regression guard
student/logs/*.csv              per-stage optimization logs
student/case_recipes/ex2xx.json per-case method + ADP history
```
