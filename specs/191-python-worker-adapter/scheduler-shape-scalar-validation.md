# Scheduler input scalar validation

The retained whole-case profile records 27,768,397 calls to the scheduler-input
shape walker (7.559 self / 10.261 cumulative seconds). These historical,
overlapping timers identify a local cost; they do not establish current Linux
wall time or explain the failed mixed run.

Inline validation of exact scalar leaves in the existing live iteration. Each
occurrence still consumes one node and retains the depth-48 boundary, string
length, integer bit length and finite-float checks. Dictionary keys are visited
before values, following the existing all-keys exact-string precheck. A key
which is no longer an exact string at visitation takes the original recursive
path. Containers, DTOs and foreign types also keep their recursive path.

Do not copy containers or cache shape results. Preserve cycle refusal, empty
containers at depth 48, dynamic DTO field/instance attribute checks, callback
and exception order, and every fresh call made by the scheduler. No SQL,
filesystem, source, policy, control, request budget or timeout gate changes.
The original recursive function extracted from commit `64ec3f54` is the
independent differential oracle; its recursive global is bound to itself.

Validation requires old-product boundary tests before implementation, the same
tests plus existing scheduler-input tests after implementation, a pure-memory
actual-function differential probe and alternating local timings. Timing is
recorded as diagnostic evidence, never an assertion or a mixed-case pass.

## Candidate observation

A 20,731-byte synthetic payload retains all 1,737 node occurrences while
reducing recursive entries from 1,737 to 88. Nine alternating blocks of 300
calls have a median candidate/old elapsed ratio of 0.772826. A separate initial
480-case depth/node-budget differential has zero mismatches. Evidence is in
primary ignored `release-closeout-20261025/scheduler-shape-candidate-1d57zwku/`.
This does not replace the focused union, final-source Linux mixed or full CI.

The 59 fixed-oracle boundary tests passed on both the old product and the first
candidate, with zero failures/errors/skips. The candidate run took 1.6443 seconds
and retained JUnit plus unchanged source/test pins in primary ignored
`scheduler-shape-independent-focused-4i14pd55/`. The final float-condition lint
rewrite is covered by the integrated union, which is still pending here. Final
Ruff, compileall and diff checks pass.
