# Native RSI SolverGateway — next P1 slice

Feature 160 continuation, 2026-10-02. This document defines the smallest composition step after
native launch input binding. It is a design and acceptance boundary; the existing native scheduler,
retained-candidate reader and `DurableSolverGateway` must not be described as this adapter until the
checks below are implemented.

## Contract

`NativeRSISolverGateway.run(request)` receives one immutable `SolverRequest` and one caller-owned
approved `MemorySnapshot`. Before consuming an attestation it must verify that the request memory
digest equals the supplied snapshot digest, stage the complete request and snapshot, bind the exact
launch intent/attestation/bootstrap identities, and claim the episode through the existing durable
ledger. The request's original absolute deadline and caller cancellation narrow the native attempt;
they are never renewed or recomputed after setup.

The adapter must use an explicit candidate selector. It may return `completed` only when a selected
candidate has same-run execution, independent evaluation and publication receipts bound to the
original request, contract, evaluator, environment and memory digests. Process exit 0, a native
terminal receipt, an output envelope, or an all-rejected publication result alone is unresolved.

The result must be a canonical `SolverResult` whose candidate, execution, official-evaluation and
trace digests point to those retained records. Failed, timed-out, cancelled and abandoned terminal
states may be returned only from durable evidence. Missing terminal/evaluator/publication evidence
is `unknown`/`recovery_required`; it cannot be converted to successful completion by a caller claim.

## Durable and recovery rules

- Claim/start/result records are create-only and keyed by episode ID plus request digest. A completed
  record replays without spawning. A started record without a complete result never relaunches.
- Recovery is read-only and accepts success only from the original bound inputs, formal native
  execution receipt, selected candidate receipt, independent evaluation receipt and durable result
  record. Otherwise it remains unknown and requires explicit evidence-bound reconciliation.
- Request, memory, intent, attestation, bootstrap, evaluator, candidate, receipt or ledger drift
  fails closed before a new process or attestation is consumed.
- The adapter cannot write RSI memory, mark a verifier pass, activate a candidate, or infer official
  evaluation from producer-declared scores. Those actions remain controller/verifier authority.

## Local acceptance matrix

The provider-free fixture must prove:

1. A matching request/snapshot reaches the native target and produces a fully bound `SolverResult`.
2. Replaying the same request performs no second spawn, evaluator call or ledger append.
3. Request/memory/intent drift is rejected before attestation consumption.
4. A crash after worker completion but before result publication remains unknown and never reruns.
5. Nonzero exit, missing candidate, evaluator rejection, all-rejected publication, receipt drift,
   deadline expiry and cancellation cannot return `completed`.
6. Read-only recovery preserves the original bytes, inode identities, budget and request digest.

No WebAgent, remote evaluator, company platform, real model, or OpenEvolve/Shinka campaign is part
of this slice. The official evaluator and external worker authenticity remain separate acceptance
work.

## Candidate selector and receipt mapper (T160-35 seam)

The provider-free `rsi_native_candidate` module now defines the control-plane seam used by the
future native gateway. `select_native_candidate(request, candidates)` validates every candidate's
request, contract, evaluator, environment and frozen-memory pins, rejects duplicate IDs and drift,
and admits exactly one `state=admitted` record. Rejected or unknown records remain evidence and are
never selected; zero or multiple admitted records fail closed.

`map_native_receipts_to_solver_result(...)` accepts only the selected candidate plus independently
bound execution, evaluator and publication receipts. All four records must carry the same request
and candidate identity. Execution must be `completed`, independent evaluation must be `pass`, and
publication must be `published`; otherwise the mapper raises a fixed contract error and does not
fabricate a solver result. The mapper carries only receipt digests and bounded provenance into the
existing immutable `SolverResult`; it cannot write memory or grant verifier authority.

## Injectable gateway facade

`rsi_native_gateway.NativeRSISolverGateway.run(request, memory)` now composes the plan,
native ledger claim, candidate selection, receipt mapper and durable result publication for a
trusted local caller. Its `plan_factory` must rebuild a deterministic plan without performing I/O
side effects, staging inputs, consuming attestations or launching work. It runs on every call so
the existing claim can be checked against the current pins. Only `receipt_provider` executes work,
after a new claim has been acquired. A competing started claim stops the call; a competing terminal
claim replays its saved result without invoking the provider.

The provider-free scheduler composition is now available through
`rsi_native_scheduler.NativeRSISchedulerContext` and
`make_native_rsi_scheduler_provider`. It validates the pre-staged request/memory input descriptor,
rechecks plan, launch, attestation, bootstrap, manifest, evaluator and environment bindings, passes
the request's original absolute deadline into `run_native_trusted_producer`, and maps only a single
published same-journal candidate with independent execution/evaluation/publication receipts. The
controller now requires the native gateway and controller to share one ledger and one approved memory
snapshot, and native gateway/provider configuration participates in the resume fingerprint.

This is still a local fixture composition boundary. The current local acceptance also persists a create-only provenance sidecar and revalidates retained artifacts on gateway and controller replay; sidecar digest/inode identity is anchored into the durable SolverResult. The context deliberately requires launch inputs
to have been staged by the existing native-input admission layer; a future staging helper may own
that write transaction. The provider does not prove external worker ownership, real evaluator
authenticity, or a real OpenEvolve/Shinka campaign. Those remain separate acceptance work.
