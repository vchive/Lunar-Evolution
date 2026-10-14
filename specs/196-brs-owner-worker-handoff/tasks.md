# Feature 196 tasks — implementation tracking

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
- [ ] Implement owner-created selected-child staging/dispatch permit while keeping
  the existing DRS owner path and public APIs unchanged.
- [ ] Integrate this channel binding into the controller's ready/ack service loop and
  enforce owner CAS/publication semantics there. The channel helper already enforces
  selected episode, exact ready digest, duplicate refusal and close/error wakeups.
- [ ] Keep owner CAS, checkpoint save, publication-lineage mutation, C1/P/C2 and
  head advancement on the owner thread; prohibit worker parent/lineage ownership.
- [ ] Add ordinal serial transition and partial-wave recovery without dropping
  completed obligations or refreshing sibling requests/budgets.
- [x] Add the focused matrix in `validation.md`; this slice locally exercises the
  pure identity/drift/nonce subset. Full owner, channel, recovery and acceptance tests
  remain open.
- [ ] Run local provider-free focused tests, Ruff, compileall and diff checks.
- [ ] Run an independent final-source CI and raw/source/tree audit before opening a
  PR. Do not mark native BRS available from design or mocked tests alone.

Implementation note (selected owner-service slice): a private controller seam now binds one
selected handoff from a complete BRS projection, rechecks invocation/ready identity, observes a
successful worker result before channel completion, and closes the channel before executor
shutdown. It is not called by the public `_drive_brs` path and does not create producer staging,
native claims, publication authority, or native BRS availability. Legacy DRS-shaped projections
remain refused.
