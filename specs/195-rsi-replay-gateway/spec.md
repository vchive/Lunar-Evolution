# Feature 195 — retained producer replay gateway

## Goal

Provide a narrow local bridge from the existing OpenEvolve/Shinka receipt replay
diagnostic into the ordinary RSI `SolverGateway` contract. The bridge is useful for
controller resume and failure-state testing without starting a producer or evaluator.

## Contract

- `RetainedProducerReplaySource` stores the five local input paths and seven independent
  SHA-256 pins. Paths are lexical identities only; every read is delegated to the
  existing no-follow replay inspector.
- `RetainedProducerReplayGateway.run(request)` accepts only the pinned producer id,
  reads the independently pinned original request and compares its complete wire before
  incomplete evidence can become unknown. Episode, evaluator, environment, memory,
  settings, charter and budget changes refuse. It reparses a completed `SolverResult`
  and checks episode/request identity.
- Missing or incomplete retained evidence maps to a stable `unknown` result. Drift,
  malformed completed evidence, and request mismatch fail closed with fixed RSI errors.
- `validate_replay(request, result)` repeats the read-only comparison and requires an
  exact result wire. The controller uses this hook for terminal and nonterminal resume,
  cached executions and direct episode recovery. Completed evidence is not dispatched
  again, and a drift refusal leaves the retained ledger head unchanged.
- Request-file byte SHA and canonical SolverRequest SHA remain distinct. The material
  descriptor pin binds the producer envelope's ordered descriptors; it is not an
  evaluator verdict or evidence of a newly executed producer.
- The gateway is explicitly replay-only. It never launches a process, invokes an
  evaluator, creates a ledger, or sets `production_admission=true`.

## Non-goals

This feature does not authenticate external workers, provide distributed ownership,
run a real OpenEvolve/Shinka campaign, or establish sealed CPython/runtime evidence.
Those remain separate P1/P2 work and cannot be inferred from a local replay.
