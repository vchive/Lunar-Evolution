# Durable resume regression matrix

This note records the provider-free recovery contract exercised by
`tests/test_rsi_resume_matrix.py`. It is a focused supplement to
[`durable-resume.md`](durable-resume.md) and does not claim acceptance of a real model,
official evaluator, or external worker.

## DRS practice-to-target retry

When a target completes but the target judge reports a capability gap, the controller writes the
target judgment and curriculum decision before creating the practice intent. A passing practice is
committed against the frozen parent snapshot, then the next target request carries the new
snapshot digest. A process interruption at any of these boundaries resumes the existing intent or
receipt and does not invoke the same solver request twice.

## BRS frozen-wave recovery

BRS reserves every ordinal in the wave before dispatch. Workers write their own running episode and
immutable result evidence; only the controller writes the wave checkpoint and merges memory in
ordinal order. If the controller stops after a child result is persisted but before the wave save,
resume reconciles that child from its request/result pair, restores the other child evidence, and
merges the frozen wave once. No worker is dispatched again and no child can publish into a newer
memory parent.

## Cancellation, deadline, and unknown outcomes

`cancelled`, `timed_out`, and `abandoned` are terminal failed outcomes for a BRS wave. A resumed
terminal run replays its persisted execution and does not retry the cancelled/deadline child. An
`unknown` child remains a quarantine boundary: the wave cannot merge or start another child until
an explicit evidence-bound reconciliation settles it. A missing result for a running child remains
`rsi_resume_recovery_required`; it is never inferred as success or retried automatically.

## Remaining boundary

The matrix uses local deterministic gateways and SQLite/WAL. It verifies controller and ledger
semantics only. Process liveness, external worker authenticity/ownership, remote evaluators,
distributed leases, real CPython/toolchains, and OpenEvolve/Shinka campaigns remain separate
acceptance work.

