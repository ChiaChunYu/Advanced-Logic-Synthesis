# Flow Optimizer Usage

This folder keeps the original baseline optimizer and the improved
circuit-type-aware optimizer separate.

## Files

- `optimizer.py`: original baseline script. Keep this unchanged as the simple
  reference implementation.
- `flow_optimizer.py`: AI/LLM-inspired circuit-type-aware optimizer. It analyzes
  each truth table, classifies the likely circuit type, searches ABC flows, checks
  equivalence, and keeps the equivalent AIG with the lowest ADP.

## Basic Commands

Run one benchmark:

```bash
python3 student/flow_optimizer.py --case ex200
python3 evaluate.py --case ex200
```

Run all 100 benchmarks:

```bash
python3 student/flow_optimizer.py --all
python3 evaluate.py
```

If your path contains spaces, run from the project root and pass relative paths:

```bash
python3 student/flow_optimizer.py --all --abc student/abc --benchmarks benchmarks --output output
python3 evaluate.py --abc student/abc --benchmarks benchmarks --output output
```

## Analysis Commands

Print extracted truth-table features:

```bash
python3 student/flow_optimizer.py --analyze-case ex200
```

Print the predicted circuit labels and classification reasons:

```bash
python3 student/flow_optimizer.py --classify-case ex200
```

## Useful Options

Limit the number of candidate flows per case:

```bash
python3 student/flow_optimizer.py --all --max-candidates 20
```

Use a deterministic random seed:

```bash
python3 student/flow_optimizer.py --all --seed 42
```

Set a per-case timeout:

```bash
python3 student/flow_optimizer.py --all --timeout-per-case 300
```

Keep temporary AIG files for debugging:

```bash
python3 student/flow_optimizer.py --case ex200 --keep-temp
```

## Outputs

Final selected AIGs are written to:

```text
output/exNNN.aig
```

Logs are written under:

```text
student/logs/
```

The main CSV log is:

```text
student/logs/results.csv
```

It records the case, labels, flow, ABC command sequence, area, delay, ADP,
equivalence result, and selected candidate.

## Notes

- Correctness is mandatory. A candidate is selected only after equivalence
  checking.
- The optimizer does not hardcode benchmark-specific final AIGs.
- On Windows, the provided `student/abc` is a Linux binary. Use Linux, WSL, or a
  remote Linux environment.
- Before submission, always run `python3 evaluate.py` and confirm all 100 cases
  are equivalent.
