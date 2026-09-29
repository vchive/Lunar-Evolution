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
- Verifier reservations and intents are durable before execution. Interrupted verifier work stays
  unknown until the original intent and current record are explicitly reconciled against retained
  evidence. Saved decisions are reused without another invocation or charge. Pure read-only
  verifier reconciliation consumes no solver retry allowance and cannot revive an exhausted run.
- Separate evaluator/verifier/transfer counters validate integer types and remaining arithmetic.
  Native evaluator calls and frozen transfer panels reserve before execution only when an explicit
  durable stage scope is installed; pending intents remain visible in a sidecar and are never replayed.
  Explicit `compare_transfer` can bind these three stage counters to the controller run ledger;
  its retained opens are read-only. The panel's gateway launches remain outside the learning
  `solver_invocations` counter, while full transfer unknown reconciliation and external provider
  telemetry remain unavailable. Complete legacy checkpoints without stage counters require
  migration rather than synthetic zero counts.
- `RSIUsageReceipt` accepts only complete token triples, non-negative integer measurements, and
  reproducible estimates using receipt-bound micro-USD rates. Missing provider telemetry remains
  unavailable (`null`), never a synthetic zero. Its aggregation uses the observed controller wall
  clock rather than summing potentially concurrent BRS episode durations.
- Optional adapter telemetry is persisted as a per-episode sidecar, bound to the original
  request/result identity and receipt digest. Resume rechecks the sidecar and run aggregate;
  `rsi inspect` exposes the durable budget and aggregate. Missing telemetry remains `null`, and
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

The same command includes `test_rsi_budget.py`, `test_rsi_usage.py`,
`test_rsi_usage_sidecar.py`, and `test_rsi_memory_governance.py`. These exercise the local durable
budget, usage-sidecar binding and the independent promotion authority. The optional durable
`candidate_only` policy is covered by `test_rsi_governance_store.py`: source/content binding, partial
nomination recovery, CAS, policy drift, read-only restoration, quarantine and activation rejection.
`test_rsi_stage_budget.py` covers verifier budget exhaustion, intent interruption and evidence-based
reconciliation without execution. CLI tests exercise both memory policies and strict retained
decision input. Trusted native holdout promotion and explicit active-memory retrieval are covered
by host-configured retained-panel evidence; default DRS/BRS automatic retrieval remains disabled.
None of these local checks substitutes for real Actor, provider telemetry, solver campaign or
transfer gains.
