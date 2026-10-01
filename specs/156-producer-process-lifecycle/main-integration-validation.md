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

## Ubuntu cancellation correction

PR run [36846543906](https://github.com/vchive/Lunar-Evolution/actions/runs/36846543906),
head `0c5cc3a`, exposed seven Linux cancellation/timeout cleanup failures in Python 3.13. The
current phase executed 9,195 cases with 30 platform skips and no errors; archived 2,294 and
frozen 24 passed. Its failure remains recorded. Exact public annotations are retained locally
at `/tmp/lunar-linux-ci-cleanup-annotations-20261001.json`.

The cleanup primitive previously probed `killpg(pgid, 0)` without reaping its live caller's
direct child after TERM/KILL. Linux zombies retain their process identity, so a stopped child
could keep the group probe alive until cleanup returned unverified. Live launchers now supply
their exact child's nonblocking `Popen.poll` before every probe. The poll return never proves
group exit or grants signal authority; the existing group and ownership checks remain, and
recovery without the original handle receives no poll hook. Hook failures remain uncertain.
Neither exhausted budgets nor active descendants receive additional grace or permission.

Faster verified cleanup also exposed a scheduler classification race in the local native
focus: native execution stopped at the cleanup reserve, but the caller deadline had not yet
expired, producing `attempt_unpublishable`. Explicit native wall timeout now preserves the
original caller-budget exception when that ceiling is tighter; an independently tighter intent
ceiling has a fixed native timeout code. Unknown cleanup/broker/stream results still reject
publication. The original failed focus is `/tmp/lunar-cleanup-native-focused-20261001.xml`.

Final local checks: producer 79 passed / 2 Linux-only skips; related cleanup/diagnostics/runtime
84 passed; five native timeout suites 105 passed / no skips; final ownership + scheduler units
68 passed. Managed Python 3.11/3.12 producer hook focus each passed five cases. Ruff, compileall,
YAML structure and whole branch diff checks pass. CI now runs the native cleanup focus before
the full required runner and retains its JUnit artifact, to expose platform failures sooner.
A fresh PR head matrix is still required; these focused results do not relabel the failed run.

The installed wheel at the preceding packaging head completed mock DRS and BRS CLI runs,
read-only inspect and exact terminal replay without additional ledger writes. Validation used
an isolated temporary home and an explicit minimal environment; no model endpoint or key was
read. Evidence: `/var/folders/kt/ygjlhpbx6sq1mk2912c3fzt80000gn/T/lunar-installed-rsi-20261001-cidgj9lf/validation.json`.

The following early Ubuntu focus at `87ea0ce` (run `36851401335`) removed the six cleanup
failures, leaving one identical active-cancellation E2E failure across all three Python versions.
Its target-written marker could precede the host accepting the start handshake. Cancellation
at that interleaving correctly keeps the terminal unknown. The active-cancellation fixture now
waits for the original session method to validate `target_started` and for the actual marker;
all cancelled receipt, cleanup, no-request/no-publication assertions remain. A deterministic
negative interleaving verifies that a marker without an accepted start frame cannot create a
known cancellation terminal. Local E2E 13 and negative 1 passed; neither production permissions
nor unknown-result semantics were loosened. Exact early annotations are retained in
`/tmp/lunar-linux-ci-reap-annotations-20261001.json`.

The wheel rebuilt after the cleanup corrections matches all 170 runtime source/resource files,
and its sdist retains the native fixture helper. Its isolated installed CLI completed mock DRS
and BRS, inspect and exact terminal replay without additional ledger writes. Final wheel CLI
evidence: `/tmp/lunar-installed-wheel-cleanup-20261001-validation.json`.

At `aa66d89`, the Linux cleanup focus passed on Python 3.11/3.12. Python 3.13 only failed an
exact floating-point subtraction assertion: `133.55416034799998 - 125.554160348` is not exactly
the integer 8. The assertion now checks the original exact deadline construction
`deadline == started + intent_budget`, without tolerance or a production budget change. The
negative marker interleaving also waits for its complete bytes before cancelling. Final local
native attempt/E2E focus: 51 passed, no skips, report
`/tmp/lunar-native-handshake-final-20261001.xml`. A fresh complete supported matrix remains required.

The early focus at `121ba4e` passed Python 3.11/3.13, but Python 3.12 exposed a genuine
cancellation-composition budget drift: an unchanged 25-second allowance was reconstructed by
deadline subtraction as `24.999999999999986`. Its publication budget/journal fingerprint then
disagreed with the caller's original control during exact retry. Cancellation composition now
retains the original allowance when its effective deadline is unchanged, including equal/later
parent deadlines. A genuinely earlier parent still narrows the budget. The deadline/journal
identity check is not loosened. Eleven deterministic cases cover float boundaries, tighter
parents and actual prepared-journal retry. Five focused suites including all native E2E cases
passed 119 tests without skips; Ruff, compileall and diff checks passed. Report:
`.lunar-evolution/test-results/native-budget-composition.xml`. The failed Ubuntu annotation is
retained at `/tmp/lunar-linux-ci-121ba4e-annotations-20261001.json`.
