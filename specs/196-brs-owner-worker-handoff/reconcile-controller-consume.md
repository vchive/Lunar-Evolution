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

The selected handoff must name the current owner thread and the captured checkpoint head and
canonical state digest. Exact registration replay is limited to the immediately adjacent,
otherwise unchanged obligation append; a later unrelated checkpoint cannot refresh that capture.
Each additional obligation binds its own parent checkpoint without rewriting earlier captures.

`consume_brs_selected_reconcile` is also owner-locked and explicit. It validates the immutable
run and request bindings and finds the original episode capture in the verified episode history.
Natural ledger successors may advance that episode to terminal without changing the capture.
The latest episode state must agree with the terminal observation, the original native claim
must bind the same request and plan, and its saved result and episode receipts must agree with
the supplied native/result digests. These reads and the obligation-removal checkpoint CAS share
one SQLite transaction. Caller-supplied terminal flags alone cannot settle running work. Unknown,
manual-review, recoverable, and drifted evidence leave both the latest checkpoint and durable
obligation untouched. Only complete `already_terminal` evidence, including process/native/mailbox/
result/transaction/cleanup observations, removes the exact obligation with a ledger CAS. The seam
never treats unknown as success, retries, refreshes a head, or relaunches work.

`native_evidence_sha256` names the existing `NativeEpisodeClaim.claim_sha256`;
`result_evidence_sha256` names the existing `rsi_episode_results.result_sha256`, the canonical
`SolverResult` digest. Neither is a newly generated receipt or a replacement for runtime evidence.

Ordinary resume, drive and finalization reject any retained obligation with
`rsi_brs_reconcile_required`; see [the default recovery gate](reconcile-default-recovery-gate.md).
This only enforces the durable fence. Automatic registration, process observation and consumption
are not enabled, and public admission remains closed. Real process/evaluator adapters and
production admission require a separate approved integration and remain outside this feature.

`RSILearningController.resume_brs_reconcile(run_id, evidence_by_episode)` is the controller
facade for this seam. It accepts a plain dict from episode id to either an exact
`BRSReconcileEvidence` value or its `to_dict()` form, acquires the per-run controller lock once,
and consumes entries in deterministic episode-id order. Unknown episode keys and malformed wire
values are rejected before any consume starts. The facade never calls ordinary `resume()`,
`_drive_brs()`, or a solver. It returns one `BRSReconcileConsumption` per accepted key; only
`already_terminal` evidence removes an obligation, while `manual_review`, `recoverable`,
`abandoned`, and `drifted` outcomes retain it for a later explicit observation. Each entry has its
own transaction; the batch is not atomic. A later ledger/binding or storage failure does not undo
earlier successful consumption. Before another explicit call, read the current checkpoint and
submit evidence only for remaining obligations. An uncertain write never authorizes a worker
retry or implicit success.
