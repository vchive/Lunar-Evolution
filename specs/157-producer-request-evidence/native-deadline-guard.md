# Native original-deadline guard

Feature 157/156 continuation, 2026-10-02. This is a narrow extension of
`native-controller-lifeline.md`, not a new execution or reconciliation protocol.

## Contract

- The formal attempt freezes its effective deadline after composing the intent, parent and
  optional RSI absolute deadline. Before preflight/attestation consumption it samples native
  monotonic nanoseconds **before** the caller clock and conservatively maps the remaining
  seconds once. Setup, gate waits and target execution consume this same budget. Neither
  command construction nor bootstrap reception may allocate another timeout.
- Formal commands pass `--deadline-monotonic-ns` together with the controller lifeline. A
  positive uint64 is required in the formal path; invalid configuration prevents readiness. Historical
  commands without a deadline remain direct fixture interfaces. An older runtime rejects the
  formal command rather than silently running without deadline supervision.
- Linux uses `CLOCK_MONOTONIC`; Darwin uses `mach_absolute_time` and its integer timebase,
  matching Python's native monotonic clock. Wall-clock changes cannot extend supervision.
  The caller clock is a trusted seconds clock; an injected clock is a local harness facility.
- The guardian starts before any control read and polls the original lifeline with bounded
  waits against the absolute deadline. EOF, unexpected data, errors or expiry stop only its
  own still-private session/group. A child checks the same deadline and lifeline before exec
  so a fork racing a guardian stop cannot start new work after expiry.
- Live cleanup retains the lifeline writer and the existing cleanup reserve. An independent
  stop does not manufacture a timed-out, cancelled, completed or successful receipt. Missing
  terminal evidence still requires read-only unknown recovery; no automatic retry is granted.

## Boundaries

The guardian exists only while bootstrap exists. The current terminal/exit/host-cleanup
handshake retires it on direct target completion. Descendants surviving bootstrap exit require
a separate child-exit/cleanup or platform-supervisor protocol and remain open. This slice does
not close malicious signal/session/namespace escape, full egress, machine-restart reconciliation,
external runtime ownership, real solver/campaign acceptance or all T156-05/06/09/12/14 gates.
Monotonic semantics and OS scheduling are retained; this is not a hard-real-time or suspend-time
budget guarantee. Stopping or suspending bootstrap itself can suspend its guardian.

## Validation

Use local compiled targets only. Test invalid Python/C arguments, expired and blocked-control
startup, pre-gate expiry, active target plus contained descendant expiry with the controller pipe
still open, and a formal attempt with only its controller suspended. The latter must stop the
native group at the original narrowed parent deadline and leave no fabricated terminal.
Recovery must preserve bytes/inodes/deadline and perform no signals, provider I/O or writes.
Keep normal completion, cancellation, broker, capture and native scheduler regressions passing.
Run focused pytest, Ruff, compileall, diff checks and final-head Ubuntu Python 3.11/3.12/3.13 CI.
