# Mockturtle Structural Optimizer

This optional tool generates structural AIG candidates for
`student/flow_optimizer.py`.  The Python optimizer still performs ABC
equivalence checking and ADP-based selection before any output is overwritten.

Build:

```bash
cmake -S student/mockturtle_opt -B student/mockturtle_opt/build
cmake --build student/mockturtle_opt/build --target mockturtle_opt -j
```

Run one candidate:

```bash
./student/mockturtle_opt/mockturtle_opt \
  --input-truth benchmarks/ex200.truth \
  --input-aig output/ex200.aig \
  --output-aig student/logs/tmp_mockturtle/ex200.aig \
  --mode aig_resub
```

Supported modes:

```text
xag_xor_heavy
mig_majority
xmg_arithmetic
aig_resub
functional_reduction
roundtrip_xag
roundtrip_mig
roundtrip_xmg
```

Unsupported or failed modes exit non-zero and print a short error message.

Python integration:

```bash
python3 student/flow_optimizer.py --mockturtle-structural --timeout-per-case 45
python3 student/flow_optimizer.py --mockturtle-case ex200 --mode xag_xor_heavy --timeout-per-case 120
```

The Python optimizer logs candidates to `student/logs/mockturtle_candidates.csv`
and only copies a candidate into `output/` after ABC equivalence checking and a
lower ADP measurement.
