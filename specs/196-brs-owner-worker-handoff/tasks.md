# Feature 196 tasks — implementation tracking

## Original rejection C1 successor — 2026-10-18

Contract: [rejection-owner-c1.md](rejection-owner-c1.md).

- [x] Add the original ordinal-zero BRS owner's strict rejected outcome, original
  native material verification and create-only descriptor retention.
- [x] Require internal original retention scope, exact adjacent C1 CAS/readback
  and fixed final owner gates; preserve old cursors/files on uncertainty.
- [x] Count all original native retained material plus ready/before/descriptors
  and future P reservation within unchanged aggregate/checkpoint bounds.
- [x] Pin explicit fresh rejection schema and all new finite dependencies; retain
  old shared-reader, dispatch and public admission refusal gates.
- [x] Freeze PR128 `3366036`; accept the same 255 distinct scoped cases on
  macOS/Linux with static checks and independent product/raw/source/import review.
  The earlier `986d9b1` failures remain NOT_ACCEPTED.
- [x] Publish PR128 and mark ready with its exact scoped validation evidence.
- [ ] Complete prerequisite full CI before dependent merges.

## Terminal recovery successor — 2026-10-17

Contract: [terminal-recovery-evidence.md](terminal-recovery-evidence.md).

- [x] Persist original-session delivery, callback and worker-terminal observations
  without changing the old mailbox history, obligation, root cursor or budget.
- [x] Require durable delivery/start ACK before the one-shot callback; preserve
  unknown and independently verify natural Future/executor/thread completion.
- [x] Compose exact envelope, original publication/materials, native cleanup,
  canonical claim/result and legal terminal episode from read-only sources.
- [x] Fresh-compose under the controller lock and recheck every ledger pin inside
  the existing consume/removal transaction.
- [x] Cover natural inert completion, missing/unknown/drift, rebuilt-ledger reads,
  callback failure and consume-time concurrent change; run static checks.
- [x] Freeze PR127 `f0e39b9`, accept the same 302 scoped cases on macOS/Linux
  plus independent product/raw review, and publish the ready successor PR.
- [ ] Merge only after full prerequisite CI passes.

## Durable recovery evidence follow-up

Contract: [durable-recovery-evidence.md](durable-recovery-evidence.md).

- [x] Strictly bind original obligation, handoff, run/episode/claim and original
  native process records; keep missing original process material permanently unknown.
- [x] Append at most four original-owner mailbox observations in an independent
  checkpoint namespace, with original root/obligation/claim checks in the side CAS.
- [x] Capture the actual request, generated response and transport snapshot outside
  callback-sensitive locks; distinguish receipt from callback and terminal results.
- [x] Add a rebuilt-ledger read-only inspector; reject drift, retain partial evidence
  and never reconstruct the owner, retry publication or consume an obligation.
- [x] Validate PR126 frozen `74a3f52` with the same 561 scoped cases on
  macOS/Linux, static checks and independent product/raw/source review. Earlier
  `ef7ee90` failures remain NOT_ACCEPTED; complete CI and main merge are separate.
- [ ] Complete required GitHub CI and prerequisite merges before main integration.

## Original owner rejection P/C2 follow-up

Contract: [rejection-owner-p-c2.md](rejection-owner-p-c2.md).

- [x] Add strict separate C2 parser/index/one-field transition and actual-P
  accounting; preserve C1 null/reservation semantics and all existing caps.
- [x] Capture the original confirmed C1 and implement same-owner create-only P
  retention, original pin custody, scoped C2 CAS/readback and poisoned failures.
- [x] Bind the finite fresh policy and canonical dependencies within current
  fingerprint limits; retain empty ready channel and closed public gates.
- [x] Verify PR130 frozen `de4fae1` with the same 400 scoped cases on
  macOS/Linux, static checks and independent product/raw/source review. Earlier
  `fc54109`/`5d9218a` and incomplete environment attempts remain NOT_ACCEPTED.
- [ ] Pass complete dependency-ordered CI before main merge. This slice does
  not close actual ready/dispatch/result/recovery/root/successor acceptance.

## Exact mailbox result composition follow-up

Contract: [exact-mailbox-result-composition.md](exact-mailbox-result-composition.md).

- [x] Freeze the original handoff/request before the native transaction and build the
  existing exact result payload once; return the exact bytes delivered by the mailbox.
- [x] Pin builder/projection dependencies and canonical module globals in the original
  policy contract; preserve all existing owner, registration and native refusal gates.
- [x] Exercise original-worker delivery and one-shot detached callbacks, unknown/duplicate
  refusal and retained reconcile fence with the real inert kernel.
- [x] Freeze PR125 source `1e7f6cf` and independently validate the same 213 distinct
  scoped cases on macOS/Linux, static checks and raw/source evidence. The earlier
  `9436283` failures remain NOT_ACCEPTED. Full CI and dependent merges remain open.

## Original owner mailbox registration follow-up

Contract: [owner-mailbox-reconcile-registration.md](owner-mailbox-reconcile-registration.md).

- [x] Add one-shot registration to the original new-phase lineage owner; validate original
  run/episode/claim pins in the checkpoint transaction.
- [x] Verify the exact adjacent obligation-only delta and recheck source/control before
  advancing the owner and wave cursors; preserve captures and poison uncertain writes.
- [x] Register in the original private mailbox composition before service/transaction;
  reject a foreign mailbox before mutation and retain the fence on every outcome.
- [x] Pin new dependencies and add focused local fault coverage.
- [x] Independently validate PR124 frozen `56745c2` on macOS/Linux: the same 288
  scoped cases passed on each platform. Required full CI and merge remain separate.

Automatic terminal consume, producer-first-launch registration and real runtime/
OpenEvolve/Shinka/production CLI acceptance remain open outside this slice.

## Recovery correctness follow-up

- [x] Fence ordinary resume, drive and finalization on any latest unconsumed BRS
  obligation, including unknown/settled phases; preserve legacy terminal replay after
  explicit consumption. See `reconcile-default-recovery-gate.md`.
- [x] Report retained obligations through the existing `rsi inspect` reconcile flag
  without changing the response schema or inspecting processes.
- [x] Bind selected registration to the owner thread and captured head/state; refuse
  replay through unrelated later checkpoints and retain each obligation's own capture.
- [x] Validate natural episode successors and actual terminal native claim/result
  within the same transaction as obligation removal and checkpoint CAS; support
  independent consumption of multiple obligations. See `reconcile-controller-consume.md`.
- [x] Validate PR123 frozen `96a7394` on macOS/Linux: the same 374 distinct scoped
  cases, static checks and independent review passed. Required full CI and main merge
  remain open; local fixture success does not close runtime acceptance.

## Original implementation slices

- [x] Freeze the detached handoff fields, canonical serialization, one-shot nonce,
  and selected-ordinal identity without adding persistence schema. Implemented as a
  pure helper using the existing BRS child preflight; it is not wired to dispatch.
- [x] Add pure gates for `max_workers=1`, `M0`, selected ordinal, owner/thread, head,
  state, source, policy and execution-control pins. Existing child preflight remains
  responsible for mode, intent, budget and capacity checks. The pure nonce gate checks
  a caller-supplied consumed set; channel-level in-memory atomic consume is tracked below.
- [x] Add channel-level owner-thread nonce consumption and a single selected-ordinal
  ready/ack binding with explicit completion before rebinding. Duplicate, closed and
  handler-error wakeups are covered. The controller does not call this API yet.
- [x] Implement a private owner-created selected-child staging/dispatch service seam
  while keeping the existing DRS owner path and public APIs unchanged. The seam is
  provider-free and remains opt-in; it does not advertise native BRS.
- [x] Integrate this channel binding into the private controller ready/ack service loop
  and enforce the exact prepared-admission owner CAS there. Publication is not included.
  Source/configuration hooks run
  before the short observation lock; the channel enforces selected episode, exact ready
  digest, duplicate refusal, detached ACK state and close/error wakeups.
- [x] BRS-2c: persist one successful selected-service result through the private
  owner-only checkpoint settlement seam, with exact return receipt/ACK/result pins,
  original M0/budget/source gates, captured-head CAS and complete readback. Implemented
  in this branch; 360 final-source focused cases and independent raw/source/static
  acceptance passed. Final CI/integration is tracked separately below. No public
  dispatch, publication, sibling transition or new durable schema is included.
- [ ] Keep publication-lineage mutation, C1/P/C2 and publication head advancement
  on the owner thread; prohibit worker parent/lineage ownership. The private result
  checkpoint sub-slice above does not close this publication obligation.
- [x] Refuse the legacy active-worker publication facade and generic/DRS/scheduler
  bypasses before plan callbacks, scheduler input observation or transaction execution.
  Preserve pin-only ready/ACK and DRS paths. This refusal does not implement an owner
  publication bridge; the remaining stages are in `owner-publication-bridge.md`.
- [x] Validate the independent one-shot owner-publication mailbox transport in
  `publication-mailbox.md` with the 872-case installed Linux focused run; this is
  not controller/scheduler or owner publication integration. Final CI is separate.
- [ ] Add ordinal serial transition and partial-wave recovery without dropping
  completed obligations or refreshing sibling requests/budgets.
- [x] Add the focused matrix in `validation.md`; this slice locally exercises the
  pure identity/drift/nonce subset. Full owner, channel, recovery and acceptance tests
  remain open.
- [x] Run local provider-free focused tests, Ruff, compileall and diff checks for the
  private seam; native multi-child, sealed runtime and production admission remain open.
- [ ] Run an independent final-source CI and raw/source/tree audit before merging the
  PR. Do not mark native BRS available from design or mocked tests alone.

Implementation note (selected owner-service slice): a private controller seam now binds one
selected handoff from a complete BRS projection, rechecks invocation/ready identity, observes a
successful worker result before channel completion, and closes the channel before executor
shutdown. It is not called by the public `_drive_brs` path and does not create producer staging,
native claims, publication authority, or native BRS availability. Legacy DRS-shaped projections
remain refused.

## Rejected original owner selected-ready successor — 2026-10-18

Contract: [rejection-owner-ready.md](rejection-owner-ready.md). Only the raw-ledger
helper sub-slice is implemented; the unchecked owner/ACK tasks below do not declare
implementation or acceptance. Preceding
P/C2 validation and complete dependency-ordered CI remain independent requirements.

- [x] Implement the internal bounded raw-row snapshot/comparer for the six scoped
  ledger tables. Use one read-only transaction, complete immutable row domains,
  strict SQLite primitive types and explicit ordering; refuse insert/delete/update,
  missing database, scope expansion and run/episode ID collisions. This helper alone
  grants no owner or ACK authority and does not complete the finite final-reader gate.
- [x] Validate that helper using real local SQLite mutation/absence/capacity/WAL
  cases, focused tests and static checks. Owner/Condition policy and matching frozen
  final-source ready acceptance remain the separate tasks below. Development: 54
  focused cases passed with no skips. PR131 frozen `62eec36` passed the same 54
  cases on macOS/Linux and independent final raw/source/import review; this does
  not imply owner/ACK integration or complete CI/main integration.
- [x] Implement and development-test the read-only original Condition/native-operation
  guard and selected queued-request identity observer described in
  [rejection-ready-observers.md](rejection-ready-observers.md). Neither observer
  grants a ready scope, semantic validity or ACK authority. The two observers have
  169 scoped development cases; three additional real close/cancel/legacy-service
  transition cases passed. Matching frozen macOS/Linux evidence is recorded
  separately; owner integration and the complete final-reader graph remain the
  unchecked tasks below.
- [ ] Retain the exact original C2/reference canonical bytes, original admission
  record digest, run/episode/started claim and writer-returned P custody before
  consuming a one-shot ready scope; preserve the old empty-channel guard.
- [ ] Add a dedicated exact-owner staged-ACK service using the real original
  channel/pending/request, with no arbitrary handler or commit callback API. Keep
  ACK/fields private until the final gate, and preserve the old service semantics.
- [ ] Add the private read-only existing-reference reader; compare the complete
  canonical admission record, original plan/journal/anchor and held C2 heads.
  Never call pin/register, append a checkpoint or reserve another attempt.
- [ ] Finish and independently review the finite final-reader graph, transitive
  ledger/physical/DTO/context dependencies, source/code/default/metadata pins and
  exact-type/shadow refusal before enabling the genuine original-worker fixture.
- [ ] Enforce observation RLock -> original condition -> read-only ledger order;
  keep dynamic callbacks and waits outside short locks, and close before worker/
  executor cleanup. Timeout consumes the scope and forbids retry.
- [ ] Commit original ACK/done/owner state once under the final condition hold.
  Retain every assigned ACK field permanently on notification/context-exit or
  postcommit uncertainty; poison/close without clearing, replacing or reissuing it.
- [ ] Add scoped fixed postcommit inspection while old provenance getters continue
  refusing a nonempty channel. Leave handoff selected and uncompleted; do not issue
  selected-return, result/claim settlement or reconcile/root authority.
- [ ] Extend sealed one/two-candidate fixtures with the original `_waiting` worker,
  natural real ready enqueue and actual ACK receipt. Prove no premature visibility,
  duplicate pin/CAS/attempt or changes to original captures/P/budget/run/episode/
  claim/result/executions/publication state; cover drift, shadows and failure windows.
- [ ] Run focused/static checks and freeze matching macOS/Linux source/inventory;
  independently review final product and raw evidence before marking ready.
- [ ] Complete full prerequisite CI before a main merge. Dispatch, fresh native
  rejection routing, result/terminal/reconcile/root/serial and public/runtime
  acceptance remain separate successors; P2 and remote evaluator stay out of scope.
