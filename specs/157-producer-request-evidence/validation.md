# Validation

The optional native broker path was checked on a local loopback HTTP fixture with a
compiled isolated target. It sent one request through inherited anonymous descriptors;
the controller attached a host-only credential, journaled admission and completion, and
returned the response. The target saw no credential. A duplicate JSON key was rejected
before provider I/O, and a second request over the registered budget produced no second
provider call. The existing native attempt suite remains green.
If the protected journal cannot initialize, the native release gate stays closed and
the target never starts.

The terminal receipt remains `process_only` and `publication_eligible=false`. These tests
do not establish a recovery-safe broker receipt, complete Feature 156 lifecycle, scheduler
integration, external producer acceptance, or real-provider performance.

## 2026-10-01 formal receipt handoff

When the native stream, envelope, broker, deadline, target-binding, and cleanup evidence all
verify, Feature 156's formal `execution-receipt.json` records the broker coverage summary. A
provider-free publication regression supplies its digest to Feature 153 and confirms that the
publication journal preserves it; missing or invalid receipts are rejected before any stage
write. The process-only terminal remains diagnostic, and this handoff does not close the
recovery-safe transport or complete-egress requirements in T157-05/T157-06.


## 2026-10-15 strict GCC compilation compatibility

The existing native bootstrap and static isolation fixtures failed strict compilation
on the new Ubuntu 26.04 host. Explicit GCC 11.5, 12.5, 13.4, and 15.2 invocations all
reported `-Werror=misleading-indentation` at the same three project-source statements:
the regular-file isolation rejection, SHA message-schedule loops, and final exit-status
branches. Each invocation used only `PATH=/bin:/usr/bin` and `LANG=C`; this was not a
missing static libc dependency or an injected compiler flag.

The correction only puts the existing consecutive statements on separate lines.
Removing whitespace yields identical source bytes before and after, and no warnings,
`-Werror`, hardening flags, permissions, or runtime gates are relaxed. The unchanged
production compile command and an existing static mutation fixture both compile with
explicit GCC 13.4 and 15.2, with empty stderr.

A Linux regression now explicitly selects GCC, builds with the existing production
flags, and verifies the resulting descriptor through the normal artifact loader. It
skips with an explanation only when GCC is unavailable. The bootstrap, descendant-drain,
and selected static input-isolation tests collected 53 cases: 51 passed and the two
Darwin-only cases skipped on Linux, with no failure or error (28.337 seconds).
Ruff, compileall, and `git diff --check` passed.
Original failing compiler stderr, exact argv/version/realpath records, corrected build
records, and the raw focused XML are retained in ignored local reports. The raw XML
SHA-256 is `dcefc3ba7a7b2dba62074c32ca76ef779ef9b330d2b0da55ce2fde18567643ba`.
This is a provider-free compiler portability check, not full release or producer-runtime
acceptance; `production_admission=false` remains unchanged.
