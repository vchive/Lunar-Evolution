# BRS local owner ready/ack

## Bounded continuation

Continue the DRS first-pin contract with an in-process BRS prepared-evidence channel.
Use only inert local fixtures. Support one Python admission child in a wave alongside
ordinary siblings. The original run has one producer proof/journal and an admission
attempt is globally unique; preserve those restrictions. Multiple independent Python
children require a separate per-episode original binding/journal/attempt routing design.
This slice does not wire real Python scheduler inputs or admit a sealed runtime.

## Owner and worker authority

The parent still reserves and persists all wave intents/budgets before dispatch, holds
the controller lock, uses one frozen memory parent, and saves executions in ordinal
order. During the wait for an ordinal future, it services ready messages from any
dispatched episode; workers never acquire the controller lock or write the controller
checkpoint. Unbound BRS behavior stays compatible.

Bind a wave to the exact controller, ledger/workspace/sidecar identities, run, active
state, original checkpoint and fixed dispatched episode IDs. Fresh worker execution
scopes only that wave/episode on its thread. Direct, nested/unrelated, wrong-thread,
non-dispatched and recovered executions have no ready authority. The DRS facade keeps
requiring DRS owner context and cannot become a generic BRS mutation entry.

The worker-facing publication facade revalidates original proof and the exact request
at entry and every transaction evidence boundary. After the journal is durable and
handoff/anchor are verified, it sends callback-free canonical original plan/journal/
anchor bytes. Messages and queue membership are bounded by the dispatched wave and
each episode submits at most one request. The channel does not inspect files or grant
launch/evaluator authority. Acknowledgement binds the exact message and record digest.

The owning thread parses the request again, verifies its original wave/request, current
captured head and expected state, then pins using CAS and the existing evidence checks.
It independently verifies the expected checkpoint and acknowledges only the precise
reference increment. A second distinct Python admission episode is refused, not given
a reused handoff or relaxed attempt uniqueness. No latest-state adoption, row repair,
budget/deadline refresh, native result retrofit or automatic unknown retry is allowed.

## Shared observation and waiting

Use a separate reentrant observation lock around the owner's atomic pin plus exact
in-memory acknowledgement and the workers' producer/reference observations. This lock
is not controller ownership. Hold it only for observation/mutation, never while waiting
for ready, ack, a future or executor shutdown. Owner execution merge/save and the wave's
captured head advance use the same lock and only the state this owner explicitly saved.
Unrelated checkpoint changes still refuse. Workers never adopt a checkpoint payload.

The service loop preserves ordinal result save/merge but must service queued ready
requests while earlier futures run, including when max_workers is below wave size.
The worker's wait repeatedly checks original RSI budget/deadline and supplied execution
control. Cancellation/timeout removes an unhandled request; a racing durable pin remains
an obligation and is never rolled back. Handler/pin/ack failure wakes its requester with
a fixed refusal. Owner exit closes the channel and wakes all waiting workers before
executor shutdown; new requests on a closed channel refuse immediately.

Pin success followed by acknowledgement failure retains durable row/reference and
leaves the old state stale. The owner stops progress and recovery must reload/revalidate
the obligation. A failed ready request invokes no evaluator or publication; already
durable worker results, budgets and unknown markers remain preserved.

## Interfaces and verification

Put the bounded channel in `rsi_python_brs_admission.py`. Controller private worker
hooks are `_python_admission_active_brs_worker(run_id, episode_id)` and
`_request_python_admission_for_brs_worker(..., wait_check=...)`, returning the retained
record digest after owner acknowledgement. Expose an explicit BRS publication facade;
keep existing DRS/public pin and read-only recovery APIs compatible.

Cover out-of-order ready vs ordinal save, one Python child plus ordinary siblings,
max_workers < pending, no worker controller lock acquisition, synchronized sibling
observations during pin, original CAS/state drift, pin/ack failure, owner exit, nested
scope cleanup, duplicate/multi-child refusal, cancellation/deadline and no missing-row
repair. Include actual BRS futures/controller settlement with inert transaction/provider
seams, and channel shape/lifecycle tests. Preserve original failure evidence.

Run focused/compatibility tests, Ruff, compileall and diff checks. Final source requires
its own three-version full CI and independent raw/source/tree audit. Do not label inert
provider tests as actual native gateway, runtime, OpenEvolve/Shinka or production acceptance.
`production_admission=false`; P2 services/distributed ownership remain deferred.
