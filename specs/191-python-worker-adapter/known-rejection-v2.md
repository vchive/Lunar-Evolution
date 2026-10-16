# Fresh v2 known rejection for same-workspace DRS

Status: implementation specification, 2026-10-14. Design choices below are confirmed. Helpers and controller integration are developed in a separate worktree; this does not change the frozen PR100 source, enable runtime or claim acceptance. Final integration acceptance and release depend on PR100 final validation and merge.

Reference source: `/tmp/le-pr100-lock-fix` at
`a62ac647e692c69f12f9df19d9bc6a20f792c738`. The independent source/design review is retained in the PR100 ignored reports. See `known-rejection-v2-tasks.md` for file ownership and implementation order.

## Purpose and release boundary

An explicitly opted-in experimental Python DRS run can settle a natively
evaluated `all_rejected` batch as a known failed child, retain its original
evidence, continue another allowed child, and replay that failed child after a
later legitimate publication. Evaluator validity zero is a known unsolved
outcome. Process failure, malformed evaluator evidence and interrupted publication
retain their current distinct meanings.

Only fresh v2 runs obtain the rejection-aware contract. Existing false/default
mode, single-child policy, BRS, production CLI refusal and
`production_admission=false` remain unchanged. A v1 run cannot upgrade from files
or a resume flag. Existing v1 DTOs, canonical bytes, public descriptor readers,
process-failure APIs and success receipts remain exact. Source/dependency drift
still refuses resume; this slice does not add cross-source v1 migration.

No remote evaluator, company platform, WebAgent, model/toolchain/runtime execution,
service API, distributed ownership, scheduler service, store schema or additional
execution permit is part of this slice. Acceptance uses only inert local seams.

## Confirmed decisions

1. A fresh v2 before descriptor explicitly separates the immediately previous
   attempted terminal from the latest published predecessor. Do not reinterpret
   v1 `predecessor_*` fields or relax their ordinal rules.
2. Native rejection provenance uses a distinct strict mode-0400 create-time pin,
   returned from the original publishing FD. The mode-0600 lineage pin remains
   unchanged.
3. Success, process-failure and rejection provenance exclude one another in all
   three standalone readers/writers and in the scheduler inventory.
4. Historical terminal mixed-chain inspection and C2 started-only inspection are
   separate read-only contracts. Neither can construct an owner or acquire an
   execution/acknowledgment permit.
5. Acknowledged before history is never removed. Rejection does not publish,
   create admission events, advance the published head, promote memory or fabricate
   official success. The same original owner performs C1 and C2 CAS acknowledgments.
6. The original budgets, cancellation/deadlines, held locks and 8 total attempts
   remain. A rejection consumes an attempt; it does not grant an extra quota.

## Fresh-run mode and parallel development

The Python controller API adds `producer_known_rejection: bool = False`. True
requires both existing `producer_child_execution=True` and
`producer_multi_episode_publication=True`, and is supported only for fresh DRS
runs. False preserves the v1 policy and wire. The original constructor value is
retained independently; configuration drift refuses before run/workspace I/O.
The fresh v2 policy uses `lunar-rsi-multi-episode-publication-v2` and binds every
new helper, owner method and read-only inspector in its dependency fingerprint.
Run payload and each checkpoint retain the original mode/policy. A missing v2
association, changed flag, source or policy cannot be upgraded on resume. CLI
production routes and BRS remain refused.

After helper cross-review, independent integration development may proceed on
the stable PR100 product baseline while its final CI runs. This scheduling change
does not loosen acceptance: the PR100 checkout remains frozen, the new branch
must synchronize to its accepted main baseline, and complete v2 product tests,
final-source CI and independent evidence review remain required before release.
No shared boundary file has more than one implementation owner.

## Native facts reused unchanged

`finalize_producer_bundle_all_rejected` already writes verified per-candidate
rejection evidence and `rejections.json`, then terminal `journal.json` last.
Its terminal journal is `state=all_rejected`, `publication_phase=committed`, and
archive/state after digests equal the base. Its ordered candidate set carries real
execution/evaluation receipts and no publication receipt.

The original native transaction already calls
`lineage_owner.retain_terminal(terminal, None)` after native terminal, Python
handoff/admission and original control checks. Native scheduling returns a real
`NativeTrustedProducerRun(status=all_rejected)`, retaining its producer receipt
and captured output. It must never be turned into `NativeTrustedProducerFailure`.

`RSILedger.publish_native_episode_result` already atomically publishes a failed
SolverResult with the original `expected_claim`. Existing failed episode
settlement, local failure verifier, diagnosis/practice policy and no-promotion
rules can be reused. No claim table, result schema or new ledger is needed.

## v2 before and rejected descriptors

Put the two new exact DTOs and their fixed-path persistence/readers in a small
`producer_bundle_lineage_v2.py` module. Reuse existing bounded no-follow/create-only
file machinery privately. Do not extend v1 parsers to accept a caller-selected
protocol or sibling path.

Proposed `ProducerLineageBeforeIntentV2` wire:

| Field | Exact contract |
| --- | --- |
| `schema_version`, `protocol`, `kind` | Fixed `2`, `lunar-producer-bundle-lineage-v2`, `before-v2`; stored as `before-v2.json`. |
| `run_id`, `journal_id`, `ordinal` | Original identities; integer ordinal 0..7. |
| `previous_attempt_journal_id`, `previous_attempt_outcome`, `previous_attempt_terminal_sha256`, `previous_attempt_lineage_sha256` | All null only at ordinal zero. Otherwise all present and equal the immediately prior attempted terminal; outcome is exactly `published` or `all_rejected`. |
| `published_predecessor_journal_id`, `published_predecessor_terminal_sha256`, `published_predecessor_lineage_sha256` | All null when no prior attempt published. Otherwise all present and equal the latest published head, independently of attempt ordinal. |
| `archive`, `state` | Original `LineageSnapshotPin` for `archive-before.snapshot` and `state-before.snapshot`. These equal latest published after bytes, or original genesis bytes when there is no published head. |
| `descriptor_sha256` | Exact canonical digest; strict shape/type, bounded size and detached serialization. |

Mixed-chain verification derives both predecessor associations from prior held
entries; caller strings cannot establish either authority. An ordinal-one before
after genesis R therefore references that rejected attempt, while its published
association stays null and its snapshot stays genesis.

Reuse the existing strict `ProducerLineageStagedTransition` and
`ProducerLineageTerminal` for the published branch: their before/staged digest
links are opaque exact hashes and their published semantics do not change. A v2
reader requires its before link to resolve to the exact v2 before type. V1 readers
continue to require a v1 before and cannot adopt this v2 chain.

Proposed `ProducerLineageRejectedTerminalV2` wire:

- fixed schema/protocol/kind `2` / `lunar-producer-bundle-lineage-v2` / `rejected`,
  stored at the fixed `rejected.json` path;
- original run/journal/episode and attempt ordinal;
- v2 before digest and original prepared journal digest;
- exact terminal journal digest and rejection manifest/terminal marker digest;
- ordered rejected candidate IDs, 1..32, unique and identical to original prepared
  journal, native terminal and manifest order;
- unchanged archive/state digests equal its original before snapshots;
- its own canonical descriptor digest.

There is no staged link, admitted candidate, published head, selected source or
publication/official-pass receipt in this descriptor. Existing native rejection
journal and receipts remain authoritative native material, not rewritten receipts.

Proposed pure/file APIs:

```python
parse_lineage_v2_descriptor(value) -> (
    ProducerLineageBeforeIntentV2 | ProducerLineageRejectedTerminalV2
)
persist_lineage_v2_descriptor(
    workspace, descriptor, *, expected_file_pin=None,
) -> tuple[Path, LineageSnapshotPin]
read_lineage_v2_descriptor_pinned(
    workspace, journal_id, *, kind, expected_file_pin,
) -> ProducerLineageBeforeIntentV2 | ProducerLineageRejectedTerminalV2
```

`kind` is an exact fixed allowlist (`before-v2`, `rejected`). An existing file is
not adopted without an independently supplied expected pin. No descriptor API
launches, claims, settles, acknowledges or repairs work.

## Immutable native rejection verifier

Extract private `_verify_terminal_batch_rejection_evidence` from
`producer_bundle_rejection._inspect`, analogous to published recovery's immutable
terminal verifier. Proposed signature:

```python
_verify_terminal_batch_rejection_evidence(
    root: Path, batch: Path, prepared: ProducerBundlePublicationJournal, *,
    terminal: ProducerBundlePublicationJournal,
    preflight: ProducerBundlePreflightReceipt | None = None,
) -> VerifiedProducerBundleRejection
```

The returned exact frozen observation carries terminal journal, manifest digest,
ordered candidate IDs and per-candidate execution/evaluation/retained-evidence
digests. Parsing or constructing this observation alone is not trusted evidence.

The helper verifies original prepared intent and handoff/attempt anchor, exact
terminal association, manifest canonical bytes/order/cardinality, all rejection
files and the existing native receipt reconstruction. It rejects this batch's
stage, published journal, publication manifest and publication terminal files.
It preserves absence of every rejected candidate's final candidate tree; that
check currently lives inside `_prefix` and must not disappear during extraction.

The helper does not compare current live population to the old base. The v2
lineage caller verifies its original pinned before snapshots and rejected evidence
pins before and after the helper. Public `inspect_producer_bundle_all_rejected`
and finalization retain their original `_prefix`/held-lock gates. There is no
public `ignore_prefix` parameter or current-head recovery fallback.

Each existing per-candidate rejection record already retains the native file
tables used to rebuild receipt evidence. Pin those original bounded records and
the manifest; do not duplicate every native source/receipt document into the
controller checkpoint. The provider separately reconstructs the original producer
receipt/output with existing read-only `recover_native_trusted_producer`, comparing
the exact retained receipt/output associations. It never invokes native execution
or the process-failure recovery path.

## Monotonic checkpoint and chain rules

Fresh policy protocol is `lunar-rsi-multi-episode-publication-v2`, bound in the
original run request, source/dependency fingerprint and every checkpoint. The
lineage association stays immutable for that run.

Published attempt: `before -> staged -> terminal`.
Rejected attempt: `before -> rejected(C1) -> rejected(C2)`.

Rejecting an already staged attempt is forbidden. An acknowledged prepared before
entry remains at its original ordinal with original request/memory/native plan,
admission/prepared association, before descriptor/source pins and snapshots.
Rejected entries add exact rejected descriptor/native terminal/evidence pins and a
separate `rejection_provenance` field. C1 has that field null; C2 fills it with the
original mode-0400 provenance pin and canonical provenance digest. No prior field
or pin may be replaced or removed.

`rejections` is an exact bounded projection/index of rejected entries (ordinal,
journal ID, rejected descriptor digest), never a second authoritative ledger or a
second evidence copy. Its contents and order are derived from `batches`.
`head` remains the latest published terminal. Rejection leaves it unchanged.

The reader tracks attempted predecessor separately from published predecessor.
Every attempted candidate ID and journal ID is unique across the retained chain.
Only published entries add archive rows/admission events and advance population
projection. A rejected entry verifies unchanged bytes against its own snapshots,
then leaves the published projection unchanged. A successor before compares with
that projection, not an arbitrary current population.

Absent genesis archive may recur at ordinal >0 only when no published predecessor
exists, previous attempts are strictly known rejected, the original genesis empty
snapshot digest and original evolution-parent identity remain associated, and the
archive is still absent at the live successor boundary. Historical earlier absence
is validated from original snapshot/parent evidence; it must not demand that the
archive remain absent after a later legitimate P.

Before a fresh successor, every earlier attempt must have a verified terminal
native result: completed for publication or failed for rejection. C1, orphan P,
C2 without saved result, native unknown marker, partial commit or pending attempt
never grants a successor. Each replay uses its own historical request and memory.

## Mode-0400 provenance and original pin

New `rsi_native_rejection.py` owns strict rejection DTOs, a distinct fixed filename
`native-rsi.rejection-provenance.json`, create-only persistence, pinned read and
pure mapping. Maximum provenance size is 1 MiB, matching the existing success
document bound; the unchanged 112 KiB checkpoint stores only a compact reference.

`NativeRSIRejectionFilePin` is separate from LineageSnapshotPin. It contains fixed
filename, complete raw-file digest/size, original device/inode and parent identity,
mode exactly 0400, nlink exactly one, and final mtime/ctime. It is captured from the
original publishing FD after write/fsync and compared with the named file before
return. Its strict reader compares that original pin and never refreshes it.

`NativeRSIRejectionEvidence` binds:

- exact original request/native plan and input binding;
- original started claim and ledger identity;
- C1 checkpoint digest, v2 before/rejected descriptor associations;
- native terminal journal and rejection manifest/ordered candidate set;
- original producer receipt digest and captured output digest;
- required provenance digest and original file pin only on read-back/mapping.

The persisted payload excludes C2. The file includes original publishing file
identity and its canonical provenance digest. Its original full raw-file pin is
retained independently in C2. This avoids circular hashes and file self-adoption.

Proposed APIs:

```python
persist_native_rsi_rejection_provenance(
    batch: Path, evidence: NativeRSIRejectionEvidence, *, retained_bytes: int,
) -> tuple[str, NativeRSIRejectionFilePin]
read_native_rsi_rejection_provenance(
    batch: Path, *, expected_file_pin: NativeRSIRejectionFilePin,
) -> NativeRSIRejectionEvidence
map_native_rejection_to_solver_result(
    request: SolverRequest, plan: NativeRSIExecutionPlan,
    evidence: NativeRSIRejectionEvidence,
) -> SolverResult
```

Fresh persistence refuses an existing file even with equal payload. Read/replay
requires the independently acknowledged expected pin. Before create, the writer
uses its exact bounded worst-case file-identity serialization and original verified
retained-byte count to reject aggregate exhaustion. Failed/partial files remain;
they cannot become their own expected pin.

The pure mapper requires exact DTOs, request/plan/claim/native rejection association
and read-back provenance. It returns failed status, fixed `native_all_rejected`
reason, no candidate/execution/official-pass receipt, no selected source, no score,
and verified rejection trace/provenance only. Filesystem/ledger trust remains the
provider/gateway's responsibility; a parsed DTO never grants settlement.

All three native provenance standalone readers/writers and the provider inventory
exclude either sibling kind via held no-follow directory checks. Keep existing
success/process-failure payloads and API types unchanged. A filenames-only private
helper is optional to avoid circular imports; it supplies no evidence or authority.

## Original owner C1 -> P -> C2 -> failed result

1. Native transaction writes the real all-rejected terminal and revalidates
   original native control/handoff/admission evidence. Existing exact
   `retain_terminal(terminal, None)` dispatches only into the fresh v2 rejected
   branch while the original prepared before owner still holds.
2. Owner verifies unchanged live archive/state byte and identity/absence, full
   immutable native rejection, original pins and capacity, then writes rejected
   descriptor and CAS-acknowledges C1 with provenance null. It remains the same
   thread/context/dispatch owner; nothing reconstructs it from disk.
3. Provider obtains a read-only C1 association from that owner, revalidates original
   native producer receipt/output and input/claim/config identities, then create-only
   persists P and receives its original publishing-FD pin.
4. Same owner verifies original P/pin against C1 and CAS-acknowledges C2 by filling
   the one provenance field. C1/rejected evidence and published head stay exact.
5. Provider/gateway repeat P/native evidence under held C2, original ledger/config
   identities and started claim. Gateway maps failed result and atomically publishes
   it through existing `publish_native_episode_result(...expected_claim=claim)`.
6. Existing runner/controller saves/settles failed episode, uses local failure
   verification and follows original diagnosis/practice/exhaustion policy. It does
   not promote memory, grant another launch or retry an unknown producer.

Proposed owner observations/addition:

```python
rejection_provenance_binding(terminal) -> RejectionLineageC1Binding
acknowledge_rejection_provenance(
    evidence: NativeRSIRejectionEvidence,
    file_pin: NativeRSIRejectionFilePin,
) -> None
```

The binding contains original C1 checkpoint/descriptor/native-terminal associations
and verified retained-byte accounting. It is an observation for provider evidence
serialization, not an execution permit. Existing publication methods remain exact.
New owner methods are source-fingerprinted in the fresh v2 policy.

Maintain controller-owner -> publication-lock ordering. Provider/native helpers
cannot acquire controller ownership in reverse or invoke arbitrary callbacks under
both locks. Original owner checks include controller scope, thread, dispatch lease,
CAS/checkpoint history, started claim/running episode, original source/config and
workspace pins. P acknowledgment uses the same owner, not a new inspection object.

## Read-only terminal and C2 started contracts

`RSIPublicationLineageV2Inspection` observes a durable selected terminal native
result, verifies the full mixed attempt chain, selected original request/memory/
plan, historical claims/results, native evidence and latest live published head.
Published entries require completed results; rejected entries require exact failed
results mapped from acknowledged P. It has no ownership/launch/acknowledgment method.
It supports both earlier published and earlier rejected selections under a later head.

`StartedRSIRejectionInspection` is a separate exact read-only resolver for one
explicitly selected C2-complete started claim with no saved native result. Its
constructor requires original expected current checkpoint/episode/claim and C2 P
pin, under the original held controller lock. It verifies immutable C1/C2 history
and original evidence. It accepts no other pending predecessor and never constructs
an original owner, dispatch lease or acknowledgment scope.

Provider `recover(request, plan)` selects the appropriate exact terminal outcome.
A started claim receives no ordinary historical fallback. Live verification may
use its exact still-registered original owner; explicit reconcile uses a separate
`recover_rejection(request, plan, *, inspection=...)` read-only provider route that
accepts only the exact started inspection type and rechecks its held association.

Proposed gateway/controller APIs:

```python
inspect_rejection(
    request, memory, *, expected_checkpoint_sha256,
    expected_episode_record_sha256, expected_claim_sha256,
    expected_provenance_file_pin,
) -> SolverResult
restore_rejection(
    request, memory, *, expected_checkpoint_sha256,
    expected_episode_record_sha256, expected_claim_sha256,
    expected_provenance_file_pin, before_publish=None,
) -> SolverResult
reconcile_native_rejection(
    run_id, episode_id, *, expected_checkpoint_sha256,
    expected_episode_record_sha256, expected_claim_sha256,
    expected_provenance_file_pin,
) -> EpisodeExecution
```

Gateway inspect is read-only and cannot publish. Restore rechecks the same held
pin and original claim, runs only the fixed controller boundary guard and uses the
existing expected-claim publication transaction. It never executes the provider.
Controller reconciliation resolves the exact historical child gateway/memory,
validates evidence before reserving the original unknown-evidence budget, stores
distinct rejection reconciliation reservation pins, then restores/settles without
driving a successor. Process-failure inspect/restore/reconcile remain unchanged.

Budget reservation adds a later checkpoint. Preserve C1/C2 as exact immutable
history associations; each inspection has a separately pinned current head/CAS.
Do not require current head literally equal C2 after authorized reservation, and
do not use a later file/checkpoint to refresh missing C2 evidence.

## Budget, capacity and interruption

Do not mark a rejection owner staged to reuse the existing terminal exemption.
Add an exact internal terminal-evidence acknowledgment mode, scoped solely to the
verified rejected C1 terminal or C2 P pin. It cannot reserve or extend execution.
Match existing published-terminal accounting: the bounded post-terminal owner
retention may call `_check_owner(check_budget=False)` only for this exact adjacent
terminal evidence transition, after the original native post-observation deadline/
parent/cancellation gate has accepted the completed native outcome. Provider
post-return input/claim/control revalidation remains before P and C2; run budget
and cancellation checks stay on that original path. New execution, successor
before/launch and all ordinary acknowledgments continue to use the original budget
check. Explicit reconciliation consumes the original unknown-evidence budget.
Test this named transition parity; do not make generic `_ack` or `_check_owner`
accept a caller-selected deadline bypass, and do not widen any deadline.

Bounds stay: 8 total attempts, 32 KiB descriptor, 16 MiB snapshot, 64 MiB owner
retained artifacts, 112 KiB checkpoint, 64 KiB ready capsule and 8 KiB capsule
reference. For v2, the owner aggregate explicitly includes ready capsule bytes,
lineage snapshots/descriptors and new rejected provenance bytes. Existing native
source/receipt material has its original bounded native rules; it is referenced,
not copied into the owner aggregate. Do not claim this aggregate accounts for every
file in the workspace. Rejection reuses before bytes and needs no after snapshots.

Check final projected rejected entry/C2 checkpoint and aggregate before create.
Include 32-candidate evidence pin cardinality; refuse honestly if a bounded batch
cannot fit. Do not widen caps, duplicate full evidence, discard old attempts or
orphan-adopt a failed create to fit the scenario.

| Interrupted boundary | Result |
| --- | --- |
| Partial rejection records or no native terminal | Unknown/refusal; no adoption or successor. |
| Native terminal, no C1 | Unknown; owner cannot be rebuilt from disk. |
| C1, no P | Unknown; no synthesis/evaluation retry. |
| P, no original C2 pin | Unknown; orphan P cannot pin itself. |
| C2, no native result | Explicit exact-evidence inspect/reconcile only. |
| Failed native result, running episode | Strict replay plus existing failed settlement; no dispatch/reservation duplication. |
| Terminal episode, missing controller execution cache | Replay only existing permitted projection; no proof refresh or producer. |

## Acceptance

Use original controller, gateway, native claim/CAS, scheduler/capture/native
transaction, rejection/publication, receipt reconstruction, retained reader,
verifier and settlement. Only the lowest process/evaluator seam is inert and
subprocess/network execution is forbidden. Required sequences:

- R-P-P: genesis target rejects; successful practice promotes M1; retry target uses
  M1. Earlier R replays under final published head.
- P-R-P: initial valid target misses quality; practice rejects without promotion;
  retry target uses M0. R changes no archive/state identities or head.
- R-R-R: all known failed attempts; run ends failed/exhausted, head null, zero
  publication events, original M0, absent genesis accepted at later ordinal under
  exact v2 proof. Repeated terminal resume executes nothing.

Also require an independently verified multiple-candidate all-rejected batch,
complete original order/cardinality/receipts and no fabricated selected candidate.
Cover each interruption boundary independently, mode/policy/source/config/request/
history/memory/plan/claim drift, file/inode/timestamp/link replacement, stale CAS,
foreign owner/thread/dispatch/workspace, parent/cancellation/deadline loss, both
provenance kinds, unknown publication markers and all caps before I/O.

Run focused tests and static checks during bounded implementation. Freeze one
final source for full product sequences and complete exact-head CI/artifact audit.
Pure helper tests, old XML and interrupted diagnostics do not close this slice.
