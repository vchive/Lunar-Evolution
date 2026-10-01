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

New promotion requires schema version 3 policy evidence. The adapter rechecks the complete
`RegressionPolicy`, each arm's trial/summary coverage, configured score/pass-rate gates, and
manifest/policy/snapshot/observation receipt bindings. The default requires every current-memory
unseen trial to pass and no seen/unseen pass-rate regression against either baseline. A failed
official outcome cannot be hidden by a higher score or by substituting the eligibility flag.
Explicit bounded noise thresholds are preserved in the report and receipts.

Policy-less schema version 2 reports keep their historical inspection/digest shape. They cannot
provide new approval/activation report evidence; historical score-only eligibility is insufficient.
Failed legacy reports may still be used for the fail-closed quarantine operation. The trusted
`activate_approved()` API only receives an existing governance row and therefore cannot infer a
new pass-gate version from opaque old receipt digests. Revalidation/migration of such rows belongs
to durable controller promotion integration; callers must not present legacy approval as new v3
evidence.

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

Controller approval writes `controller_transfer_promotion_v2:<canonical intent digest>` into
the existing governance `reason` field in the same CAS append as the regression receipts. This
binding includes the observed component identities, caller-supplied external pins, actual frozen
manifest, effective policy, parent memory and planned campaign budget. Nested external pins are
frozen and checked around each trial; callers cannot mutate an alias after approval. Controller
replay and approved-to-active recovery require the same binding, even when `compatibility={}`;
an old approved/active record without the v2 binding returns `rsi_memory_promotion_identity_missing`, rather
than inventing its original component identity. Direct adapter callers retain the unbound local
API unless they explicitly supply an approval reason. This controller binding does not authenticate
external evaluators or add automatic scheduling.
External pins supplied at first approval must be supplied unchanged on later replay, including
recovery by a fresh controller; omitting them changes the binding and stops activation.

With a controller ledger the holdout uses `DurableRegressionCampaign`: per-trial started/completed
records, conservative transfer/evaluator reservations and evidence-bound unknown reconciliation.
Restart before governance approval reuses completed trials. Its budget uses the common RSI schema
but is scoped to this campaign; it is not yet deducted from a parent learning run's consumed budget.
Local report caches are scoped to governance path, admission and both receipts, with snapshot checks
before return. See `durable-regression.md` for the complete recovery contract.

This is an opt-in, provider-free composition boundary. The caller supplies the local regression
runner; it does not schedule a holdout campaign, invoke an official evaluator, modify the
read-only `RSIMemoryStore`, or establish external worker authenticity. The clean-room path has a
separate `CleanRoomAdmissionGate` that only advances a provenance-matched passing verdict from
`observed` to `verified`; it must not be conflated with transfer promotion or automatic activation.
