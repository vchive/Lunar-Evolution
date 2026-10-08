# Feature185 native POSIX message queue control

Priority P0. Continue Feature183 lifecycle without changing the frozen guardian
topology or public record schemas. POSIX message queues address shared IPC-namespace
objects through mq_* syscalls; ordinary path grants do not alone establish denial.
This slice denies the six native mq syscall families on x86_64/aarch64/i386 and the
i386 time64 send/receive entries. Older headers must not omit runtime entries.

Use actual Linux target seccomp enforcement. Denial returns EPERM for mq_open,
mq_unlink, mq_timedsend, mq_timedreceive, mq_notify, mq_getsetattr and the supported
time64 variants. No proxy syscall, new namespace, additional inherited queue FD
or compatibility fallback is admitted. Preserve ordinary private pipe/file/UNIX
socketpair/fork/thread IO, existing broker, original grants and descriptor closure.

Add Linux default/formal selector native-bootstrap-linux-posix-mq-control-v1.
Every existing earliest rejection remains unchanged; guardian-only descriptors
are rejected with native_trusted_attempt_mq_control_required before cancellation,
budget/input/nonce/spawn. Historical load/recovery and Darwin remain in their
original readonly/platform scope. No older descriptor is relabeled.

Tests may create only an inert parent-owned O_EXCL mode0600 queue with bounded
message length/count. Verify usable baseline, filtered syscall EPERM, unchanged
queue contents and clean parent-owned unlink on every path. Never attach to an
existing outside queue. Actual native CI, not Darwin skip or source constants,
must establish execution. Preserve raw failed runs alongside final evidence.

This is not complete egress/information-flow or runtime immutability. Other kernel
routes/keyrings and effective broker redirect/proxy destinations remain open.
No model, solver campaign, WebAgent, remote/company evaluator or credentials.
P2 distributed ownership/service/scheduler remains deferred.
