# Retained shared transfer completion recovery

This continues Feature 160 shared accounting. The first recovery slice closes only the window
where `comparison.json` is durable but the shared transfer completion checkpoint is missing.
It does not launch unfinished arms or recreate missing native results or verification evidence.

`controller.reconcile_transfer(...)` takes the original benchmark, tasks, snapshot, run/comparison
IDs, expected controller checkpoint digest, pending transfer intent digest, and expected comparison
receipt digest. These pins select retained evidence; caller data never replaces an authoritative
result. The original run lock and checkpoint CAS protect the operation.

The retained panel must contain every declared arm. All solver, evaluator and verifier reservations
must already be settled. Only the panel transfer reservation may be pending. Recovery validates a
private prospective copy through the normal retained comparison validator, which reopens native
results and independent verification evidence without calling a gateway, verifier, or evaluator.
After successful validation, one controller checkpoint records the transfer receipt and an audit
binding to the original checkpoint and intent. Budget counters remain unchanged. Identical repeated
reconciliation is a read-only no-op; changed pins, evidence, or settled receipts fail closed.

If the complete comparison file is absent, return `unknown` without a checkpoint mutation. Missing
arms, unfinished inner reservations, absent/tampered independent evidence, or changed profiles do
not grant completion authority. Other interrupted-panel continuation remains open.

Local fixture tests cover the completion-write crash, duplicate recovery, wrong/stale pins,
changed retained bytes, missing comparison, pending inner work, no execution calls, and unchanged
budgets. This does not establish real campaign recovery or provider telemetry.
