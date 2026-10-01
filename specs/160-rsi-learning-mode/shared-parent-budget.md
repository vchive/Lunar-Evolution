# Shared parent learning and holdout budget

`promote_transfer_regression(parent_run_id=...)` explicitly charges a durable learning run's
remaining budget. With no parent ID the existing separately scoped campaign API remains valid.
Parent identity binds ledger path/device/inode, original run request and complete planned limits;
it is included in campaign intent and controller approval identity. A missing, legacy, uncertain,
cancelled or exhausted parent cannot authorize a new holdout trial. Completed learning runs may
spend their original remaining budget for an explicitly requested holdout; their learning outcome
and memory snapshot remain immutable.

Parent and child must reuse the same `RSILedger` instance; a different ledger is rejected before
intent publication, charge or dispatch. Lock order is parent run, campaign, callback. The already-owned parent lock may be borrowed by the
controller's same thread for automatic post-practice regression. Each arm/task/repetition reserves
transfer + evaluator together in the parent checkpoint before campaign reservation and callback
started. The parent stores immutable event/binding receipts. A crash between parent charge and
campaign charge reuses the original parent event, never charges twice or refunds uncertain work.
Explicit reconciliation similarly charges unknown-retry evidence once without refreshing the
dispatch deadline. Parent identity, planned limits, event receipts and consumed counters are
verified across checkpoint history; drift and under-accounting fail closed.
Controller terminal resume also validates external reservation history; removing a receipt while
preserving consumed counters cannot bypass the audit gate. Generation outer callback reconciliation
charges its own unknown-retry reservation in addition to any uncertain child trial.

All subsequent controller writes preserve external reservations and synchronize their budget
state before reserving new launches. Parent total budget and any stricter campaign-local limits
both apply. Terminal campaign replay is read-only and does not ask for a new dispatch allowance.
This is a single-host durable accounting contract; it does not authenticate provider billing.

Focused fixtures cover already-consumed evaluator budget, multiple campaigns sharing a parent,
reservation crash windows, unknown reconciliation, inherited deadline, parent/limit drift,
terminal replay, concurrent controller exclusion and subsequent learning accounting.
