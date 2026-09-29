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

## Durable budget and accounting

- A durable run checkpoint fixes `max_depth`, `max_solver_invocations`,
  `max_practice_episodes`, `max_unknown_retries`, and an absolute `deadline_unix`. Resume rejects a
  changed plan, a missing budget state, or `planned/consumed/remaining` values that cannot be
  reconstructed from the episode reservations.
- Before a solver launch the controller persists the episode's depth, ancestry and reservation.
  Depth overflow, a lineage cycle, an elapsed absolute deadline, or any exhausted launch/practice
  limit ends the run as `budget_exhausted`; resume of that terminal run issues no new gateway call.
- Unknown reconciliation has its own bounded counter. An exhausted reconciliation budget preserves
  the unknown evidence and ends the run as `budget_exhausted`; it cannot authorize an implicit retry.
- `RSIUsageReceipt` accepts only complete token triples, non-negative integer measurements, and
  reproducible estimates using receipt-bound micro-USD rates. Missing provider telemetry remains
  unavailable (`null`), never a synthetic zero. Its aggregation uses the observed controller wall
  clock rather than summing potentially concurrent BRS episode durations.
- Usage receipt validation is currently a local model-level check. Durable episode sidecars,
  run-level aggregation, CLI display, and adapter telemetry capture remain an open integration task;
  no provider usage or cost claim is inferred from `SolverResult`.

## Integration regression

- Existing Population, OpenEvolve, Shinka handoff, ordinary `MemoryStore`, Feature 044 experiment
  memory, candidate receipts and recovery tests remain green.
- Mock, Native Population, OpenEvolve fixture and Shinka export fixture can each be invoked through
  `SolverGateway` without gaining direct RSI memory access.
- Ruff, compileall and focused Feature 160 tests pass without provider credentials or WebAgent.

## Current local evidence

The provider-free regression command is:

```bash
PYTHONPATH=src:. python -m pytest tests/test_rsi_*.py \
  --basetemp /tmp/lunar-rsi-validation --junitxml=/tmp/lunar-rsi-validation.xml
```

The CLI diagnostics only use local fixture solver IDs and persist to `rsi.sqlite3`; they do not
constitute evidence for real OpenEvolve, Shinka, OSWorld, or remote evaluator performance.

Recovery now covers both a launched call with no retained outcome and an actual retained `unknown`
outcome. Explicit evidence can reconcile either to completion, failure, timeout, abandonment or
cancellation. Timeout/abandonment cannot create memory or silently reissue the original call.
Actor durable pins include full runtime/receipt profiles; native verifier replay reopens retained
evidence and checks inode/bytes without rerunning evaluation. The baseline command above exercises
local native subprocesses as well as fixtures; no external campaign is launched.

All controller paths, including the non-durable DRS and single frozen-transfer runner, require a
completed episode with its attached passing verifier decision before a custom target judge can
accept it. A judge can narrow acceptance; it cannot promote unknown, stopped or unverified work.

The same command includes `test_rsi_budget.py` and `test_rsi_usage.py`. The former exercises the
durable Phase 1 budget contract; the latter validates standalone receipt parsing and aggregation.
Neither test substitutes for real Actor, provider telemetry, solver campaign, or heldout-transfer
acceptance.
