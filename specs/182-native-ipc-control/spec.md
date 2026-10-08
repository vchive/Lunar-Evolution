# Feature182 native IPC controls

Priority P0. Continue Feature181 in a separate worktree with both fixture repairs; the inherited
committed tree matches repaired head fbd982e/tree486ea847 before this feature.
Feature181 final CI and merge remain independently tracked.
The target still uses the host IPC namespace; SysV objects can be addressed by numeric
ID without inherited FDs or socket/connect. Close that concrete candidate route and
omitted socket ancillary-message APIs through the real Linux seccomp header.

New Linux formal/default descriptor: native-bootstrap-linux-ipc-control-v1. Preserve
older refusal order, then reject grant-objects-only before budget/input/nonce/spawn
with native_trusted_attempt_ipc_control_required. Existing controlv2, grant binding,
original object checks, lifeline/deadline/drain/FD controls and all durable schemas
remain unchanged. Historical read-only load/recovery and Darwin retain their scope.

Deny SysV shmget/shmat/shmdt/shmctl, msgget/msgsnd/msgrcv/msgctl, semget/semop/semctl/
semtimedop, i386 ipc multiplex and semtimedop_time64 with EPERM. Deny sendmmsg,
recvmsg/recvmmsg and i386 recvmmsg_time64 to prevent omitted ancillary FD transfer.
Allow internal AF_UNIX socketpair with an exact domain argument; deny other domains
and high-word domain encodings. Existing i386 socketcall remains denied; source
tables do not imply native i386/ARM execution coverage.

Keep pipe/ordinary file/broker/stdout IO, work/output writes, fork/threads, sealed
target execution and descendant drain usable. Ordinary permitted writes are not an
unauthorized endpoint. Socket-message fixtures with deliberately inherited outside
sockets are direct-header evidence; the formal launcher supplies no outside socket.
Formal SysV tests use only private parent-owned mode0600 objects and numeric IDs,
and must prove original bytes/state are unchanged after rejected access.

This bounded slice does not claim complete egress or information-flow isolation.
POSIX message queues/other kernel routes, effective broker redirect/proxy destinations,
runtime load protection and independent bootstrap death/pause stopping remain outside
this slice. No service, multi-host ownership, real model/solver/campaign, WebAgent or
remote/company evaluator is introduced. Do not read .env or credentials.
