# Explicit controller reconcile registration and consume

This private, provider-free seam records one selected BRS owner/worker obligation after the
owner has already validated the exact selected handoff and native plan/prepared pin. The caller
must hold the per-run controller lock and supply the captured controller checkpoint, episode
record, and non-zero native-plan digests. Registration is an explicit API; it does not launch a
worker, inspect a process, publish a result, or enable public BRS. Replaying the exact captured
obligation is idempotent. A changed payload or stale capture is rejected.

The checkpoint digest in the obligation is the parent head captured before the obligation append.
The ledger append returns the new head that contains the obligation. Resume code therefore keeps
the captured parent binding while using the latest head for the subsequent compare-and-swap.

`consume_brs_selected_reconcile` is also owner-locked and explicit. It validates the immutable
run, request, and episode bindings, then evaluates a caller-supplied evidence envelope. Unknown,
manual-review, recoverable, and drifted evidence leave both the latest checkpoint and durable
obligation untouched. Only complete `already_terminal` evidence, including process/native/mailbox/
result/transaction/cleanup observations, removes the exact obligation with a ledger CAS. The seam
never treats unknown as success, retries, refreshes a head, or relaunches work.

The APIs are intentionally not wired into the ordinary BRS driver or public admission path. Real
process/evaluator adapters and production admission require a separate approved integration and
remain outside this feature.
