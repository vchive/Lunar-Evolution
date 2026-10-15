# PB-02c — preparation evidence to mailbox request

Status: private evidence projector implemented. This follows PB-02b and PB-02a and does not
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

## Frozen local acceptance

Product/test source `1ca432563f1bdd4122076b3f03a837f7579cbeb7`, tree
`8039d534486cb0967fc44e61e6e0d0b8185863e9`, passes **179 distinct cases on each
of macOS and Linux**:
35 new projection cases, 67 original producer preparation cases and 77 original
mailbox cases. Zero failures/errors/skips; exact XML/collection identities match.
Ruff over `src tests tools`, compileall and diff-check pass. Own-editable Python
3.11.15 has `PYTHONPATH` unset; all 2,045 tracked files remain unchanged.
Inventory SHA256:
`8ceeff71199ce89f1c6d0bc8a95e9fef70d6f01177995e2cdb383b221500f5e5`.

Raw results are retained at ignored
`/Users/liminghan/Documents/lunar_agent/.lunar-evolution/reports/brs-preparation-mailbox-inputs-20261016/final-1ca4325/`.
Independent read-only code review passed after correcting callback shadowing and
malformed primitive error normalization; its separate report is in `code-review/`.
The original 34-case development and predecessor 178-case source results remain
separate; they are not summed with this final 179. Final-source
CI and main integration remain separate gates. These fixtures forbid process and
transaction execution and do not establish native owner recovery or runtime admission.

The independent Linux Python 3.12.3 own-editable checkout passed the same 179
cases once, zero failures/errors/skips, JUnit 4.630 seconds; all 13 install,
collection, test and static exits are zero. All 2,045 actual immutable Git blobs
match the before/after source maps and original clean identity. Its raw XML,
inventories and independent review are retained in the sibling `linux-1ca4325/`.
Transport archive SHA256:
`3fd19b426a2641a294aabff3b1a280869f2b553fff9c7642a00adce4f6b78f4f`;
XML SHA256:
`fbe23e1659a33f83ce86ac9d84c0a4ced591828c4efb660b86b5a522094c7539`.
This verifies the same inventory on two platforms, not 358 different cases.
Later documentation/workflow updates keep product/test/tool bytes unchanged;
the new 35-case focused gate is one of 57 uniquely annotated XML outputs.

The later unified `01c3bd1` source also passes this exact disjoint 179-case group
on macOS/Python3.11.15 and Linux/Python3.12.3. Its companion checkpoint group has
143 distinct cases; profiles and independent raw verification are recorded in
[`publication-validation.md`](publication-validation.md#pb-02cpb-03d-unified-final-focused-acceptance--2026-10-16).
The original `1ca4325` run retains its own source label and is not added again.
