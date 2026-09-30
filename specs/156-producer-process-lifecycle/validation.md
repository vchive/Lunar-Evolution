# Feature 156 validation

## Active cancellation follow-up (2026-09-30)

The cooperative local runner accepts an optional process-local `cancelled` callback and observes it
before launch, after registration, inside the nonblocking capture loop, and during leader wait. A
verified owner-checked cleanup produces one durable `cancelled` execution receipt; cleanup
uncertainty remains `unknown`, and callback exceptions or non-boolean values fail closed before
spawn. Focused producer-process/lifecycle tests pass **81 passed, 2 skipped** after this slice.
This does not claim trusted bootstrap admission, host-observed requests, scheduler integration or
real producer acceptance.

## Cooperative preparation terminal checkpoint (2026-09-28)

`run_producer_lifecycle` now returns explicit terminal, cleanup, execution-outcome and deadline-scope
fields only after the process receipt is completed with zero exit, gate release, verified cleanup,
stable envelope evidence, and a matching durable terminal receipt chain. The focused provider-free
tests cover success, unknown terminal, unverified cleanup, missing envelope evidence, receipt-chain
drift and post-execution envelope replacement. The wall-clock deadline covers the process attempt;
the later bundle/draft/plan preparation is outside that deadline. This is supporting cooperative
preparation only, without trusted bootstrap admission, host-observed request enforcement, evaluator
execution or publication.

## Native process-terminal follow-up (2026-09-28)

The provider-free native attempt now persists a process-only terminal receipt after a known exit,
verified process-group cleanup, and durable cross-record bootstrap evidence. Its recovery reader
checks the exact registration/handoff/evidence chain and rejects receipt tampering. A missing
terminal permits only explicit owner-checked cleanup and an unknown recovery receipt, never a
replacement launch. The native attempt focused suite passes **13 tests** on Darwin, including a
live registered group left by an interrupted cleanup. This does
not close broader Feature 156 acceptance: stdout/stderr capture, result-envelope validation,
host-observed requests, and scheduler/publication integration remain open.

## Cross-feature lifecycle acceptance matrix (`2026-09-28`)

The provider-free lifecycle evidence is now indexed in the [acceptance matrix](acceptance-matrix.md).
It ties each Feature 156 process, capture, cleanup, receipt, and recovery case to an actual fixture,
and records the supporting Feature 157 broker and Feature 158 bootstrap boundaries separately from
the still-open production integration rows. `tests/test_lifecycle_acceptance_matrix.py` parses the
matrix and fails when a claimed fixture file or test function is removed. This is a traceability
and regression guard; it does not close T156-09, T156-14, T157-05/T157-06, or T158-04 and does not
authorize a provider or external campaign.

## Native bootstrap isolation supporting checkpoint (`15b8113`, 2026-09-27)

The Feature 158 native bootstrap now has an actual Darwin pre-exec sandbox integration test.
After the one-byte gate closes, the compiled target starts and exits zero, writes the declared
workspace, and receives an OS permission denial for an outside write, controller-secret read
and direct network connection. A live loopback listener with an unsandboxed positive control
ensures the network denial is not merely a closed port. The C `execve` uses the verified target
path independently of `argv[0]`. The sandbox grants dyld access to the root directory itself,
not its subtree, so startup can complete without granting controller-file access.

The five acceptance/native-isolation suites at this checkpoint pass **82 tests**, with no
failures/errors/skips; the report is
`.lunar-evolution/test-results/checkpoint-15b8113-focused/focused.xml`. Feature 158's specific
coverage and scope are recorded in its [validation](../158-trusted-producer-bootstrap/validation.md).
These are local controlled executables, not an external producer acceptance. No Feature 156
production runner, attestation consumption, formal registration, shared deadline, request broker,
cleanup/recovery or scheduler path is added by this supporting increment. Its open lifecycle
tasks therefore remain open.

## Post-crash cleanup acceptance (2026-09-26)

Explicit recovery cleanup is a separate operation from read-only inspection. The runner and
recovery must share a nonblocking, no-follow lifecycle lock so a live controller is never
mistaken for a crashed one. Recovery must validate the full claim-to-registration identity
tuple and the exact PID/PGID types before any signal. Each owner check must reread the durable
registration, match the lock file's registered device/inode, and match the current OS process
start identity. The lock device/inode is included in the registration digest, and legacy
registrations without it cannot authorize cleanup. Lock replacement while the old controller
still owns its flock, or immediately before a recovery signal, must fail closed. If the leader is gone while its
group remains, recovery has no continuous child observation and must not signal that group.

The cleanup result belongs in a create-only, fsynced recovery receipt chained to the
registration. It proves only the cleanup observation: missing stream/envelope evidence cannot
be promoted to successful execution, publication, or a fresh launch. Tests must cover live
controller contention, exact owner cleanup, reused PID/group, absent leader/group, signal and
probe uncertainty, registration tampering, duplicate recovery, and receipt write failure.

The focused producer-process, process-ownership, and trusted-bootstrap-runtime suites pass.
The complete provider-free three-stage regression passes: current **7453 passed, 6 skipped**;
archived **2294 passed**; frozen registration **24 passed**. Ruff, compileall, and diff checks
pass. No provider, external producer, scheduler, WebAgent, or real campaign was run. The fixture's
ordinary wall-clock budget is five seconds so file replacement assertions remain deterministic
under the full suite; the dedicated timeout fixture retains a one-second budget.

This increment does not close T156-06 by itself. Trusted bootstrap integration, host-observed
request enforcement, complete lifecycle fixtures, and external producer admission remain open.

## Owner identity checkpoint (2026-09-25)

The local runner now records an OS-observed process start identity in its durable registration
before gate release, repeats it in the terminal receipt, and rejects a mismatched identity before
in-process cleanup. If identity becomes unreadable, the live controller may retain cleanup authority
only after reaping its child and confirming the leader PID is absent; a reused visible PID is denied.
Darwin reads microsecond start time from `libproc`; Linux records the boot ID and `/proc` start tick.
Recovery checks the registration-to-receipt binding but remains read-only:
there is no post-crash owner-checked cleanup or terminal recovery receipt yet. T156-06 therefore
remains open, as do trusted bootstrap integration and byte-bound execution on other platforms.

The owner-identity and Feature 156/157/158 focused suites pass **133 tests**. The final code also
passes the full offline repository suite, Ruff, compileall, and diff checks. No provider, external
producer, scheduler, or campaign was run.

Validation is provider-free and uses short local fixture executables only. No external producer,
provider, evaluator, WebAgent, or campaign is started.

| Area | Required evidence |
| --- | --- |
| Attestation consume-once | Exact tuple, intent digest, executable bytes/size/inode/timestamps, schema, nonce, and self-digest are required. Replay, duplicate claim, altered claim, and uncertain claim state fail before spawn. |
| Process creation | `Popen` receives an argument vector, `shell=False`, `start_new_session=True`, `close_fds=True`, closed stdin, derived cwd, and no credentials or shell control text. |
| Registration gate | Child cannot perform work before a durable registration receipt records exact PID/PGID, owner identity, intent, attestation, and executable evidence. Gate or registration failure is never treated as successful execution. |
| Deadline and budgets | One monotonic deadline covers gate, process wait, pipe drain, cleanup, and envelope read. Request count, output bytes, and wall time remain independent and cannot be reset by retry or recovery. |
| Capture | Concurrent stdout/stderr draining handles full pipes without deadlock; each stream is bounded and records only byte count, digest, and truncation/status. |
| Cleanup | SIGTERM/SIGKILL is preceded by exact owner checks and uses existing process-group cleanup. Reused PID/PGID, failed liveness, callback failure, or unverified cleanup yields terminal unknown/recovery-required evidence. |
| Envelope evidence | No-follow ancestor/file checks, regular single-link requirement, size bound, before/after identity, stable bytes, and canonical digest are all verified. Replacement, symlink, truncation, append, parse, or read uncertainty is rejected or unknown according to observability. |
| Durable receipts | Every bounded receipt is fsynced and atomically committed; previous receipt digests prevent overwrite. A controller interruption leaves an inspectable terminal or recovery-required record. |
| Recovery | Recovery inspects and may clean only the exact registered group. It cannot consume another nonce, widen budgets, alter intent, reinterpret output, or relaunch. |
| Regression | Focused lifecycle tests, Ruff, compileall, diff checks, and the full project offline suite pass. Existing automatic solve and scheduler defaults remain unchanged. |

The focused matrix must include: successful gated completion; a hostile pre-gate side-effect
fixture; child exit before gate/broken gate delivery; nonce replay; tuple and executable
identity drift; shell/credential rejection; registration write failure;
full stdout/stderr pipes; deterministic output overflow, including simultaneous stdout/stderr
overflow; wall timeout; PID/PGID ownership loss;
SIGTERM/SIGKILL uncertainty; controller interruption; symlinked/replaced/truncated envelope;
unstable receipt writes; recovery with no automatic relaunch; and a replacement exactly between
the final executable check and process creation that cannot execute un-attested bytes.

The current provider-free matrix includes simultaneous stdout/stderr overflow without deadlock,
explicit shell/session/stdin/environment assertions, and a hostile executable that writes a durable
side effect before reading the gate. The hostile case is intentionally negative evidence: the
ordinary runner cannot prove pre-gate non-execution, so it does not satisfy T156-12 or T158-04.

## Implementation checkpoint (2026-09-24)

The local runner now claims the nonce once across the workspace, revalidates launch identity,
starts a cooperating fixture without a shell and with a fixed non-secret environment, records
PID/PGID before gate release, bounds stdout/stderr and wall time, verifies the result file through
a held no-follow directory descriptor, and atomically publishes a chained terminal receipt.
Recovery verifies the claim, registration, and terminal receipt without relaunching. The focused
provider-free matrix covers gate order, cross-batch nonce replay, executable drift, nonzero exit,
request and output limits, timeout, envelope/directory replacement, registration/terminal write
failures, duplicate JSON keys, and recovery tampering. The focused matrix has **31 passing tests**.
The final offline repository regression has **7345 passed, 1 skipped**; Ruff, compileall, and
`git diff --check` pass.

This was not yet the full acceptance matrix. Request-level timeout was a declaration to the
producer and could not be enforced inside an arbitrary executable by the parent process. A
non-cooperating executable could do work before reading the gate. At this checkpoint Darwin
used a private immutable snapshot, while Linux and other non-Darwin platforms still re-opened
the executable by pathname between the final identity check and `Popen`. The default scheduler
did not call this runner.

The descendant cleanup gap is now addressed for descendants that remain in the registered
process group. The runner cleans that group when the leader exits and retains the first cleanup
evidence; fixture tests cover inherited pipes, redirected pipes, and a descendant that ignores
SIGTERM. A descendant that leaves the registered group remains outside this ownership contract.

The macOS local probe confirmed that a shebang fixture cannot be launched through `/dev/fd` even
when the verified descriptor is inherited by the child. `fexecve` and `execveat` are unavailable
through the local Python/libc interface. Darwin now uses a private immutable executable snapshot;
the replacement-after-final-check fixture verifies that the snapshot bytes run and that a failed
immutable lock rejects before spawn. Linux uses a sealed memfd inherited across `Popen` and
executed through `/proc/self/fd`; other platforms retain the `pathname_unbound` prototype.

## Linux byte-bound launch follow-up (2026-09-25)

The Linux runner now holds a sealed memfd through `Popen` and passes it in `pass_fds` along with
the registration gate. The actual Linux fixture replaces the source path inside the `Popen`
callback, after the runner's final identity check. The original shebang script still completes,
the registration and terminal receipt bind its digest as `linux-sealed-memfd`, and the parent
descriptor is closed after process creation. An unavailable Linux binding rejects before spawn
after the one-time attestation has been consumed. The focused Linux producer-process and binding
suites passed with **46 passed, 2 skipped**; Ruff, compileall, and diff checks passed locally.
The Darwin focused suite passes with the Linux-only tests skipped. This closes the Linux pathname
replacement window, but external admission remains blocked by the trusted pre-gate bootstrap and
host-observed request enforcement; other platforms remain pathname-bound prototypes.

## Deadline and fault-injection follow-up (2026-09-24)

The cleanup primitive now accepts one absolute monotonic deadline. SIGTERM grace, SIGKILL
grace, and the final leader wait are all clipped to that deadline; a post-deadline live group
is reported as `cleanup_unverified` rather than extending the attempt. The trusted bootstrap
fixture passes that same deadline through both normal and exceptional cleanup paths.

The capture evidence path retains and hashes exactly the in-budget prefix when one non-blocking
read crosses the stream ceiling; the receipt still records a saturated `limit + 1` observation
and `truncated=true`. Process waits use a zero-clamped remaining timeout, so an exhausted wall
deadline cannot add an extra wait interval.

The focused process-ownership, producer-process, and trusted-bootstrap-runtime suites pass.
New fixtures cover capture-read failure, SIGTERM failure, SIGKILL failure, cleanup uncertainty
projection, owner-loss without a direct fallback kill, child exit after registration but before
gate release, broken gate delivery, and a two-phase cleanup that cannot exceed the absolute
deadline. T156-13 is complete; T156-09's broader lifecycle matrix remains open.

At this checkpoint T156-05, T156-06, T156-09, T156-11, T156-11b, T156-12, and T156-14 remained
open. T156-11b is now complete for Linux as recorded above. The trusted bootstrap is still
fixture-only, and controller-owned request evidence is not yet connected to the runner.
