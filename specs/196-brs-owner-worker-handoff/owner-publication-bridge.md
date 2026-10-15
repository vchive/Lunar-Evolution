# Selected BRS owner publication bridge — online design and checkpoint primitive

## Verified gap

The private selected execution settlement runs after the worker future, channel close
and executor shutdown. By then the runner has completed the episode and saved its
native result. It is a checkpoint settlement boundary, not a publication boundary.
`RSIPublicationLineage` requires a genuine DRS dispatch scope, a running episode and
a started native claim. A completed BRS return cannot satisfy that contract.

The scheduler currently builds that DRS lineage owner before producer dispatch, then
`native_trusted_scheduler` calls the entire publication transaction on its calling
thread. The all-rejected scheduler continuation also writes rejection provenance on
that thread. Moving only lineage callbacks to the owner would leave evaluation,
shared archive staging/commit and rejection provenance on the worker.

The first implemented slice therefore refuses the existing worker publication facade,
its generic/DRS facade bypasses and the scheduler's live BRS worker path. Existing
prepared pin/ACK APIs remain available. Public native BRS stays disabled.

## Planned boundary

The worker must stop after original receipt/output/handoff evidence exists and before
the publication transaction begins. An independent, one-shot in-memory mailbox will
let the original BRS owner execute the whole transaction while the worker waits.
The original run lease remains held; neither side waits with the observation mutex
or a workspace mutation lock held.

The mailbox is separate from `BRSAdmissionChannel`: its existing ACK means only that
the exact prepared admission was pinned. It is not a publication capability. A request
contains bounded detached evidence and original digests/pins, never worker-supplied
callables or a lineage owner. The owner retains its own provider, strategy, workspace,
memory, control and policy. It re-reads pinned evidence before using those values.

The complete order is:

1. The owner captures selected child/staging/launch pins and the original reservation.
2. The normal runner/gateway creates the real running episode and started claim.
3. The worker produces receipt/output/handoff, submits once, then waits.
4. The owner checks the original wave/head/request and creates an explicit BRS owner.
5. The owner performs before/prepared pin/evaluation/staged/precommit/commit/terminal.
6. For all-rejected results the same owner performs rejection C1 → provenance P → C2.
7. Exact readback allows detached result delivery; the worker can then settle its result.
8. Channel close and successful executor shutdown precede the existing selected-return
   controller checkpoint settlement.
9. A later ordinal needs its own original intent and handoff after durable settlement.

Successful publication uses before → staged → terminal. **C1/P/C2 names only the
existing known-rejection sequence**; it is not a new success schema. Rejection does
not advance the population or memory head. No terminal episode or claim is changed
back to running/started to obtain publication authority.

## Explicit BRS authority

The complete online BRS owner must have its own mode/policy and scope gate. It must not
forge `_PythonAdmissionFlowContext`, rewrite BRS state as DRS, borrow a DRS dispatch
lease or accept duck-typed owners. Existing descriptor/snapshot/rejection formats and
capacity rules can be reused behind a private kernel with explicit known-owner dispatch.

Construction and every mutation validate exact controller/ledger/workspace/sidecar,
owner thread and already-held run lock, active wave, selected handoff/nonce/digest,
`mode=brs`, `max_workers=1`, frozen M0, original reservation/ordinal/request/plan,
source/policy/control/deadline, captured head and full canonical payload, original
ready/child pins, running run/episode, started claim and absent native result.

Only an adjacent write made by this owner with exact delta and full readback may
advance the captured wave head. A worker wait check, retained descriptor or latest
database row cannot refresh authority. Callback and source hooks run outside the
short observation mutex, followed by the original identity/head checks.

## Recovery and remaining work

PB-03a now extracts two private pure checkpoint helpers: the one-field lineage delta
and comparison of already-observed head/payload bytes. The original DRS facade still
owns exact owner admission, capacity/strict serialization, captured-head CAS, readback
scope and context/root-binding checks. Both live functions are explicit fingerprint
dependencies. This changes new policy fingerprints and retains old-run drift refusal;
that slice does not provide a BRS owner or migrate a persisted policy. Its 17-case focused
validation is recorded separately in `validation.md`.

PB-03b implements a narrower private primitive in
`rsi_brs_publication_lineage.py`: `_BRSLineageCheckpointOwner` supports only
`checkpoint_before` and `acknowledge_prepared` for the first original ordinal. It
requires the exact original controller, ledger, wave, selected handoff/context and
channel, original owner thread and held run lock. The real worker must still be
waiting with a running episode, started native claim and no result. The frozen
request, M0, native plan, sidecar, intent/reservation, budget, source, control and
deadline remain bound. No DRS context, lease or mode rewrite is manufactured; the
original DRS mutation facade explicitly refuses this owner.

Its distinct protocol is `lunar-rsi-brs-lineage-checkpoint-v1`. Its policy pins
`mode=brs`, `max_workers=1`, `production_admission=false` and
`online_publication=false`. PB-03b initially pinned it only at owner construction.
PB-03c now retains dedicated `producer_brs_checkpoint_policy` metadata in the
original create-run payload before the first running transition, original run
fingerprint and every controller checkpoint. Selection is limited to new exact
producer-sidecar, single-worker BRS runs; DRS, provider-free and multiworker field
selection is unchanged. The owner checks the complete durable history and current
policy, refusing missing or changed original pins without migration or backfill.
JSON-only history checks do not invoke source/configuration callbacks under the
short observation mutex. See `prewave-policy.md`. The genuine BRS fixture
retains `producer_multi_episode_publication=false`; construction is no publication
or dispatch grant.

The primitive reuses existing descriptor, snapshot, source and file-pin formats,
actual file readback, the 112 KiB checkpoint bound, and the shared 64 MiB
ready-capsule plus lineage-snapshot budget. Shared retained-byte accounting runs
before descriptor or snapshot reads. Live owner methods, shared accounting, pure
checkpoint helpers and evidence readers are explicit fingerprint dependencies;
source files are hashed as well. The writer admits only its exact phase and legal
one-field delta, never arbitrary caller checkpoint wire.

Prepared acknowledgment has two distinct increments: the existing controller/store
admission-reference CAS, then this owner's prepared-journal evidence-pin CAS. The
owner adopts only the exact adjacent verified reference head and canonical payload.
After callback checks it verifies that fixed head/payload again and rereads the
entire history, so a late same-payload no-op revision cannot become a fresh capture.
Full write/readback and post-write owner/root checks precede shared wave/state/head
advance. Failed or ambiguous write/readback retains durable evidence, stale captured
authority and a poisoned owner, without retry, repair or latest-row adoption. Source
and configuration hooks run outside the short observation mutex.

The final focused acceptance for this primitive is **40 = 37 new + 3 original** at
`309ce16`, with static/install/source verification and independent code review.
Exact evidence and preserved failures are recorded in `publication-validation.md`.
This closes no staged, terminal, rejection, publication transaction, reconcile or
serial successor path.

The separate PB-03c frozen acceptance at `399958c` passed **402 = 21 new + 381
original** cases, all static/install/source checks, and independent code review.
Its original-policy metadata grants no online transaction capability. These
different source acceptances are not summed; final integrated-source CI remains
separate.

Mailbox, nonce and owner objects are ephemeral and cannot be recovered from files.
Interrupted producer work remains an unknown started obligation. Queued requests are
not resubmitted for fresh authority. CAS/commit with lost ACK or failed readback retains
durable evidence and the stale captured head, with no automatic retry or head adoption.
Incomplete before/prepared/staged/terminal or rejection C1/P/C2 requires explicit
reconciliation. Existing DRS inspections do not authorize BRS reconciliation.

The next implementation slices remain open:

- Online composition of the private before/prepared owner and its persisted
  original BRS policy with the controller and scheduler transaction lifecycle.
- One-shot mailbox transport is implemented in the successor candidate
  (`publication-mailbox.md`); focused acceptance and its controller/pre-publication
  scheduler dispatch integration remain separate open work.
- Owner rejection provenance/C2 and exact terminal result delivery.
- Independent BRS read-only reconcile, serial ordinal transition and partial-wave recovery.

Tests must record owner thread identity for transaction, admission pin, lineage CAS,
archive commit and C1/P/C2; prove running/started while the worker waits; inject drift,
duplicate/foreign requests, failed CAS/readback, every durable interruption and shutdown
failure; and preserve the existing DRS and pin-only BRS contracts. This document does
not complete those slices or enable CLI/native BRS, real producers, sealed runtime,
remote evaluators or production admission.
