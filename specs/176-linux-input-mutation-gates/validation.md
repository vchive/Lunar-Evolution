# Validation

Local implementation is complete. Use only bounded local inert C/filesystem
fixtures. Actual Linux final-head CI and integration remain pending.

Required checks: actual Linux ABI>=3 TRUNCATE enforcement; narrow version-query
ABI2/error rejection without policy installation or continued execution; known
constant fallback with omitted old-header symbols; bound-input ownership/time/
xattr denial with independent host state comparison; no-read metadata and
work/output read/write/truncate compatibility; existing permission/control/
architecture regressions; Ruff, compileall and git diff --check.

Each mutation probe needs a successful unfiltered owned-file control. Do not
count O_RDONLY ftruncate EBADF, mode 0400 denial, unsupported xattrs/syscalls or
platform skips as filter evidence. Actual Linux CI remains required after local
Darwin validation. First failing XML must be retained without overwriting it.

## Local Darwin evidence (2026-10-08)

- First focus: 1 passed / 179 skipped / 0 failures / 0 errors, XML
  `/tmp/lunar-feature176-first-focus-20261008.xml`. The pass executes the actual
  unsupported-architecture header branch; all Linux mutation/runtime probes skip.
- Version/default and descendants compatibility focus: 32 passed / 201 skipped /
  0 failures / 0 errors, XML `/tmp/lunar-feature176-round2-focus-20261008.xml`.
- Expanded bootstrap/attempt/mutation/permission/control/architecture/version/
  descendants/policy focus: 81 passed / 211 skipped / 0 failures / 0 errors, XML
  `/tmp/lunar-feature176-round3-focus-20261008.xml`, 29.36 seconds. It includes 38
  actual Darwin native-attempt tests, 21 version/early-refusal units and Darwin
  compatibility fixtures. The 150 new mutation probes all skip on Darwin.
- Ruff, compileall and git diff --check pass. One initial Ruff RUF022 finding
  (module __all__ ordering) was corrected; no pytest failure occurred locally.

Later Linux-only legacy-number fallback additions do not alter the Darwin branch;
final static checks cover those changes. None of these local skips establish
Linux enforcement or ABI3 capability.

## Linux skip accounting and remaining acceptance

The new module collects 150 tests. On actual x86_64 Linux with ABI>=3 and working
user xattrs, expected native-ABI omissions are 28 skips: chown32/lchown32/fchown32/
utimensat_time64, each across current/old-header bound-input, bound-output and
no-read cases (24); raw_truncate64 across both headers and input/outside (4).
setxattrat/removexattrat deny cases are never skipped merely for kernel ENOSYS;
seccomp must return EPERM first. No-read modern calls may retain ENOSYS after an
unfiltered control confirms the same unsupported syscall. Actual i386/aarch64
must report their own syscall inventory, not reuse this x86_64 skip accounting.

The ABI2/1/0/error rejection fixture injects only the version query in the real
header and verifies no further ruleset syscall or no-new-privileges change before
exec continuation. It does not claim an actual ABI2 kernel was available. The
current/old-header enforcement variants query the actual kernel and install the
real Landlock/seccomp boundary. Missing kernel capability and filesystem xattr
support are explicit skips where applicable, never passed enforcement evidence.

Linux final-head CI must execute the new module plus existing input-permission,
control, architecture, descendants, bootstrap, formal attempt and release/current
regressions independently. Historical subreaper constant/load remains unchanged
in scope; new formal launch requires the input-mutation implementation before
budget, nonce or Popen effects. No inherited-writable-FD or complete containment/
egress claim is made.
