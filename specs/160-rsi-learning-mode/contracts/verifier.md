# Independent Verifier contract

The Verifier is a separate authority boundary from the Actor and SolverGateway. It receives a
bounded evidence manifest, exact contract/evaluator/environment pins, and a read-only candidate
workspace. It does not receive Actor private reasoning, mutable draft memory, or an unchecked solver
score as an authority signal.

```json
{
  "schema_version": "1",
  "kind": "rsi_verifier_request",
  "episode_id": "episode-...",
  "contract_sha256": "<sha256>",
  "evaluator_sha256": "<sha256>",
  "environment_sha256": "<sha256>",
  "evidence": {
    "candidate_receipt_sha256": "<sha256>",
    "execution_receipt_sha256": "<sha256>",
    "official_evaluation_receipt_sha256": "<sha256>",
    "trace_digest": "<sha256>"
  },
  "memory_snapshot_sha256": "<sha256>|null"
}
```

The response is the `rsi_verifier_decision` in the data model. Verifier implementations must:

- re-open and hash every declared receipt and reject changed bytes, missing files, path escapes,
  duplicate evidence ownership and evaluator identity drift;
- use a separate process/runtime or an explicitly declared independent adapter;
- return `unresolved` for timeout, worker `unknown`, abandoned execution, unavailable evaluator,
  insufficient holdout evidence or any integrity ambiguity;
- provide a bounded diagnosis and capability gap without copying private reasoning;
- never write an approved memory snapshot themselves. Only the controller may commit one after a
  `pass` decision and compare-and-swap of the parent snapshot.

The default MVP verifier is deterministic and local: it re-runs the exact evaluator in clean-room
mode, checks the declared output contract, and optionally runs a fixed transfer/holdout probe. An
LLM-assisted verifier may propose a diagnosis, but its result remains `unresolved` until the exact
checks pass.
