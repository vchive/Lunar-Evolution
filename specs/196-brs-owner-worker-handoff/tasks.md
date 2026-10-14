# Feature 196 tasks — implementation tracking

- [x] Freeze the detached handoff fields, canonical serialization, one-shot nonce,
  and selected-ordinal identity without adding persistence schema. Implemented as a
  pure helper using the existing BRS child preflight; it is not wired to dispatch.
- [x] Add pure gates for `max_workers=1`, `M0`, selected ordinal, owner/thread, head,
  state, source, policy and execution-control pins. Existing child preflight remains
  responsible for mode, intent, budget and capacity checks. The nonce gate checks a
  caller-supplied consumed set; atomic consume remains an owner-integration task.
- [x] Add channel-level owner-thread nonce consumption and a single selected-ordinal
  ready/ack binding with explicit completion before rebinding. Duplicate, closed and
  handler-error wakeups are covered. The controller does not call this API yet.
- [ ] Implement owner-created selected-child staging/dispatch permit while keeping
  the existing DRS owner path and public APIs unchanged.
- [ ] Route the existing ready/ack channel through the selected handoff; enforce
  one request per episode, exact payload digest, duplicate refusal and close wakeups.
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
