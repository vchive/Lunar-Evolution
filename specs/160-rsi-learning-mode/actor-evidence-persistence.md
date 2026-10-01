# Durable local Actor clean-room evidence

The local Actor bridge returns complete evidence, but the controller callback stores only the
decision. Add an opt-in `DurableActorCleanRoomVerifier(bridge, store)` wrapper and a separate
`ActorCleanRoomEvidenceStore(root)` sidecar store. Existing Actor, controller and verdict schemas
remain unchanged. Only local fixtures and importable trusted evaluators are in scope.

Each immutable record retains the stable episode identity, exact solver request/result, original
complete bridge configuration/fingerprint, decision, complete `ActorCleanRoomEvidence` and full
optional `CleanRoomVerdict`. The canonical self-digest binds every field; records are bounded to
1 MiB. Every read/write uses held no-follow directory chains and stable regular-file identity
checks; symlinks, hardlinks, replacement, malformed/noncanonical bytes and identity collisions
fail closed. Creation never replaces an existing record. Identical replay returns the stored
record; changes to inputs, configuration, verdict or decision are rejected.

The wrapper checks retained evidence first. A complete matching record returns without touching
Actor artifacts or spawning an evaluator. Before a first evaluation it creates an immutable
verification claim. An existing claim without a final record requires explicit reconciliation;
it cannot authorize another spawn. A save failure or interruption retains this unknown boundary.
An explicit save of independently retained exact evidence can complete that claim. This is local
crash safety, not remote evaluator authentication or distributed exactly-once execution.

Validation keeps Actor manifest hashes distinct from raw source/dependency hashes, verifies the
source manifest against its declared path, verifies complete original contract/environment/task/
evaluator pins, request/result identity, verdict provenance, evidence check and decision receipt.
Fail/unresolved evidence is retained for diagnosis; only a passing uncontaminated verdict can
feed `CleanRoomAdmissionGate`. The caller supplies a complete `CleanRoomAdmissionRequest`; pins
are never filled from untrusted output. Admission reaches only `verified`, with no automatic
candidate/shadow/holdout approval. Raw verdict receipts and controller decision receipts remain
different authorities, as required by their existing protocols.

Focused tests cover full durable pass/failure, record replay without spawn or source reread,
unknown claims, interrupted saves and explicit evidence completion, changed inputs/pins/config,
rehash-resistant cross-field drift, malformed/canonical/size/file-identity failures, and strict
admission provenance. Controller integration remains owned by the coordinating task.

Validation: evidence-store/controller, existing bridge and clean-room admission focused suites
pass 81 tests with no failures, errors or skips. The controller DRS fixture independently verifies
three episodes, persists all full verdicts before callback completion, commits verified practice
memory, and reopens a terminal run without solver/evaluator replay or sidecar changes. Component
configuration binds stable implementation identities and store identity, never current records or
claims. Ruff, compileall and `git diff --check` pass.
