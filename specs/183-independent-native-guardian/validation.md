# Current validation boundary

## Bounded readiness follow-up (2026-10-09)

The host readiness wait now uses `poll(2)` instead of `select(2)`, preserving the
same absolute monotonic deadline and exact one-byte `R` protocol for descriptors
above `FD_SETSIZE`. It rejects error, hangup, invalid and ambiguous poll events
before reading, rechecks the original deadline before and after the read, and does
not create a second budget. The portable readiness fixture has 19 cases covering
high-numbered descriptors, valid/invalid frames, EOF, timeout, deadline expiry,
read errors and cleanup. The focused macOS run passed 19 cases with the existing
Linux-only guardian cases skipped; this is host-side evidence only.

The two early bootstrap fixtures now close their gate, frame reader and stderr
handles on every assertion path, preventing descriptor accumulation in a full
composition. The Linux workflow's dedicated guardian gate includes the 19 new
readiness cases and requires 82 total cases with zero skips, failures or errors.
The new source head still requires a fresh three-version Linux CI run and
independent raw artifact/source/tree audit before merge. The earlier PR29 failure
attempts remain preserved and are not treated as evidence for this fix.

Feature183 source is implemented on codex/native-independent-guardian and proposed
in PR18. It is not yet merged or accepted as a Linux production capability. The
branch was rebased onto main7031475 after independently audited PR15, PR16 and
PR17 were merged in order. Previous PR results do not establish Feature183.

Local final focused composition /tmp/lunar183-focused-final.xml contains149cases:
64passed,85Darwinplatformskips,0failure/error. It covers selector/gate compatibility
and existing lifecycle composition; native guardian execution remains Linux-only.
Ruff over src/tests/tools, compileall, git diff --check, strict Darwin C compilation
and workflow YAML validation passed. The workflow now retains a dedicated
independent-guardian.xml from host ownership and actual native protocol tests.

PR18 first run37721747456 at7191779 failed in the old grant-control fixture because
watcher Popen omitted a fixed cwd. The second run37722439330 atfb0bb5b failed because
the fixture required all Popen children, including the independent watcher, to
inherit grants. Head6a75fac distinguishes those roles: bootstrap inherits original
grants, watcher inherits none. These are separate failed source heads, not successful
retries. Original raw materials must remain available alongside subsequent evidence.

Third6a75fac/run37723098095 and AEC/run37723412200 produced17 actual guardian
fixture failures before cancellation: incorrect ps empty/Z+ handling and noncanonical
v2 grant order. Head9714bdb corrected those fixture contracts. Run37723854848 then
actually passed all63guardian cases with0skips, but the native-cleanup403 phase
failed one older cancellation cleanup-uncertainty reason assertion. The original
cleanup_unknown priority is now retained; the test also uses captured live original
ownership for finally teardown instead of reading durable IDs to signal/wait.
These partial successes are not complete source acceptance.

Final Linux three-version CI, source/tree/parents, case/skip inventories, raw XML,
logs and ZIP hashes remain required before merge. A platform skip, capability name,
terminal frame or previous PR's CI cannot establish independent stopping or reap.

The frozen topology and earlier bounded gap probes are retained at
/tmp/lunar183-independent-guardian-plan.md,
/tmp/lunar183-design-freeze-evidence.json and
/tmp/lunar183-guardian-probes-v3/current-pthread-results.json. Earlier Darwin
pthread probes establish the death/pause gap, not Linux guardian acceptance.

Remaining boundaries: Linux6.9+ actual pidfd flag4 support is required; no numeric
PGID or weaker fallback is provided. Paused bootstraps stop by original deadline
or owner EOF, not immediate pause detection. Guardian starvation or privileged
termination and uninterruptible kernel tasks remain outside the scheduling contract.
Complete egress and immutable Python runtime/load protection remain later slices.
