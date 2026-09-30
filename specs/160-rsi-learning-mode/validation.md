# Validation: RSI learning mode

This file records the local acceptance boundary. The DRS/BRS interruption matrix, CLI repeat-run
checks and frozen-transfer recovery tests have passed locally. On 2026-09-30 the RSI suite passed
**289 tests**, with no failures or skips (`/tmp/lunar-rsi-final-combined02.xml`). Ruff, compileall
and `git diff --check` passed. T160-13 stage 1 still has open recovery interfaces listed below.
An isolated export of the staged source also passed all **289 tests**
(`/tmp/lunar-rsi-index-validation.xml`), source compilation, Ruff and an import check of every
public API export. This excludes unrelated, uncommitted producer source from the evidence.
A passing fixture matrix is not evidence that every external worker or callback recovery path has
been implemented.

## Data and authority

- Canonical digests reject duplicate JSON keys, non-finite numbers, unknown fields and changed bytes.
- Contract, evaluator, environment and memory snapshot pins are present in every episode and cannot
  change during resume.
- A solver result with a score but without an intact official evaluator receipt is not authoritative.
- A `fail`, `unresolved`, `timed_out`, `abandoned`, `cancelled` or `unknown` episode cannot create an
  approved memory entry.
- Concurrent commits against one parent snapshot use compare-and-swap; one loses without merging.

## Verifier and transfer

- The local verifier checks request identity, worker outcome and required receipt bindings. These
  fixtures do not reopen artifacts in a clean workspace or rerun an independent official evaluator.
- Actor traces expose bounded public observations rather than private reasoning. Isolation and
  artifact validation by a real verifier remain separate acceptance work.
- Frozen transfer runs with `curriculum_enabled=false` and `memory_write_enabled=false`; an attempted
  write fails closed and leaves the snapshot unchanged.
- Transfer evidence is retained as a receipt and cannot retroactively promote memory. Transfer
  recovery must preserve the original request, snapshot, component fingerprints and budget; a
  published receipt is replayed without a second gateway/verifier/judge invocation.
- `FrozenMemoryTransferRunner` persists a started gate before verifier/judge callbacks. If the
  callback starts but its result is not persisted, recovery stops at the gate instead of blindly
  repeating it. This specific gate is not yet implemented for DRS/BRS verifier/curriculum/judge.
- A published unknown transfer receipt remains immutable after an explicit worker settlement.
  The current runner returns `rsi_transfer_unknown_receipt_reconcile_required`; a dedicated receipt
  reconciliation path has not been implemented.

## Recovery and scheduling

- The v2 journal persists the DRS/BRS plan and launch intents. DRS reconstructs its completed
  target/practice, verifier and memory steps, then may launch the next previously unstarted episode
  from that original plan. A running episode whose result is unknown is never dispatched again.
- Legacy checkpoints without the complete plan recover existing evidence only; they do not infer
  a missing wave or silently start new episodes.
- BRS launches all practices from one frozen wave snapshot and merges pass decisions in deterministic
  ordinal order only after the wave is complete.
- A `running` episode without a result requires recovery; `unknown` requires evidence-bound
  reconciliation. A blocked child prevents the entire wave from merging. Explicit terminal
  reconciliation must be consumable without rewriting the original result envelope.
- Fresh runs and resume share one controller lock. A live run excludes a competing run or resume,
  and repeated terminal resume does not change run history or increase side-effect counts.
- A crash between terminal checkpoint publication and run-head update retains the recorded terminal
  outcome even when the deadline has expired by the time recovery begins.
- Resume recomputes the current solver/actor/verifier/curriculum/judge identities. Supplying the old
  fingerprint from the ledger cannot hide changed component code/configuration.
- Persisted planned/consumed/remaining budgets and the absolute `deadline_unix` survive restart.
  Atomic launch reservations cover solver/evaluator/verifier stages; exhausted budgets stop before
  new work, and replay does not charge the same reservation again.

## Integration regression

- Compatibility requirement: existing Population, OpenEvolve, Shinka handoff, ordinary
  `MemoryStore`, Feature 044 experiment memory, candidate receipts and recovery tests must remain
  green. This is the compatibility regression requirement, not a claim that those broader suites
  were rerun in this RSI-focused round.
- Mock, Native Population, OpenEvolve fixture and Shinka export fixture can each be invoked through
  `SolverGateway` without gaining direct RSI memory access.
- Ruff, compileall and focused Feature 160 tests pass without provider credentials or WebAgent.

## Local regression entry points

The provider-free regression command is:

```bash
PYTHONPATH=src:. pytest -q tests/test_rsi_*.py --basetemp /tmp/lunar-rsi-validation
ruff check src/lunar_evolution/rsi_*.py tests/test_rsi_*.py
python -m compileall -q src/lunar_evolution
git diff --check
```

Use a separate temporary directory for each test run. The result above covers the local RSI suite,
including DRS/BRS CLI replay and transfer recovery; it is not a full repository or real-provider run.

| Evidence area | Focused tests |
| --- | --- |
| DRS/BRS result, verified-result, memory publication and paused-run recovery | `test_rsi_durable_flow.py` |
| Immutable result replay, failed/cancelled reconciliation, concurrent resume | `test_rsi_resume_matrix.py`, `test_rsi_resume_reconcile_contract.py` |
| Controller locks, journal hash-chain/CAS and canonical episode boundaries | `test_rsi_checkpoint.py`, `test_rsi_store.py` |
| Fingerprint/config drift and supplied-old-fingerprint rejection | `test_rsi_identity_drift.py`, `test_rsi_fingerprint.py`, `test_rsi_durable_flow.py` |
| Planned/consumed/remaining, deadline, atomic reservation and depth/cycle primitives | `test_rsi_budget.py`, `test_rsi_durable_flow.py` |
| Frozen transfer publication/replay and side-effect recovery gates | `test_rsi_transfer_recovery.py` |
| Existing local protocol, actor, CLI and backend fixtures | Remaining `test_rsi_*.py` tests |

The CLI diagnostics only use local fixture solver IDs and persist to `rsi.sqlite3`; they do not
constitute evidence for real OpenEvolve, Shinka, OSWorld, or remote evaluator performance.

## Still outside this acceptance claim

- Dedicated evidence-bound APIs for resuming a transfer verifier/judge that started without
  persisting a result, and for resolving an already published unknown transfer receipt. These
  cases currently fail closed instead of repeating callbacks or rewriting receipts.
- DRS/BRS verifier/curriculum/judge callbacks can recompute a local deterministic fixture after an
  interruption inside the callback and before its result is saved. Their real external-callback
  started gates, idempotency/reconciliation and exactly-once semantics are not implemented.
- Real producer launch/ownership/heartbeat, cancellation/cleanup and unknown-worker inspection;
  real OpenEvolve/Shinka/native campaigns and provider performance.
- A clean-room verifier that reopens candidate inputs/dependencies and independently runs an
  official evaluator; memory promotion/holdout and transfer quality regression.
- Solver→RSI recursive execution and nested budget propagation. Depth/cycle and unknown-retry
  budget primitives must not be described as a completed nested scheduler.
- Real request/token/CPU/GPU/cost accounting. Control-plane reservations are not measured provider
  usage, and frozen transfer fixture success does not prove learning gains.

No WebAgent, remote evaluator or company evaluation platform is required or authorized by this
local validation procedure.
