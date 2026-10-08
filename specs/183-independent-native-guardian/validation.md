# Current validation boundary

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
