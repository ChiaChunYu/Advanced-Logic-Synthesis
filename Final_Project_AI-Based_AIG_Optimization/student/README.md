# Flow Optimizer Usage

This file explains how to run `flow_optimizer.py`, the AI/LLM-guided ABC flow
search script for this project.

## Purpose

`optimizer.py` is the original baseline script. It only runs:

```text
read_truth -xf <benchmark>; st; write_aiger -s <output>
```

`flow_optimizer.py` is the improved optimizer. For each benchmark, it tries
multiple ABC optimization command flows, checks equivalence, measures area and
delay, then keeps the equivalent AIG with the lowest ADP:

```text
ADP = area * delay
```

## Basic Commands

Run one case quickly:

```bash
python3 student/flow_optimizer.py --case ex200 --fast
python3 evaluate.py --case ex200
```

Run one case with all candidate flows:

```bash
python3 student/flow_optimizer.py --case ex200
python3 evaluate.py --case ex200
```

Run all 100 benchmarks:

```bash
python3 student/flow_optimizer.py
python3 evaluate.py
```

## Output Files

The best AIG for each case is written to:

```text
output/exNNN.aig
```

The experiment summary is written to:

```text
student/results.csv
```

The CSV records each case's best flow, area, delay, ADP, and number of tried
flows. This file is useful when writing the final report.

## Useful Options

Use only the first few faster flows:

```bash
python3 student/flow_optimizer.py --fast
```

Run a single benchmark:

```bash
python3 student/flow_optimizer.py --case ex200
```

Keep temporary candidate AIG files for debugging:

```bash
python3 student/flow_optimizer.py --case ex200 --keep-temp
```

Temporary files are stored under:

```text
output/.optimizer_tmp/
```

Use a custom ABC executable:

```bash
python3 student/flow_optimizer.py --abc /path/to/abc
```

## Notes

- Correctness is checked before a candidate can become the final output.
- If no equivalent candidate is found, the script reports that case as `FAIL`.
- On Windows, the provided `student/abc` may not run directly. Use Linux, WSL,
  MobaXterm remote Linux, or provide a Windows-compatible ABC executable with
  `--abc`.
- Before submission, always run:

```bash
python3 evaluate.py
```

and confirm that all 100 cases are equivalent.
