# Provider-free solver adapter contract (B5)

This document defines the narrow adapter boundary used by RSI before a real solver process is
introduced. It is implemented by `lunar_evolution.rsi_adapter_contract` and deliberately wraps the
existing `SolverGateway` request/result wire types.

## Lifecycle

An adapter invocation has the following ordered phases:

`register -> preflight -> snapshot -> execute -> observe -> finalize -> verify -> recover -> close`

`recover` is entered for `failed`, `timed_out`, `cancelled` and `unknown` outcomes when the
capability declares recovery. A legacy provider-free gateway that only has `run(SolverRequest)` is
still valid: the harness supplies the other phase records and calls `run` in the execute phase.
`close` is always recorded and is best effort for a failed invocation.

The `verify` phase is an observation hook. It does not make a verifier decision and cannot promote
memory. Independent verification remains a Lunar control-plane responsibility.

## Identity and authority

`AdapterRequest` carries one immutable episode ID, solver ID, four content-addressed pins
(contract, evaluator, environment and memory snapshot), bounded solver settings/charter, a bounded
budget and an optional monotonic deadline. A result must return the same episode ID and the digest
of the canonical `SolverRequest`; changed pins are rejected by the harness.

`AdapterReceipt` is the bounded authority-neutral result envelope. It preserves the candidate,
execution, official-evaluator and trace receipt digests and maps terminal states to exactly one of
`completed`, `failed`, `timed_out`, `abandoned`, `cancelled` or `unknown`. Timeout and cancellation
are never converted into success. An exception with no stronger signal maps to `failed`; an
uncertain/unknown exception maps to `unknown`.

The adapter owns only its workspace/process cleanup. `AdapterOwnership.memory_write_enabled` is
always false. The harness rejects gateways exposing memory-store or memory-commit authority, and
adapters must not call `RSIMemoryStore` directly. Promotion is performed only after the controller
receives an independent verifier decision.

## Capabilities and fixtures

`AdapterCapability` declares snapshot, recovery, verification-hook and cleanup support. The
`fixture_capability("openevolve")` and `fixture_capability("shinka")` declarations identify
provider-free compatibility fixtures; they do not import, start or contact either external
project. `OPENEVOLVE_CAPABILITY` and `SHINKA_CAPABILITY` are declaration constants for registry
planning.

The contract is intentionally narrower than a production process supervisor. Durable process
attestation, external evidence reconciliation, sandboxing and real OpenEvolve/Shinka launch remain
follow-up work before a remote adapter can be admitted.
