# PB-05 detached serial successor primitive

This slice adds a provider-free, pure transition helper in
`rsi_python_brs_successor.py`. It is intentionally narrower than the online
PB-05 contract: it does not dispatch a worker, acquire a controller/lineage
lock, inspect a ledger or workspace, reserve budget, or grant publication
authority.

`BRSOrdinalCompletion` requires the exact pending `(run, wave, ordinal,
episode, request)` identity plus independent native result, native terminal,
owner-lineage acknowledgement, and verified-head digests. Both successful and
known-rejected terminal outcomes are accepted as evidence; a ready ACK or a
worker result by itself cannot advance the projection.

`advance_brs_ordinal` then reconstructs the detached preflight and appends only
the first pending episode. It increments the episode and solver counters while
preserving the original M0/root snapshot, plan, and reservation. It returns a
fresh non-authorizing selection for the next ordinal, or `None` at the end of
the wave. No nonce, claim, journal, receipt, request, or owner context is
copied to the successor. The caller must bind that selection to a new captured
owner context and nonce after the online owner transaction is implemented.

Focused coverage includes successful and rejected transitions, exact ordinal
and request mismatch, complete-wave refusal, budget exhaustion, invalid owner
evidence, M0 preservation, and non-authority of the returned selection.

The online PB-03 owner publication bridge, C1/P/C2 settlement, read-only
reconcile, and production native BRS admission remain open. This primitive is
not evidence that those capabilities are available.

## Fresh successor claim boundary

`claim_brs_successor(ledger, selection, request, ...)` is the first online
boundary after the detached transition. It accepts only an exact
`BRSNativeChildSelection` and `SolverRequest` pair, then delegates to the
existing guarded `RSILedger.claim_native_episode` operation with the new
controller checkpoint digest. The caller must already hold the controller
lock. The ledger transaction therefore rejects a stale owner head, duplicate
claim, existing episode/result, or an unclaimed result without creating a new
row. The returned `NativeEpisodeClaim` is launch state only; it does not carry
the previous ordinal's claim, nonce, receipt, owner object, or publication
authority.

The provider-free `dispatch_brs_successor` composition now covers the narrow
owner sequence in one explicit helper: it verifies that the terminal's
`verified_head_sha256` equals the newly captured context and expected
controller checkpoint, calls `advance_brs_ordinal`, creates a fresh
`BRSSelectedChildHandoff`, re-runs the exact handoff gate, creates the guarded
successor claim, and only then invokes a caller-supplied local dispatch
callback. The callback receives `(handoff, request, claim)` and is an inert
launch seam; it cannot settle a result, publish a candidate or grant owner
authority. Callback failure intentionally leaves the durable claim in
`started` state for explicit recovery. A final ordinal returns
`status="wave_complete"` without a claim or callback. This helper does not
spawn a process, inspect a workspace, reserve a second budget, or enable
public/native BRS.

This is the minimum terminal → fresh handoff → claim → dispatch lifecycle.
The complete controller integration still needs real runtime/receipt evidence,
result delivery/settlement, rejection C1/P/C2, durable resume and production
CLI acceptance.
