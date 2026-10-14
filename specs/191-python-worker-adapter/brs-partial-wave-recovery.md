# BRS partial-wave admission recovery

## Confirmed defect and bounded change

The existing local BRS owner supports one Python admission child alongside ordinary
siblings. It saves each execution in ordinal order after reserving all wave intents
once. If the owner stops after saving the admitted child, the next resume dispatches
only the uncached siblings. The admission wave scope currently checks every retained
reference against that pending subset and refuses the completed child's original
reference as foreign. A completed native admission obligation must survive this
partial-wave recovery.

This repair changes only the controller's existing admission wave capture and its
call site, plus a new inert regression module. It does not enable native multi-child
BRS, a producer stager in BRS, known-rejection BRS, new bindings, real evaluators,
distributed ownership, or new launch authority. Existing default and private scope
callers retain their current strict dispatch-only behavior.

## Contract

The owner supplies the complete original wave IDs separately from pending dispatch
IDs. The complete IDs must equal the IDs derived in ordinal order from the original
durable BRS plan, agree with the current checkpoint's plan, and have original intents.
Pending IDs must be precisely those complete IDs that have no cached execution.
An unrelated cached execution does not extend this set.

The channel, fresh worker token, active worker checks and Ready/Ack checks remain
bounded to the pending IDs. Completed children receive no new Ready/Ack authority.
The completed child's reference is accepted only as a retained obligation: its plan
request must equal the original intent and execution request, its cached execution
must equal the original canonical episode/result, and the existing admission row,
claim, sidecar, handoff, prepared journal and anchor checks must all still pass.
Original evidence is checked read-only before channel dispatch. The captured
controller head and payload are rechecked afterwards; there is no latest-head
adoption, missing-row repair, result fabrication, repeated reservation or deadline
refresh.

Completed native replay hooks run outside the short BRS observation mutex while
the original owner mutation lock remains held. Capture original identities and
head/payload under the short mutex first; after the read-only replay, reacquire it
and recheck those exact identities, checkpoint head, full payload and original
reference evidence before creating a channel. A callback cannot make the owner
adopt a newer head or install another ledger/gateway/sidecar. Exact JSON and string
shape checks refuse caller collection/equality hooks before original evidence reads.

## Reproduction and acceptance

Use the real controller, runner, local worker futures, bounded ready channel, owner
admission CAS and immutable native result row with inert prepared evidence. Two
practice children share M0; ordinal 0 submits the one original Python admission and
ordinal 1 is an ordinary sibling. A test observer stops ordinal 1 before calling the
original runner or creating its episode head. Interrupt the owning thread immediately
after it saves ordinal 0's original result and execution. Its reference and execution
remain cached; ordinal 1 has an original reserved intent but no episode head, result
or execution cache. The unpatched resume must reproduce the foreign-reference refusal.
A separate pre-fix control with both original results durable already succeeds because
public resume rebuilds the sibling cache before wave capture; that is not this defect.

The repaired fresh controller must finish this original wave by dispatching only the
previously unstarted ordinary sibling. It must not redispatch the completed admission
child, repeat reservations, replace references or duplicate memory.
Terminal resume must be read-only. Add refusal tests for a foreign completed
episode/reference, an altered completed execution, a missing or changed original
admission row, and a checkpoint change during capture. Verify pending worker
authority still excludes the completed admission child.
Include a replay callback whose separate observer thread must be able to acquire
the short mutex, plus callback-induced in-memory/durable head and binding drift.

Run the new regression and the existing admission/BRS channel, owner, publication
and durable flow tests, followed by Ruff, compileall and `git diff --check`. Preserve
the red reproduction and its original source identity. This is local inert recovery
validation only; `production_admission=false` remains in force.
