# Durable local solver gateway

## Problem and scope

`AdapterContractHarness` describes a provider-free lifecycle but keeps no durable invocation
state. Repeating the same request executes again. `PracticeEpisodeRunner` records a returned
result in the RSI ledger only after `gateway.run()` returns, leaving a worker-completion to
controller-publication interruption window.

Add an explicit `DurableSolverGateway(gateway, ledger, *, scope_id)` wrapper. It reuses the existing
trusted local SQLite `DurableCallbackJournal`, preserves complete `SolverResult` wire evidence,
and implements the ordinary `run(SolverRequest)` protocol. Existing gateways and controller/store
behavior remain unchanged unless the caller opts in.

This is a local idempotency boundary, not process ownership, external source authentication,
remote exactly-once execution or an independent verifier. No real OpenEvolve/Shinka campaign,
model, remote evaluator or transport implementation is introduced.

## Contract

- RSI episode IDs are globally unique in the ledger. Use a fixed wrapper namespace and a key
  derived only from episode ID. Caller scope and request digest are part of the binding, never
  the key; changing either for an existing episode must fail, not execute in a second namespace.
  An already-published legacy episode result without a wrapper claim also rejects a new call.
- Bind the full canonical request, gateway source/config identity and live `run` callable
  identity using the existing component fingerprint implementation. Bind wrapper scope and
  database device/inode; reject live configuration, callable or ledger replacement drift.
- Canonically copy nested request/result values. An adapter must not mutate its frozen request.
  Validate request and fingerprints before dispatch, after return and before replay is returned.
- Persist `started` before calling the gateway and the complete canonical result before returning.
  Reopening with identical configuration replays a completed invocation without another gateway
  call or application journal append. A returned `SolverResult.status == unknown` stays unknown
  on replay. This does not promise byte-read-only access to the entire filesystem: SQLite WAL,
  connection initialization and controller lock sidecars retain their existing behavior.
- A started invocation without a persisted result raises a fixed reconciliation-required error.
  It never calls the adapter again. Exceptions or invalid/drifted results leave that claim pending.
- `inspect(request)` validates identity and returns the journal checkpoint without dispatching.
- `run()` publishes the same full result to `RSILedger.save_episode_result()` before returning.
  The controller's existing second publication is idempotent. `restore_result(request)` reads
  only a completed journal and publishes its exact original result, without starting a claim or
  invoking the gateway. Missing, started or conflicting result publications reject.
- `reconcile(request, *, expected_checkpoint_sha256, result, evidence)` is an explicit trusted
  local failure-settlement API. It accepts only failed, timed_out, cancelled or abandoned results
  with exact episode/request identity and the existing callback binding/result/receipt evidence.
  Completed and unknown results are rejected even if their digests match. Exact reconciliation
  replay appends nothing; changed evidence or stale checkpoint rejects.
- No code path upgrades an uncertain invocation to successful completion from an operator's
  source label or a digest. Independently trusted successful completion remains a separate
  follow-up protocol. No memory admission, budget refresh or worker kill permission is granted.

The wrapper does not reserve additional solver/evaluator/unknown counters or independently
interpret adapter budgets. The controller and underlying execution adapter retain their original
admission/deadline responsibilities; the full original request budget is frozen in the binding.
The existing fingerprint helper's strict callable/config rules apply, including refusal of
unprojected mutable captures or unavailable implementation identity.

The completed callback journal is the wrapper's source of truth. A controller that died before
its own result publication may explicitly call `restore_result()` with the original request and
then use the existing episode recovery path. The wrapper does not automatically alter an episode
or overwrite an already-persisted unknown result. Completed replay with an already-published
episode result appends no application claim/result record; restoration of a missing publication
is an explicit write.

## Acceptance and tasks

- [x] DSA-01 Add the opt-in wrapper and strict request/result/fingerprint binding.
- [x] DSA-02 Verify completed replay after reopening and after controller publication failure,
  with one physical gateway invocation and unchanged completed journal.
- [x] DSA-03 Verify started exceptions, returned unknown and interrupted completion publication
  never trigger a second invocation; invalid result and mutation also retain a pending claim.
- [x] DSA-04 Verify request, nested settings, gateway config/code, run callable, scope and database
  drift reject before dispatch/replay; distinct episode IDs remain independent.
- [x] DSA-05 Verify failure-only reconciliation, exact CAS replay, evidence conflicts and refusal
  of all success/unknown settlements. Concurrent callers execute once.
- [x] DSA-06 Run focused tests, Ruff, compileall and diff whitespace checks. Local fixtures are
  supporting evidence only; external ownership/authentication and true campaign acceptance stay open.

Local focused validation: 54 gateway units plus controller integration, existing durable callback
and adapter-contract suites passed in `/tmp/lunar-durable-gateway-focused-20261001.xml` (113 cases).
Ruff, compileall and diff checks passed. All fixtures are local/provider-free; no real model,
remote evaluator, company platform or external campaign ran.
