# Main integration — 2026-10-01

The integration target is `main`, not `master`. The original feature head `f40679d` is 81
commits ahead of `d88e098`, with no commits behind and no merge conflicts. The reviewable change
is [PR #1](https://github.com/vchive/Lunar-Evolution/pull/1). Pushing the feature branch does not
merge it; the PR stays a draft until the supported Ubuntu/Python matrix passes.

## Integration corrections

- Deterministic native draft run allocation uses held no-follow directory descriptors for
  creation, permissions and sync. It verifies parent/run/child device and inode identities;
  active replacement cannot redirect writes or chmod outside the allocated tree.
- The native bootstrap accepts a Linux anonymous zero-link target FD only with all four
  required seals. Ordinary unlinked files, incomplete seals and pathname hardlinks fail closed.
- Landlock exact regular-file read/execute rules omit the directory-only `READ_DIR` right.
  Linux C fixtures are statically linked; no dynamic external runtime allowlist is added.
- The cooperative producer test expects exactly the gate FD and, on Linux, the sealed executable
  FD. The handoff test restores its OS-operation guard before filesystem assertions and pytest
  reporting, fixing the observed Python 3.11/3.12 JUnit crash.
- PR CI cancels superseded runs. The same current, archived and frozen regression phases and
  Python 3.11/3.12/3.13 matrix remain required.
- The source distribution explicitly retains the native target fixture helper imported by its
  included tests; setuptools' default `test*.py` selection otherwise omits underscore helpers.

## Local evidence and limits

The full required runner was started at `f40679d` before integration edits. Current collection:
9,179 cases; 9,171 passed, 7 platform skips, one preparation auditor-preflight failure. The
runner correctly exited 1. The unchanged failed node subsequently passed alone, and the whole
preparation-recovery file passed 48 cases. Its original preflight fixture budget was 3 seconds;
the failed test took 4.049 seconds. This indicates load sensitivity but does not reconstruct an
exact lost process status.

Archived verification passed all 2,294 historical cases with exactly 24 frozen registration
deselections. Frozen verification separately passed all 24 registered cases. Original bytes,
collection digests, import origins and isolated editable environments were verified; no old
source/test pins were changed. Reports: `/tmp/lunar-merge-runner-20261001/`.

Integration focused runs include 76 producer/native passes, 17 final draft-allocation passes,
74 native passes plus 8 Linux-only skips, 75 cooperative process passes plus 2 Linux-only skips,
and 100 passes each on managed Python 3.11 and 3.12 for handoff/bootstrap/allocation. A combined
183-case run had 172 passes, 10 Linux skips and one scheduler fixture request uncertainty: its
one-second broker budget expired without a completed journal row and the target exited 12.
The exact node passed in isolation. The scheduler fixture now allows five seconds per loopback
request inside its unchanged 12-second native wall budget. Dedicated deadline/cancellation and
unknown-recovery assertions remain intact; HTTP timing regressions keep their own explicit
budgets. Failed original reports are retained rather than relabeled as successful full runs.

The final scheduler E2E run passed all 13 cases in 17.75 seconds. Exact final inventory
reconciliation covers all 9,195 current node IDs: 9,180 passed, 15 expected Darwin skips,
zero latest failures/errors, and no missing/extra identities. The original full runner and
combined focus failures remain in the chronological record. This is a starting full run plus
final focused reconciliation, not one immutable final-tree zero-failure run.
Reports: `/tmp/lunar-e2e-merge-worker-budget-20261001.xml` and
`/tmp/lunar-merge-runner-20261001/final-reconciliation.json`.

This does not substitute for a clean Ubuntu matrix on the PR head. Ruff, compileall and the
whole integration diff check must pass before push. No real model, WebAgent, remote evaluator,
company platform, external OpenEvolve/Shinka campaign or secret configuration is accessed.

## Merge and release boundaries

Merge readiness requires the current PR head's checks and no unresolved conflicts. Official
evaluator/model acceptance, authenticated external project launch/runtime/dependency policy and
real campaign acceptance remain separate release work. Trusted local SQLite is not a remote
lease service or protection against historical database rollback; optional local RSI APIs do
not claim those properties.
