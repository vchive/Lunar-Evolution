# SolverGateway contract

`SolverGateway` is the only boundary through which RSI Actor code invokes a search workflow. It is
an orchestration interface, not an `EvolutionStrategy` implementation. The gateway may delegate to
Native Population, OpenEvolve, ShinkaEvolve, a traditional SolverAdapter, or a mock fixture.

## Request

```json
{
  "schema_version": "1",
  "kind": "rsi_solver_request",
  "episode_id": "episode-...",
  "contract_sha256": "<sha256>",
  "evaluator_sha256": "<sha256>",
  "environment_sha256": "<sha256>",
  "memory_snapshot_sha256": "<sha256>",
  "solver_id": "openevolve",
  "solver_settings": {"iterations": 5},
  "practice_charter": {"goal": "...", "constraints": ["..."]},
  "budget": {"candidate_attempts": 8, "wall_timeout_seconds": 300},
  "workspace": "episode/episode-..."
}
```

The controller resolves and fingerprints the solver before launch. The gateway receives a read-only
memory snapshot and may write only beneath its episode workspace. It cannot call the RSI memory store,
change the contract/evaluator/environment pins, or claim verification.

## Result

```json
{
  "schema_version": "1",
  "kind": "rsi_solver_result",
  "episode_id": "episode-...",
  "status": "completed|failed|timed_out|abandoned|unknown",
  "candidate_receipt_sha256": "<sha256>|null",
  "execution_receipt_sha256": "<sha256>|null",
  "official_evaluation_receipt_sha256": "<sha256>|null",
  "solver_score": 0.0,
  "solver_provenance": {"population": "...", "island": 0, "iteration": 1},
  "trace_digest": "<sha256>",
  "terminal_reason": "..."
}
```

`solver_score` and `solver_provenance` are informational. The official evaluator receipt and the
independent verifier decide whether a practice can teach memory. Any missing or conflicting receipt
is an `unresolved` verifier input, even if the solver returned success.

## Required behavior

1. The gateway must be deterministic with respect to the request pins and must persist a bounded
   launch/result record before returning.
2. A worker timeout, cancellation, abandoned process or unreconciled lifecycle is returned as the
   corresponding terminal status and cannot be converted to `completed` by the Actor.
3. Resume accepts the same request digest and episode ID only. Changed solver settings, contract,
   evaluator, environment or memory snapshot are rejected.
4. Gateway implementations must preserve the existing candidate execution/evaluation receipt and
   recovery semantics of the selected solver.
