# Exact persisted RSI record digest reuse

Status: implemented and source-reviewed; concentrated focused regression has
382 latest passing nodes, retaining its two original test-fixture failures and
the affected 55-node repair run. Final-source mixed/CI acceptance remains open. This continues the local RSI ledger contract and
does not grant execution or publication authority.

## Problem and scope

The retained `df81a46c` single mixed case timed out at its original 600-second
deadline. Its v2 diagnostic records 354 samples over the first 180 seconds;
13 main-thread leaf observations are `_record_digest`. These samples justify
examining repeated canonical hashing, but do not measure its CPU share or prove
that this change will resolve the timeout. The original failure remains failed.

RSI readers repeatedly SELECT and decode the same persisted event rows. Reuse
only the pure expected digest for an exact immutable SQLite row identity, as the
existing checkpoint digest cache already does. Keep the static `_record_digest`
and `_row_to_record` entry points unchanged for compatibility and fallback.

## Contract

- Each read still performs its original fresh SQL query and `json.loads`, and
  returns a newly allocated record and payload. History, lineage, kind, state,
  request, parent, budget and authority checks are unchanged.
- The key contains logical ID, revision, kind, state, request digest, parent
  digest and the complete original SQLite payload TEXT. Every changed key field
  misses, including different JSON spelling with equal canonical content.
- Cache only an expected digest string and its retention accounting. Never
  cache a decoded dictionary, DTO, stored digest claim, SELECT result, admission
  decision or other authority. Compare the current row's `record_sha256` on
  every hit and miss. `created_at` remains freshly returned and is not part of
  the existing digest algorithm.
- Cache use is limited to an exact `RSILedger` and `sqlite3.Row`, with exact
  string metadata/payload, exact integer revision and `None` or exact-string
  parent. Other rows/ledger subclasses use the original static converter;
  nonexact metadata/payload retain the same fresh conversion and uncached
  digest path, preserving existing acceptance and errors, including SQLite
  BLOB payload handling.
- A replaced instance/class row converter, replaced instance/class digest
  helper, changed decoder/canonicalizer, or changed original helper code must
  retain its original execution rather than a warm memo. A substituted record
  constructor also uses the original converter. Do not turn this optimization into
  a new trusted parser or a caller-controlled validation flag.
- Keep an independent per-ledger LRU of at most 128 entries and at most 16 MiB
  conservative retained units. Count four bytes per retained string character,
  the revision's shallow allocation and 1,024 units of per-entry overhead.
  Oversized entries bypass retention. Protect access, promotion, eviction and
  accounting with a lock; expensive canonical computation occurs outside it.
- Preserve existing SQL transactions, external digest comparisons, append-only
  history, filesystem/source checks, locking, deadlines and zero retry policy.

## Validation plan

- Demonstrate warm reads keep fresh SELECT/JSON decoding while avoiding another
  original canonical digest computation, and retain static entry point behavior.
- Exercise each metadata/text key field, Unicode/equal JSON spelling, current
  stored digest tampering, malformed JSON, and independent subsequent SQL edits.
- Mutate returned nested payloads and confirm later reads remain detached.
- Verify substituted row/digest helpers run despite a warm cache, including
  original-function code replacement; a changed decoder cannot reuse a digest
  for a different decoded graph. Nonexact rows/metadata use uncached conversion.
- Keep the new instance reader in the existing rejection-ready reference shadow
  gate so replacing it cannot widen that reference's authority.
- Exercise count/retained-unit LRU eviction, oversized-key bypass and concurrent
  equal-key misses with exact accounting.
- Run focused ledger/history/admission tests plus Ruff, compileall and
  `git diff --check` in the root agent's single coordinated regression.

The author performs AST-only source validation. Test results and end-to-end
acceptance must be reported separately under the source actually executed.

## Actual concentrated validation

The 14-file execution returned 1 with 380 passing and two failing nodes, no
errors/skips, and equal before/after source inventories. Both failures followed
a test cleanup error: replacing an inherited JSON decoder method with
`monkeypatch.setattr` restored a bound method onto the instance, leaving the
shadow that the product correctly refuses. The repair uses a dictionary-item
patch so undo removes the previously missing key; no product guard was relaxed.
Only the affected test file was executed again: 55 real nodes passed with
return code 0, no errors/skips and equal source inventories. The latest node
union remains 382, not 437. Original XML and return code 1 are preserved.

The original CI Ruff command, compileall and diff checks passed. See the
[batch acceptance](../../docs/parallel-batch-acceptance-20261027.md) for evidence.
These results do not resolve the retained 600-second timeout.
