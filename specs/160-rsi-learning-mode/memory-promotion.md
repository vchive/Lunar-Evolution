# Explicit transfer-to-memory promotion adapter

Feature 160's provider-free transfer suite and memory governance control plane are separate by
design. `MemoryPromotionAdapter` is the narrow controller-facing boundary between them:

```text
TransferRegressionReport.promotion_evidence()
  -> shadow --(holdout + baseline + regression_passed)--> approved
  -> approved -------------------------------------------> active
```

The adapter accepts only a `TransferRegressionReport` whose canonical report digest still
matches its contents and whose promotion decision is eligible. It requires all three evidence
fields (`holdout_receipt_sha256`, `baseline_receipt_sha256`, and `regression_passed=True`) before
calling the governance transition. A rejected report, a tampered report, stale CAS digest,
compatibility drift, or revoked admission fails closed without appending a revision.

`promote(..., activate=True)` always appends `approved` first and then `active`; a single practice
or transfer pass cannot skip the approved gate. The controller may pass an expected compatibility
map explicitly; when omitted, the adapter binds the immutable map already recorded on the admission
and the governance drift check still applies. The adapter does not execute a solver/evaluator,
does not contact OpenEvolve/Shinka or another remote service, and never mutates the immutable
`RSIMemoryStore`. `promote_transfer_report(...)` is the equivalent functional entry point for a
controller that does not need to retain an adapter instance.

## Controller composition

`RSILearningController.promote_transfer_regression(...)` is the explicit controller-facing
composition for this adapter. It obtains the controller's current immutable snapshot, accepts an
explicit frozen `old_memory`, runs the local `TransferRegressionSuite`, verifies the admission's
current and parent snapshot digests plus solver/verifier/curriculum/target-judge fingerprints,
then delegates to `MemoryPromotionAdapter`. With the default `activate=False` it appends only
`shadow -> approved`; `activate=True` appends `approved` first and then `active`. A completed
promotion is replay-safe on the same controller instance: it returns the cached report without
rerunning the suite or appending another governance revision. CAS, snapshot, compatibility or
report eligibility failures remain fail-closed.

This is an opt-in, provider-free composition boundary. The caller supplies the local regression
runner; it does not schedule a holdout campaign, invoke an official evaluator, modify the
read-only `RSIMemoryStore`, or establish external worker authenticity. The clean-room path has a
separate `CleanRoomAdmissionGate` that only advances a provenance-matched passing verdict from
`observed` to `verified`; it must not be conflated with transfer promotion or automatic activation.
