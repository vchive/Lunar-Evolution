# Feature 196 — BRS-2 owner/worker handoff contract

## Status and scope

This SDD freezes the in-process owner/worker boundary needed by native BRS. The
detached handoff value/gates and a selected-episode channel binding sub-slice are
implemented and tested. A private controller owner-service seam now constructs pins
from an actual BRS checkpoint, binds one selected handoff, rechecks worker identity
and ready messages, and closes the channel before executor shutdown. It is exercised
only against complete owner-held BRS projections; legacy DRS-shaped state is refused.
A private owner-only checkpoint settlement seam now records the exact returned
selected execution through the existing CAS and full readback. Public native BRS,
selected-child producer staging, sibling transition and publication remain open;
no existing provider-free DRS/BRS behavior is changed.

The next bounded slice closes the legacy active-worker publication helper and the
generic/DRS facade and native scheduler bypasses. A BRS worker can still request an
exact prepared pin/ACK, but cannot execute a publication transaction. Successful
publication and rejection C1/P/C2 remain unimplemented for native BRS. The actual
pre-publication owner bridge and its timing constraints are described in
[`owner-publication-bridge.md`](owner-publication-bridge.md).

The first implementation accepts a fresh BRS wave with `max_workers=1`. The parent
controller reserves the complete wave once, freezes one root memory snapshot (`M0`),
and selects one ordinal at a time. A worker may perform the selected child's producer
work and original execution-record lifecycle. The owning controller thread performs
controller checkpoint, admission CAS, shared publication workspace and lineage mutations.
Worker writes of its original running episode/native result do not grant authority
over those owner operations.

This slice uses the existing in-process ready/ack channel and existing durable rows.
It introduces no SQL table, ledger row kind, wire protocol, RPC, scheduler service,
remote worker, remote evaluator, or production admission. `max_workers>1`, multiple
native children in one shared workspace, and distributed ownership remain later work.

### Current reserved-wave serial extension

The private reserved-wave serial extension is implemented in the current working
tree as bounded projection/prefix and ledger/reservation readers, fresh preparation
exchange, native provider/completion, serial driver, rejection readers and governed
finalization readers. Focused component checks exist, but the natural two-child
`rejected -> rejected` owner admission/mailbox integration is not accepted. The
earlier local run stopped at
`rsi_brs_reserved_prefix_material_path_invalid` while validating the rejection
evidence material path/pin contract; the strict path/pin mapping is now repaired
and its focused validator regressions pass. The latest integrated run advances to
`rsi_brs_reserved_serial_settled_transport_missing`, which remains open until the
owner/settled-transport contract is repaired and the complete V01-V10 matrix plus
final-source gates pass. The extension remains private; public native BRS,
production admission, remote workers/evaluators, distributed ownership and P2
service paths stay closed.

## Authority model

The **wave owner** is the controller thread that created the fresh run and holds the
existing controller ownership context. It alone may reserve or settle wave budget,
create a child staging permit, perform admission CAS, advance the captured head,
invoke publication-lineage owner operations, save the checkpoint, and close the wave.

The **selected worker** receives a one-shot, in-memory dispatch handoff for one
`(run_id, wave_id, episode_id, ordinal)`. It may run the selected child's producer
seams, observe its own execution evidence, and submit one prepared
`BRSAdmissionReady` request through the existing channel. It never receives the parent
controller lock or a publication-lineage owner object. It never writes the controller
checkpoint, changes a head, settles another episode, chooses a later ordinal, or
calls a public DRS mutation API. In the planned publication bridge, publication
evaluation and the complete archive/lineage/rejection transaction run on the owner.

Ready/ack has one meaning: it proves the exact prepared admission record was pinned by
the owner and returns its retained record digest. It does not authorize launch,
staging, evaluator invocation, publication, memory promotion, C1/P/C2 handling, or
recovery. An acknowledgement cannot be used as a lineage or parent-owner token.

## Handoff identity and lifetime

The handoff is an ephemeral detached value, not a new persisted schema. Before the
worker starts, the owner captures and binds:

- run and wave identifiers, selected episode identifier, ordinal, and one-shot lease
  nonce;
- canonical request digest and selected intent digest;
- root memory/checkpoint digest (`M0`), captured current head and payload digest;
- exact controller, ledger, workspace, sidecar and owner-thread identities;
- source, policy, evaluator, environment and execution-control fingerprints;
- fixed `max_workers=1` and the original wave budget reservation.

The worker must present the same canonical handoff and an invocation-scoped worker
capability. The owner rechecks the handoff, request, current captured head, expected
state, and source/policy fingerprints at every evidence boundary. A worker or nested
callback cannot reconstruct authority by reading a checkpoint, a latest state, a
retained receipt, or a serialized ready message.

The handoff expires when the selected child reaches a durable terminal result,
unknown/error/cancelled close, owner drift, deadline, or wave close. It cannot be
replayed for a second episode or reused after acknowledgement. Existing durable
failure and unknown evidence remains available for read-only recovery; no automatic
retry or row repair is implied.

## Required call boundary

The planned call sequence is:

1. The owner runs BRS preflight, reserves the whole wave and persists all intents
   against `M0`; it selects the next ordinal without refreshing sibling requests.
2. The owner creates the selected child's exact staging/dispatch permit while holding
   the existing owner context. The run ownership lease remains held for the whole
   live wave, including waits, so another process cannot mistake it for recovery.
3. The worker enters its invocation scope with the one-shot handoff and runs only
   the selected producer. After receipt/output/handoff, it submits bounded original
   evidence to a separate publication mailbox and waits before any transaction.
4. While any future is running, the owner services ready requests without holding the
   observation mutex or workspace mutation lock while waiting or running a worker
   callback. It retains the run ownership lease; the original owner-thread and CAS
   checks still guard each short admission mutation. It verifies the original
   wave/request and performs the existing precise admission CAS.
5. The owner executes the complete publication transaction while the original episode
   is running and claim is started. Its prepared observer pins the actual journal/anchor
   by exact CAS. Existing ready/ACK remains a pin-only facility, not a prerequisite
   publication grant. Success uses before/staged/terminal; rejection C1/P/C2 also runs
   on this owner before detached publication-result delivery.
6. The worker revalidates the returned evidence, then completes its normal native result
   and episode. It never receives a lineage owner or publication capability.
7. On close, the owner closes the channel/mailbox before executor shutdown and wakes
   every waiter. A racing durable pin remains an obligation. Only successful shutdown
   permits the existing selected execution checkpoint settlement; serial next ordinal
   still needs an independent exact transition.

The owner may service a queued ready request while an earlier ordinal future runs,
but it must not let a later child publish against a stale head. If a head, payload,
controller, ledger, workspace, sidecar, owner-thread, request, or source fingerprint
drifts, the request is refused and durable evidence is retained for reconciliation.

## Terminal and refusal semantics

The handoff recognizes `prepared`, `running`, `ready`, `acknowledged`, `completed`,
`rejected`, `unknown`, `cancelled`, `error`, and `closed` observations. Only the
owner can make a terminal settlement. `unknown`, timeout, cancellation, owner exit,
CAS failure, and channel close stop fresh sibling dispatch for the wave unless a
later recovery contract explicitly permits it. They do not become success, ack,
publication, or a budget refresh.

A failed ready request invokes no evaluator or publication. A pin followed by ack
failure retains its durable reference and leaves the old state stale; recovery must
reload and revalidate that obligation. A second Python admission child must have its
own original intent, journal, claim, attempt and handoff; the first child's values
cannot be copied or relaxed to satisfy uniqueness.

## BRS-2c: private owner checkpoint settlement

This bounded private slice records one successfully returned selected execution in the
controller recovery checkpoint. It does not publish a candidate, promote memory,
select a sibling, reopen the channel, or enable the public native BRS driver.

The owner may call the private settlement seam only after the selected service and
executor shutdown have succeeded. An invocation-scoped in-memory return receipt
binds the original returned object and canonical execution bytes, handoff, retained
ACK and durable result to that service. A caller-created equivalent result is not
an execution grant. The receipt is neither a new durable schema nor recovery
permission and is consumed at most once.

Before settlement the owner rechecks its run lock/thread, exact controller/ledger/
workspace/sidecar, original handoff, M0, request, source/configuration, planned
reservation, retained ACK, episode/result and captured checkpoint. Source and
configuration hooks remain outside the short observation mutex; the original run
ownership lease stays held. Only the selected execution and evaluated/current
checkpoint fields may advance. Sibling requests and budgets stay original.

Settlement uses the existing `_save_flow` CAS against the captured head, then reads
back the complete exact checkpoint. Only successful readback advances the wave's
in-memory head/payload and consumes the return receipt. A CAS failure or ambiguous
write/readback keeps the old captured head stale, preserves any durable obligation,
and grants no retry, latest-head adoption, repair, publication or sibling dispatch.
The settlement seam itself does not resolve an unknown durable outcome.

The original state object and actual owner object identities are rechecked against
the frozen handoff before and after save/source callbacks. Unknown rollback restores
only the captured state object and original budget/head; a foreign replacement state
is not cleared or adopted. The execution parser accepts only known exact DTOs,
exact attribute dictionaries/string keys and recursive exact containers/primitives.
Type dispatch uses identity comparisons, and nested fields are read only after
safe detachment; worker-held mapping, key, serializer, equality and metaclass
callbacks cannot run before rejection.

## Non-goals

This feature does not enable native BRS, implement multi-child publication, add
external-worker authentication, distributed/multi-machine ownership, official or
remote evaluators, OpenEvolve/Shinka campaigns, sealed runtime acceptance, a new
CLI mode, or a new persistence schema. Those require separate approved SDDs and
independent acceptance evidence.
