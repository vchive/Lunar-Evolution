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

`MemoryPromotionAdapter.quarantine_failed_report(...)` is the provider-free rollback boundary for
an already-approved or active admission. It accepts only a canonical report with
`promotion_eligible=False`, non-empty rejection reasons, and matching current/parent snapshot
digests. It atomically appends `revoked` through the governance CAS transition, so failed unseen
holdout, regression, or contamination evidence is removed from retrieval. The revocation reason
binds the canonical report digest. Replaying the same report with the resulting head digest returns
the existing revoked record without a second revision; a manual revocation or a different failed
report cannot be presented as the same completed operation. Stale CAS, report drift, snapshot drift,
or a passing report fails before any write.
The optional `reason=` keyword remains supported as a bounded annotation after the report digest;
it cannot replace that binding. Replay must supply the same annotation when one was recorded.

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

Before starting the suite, the controller accepts only shadow, approved or active admissions;
revoked and earlier lifecycle states cannot spend evaluation calls. Caller-supplied fingerprints
may add external pins or repeat matching component pins, but cannot overwrite the controller's
observed memory, solver, verifier, curriculum or target-judge identity. These component identities
are checked at each runner entry and return, and before the governance write, even if the admission
has no explicit compatibility entry for that component. A runner that changes them across these
boundaries cannot promote memory. This is a trusted local callback contract, not an OS sandbox or
proof of changes made and undone inside a callback.

Controller approval writes `controller_transfer_promotion:<canonical component pins digest>` into
the existing governance `reason` field in the same CAS append as the regression receipts. This
binding includes the observed component identities and caller-supplied external pins. Controller
replay and approved-to-active recovery require the same binding, even when `compatibility={}`;
an old approved/active record without it returns `rsi_memory_promotion_identity_missing`, rather
than inventing its original component identity. Direct adapter callers retain the unbound local
API unless they explicitly supply an approval reason. This controller binding does not authenticate
external evaluators or add automatic scheduling.
External pins supplied at first approval must be supplied unchanged on later replay, including
recovery by a fresh controller; omitting them changes the binding and stops activation.

This is an opt-in, provider-free composition boundary. The caller supplies the local regression
runner; it does not schedule a holdout campaign, invoke an official evaluator, modify the
read-only `RSIMemoryStore`, or establish external worker authenticity. The clean-room path has a
separate `CleanRoomAdmissionGate` that only advances a provenance-matched passing verdict from
`observed` to `verified`; it must not be conflated with transfer promotion or automatic activation.
