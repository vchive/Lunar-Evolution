# Linux target descriptor control

Feature179 extends Feature178's inherited-descriptor handoff. New Linux artifacts use
`native-bootstrap-linux-fd-control-v1`; formal attempts refuse older artifacts before staging,
budget persistence, nonce consumption or spawn. Historical read-only recovery keeps its scope.
Darwin retains its original implementation and receives no Linux descriptor-control claim.

The target inherits only the already-bound handoff descriptors. After Landlock and the existing
architecture/control filter, two additional intersecting seccomp filters apply:

| Interface | Admitted operations |
| --- | --- |
| fcntl / i386 fcntl64 | DUPFD, DUPFD_CLOEXEC, GETFD, SETFD, GETFL, non-async SETFL; POSIX/large-file/OFD advisory locks; GETLEASE, GETPIPE_SZ, GET_SEALS |
| ioctl | FIONREAD, FIONBIO, FIOCLEX, FIONCLEX |

Every other command/request fails EPERM. F_SETFL rejects O_ASYNC. Command/request upper words
must be zero; F_SETFL's flags also require zero upper word. Ownership, notification, leases,
pipe resizing, seal changes, devices/terminals and future requests cannot bypass the gate.
Ordinary nonblocking I/O, descriptor duplication and locks remain available. FIONBIO controls
nonblocking mode only; it cannot enable asynchronous notifications.

Tests use a private pipe and disposable blocked-SIGIO receiver for the unfiltered kernel
baseline, then verify the filtered child cannot arm that route. Actual native composition
uses a sealed C target, fresh anonymous broker pipes, original guard/deadline and host stdout.
The baseline proves the local signal mechanism; it is not an exploit against a user process.
The three-version Ubuntu matrix tests x86_64. i386-only tests are explicitly skipped there;
they are not i386 runtime acceptance evidence.

This closes a bounded control surface, not all descriptor authority or containment. Host
stdio identity, grant path/inode/overlap, runtime load protection, general egress and independent
stopping after bootstrap death/pause remain separate work. No receipt schema or publication
authority changes. Only local provider-free fixtures and existing GitHub CI are used.
