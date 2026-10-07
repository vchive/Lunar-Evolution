# Plan

1. Change only the Linux native child lifecycle: verified subreaper setup, bounded polling of
   adopted waitable children, guardian retention and final synchronous guard checks. Preserve the
   direct status and all existing target isolation and original-clock behavior.
2. Version the build descriptor and explicit formal command. Reject old Linux launch descriptors
   before attestation consumption or spawn. Leave old evidence readers and Darwin child-drain
   scope unchanged; apply common final guardian checks and terminal-write failure handling.
3. Add an independent inert-C descendants suite plus focused host compatibility and admission
   tests. Keep test faults at compile-time seams; production reads no bypass environment flag.
4. Run focused suites with Ruff, compileall and diff checks, independently review authority and
   terminal races, then require the final head's complete Ubuntu Python 3.11/3.12/3.13 matrix
   before the already-authorized merge.

Parallel ownership: C lifecycle; dedicated descendants tests; root Python build/command/formal
binding, specs, integration and release. All edits use the isolated worktree.
