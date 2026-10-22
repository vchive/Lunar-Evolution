# Original-budget serial regression performance

This continuation addresses the existing three-child mixed serial regression
gate. It changes no solve budget, policy/admission wire, evaluator behavior,
checkpoint digest algorithm or source-fingerprint output.

## Retained failure and diagnosis

Exact source `cfd76f8ed2fbe3e0a91c5f9240e852cc50a67c82` passed the local
Python 3.13.12 case in 468.41 seconds with `SolveExecutionControl(600)`.
The independent Linux Python 3.13.13 replay failed after 602.75 seconds with
`rsi_python_brs_native_dispatch_rejection_control_expired`. The original raw
stdout, XML, metadata and exit result are retained under ignored
`.lunar-evolution/validation/feature189-20261023/linux-mixed-cfd76f8-k2sex269/`.
This is a real open performance gate; a passing macOS case does not close it.

A separate single Linux diagnostic samples Python stacks every 0.1 seconds
without reading frame locals or altering source, budget or process fixtures.
At 120 seconds, repeated checkpoint-history traversal and full persisted-text
SHA-256 computation dominate active samples. The existing digest cache hashes
the entire SQLite text even on a hit. A separate pure policy observation
records 738 component fingerprints and 613 different source-cache keys;
the 256-entry LRU repeatedly misses, despite retaining only 391,348 source
bytes. Sampling results are diagnosis, not acceptance or timing guarantees.

## Two bounded pure-cache changes

1. The checkpoint digest cache may key by the exact immutable persisted
   Python `str`, plus run/revision/parent. Dictionary hash collisions still
   require exact string equality; no revision-only or stat-based shortcut is
   permitted. Avoid the additional UTF-8 copy and cryptographic hash used
   solely for the old cache key. Retain explicit entry and text-memory bounds,
   with LRU eviction. On a miss compute the original canonical checkpoint
   digest. Every call still reads and parses fresh SQLite rows and performs
   all revision/parent/digest/reference/history checks. Do not cache whole
   validation results, skip a row scan, or share mutable decoded histories.
2. The source-extraction cache may retain enough small entries for the actual
   graph, subject to a separate total source-text budget no larger than its
   old theoretical 256 x 96 KiB ceiling. Keep the exact source-content digest
   and full locator in every key, both fresh source-byte reads and all
   before/after ownership/code/backend checks. Defaults, closures, explicit
   code hooks and configuration hooks remain live on every fingerprint.
   Do not cache component identities or final fingerprints.

These two offline changes are now implemented in `rsi_store.py` and
`rsi_identity.py` with separate test suites. The digest cache retains up to 128
entries under a 16 MiB conservative unit budget and keys on exact persisted
SQLite text. The source cache retains up to 1,024 extracted-source entries
under a 24 MiB UTF-8 source-text budget (the former theoretical maximum). The
new digest suite covers same-length row replacement, fresh-history mutation,
exact-text hits, parent/revision/run changes, LRU/budget eviction, concurrency
and detached returned state. The source suite exercises 613 distinct small
components without extraction thrash and checks live drift and budget behavior.
The focused cache/store/identity gates have passed; the unchanged Linux mixed
case on this exact final source is still required before this task closes.

Both caches remain optional performance aids. Misses, eviction and disabled
retention must produce the same digest/source as an uncached observation.
Source edits, same-length text replacement and identity/parent/revision drift
must remain detectable. Source-cache bounds must also hold for its existing
direct `clear()` test seam and replacement; clearing must reset bookkeeping.

## Verification

Run focused cache/identity/store tests with independent canonical expectations,
fresh-history drift and capacity/eviction cases; Ruff, compileall and diff
checks; then rerun the unmodified Linux three-child mixed case on the exact
changed source under the original 600-second control. Retain all failures
separately. Final-source three-version CI remains mandatory before main merge.
This work does not close the static-image build or runtime gates in G1-G3.
