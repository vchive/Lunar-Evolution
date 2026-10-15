# PB-04a — original-owner retained-context reader

Status: private read-only primitive. Public native BRS, online publication and
production admission remain disabled.

`_BRSRetainedNativePreparationReader(owner, original_preparation=...)` requires the
exact already registered `_BRSLineageCheckpointOwner`, its original owner thread,
held run scope, genuine running episode and started claim. Construction and both
sides of recovery invoke its real owner/source/control/head gates. Only the
unchanged `new` or `before` phase is accepted; this reader cannot refresh a head,
advance a phase, reconstruct an owner or acquire a new reservation.

Construction freezes consumed native context, native plan, selected handoff,
receipt/output comparison evidence and Python creator handoff file pin. The
caller preparation is comparison evidence only; it confers no controller or
publication authority. Worker attempts, drafts and bundles are ignored entirely.
The canonical worker mailbox request must exactly match this retained projection
before native or handoff reads begin. The original selected head/state identify
the transport request; this old selected capture is deliberately distinct from
the reader's separately frozen current owner checkpoint head. Current owner
authority is independently checked, never substituted into the mailbox request.

The exact original admission channel must remain open and selected. Original
native execution-control/cancellation objects and their deadline/callback pins
remain fixed. Current cancellation and deadline checks run before and after the
durable read, outside observation/channel locks; callbacks are followed by full
original owner/head/context checks. No timeout, callback list or budget is renewed.

One recovery attempt invokes the existing strict native producer recovery with
broker evidence required, rereads the Python handoff twice using its original
creator pin, and compares the recovered receipt and reconstructed mailbox
projection. Returned receipt, envelope, bundles and candidate drafts are detached
from both the caller and native reader objects. Drafts come only from native
durable output recovery. `publication_eligible=False` remains unchanged.

The reader does not create filesystem pins. The native receipt, terminal and
capture formats do not carry original creator inode pins for all their own
sidecar files; their existing canonical/digest/stable-read guarantees are reused,
not described as original-inode proof. Envelope/material identities and broker
journal identity retain their existing capture checks. The separate Python
handoff creator pin enforces its original inode, metadata, parent and bytes.

The original BRS policy explicitly pins this module, projector, native recovery,
output/receipt/capture/handoff readers and their source dependencies. Existing
persisted policies drift and remain refused; no migration or backfill is added.
Policy inspection fingerprints code only and never constructs or invokes a reader.
The finite recovery entry chain also requires original import-alias identities
and each function's canonical application module dictionary. Replacing an alias
and its canonical target with the same-code function over different globals is
therefore refused before recovery. This gate does not recursively expand to
unrelated application paths or standard-library internals.

This primitive neither launches a producer, model or evaluator nor writes a
checkpoint, budget, admission ACK, transaction, population or result. Any failed
read consumes the in-memory reader without retry or pin adoption. Mailbox service,
creator-pin provenance transport, exact transaction dispatch, prepared admission,
rejection, terminal result delivery and interrupted-run reconcile remain separate
composition work. An original owner plus comparison evidence is not proof that
the full execution chain has been integrated.

Focused tests use a real registered owner and running/started SQLite state,
real durable canonical receipt readback, output capture and broker journal,
envelope/material/bundle/draft reconstruction and creator-pinned handoff readers.
Only native process terminal reprojection and its formal receipt projection are
explicit inert fixture doubles. No native target, real solver, model, evaluator,
WebAgent or remote service is run; this proves reader composition, not native
execution or production admission. Development failures and frozen validation
results must retain distinct labels.

The reader test inventory has 53 cases. Development `dev-11` passed the prior
47-case inventory; `dev-12` passed 12 focused cases for canonical-global binding,
successful recovery, current cancellation, timeout and last-source-hook controls.
These are development results, not final unified acceptance. The final integrated
source still requires the owner-prepared-pin composition and frozen Mac/Linux
qualification under the coordinating worktree's exact commit and tree.
