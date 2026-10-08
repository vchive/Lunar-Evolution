# Feature 192 — Linux kernel-global route control

## Goal

Close a bounded set of kernel entrypoints that are reachable without a path
grant or inherited descriptor. The local producer contract has no use for
eBPF, performance counters, userfaultfd/fanotify, filesystem handles, or mount
namespace mutation. The Linux isolation filter therefore rejects those syscall
families with `EPERM` before argument validation.

## Contract

- Refuse `bpf`, `perf_event_open`, `userfaultfd`, `fanotify_init`,
  `name_to_handle_at`, `open_by_handle_at`, `mount`, `umount2`, `pivot_root`,
  and `chroot` on x86_64, AArch64 and native i386 syscall tables.
- Keep ordinary pipe, file, fork/thread, broker and declared grant behavior
  unchanged. This feature adds no inherited FD, public numeric FD, wire,
  registration, deadline, or recovery field.
- Return fixed `EPERM` for malformed probes as well as valid calls. The test
  fixture uses zero arguments and disposable local output only; it never
  creates or inspects a host kernel object.

## Boundary

This is one deny-list hardening slice. It does not claim complete Linux
containment, network isolation, runtime immutability, remote worker
authentication, or multi-host ownership. Remaining kernel families need their
own contract and acceptance evidence rather than being inferred from this
list.
