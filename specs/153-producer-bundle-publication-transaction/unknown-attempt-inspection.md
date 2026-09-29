# Read-only native attempt inspection

## Boundary

An interrupted native draft may have a prepared journal and a retained run without a
candidate/evaluation terminal record. Re-entering the transaction must never infer that
verified process cleanup makes the same candidate safe to execute again.

`inspect_native_producer_bundle_unknown_attempt` inspects one already allocated draft. It
requires the exact prepared journal and admission plan, reopens the retained source, binding,
execution plan and admission, and checks the candidate/evaluator record. It reports only
`unknown` with the stage, a verified stop reason when present, and cleanup observation. It has
no write, launch, evaluator, publication, or retry path. A complete attempt belongs to the
existing exact-evidence retry path and is rejected by this inspector.

Missing terminal evidence remains unknown, including a crash before a stop receipt could be
written. A canonical interruption receipt must bind the retained launch intent or evaluation
request SHA-256 and cannot coexist with a terminal result. A verified cleanup observation is
diagnostic only. Source, mapping, admission, receipt, or directory identity drift fails closed.

This inspection does not prove that an orphan process is dead, repair an unknown publication
marker, or authorize replay. Those operations need a separate owner-checked recovery protocol.

## Acceptance

- [x] Inspect a stopped candidate and stopped evaluator without running either process.
- [x] Treat missing or incomplete terminal evidence as unknown, never as retryable.
- [x] Reject changed source, prepared intent, receipt, request, or directory identity.
- [x] Reject a forged or coexisting completion and interruption receipt.
- [x] Keep live archive/state and retained evidence unchanged across inspection.
