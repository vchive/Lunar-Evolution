# Plan

The read-only route audit is preserved at /tmp/lunar182-egress-gap-plan.md. Source
analysis identifies SysV IPC as a formal reachable candidate; actual Linux baseline
and denial evidence is still required. Ancillary socket APIs are a direct-header
boundary unless a formal outside socket source is demonstrated.

1. Extend native_producer_isolation.h with stable native architecture syscall constants
   when headers omit symbols; independently check x86_64/aarch64/i386 numbers. Keep
   audit architecture/x32 gates, existing intersecting filters and ordinary clone flags.
   Do not invent i386 native semop/time32 calls: ipc multiplex covers them.
2. Add explicit SysV and socket ancillary denies. A socketpair subfilter checks the
   full domain argument and permits AF_UNIX only; i386 socketcall remains refused.
3. Add the new capability to build/command known versions and old gate accept sets,
   then its own final early gate. Preserve v2 grant negotiation and original lifetimes.
4. Add static local C baselines/filtered refusals against private message queue/shared
   segment/semaphore state, direct socket ancillary transfer baselines and harmless
   internal socketpair/pipe/file/fork/thread positives. All IPC objects are create-only
   fixtures and removed by their parent in finally; no host object scans or real IDs.
5. Formal sealed native targets receive private IPC IDs through ordinary bounded argv,
   never extra socket FDs. Require normal ready/release/start/terminal with EPERM result
   and unchanged parent state. Preserve inherited-FD closure and broker regressions.
6. Retain dedicated ipc-control XML plus full current/archive/frozen logs in three Python
   versions. Independent source review, focused tests, Ruff, compileall, diff check and
   final-head Linux raw audit precede merge. Preserve first failures; never borrow181 CI.

Root owns selectors/caller gates/exports/specs/docs/workflow. A delegated C implementer
owns the header and new native IPC tests. Independent review avoids author self-review.
