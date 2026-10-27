# Reserved terminal join: event and idle observations

The opt-in private reserved serial driver now supplies its existing owner hot
check to `BRSOwnerTerminalLifecycle.serve`. This applies only after the original
publication mailbox bridge returns, while its original worker completes terminal
re-observation. The generic selected-owner wait and default lifecycle behavior
retain their complete poll checks.

An empty join poll verifies exact retained session/transport objects, original
control identity, owner thread, cancellation, both original deadlines, run budget
and the live checkpoint through the existing reserved hot check. That check runs
outside the condition. Session and transport identity are checked again after
the callback, before touching the condition or Future. A foreign handle, failed
exchange or malformed event counters refuses without an acknowledgement.

Idle polls do not repeat the complete publication policy/history projection.
They cannot append evidence, publish results, acknowledge an event or settle a
root. A pending event still runs the original full caller check and `_drain`
including `_fixed`, before evidence/ACK. Future completion independently runs
the full caller check and owner gate even without a pending event. The original
tail drain remains outside the policy observation scope, followed by the same
mailbox close, executor join, complete event-history and persisted-result gates.

This changes the timing of drift detection only during an empty idle join:
policy, source and filesystem drift must still refuse at the next evidence or
Future completion boundary. No successful validation is cached. Each actual
complete observation retains its fresh ledger/filesystem reads. The new helpers
participate in the persisted finite policy graph. Neither deadline nor retry
allowance changes; this is not evidence that the 600-second mixed case passes.

Focused component tests use real threads, Futures and original execution control
with an explicitly incomplete owner graph. They cover idle no-ACK behavior,
full refusal before each event and completed Future, cancellation/deadlines,
callback handle replacement and default compatibility. Existing lifecycle,
reserved policy, completion and serial integration remain separate regression
gates. These fixtures provide no production or solver authority.
