# Reserved-wave serial implementation plan

Status: implementation in progress. The bounded A/B readers, native
provider/completion, private serial driver and finalization readers now exist in
the working tree with focused checks; no integrated behavior or final-source
acceptance is claimed. The latest natural two-child fixture run did not complete
owner admission and mailbox handoff; the underlying cause remains under
investigation. The earlier recorded failure
`rsi_brs_reserved_prefix_material_path_invalid` at
`read_reserved_brs_prefix -> validate_brs_reserved_prefix` has been repaired by
an exact rejection-evidence path/pin mapping; the latest integrated failure is
`rsi_brs_reserved_serial_settled_transport_missing`. Do not weaken the validator,
owner or lifecycle gates while repairing the settled-transport contract. The
governing behavior is
[reserved-wave-serial.md](reserved-wave-serial.md), requirements RW-01 through
RW-12. Tasks and validation inventory are in
[reserved-wave-serial-tasks.md](reserved-wave-serial-tasks.md).

## Baseline and existing incompatibilities

Planning baseline is commit `ccc754788fb4806b4093c397d9e8bc92792364d9`, tree
`daed8cd4da7d7f3348d514fd03d579fe0720706e`. Develop in the separate
`codex/brs-reserved-wave-serial` worktree; do not change the frozen
rejected-lifecycle source or the primary checkout's user-owned RSI gap report.
The predecessor's final acceptance and main integration remain separate gates.

The existing code has these concrete integration gaps:

- `_drive_brs` reserves all original intents before submitting pending futures,
  but submits all futures up front. A one-worker pool alone does not implement
  verified native serial dispatch.
- `advance_brs_ordinal` charges already reserved counters again, and detached
  dispatch preclaims before its callback. Ordinary gateway `run` creates its own
  claim and rejects an existing started claim. Neither detached operation is
  reused by the live reserved driver.
- `_PythonAdmissionBRSWave` and selected binding treat the pending domain and
  channel as one lifetime. A rejected channel retains its request/ACK/guard;
  previous success closes its channel. Sibling custody must be constructed fresh.
- The original publication owner, before/success, C1/P/C2, terminal messages and
  composer contain ordinal-zero/one-batch/current-live-source assumptions. Serial
  operation needs an explicit prefix proof and original historical snapshots;
  deleting an equality check cannot supply that proof.
- Original live root settlement currently composes rejection only. Genuine
  published success must use the same full terminal/root/retirement order, rather
  than the older selected-return grant after worker completion.

## Private module contracts

Names below are the proposed implementation seam. They may be adjusted together
at review, but the input authority and side-effect boundaries are fixed. No public
export, production flag, new descriptor protocol or SQL table is introduced.

### A. Reserved projection and untouched selection

New private module `src/lunar_evolution/rsi_brs_reserved_wave.py`:

- `BRSReservedWaveProjection`: immutable bounded descriptive value containing
  original wave/domain, plan/request/M0 digests, complete reservation basis,
  original budget/deadline pins, completed-prefix length, next ordinal and
  latest published predecessor. Attempts/counters retain the original N-intent
  reservation and are separate from completion count.
- `project_reserved_brs_wave(...)`: consumes exact bounded original/durable
  observations and validated prefix facts; checks full original domain and
  contiguous settlement, capacity and untouched next-intent eligibility. Returns
  a projection or fixed-code refusal, never writes or invokes a hook.
- `select_reserved_brs_child(projection)`: returns the original untouched
  selection/request identity, or wave-complete. It contains no live authority.

The controller supplies original-history and current-head observations under its
existing lease. Pure helpers do not accept a ledger, owner object, callback or
arbitrary source reader. A request for an already settled ordinal is not a live
selection, even if the gateway could replay its terminal result. Recompute the
projection after every exact settlement; never mutate the old projection's
consumed counters to imitate the detached successor.

A-line development now provides these exact signatures:

```python
project_reserved_brs_wave(
    original: dict[str, object], state: dict[str, object], *,
    attempt_traces: dict[str, dict[str, object]],
    settled_prefix: tuple[tuple[str, str, str], ...],
    retained_materials: tuple[tuple[str, int], ...], candidate_count: int,
) -> BRSReservedWaveProjection
select_reserved_brs_child(
    projection: BRSReservedWaveProjection,
) -> BRSReservedChildSelection | None
```

`original` is the independently observed original controller checkpoint after full
reservation and before dispatch; `state` has the existing controller shape. The
pure layer compares original plan/pins/M0/intents/budget bytes and execution
bodies, but cannot prove that the supplied original record or prefix has custody.
It requires exactly N original practice/solver/evaluator/verifier reservations;
additional parent accounting refuses pending explicit integration review.

`attempt_traces` covers every original episode and has exactly `episode`, `claim`,
`result`, `material_sha256s`, `reference_sha256`, `obligation_sha256`. The first
three are actual observed wire records or None; the last three retain material
digest inventory and independently observed reference/obligation digests. No
Boolean all-clear substitutes for a domain scan. Prefix triples contain original
episode, known outcome and canonical execution digest; actual execution bodies,
original identities and observed claim/result/reference are compared again.
Material entries contain distinct original pin identities and observed sizes,
with a bounded 1,024-entry inventory; equal digests do not remove file charges.
The controller/prefix observers still own complete source/file inventory proof.

The DTO field `original_state_sha256` is only the original canonical payload
digest; it is never a ledger checkpoint head. The controller/B observer must carry
the independently observed original checkpoint head separately.

The DTO retains immutable original episode/request/budget bytes, reservation and
completion counts separately, original deadline and both original domain digests
and derived latest-published progress. It never checks a newly computed `now` or
grants deadline permission. Eighty focused development cases and scoped static
checks pass; prep handover, live driver and full behavior acceptance remain open.

### B. Append-prefix and historical material proof

New private module `src/lunar_evolution/rsi_brs_lineage_prefix.py`:

- `BRSLineagePrefix`: immutable bounded proof facts describing original ordered
  batches, outcomes, pinned before/poststate, original verified root associations,
  current tail and latest published predecessor. This is descriptive evidence,
  not a reconstructed owner or permission to publish.
- `validate_brs_reserved_prefix(...)`: validates original association and exact
  retained descriptor/material pins, all native terminal/result/root associations,
  contiguous ordinals, both predecessor axes and per-domain/aggregate limits.
  Format parsing reuses existing lineage v1/v2 strict readers; a caller cannot
  select a different historical prefix to manufacture the result.
- `validate_brs_reserved_append(prefix, ...)`: proves adjacent append with an
  unchanged old prefix, correct nonzero before-v2 links and before snapshot
  content equal to predecessor poststate. Current live source observation belongs
  to the active-tail gate, not to historical pin substitution.

Separate pure bounded comparison from filesystem/ledger observation. Observers
use existing strict original-pin readers and run outside the short observation
mutex where required. Preserve exact descriptor bytes, inode/source pins and
original checkpoint history; a later suffix cannot rewrite them. An original
published after snapshot supplies historical poststate. A rejected child's before
snapshot supplies its unchanged poststate. Count all retained snapshots/material,
including equal-digest files, before accepting an append.

Add an explicit private serial-owner construction path in
`rsi_brs_publication_lineage.py` that requires the controller-held lease, fresh
selected custody, actual running claim and independently validated prefix. Keep
the legacy constructor's ordinal-zero restrictions. Before/prepared/success and
rejection C1/P/C2 consumers receive the selected actual ordinal/prefix through
that path; they do not discover a convenient prefix from the latest root. Update
`rsi_brs_rejection_c1.py`, original rejection/provenance/ready readers and terminal
messages/evidence only where their exact single-batch assumptions require it.
Do not synthesize a new one-batch descriptor or share old owner objects.

### C. Original-owner serial composition

New private module `src/lunar_evolution/rsi_brs_serial_driver.py` contains the
bounded orchestration. `RSILearningController` delegates through a private entry,
proposed `_drive_reserved_brs_native_serial(state)`. Public `_drive_brs` does not
automatically select it and retains its refusal/admission behavior. Use an explicit
private inert integration fixture entry until later P1 admission is accepted.

The private driver owns one frozen wave scope and run lease. Per-child custody is
separate from the immutable full-wave envelope: original domain and reservation
remain the same, while selected pending domain, captured head, context, nonce,
channel, mailbox, endpoint, Future/executor and owner are fresh. This may add a
private child-scope helper to the controller; it must not mutate an old
`wave.episode_ids` or clear old channel fields to satisfy existing validators.

The sequence is fixed:

1. Observe original history/policy and full reservation. Scan the whole original
   domain for attempt traces, obligations and existing native state. Validate
   prefix/projection before allocating any live child custody.
2. Revalidate current tail/live archive/state, run control, deadlines and exact
   untouched request. Create fresh custody and check the captured root adjacent
   to worker start under the same exclusive lease.
3. Start exactly one selected natural runner. Its ordinary gateway `run` is the
   only claim creator. No detached preclaim and no transferred
   `_fresh_child_dispatch` closure. Do not write an owner checkpoint in the gap
   before the worker's original preparation request.
4. Bind the actual worker plan/running episode/started claim to its original
   mailbox. Construct that child's original owner using the selected prefix.
   Register the existing recovery fence before the shared native transaction.
5. Compose genuine published or all-rejected preparation, ready/ACK, final
   mailbox delivery, one callback and natural terminal native persistence using
   the existing separate outcome protocols. Validate the exact original session
   at every lifecycle seam. Extend published settlement to the genuine success
   path rather than invoking the old post-completed selected-return seam.
6. Observe exact terminal and cleanup evidence, close before join, and call the
   asserted already-held reconciliation implementation. Verify the sole root
   execution/fence delta by full readback, then retire the child owner/handoff.
   Keep old custody and material as immutable retained evidence.
7. Reobserve the newly verified head, append proof and reservation. Only after
   retirement select the next untouched ordinal. Complete waves use existing
   plan-ordered `_commit_flow` and finalization, preserving M0 and rejection rules.

Waits and hooks do not run under the short observation mutex or workspace mutation
lock. CAS/readback failures retain old captures. The single held lease is not made
reentrant and is not dropped while a live child or cleanup wait remains.

#### C prerequisites demonstrated by the existing natural gateway

The accepted rejected-lifecycle fixture substitutes its operation and manually
creates the claim/result. It exercises the original runner, storage, mailbox and
transaction, but is not acceptance of ordinary `PythonProducerRSISolverGateway.run`.
That gateway's base `run` is still the sole natural claim creator; its exact
`NativeRSISchedulerProvider` immediately refuses BRS publication. Three seams must
therefore be integrated before reserved serial behavior can be accepted:

1. Add private `rsi_brs_preparation_exchange.py` and its dedicated tests. The
   selected ordinary worker offers its original preparation, request, plan and
   already-started claim; the original owner takes that offer once and hands back
   its exact original terminal endpoint once. Bind the actual single-worker
   executor, running Future and worker thread. Preserve original DTO identity and
   bounded consumed comparison bytes. One Condition transports the offer and
   endpoint; existing budget/cancellation `check` calls run outside it. Duplicate,
   replacement, expiry, wrong-thread and interrupted waits poison the exchange
   and wake both sides. This transport creates no claim/result/checkpoint and
   accepts no publication handler, owner capability, retry or refresh callback.
2. Integrate the existing lower `_prepare_native_trusted_python_producer` split
   into the natural provider, then add separate private published and rejected
   completion readers. Success must reread genuine retained receipts/provenance.
   Rejection must preserve the mapper's second independent live rejection reread
   without transferring the DRS `RSIPublicationLineage` owner to a BRS worker.
   Keep the original separate success/rejection wire and mapper persistence; a
   caller-supplied receipt or fabricated shared outcome is not a substitute.
3. Resolve a fresh private per-child gateway/context from original retained
   inputs for every selected ordinal. The existing gateway is single-episode and
   its resolver explicitly permits DRS only; reusing/mutating the root gateway
   cannot bind a BRS sibling. Keep the DRS gate unchanged and require frozen M0,
   full reservation, original prefix and current live scope before each natural
   worker start. Parent-owned controller/provider/terminal integration and the
   multi-child natural acceptance cases complete this same behavior PR.

The projection, lineage-prefix and preparation-transport helpers alone do not
constitute a completed serial driver or a newly opened public native BRS mode.

## Recovery and composer integration

Generalize private terminal/evidence observations to select the original actual
ordinal and retained prefix, without weakening the existing exact single-child
entry. A settled historical result is verified against its own original terminal,
root checkpoint and immutable snapshots; compare live archive/state only at the
current tail/active gate. Repeated validation after a later published child must
accept unchanged historical evidence, but changed old pins must still refuse.

Fresh recovery takes one run lease and uses the same pure prefix/projection
contracts. The first missing root execution is not automatically untouched:
inspect original episode/claim/result, material/reference and fence records for
every original intent, including the claim-before-mailbox window. Complete
independent terminal evidence may enter explicit locked reconciliation for one
exact root delta. Any partial/unknown evidence stops the suffix. Never retry an
old transaction, callback, native claim or owner construction during recovery.

There is no durable cursor or retired flag. A crash after exact root commit and
before ephemeral retirement is resolved only from a new exclusive lease plus
existing terminal/cleanup evidence and exact root readback. A complete prefix is
read-only replay; only an original intent with no durable attempt trace can gain
new custody. Original expiry and parent budget still apply.

## Source policy and bounded representation

The completed dependency graph must be pinned in the original persisted BRS
checkpoint policy, run fingerprint and checkpoint history before reservation or
dispatch. Include new private entry/projection/prefix/owner/terminal observers,
their executed canonical module aliases and direct imported helpers. Recompute
the graph outside the short mutex before hashing the bounded canonical policy;
do not cache a later baseline or duplicate the graph into every record. Existing
runs without these original pins refuse this path, with no migration/adoption.
Check actual serialized policy/root/projection size against existing limits before
launch; do not widen the 128 KiB record or other ceilings.

## Parallel ownership after design review

| Owner | Exclusive edit scope | Handoff |
| --- | --- | --- |
| A: reserved wave | New reserved-wave module and its focused tests | Pure projection/selection API, exact reservation/deadline vectors, no shared controller edits. |
| B: prefix proof | New prefix module, lineage owner/rejection prefix consumers and focused tests | Pure proof interface and immutable historical-source model agreed with C before changes. |
| C: composition | New serial driver, controller private scope/entry/settlement, gateway or store only if a demonstrated gap requires it, natural integrated tests | One live child lifecycle, fresh resume and root/retirement fault injection; sole shared controller owner. |
| Integration reviewer | Terminal message/composer/recovery compatibility and original policy pins | Coordinate file ownership with B/C before editing; independent final review after integration. |

Root assigns available slots and serializes overlaps before coding. Implementers
can share fixtures through an agreed owner; do not concurrently edit the large
controller, lineage owner, terminal composer or policy list. One combined behavior
PR receives the acceptance evidence. No standalone guard PR represents delivery
of serial continuation.

## Validation and delivery

Freeze fixture hooks before original source/policy capture; the production path
must not gain a caller handler just to make tests pass. Collect all four natural
two-child outcome sequences, one three-child mixed predecessor case, N-sized
reservation/max-eight cases, population-changing historical proof, partial-wave
fresh resume and every lifecycle interruption. Capacity/drift/foreign/stale cases
must prove zero next-child effects and unchanged prior evidence, not just match
an exception string. Preserve existing ordinal-zero/detached/DRS/public gates.

Run focused pytest and the required Ruff/compileall/diff checks after coherent
edits, retaining first failures. After integrated review freeze one source tree;
run matching collected cases on macOS and Linux (5090gpu CPU fixtures permitted),
verify installed/imported origin and tracked bytes before/after, retain raw XML
and all driver/leaf exits and obtain independent evidence review. Full required
33-job GitHub CI is a separate required gate. Root owns commit, push, PR, final
acceptance and main integration. Foundation checkpoint commits may preserve
reviewed work, but do not represent delivery of the complete serial behavior.
