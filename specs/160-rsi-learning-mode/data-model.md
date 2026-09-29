# Data Model: RSI learning mode

Feature 160 introduces a durable learning control plane beside the existing evolution archive.
All records below are bounded JSON documents. A record is canonicalized with sorted keys, compact
separators and `allow_nan=false`; its digest is SHA-256 of those canonical bytes. Persisted records
are immutable. A later state is a new record linked to the previous record by digest.

## Shared identities

| Field | Meaning |
| --- | --- |
| `run_id` | One RSI learning run. It owns the curriculum budget and memory branch. |
| `episode_id` | One practice or target execution. It is never reused after terminal evidence exists. |
| `contract_sha256` | Exact `AlgorithmProblemContract` or environment task contract used by the episode. |
| `evaluator_sha256` | Exact official evaluator/receipt protocol used for the episode. |
| `environment_sha256` | Sanitized runtime, dependency, tool-capability and fixture identity. Credentials and hostnames are excluded. |
| `memory_snapshot_sha256` | Frozen parent snapshot read by the episode; `null` means the empty snapshot. |
| `solver_id` / `solver_fingerprint` | Registered solver adapter and its immutable settings. Population state is referenced as provenance only. |

## RSI run

```json
{
  "schema_version": "1",
  "kind": "rsi_run",
  "run_id": "rsi-...",
  "mode": "brs|drs",
  "status": "created|running|paused|completed|failed|cancelled|unknown",
  "contract_sha256": "<sha256>",
  "evaluator_sha256": "<sha256>",
  "environment_sha256": "<sha256>",
  "memory_scope": "problem-family:...",
  "root_memory_snapshot_sha256": null,
  "max_waves": 3,
  "max_practice_rounds": 8,
  "max_target_attempts": 4,
  "wall_timeout_seconds": 1800,
  "no_improvement_limit": 2,
  "created_at": "2026-09-28T00:00:00Z",
  "previous_record_sha256": null,
  "record_sha256": "<sha256>"
}
```

`paused` is resumable. `unknown` means the controller cannot prove whether an external worker
finished; it requires reconciliation and cannot be silently retried. A run can be completed only
after all target/transfer evidence required by its mode is terminal.

## Practice episode and target attempt

Both use the same envelope and differ by `episode_kind`:

```json
{
  "schema_version": "1",
  "kind": "rsi_episode",
  "episode_id": "episode-...",
  "run_id": "rsi-...",
  "episode_kind": "practice|target",
  "status": "planned|running|completed|failed|timed_out|abandoned|cancelled|unknown",
  "wave": 1,
  "ordinal": 0,
  "parent_target_episode_id": "episode-...",
  "curriculum_decision": {
    "practice_family": "...",
    "capability_gap": "...",
    "reason_code": "target_failure_gap",
    "decision_sha256": "<sha256>"
  },
  "practice_charter_sha256": "<sha256>",
  "contract_sha256": "<sha256>",
  "evaluator_sha256": "<sha256>",
  "environment_sha256": "<sha256>",
  "memory_snapshot_sha256": "<sha256>",
  "actor_fingerprint": "<sha256>",
  "solver_id": "native_population|openevolve|shinka|...",
  "solver_fingerprint": "<sha256>",
  "budget": {"tool_steps": 40, "candidate_attempts": 8, "wall_timeout_seconds": 300},
  "trace_digest": "<sha256>",
  "actor_fingerprint": "<sha256>",
  "solver_fingerprint": "<sha256>",
  "candidate_source_sha256": "<sha256>|null",
  "dependency_sha256": "<sha256>|null",
  "trace_events": [{"sequence": 0, "kind": "action|tool|observation", "name": "...", "payload_sha256": "<sha256>", "observation_sha256": "<sha256>|null"}],
  "candidate_receipt_sha256": null,
  "execution_receipt_sha256": null,
  "official_evaluation_receipt_sha256": null,
  "verifier_decision_sha256": null,
  "terminal_reason": null,
  "previous_record_sha256": null,
  "record_sha256": "<sha256>"
}
```

`candidate_receipt_sha256`, execution receipt and official evaluator receipt must point to existing
Lunar evidence. A solver score or an unverified model response cannot fill any of these authority
fields. `trace_digest` covers a bounded action/tool/observation summary; raw private chain-of-thought
is never a required or accepted field.

## Verifier decision

```json
{
  "schema_version": "1",
  "kind": "rsi_verifier_decision",
  "episode_id": "episode-...",
  "outcome": "pass|fail|unresolved",
  "checks": [
    {"name": "official_evaluator", "status": "pass", "receipt_sha256": "<sha256>"},
    {"name": "transfer_generalization", "status": "pass", "receipt_sha256": "<sha256>"}
  ],
  "diagnosis": {"capability_gap": "...", "failure_boundary": "..."},
  "verifier_fingerprint": "<sha256>",
  "independent_of_actor": true,
  "record_sha256": "<sha256>"
}
```

`independent_of_actor` is true only when the verifier uses a separate process/runtime and receives
only the declared episode evidence, contract, evaluator and environment pins. `unresolved` covers
timeout, abandoned, worker-unknown, missing evidence and integrity mismatch. It is never treated as
pass for memory promotion.

## Approved memory snapshot

An RSI memory snapshot is a content-addressed ordered set, not a mutable row or free-form note:

```json
{
  "schema_version": "1",
  "kind": "rsi_memory_snapshot",
  "snapshot_sha256": "<sha256>",
  "parent_snapshot_sha256": "<sha256>|null",
  "scope": "problem-family:...",
  "entries": [
    {
      "memory_id": "rsi-memory-...",
      "trigger": "when ...",
      "strategy": "...",
      "condition": "when ...",
      "action": "...",
      "observed_result": "...",
      "applicability": "...",
      "expected_result": "...",
      "failure_boundary": "...",
      "compatible_contracts": ["<sha256>"],
      "compatible_solvers": ["native_population"],
      "source_episode_id": "episode-...",
      "verifier_receipt_sha256": "<sha256>",
      "status": "approved"
    }
  ],
  "record_sha256": "<sha256>"
}
```

An entry is eligible only when its source episode has a `pass` verifier decision and all authority
receipts are intact. Failed, unresolved, timed-out, abandoned or unknown episodes may be retained as
diagnostics but cannot appear with `status=approved`. Commit is compare-and-swap on the parent digest;
two concurrent waves must not silently merge different parents.

## Frozen-memory transfer receipt

```json
{
  "schema_version": "1",
  "kind": "rsi_transfer_receipt",
  "transfer_id": "transfer-...",
  "run_id": "rsi-...",
  "target_episode_id": "episode-...",
  "memory_snapshot_sha256": "<sha256>",
  "curriculum_enabled": false,
  "memory_write_enabled": false,
  "solver_fingerprint": "<sha256>",
  "official_evaluation_receipt_sha256": "<sha256>",
  "outcome": "pass|fail|unresolved",
  "record_sha256": "<sha256>"
}
```

Transfer execution must reject any memory write or curriculum mutation. The transfer result is a
measurement of the frozen snapshot and never changes that snapshot.

## State transitions

```text
run:       created -> running -> paused -> running -> completed
                              \-> failed|cancelled|unknown
episode:   planned -> running -> completed|failed|timed_out|abandoned|cancelled|unknown
verifier:  absent -> pass|fail|unresolved
memory:    candidate -> approved|rejected|unresolved
transfer:  planned -> running -> completed|failed|unresolved
```

Every transition records the prior record digest, actor/controller identity, reason code and the
relevant evidence digests. Resume continues a non-terminal record; it does not create a second
execution for an episode with a known terminal receipt.
