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
