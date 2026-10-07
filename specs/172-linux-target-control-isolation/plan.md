# Plan

Modify only the Linux filter in `native_producer_isolation.h`. Test through a compiled local
fixture invoking the actual header; syscall probes use signal zero or fixture-owned identities.
Namespace clone probes must be refused before creating any namespace. Actual descendants remain
in the original group and can be stopped by their fixture supervisor.

Keep ordinary fork, vfork and pthread paths available, including clone3 ENOSYS fallback. Add the
focused module to early native CI and retained XML/annotations. Existing native/broker/scheduler
tests provide compatibility evidence. Full current/archived/frozen CI must pass at the final head.
