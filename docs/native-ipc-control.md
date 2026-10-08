# Native IPC controls

Linux producers run in the host IPC namespace. A target can address a SysV shared
memory segment, message queue or semaphore by numeric ID without opening a file or
inheriting a socket. `native-bootstrap-linux-ipc-control-v1` closes those API routes
through the real seccomp header; it is the new Linux build/formal-attempt capability.

The filter refuses `shmget/shmat/shmctl/shmdt`, `msgget/msgsnd/msgrcv/msgctl` and
`semget/semop/semctl/semtimedop` with EPERM. Native i386 also refuses the `ipc`
multiplexer and its relevant time64 entry. Explicit native ABI numbers keep the
policy effective when libc headers omit the syscall names; independently retained
Linux tables and compile-time comparisons validate the numbers. These source checks
do not establish execution coverage on ARM or i386.

The filter also refuses `sendmmsg`, `recvmsg`, `recvmmsg` and i386
`recvmmsg_time64`, complementing the earlier socket and `sendmsg` denials. This
prevents omitted ancillary-message APIs from transferring descriptors. An
intersecting filter permits `socketpair` only for the exact full-width AF_UNIX domain
argument. Private byte communication over an AF_UNIX pair, ordinary pipes/files,
fork, threads and the existing producer pipe broker remain usable. The old i386
`socketcall` denial remains in effect.

The formal entry accepts the new selector in all earlier capability gates, then
rejects a grant-objects-only descriptor before budget persistence, input staging,
nonce consumption or spawn. Historical loading and recovery stay read-only and
retain their original scope. Original grants, private control v2, FD closure, child
drain and lifeline/deadline/receipt/publication protocols are unchanged.

Tests create private mode0600 IPC objects owned and removed by the fixture parent.
They compare unfiltered baselines, filtered refusals and sealed v2 native launches,
checking the parent's original bytes/state. Direct-header socket fixtures deliberately
inherit local socket peers to test descriptor transfer; the formal launcher does not
supply outside sockets. Useful IO and original FD closure have positive coverage.
Existing CI retains `ipc-control.xml` and full current/archive/frozen results.

This is a bounded IPC capability. It does not establish complete egress or
information-flow isolation. POSIX message queues, other kernel routes, effective
HTTP broker redirect/proxy destinations, immutable runtime/load protection and
independent stopping after bootstrap death/pause require separate work. No service,
multi-host ownership or remote evaluator is introduced.
