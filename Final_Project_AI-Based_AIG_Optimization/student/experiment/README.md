# Experiment Scripts

This directory keeps exploratory scripts that were useful during development
but are not required by the final reproduction command.

The submitted, reproducible entry point remains:

```bash
bash student/reproduce_best.sh
```

Scripts in this folder may run focused searches, diagnostics, or one-off
analysis for individual cases. They are preserved for auditability, but the
clean reproduction path does not depend on them.

Current contents:

```text
aggressive_opt.py             early aggressive ABC portfolio probe
analyze*.py                   root-level truth/function reverse-engineering probes
analyze_fp8.py                FP8/BF16 conversion investigation helper
focus_ex252_pareto.py         focused ex252 Pareto/deepsyn probe
opt_single.py                 single-case experimental runner
overnight_opt.py              long-running batch experiment runner
parallel_opt.py               parallel experiment scheduler
run_remaining_casefair.sh     post-result case-fair experiment runner
run_remaining_rescue.sh       post-result rescue experiment runner
targeted_optimize.py          early high-ratio targeted optimizer
verify_ex261.py               ex261 semantic/debug verification helper
```
