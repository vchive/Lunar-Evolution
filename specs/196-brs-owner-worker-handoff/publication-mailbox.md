# PB-02a — original selected-worker publication mailbox

Status: bounded transport implemented; final Linux focused acceptance passed.
Independent final-source and raw evidence reviews passed; final-source CI remains open. This does not implement PB-03,
wire the native scheduler/controller, grant publication authority, or enable native BRS.
It follows `owner-publication-bridge.md`; public refusal and production admission stay unchanged.

## Request, response and original pins

One owner creates one in-memory mailbox from its original strict detached
`BRSSelectedChildHandoff` and a separately retained worker thread identity. Both
threads must differ. There is no deserialize-from-disk mailbox, nonce refresh or
new dispatch permit. Transport thread identity is not external-worker authentication.

The request contains exact run/episode/handoff digest and canonical bounded JSON:

- `native_plan_sha256`, `expected_head_sha256`, `expected_state_sha256`,
  `native_execution_receipt_sha256`;
- `output`: `process_terminal_sha256`, `output_capture_sha256`,
  `envelope_bytes_sha256`, `execution_receipt_sha256`, `admission_plan_sha256`,
  and `request_coverage=brokered_requests_only`;
- `python_handoff_file_pin`: the original creator's existing detached file pin.

All digests are nonzero lowercase hex SHA256. Request head/state must equal the
head/state captured by the original owner when constructing this mailbox. By default
these are the selected handoff pins; explicit head/state must be supplied together
if preceding, precisely acknowledged owner CAS has advanced the original capture.
There is no refresh API, worker adoption or latest-row capture. Receipt/output receipt digests and file-pin run identity
must agree. Messages contain no draft objects, caller paths, strategy, control,
lineage owner, callback, prepared journal or admission anchor. The owner transaction,
not the worker request, creates the actual prepared journal/anchor.

A domain-separated request digest binds run, episode, selected handoff and exact
payload bytes. The response retains those exact request identities, its canonical
owner-evidence bytes and a separately domain-separated digest. The transport only
requires an object-shaped canonical JSON response; it does not invent or validate
native success/rejection formats. PB-03 must enforce the existing native journal,
terminal and original provenance formats and independently validate their readback.
A transport response alone is never admission/publication/result authority.

Messages have an 8 MiB transport ceiling and depth 48. Existing native, staging,
checkpoint and lineage bounds remain mandatory and are not widened by this ceiling.
Duplicate keys, noncanonical encoding, invalid scalars, callback objects and DTO
subclasses refuse. Public boundary copies exact primitive fields before comparison;
handler-visible and caller-visible DTOs do not alias retained request/response data.

## State and lock contract

`open -> queued -> inflight -> delivered` is the only delivered path. Only the
bound worker may submit, once; only the original owner may service. A second submit
refuses even after cancellation or a handler error; recursive submission from the
initial worker check also refuses before enqueue. A check failure before enqueue
has no consumed request. Owner service checks original
pins through its trusted callback before and after invoking its trusted handler.
Neither check, handler nor worker wait check runs while holding the condition lock.
No observation or workspace lock scope is supplied by this transport.

Cancellation/close/error after submission and before worker response acceptance
leads to `abandoned` (or `closed` before submission), wakes waiters and retains the
consumed request. Close after successful acceptance is idempotent and does not
revoke the delivered transport history. Close may be called by
an aborting thread; it cannot cancel or undo an already-running owner transaction.
If an inflight handler completes after the worker abandons/close occurs, no response
is delivered and the owner receives fixed `delivery_unknown`. Handler exceptions
propagate only on the owner; worker receives a fixed refusal without exception text.
The `delivered` state means a response was made available, not that the worker
accepted it or that its result/episode was settled. The original selected service
must still observe the worker return, channel close and successful executor shutdown.
Close before worker acceptance discards the available response and marks abandonment;
close after acceptance preserves the delivered history. Acceptance is recorded under
the condition only after the original worker check and strict response reconstruction.
No automatic retry, repair, head adoption, budget refresh, redispatch or sibling
transition follows from any terminal state. Durable unknown obligations belong to
the future owner integration; this ephemeral mailbox never writes durable state.

## Next integration dependency and validation

The existing read-only `recover_native_trusted_producer` rechecks the original
receipt/output capture and reconstructs drafts without execution/evaluation. The
future BRS owner must use its own retained context and compare the original request
pins, then read the handoff against the creator's file pin. Existing scheduler gates
still require a real DRS owner; a separate BRS producer-only/post-output seam and
explicit BRS owner composition remain necessary. Do not bypass those gates.

Focused provider-free tests cover bound threads, canonical identity/digests, strict
DTO detachment, one-shot races, reentrant service, cancellation before/during owner
work, close and lost delivery, fixed worker errors and check/handler lock freedom.
No real producer, process, model, evaluator, controller CAS or transaction is run.
Ruff, compileall, diff-check, installed-source evidence and independent review are
required. Transport acceptance does not close owner transaction, rejection C1/P/C2,
read-only BRS reconcile, ordinal transition, final-source CI or runtime acceptance.

## Final integrated local acceptance

Frozen source `b468f55804699fbfe94b154770194f7528695df1`, tree
`859a2acbc175248736e9a80f9c5d26691ecd13fa`, passed **872 exact distinct cases**
across 18 modules and eight disjoint groups: 124/91/112/122/99/111/117/96.
There are zero failures/errors/skips. All 13 collection/install/test/static exits
are zero, tracked sources are identical before/after, and editable installation
points to the dedicated Linux worktree/venv. Ruff covers `src tests tools`;
compileall and `git diff --check` pass. The 77 mailbox and 27 parser semantic
cases have separate exact CI XML gates.

Inventory SHA256:
`b738da3c674aa7651840aec6b7a3e7fc0baf2a325e7e36c51ff05e5c359c47ea`.
Mailbox product SHA256:
`5c76bbfe885f36b5a8a8ba08119cf4f9f488f3c5c92d8b66ab7ae74aa41cc505`.
Mailbox test SHA256:
`60f1874d354e21ebfbab5129b1b0e5e7805c7ff9bee98e14233e6c1e40ccdd00`.
Tree parser product SHA256:
`1b70d8ad9b37267a9203ef3d81b2becc25c021061e7c4498987bf3ee02355d23`.

Raw XML, exact inventories, source/install maps, logs and exits remain in ignored
`.lunar-evolution/reports/brs-mailbox-parser-20261015/final-872/` and remotely in
`/home/qinzhiqing/vchive/lunar-mailbox-parser-final-4949k5nr/`.
The development 44-case run's close-state fixture mismatch and subsequent 47/72-case
runs' actual close-before-accept/repeated-close failures remain retained separately;
they are not rewritten as passing. Final tests cover the repaired transitions and
strict huge-integer timeout refusal. Only documentation is updated after this
frozen product/test source; no cross-source counters are added to the 872 result.

No mailbox handler in these tests performs a native transaction or real evaluation.
This acceptance does not complete PB-03, public native BRS, runtime admission or
final-source CI/merge.

Independent stdlib-only review passed 6,219 assertions: all 2,029 tracked files
match immutable commit blobs by SHA/mode/size; eight exact XML inventories and
collection/install/test/static exits agree. The reviewer independently downloaded
the raw records. Review JSON is retained at ignored
`.lunar-evolution/reports/pb03-kernel-and-final872-independent-20261015/review.json`,
SHA256 `866333e2b6c984535d539f7988138ceb653d0d47c803379a56757c6c6d836660`.
Separate independent final source/spec/workflow review also passed. The documentation
successor leaves all product and test bytes equal to the tested commit.
