# Feature 179 — Linux target descriptor control

Priority: P0. Status: implementation in progress, Linux final-head validation pending.

After Feature178 closes unexpected descriptors, target code can still call fcntl/ioctl on
allowed standard streams, executable and broker pipes. Explicit signal syscalls are denied,
but asynchronous file ownership/notification can request kernel-generated signals. Establish
this gap with a private local receiver and anonymous pipe before treating it as proven.

The Linux target seccomp boundary admits an explicit fcntl command set for ordinary descriptor
duplication, inheritance, status queries/nonblocking I/O and advisory locks. F_SETFL refuses
O_ASYNC. Ownership, notification, leases, sealing, pipe resizing and unknown commands fail with
EPERM. The fcntl64 entry receives the same gate on i386. Ioctl admits only FIONREAD, FIONBIO,
FIOCLEX and FIONCLEX; all other requests fail with EPERM. Compare full command/request words
before narrowing, preventing alternate encodings from bypassing the gate.

New Linux default/formal builds require native-bootstrap-linux-fd-control-v1 before budget,
input staging, nonce or spawn. Existing rejection order for older descriptors is preserved;
the Feature178-only descriptor receives a distinct fd-control-required rejection. Retained
historical load/recovery keeps its original read-only scope. Darwin gains no Linux capability.

Preserve the original handoff, subreaper, guardian, deadline, control/frames, broker journal,
receipt and publication protocols. Negative tests use only private anonymous pipes/regular
files and inert invalid requests, never user processes, devices or remote systems. Positive
tests exercise ordinary duplicate/nonblocking/lock operations and actual native broker pipes.

This is a bounded descriptor-control prerequisite. It does not close grant path/inode/overlap,
runtime sealing, arbitrary egress, host stdio authority, bootstrap death/pause supervision or
real solver production wiring. No model, WebAgent, remote/company evaluator, real campaign,
.env or credential access.
