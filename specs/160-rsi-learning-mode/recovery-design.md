# RSI controller durable recovery

## Scope and public API

`RSILearningController` uses the durable engine whenever a ledger is supplied. Existing in-memory
callers retain the previous provider-free behavior. Calling `run_drs` or `run_brs` again with the
same run ID and identical configuration resumes or returns the retained terminal result.

The controller adds:

- `resume(run_id=..., contract_sha256=None, evaluator_sha256=None, environment_sha256=None,
  solver_id=None, solver_settings=None, actor_fingerprint=None)`.
- `reconcile_episode(run_id=..., episode_id=..., result=SolverResult(...),
  expected_record_sha256=...)`, which validates evidence for the original request and continues
  that run. The expected record digest is the current episode ledger head, not a request digest.
- Constructor settings `solver_settings` and `actor_fingerprint`. Durable AgentLoop actors require
  an explicitly pinned actor fingerprint. Recovery rejects changed component fingerprints,
  solver settings, target judge, contract, evaluator, environment, or explicitly supplied memory.

`SolverRequest.from_dict(checkpoint["episodes"][episode_id]["request"])` reconstructs the exact
request for an external reconciler. The CLI must not synthesize a new request or treat a worker
state label as successful evidence. Legacy runs without controller checkpoints are readable but
are rejected by resume because their request/result context cannot be proven.

## Durable boundaries

The append-only `rsi_controller_journal` stores a hashed parent chain of complete checkpoints.
Each checkpoint contains immutable run configuration, the initial and current memory snapshot,
per-episode request, result, canonical episode, verifier decision, curriculum decision, target
judgment, ordered committed episode IDs, and quarantined BRS episode IDs. Checkpoint CAS and a
run-scoped cross-process lock serialize writers. SQLite uses WAL with FULL synchronous writes.
The lock rejects symlinks and hardlinks, pins the lock and directory inode, and checks that the
held lock remains named before checkpoint mutations and solver dispatch.

The run configuration includes one immutable controller budget plan: `max_depth`,
`max_solver_invocations`, `max_practice_episodes`, `max_unknown_retries`, and optional absolute
`deadline_unix`. The checkpoint stores its separate `budget_state` as exact
`planned/consumed/remaining` values. Each episode checkpoint also stores its derived `depth`,
unique `ancestry`, and whether its launch reservation was durably charged. Resume reconstructs
these facts from the episode graph and reservations, rejects mismatches or plan drift, and rejects
legacy controller checkpoints without budget state.

Execution persists a planned request, then a launch intent, before invoking the gateway. A launch
intent without a result becomes unknown on recovery and is never reissued automatically. A
terminal result is persisted before verification; a verifier decision is persisted before its
canonical episode append. A crash after either boundary reuses retained evidence. Verifiers may
provide `validate_retained(episode, request, result, decision)` to reopen retained evidence without
executing the evaluator again. A crash inside a verifier before any decision is persisted may
repeat verification; a solver launch is never repeated.

Before the launch intent is durable, the controller reserves the episode against the run budget.
It refuses a new launch when the absolute deadline has elapsed, when the derived depth exceeds the
plan, or when the solver/practice limit is exhausted. These conditions persist a terminal
`budget_exhausted` run, whose resume path cannot dispatch another solver request. This Phase 1
controller gate governs new launches; propagating deadline cancellation through real external
solver/evaluator processes remains adapter lifecycle work.

Memory promotion first computes a snapshot against a private CAS store. Its immutable ledger
record is written before the checkpoint names the new snapshot. A crash between those writes
reconstructs the same snapshot and validates the existing record. Recovery reconstructs every
committed memory transition from verified episode evidence and rejects missing snapshots,
duplicate promotions, or lineage drift.

## Unknown and BRS behavior

An unknown result or interrupted gateway blocks all subsequent controller launches. Explicit
reconciliation accepts completed, failed, timed-out, abandoned or cancelled evidence whose episode ID, request
digest and pinned actor match. Completed evidence must contain all required receipts and pass
the configured verifier before promotion. A stale episode CAS or conflicting terminal result is
rejected. The generic ledger still rejects unknown-to-running; only the controller's evidence
gate may reopen an unknown run once every launched child is settled.

Reconciliation is separately limited by `max_unknown_retries`. Its consumed count is checkpointed
with the other budget dimensions; an exhausted limit reaches `budget_exhausted` while retaining the
unknown evidence. It never authorizes an automatic solver replay.

BRS stores the complete wave decisions in configuration and pins every request to the same
initial memory snapshot. Independent children run concurrently, but every launch/result append
is serialized. An uncertain child quarantines verified siblings and blocks all memory merges.
After reconciliation, completed children are reused and merged by ordinal. An interrupted merge
continues after the last committed snapshot without invoking any solver again.

## Usage and cost receipts

The local `RSIUsageReceipt` contract records exact request count and local wall time, optional
complete provider token telemetry, optional CPU/GPU time, and an optional reproducible micro-USD
estimate whose rates are bound into the receipt. Aggregation uses controller-observed wall time so
parallel BRS episode durations are not double-counted. Missing telemetry is represented as
unavailable, not zero.

This receipt model is deliberately outside `SolverResult` and has not yet been connected to
episode checkpoint sidecars, reconciliation, completed-run aggregates, or `rsi inspect`. Until
that wiring exists, recovery makes no claim that a run's provider usage or cost is complete.

## Verification

Provider-free fault tests cover gateway interruption, terminal-result/verifier interruption,
verifier-append/checkpoint interruption, memory-record/checkpoint interruption, partial BRS merge,
unknown reconciliation, stale/forged evidence, missing committed memory, drift rejection,
checkpoint corruption, replaced lock files, and an independent process holding the run lock.
Budget checks additionally cover exhausted solver and depth limits, terminal resume without a
second dispatch, expired absolute deadlines, reconciliation limits, and forged budget counters.
Receipt unit checks cover strict telemetry/cost validation and unavailable-value aggregation.
These checks do not establish real-model quality, real provider usage, or external campaign
reliability.
