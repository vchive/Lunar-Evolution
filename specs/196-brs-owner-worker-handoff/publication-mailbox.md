# PB-02a — original selected-worker publication mailbox

Status: bounded transport implementation in progress. This does not implement PB-03,
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
