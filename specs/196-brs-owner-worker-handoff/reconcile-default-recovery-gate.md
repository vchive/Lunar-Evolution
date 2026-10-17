# Default recovery gate for retained BRS obligations

An unconsumed `brs_reconcile_obligations` entry is a durable recovery fence. The explicit
`resume_brs_reconcile` facade remains the only controller entry in this slice that may consume
one; ordinary `resume()` and the default drive paths must not infer that the associated worker
can be restarted, merge its memory, or finalize the run while the fence remains.

Before recovery or drive changes state, inspect both the supplied checkpoint and the latest
durable controller checkpoint. Parse retained obligations strictly and reject a nonempty set
with `rsi_brs_reconcile_required`, regardless of the recorded phase or the run's terminal state.
This is a request for explicit evidence reconciliation, not a declaration that a terminal run
or an unknown worker is recoverable. An invalid obligation fails with its validation error.

Only the latest checkpoint is a recovery fence. Once explicit evidence consumption has removed
the last obligation, historical checkpoints containing that obligation must not block ordinary
terminal replay. Runs whose checkpoints never carried obligations retain their existing resume
behavior. The gate performs no process inspection, retry, dispatch, budget reservation, or ledger
write. Public native BRS, `online_publication=false`, and `production_admission=false` remain
unchanged.

Provider-free focused tests cover paused work, terminal run heads and terminal checkpoints,
direct drive entry, stale in-memory state, malformed obligations, and terminal replay after
explicit consumption. No real model, remote evaluator, or solver campaign is required.

The explicit facade's current batch preflight only guarantees evidence DTO/wire syntax and
known episode keys before the first consume. Each selected episode then performs its own
binding validation and CAS; a later binding/storage failure may follow an earlier successful
consume. This slice does not add a batch transaction. A later composition may validate all
selected episode histories while holding the owner lock before the first consume, using the
same single-episode validation kernel, without promising rollback of durable writes.

`rsi inspect` reports the same latest-head recovery fence in its existing
`reconcile.required` boolean. Any retained obligation keeps the flag true, including an
unknown or settled phase on an otherwise completed run. Once exact consumption removes it,
historical entries do not affect the flag. The legacy output schema stays unchanged; inspection
does not probe processes, retry work, or modify the ledger.
