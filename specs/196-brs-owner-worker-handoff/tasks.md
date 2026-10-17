# Feature 196 tasks — implementation tracking

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
- [ ] Validate genuine-owner integration, fault cases and unchanged recovery fences;
  freeze one source for identical macOS/Linux cases and independent review.
- [ ] Complete required GitHub CI and prerequisite merges before main integration.

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
