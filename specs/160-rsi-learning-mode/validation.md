# Validation: RSI learning mode

The implementation is ready for the next phase only when these provider-free checks pass.

## Data and authority

- Canonical digests reject duplicate JSON keys, non-finite numbers, unknown fields and changed bytes.
- Contract, evaluator, environment and memory snapshot pins are present in every episode and cannot
  change during resume.
- A solver result with a score but without an intact official evaluator receipt is not authoritative.
- A `fail`, `unresolved`, `timed_out`, `abandoned`, `cancelled` or `unknown` episode cannot create an
  approved memory entry.
- Concurrent commits against one parent snapshot use compare-and-swap; one loses without merging.

## Verifier and transfer

- The verifier rejects receipt tampering, evaluator drift, duplicate ownership and workspace escapes.
- Actor private reasoning and mutable draft memory are unavailable to the verifier.
- Frozen transfer runs with `curriculum_enabled=false` and `memory_write_enabled=false`; an attempted
  write fails closed and leaves the snapshot unchanged.
- Transfer evidence is retained as a receipt and cannot retroactively promote memory.

## Recovery and scheduling

- DRS resumes the same target/practice episode after interruption and does not duplicate a terminal
  receipt.
- BRS launches all practices from one frozen wave snapshot and merges pass decisions in deterministic
  ordinal order only after the wave is complete.
- Worker `running`, `idle`, `completed`, `failed`, `cancelled` and `unknown` states map to explicit
  episode terminal/recovery states; `unknown` requires reconciliation.
- Changed solver settings, contract, evaluator, environment or memory snapshot are rejected on resume.

## Integration regression

- Existing Population, OpenEvolve, Shinka handoff, ordinary `MemoryStore`, Feature 044 experiment
  memory, candidate receipts and recovery tests remain green.
- Mock, Native Population, OpenEvolve fixture and Shinka export fixture can each be invoked through
  `SolverGateway` without gaining direct RSI memory access.
- Ruff, compileall and focused Feature 160 tests pass without provider credentials or WebAgent.

## Current local evidence

The provider-free regression command is:

```bash
PYTHONPATH=src pytest -q tests/test_rsi_cli.py tests/test_rsi_controller.py \
  tests/test_rsi_store.py tests/test_rsi_learning.py tests/test_rsi_gateway.py \
  tests/test_rsi_adapter_controller_integration.py
```

The CLI diagnostics only use local fixture solver IDs and persist to `rsi.sqlite3`; they do not
constitute evidence for real OpenEvolve, Shinka, OSWorld, or remote evaluator performance.
