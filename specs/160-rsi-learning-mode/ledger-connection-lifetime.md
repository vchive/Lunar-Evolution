# Deterministic RSI SQLite connection lifetime

## Problem and scope

The d152 mixed execution still timed out at 600.033323802 seconds. Its first
180-second stack sample repeatedly reaches ledger connection and SQL reads;
these observations do not establish timing shares or timeout causality.
Separately, source inspection establishes a resource-lifetime defect: SQLite's
Connection context commits or rolls back but does not close. Every fresh
RSILedger connection can therefore remain in SQLite/Python cycles until GC.

This continuation closes each internally owned connection deterministically
without sharing a connection, caching SQL results, changing transactions,
removing fresh authority reads, changing PRAGMAs or extending deadlines.
The private raw `_connect` API still returns a real sqlite3.Connection whose
caller owns its lifetime; existing external test helpers keep that contract.

## Requirements

- Each internal `_connect` use enters a closing context outside its original
  connection transaction context. Commit/rollback runs before close, including
  early returns and exceptions. Materialized rows and detached DTOs remain usable.
- The combined read-only scope keeps its order: observation scope, connection
  ownership, transaction. Query-only and mode=ro remain unchanged.
- A connection created inside `_connect` is closed if configuring its PRAGMAs or
  row factory fails; propagate the original failure. Do not close a connection
  that failed before sqlite3.connect returned.
- Do not alter SQLite timeout, journal mode, lock ownership, checkpoint CAS,
  admission validation, canonical bytes, caches or read/write sequencing.
- Do not introduce a reusable pool, a new controller, runtime authority or
  a retry. A successful resource test does not close mixed/CI acceptance.

## Validation plan

Use real SQLite with retained strong references and disabled automatic GC to
prove success/read-only/early-return/rollback paths close their connections.
Verify committed data survives reopening, failed writes roll back, invalid
history refuses and releases resources, and connection setup failure closes.
Keep original methods covered by the existing focused ledger/admission/history
and recovery tests. Root runs one concentrated affected set, then project Ruff,
compileall and diff checks after the parallel source batch freezes.


## Concentrated validation result

All ten new real-SQLite resource cases pass, including disabled GC/strong-reference
retention, readonly write refusal, combined snapshot scope restoration, rollback
after an actual INSERT and original setup exception preservation if close fails.
The concentrated latest unique-node union is407 (379 plus38 minus10 overlap),
with zero failures/errors/skips. Only an equivalent test-with style fix required
repeating its ten cases; final project Ruff, compileall and diff checks pass.
Independent AST review confirms all31 transaction bodies/SQL/authority checks are
unchanged and no connection/cursor escapes. Mixed/CI acceptance remains open;
resource-lifetime correctness does not establish a performance improvement.
