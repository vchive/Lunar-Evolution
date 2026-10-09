# Feature183 independent native guardian

Priority P0. Continue the existing original native lifecycle from Feature182; do not
redesign Lunar into a service or distributed scheduler. Source base is the exact
Feature182 tree affcde51, whose independent final CI/merge remains separately tracked.
This specification is not an implemented capability or launch authority.

The current pthread guardian stops with bootstrap SIGSTOP and disappears with
bootstrap SIGKILL. Target and contained descendants can therefore exceed the same
original deadline while the controller remains alive. A small independently scheduled
native process must observe the original controller lifeline and absolute monotonic
deadline and stop that original private group under bootstrap-only death/pause.
Bootstrap death should be observed with an original live pidfd; SIGSTOP does not
make a pidfd readable, so pause stopping is by the original deadline/EOF. Never claim
immediate pause detection or introduce a reception-time/heartbeat/reset deadline.

Keep original protected grants/controlv2, two FD closures, target process-control
restrictions, nonce, launch/intent/executable identities, attestation consumption,
registration/handoff/terminal/cleanup/stream/broker/receipt/publication schemas and
process-only outcomes. Retained records remain read-only; no recovery relaunch,
signaling/reap by recorded PID, replacement nonce or refreshed fingerprint is allowed.

Preserve kernel ECHILD target-tree drain with __WALL. Direct-child exit, waitpid0,
output EOF, a group probe or skipping a live guardian PID cannot establish completion.
Keep the independent watcher active through complete drain and guarded terminal
write. Normal success also requires exact guardian finish/ack and observed normal
exit/reap, plus existing bootstrap cleanup/output evidence; a terminal frame alone
does not suffice. All lifecycle waits consume the original execution deadline.
The host acknowledgement wait must support valid descriptors above `FD_SETSIZE`
with `poll(2)`. Readiness requires exactly `R`, one matching readable event with
no error or hangup, and the original deadline still valid before and after the
read. Integer-millisecond rounding must never renew the absolute deadline.

Every newly created process must have an exact live owner and reap path on startup,
normal exit, cancellation, malformed handoff, deadline/EOF, bootstrap SIGKILL before
handoff and startup syscall/allocation failure. An unannounced controller-child
zombie is an unresolved implementation gap, even if the attempt is marked unknown.
Do not use wait(-1) over unrelated controller children or reopen a durable numeric
PID to paper over it. Original owned pidfds may be used for their exact child only.

Internal guardian endpoints/pidfds/finish handles are bounded private native/host
objects, absent from target argv/env and durable authority. Validate pipe/socket
types, direction, non-ASYNC, original roles and all static/dynamic FD separation;
close target/bootstrap/grant/broker/stdio handles in the guardian as applicable.
The target inherits no guardian channel or descriptor. Catchable group teardown
signals must not destroy the watcher before it observes bootstrap death.

Linux-only capability/default and final guardian-required gate can be added only
after the complete native/host lifecycle is implemented. Preserve every older
earliest refusal before budget/input/nonce/spawn; historical/Darwin scope is unchanged.
Unsupported topology/kernel/ABI fails closed, without weaker automatic fallback.

Guarantee assumes the kernel schedules the independent guardian and the existing
target rules keep descendants in their original group/session. Privileged actors
stopping/killing the guardian itself or the entire group, uninterruptible tasks and
universal real-time kill latency are outside this bounded contract. No immutable
runtime, complete egress, external authentication or multi-host capability is implied.
Only inert local native/process/pipe/socket fixtures and existing CI are allowed;
no model, solver campaign, WebAgent, remote/company evaluator or credentials.

Frozen implementation topology: controller-owned second Popen watcher in a separate
session, original bootstrap pidfd with PIDFD_SIGNAL_PROCESS_GROUP=4, exact R/F/EOF/D
private pipes and actual normal watcher reap. See plan.md. CLONE_PARENT and numeric
PGID fallback are not selected. Unsupported group-flag kernels fail closed.
