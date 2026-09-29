# Shared RSI run accounting and retained promotion

This continues T160-13c and T160-13d without changing the default DRS/BRS memory policy.

## Contract

A durable learning run opts in with `enable_transfer_accounting=True`. After learning completes,
`controller.compare_transfer(...)` may run a host-declared frozen panel under that run's remaining
budget. The panel identity fixes tasks, profiles, snapshot, comparison ID, benchmark fingerprint,
and the original ledger/run binding before any gateway call. Normal learning does not launch a
transfer panel implicitly. Non-durable opt-in is rejected before work.

Every panel reserves its transfer invocation; each baseline/frozen gateway invocation reserves
`solver_invocations`; native evaluation and independent verification reserve their own counters.
Learning episodes and panel calls use the same `planned/consumed/remaining` state and checkpoint
writer. A one-task successful panel adds two solver, four evaluator and two verifier invocations.
The panel itself adds one transfer invocation. Its solver requests retain the per-task budget.

A reservation is persisted before work. A persistence failure rolls back the in-memory mutation
and poisons that accounting instance, including callers already queued on its lock. Completion
binds the original result or receipt digest; repeating identical completion is a no-op. Checkpoint
history cannot erase a panel, reservation, settled receipt, or consumed count. Recovering an old
panel without solver reservations requires explicit migration; absence is never counted as zero.

A budget failure stops before the next side effect and retains the panel intent and all earlier
charges. An unfinished panel remains unknown and cannot resume by launching another arm. A complete
panel can be reopened read-only, with exact task/arm/request/result and evaluator/verifier bindings.
Full evidence-based continuation of an interrupted panel remains a separate recovery task.

## Promotion

`NativePromotionEvidence` may bind an explicit shared ledger and run ID. It reads the original
checkpoint history and panel records, reconstructs counters, and reopens native comparison
artifacts through the retained validator. It must never call `compare`, a gateway, or an evaluator.
A caller-provided comparison mapping only selects already-retained evidence; it grants no authority.

The old standalone promotion fingerprint and receipt format remain unchanged when shared binding
is absent. Shared evidence additionally binds its ledger/run identity. Missing, changed, unfinished,
or budget-inconsistent records fail before approval. Practice and holdout task IDs stay disjoint;
the host still owns the holdout selection and statistical independence of its tasks.

## Validation and remaining scope

Tests use local fixture subprocesses. They cover shared counters, exhaustion before either arm,
pending no-replay, changed reservation/result/receipt, persistence failure, read-only promotion,
and standalone compatibility. These checks do not establish provider telemetry or generalized
model benefit. Automatic DRS/BRS active retrieval, full transfer reconciliation, real Actor and
OpenEvolve/Shinka campaigns remain separate tasks.
