# Mockturtle Structural Resynthesis Plan

## Header and Example Inspection

Local source tree inspected:

```text
student/mockturtle_src/
```

The current project also has the ABC executable at `student/abc`.  The Python
optimizer remains responsible for final equivalence checking and ADP selection.

## Available Network Types

- `aig_network`: supported by `mockturtle/networks/aig.hpp`.
- `xag_network`: supported by `mockturtle/networks/xag.hpp`.
- `mig_network`: supported by `mockturtle/networks/mig.hpp`.
- `xmg_network`: supported by `mockturtle/networks/xmg.hpp`.

## Available I/O

- AIGER read is available through `lorina/aiger.hpp` and
  `mockturtle/io/aiger_reader.hpp`.
- AIGER write is available through `mockturtle/io/write_aiger.hpp`.
- The `aiger_reader` can import AIGER into AIG-like networks such as AIG, XAG,
  MIG, and XMG when the target network implements the required constructors.
- `cleanup_dangling<Src, Dst>` supports conversion between AIG/XAG/MIG/XMG-like
  networks when the destination can construct the source node semantics.

## Available Algorithms

- AIG balancing:
  `mockturtle/algorithms/aig_balancing.hpp`, function `aig_balance`.
- XAG balancing:
  `mockturtle/algorithms/xag_balancing.hpp`, function `xag_balance`.
- Generic SOP/ESOP balancing:
  `mockturtle/algorithms/balancing.hpp`; available, but not used in the first
  tool version because direct AIG/XAG/MIG/XMG passes are simpler and safer.
- Refactoring:
  `mockturtle/algorithms/refactoring.hpp` with
  `node_resynthesis/sop_factoring.hpp`.
- AIG resubstitution:
  `mockturtle/algorithms/aig_resub.hpp`, functions `aig_resubstitution` and
  `aig_resubstitution2`.
- XAG resubstitution:
  `mockturtle/algorithms/xag_resub.hpp`, function `xag_resubstitution`.
- MIG resubstitution:
  `mockturtle/algorithms/mig_resub.hpp`, function `mig_resubstitution`.
- Cut rewriting:
  `mockturtle/algorithms/cut_rewriting.hpp`, with resynthesis engines such as
  `node_resynthesis/xag_npn.hpp`.
- Functional reduction:
  `mockturtle/algorithms/functional_reduction.hpp`, function
  `functional_reduction`.
- Akers synthesis:
  `mockturtle/algorithms/akers_synthesis.hpp`, function `akers_synthesis`.
  This is available, but the first tool version does not synthesize directly
  from multi-output project truth tables with Akers.
- XAG algebraic rewriting:
  `mockturtle/algorithms/xag_algebraic_rewriting.hpp`, function
  `xag_algebraic_depth_rewriting`.
- XAG optimization:
  `mockturtle/algorithms/xag_optimization.hpp`, functions including
  `xag_constant_fanin_optimization` and `xag_dont_cares_optimization`.
- MIG algebraic rewriting:
  `mockturtle/algorithms/mig_algebraic_rewriting.hpp`, function
  `mig_algebraic_depth_rewriting`.
- XMG algebraic rewriting:
  `mockturtle/algorithms/xmg_algebraic_rewriting.hpp`, function
  `xmg_algebraic_depth_rewriting`.
- XMG optimization:
  `mockturtle/algorithms/xmg_optimization.hpp`, function
  `xmg_dont_cares_optimization`.

## Structural Modes

The optional C++ tool supports the following command-line modes.  Unsupported or
failing modes exit with a non-zero code and a clear message; Python logs the
failure and keeps the existing output.

- `xag_xor_heavy`: imports the current AIG as XAG, runs XAG balance and
  algebraic rewriting, then writes an AIGER candidate.
- `mig_majority`: imports the current AIG as MIG, runs MIG algebraic rewriting
  and resubstitution, then writes an AIGER candidate.
- `xmg_arithmetic`: imports the current AIG as XMG, runs XMG algebraic rewriting
  and optimization, then writes an AIGER candidate.
- `aig_resub`: imports the current AIG as AIG, runs AIG balance, cut rewriting,
  refactoring, and resubstitution, then writes an AIGER candidate.
- `functional_reduction`: imports the current AIG as AIG, runs functional
  reduction, then writes an AIGER candidate.
- `roundtrip_xag`: XAG round-trip and optimization.
- `roundtrip_mig`: MIG round-trip and optimization.
- `roundtrip_xmg`: XMG round-trip and optimization.

## Python Strategy Mapping

`student/flow_optimizer.py --mockturtle-structural` uses
`student/boolean_fingerprint.py` to choose at most two structural modes per case:

- affine/parity labels: `xag_xor_heavy`, `roundtrip_xag`
- majority/threshold/carry/monotone/symmetric labels:
  `mig_majority`, `roundtrip_mig`
- arithmetic mixed XOR/majority labels:
  `xmg_arithmetic`, `roundtrip_xmg`
- general high-area or redundant-looking cases:
  `aig_resub`, `functional_reduction`

Every generated candidate is polished by a fixed ABC set, checked for
equivalence against the original truth table, measured with ABC `ps`, and only
accepted when ADP is lower than the current output.
