# Plan

1. Preserve Feature175/176/177 tested heads; develop from exact PR11 head in a separate worktree.
2. Review current Python pass_fds and C fork/dup/exec lifetime. Add a Linux-only child handoff with
   a fixed-size sorted keep set and bounded close_range segments. Fail closed on unsupported calls.
3. Validate broker endpoint declarations and reserved aliases before any close/dup operation.
   Keep error reporting intact and CLOEXEC; preserve the original target FD behavior for fexecve
   and sealed-script reopen compatibility.
4. Advance the Linux default descriptor and formal early gate; keep old read-only loading/recovery
   and existing child-supervision negotiation. Do not alter binary control or frame schemas.
5. Add inert C integration and strict negative fixtures; run focused/static checks, independent
   review and final-head three-version CI with original XML. Merge only that passing exact head.

Root owns Python descriptor/formal gate, existing binding tests, exports, workflow, SDD and handoff.
The native owner owns C handoff and new FD integration tests. CI owners do not edit source.
