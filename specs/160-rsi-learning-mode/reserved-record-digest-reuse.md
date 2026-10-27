# Reserved snapshot event digest reuse

Status: implemented and focused-tested in the 828-node concentrated batch.
The three-file style repair passed147 overlapping nodes; this does not close
Linux mixed/full CI or establish a mixed-case speedup.

The reserved whole-ledger reader builds fresh exact dictionaries from its query-only raw snapshot. Its original `RSILedger._row_to_record(row)` call bypasses the existing ledger-owned pure expected-digest memo. This candidate lets only that explicit class-static path use the same bounded memo for complete nine-field primitive dictionaries. Normal SQLite/instance dispatch and ordinary mapping fallback remain unchanged.

Every call still reads both complete raw snapshots, fresh-decodes JSON, constructs a fresh RSIRecord and payload graph, walks the entire chain, and compares the current claimed digest. The memo stores only a digest derived from all original digest fields and the exact payload string. The exact payload object used for decoding is also used as the key; no second dictionary read can bind different text. `created_at` remains fresh and excluded from the original digest; the current stored digest is always compared.

Class-static mode resolves the converter and digest from RSILedger, ignoring instance shadows just as the previous explicit class call did. Class helper replacements, in-place code changes, decoder/canonical helper dispatch changes, foreign constructors, subclasses, mappings, incomplete/extra shapes and non-primitive values follow the original class converter. Existing bounded LRU accounting is shared; no DTO, SQLite snapshot, parsed admission or validation acceptance is cached.

Root must independently review and run the new focused tests plus existing event-cache/reserved-reader/shadow tests. This is a structural reduction of repeated canonicalization/hashing; no mixed-case speedup or causal performance claim has been measured. The original timed-out head must not be rerun. Any later mixed diagnostic requires a fresh source/runner freeze and retains the original 600-second deadline.
