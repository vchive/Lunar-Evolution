# RSI CLI budget and usage sidecar

The `rsi run` command exposes the same bounded `RSIRunBudget` fields used by the controller:
depth, practice/target limits, stage invocation limits, unknown-retry limit, and an absolute
`deadline_unix`. The handler passes one canonical policy to the controller; the persisted request
and fingerprint remain authoritative. A BRS run derives its omitted practice/target defaults from
the requested practice count, preserving the pre-existing command behavior.

`rsi resume` accepts the same fields only as assertions. It compares each supplied value with the
persisted policy before constructing the controller, then passes the complete persisted policy to
the controller's resume gate. A mismatch fails closed with `rsi_resume_budget_drift`; resume never
uses a new policy and never dispatches an unknown episode.

Both commands accept an optional `--usage-ledger PATH`. When supplied, the provider-free
`RSIUsageLedger` is attached to the controller and records one idempotent local solver receipt per
episode. The option is opt-in to preserve existing CLI behavior; token, CPU, and provider billing
values remain unknown unless an adapter supplies trusted observations. Reusing the same sidecar on
resume preserves event identity and does not append a duplicate receipt. The path is reported in
the JSON response for operators to inspect with `rsi usage PATH`.

`rsi inspect RUN_ID` includes a read-only `budget` summary (planned, consumed, remaining) and a
`reconcile` summary (run state and unknown episode IDs). Existing ledger history remains unchanged;
the summary does not authorize a resume or infer missing evidence.

This is a provider-free local CLI surface. It does not add external worker authentication,
distributed ownership, remote evaluators, or real OpenEvolve/Shinka campaigns.
