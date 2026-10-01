# Controller durable holdout regression

## Contract

`promote_transfer_regression(..., budget=...)` uses a durable local campaign whenever the
controller has an RSI ledger. Its scope is the admission ID. The campaign freezes the ordered
manifest, complete RegressionPolicy, old/current snapshots, controller pins, runner code/config
identity, initial shadow admission CAS and planned budget. A new invocation with changed intent
fails before any runner call. Without a ledger the same entry remains an explicit fixture API;
its budget is local and does not claim crash recovery.

Each arm/task/repetition has a deterministic callback ID. Reserve one transfer and evaluator
invocation together and persist the reservation before writing callback started and invoking the
runner. A crash between reservation and started retains that charge; recovery may use the same
reservation, never another budget. Completed observations are validated and reused. Started
without result returns `rsi_callback_reconcile_required`, never silently repeats evaluation.
Explicit reconciliation must bind the original callback intent, canonical observation and trusted
local evidence. This identifies a local evidence source, not a remote evaluator attestation.
The total is bounded to 1024 trials before constructing a journal or executing a callback.
Transfer/evaluator counts and the shared deadline govern trials; the callback does not launch a
solver or a nested RSI run. As in the controller callback protocol, explicit reconciliation reserves
one `unknown_retries` count before recording evidence, even after the dispatch deadline. Its
evidence-bound reservation is durable and repeated identical reconciliation does not charge again;
it retains the original transfer/evaluator reservation and never extends the dispatch deadline.

The campaign records monotonically consumed/remaining RSIRunBudget state and absolute deadline.
This is one campaign's budget using the shared schema, not a reservation from the prior DRS/BRS
run. A shared parent/run budget across learning and holdout remains an integration task.
Reservations are prefix ordered and each consumes exactly one transfer/evaluator count. Deadline
or count exhaustion is persisted and blocks further calls and promotion. Completed terminal
report replay does not consume budget or apply a fresh deadline. A callback that runs past its
deadline may persist its observation but cannot start another trial or publish a new report.
The callback is trusted local code; no hard timeout or distributed exactly-once guarantee is made.

Controller approval uses `controller_transfer_promotion_v2:<digest>` and binds observed/external
pins, old memory, actual manifest, effective policy and planned budget. Legacy v1 reasons cannot
be replayed or activated through this path. Trial drift checks remain in force around every call.
Governance CAS remains the publication authority. A crash before approval reuses all completed
trials; a crash after approval reads the approved row. The immutable memory store is not changed.

## Validation

Use local fixtures to cover crash after completed trial, unknown runner interruption and explicit
reconcile, crash after budget reservation, prefix/counter corruption, changed runner/manifest/
policy/budget, concurrent campaign exclusion, deadline/count exhaustion, report replay after
deadline and zero-repeat approval recovery. No provider, WebAgent or remote evaluator is used.
