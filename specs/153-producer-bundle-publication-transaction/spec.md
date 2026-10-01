# Feature 153: producer bundle publication transaction

**Status**: Offline imported Shinka material can pass native draft evaluation, retained-evidence
publication, population read-back/resume, and delivery verification in the initial population
window. Caller-owned active deadline/cancellation, same-boot durable deadline restoration,
durable all-rejected terminal inspection, the optional Feature 156 formal execution-receipt link,
and complete formal receipt schema revalidation at this boundary are implemented. A local
provider-free native trusted one-shot/recovery supporting slice is also available. Active-process
cancellation, full unknown-result recovery, production launcher/scheduler integration, and real
campaigns remain open.

## Problem

Feature 152 produces an authority-bound admission plan, but the plan is still an in-memory
intent. It does not reserve an archive prefix, describe per-candidate execution outcomes, or
make a partially published producer batch recoverable. Passing the drafts directly to the legacy
seed publisher would incorrectly require `SeedManifest` evidence and could mix producer bundles
with an unrelated archive state.

## Outcome

Define a separate, durable batch journal for producer bundle publication. The journal binds one
Feature 152 plan digest to the contract, execution authority, archive prefix, candidate order,
per-candidate receipts, and a terminal publication state. The implemented offline path connects
an imported Shinka `programs.sqlite` export to native local evaluation and atomic publication of
the admitted subset. The contract below remains the full target; the remaining implementation
limits are listed under Integration boundary.

## Contract

- A journal is created from one `ProducerBundleAdmissionPlan`, one run/task identity, and one
  canonical archive-prefix digest. The plan digest, run identity, and prefix digest are immutable
  for the lifetime of the batch.
- Before the first native draft evaluation, the complete prepared journal is durably written to
  `journal.prepared.json`. It remains distinct from the adjudicated publication journal. An exact
  pre-publication retry checks the original prepared bytes; changed task, plan, budget, prefix,
  authority, or candidate mapping cannot adopt an already-started run.
- The archive prefix covers append-order archive records, the current `state.json`, strategy
  configuration, active island assignments, and any seed-commit marker. A digest that omits state
  or reorders records is not a valid prefix authority.
- Candidate order is the plan order. Candidate IDs are derived before execution and cannot be
  replaced, reordered, or reused by resume.
- Candidate IDs are safe, deterministic hashes of the batch ID, plan ordinal, bundle ID, and
  bundle digest. Preflight rejects collisions with existing archive records and never calls a
  sequential `next_id` allocator.
- Each candidate mapping records its strategy, parent ID, generation, iteration, island ID, and
  the population configuration digest. The mapping is fixed before the first execution and is
  sufficient for `PopulationStrategy` to reconstruct active state.
- Each candidate has separate preparation, execution, evaluation, and publication receipts. A
  missing, duplicated, stale, or cross-batch receipt blocks publication.
- The transaction binds one canonical budget profile digest covering preparation requests,
  execution/evaluation limits, and the total wall-clock allowance. Resume cannot widen or replace
  that profile.
- Every item is adjudicated before publication. Known local invalid items are recorded as
  rejected, while the admitted subset is published all-or-nothing. An empty admitted subset
  is recorded as a durable `all_rejected/committed` terminal without changing the archive or
  active state. Execution and evaluation receipts remain bound to their original retained evidence.
- For the admitted subset, the archive, candidate source trees, sidecars, state snapshot, and
  journal terminal marker must agree before success is exposed.
- A failed pre-publication attempt may be resumed only from the exact journal and exact plan.
  An unknown or partially published result is terminal and fails closed; it cannot be repaired by
  silently replaying the producer or evaluator.
- A pending item with no side effect may continue. Existing execution/evaluation evidence is
  reused only after exact receipt and inode/byte verification; `running`, `unknown`, timeout, or
  cleanup-unknown evidence never triggers a producer/evaluator replay and returns
  `recovery_required`.
- A nonzero process exit, invalid evaluator result, or independently verified cleanup failure is a
  known rejected item. Timeout, observer/cleanup unknown, missing evidence, and any uncertain
  write or commit state are `unknown` and make the whole transaction terminal.
- Journal bytes live in the system-generated
  `workspace/evolution/producer-batches/<batch_id>/` directory; callers cannot choose a sibling,
  symlink, or path outside the run workspace. The journal, stage tree, and recovery marker have
  fixed names, regular-file/no-follow checks, and bounded sizes. Journal parsing is canonical,
  bounded, no-follow, and provider-free. It never executes source,
  calls a producer, or treats producer scores as local authority.

## Non-goals

This feature does not change the legacy single-file `SeedManifest` protocol, the existing seed
publisher, automatic solve defaults, AgentLoop defaults, producer launchers, schedulers, remote
transport, or real external campaign acceptance. It does not claim framework parity or model
effectiveness.

## Integration boundary

The preflight, stage and commit APIs remain provider-free and consume adjudicated local evidence.
`run_native_producer_bundle_publication_transaction()` now connects them to
`MultiFileCandidatePipeline.evaluate_draft_non_publishing()`. Imported Shinka SQLite material
passes explicit bundle grouping and the Feature 152 admission plan, then executes and is
independently evaluated locally under deterministic candidate IDs. The transaction freezes the
draft batch, verifies the live strategy configuration and authority against the existing state,
and records the immutable prepared journal before the first execution. It does not invoke the
normal per-candidate publisher or sequential ID allocator.

The native bundle-evidence parser currently requires `run_root` under
`evolution/bundle-attempts/.bundle-run-<24-hex>` and verifies the original execution and
evaluation paths. Therefore the first integration keeps each retained run at its allocated
path in the destination workspace while using a private batch source/stage tree. Before candidate
execution, the run is durably bound to the prepared journal digest and planned candidate ID. It
is not a published archive candidate and its evidence is never moved. An exact pre-stage retry
can inspect completed retained evidence without executing or evaluating it again. Copying a
scratch archive or rewriting candidate IDs, evidence paths, digests, or inode identities after
execution is not valid evidence.

The non-publishing native path accepts the planned ID and frozen lineage/island mapping,
revalidates the source bundle, and uses the existing executor and independent evaluator. It
leaves destination `archive.jsonl`, `state.json`, and final `evolution/candidates/<id>` trees
unchanged until commit. Independent evidence inspection prepares canonical native records and
receipts for the planned final source paths. Staging binds and rechecks the retained prepared
intent, source, plan/admission, workspace/input, attempt/completion/cleanup, and evaluation evidence
alongside portable receipts. A portable digest alone does not establish retained evidence.

The supported entry point requires an initialized population with `iteration=0` and
`status=running`, no offspring history, no seed admissions, and no previous producer admissions.
Evolved and terminal populations are rejected before evaluation. `state_after` is derived from
the frozen archive and admitted candidate records using native ranking, island capacities, best
candidate and stagnation rules. Admission to the archive does not guarantee active membership:
the active population remains bounded. The publication lock checks the original archive/state
prefix and retained evidence before any final candidate, archive, or active-state change.

After commit, the transaction checks native archive integrity and the complete state/population
projection. Offline coverage also verifies `PopulationStrategy.resume()` and delivery publication
and inspection through the existing delivery APIs. Delivery verification does not introduce a
new automatic delivery orchestrator or establish real Shinka campaign acceptance.

The optional `execution_control` accepts a caller-owned `SolveExecutionControl` created before
preparation. It shares one fixed active deadline across preparation, every candidate, adjudication,
publication lock acquisition, staging, and commit admission. Existing tighter parent controls are
preserved and hooks are restored on exit. Every invocation derives its budget digest from actual
native execution/evaluation limits, zero preparation provider requests, and the declared wall
allowance (`null` when omitted). An explicit digest only checks that policy; it cannot replace it.
An exact retry cannot remove the control or change limits while preserving a controlled intent.
The caller must retain the same control for in-process retry; this API does not persist elapsed
time or prevent a caller from constructing a fresh control with the same allowance after restart.

Cancellation and expiry stop admission to subsequent stages and bounded lock waits. Native
subprocesses receive their remaining timeout at launch; cancellation during execution is observed
at the next stage boundary, not by an immediate process watcher. File IO and cleanup are not a hard
host-wide timeout. Commit checks again after acquiring the lock and verifying the staged evidence.
After writing the durable unknown marker it completes the existing commit protocol, without a
new timeout check that could create partial publication or misreport an already published batch.

A successful local execution with independently evaluated `validity=0` can be finalized as
all-rejected. The separate `rejections/` receipts and `rejections.json` manifest bind every original
native source/run/evaluation and prepared intent; `journal.json` is written last. Inspection
rebuilds the complete receipts from retained evidence, verifies bytes and identities, and checks
unchanged archive/state digests. Exact transaction retries return the terminal journal with no
evaluation calls. Missing or partial terminal evidence requires recovery and is never silently
repaired or replayed. Nonzero execution, timeout, and other unknown draft outcomes are still
outside this completed terminal slice.

The transaction also accepts an optional `native_execution_receipt_sha256` from the trusted native
producer path. Before creating `journal.prepared.json` or any other publication side effect, it
reads the create-only `execution-receipt.json` under the journal's batch directory, verifies its
self-digest, complete nested stream/envelope evidence, owner identity,
identity/status/cleanup/broker summary, and retained native evidence, and records the same digest
in the canonical publication journal. Legacy calls that omit the link retain their original
canonical bytes. The local `native_trusted_scheduler` composes this receipt path with one-shot
attempt and strict output projection, and exposes a read-only recovery projection. Neither
boundary launches a replacement producer or implies production scheduler/real-campaign acceptance.

Remaining work includes active-process cancellation and the full unknown/interruption recovery
matrix. Launcher/scheduler integration, remote execution, and real OpenEvolve/Shinka campaigns
are separate work.

## Acceptance

1. A valid plan creates one canonical journal whose digest is stable across parse/serialize
   round trips.
2. Contract, evaluator, runner, dependency, environment, plan, and archive-prefix drift are
   rejected before any candidate or archive write.
3. Preparation, execution, evaluation, and publication receipt ownership is unique and ordered;
   duplicate or foreign receipts fail closed.
4. A mixed batch records every adjudication and publishes only the admitted subset once, with one
   terminal journal marker and no partial archive/state success; an all-rejected batch publishes
   nothing.
5. Injected failures before publication leave no committed subset; failures after publication are
   reported as unknown and cannot be retried through the same journal. A terminal marker and
   after-archive/after-state digests are required before success is exposed.
6. Resume accepts only the exact journal, source bytes, authority pins, archive prefix, and
   receipt set; stale, reordered, truncated, symlinked, or tampered files are rejected.
7. Existing single-file seed, native multi-file, worker, and acceptance regressions remain
   unchanged, and provider-free tests do not start a producer or model provider.
8. The preflight revalidates the existing candidate source/record/receipt tree before any batch
   write; archive/state drift or source tampering has zero side effects.
9. A verified two-file draft executes and is independently evaluated once under its planned ID.
   Before commit, the original archive/state bytes and final candidate-tree inventory are
   unchanged; sequential ID allocation and per-candidate destination persistence are not called.
10. Staging and commit reject missing, foreign, truncated, symlinked, replaced, or identity-changed
    retained native evidence, even with unchanged portable receipts. A successful commit passes
    native archive integrity, population restore, and delivery read-back checks.
11. Mixed admitted/rejected candidates publish the admitted subset once; an unknown attempt,
    cleanup uncertainty, deadline expiry, cancellation, or archive-prefix drift publishes none.
    Recovery inspection does not replay a started execution or evaluator.
12. Deterministic draft run allocation creates directories relative to held no-follow directory
    descriptors, binds device/inode identity, and rechecks the parent, run and child names before
    returning. Active directory or symlink replacement fails with `destination_changed` without
    writing or changing permissions through the replacement. Existing run IDs remain create-only.
