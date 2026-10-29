# Original owner durable recovery evidence

## Current gap and scope

PR125's frozen `1e7f6cf` has passed the same 213 scoped fixture cases on macOS
and Linux, static checks and independent product/platform/aggregate review. Its
complete GitHub CI and prerequisite merges remain pending. The private mailbox
now delivers the existing exact response, but the original recovery obligation
still has `worker_profile=None`, and mailbox observations disappear with the
controller. Neither callback completion nor a joined Python thread proves an
episode result or native producer cleanup.

This follow-up persists original-owner observations and native producer record
bindings. It does not settle an episode, consume an obligation, reconstruct an
ephemeral owner, retry publication, enable public native BRS or change production
admission. Only local inert/provider-free fixtures run. Remote evaluators,
external authentication and distributed ownership remain deferred.

## Storage and immutable capture

Use the existing `rsi_controller_journal` checkpoint/hash-chain/CAS mechanism in
one deterministic observation namespace derived from the original obligation.
This is not the `DurableCallbackJournal` started/completed protocol: its cached
replay behavior and two-record schema cannot represent mailbox observations.
No database migration or change to obligation v1 is required. Keep the original
run checkpoint, owner/wave cursors, budget, handoff and obligation unchanged.

The binding contains the complete original obligation and selected handoff, their
digests, selected SolverRequest/native plan/started claim identity, original run
and episode record pins, and one detached native-process capture. Explicitly
distinguish the SolverRequest digest, mailbox request envelope digest, response
envelope digest and response payload byte digest. None is a SolverResult digest;
never populate `owner_result_sha256` with transport evidence.

Native process capture uses the original owner's already retained native context
and plan. It identifies the earlier native producer OS process, not the current
BRS worker thread. Reuse verified registration, formal receipt, terminal and
cleanup records, their original launch/ownership digests and entry-observed file
identity pins. Do not fabricate an ExternalWorkerTrustProfile, runtime or project
digest. Missing original material yields a fixed unknown capture; it cannot be
backfilled or upgraded later. A captured reference that changes yields drift.
Entry pins make no claim about historical creator identity. Observation never
signals a process, performs cleanup, launches a worker or writes native files.

## Finite mailbox observations

The original bridge records at most these four adjacent observations:

1. `owner_capture`: after the durable run obligation, before mailbox service;
   persist the original binding and actual open/queued snapshot even if no request
   is eventually serviced.
2. `request_observed`: handler entry, before native publication; retain the actual
   immutable request envelope identity and payload byte digest.
3. `response_generated`: after constructing the exact response DTO, before making
   it available to the worker; persist its original request binding and byte
   digests. Invoke the internal observer outside the mailbox condition.
4. `transport_observed`: after successful service, copy actual status and the
   original `_accepted` flag under the condition, then persist outside it. True
   only proves the original worker took a response DTO. False means receipt was
   not observed at that instant. Callback/parser completion is always unobserved.

No arbitrary additional transition, cached publication replay or adoption of a
latest namespace head is allowed. A missing suffix is partial/unknown. Failure
after any append retains that evidence and the original run fence. Publication
may already be durable; never retry it to repair an observation gap.

## Owner, transaction and readback rules

Only the genuine original owner thread with its original run lock may capture or
append. A namespace lock alone is insufficient. All source/config/control hooks
and filesystem observations run outside mailbox conditions, SQLite transactions
and short observation mutexes. Snapshots contain only detached primitive values.

The narrow store writer uses one `BEGIN IMMEDIATE` to verify the exact current
root checkpoint, unchanged obligation, original running run/episode and started
native claim with no saved result, then append the observation namespace using
its expected head. The root checkpoint itself never advances. Verify the exact
adjacent namespace readback, complete payload and original root/control before
acknowledging the local observation cursor. Any uncertain write/readback poisons
the original owner and preserves its old cursor; do not retry or refresh capture.
Source/policy checks include new finite dependencies and canonical aliases, within
the existing fingerprint size/depth limits using fixed grouping labels.

## Recovery reader and validation

A read-only reader on an existing rebuilt ledger validates the original root
obligation, deterministic namespace, bounded record shape, exact adjacent events
and immutable bindings. Use `read_only_observations()`; no generic callback invoke,
reconcile, owner reconstruction, database initialization or worker launch occurs.
Missing/partial capture remains unknown; drift rejects. An explicit original
native context is needed to reobserve process records; its absence is unknown.
Completed transport is still not sufficient evidence for terminal consume.

Test genuine owner/worker integration, restart/zero-write inspection, original
request/response distinctions, worker receipt observation, callback unobserved,
unknown process/no backfill, native file/identity drift, root/claim/obligation CAS
drift, conflicting/uncertain append/readback and retained fences. Preserve the
existing native all-rejected refusal. Freeze one final source, run focused tests,
Ruff, compileall and diff checks, and validate the same distinct cases on macOS
and 5090gpu Linux with collection/JUnit/source/import/exit evidence. Complete CI
and main merges remain separate gates.

## SQLite baseline lifetime clarification — 2026-10-29

The original Python 3.12 current-1 CI assertion observed an absent WAL becoming
an empty WAL during inspection, while the database bytes were unchanged. That
failure remains preserved. SQLite `mode=ro` forbids database creation and SQL
writes, but may create WAL/shared-memory bookkeeping for an existing WAL-mode
database. It must still observe committed live WAL rows; `immutable=1` is not a
valid replacement.

The zero-write fixture now explicitly holds a caller-owned `mode=ro` connection,
reads the original schema, then captures the exact database/WAL bytes and inode
identities. It keeps that connection open through inspection and both comparisons,
and closes it deterministically afterward. The original SQL-write and ledger
initialization refusals and exact byte comparisons remain; no absent/empty WAL
normalization, connection pool, product PRAGMA change or inspection authority is
introduced. This separates SQLite baseline setup from the operation under test,
without depending on older connections remaining alive until garbage collection.
The correction still requires focused regression; it is not a passing CI result.
