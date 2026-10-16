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
