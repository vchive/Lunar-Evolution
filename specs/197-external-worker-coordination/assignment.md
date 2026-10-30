# Slice B — durable external-worker assignment

Status: local implementation and combined focused/static validation complete;
cross-host deployment and simultaneous-owner acceptance remain open. See
`validation.md` for the exact scope and retained original failures.

## Contract

One trusted controller host owns the existing RSILedger. An explicit API records
an assignment for an already-started native claim. The caller must hold that
ledger instance's original run lock, supply its current checkpoint and the exact
original native claim. Registration does not create a claim, launch a worker or
deliver execution authority. The caller is trusted to supply the original owner;
the legacy native-claim table does not independently attest the creating run.

The assignment binds controller/run/task/episode, complete request and plan,
claim digest, original checkpoint, worker/host/boot/key identity and profile. It
creates a cryptographic challenge once, with generation fixed at 1. A global
episode namespace and local episode guard prevent a second assignment through a
different run, worker, profile or controller namespace. The existing callback
journal persists intent before creating the challenge and result afterward.
Interrupted intent remains recovery-required; registration never retries it.

Receipt recording loads expected context and identity from that assignment,
authenticates actual receipt bytes with Slice A, and consumes the challenge once
in a shared settlement journal. An unknown outcome uses the same settlement ID.
Completed settlement and interrupted settlement both refuse further consumption,
including after reopening the ledger. Invalid authentication writes no journal.
Current run lock/checkpoint and started claim are rechecked before each write.

Read-only inspection retains original challenge and outcome. It grants no new
execution, completion, cleanup, evaluator acceptance or publication authority.
There is no automatic reassignment, TTL takeover, remote PID inference, shared
NFS SQLite, transport or service. Unknown does not prove that a remote worker
stopped. Production admission and online publication remain false.

## Validation

Use isolated local SQLite fixtures and actual HMAC, with no worker launch or
remote request. Cover original claim and checkpoint drift, missing/foreign locks,
one-time receipt consumption, invalid identity/bytes, reopen/replay, cross-run
duplicate registration, unknown fencing and interrupted journal recovery gates.
The root performs one combined focused run and static checks after code freeze;
these local tests do not establish cross-host deployment acceptance.
