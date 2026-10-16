# BRS CI fixture scope and ACK mutation window

This follow-up changes tests only. It starts from `ed66333b40d4e3cabb9b8195321820e86f9a6a8e`
and preserves the original product refusal gates, process/network traps and
official PR107 failure evidence. It grants no worker publication authority.

## Observed fixture defects

The native scheduler rejection fixture allocates its controller with `__new__`.
Unlike a controller created by `__init__`, it had no BRS thread-local scope. The
new negative worker-publication gate therefore raised `AttributeError` before
either opt-in rejection assertion. The inert fixture now creates the same empty
flow/BRS `local()` scopes, absent BRS wave and observation `RLock()` as the real
constructor. It still uses genuine SQLite claims and exact DTOs; native recovery
and candidate observation remain explicit inert seams.

The shared-handoff mutation test previously called the full `_execute_intent`
before changing its handoff. That lets the worker append a completed episode
while the owner is revalidating an admission against a captured running episode
head. A controlled barrier reproduced `rsi_python_admission_episode_conflict`
before the intended handoff refusal, with the original regex unchanged.

## Required negative-test window

The fixture performs its genuine ready/ACK exchange and verifies the retained
reference first. An optional test-only `_ack_and_result` callback then observes
the running episode, unchanged started native claim and absent native result.
Only then does it mutate the selected handoff. A worker barrier keeps native
result publication and episode settlement unreachable during the owner's
identity check. The test keeps the original `selected_identity_invalid|handoff_`
refusal assertion; it does not accept a terminal CAS conflict instead.

The actual owner close path releases the barrier in `finally`, before the
executor's `shutdown(wait=True)`. The inert worker then stops deliberately and
records its own `finally` completion. Assertions require close-before-shutdown,
an owner-observed witness that the worker's wait returned successfully (so a
timeout stored in an unconsumed Future cannot look like successful cleanup),
one retained admission, the exact unchanged running episode/started claim, no
native result, no completed selected channel, and no sibling execution.

## Separate product diagnostic and evidence limits

The same forced running-to-completed interleaving also makes the existing
positive selected-service test fail closed with
`rsi_python_admission_episode_conflict`, without any handoff mutation. Its raw
log, diagnostic script and XML are retained separately. This is a product
concurrency concern, reported to the parent before this tests-only patch; these
fixture corrections do not resolve or hide it. Product changes or a revised
owner observation contract require a separate review. A normal positive focused
pass does not disprove the controlled interleaving.

Local evidence is retained in the implementation worktree's ignored report
directories `pr107-native-scheduler-rejection-fixture-*` and
`pr107-selected-handoff-window/`. Initial failures remain separate from repaired
tests. Validation covers local inert fixtures only: no model, producer, target
runtime, remote evaluator or external campaign is run.
