# Native bootstrap controller lifeline

Feature 157/156 continuation, 2026-10-02. Extend the native bootstrap lifetime contract without
changing recovery's process-signal authority or inferring the provider/candidate outcome.

## Observed gap

The HTTP transport has a controller-owned lifeline, but the native bootstrap closes its gate
after release and then waits for the target. Python cleanup runs only while the controller is
alive. In a local reproduction with a two-second intent and ten-second target, killing only the
controller after authenticated `target_started` left bootstrap and target alive past the original
deadline. Read-only recovery correctly retained missing terminal/unknown evidence.

## Contract

- Formal `run_native_trusted_attempt` creates a private anonymous lifeline pipe. Only its reader
  is inherited by the trusted bootstrap; the writer stays in the controller and is retained
  through owner-checked cleanup. The target closes the reader before exec. Neither endpoint is
  offered through producer environment, filesystem, broker or journal interfaces.
- The bootstrap accepts an explicit controller lifeline descriptor. Before announcing ready it
  validates a read-only FIFO, distinct control/gate/frame descriptors, and its own fresh session
  and process-group leadership (`PID == PGID == SID`). Guardian setup errors prevent gate release.
- A guardian in the bootstrap monitors EOF/error on that original pipe. If controller death
  closes the writer, it stops its own group, including itself and contained targets. It never
  loads a PID from a file or selects a different group. Recheck its own group/session before
  stopping; this mechanism gives a later recovery caller no extra signal permission.
- Frame-write failure after controller death must not terminate the bootstrap through SIGPIPE
  before its guardian can stop the target. Setup, pre-exec and active-target failure paths must
  retain conservative cleanup and cannot yield formal success.
- Normal target completion and live cancellation keep the existing handshake, exit-code,
  original deadline and owner-checked cleanup semantics. The parent closes its writer during
  final cleanup; it must not race an unverified group stop ahead of live cleanup bookkeeping.
- The older direct bootstrap command without a lifeline remains a fixture interface; formal
  native attempts always provide the lifeline. A legacy binary cannot be treated as a guarded
  production runtime merely because it has a compatible historical descriptor.

Controller-only death cannot fsync a verified terminal. Missing terminal/cleanup/stream/broker
evidence remains `unknown`/`recovery_required`; guardian stop never fabricates cancelled, timed-out
or successful receipts, never publishes a candidate and never retries an execution. Absent or
zombie orphan observations do not prove recovery caller reaping or remote operation cancellation.

This slice stops targets contained in the original native group. Complete malicious producer
namespace/signal escape protection, machine restart and independently trusted successful
reconciliation remain separate acceptance work. `native-deadline-guard.md` extends this slice
with an independent original-deadline timer while bootstrap remains alive; formal attempts now
always pass that absolute native clock bound along with the lifeline.
The guardian is retired when the direct target completes and the bootstrap emits its terminal;
it does not supervise descendants after bootstrap exit. Live owner-checked cleanup retains its
existing conservative authority. The guardian thread polls the pipe and deadline; this slice does
not claim general POSIX async-safe behavior for every platform sandbox library called after fork.

## Validation

Run only local compiled C targets and trusted native fixtures. Kill the controller PID after
host-accepted start while the target is still active, and verify group members stop before any
fixture cleanup or original deadline. Exercise pre-start death, invalid/missing/duplicate lifeline
descriptors, descriptor inheritance, normal completion and live cancellation. Recovery must retain
original bytes/inodes/deadline and perform no new execution, provider I/O or success publication.
The native scheduler, broker and receipt/output/publication regression must still pass. Run focused
pytest, Ruff, compileall and whole-branch diff checks; require independent final-head Ubuntu CI.
