# Feature 172 — Linux target control isolation

This P0 slice narrows the existing Linux target seccomp policy. The trusted bootstrap and host
controller stay outside the target filter. Ordinary cooperative fork/thread work remains allowed.

## Contract

- Reject target `setsid`, `setpgid`, namespace creation/joining, cross-process signals and memory
  access/FD duplication, and unused io_uring syscall entrypoints. Signal restrictions include
  queued-signal entrypoints as well as kill/tkill/tgkill/pidfd APIs.
  This prevents those direct escape/control APIs.
- Legacy clone remains available without namespace flags; reject namespace flags. Return ENOSYS
  for clone3 so supported libc can fall back to the filtered legacy clone path.
- Reject x32 syscall-number encoding on x86_64 and i386 socketcall multiplexing. Keep the existing
  architecture check and fail-closed installation behavior.
- Preserve native source/artifact digest binding. An old retained runtime is not relabelled with
  new capability. No control-frame, deadline, registration or recovery protocol changes.

## Boundary

This is a deny-list hardening, not complete containment or egress. Bootstrap retirement after
direct target exit, descendants tree-drain, independent original-deadline pins for missing-terminal
recovery and trusted unknown settlement remain open. No multi-host ownership or service is added.
Darwin policy is unchanged; local Darwin skips cannot prove Linux syscall enforcement.
