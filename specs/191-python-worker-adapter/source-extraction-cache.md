# Bounded source extraction cache

## Problem and scope

PR99's Python 3.11 current-1 XML records 13 inert child execution cases taking
2702.16 seconds. Three publication/recovery cases account for 2151.563 seconds.
Source inspection is repeatedly performed by gateway wiring, producer staging
policy, and the scheduler input dependency projection. A short local profile of
the 31 input dependency fingerprints spent about 97% of its time extracting source.
These measurements identify a useful optimization; they do not establish an
end-to-end speedup or attribute all CI time to one function.

This slice changes only source extraction in `rsi_identity`. It does not relax
ledger, run ownership, request, memory, budget, file, or recovery validation.

## Contract

- Cache only successful source strings for exact ordinary Python functions,
  bound methods, and classes backed by real `.py` files and `SourceFileLoader`.
- Observe bounded exact file bytes on every call and compare another fresh
  observation after extraction or lookup. Metadata alone never identifies source.
- Key the cache by source content, current file association, and the current
  unwrapped function code or class locator. Retain object references to prevent
  reuse of object ids from reusing an unrelated entry.
- Limit the process-local LRU to 256 entries, each at most 96 KiB. File observations
  are bounded to 2 MiB; larger or unsupported sources use the original path.
- Evaluate configuration, defaults, lexical captures, and explicit code hooks on
  every call. Do not cache the final identity, fingerprint, or failures.
- Preserve this Python interpreter's `inspect.findsource` and `getblock` behavior,
  including nested/decorated/conditional class definitions. Supply fresh lines in
  a private globals view; never alter process-wide `linecache` or `inspect`.
- Disable caching when the inspector or linecache functions change. Generated,
  custom-loader, and synthetic linecache sources keep the original inspection and
  bytecode fallback behavior. Unwrap cycles keep their existing refusal.
- Refuse an ordinary source or target association that changes during observation.
  Same bytes at a replacement inode may reuse a pure extraction result; this does
  not authorize a worker, candidate file, or publication.

## Acceptance

Focused identity tests must prove unchanged canonical identities, live hooks and
callable configuration, source edits despite unchanged mtime/size or stale
linecache, equal-byte file replacement, code/unwrap/file reassignment, observation
drift refusal, unchanged generated fallback, inspector changes, uncached failures,
and bounded eviction. Verify source extraction reuse with call counts rather than
fragile wall-clock thresholds. Ruff, compileall, and diff checks are required.

Provider workflow tests are deferred until parallel product edits are frozen.
Full child-flow CI is required before claiming an end-to-end speed improvement.
