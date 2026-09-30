# RSI memory governance (Feature 160 P1 narrow contract)

This document defines the first durable admission control plane for RSI memory.  It is deliberately
separate from `RSIMemoryStore`: the snapshot store keeps immutable content, while governance decides
which content may be retrieved by a later request.  The implementation is provider-free and does
not start a solver, evaluator, worker, or producer.

## Admission identity

An `MemoryAdmissionRecord` binds:

- a content-addressed `memory_snapshot_sha256` and `memory_item_sha256`;
- the source `source_episode_id` and independent `verifier_receipt_sha256`;
- the immutable `parent_snapshot_sha256` (or `null` for the empty root);
- a `scope` and exact compatibility map (solver, contract, environment, or other declared pins);
- optional holdout and baseline regression receipts;
- the source episode outcome (`pass`, `fail`, or `unknown`).

The initial record is `observed`.  Records carry a revision, parent record digest, and their own
canonical SHA-256 digest.  SQLite rows are append-only; a lifecycle update creates another row.

## Lifecycle and gates

```text
observed -> verified -> candidate -> shadow -> approved -> active -> deprecated -> revoked
```

The promotion edges are strict and compare-and-swap guarded:

1. `observed -> verified` requires a passing source episode and a verifier receipt.
2. `verified -> candidate` records the only initial learning outcome.  A pass can become a
   candidate, never an active memory directly.
3. `candidate -> shadow` places the item in a non-retrievable observation phase.
4. `shadow -> approved` requires both a holdout receipt and a baseline receipt with
   `regression_passed=true`.
5. `approved -> active` is the only activation edge and retains the regression evidence.
6. `active -> deprecated` retires an item without claiming a failure.
7. `revoke` is a fail-closed safety transition from any non-revoked state.  It requires a reason;
   revoked records cannot be promoted or retrieved.

The store rejects skipped gates, failed/unknown episodes, missing evidence, stale CAS digests,
compatibility changes, and activation without regression evidence.  A compatibility mismatch during
retrieval yields no admission, so callers cannot silently fall back to drifted memory.

## Persistence and API

`MemoryGovernanceStore(database)` creates only the `rsi_memory_governance` table in the supplied
SQLite database.  It can share the RSI ledger file, but it does not call or mutate `RSIMemoryStore`
or `RSILedger` methods.  The narrow API is:

- `create(record)` — append an `observed` admission;
- `get()` and `history()` — inspect the current immutable head or full lineage;
- `transition(..., expected_record_sha256=...)` — perform one gated lifecycle edge;
- `promote()` — a named alias for `transition`;
- `revoke(..., reason=...)` — fail-closed rollback/revocation;
- `list_retrievable(scope=..., compatibility=...)` — return only `active` and compatible records.

This P1 contract does not perform holdout execution, clean-room verification, transfer regression,
artifact garbage collection, or automatic champion/challenger scheduling.  Those callers provide
the signed/hashed receipts and invoke the explicit gates.  A later feature can add those runners
without changing the append-only state machine.

The provider-free controller seam is `MemoryPromotionAdapter` (or
`promote_transfer_report`). It consumes a `TransferRegressionReport` only after its report digest
and `promotion_evidence()` are validated. It appends `shadow -> approved` with the holdout and
baseline receipts, and only then may append `approved -> active`; it cannot activate a memory from
a single pass.
