# PB-03i — controller response acceptance and native result CAS

## Status

The private selected owner service now has a narrow owner-side response boundary. After the
worker has returned its detached `EpisodeExecution`, the original owner thread checks the
retained ready/ACK channel, native plan and claim, current controller checkpoint, and exact
terminal episode head. It then calls the ledger's `accept_native_episode_result` under the
existing controller lock and SQLite transaction before retiring the selected handoff.

This is provider-free local wiring only. It does not enable public native BRS, publication,
memory promotion, external workers, a remote evaluator, or a new persistence schema.

## Contract

`publish_native_episode_result` remains the worker-side create-only result write. The new
owner-side method is a separate acceptance boundary with these required pins:

- the exact `SolverRequest`, native plan digest, and original `NativeEpisodeClaim`;
- the original controller run lock and current checkpoint digest;
- the exact current episode record digest;
- a terminal `SolverResult` whose request, episode, status and immutable episode identity agree.

The method checks all pins inside one `BEGIN IMMEDIATE` transaction. It accepts an existing
result only when its canonical request/result bytes and result digest are identical. If the
worker result row is missing after a crash, it may insert that exact row only after the claim,
checkpoint and episode-head checks pass. It never creates a claim, changes an episode head,
advances controller lineage, publishes a candidate, changes memory, refreshes a budget, or
retries a sibling.

The selected channel exposes a read-only `assert_selected_handoff_acknowledged` check so a
missing or failed ACK is rejected before result acceptance. The check does not retire the
handoff or grant authority. The owner retires the handoff only after the CAS and durable
readback succeed; a failure leaves the original durable evidence and stale captured owner
context for explicit recovery.

## Validation and boundary

The local selected-service fixture covers the normal owner path and a missing native result
row that is recreated by the pinned owner CAS. Existing selected-service and settlement tests
continue to cover foreign owner, checkpoint drift, result drift, ACK failure, channel close,
unknown save and executor shutdown paths. Ruff, compileall and diff checks remain required.

This slice is not online publication. The owner still needs a separately reviewed response
mapper, successful `before/prepared/staged/terminal` transaction composition, known-rejection
C1/P/C2 composition, read-only reconcile and serial ordinal transition before public native
BRS can be considered.
