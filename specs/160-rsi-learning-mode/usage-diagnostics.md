# Read-only RSI usage diagnostics

## Problem and scope

The local RSI usage ledger preserves unknown token/time/cost observations as `null`, but its
aggregate summary cannot explain which metrics or adapter stages have missing observations.
The existing CLI does not expose this ledger. A scope with no matching receipts must not be
presented as measured zero consumption.

This slice adds an explicit `rsi usage PATH` command and a reusable `inspect_usage_ledger()` API.
They read an existing local JSON usage ledger; they do not run a solver, create a usage receipt,
authorize a budget, reconcile evidence, or contact a model/evaluator. Existing controller,
actor/verifier and memory-promotion behavior remains unchanged.

## Input and read-only contract

```text
rsi usage PATH [--run-id ID] [--episode-id ID] [--adapter-stage STAGE] [--json]
```

Filters are intersected using exact bounded identifiers. The explicit path must identify an
existing bounded regular file. Reject a final symlink, malformed/duplicate-key JSON, unknown
fields, malformed receipts, inconsistent totals, duplicate events or broken hash-chain/head.
The same schema and receipt-chain validator used by `UsageLedger` is reused for diagnostics.
The reader opens the original path with `O_NOFOLLOW`; it does not resolve a final symlink first.

The CLI branches before `_config()` and `RSILedger` construction. No home, database, directory,
lock, temporary file or report file is created, and the ledger bytes are never written back.
Missing/invalid files or invalid filters return the normal CLI diagnostic error with exit code 2.
Valid reports return exit code 0 even when their accounting evidence is incomplete.

## Output contract

The JSON report has protocol `rsi-usage-diagnostics-v1`, the validated ledger head digest,
the selected run/episode/stage scope, aggregate totals, metric completeness, and deterministic
stage breakdown. Each aggregate/stage reports:

- `evidence_status`: `no_receipts`, `partial` or `complete`;
- matching `receipt_count` and receipt `request_count`;
- nullable input/output/total tokens, summed local wall/CPU milliseconds, estimated micro-USD cost;
- for each metric, the count of receipts with known/unknown data;
- `usage_complete=false` when no receipt matches or any metric is unknown.

Adapter stages are sorted lexically. Unknown observations remain `null` in totals; known
observations are never substituted for a complete total. No-match scope returns zero matched
receipt/request counts and `null` measured totals. Cost is always labelled `estimate`, even when
an explicit receipt value or the persisted pricing configuration makes it calculable.

Receipt request counts are local adapter-stage observations, not a count of verified provider
requests. Summed episode/stage wall time is not the elapsed duration of a parallel run. The report
does not infer an unrecorded stage, missing provider token usage, CPU/GPU measurements or billing
truth. The persisted head digest authenticates receipt-chain integrity within the local file, not
an external system or the pricing source.

## Implementation plan

1. Extract the existing usage state validator so writable reopen and diagnostics share checks.
2. Implement a one-shot no-follow read and scope/stage report construction in `rsi_usage.py`.
3. Add parser and early command branch in `cli.py` without initializing application state.
4. Add focused protocol and CLI tests, then run Ruff, compileall and diff checks.

## Acceptance tests

- Valid complete, partial and no-match scope reports preserve totals and unknown counts.
- Run/episode/stage filters intersect; stage breakdown and repeated reports are deterministic.
- Persisted pricing can calculate only an explicitly labelled cost estimate; unknown required
  pricing/token observations leave cost `null`.
- Missing file, final symlink, directory, malformed/duplicate-key JSON and receipt-chain tampering
  fail before a report is produced; invalid filters fail without writes.
- CLI success/error/partial paths never invoke config/state initialization, launch workers or
  create/change local files. Existing writable ledger tests remain green.

No real provider, remote evaluator, WebAgent or company evaluation platform is used by this slice.
