# Implementation plan

1. Extend the self-contained Linux branch of `native_producer_isolation.h`:
   known Landlock ABI constants, actual version query, handled REFER/TRUNCATE and
   writable-only TRUNCATE grant. Preserve supported ABI validation before query.
2. Append conditional EPERM seccomp entries for chown/timestamps/xattr APIs.
   Include old i386 ownership aliases and utimensat_time64 where applicable;
   retain existing chmod behavior and no-read compatibility.
3. Add `test_native_input_mutation_isolation.py`. Real Linux targets probe the
   actual ABI, run unfiltered controls on disposable UID-writable files, then
   compare bound-input denial with no-read work-file compatibility. Independent
   host snapshots verify bytes, size, mode, uid/gid, mtime and xattrs. Narrow
   version-query injection proves ABI2/error failure branches before installation;
   old-header macro omission uses the real header and actual Linux ABI.
4. Retain focused permission, architecture, process-control and ordinary policy
   regressions. Run Ruff, compileall and diff checks. Record platform skips as
   skips; local Darwin results cannot establish Linux enforcement.
5. Add explicit new Linux artifact implementation/default and early formal
   admission gate in native_bootstrap/native_trusted_attempt. Command negotiation
   keeps the existing child flag for both historical and new implementations;
   read-only load/recovery retains historical descriptor scope. Add version/refusal
   units and update only the descendants fixture's expected default version.

Ownership: this slice owns the native isolation header, its new focused tests,
Feature 176 specifications, dedicated documentation, local descriptor/version
admission binding and its focused tests. Root owns shared exports, CI workflow,
HANDOFF and final integration. Separate
target-FD allowlist work must not overlap this header without coordination.
