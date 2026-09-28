# RSI memory commit contract

RSI memory is a verifier-gated, content-addressed snapshot. It is intentionally separate from the
existing `MemoryStore` notes and from Feature 044 experiment-memory projections.

## Commit request

```json
{
  "schema_version": "1",
  "kind": "rsi_memory_commit",
  "run_id": "rsi-...",
  "episode_id": "episode-...",
  "parent_snapshot_sha256": "<sha256>|null",
  "verifier_decision_sha256": "<sha256>",
  "entries": [{"trigger": "...", "strategy": "...", "failure_boundary": "..."}]
}
```

The controller validates that the verifier decision is `pass`, the episode is terminal and all
contract/evaluator/environment/receipt digests still match. It normalizes and bounds each entry,
computes the new snapshot digest, and atomically creates the snapshot only if the current parent
digest equals `parent_snapshot_sha256`.

## Read rules

An episode starts with one immutable memory snapshot. Retrieval is scope- and compatibility-filtered
by contract family, environment, solver and snapshot digest. Memory writes are disabled during a
frozen-memory transfer test. A caller can inspect rejected/unresolved diagnostics, but those records
are excluded from approved retrieval.

`MemoryStore.remember()` remains available for ordinary user notes. It is not a valid implementation
of this contract because it has no verifier decision, content-addressed snapshot, or compare-and-swap
lineage.
