# Governed frozen snapshot admission gate

`GovernedMemorySnapshotGate.validate(snapshot)` is an opt-in, local read-only boundary before
each new solver side effect. It rejects the complete frozen snapshot when any mapped item is
missing, revoked, deprecated, not active, or incompatible. It never filters items, changes a
snapshot digest, appends governance revisions, or manufactures approval. Completed episode and
callback replay remains a read-only operation and does not revalidate active eligibility or rerun
the solver.

Configuration pins the snapshot digest, an exact `memory_id -> admission_id` mapping, scope,
compatibility, and canonical governance database path/device/inode. The component fingerprint
covers that configuration rather than mutable admission heads. Revocation therefore fails at the
admission gate instead of changing the controller's component identity.

Validation reads the latest heads through one read-only SQLite connection and requires every
head to be active, passing, and regression-approved with holdout and baseline receipts. The head
must bind the exact snapshot and parent digests, canonical item digest, source episode, the item's
verifier receipt, scope, and complete compatibility map. No missing or extra mapping is accepted.
The database inode is checked before and after the read; replacement and selected-head payload,
metadata or schema corruption fail closed. This latest-head reader does not authenticate the
complete historical chain or prevent a local database owner from deleting a newer revision and
rolling back to an intact old head. Empty snapshots require an empty mapping and still retain
their configured digest.

This first boundary deliberately requires exact snapshot binding for inherited items. An admission
bound to an older snapshot does not authorize its item in a descendant snapshot: the caller must
re-admit it for the new frozen snapshot. Verified provenance-lineage reuse is deferred. The gate
is a trusted local callback boundary; it does not provide an atomic lease spanning remote solver
execution or authenticate external workers. Controller integration must call it only before a new
solver invocation, preserving already-completed durable replay.

The controller accepts `memory_admission_gate=` explicitly. It validates before reserving a new
intent and again immediately before running-episode publication/solver dispatch, then rechecks the
original budget deadline after the potentially blocking read. The optional gate identity is bound
to the run fingerprint; removing or replacing it during recovery fails closed. Existing fixture
controllers without the option retain their earlier local memory behavior.

This version consumes one governed frozen generation. A practice commit creates a new descendant;
the old gate refuses the descendant. It must be admitted with a new gate in a new run before use.
Automatic holdout/admission within the same learning run remains separate work; replacing a gate
cannot bypass that run's durable identity.

Focused fixtures cover active and empty acceptance, revocation observed by the next validation,
stable fingerprints across revocation, missing/extra mappings, all non-active lifecycle states,
source/item/verifier/scope/compatibility/snapshot drift, inherited-snapshot rejection, and database
replacement/corruption. Existing immutable snapshot bytes and governance history remain unchanged.

Validation: the focused gate and existing governance suites pass 53 tests with no failures,
errors, or skips. Ruff, compileall, and `git diff --check` pass. This evidence uses local fixtures
only; controller integration has separate coverage owned by the controller task.
