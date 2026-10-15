# Feature 196 — BRS owner publication boundary

**Status: PB-01 refusal slice implemented in an isolated branch; validation pending.
Owner publication, online prepared bridge and ordinal transitions remain design-only.**

Reference source is `868bccccc9ede2cd035d28b16cfb316fef049c0a`. The private selected
service and checkpoint settlement at that source do not authorize owner publication.
`production_admission=false` and the public native BRS refusal remain unchanged.

## Current boundary and first implementation slice

The named `run_rsi_python_bundle_publication_for_active_brs_worker` symbol remains
importable with its original signature, but always raises the fixed code
`rsi_python_publication_brs_worker_publication_forbidden` before inspecting inputs,
calling callbacks, submitting ready, opening a transaction or touching evidence.

The generic `run_rsi_python_bundle_publication` and DRS
`run_rsi_python_bundle_publication_for_active_flow` mutation facades also refuse an
already-established BRS invocation before plan parsing, including the entry/source-hook,
pre-active dispatch and nested active/dispatch-suppression windows. A negative
thread-local publication-forbidden marker is set at invocation entry and restored
in finally; it grants no execution or publication authority. They do not
discover a BRS run from disk or invent new ownership. Direct already-pinned generic
calls and original DRS ownership retain their existing semantics. Read-only resume
is unchanged. Prepared admission through the existing ready/ACK channel stays
available independently; an ACK is never publication authority.

This slice does not create an owner publication facade. The combined scheduler slice
also refuses its direct transaction route on a BRS worker before input or context
callbacks. A negative invocation marker covers entry/source hooks and nested scopes
that suppress active/dispatch capabilities. A Python helper gate is not a sandbox
against arbitrary code invoking unrelated standalone native APIs.

## Two existing lineage sequences must remain distinct

Successful publication already uses the existing Feature191 sequence:

1. `before`: the original owner retains before snapshots and descriptor by CAS.
2. Prepared admission acknowledgment binds the exact native plan/journal/reference.
3. `staged`: the owner retains the exact manifest and after snapshots by CAS before
   the existing native commit begins.
4. `terminal`: after native commit and complete read-back, the owner retains the
   published terminal and advances the published lineage head by CAS.

Known rejection v2 uses a different existing sequence:

1. **C1**: after the actual native `all_rejected` terminal, the original owner
   retains the rejected descriptor and native evidence by CAS; provenance is null.
2. **P**: the provider create-only writes the original mode-0400 rejection
   provenance file and receives its publishing-FD pin.
3. **C2**: that same owner verifies P and fills only the independently retained
   provenance association by CAS. The gateway may then map/publish the original
   failed native result.

C1/P/C2 are rejection-provenance terms. P is not the successful candidate
publication transaction. A rejected result never publishes a candidate, advances
the published head or promotes memory. Do not add a new success/rejection wire or
rename existing state phases to force both sequences into a new model.

## Completed return is not an online publication grant

The current `_python_admission_run_selected_brs_intent` issues `selected_return`
only after the worker has persisted a completed native result and episode, the
channel is closed and executor shutdown succeeds. The private settlement consumes
that receipt to cache the exact completed execution by checkpoint CAS/read-back.

Existing `RSIPublicationLineage` instead requires a running episode, original
started claim, DRS flow context, exact fresh child dispatch lease and owner thread.
A completed BRS return cannot satisfy those requirements. Do not manufacture a DRS
scope, change `state.mode`, resurrect a running episode, mint a dispatch lease or
adopt current files to bridge the difference. Do not call the native transaction
after a completed result if that would repeat evaluation or publication.

## Next design dependency: prepared-stage owner online bridge

PB-02/PB-03 still require an implemented online bridge; its design is in
`owner-publication-bridge.md`. The worker submits receipt/output/handoff/admission plan
and original pins before entering the transaction, while the selected invocation
is still live, then waits without owning the controller/observation/publication lock.
The owner transaction creates the actual prepared journal/anchor and its observer
performs the exact prepared pin/CAS. A worker-written prepared journal is not a
prerequisite publication request or publication authority.
The owner must service that request on its original thread, preserving the run
lease and revalidating the complete selected handoff, M0, original reservation,
request, source/configuration, native plan, prepared journal, anchor and claim.

The bridge must use a BRS-specific owner composition rather than relaxing DRS
`RSIPublicationLineage` gates. Before code, freeze the exact request/response,
retained bytes, lifetime, callback/lock order, successful `before/staged/terminal`
and rejected C1/P/C2 observation points. Existing schema/bounds stay unchanged; any
necessary durable field addition needs an explicit reviewed extension.

## Head, CAS and unknown rules for that future bridge

Every owner mutation uses its captured exact checkpoint head/payload. After an
acknowledged exact CAS delta and complete read-back, only that original owner may
advance its capture. A changed checkpoint, run, state object, source, sidecar,
workspace, inode, budget, deadline, request or handoff refuses. Reading a latest
checkpoint or file cannot supply a missing expected pin.

The native publication lock checks the original before prefix and staged evidence
before the first final move. Keep controller owner -> publication lock order;
arbitrary source/configuration hooks and waits stay outside the short observation
mutex. The existing durable unknown marker/commit critical region retains its
meaning and cannot be replaced by a generic new timeout or rollback.

A CAS failure or ambiguous post-write/read-back keeps the owner's captured head
stale and preserves durable obligations. Missing original before/staged/terminal or
C1/P/C2 evidence, partial commit, cancellation/timeout/owner exit or channel close
grants no retry, repair, orphan adoption, latest-head refresh, budget extension,
memory promotion or sibling dispatch. Recovery remains original-pin read-only
inspection until a separate explicit reconcile contract is accepted.

## Serial successor and scope

`max_workers=1` stays fixed. A later ordinal requires the preceding exact native
terminal/result and complete owner lineage acknowledgment. It gets a fresh handoff
against the verified head while retaining the original wave reservation and M0.
No prior nonce, journal, claim, receipt or request may be copied to a sibling.

The current slice uses only local provider-free/inert fixtures. It enables no
public native BRS, multi-child publication, external worker, distributed ownership,
remote evaluator, scheduler service, production CLI, sealed runtime, real model or
OpenEvolve/Shinka campaign. Final-source CI and independent raw/source/tree review
remain necessary even for the bounded refusal slice.
