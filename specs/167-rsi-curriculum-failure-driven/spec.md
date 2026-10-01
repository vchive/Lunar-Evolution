# Feature 167: provider-free failure-driven curriculum

## Scope

This feature supplies the narrow, deterministic B4 curriculum policy for RSI learning mode. It
runs entirely in the controller process and consumes only bounded public failure observations. It
does not call an LLM, evaluator, solver, WebAgent, or remote service, and it does not mutate the
approved `RSIMemoryStore` snapshot.

## Contract

`FailureObservation` is the minimal ontology: failure code, capability, observable symptom,
failure boundary, practice task, transfer task, prerequisites, and an optional hard-negative task.
Observations with the same normalized failure code, capability, observable, and boundary form one
content-addressed cluster. Recording the same observation is idempotent.

`FailureDrivenCurriculum.choose(...)` remains compatible with the existing `Curriculum` protocol. Its component fingerprint covers only policy version, seed, and budget; the mutable ledger is run state and is checkpointed separately.
It returns the existing `CurriculumDecision`, while `selections` and `to_ledger()` expose the
selection audit. Every selection records:

- cluster and task identity plus a deterministic selection id;
- reason (`failure_cluster_gap`, `hard_negative`, or `failure_boundary_probe`);
- newly covered capability and prerequisite names;
- novelty score and whether the task is a hard negative;
- budget before/after/remaining, seed, and ordinal.

A repeated cluster never emits the same practice task twice. The first repeat chooses its declared
hard negative or a deterministic `:boundary` task. Further repeats receive deterministic suffixes,
so recurring failures generate distinct boundary probes instead of an unbounded retry loop.

## Replay and failure behavior

The ledger contains only canonical JSON values, observations, and selection records. Reconstructing
with `FailureDrivenCurriculum.from_ledger(ledger, seed, budget)` restores the same cluster and
selection state; the next choice is byte-for-byte equivalent for the same target, diagnosis,
wave, ordinal, seed, and budget. A mismatched seed/budget, tampered selection id, novelty, or
unknown ledger event fails closed. Selection after budget exhaustion raises
`rsi_curriculum_budget_exhausted`.

The policy is deliberately not an exploration bandit or reinforcement learner. Coverage and
novelty are deterministic audit signals, not a claim of transfer success. Promotion and transfer
remain verifier/memory-governance responsibilities.
