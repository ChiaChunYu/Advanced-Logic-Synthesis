# Hybrid AIG Optimizer

Submitted optimizer for the AI-Based AIG Optimization final project.
Optimizes 100 Boolean circuits (`ex200`–`ex299`) by minimizing ADP = area × delay.

---

## Setup

**Execution environment:** Linux or WSL is required — `student/abc` is a Linux ELF binary and cannot run natively on Windows. `student/evaluate.py` handles WSL path conversion automatically for Windows users.

**Required tools:**

| Tool | Version | How to get |
|------|---------|------------|
| Python | 3.8+ | pre-installed on most Linux distros |
| ABC | — | pre-built at `student/abc` (included in repo) |
| Yosys | any recent | `sudo apt install yosys` |
| mockturtle | — | pre-built at `student/mockturtle_opt/mockturtle_opt` (included in repo) |
| cmake | 3.14+ | only needed if mockturtle binary missing: `sudo apt install cmake` |

**No Python packages need to be installed** — all scripts use the standard library only.

**Setup steps:**
1. Clone the repo and enter the project directory
2. Make ABC executable: `chmod +x student/abc`
3. If `student/mockturtle_opt/mockturtle_opt` is missing, `reproduce_best.sh` will build it automatically via cmake
4. Verify Yosys is available: `yosys --version`

---

## How to Reproduce

```bash
bash student/reproduce_best.sh      # full pipeline, ~6–10 hours
python3 student/evaluate.py         # evaluate current output/ (~5 min)
python3 student/evaluate.py --case ex240   # single case
```

`reproduce_best.sh` runs the complete pipeline end-to-end:
Core stages 1–17 → Block A → Block B → Block C → Block D/D2 → Block E.

Every replacement is equivalence-gated — a candidate AIG is only adopted if it is CEC-verified and has strictly lower ADP than the current output. Because each block's output feeds into the next, exact reproduction is not guaranteed across different machines or ABC versions.

---

## Architecture

The optimizer uses a multi-stage hybrid pipeline with four layers:

**1. Boolean Fingerprinting & Function Recognition**
Analyze truth-table features (support, influence, density, ANF degree, symmetry) to label each circuit and identify arithmetic functions (adder, multiplier, signed multiplier, isqrt).

**2. Semantic / Word-Level Reconstruction**
For identified arithmetic circuits, synthesize hand-written Verilog through Yosys + ABC + `&my_deepsyn` and adopt only if the RTL AIG beats the structural result on ADP.

**3. Structural Front-End Synthesis**
Generate diverse AIG candidates from the truth table: ABC truth synthesis, SOP/BDD/Shannon structures, mockturtle AIG/XAG/MIG/XMG rewriting, Yosys remapping, `&ttopt`/`&deepsyn` search.

**4. Equivalence-Gated Back-End Optimization**
Refine all candidates through ABC flow suites and `&my_deepsyn` Pareto search with increasing budgets (90s → 480s). Every replacement requires CEC equivalence + strict ADP decrease.

---

## Optimization Pipeline

### Core — Stages 1–17 (`flow_optimizer.py --reproduce-best`)

Runs over all 100 cases. Each stage tries a different synthesis approach; only CEC-verified strict ADP improvements are kept.

| Stage | Method | Description |
|------:|--------|-------------|
| 1 | Boolean fingerprinting | Compute truth-table features: support, per-input influence, density, monotonicity, symmetry groups, Shannon split scores, ANF degree. Produce per-case labels for later stages. |
| 2 | Exact function recognition | Prove bit-exact matches against arithmetic templates: adder, multiplier, signed multiplier, square, divider, integer square root. |
| 3 | Initial candidate synthesis | Generate diverse starting AIGs: ABC truth synthesis, SOP/POS/factored-SOP, Shannon/BDD structures, complement-first synthesis, arithmetic template seeds. |
| 4 | mockturtle structural resynthesis | Fingerprint-selected AIG/XAG/MIG/XMG algebraic rewriting. XAG modes reduce delay for high-delay multi-output cases. |
| 5 | ABC `&ttopt` synthesis | Synthesize new AIG topology directly from truth table using level-preserving transduction. |
| 6 | Bounded `&deepsyn` resynthesis | Fixed-seed LUT map/unmap resynthesis, bounded to stay deterministic. |
| 7 | `&my_deepsyn` area-Pareto | Area-first Pareto resynthesis for large cases (area ≥ 500). Selects by ADP after Pareto sweep. |
| 8 | Yosys hybrid resynthesis | Route AIG through Yosys remap + optional mockturtle + ABC polish. |
| 9 | Compact vector Pareto probe | Iterative Pareto resynthesis for low-ANF-degree functions. Expands budget only after a verified improvement. |
| 10 | Long-large structural rescue | For large high-ADP cases: new `&ttopt` seed + area-Pareto + DSD balancing. |
| 11 | Transduction rescue | Bounded equivalent expansion/reduction candidates. |
| 12 | Re-synthesis competition | 120-candidate budget: truth/SOP/BDD/template seeds × ABC post-flows competing against current AIG. |
| 13 | Complement-first synthesis | Synthesize complement of each output, negate; sometimes exposes smaller topology. |
| 14 | Area-first refinement | Aggressive area flows: `resub -K 10`, `dc2` loops, `fraig`, `dch+if`, `compress2rs`, `&sopb`, `&b -d -s`. |
| 15 | `&my_deepsyn -C area` all-case sweep | Area-first Pareto on every case with area ≥ 500. |
| 16 | Case-fair final refinement | Every case receives the same objective/micro/small/complement package. |
| 17 | GIA canonical convergence | Interleaved micro-guided resubstitution and GIA canonical cleanup, iterated until no ADP improvement. |

---

### Block A — Semantic Front-End Reconstruction

Runs after core stages on cases where structural optimization is insufficient. Decomposes circuits into sub-functions by splitting on candidate class variables (sign bit, exponent byte, high nibble) using exponent/class split, field-pair split, shared-cofactor BDD, and global multi-output BDD strategies.

- **A1** (`--semantic-split-optimize`): `ex200 ex201 ex202 ex203 ex220 ex240 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex298 ex299`
- **A2** (`--circuit-type-optimize`): `ex223 ex225 ex250 ex252 ex262 ex263 ex264 ex286 ex297 ex299`

---

### Block B — Back-End Flow Refinement (`post_optimize.py`)

Equivalence-gated ABC flow search; adopts only strict ADP decreases.

| Step | Cases | Description |
|------|-------|-------------|
| B1 | all above-reference | Parallel ABC flow suite: `&resyn3rs`, `&sopb`, `resub -K N`, `dch+if`, `&compress2rs`, etc. |
| B2 | ex262 | Targeted cleanup after B1. |
| B3 | high-ratio cases | Area-first `&my_deepsyn` pass. |
| B4 | ex219, ex247, ex261 | Cleanup after area-first pass exposes new local minima. |
| B5 | ex261 | Decoded semantic probe + cleanup for the signed 5×5 multiplier. |
| B6 | ex295 | Full guarded cleanup tail: Pareto → refine → area-first → objective → refine. |

---

### Block C — Word-Level Semantic Reconstruction (`rtl_synth.py`)

Hand-write Verilog, synthesize through Yosys + ABC + `&my_deepsyn -C adp`, CEC-verify, adopt only on strict ADP improvement.

| Step | Family | Cases |
|------|--------|-------|
| C1 | FP8 | ex240 (e4m3 add), ex241 (e4m3 mul), ex245 (e5m2 add) |
| C2 | Signed multiplier | ex261 (5×5), ex262 (6×6), ex263 (7×7), ex264 (8×8) |
| C3 | Integer isqrt | ex279 (16-bit) |

---

### Block D — Final Back-End Sweep (`flow_optimizer.py --optimize`)

Strongest equivalence-gated search after all front-end stages. Strategies per case: broad ABC flows, truth re-synthesis, `&my_deepsyn` Pareto, mockturtle resynthesis.

- **D**: all cases — 90s deepsyn, seeds {0, 42}, 6 workers
- **D2**: `ex242 ex243 ex247 ex248 ex249 ex251 ex262 ex289 ex205 ex264 ex263` — 480s deepsyn, seeds {0, 42, 7, 11}. These cases only break through under long multi-seed search (e.g. ex242: 15,285 → 11,040 found only at 480s × 4 seeds).

---

### Block E — Evaluate, Verify, Record

```bash
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
python3 student/pipeline_bookend.py verify
python3 student/pipeline_bookend.py recipe --refresh
```

---

## Results vs TA Reference

**Total ADP: 8,731,655 / Reference: 6,696,028 — overall ratio: 1.304×**

All 100 cases are equivalent (100/100 CEC pass).

| Category | Cases |
|----------|------:|
| Beat reference (< 1.0×) | **15** |
| Within 5% (1.00–1.05×) | 11 |
| Within 10% (1.05–1.10×) | 17 |
| 1.10–1.20× | 28 |
| 1.20–1.50× | 17 |
| Above 1.50× | **12** |

75 out of 100 cases (75%) are within 1.2× of the reference. The remaining gap is dominated by 12 hard cases where structural optimization has reached its limit — `ex286` (5.99×) and `ex252` (4.81×) in particular appear to require semantic decomposition strategies that have not yet been identified.

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
