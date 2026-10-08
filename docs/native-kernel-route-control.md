# Linux kernel-global route control

Feature 192 adds a small, explicit deny boundary to the existing local native
producer isolation profile. `bpf`, `perf_event_open`, `userfaultfd`,
`fanotify_init`, filesystem-handle APIs, and mount namespace mutation are
unneeded by a producer and are reachable outside ordinary path grants, so the
filter returns `EPERM` for each family on the supported Linux ABIs.

The local C fixture uses only malformed zero-argument probes and a disposable
work directory. It also checks that ordinary pipes and declared file writes
still work. This is a bounded hardening slice; it does not establish complete
kernel containment or any distributed-worker capability.
