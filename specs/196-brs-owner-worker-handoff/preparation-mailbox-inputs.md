# PB-02c — preparation evidence to mailbox request

Status: implementation in progress. This follows PB-02b and PB-02a and does not
enable the online owner transaction or public native BRS.

The private `_request_from_native_preparation` consumes the exact producer-only
preparation DTO, original selected handoff, explicit native execution plan, and
explicit original owner-captured checkpoint/state digests. It projects those
already-retained inputs into the existing bounded canonical mailbox request.
It never discovers current pins or derives a native plan from a selected handoff.

Before serialization or comparison, validate exact DTO types and primitive shapes
of all consumed receipt, request, native/admission plan, envelope, handoff and
file-pin fields. Reparse their existing formats, including self-digests and the
sidecar's original raw/file-pin association. Refuse callback collections and DTO
subclasses before invoking their methods. Unused attempt, draft and bundle
objects are neither serialized nor invoked; the owner must reconstruct original
output from durable evidence rather than trust those worker objects.

Require prepared/no-publication run state, completed successful receipt, brokered
eligible output, original receipt/output/native capture agreement, selected
request/M0/run/episode, and common native launch/journal/parent/child/intent/
attestation/contract/evaluator/environment identities. Preserve the distinction
between Python runtime terminal evidence and the native process terminal capture.
Use the original file pin, never a newly observed filename pin.

The helper performs no file or ledger I/O, callback, process, recovery, evaluation,
publication, admission ACK, lineage mutation, memory promotion or budget change.
Its request is transport evidence only. Owner-side read-only recovery and fresh
running/started/authority checks remain mandatory before any later transaction.
Caller-supplied head/state digests are compared with the retained capture by the
existing mailbox; this projector does not attest ownership of those digests.

Focused acceptance must exercise actual PB-02b preparation through this projection
and the original one-shot owner/worker mailbox, plus drift, malformed/subclass/
callback inputs, original pin mismatch, canonical detachment and zero side effects.
Existing preparation/mailbox tests, Ruff, compileall and diff-check remain gates.
`online_publication=false` and `production_admission=false` remain unchanged.
