# RSI provider-free usage and cost accounting

Feature 160 requires experiment-level accounting even when a provider does not return a trusted
usage envelope. `src/lunar_evolution/rsi_usage.py` provides the narrow local boundary. It is an
independent ledger from `model_profile.UsageLedger`: model profiles enforce an in-memory model
ceiling, while this ledger preserves run/episode/adapter-stage observations across restart.

Each `UsageReceipt` binds an event to a `run_id`, optional `episode_id`, and adapter lifecycle
stage. It records request count, input/output tokens, wall and CPU milliseconds, and an optional
estimated micro-USD cost. Missing values remain `null`; they are never converted to zero. A
summary therefore becomes `usage_complete=false` when any selected receipt has unknown token,
time, or cost data. `budget_check()` rejects an incomplete summary by default, so partial data is
useful for audit and cannot authorize additional work.

`UsageLedger` stores a canonical JSON document with an append-only hash chain. Appends use a
compare-and-swap head digest and write through a temporary file plus `fsync`/rename. Reopening
validates the schema, pricing configuration, event uniqueness, parent links, and every record
digest. `UsagePricing` contains optional input/output per-1k-token rates and a fixed per-request
estimate; all estimates are integer micro-USD and remain explicitly estimates.

This is provider-free evidence and does not establish external billing truth. It does not measure
GPU time or infer a provider charge from a control-plane reservation. Process adapters may append
one receipt per lifecycle stage once they can provide a trusted local observation.
