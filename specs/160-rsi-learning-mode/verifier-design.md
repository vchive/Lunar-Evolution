# P1 bounded native execution and independent verification

## Scope

`NativePopulationGateway` implements `SolverGateway.run` for one local multi-file proposal using
Lunar's existing native population pipeline without publishing into an evolution population.
The context and proposal factories are host-owned adapters; this is neither a model-backed
AgentLoop acceptance nor an OpenEvolve/Shinka campaign adapter. `NativeIndependentVerifier`
implements `verify(episode, request, result)` and must be passed explicitly to RSI controllers.
The deterministic mock verifier remains a fixture.

## Execution and admission

The gateway pins the episode/request and bounded local profile before executing a proposal. It
retains the native bundle, workspace plan, admission, process cleanup, execution completion,
evaluator snapshot, and a canonical RSI candidate receipt. Dependencies are an explicit bounded
file list whose bytes are hashed; the environment fingerprint hashes declared runner/evaluator
commands, executable bytes and environment. This is a local declared dependency boundary, not a
claim to inventory every OS library or provide an OS security sandbox.

A fresh episode runs at most one candidate process and one independent evaluator. Existing
terminal results are inspected read-only before returning. An intent without a complete RSI
result is unknown and is never replayed implicitly. Changed request identity is rejected.

## Verification

The independent verifier does not accept digest-shaped strings as proof. It resolves retained
paths without symlinks, compares the stored SolverResult to the supplied result, rehashes the RSI
receipt, validates source bundle bytes and file table, and calls Lunar's native execution and
evaluator inspectors. It compares contract, evaluator, dependency, environment, admission,
runner, input/output and completion bindings. Candidate cleanup must be verified.

It then copies only verified source bytes into a new verifier-owned workspace and runs the
candidate and exact evaluator again. The evaluator already uses a separate read-only input/output
snapshot and process; the original Actor workspace is reopened only for inspection. The new
execution/evaluation receipts are retained rather than discarded. The official report must be
valid and agree with the independent report. Evidence is inspected again after the rerun to detect
changes during verification.

Exact equality is deliberately conservative: nondeterministic scoring, missing/changed evidence,
timeout, incomplete lifecycle, unsupported profile, and unavailable evaluator are unresolved.
An exact invalid evaluator result is fail and cannot teach memory. A pass proves this candidate
and contract under this local profile; it does not prove held-out transfer improvement.

## Verification plan

Real local subprocess fixtures cover successful rerun, no implicit repeat on exact retry, result
forgery, source/helper mutation, missing receipt, same-byte inode replacement, dependency and
executable/environment drift, mismatched request pins, invalid candidate result, interrupted
intent, and controller integration with explicitly selected native verifier. No network or model
calls are permitted in this validation.
