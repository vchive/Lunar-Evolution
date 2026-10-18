# Original rejected BRS owner selected-ready ACK

## Status and scope

This describes the successor to [rejection-owner-p-c2.md](rejection-owner-p-c2.md),
based on `de4fae1f0228863df4f647c7c02fda0da847753b`. The internal raw-ledger helper
sub-slice in PR131 is independently accepted on frozen `62eec36`, with the same 54
cases passing on macOS/Linux and zero failures/errors/skips. This does not implement
or accept the full owner/selected-ready ACK contract below. The next read-only
synchronization/channel observation prerequisites are described in
[rejection-ready-observers.md](rejection-ready-observers.md). Preceding P/C2 validation,
complete CI and main integration are separate.

The connected pre-arm implementation is specified separately in
[rejection-ready-capture.md](rejection-ready-capture.md). Its one-shot capture is not
arming and does not implement the staged ACK interfaces or final-reader contract below.

After its own confirmed ordinal-zero C2/P, the exact original
`_BRSLineageCheckpointOwner` may acknowledge one actual ready request from its original
selected worker against the existing admission record. Preserve the original owning
thread/controller lease, wave/handoff/nonce/channel/condition, running run/episode,
started claim, C1/C2/P custody, source, M0, budget and null publication head.

No second reference pin/registration/CAS, checkpoint, attempt, evaluation or budget
consumption occurs. ACK returns only the original admission record digest. Success
proves retained channel ACK; actual worker receipt is a separate fixture observation,
not result or handoff-completion authority. Dispatch, fresh native rejection routing,
result/terminal/reconcile/root/serial and runtime/CLI/solver acceptance remain successors.
Public native BRS, production admission and online publication remain closed. Only local
inert/provider-free fixtures are allowed; no P2, distributed service or remote evaluator.

## Dedicated interfaces and unchanged refusals

Existing `BRSAdmissionChannel.service()` exposes ACK before observation-scope exit;
`request()` may return without waiting for `_servicing=False`. Final checking in that
old scope cannot prevent premature ACK visibility. Add a dedicated staged-ACK path;
leave old service, worker request and fresh-reference handler semantics unchanged.
The fresh-reference handler must still reject an already registered episode.

The intended private interfaces are:

- Owner `service_rejection_ready(*, timeout: float) -> str`: dedicated-module alias
  on the original class; consume one scope and return the original record digest only
  after commit. Timeout raises a fixed refusal and consumes the scope, forbidding polling.
- Channel `_service_selected_rejection_ready(owner, *, timeout: float) -> str`:
  owner-thread/exact-owner-only fixed delegation; reuse original pending/queue/condition.
  Accept no arbitrary handler, commit hook, caller ACK or external permit.
- Controller `_python_admission_existing_rejection_brs_ready(owner, ready) -> str`:
  read-only original-record comparison bound to the exact active service/pending;
  never call the old handler, pin kernel or register API.

Helper decomposition may change during implementation; authority/visibility cannot.
Keep long methods in a dedicated rejection-ready module, with minimal owner slots/init/
aliases/policy wiring. Do not connect these interfaces to public dispatch in this slice.
Original `_before_channel()` and provenance empty-channel gates remain unchanged.
New states require a separate exact validator, never `allow_nonempty` or cleared requests.

## Capture before arming and existing-reference check

Complete original empty-channel C2/P checks, then independently retain immutable:

- C1/C2 head/payload; selected reference canonical bytes and original admission digest.
- Original run/episode heads, full started claim, plan/prepared journal/expected anchor.
- Original writer-returned P pin/body bytes/digest, descriptor/snapshot/native pins,
  ledger inode identity and selected handoff bytes.
- Original budget bytes, M0, intents/executions and publication state.

Unlocked `_python_admission_evidence()` may reconstruct the record. Its returned current
checkpoint must equal held C2 before and after; never adopt it. Existing read-only
`_validate_python_admission_record_evidence()` and `_validate_python_admission_references()`
may be reused with a pinned graph. P/C2 already validates prepared references beside
rejected state; this does not waive file or row validation.

Read canonical `RSILedger.python_admission_record()` against original record/run/episode
heads and held C2, comparing full canonical bytes to rebuilt evidence and held reference.
Ready must carry the unchanged three-field canonical payload, request digest and entire
original plan/journal/anchor. Matching IDs or an existing reference alone are insufficient.
Reject any missing/drifted evidence without repair, recovery or refreshing original pins.

## One-shot state

Keep `_phase="rejected-provenance"`; use a separate bounded ephemeral
`unused -> armed -> inflight -> committed` state. Any failure after arming sets failed
and poisons the owner. There is no reset/rearm/retry or new persisted schema.

| State | Requests / queue | Pending / servicing | ACK |
| --- | --- | --- | --- |
| unused | Empty / empty | Absent / false | None |
| armed-empty | Empty / empty | Absent / false | None; bounded wait |
| armed-queued | Only original pending / that pending | queued / false | None |
| inflight | Only original pending / empty | inflight / true | Local staged value only |
| committed | Only original pending / empty | done / false | Original ACK/four fields retained |
| failed | Retain existing evidence; never service again | Fixed failure / false | Failure rules below |

Each state checks original channel/condition/thread/run/wave, selected episode/digest,
original singleton nonce, handoff mode and empty completed-selected set. Validate exact
primitive/container types before lookup/equality. Retain the same exact pending/detached
ready/bytes/digest/binding through later states; a matching reconstructed pending fails.
Arming requires empty channel; early ready, sibling, duplicate, old ACK, close/cancel/error
or reentry refuses. Timeout consumes the scope even without a request. Require exactly
`type(timeout) is int` or `type(timeout) is float`, finite, with `0 < timeout <= 60`;
reject bool, subclasses, nonfinite values and zero. This is only a queue-wait bound,
using the earliest of its monotonic expiry and original run/control/parent remaining
deadlines. It does not establish a new allowance for validation or commit, which still
check the unchanged original deadlines. Never extend those deadlines. The existing
generic service's timeout semantics remain unchanged.

## Lock order and ACK visibility

1. Retain the original controller mutation/lease context. Wait with channel condition
   only; take the unique pending inflight under it, then release for dynamic observation.
2. Finish source/config/control callbacks, native strategy/input validation/recovery,
   exact ready/reference checks and ACK construction outside both short locks. Stage ACK
   and its four plain strings in owner locals; pending ACK/fields stay null.
3. Final order is controller observation RLock -> held channel condition -> read-only
   ledger observation. No outer path takes observation mutex while holding condition.
   No callback, worker wait/join or executor shutdown runs under either short lock.
4. Use the fixed graph below for final C2/history, physical material, run/episode/claim/
   result, deadline and exact pending/ready/cancel/error/closed checks. Refuse shadowed
   condition/context operations before invoking them.
5. Before the first ACK/field assignment retain a `commit_started` marker. After the
   last fixed gate only assign pending done, original ACK/fields, owner committed and
   servicing=false, then notify. Partial assignment is not a completed ACK: the scoped
   success observer requires all four held strings and the exact retained ACK to agree.
   Release of condition is worker visibility.
   No later dynamic observer may retroactively validate the ACK.
6. Once any ACK/field assignment occurs it is permanent evidence. A marker alone does
   not prove assignment or receipt; retain exactly the prefix that actually occurred.
   Notification or
   context/lock-exit uncertainty poisons and retains fields; never enter legacy service
   cleanup that clears ACK. Do not claim uncertain delivery means worker nonreceipt.
7. Release both short locks and close before join/shutdown. Worker post-ACK validation
   reacquires observation mutex, so joining under it can deadlock. Worker post-ACK checks
   and actual receipt are separate from retained ACK commit.

## Fixed final-reader graph to finish before implementation acceptance

These are required roots/known edges, not an already implemented complete policy.
Use canonical class-level readers after exact-instance/instance-shadow refusal. Pin
all reachable functions/aliases/globals/code/defaults/keyword defaults/attributes/plain
metadata under an independently held guard before owner/fixture capture. Keep current caps.

| Responsibility | Existing roots and required known edges, or dedicated fixed replacement |
| --- | --- |
| Exact channel/ready | New strict primitive/identity validator of held channel/condition/pending/detached ready/snapshots; no instance DTO serializers. |
| Lock/observation | Original controller observation RLock; Condition and its original native RLock, acquire/release/notify/wait operations and instance-bound internal operations; ledger read-only observation, `_connect`, controller ownership checks. |
| C2/admission/run/episode/claim/result | Complete canonical readers validate these outside the short locks. Before arming, independently hold their original raw rows, heads and ordered histories. A dedicated bounded read-only transaction compares that same row snapshot immediately before commit, including result absence and original adjacent C1/C2. It must not invoke the full controller/DTO validation graph in the final tail. The exact table/column/order inventory must be reviewed before implementation. |
| Ledger inode | Canonical `_read_ledger_identity` and bounded DirectoryChain/stat/open/fstat/check/close graph; original database path/device/inode. |
| Material pins | `verify_persisted_lineage_snapshot -> verify_lineage_snapshot_pin -> _observe_file`; `read_lineage_v2_descriptor_pinned -> _normalized_snapshot_pin / lineage_directory / _observe_file / parse_lineage_v2_descriptor`; original descriptor/snapshot/native pins. |
| P | `read_native_rsi_rejection_provenance -> _dto_shape / _directory / _read -> _read_once / strict evidence parser` and DirectoryChain cleanup; original full bytes/body digest/writer pin. |
| ACK construction/receipt | `BRSAdmissionAck.__init__ / __post_init__ -> _identity / _sha / _fail`, including the unchanged worker `request()` constructor call under the condition; no dynamic callback may enter through this tail. |
| Final tail | Strict numeric/deadline/budget/capture checks and canonical clock primitives; no callbacks after physical reads; fixed ACK assignments and notification only. |

The smaller read-only transaction is the chosen final ledger reader. The existing
`python_admission_record -> _python_admission_state_tx` graph reaches staging history,
child checkpoint selection and `component_fingerprint(select_native_candidate)`; pinning
that graph would not remove its dynamic callbacks. Keep complete semantic validation
outside the short locks and reject any later raw-row drift instead of accepting a rebuilt
record. This choice does not narrow the original supported state or waive indirect rows.

The first implementation sub-slice is an internal
`rsi_brs_rejection_ready_ledger` reader/comparer. It returns immutable primitive rows,
bound to the original absolute database path, run ID and complete episode domain. Its
six ordered row groups contain all columns of:

- `rsi_records`: complete original run and wave/held-reference episode histories.
- `rsi_controller_journal`: complete original run history, including adjacent C1/C2.
- `rsi_python_admissions`: every original run row, not only the selected admission.
- `rsi_native_episode_claims`, `rsi_episode_results`, `rsi_episode_reconciliations`:
  the complete union of wave and held-reference episodes, including empty row domains.

Use explicit columns and deterministic ordering in one non-creating, query-only SQLite
read transaction, and close the connection on success or failure. Compare exact SQLite
primitive types as well as values; insertion, deletion and modification all refuse. Bound
row count and total bytes without raising existing record/snapshot limits. Independently
hold and compare the six original `sqlite_schema` source rows in that same transaction;
require actual ordinary tables, including original SQL and root pages, so an equal-row
replacement view or virtual table cannot masquerade as the original source. Schema rows
are comparison metadata, not another business table or a new durable schema. This helper
does not parse DTOs, invoke controller/source hooks, validate an owner or grant ACK
authority. The caller must completely validate semantics in the same read snapshot, or
prove that full raw captures before and after semantic validation are identical. Original
database inode custody remains a separate owner gate; matching rows at a replacement
path are insufficient. No owner/channel wiring is part of this first helper sub-slice.

Finish the transitive inventory of the dedicated SQL reader, `_connect`, physical readers,
DTO parsers, DirectoryChain and Condition/RLock/context methods. Hold the exact database
Path and relevant path/SQLite runtime operations. Material readers construct and compare
`LineageSnapshotPin`; its generated constructor, post-init, from/to-dict, equality and
dataclass field metadata belong to the fixed graph, including closure-cell custody where
present. Inventory and review precede real fixture enablement; the table alone is not an
executable fingerprint projection.

Condition class methods alone are insufficient: `notify_all -> notify -> _is_owned` and
waiter releases, and `wait -> _allocate_lock / _release_save / _acquire_restore` also use
instance-bound operations. Hold the original Condition/native RLock, queue, waiter types
and these operation identities; refuse shadows before invoking them. The observation
context similarly needs its original RLock and context/thread-local restore graph pinned,
or fixed operations on the held original lock that preserve the existing lock semantics.

SQLite read-only connection acquisition may wait up to its existing 30-second timeout.
Check the original absolute deadlines again after the last ledger read and immediately
before ACK assignment; a pre-read budget check cannot authorize a delayed commit.

Do not reuse `_fresh()` (native recovery/strategy/input operations), `_observe()`, `_fixed()`,
`_identity()` or public provenance getters as final bundles. Existing `_readback(final=True)`
covers history but not complete run/episode/claim/result gates. Finish dynamic seams first,
then fixed physical/canonical reads. This local ordering does not create a multi-machine
atomic transaction or authorize accepting later external drift.

## Failure and postcommit inspection

Preassignment failure leaves ACK/fields null, supplies a fixed pending error if present,
clears servicing, poisons/closes the consumed scope and retains C1/C2/P/captures. No retry,
rollback, orphan adoption, latest-head refresh, repair or unknown upgrade is permitted.
After any ACK-field assignment, uncertain notification/context-exit/worker-check/cleanup
failure retains all assigned evidence and poisons/closes; never clear/replace/reissue ACK.

Old provenance getters intentionally refuse the now-nonempty channel. A new scoped fixed
observer checks held captures/retained channel fields; do not temporarily clear requests.
Leave handoff selected/uncompleted. Fixture close is cleanup, not handoff completion.
No path writes result/execution, settles claim, issues selected-return, consumes reconcile,
advances root/publication or selects another ordinal. Budget and original file pins stay fixed.

## Implementation and verification tasks

First implement staged transport/error/visibility, then original capture/existing-reference
checks and independently reviewed finite readers. Use sealed one/two-candidate fixtures
with existing `test_rsi_brs_publication_lineage_owner.py::_waiting`: its real
`_execute_brs_intent` claims the episode, waits on ready, invokes unchanged worker ready
request, reports the ACK digest through messages, then waits on stop. Do not inject pending.
A fixture observer may wait for armed under the original condition and release ready outside
it; this coordination is not a production callback. Close/release stop+ready before bounded join.

Prove no ACK while final gate is paused and real worker receipt of original digest afterward;
no second pin/CAS/attempt or changes to captures/P bytes+inode/budget/started claim/running
run+episode/absent result+executions/null publication. Cover precommit close/cancel/timeout,
reentry/duplicate/foreign identity, last-dynamic-seam P drift, final-reader shadows,
postassignment notify failure, permanently retained fields, old empty-API refusal and no leaks.

After implementation changes run focused tests, Ruff, compileall and diff-check. Freeze one
source for matching macOS/Linux inventory/raw/JUnit/import/source evidence and independent
product/evidence review. Full dependency-ordered CI precedes main merge. No acceptance box
may be checked merely because this design exists.
