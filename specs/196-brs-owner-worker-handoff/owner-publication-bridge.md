# Selected BRS owner publication bridge — design, not implementation

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

A future exact BRS owner must have its own mode/policy and scope gate. It must not
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
it does not provide a BRS owner or migrate a persisted policy. Its 17-case focused
validation is recorded separately in `validation.md`.

Mailbox, nonce and owner objects are ephemeral and cannot be recovered from files.
Interrupted producer work remains an unknown started obligation. Queued requests are
not resubmitted for fresh authority. CAS/commit with lost ACK or failed readback retains
durable evidence and the stale captured head, with no automatic retry or head adoption.
Incomplete before/prepared/staged/terminal or rejection C1/P/C2 requires explicit
reconciliation. Existing DRS inspections do not authorize BRS reconciliation.

The next implementation slices remain open:

- Explicit BRS policy/owner and captured-head lineage CAS with provider-free fixtures.
- One-shot mailbox transport is implemented in the successor candidate
  (`publication-mailbox.md`); focused acceptance and its controller/pre-publication
  scheduler dispatch integration remain separate open work.
- Owner rejection provenance/C2 and exact terminal result delivery.
- Independent BRS read-only reconcile, serial ordinal transition and partial-wave recovery.

Tests must record owner thread identity for transaction, admission pin, lineage CAS,
archive commit and C1/P/C2; prove running/started while the worker waits; inject drift,
duplicate/foreign requests, failed CAS/readback, every durable interruption and shutdown
failure; and preserve the existing DRS and pin-only BRS contracts. This document does
not implement those slices or enable CLI/native BRS, real producers, sealed runtime,
remote evaluators or production admission.
