# Native POSIX message queue control

Feature185 extends the Linux native target boundary to deny the six POSIX message
queue syscall families, including native i386 time64 send/receive. Queues address
shared IPC-namespace objects independently of ordinary path grants, so filesystem
policy alone does not establish refusal.

Feature185 introduced native-bootstrap-linux-posix-mq-control-v1. Later keyring
selectors retain these mq controls; current admission is documented in
native-keyring-control.md. Formal attempts
with only the preceding guardian selector fail with mq_control_required before
budget/input/nonce/spawn. Older refusal order, Darwin and historical read-only
load/recovery contracts remain unchanged.

The existing group pidfd guardian, R/F/EOF/D protocol, ECHILD drain, original held
grants, target FD closure, deadlines and durable records are unchanged. Ordinary
private pipes/files/UNIX socketpair/fork/thread and broker IO remain available.

Only inert exclusive mode0600 parent-owned queues are used in validation. Local
Darwin skips are not Linux evidence; exact final GitHub CI/raw materials are
required before main acceptance. This does not prove complete egress, keyring or
all other kernel routes, broker effective proxy/redirect destinations, immutable
runtime loading or distributed ownership.
