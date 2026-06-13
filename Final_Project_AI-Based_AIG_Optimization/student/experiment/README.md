# Experiment Scripts

Exploratory scripts kept for auditability. The reproducible entry point is
`bash student/reproduce_best.sh`; nothing here is required by it.

## Function identification (semantic reverse-engineering)

Decode the word-level meaning of benchmarks, then verify a candidate exactly
against the truth table before any RTL is written. Winners graduate to a
`*_synth.py` in `student/`; the ones whose RTL loses to the structural AIG stay
documented here.

```text
identify_fp8.py      fp8 codec + RNE grid + op/format/rounding hypothesis sweep
check_fp8_rtl.py     Python emulation of the e4m3 add/mul/div datapaths vs truth
compact_fp8.py       compact FPU-shaped e4m3 algorithms (translate to Verilog)
verify_fp8_full.py   full 65536-row verification of fp8 hypotheses
check_e5m2.py        e5m2 (no-inf) add/mul — confirmed bit-exact (ex245/246)
refine_e5m2.py       e5m2 near-miss hypothesis diffing
check_fp16_log.py    fp16 log2 fixed-point datapath verification (ex224)
check_isqrt_rtl.py   non-restoring integer isqrt vs truth (ex275-279)
dsd_hard.sh          ABC &dsd / collapse probes on the uncrackable hard cases
```

## Identified but RTL does not win (kept for the record)

These functions are bit-exactly identified, but their LUT/iterative RTL is
deeper than the existing structural AIG, so they are not in the pipeline.

```text
fp16_synth.py        fp16 log2 (ex224) — verified, deepsyn floors above the BDD
square_synth.py      unsigned x^2 (ex270-274) — structural AIG already tighter
```

## Bulk / structural search drivers

Standalone versions of optimizations later folded into the pipeline
(`_phase_resynth_competition`, `optimize.py`). Kept for ad-hoc reruns; all write
to `output/` only on CEC-verified strict ADP improvement.

```text
resynth_all.py       re-synthesize every case from truth (now Phase 4)
full_sweep.py        multi-strategy sweep over all cases
hard_deepsyn.py      long &my_deepsyn area search for the hardest lagging cases
```
