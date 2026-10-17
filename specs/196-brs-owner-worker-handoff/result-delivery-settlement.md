# PB-03j — exact owner-result delivery and one-shot settlement

The private owner mailbox now has a follow-up to compose this envelope directly;
see [exact mailbox result composition](exact-mailbox-result-composition.md). A detached
callback settlement is separate from controller wave settlement and process cleanup.

This slice adds a provider-free result envelope for the private owner/mailbox bridge.
The owner projects the immutable transaction terminal journal into bounded canonical
bytes with the selected run, episode, mailbox request, selected request, handoff and
native preparation plan bound together. The selected worker can parse those bytes only
through the original `BRSOwnerPublicationResponse`; response identity and digest are
rechecked before any callback is invoked.

The payload carries the terminal status (`published` or `all_rejected`), journal and
terminal marker digests, resulting archive/state digests and admitted candidate IDs.
A published result must contain at least one admitted candidate; an all-rejected result
must contain none. A journal is accepted only when its run and task identify the
selected run and episode and its terminal state agrees with the result status. The
worker request envelope digest and the selected solver request digest are retained as
separate fields: they are different identities and must not be conflated.

`deliver_brs_owner_result` returns a `BRSOwnerResultSettlement` gate. Its callback is
consumed at most once. Callback failure transitions to `unknown`; no retry, fresh
owner, latest-head adoption or inferred success is provided. A duplicate settlement
is refused. The callback receives a detached immutable DTO and no owner, strategy,
workspace, ledger or publication capability.

The module does not create a mailbox, acquire a controller lock, perform a transaction,
write a ledger row, reconcile an unknown result or enable public native BRS. The online
owner bridge must still call it only after its own transaction readback and retained
preparation/owner checks. Real producer/evaluator, remote worker, distributed
ownership and remote evaluator paths are outside this feature.

Validation: `tests/test_rsi_python_brs_result_delivery.py` covers success and known
rejection delivery, request/handoff/preparation/journal drift, canonical and duplicate
settlement refusal, callback unknown semantics and transaction cross-binding. Focused
pytest, Ruff, compileall and `git diff --check` pass on the local inert fixture.
