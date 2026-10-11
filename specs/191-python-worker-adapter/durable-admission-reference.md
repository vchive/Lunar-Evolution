# Durable admission references in the RSI flow

## Scope and interfaces

Continue the late-controller evidence SDD with an explicit provider-free obligation:
once the caller pins a late admission identity, ordinary controller recovery must
require that same retained row and revalidate its original files. The existing
`register_python_admission` and `validate_python_admission` keep their semantics and
do not change the checkpoint. Original run request/proof, planned budget/deadline,
gateway identity and native plan remain unchanged. `production_admission=false`.

`RSILearningController.pin_python_admission(run_id, episode_id, *, native_plan,
prepared_journal, expected_anchor_sha256)` returns the exact admission record after
atomically retaining its separate row and checkpoint obligation. The ledger operation
`pin_python_admission_record(record, *, reference, expected_run_record_sha256,
expected_checkpoint_sha256, expected_episode_record_sha256)` returns that record and
the resulting checkpoint digest under the existing controller lock.

This is an explicit checkpoint boundary. A pin makes an older in-memory flow state
stale; continuing with it must refuse rather than silently erase or adopt the new
obligation. Reload the durable state through ordinary resume. Automatic scheduling,
real Python runtime input production and publication callbacks are later composition;
this slice does not invent inputs or grant execution/evaluation authority.

## Reference wire and history

The optional `python_admission_refs` checkpoint map is keyed by episode ID. Each
exact reference contains `journal_id`, `attempt_id`, `record_sha256`, the original
canonical complete `native_plan` wire and original prepared/preflight
`prepared_journal` wire. The original wire permits recovery without calling the
provider, reconstructing a plan from new inputs or substituting a latest journal.
Each wire is strictly reparsed before serialization/I/O; its digest and attributed
request must agree with the retained row. IDs, shape, nonzero hashes, types, sizes,
and fractional budget/deadline values follow the existing protocols. Reject callback
collections, mutated/subclass DTOs and unknown fields without invoking callbacks.

For each verified checkpoint revision, reference keys may only be added. A previously
retained value cannot be deleted, replaced or reattributed, even by a hash-valid
append. Non-pinned and non-Python checkpoints omit the field and preserve their wire.
All checkpoint write paths enforce this monotonic obligation before insertion.
The existing local trust model does not resist rewriting every trusted historical pin.

## Atomic pin and read-only replay

Revalidate original proof, sidecar, handoff/prepared association and content anchor
with the existing late-evidence gate. Avoid recursive reference validation by a
separate private original-proof helper; expose no public bypass switch.

Reference verification is read-only and can run in a BRS worker while the parent
controller thread owns the mutation lock. Use a private evidence/CAS read helper,
not the public lock-acquiring validation API. The public API and all writes retain
their existing lock requirements. Reread durable references after file validation
so an obligation added during the read cannot be silently ignored.

Under the controller lock and one `BEGIN IMMEDIATE`, compare retained run/checkpoint/
episode heads, verify original attribution/native claim and reference history, then
insert or exactly replay the admission row and append only the new reference to the
checkpoint. No budget/accounting/status/plan/intent/execution or other field changes.
Both changes commit together; an exception between them rolls both back. An unknown
return after commit keeps both for inspection/replay, never repairs them.

A first reference requires running run/checkpoint/episode and a native claim without
a persisted terminal result, including when the row was separately registered earlier.
An existing exact reference and row replay read-only after terminal/unknown states.
A required missing or drifted row refuses before any insertion; never recreate it.
Attempt ownership, exact record/reference bytes, CAS and foreign-lock conflicts refuse.

## Controller boundaries

At ordinary resume entry, including terminal/unknown branches, validate reference
history and all pinned rows before budget reservation, callback, dispatch, settlement
or public return. Revalidate the original sidecar, pinned handoff, prepared association
and content anchor using the retained original plan/journal. Apply the same gate at
checkpoint save/no-op, direct episode/cached native recovery, callback/native-failure
reconciliation and subsequent producer progress boundaries. A prospective state that
drops a reference is rejected. These operations perform no solver/evaluator/launch or
evidence repair merely to validate a reference.

Fresh gateway returns need the same gate before an episode terminal append and before
verifier attachment/public return. A caller-supplied runner settlement hook checks the
current reference/file identity. Preserve existing deadline checks and known-terminal
settlement semantics; do not add a new post-gateway budget refusal. Retain the immutable
worker result and physical usage evidence for inspection if this gate refuses; leave
the episode running rather than publish a terminal claim. Existing standalone runners
without the optional hook keep their behavior. Durable callback dispatch also rechecks
identity immediately after its started journal write and before calling the callback;
refusal retains the started record for quarantine without invoking the callback.

SQLite CAS and separate file observations are not globally atomic against a hostile
concurrent writer. Complete runtime crash composition and sealed-runtime acceptance
remain separate P0/P1 work. No actual CPython/toolchain acquisition/build/execution,
WebAgent, real solver campaign or remote/company evaluator is authorized here.

## Validation

Use local inert fixtures for atomic first pin and exact no-write replay, original
request/proof/budget/plan preservation, fresh ordinary resume, terminal/unknown replay,
row loss/replacement, reference deletion/replacement in a correctly rehashed append,
stale save/no-op and direct recovery refusal, retained-file drift, CAS/lock conflicts,
transaction rollback and unknown-after-commit replay. Each refusal adds no budget,
dispatch, callback, settlement or repair. Preserve the existing128-case late-register
gate and older golden wires. Run focused/compatibility tests, Ruff, compileall and
diff checks; the final source needs its own full Ubuntu3.11/3.12/3.13 CI and raw audit.
