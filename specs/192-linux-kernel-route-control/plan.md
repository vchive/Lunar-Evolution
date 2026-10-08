# Plan

1. Define stable per-ABI syscall constants in the self-contained native
   isolation header, including fallback values for older libc headers.
2. Add the ten fixed `EPERM` rules to the existing intersecting seccomp
   filter. Do not broaden grants or change the v2 lifecycle.
3. Compile one disposable C target against the real header and assert the
   filtered refusal plus ordinary pipe/file compatibility on Linux.
4. Run focused tests, Ruff, compileall and diff checks. Linux CI remains the
   acceptance authority; Darwin skips do not prove syscall enforcement.
