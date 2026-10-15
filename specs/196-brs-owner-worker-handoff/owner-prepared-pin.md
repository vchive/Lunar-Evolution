# Feature 196 — original owner prepared-reference pin

This slice continues PB-03 with a private controller entry,
`_pin_python_admission_for_original_brs_owner(owner, expected_anchor_sha256=...)`.
It replaces the test-only detour through worker admission ready/ACK when an
original BRS publication owner already holds genuine prepared evidence. It does
not yet compose the online publication mailbox, transaction or worker result.

## Authority and fixed inputs

The caller supplies the exact registered `_BRSLineageCheckpointOwner` on its
original owner thread, with the original run lease still held. The owner must
already have durably acknowledged its first `before` descriptor. Its original
request, M0, native plan, prepared journal, selected handoff/context, policy,
budget and captured controller head are the only inputs. A clone, replacement
registry entry, later head, settled claim or completed episode grants no entry.
The explicit anchor digest must verify against the original native evidence.

Before the write, the existing complete owner gate validates source and execution
control pins, original proof, policy/history, naturally started claim and running
episode. The shared `_python_admission_pin_exact` kernel performs the unchanged
atomic admission-record/reference CAS against that captured head.

After the durable write, the old wave/owner capture intentionally remains in
memory while source/policy/execution-control fingerprints, original producer and
staging evidence, native strategy and owner identity are rechecked. The existing
selected service gate cannot be reused at this point because it requires the
durable checkpoint to equal the old wave head. This entry recomputes the same
fixed source/policy/control projection without granting a moving-head capture.
All configuration/source hooks finish outside the short observation mutex.

The entry retains the actual native cancellation callable and monotonic control
without creating a replacement. Its timing values, clock, stage observer, lock
and cancellation callback identities stay fixed, matching the existing native
prepublication control pin. Only the exact control class and its eight original
instance fields are accepted; subclasses and method shadows are refused before
invocation. The original class `check` implementation handles the same control.
Cancellation must return an exact boolean. The live
control/cancellation check also runs after each pre-CAS source gate, including
the kernel's last `active` check, and again after post-CAS hooks. A cancellation
or elapsed deadline at the final source hook therefore prevents the reference
write instead of merely refusing its later acknowledgment.

The original admission channel must remain open with its original owner/run and
episode set, selected episode/handoff digest and already bound nonce. No selected
completion, ready request, ACK, pending queue or service may exist. These checks
run under the original channel condition at entry, after the final pre-CAS hooks
and while the shared wave advances. This preserves the first selection; it never
consumes a second nonce or rebinds a completed/closed channel.
The combined source must include the companion persisted-policy binding for the
admission channel and control source/method/helper closure; this three-file slice
does not alter or migrate the original policy by itself.

The final durable observation must show exactly adjacent old and new history
entries and the exact returned head/payload. A later same-payload revision is a
conflict. Only then does the shared wave advance its reference map and captured
head; the owner still retains its original `before` capture.

## Evidence boundaries and separate acknowledgment

The prepared journal's immutable canonical content and original handoff file pin
are checked by the existing native kernel. The `before` schema contains no
original prepared-journal inode pin. This entry therefore captures a journal file
pin at entry and checks it again after all post-write source/configuration hooks;
it refuses replacement during the pin operation. It does not claim to recover an
original inode from an absent historical pin.

The caller subsequently invokes the existing
`owner.acknowledge_prepared(journal, record_sha256)`. That operation independently
verifies the exact adjacent reference and performs a second CAS adding the
prepared evidence pin. The new entry neither performs that evidence CAS nor
manufactures a worker ready request, ACK, service scope or DRS scope.

Any failure after accepting the genuine owner poisons it. A durable pin or
competing checkpoint remains available for explicit future inspection; neither
the old owner nor the shared wave adopts a latest head, retries, repairs evidence,
refreshes budget or starts a successor.

## Validation scope

`tests/test_rsi_python_brs_owner_prepared_pin.py` uses the existing genuine
original-owner fixture: real SQLite CAS, original selected worker/handoff/run
lease and a naturally running episode/started claim over inert local evidence.
It verifies the distinct reference/evidence revisions, unchanged M0/budget and
zero ready/ACK/channel or external execution. Negative cases cover authority,
evidence, competing CAS, missing/wrong readback, late no-op revision, same-byte
inode replacement, post-write source/control/lease drift and reentrant hooks.
Real native-context tests additionally cover control replacement, extended
deadline, replaced clock/stage/lock/cancellation callbacks, cancellation,
monotonic timeout and non-boolean cancellation results. The final pre-CAS source
hook cancellation/timeout cases require zero pin calls and unchanged durable
head.
Channel refusal covers closure before the pin (zero CAS), closure after the pin
(durable evidence and stale poisoned capture), changed owner/run/episode set,
selection/digest/nonce/completion and condition replacement during the operation.

Development results are retained separately under
`.lunar-evolution/reports/brs-owner-prepared-pin/`. They are macOS development
qualification of this slice, not combined frozen-source Linux acceptance or
final CI. Public native BRS, online owner publication/rejection, unknown reconcile,
serial successor and policy/memory composition remain open. No schema, cap,
budget or public production-admission flag changes.
