# Validation

## Fresh real-acceptance materials and preflight (2026-09-27)

The new Feature 142 case builder and 20 committed material files retain the prior effective
`openai-compatible` / `glm-5.2` / `chat_completions` request identity, exact task and
`{"limit":3}\n` input, independent evaluator/profile criteria, and eight actual probe snapshots
with expected judgments. The task and input SHA-256 values match the historical record. Criteria
digests are preregistration identities; the generated Python evaluator/profile must receive
separate runtime digests and an independent comparison during preparation.

The read-only registration preflight now checks all four primary and sixteen holdout materials
against tracked, regular Git blobs and the current bytes. Product files and materials have an
8 MiB limit; manifest/seal remain 128 KiB. It pins one HEAD for blob comparisons and rechecks
the checkout after reading. Focused registration/case tests **78 passed**, including committed-symlink
masking and checkout-change tests. The native offline E2E profile again passed **224/224**, with
zero failures/errors/skips; old protected pytest temporary snapshots emitted 2817 cleanup warnings.
Ruff, compileall, SDD prerequisites and diff checks pass. This preflight still trusts the local
`origin/main` ref. A real launch runner must independently verify the remote commit and atomically
claim the new root before any provider call. No fresh registration, root or real attempt exists yet.

## Repeatable offline native E2E (2026-09-27)

`tools/run_tests.py --suite native-e2e --junit-dir ...` now selects seven current-product suites
without archive/index/environment setup. Default and explicit `--suite all` retain the original
three-stage release path. The focused path verifies this checkout's imports, isolates pytest
selection/plugin settings, collects a nonempty unique inventory, requires every selected file to
contribute tests, and checks exact JUnit accounting. It clears a stale profile report before
preflight so import/collection failure cannot leave an old success report as current evidence.
Skips remain separately visible and are not executed successes.

The final seven-suite profile passed **224 tests**, **0 failures/errors/skips**, in **85.21s**.
Coverage includes actual foreground/background CLI coordinators and loopback HTTP, automatic
multi-file preparation/generation/execution/scoring/parent delivery, waiting input/answer/resume,
cancel/deadline terminal precedence, real runtime/tool timeout and descendant cleanup, killed
worker recovery, and wheel installation outside the checkout. The complete runner suite passed
**46 tests** in **6.09s**, including 12 added routing/collection/report/skip boundary cases and
existing archive/frozen identity checks. No `src/` product bytes changed in this runner extension.
Reports are retained in `.lunar-evolution/test-results/native-e2e-20260927-final/` as
`native-e2e.xml` and `runner.xml`; the tested working tree was based on `0f1a221`.

The standalone `specs/112-automatic-bundle-evaluator/quickstart.py` also passed: four independently
scored candidates **1/2/6/7**, selected and delivered **7**, one delivery copy, and unchanged
contract/compiler/auditor/generation/execution counts after terminal resume. Its inspectable
workspace is `/private/var/folders/kt/ygjlhpbx6sq1mk2912c3fzt80000gn/T/lunar-auto-bundle112-janfj58p`.
The Phase C fixtures separately use 1/2/999-invalid/9; their delivery checks select 9. These are
different offline fixtures, not model quality measurements.

The first 187-test invocation and final default-temporary-directory runs reported 2780 pytest
garbage-removal warnings from old immutable producer snapshots retained by earlier fault tests;
the selected suites passed and did not create those snapshots. A separate 187-test native profile
in a fresh temporary root passed without warnings in **84.92s**. The complete runner suite first
reported **45 passed / 1 failed** under that longer custom `TMPDIR`; its immutable historical
console identity check rejected the installed launcher. The unchanged check passed in the default
environment, followed by the final **46 passed** suite. No historical guard or evidence was
modified. These intermediate observations remain distinct from the final results.

The complete three-stage release runner returned **exit 0** against this working tree:
current **7586 passed / 7 skipped**, archived **2294 passed**, frozen registration **24 passed**;
all stages report **0 failures/errors**. Its separate reports are
`.lunar-evolution/test-results/native-e2e-release-20260927/{current,archived,frozen123}.xml`.
The historical runner verified its fixed collection/hash and manifest pins before and after the
tests. The skip count and pytest warnings from old protected temporary snapshots remain visible;
they do not turn into passing tests. No historical files or registrations were changed.

Ruff for `src`, `tests` and `tools`, compile checks, Specify prerequisites and whitespace checks
pass. This is offline implementation evidence only: no real provider, external producer, WebAgent
or campaign was run.
Fresh real-model materials, launch runner, committed registration and independent postrun audit
remain required; Feature 139 stays preparation **1/1**, primary/joint **0/1**.

## Provider-free registration preparation (2026-09-22)

The new canonical registration manifest/seal contract is implemented in
`lunar_evolution.acceptance_registration`. It fixes the fresh `attempt-001` identity, product
checkpoint and file pins, nested task/input/evaluator/profile materials, eight ordered holdout
pins, one-island/one-candidate/one-round/12-step limits, and the registered Feature 142 budgets.
The read-only preflight checks committed no-follow manifest/seal bytes, clean `HEAD == origin/main`,
product checkpoint ancestry and bytes, frozen identity reuse, and an absent campaign root. It runs
no provider, evaluator, candidate or campaign and creates no root or report.

The focused registration suite passed **16 tests** (canonical/digest and private-field rejection,
material and frozen-identity bindings, seal tamper, and a temporary Git checkout covering clean,
dirty, unpushed, root-reuse, product-drift and identity-reuse rejection). This is an offline
admission-boundary check; it does not authorize or perform the real attempt. Feature 149 now supplies
the provider-free independent cleanup-v1 receipt and native auditor wiring, including compatibility
for legacy records whose cleanup remains unknown. Launch-time material bytes, a separately committed
registration and the actual automatic multi-file acceptance remain pending.

## Phase C detached execution (2026-09-21)

The current implementation adds automatic background fresh solve, both resume entry points and
answer. The private coordinator adopts the existing workspace lock, waits for the parent's
registration gate, and executes the shared automatic continuation. Credentials travel only in
the environment. Policies are restored from the original request, and accepted answers remain
available after a launch failure. The ordinary detached launcher retains its previous behavior.

Actual Python subprocesses against a loopback-only HTTP fixture verify foreground/background
delivery equivalence, exact policy restoration, waiting-input exit, once-only answer acceptance,
contract cancellation, cancellation during a candidate's independent process group, SIGKILL
recovery during intake, terminal idempotency and competing foreground/background continuations.
The ten integration scenarios passed together in the final **37-test** worker/integration run.
The runnable entry is [quickstart.md](quickstart.md).

The new CLI suite passed **28 tests**; ordinary CLI/explicit-profile compatibility passed **87**,
automatic policy/preparation/conversation compatibility passed **220**, and lifecycle/cancel/
deadline/status/propagation compatibility passed **101**. New descriptor/runner ownership tests
cover real exec inheritance, malformed descriptor rejection, concurrent registration and stale
finalizer exclusion. The final **63-test** CLI/descriptor run and **37-test** worker/integration
run passed: **100 new tests**, with the single obsolete blanket-detach-rejection parameter removed.
The worker run includes **20** recovery/finalizer cases and **7** independent launch-fault cases.
Reports are `focused-cli-ownership.xml` and `focused-worker.xml` in the Phase C results directory.
Independent review passed. The complete three-stage runner returned **exit 0** against frozen
product/test bytes, inventoried in `product-test-bytes.json` in that directory:

| Phase | Revision / scope | Result |
| --- | --- | --- |
| Current product | Working tree based on `dfd3faf`; all 293 inventoried product/test/tool files unchanged during verification | **6684 passed, 1 existing skipped**, 0 failures/errors, 862.40s |
| Archived historical | `c6947fdfbf43d84e83cc29cc215e7bc0250db83a`; exact collection and file inventories | **2294 passed**, 24 registration nodes deferred, 0 failures/errors, 403.34s |
| Original registration | `5560eb9f67463badc31fed17e309bb5dc1dabf8f`, original product/manifest pins | **24 passed**, 0 failures/errors, 18.74s |

Full reports are `current.xml`, `archived.xml`, `frozen123.xml` and `full-run.log` in
`.lunar-evolution/test-results/feature142-phase-c-20260921/`. The first full run passed without a
rerun, retry or historical source change. The new current collection is **6685** nodes: the prior
6586 plus 100 new cases minus one obsolete negative parameter. Historical denominators are unchanged.
Product **`ff1edcb6f7d58f5a28511184837b65948036517a`** is pushed to `origin/main` with exactly the
verified product/test bytes. Its first
[Linux matrix](https://github.com/vchive/Lunar-Evolution/actions/runs/35568522333) passed all steps
on Python **3.12 and 3.13**. Python **3.11** failed the current test
`test_materialization_attestation.py::test_cli_preflights_and_returns_only_registration_metadata`
(CLI returned 2 instead of 0); its static check was skipped. The original failure is retained in
`linux-ci-initial-failure.json` and the public job HTML. Public API quota exhaustion required using
the public workflow/job pages; those pages expose the exact commit and step conclusions.

The unchanged 76-test attestation suite passes locally under Python 3.11. A separate controlled
reproduction exposes a pre-existing fixture race: collecting unclosed source SQLite connections
after snapshot copying checkpoints the database (4096 to 217088 bytes) and removes its 1281352-byte
WAL, so strict snapshot validation correctly rejects registration. Holding a live source connection
through the same forced collection preserves the files and succeeds. This matches the earlier
fixture-lifecycle issue already handled by the adjacent receipt-immutability test, but does not
prove the exact CI interleaving: its public annotation lacks the captured snapshot error.
The remedy is restricted to the current positive test fixture and a deterministic GC regression;
product guards, frozen evidence, archive source and original registration tests remain unchanged.
The fixture now explicitly keeps and closes a source connection across both successful CLI calls.
Three parameters cover normal GC, forced collection before validation and forced collection after
validation. Both forced paths run the real snapshot context and its unchanged-source guards;
neither disables GC, mocks a guard, catches failure for retry nor changes a product check.
Independent review passed. Python **3.11.15 and 3.13.12 each passed 86 tests** (78 attestation tests
and eight real-source-change refusal cases), with no failure, error or skip. Reports are
`attestation311-gc-fixed.xml`, `attestation313-gc-fixed.xml` and `ci311-gc-reproduction.json`.
The two additional GC parameters bring current collection to **6687** nodes. The prior complete
local run remains its original 6685-node checkpoint; unchanged product/archive stages were not
needlessly repeated. The follow-up CI runs all three complete stages against the test fix.
The test-only fix is **`ad89b50e5e95377c496c38e765998f2649b40be9`**, pushed to `origin/main`.
Its [follow-up matrix](https://github.com/vchive/Lunar-Evolution/actions/runs/35570899139) completed
successfully. Public API metadata and job pages were independently checked at **2026-09-21
07:24:13 UTC** against that exact SHA. Python **3.11, 3.12 and 3.13** each passed installation,
the complete three-stage test runner, failure annotation, report preservation and static checks.
Job IDs are respectively **106242131308**, **106242130982** and **106242131330**. This closes T028;
the initial failed matrix remains recorded separately above.

Final public evidence is retained under
`.lunar-evolution/test-results/feature142-phase-c-20260921/ci-ad89b50-35570899139/`:
`linux-ci-final.json`, `run-final.json`, `run-final.html` and the three final job pages.
All `src/` and `tools/` bytes remain identical to the verified product `ff1edcb`; tests and CI
configuration remain at `ad89b50` during documentation closeout. The new 6687-node collection is
distinct from the earlier 6685-node full local run. No additional local full run is needed for
this documentation-only closeout; the final complete matrix validates the test fixture change.
Closeout checks cover nine changed Markdown files and **123** resolving local links, with zero
retired-name matches across **1144** publication files. Product/test/CI byte checks, Specify
prerequisites and diff whitespace checks pass; `documentation-closeout-check.json` retains the
separate closeout scope without replacing the earlier publication checkpoint.

Initial integration exposed missing workspace creation before the new lock acquisition; the
fresh-run branch now creates its workspace before locking while input staging remains inside
ownership. Failure-first CLI tests additionally exposed launch success inheriting an old
preparation failure exit code and cancelled continuation failing during link preparation.
Accepted launches now have `launch_status: accepted` while retaining the prior diagnosis, and
failed/cancelled terminal continuations return their existing handle without new work. The new
28-test CLI suite also fails in its entirety against the previous `dfd3faf` CLI implementation.

Final independent review tightened three failure boundaries before the full regression: private
continuations must match the owner's home and parent; exiting coordinators freeze their cleanup
targets and recheck their own exact runner identity before each signal; launcher database failures
and process-exit races still reap only the newly launched child and retain any unconfirmed
registration. Recovery also refuses malformed/partial process identities. The Store process query
now exposes either non-null PID or PGID so incomplete cleanup responsibility cannot disappear
from recovery checks. No database schema or historical identity changed.

Two independent reviews covered CLI policy/routing and worker launch/recovery/exit boundaries.
README and quickstart command parsing passed for **91** examples without runtime side effects.
Ruff for `src`, `tests` and `tools`, compileall, offline lock validation, SDD prerequisites and
whitespace checks pass. Publication scanning found **zero** retired-name matches across **1144**
tracked/new files and paths; all **230** final changed-document local links resolve. Product/test
byte verification remained unchanged after all test stages.

Read-only verification of the relocated 131/134/139 inventories again matched **188 files /
781341 bytes**, all sizes and SHA-256 values, with no missing or extra files. The report is
`.lunar-evolution/test-results/feature142-phase-c-20260921/evidence-integrity.json`.
The same inventory was rechecked after all three regression stages with identical results in
`evidence-integrity-final.json` in that directory.
No real provider request, historical candidate execution, campaign or WebAgent rerun occurred.
Feature 139 remains preparation **1/1**, primary/joint **0/1**. Real-model complete delivery and
Feature 143 T009 consumer integration remain separate unfinished work.

## Cancellation cleanup race found during Feature 145 regression

2026-09-21: the completed current-product regression identified an intermittent failure in
`test_subprocess_runtime_releases_all_terminal_paths[timeout]`: only the started callback was
recorded, with no release callback. That run recorded **6574 passed / 1 failed / 1 skipped**.
An earlier estimate from progress dots incorrectly selected the cancel parameter; the final
traceback supersedes that estimate. A separate deterministic reproduction with a real private
process group identified a cleanup race: another thread can reap the leader after the group
probe but before `getpgid`, while `Popen` still holds its wait lock and has not published the
return code. `getpgid` then reports a missing leader and nonblocking `poll()` returns `None`.
The existing cleanup branch reports unconfirmed cleanup even when the group has disappeared.
This reproduction is established independently. The timeout traceback does not expose cleanup's
OS observations and does not establish that the timeout failure has the same cause; that
attribution remains unproven.

The bounded repair re-probes this same owned group at that boundary. Only observed group
absence may confirm cleanup and emit release; a surviving group still fails closed. No extra
termination signal, timeout increase, permission, retry or weakened process-release assertion is
introduced. Acceptance covers the real reaping/publication interleaving, surviving-group refusal,
and release only after group absence, followed by the runtime/process/worker suites. The original
failure and pre-fix regression result remain part of this checkpoint's evidence.

The three new deterministic cases produced **2 failed / 1 passed before the product repair**:
actual group absence was falsely unconfirmed, release was missing after confirmed absence, and
the surviving-group refusal already passed. After the one-branch repair, **228 tests passed**
across all 12 selected runtime/process/cancellation/worker suites. Ruff, compileall and diff
whitespace checks passed. Existing real-process release assertions remain unchanged. No provider,
historical candidate or full campaign was executed by this diagnosis or focused verification.

### Transient permission denial during timeout cleanup

A separate instrumented repetition of the existing real timeout fixture reproduced a second
failure after the reaping/publication repair, on iteration 9. The private group probe and leader
identity check succeeded, followed by a successful `SIGTERM`; the next `poll()` returned `None`
and `killpg(pgid, 0)` raised `PermissionError` (`errno=1`). Both cleanup attempts immediately
reported false. A follow-up observation after 1 ms found return code `-15` and group absence
(`ProcessLookupError`, `errno=3`). This establishes a transient probe-denial failure independently
of the reaping/publication interleaving; the uninstrumented full-run traceback alone cannot prove
which OS interleaving occurred in that earlier run.

Acceptance keeps permission denial unknown. Only a probe inside the existing 250 ms wait window
after an already-authorized signal may be retried with `poll()`; the deadline must not reset. A
window ending with an unknown probe must fail closed without a new signal or wait window. Initial
probe denial, leader-identity denial and termination-signal denial still fail immediately. Release
requires observed group absence, even when the leader return code has been published. Deterministic
cases cover transient denial followed by absence, persistent denial, a surviving group, and each
pre-signal/signal permission boundary. Existing real timeout/cancel release assertions remain
unchanged, and repeated timeout/cancel fixtures verify the fix without provider or campaign work.

The seven new permission-boundary cases produced **3 failed / 4 passed before the repair**:
transient denial prevented release, while persistent denial and recovered-live observations
incorrectly abandoned the existing wait immediately; all four pre-signal/signal denial refusals
already passed. After the bounded-loop repair, all seven cases passed and the same 12 focused
runtime/process/cancellation/worker suites passed **235 tests**. A separate repetition passed
**100 real timeout and 100 real cancellation checks**, including concurrent cancellation and
run-finally cleanup, with the original process-release assertions unchanged. These repetitions
are observed regression evidence, not proof that every possible OS interleaving is covered.
Independent review confirmed the unknown-state and signal-authority boundaries. Ruff, compileall
and diff whitespace checks passed. No execution timeout, cleanup window, release assertion or
provider/campaign boundary was relaxed.

## Scope of this checkpoint

2026-09-20: Phase A foreground implementation and Phase B cancellation/process cleanup are
complete. A shared monotonic deadline now spans
contract intake, preparation, generation, candidate execution, independent scoring, selection and
parent delivery. Durable orchestration prevents premature parent success. Solve, resume and answer
share execution admission; process-local ownership plus a nonblocking workspace lock excludes
concurrent foreground owners. Answer acquires ownership before accepting its artifact.

This is one **active execution** budget. Human waiting and admissible explicit continuations create
separate execution identities under the same policy. Observed exhaustion is terminal and cannot
be replenished by continuation. The status projection contains bounded recorded facts and never
reconstructs a live monotonic remainder from persisted timestamps.

Phase B in-flight cancellation and owned process registration/cleanup are verified. Parent
cancellation selects only an exactly verified linked child; probe, candidate and evaluator
processes register their PID/PGID and release ownership, while cancellation and deadline cleanup
fan out through owned groups before the coordinating worker. Failed cleanup retains the durable
registration and blocks replacement work. Phase C detached entry points remain open and automatic
`--detach` remains rejected. Local cleanup does not terminate remote provider work.

## Offline acceptance

| Area | Evidence | Result |
| --- | --- | --- |
| Policy validation | solve/resume/answer bounds, unsupported modes, exact restoration, legacy injection rejection | Pass |
| Shared deadline | Deterministic native fixture covers contract/compiler/auditor/generation, local execution, scoring and delivery under one control | Pass |
| Immutable identity | Frozen inputs, profile, contract, evaluator and plan bytes retain their configured ceilings while actual process timeouts narrow | Pass |
| Parent lifecycle | Parent running during delivery, one reused orchestration task, ordinary scheduler exclusion, child failure cannot succeed parent | Pass |
| Recovery | Human wait starts a new active execution; valid preparation recovery retained; corrupt recovery rejected before any new observation; successful/exhausted continuation is read-only | Pass |
| Terminal precedence | One solve-policy budget event; cancellation-first and budget-first preserved; late task success cannot replace the budget failure | Pass |
| Ownership | Busy same-process and cross-process owners reject admission; busy answer does not consume input or write artifacts | Pass |
| Status | Fixed fields, absent/explicit policy origin, successful final delivery phase, malformed observation rejection and no status writes | Pass |
| Delivery | Deadline checks after material reads, before copy/output commit, and before successful parent settlement; unfinished output batches reconcile on typed stop | Pass |
| In-flight cancellation and local cleanup | Verified parent/child fan-out, probe/candidate/evaluator PID/PGID registration, ownership release, cancellation/deadline races, late-response guards, cleanup failure retention, and cleanup ordering | Pass (local fixtures) |
| Detached execution | Automatic entry point remains rejected | Gate preserved; positive behavior not implemented |

## Focused verification

New/extended suites:

- `tests/test_automatic_solve_lifecycle.py`: deadline math, typed stop, process/workspace ownership,
  unsafe lock rejection, and budget failure between last-task success and parent settlement.
- `tests/test_automatic_solve_deadline_integration.py`: 18 native offline integration cases, all
  passing; local model responses are fixtures, and candidate/evaluator programs are fresh fixtures.
- `tests/test_automatic_solve_status.py`: 13 cases passing, including answer identity, read-only
  status, bounded diagnostics and terminal winner behavior.
- `tests/test_solve_budget_propagation.py`: 23 cases passing, including timeout ceilings,
  independent scoring admission and typed stops surviving broad exception handlers.
- `tests/test_automatic_solve_orchestration.py`: Store, scheduler, child outcome, delivery and legacy
  compatibility; output-publication Store tests cover rejection after failed/cancelled parents.
- `tests/test_automatic_cancel_phase_b.py`, `tests/test_automatic_runtime_processes.py`,
  `tests/test_evaluator_bundle_process_ownership.py`, `tests/test_candidate_process_release.py`,
  and `tests/test_process_ownership.py`: Phase B cancellation, process registration, cleanup
  ordering, ownership release, and late-response coverage. The child-stage cleanup fixture
  includes a claimed parent orchestration attempt, matching the production lifecycle.

The final Phase B focused verification command passed **146 tests in aggregate** across the
cancellation/deadline, population, candidate evaluation/evaluator/evidence, snapshot evaluator,
and process ownership suites. The cleanup regressions also prove that a new launch cannot replace
a registration retained after failed cleanup, and that cancellation blocks later generation,
execution, scoring and delivery when no wall timeout is configured.

The policy/preparation/automatic-bundle/orchestration compatibility command passed 227 tests.
Preparation-recovery/status/deadline integration passed 42 tests before the final five boundary
cases were added. A subsequent 28-test status/integration run and independent 15-test integration
run passed. Final Store/Controller/run-budget/lifecycle/status refinement passed 46 tests. The
materialization and attestation compatibility suites passed 186 tests after the additive task
schema fixture update; publication and lifecycle boundary suites passed 134 tests.

Ruff for all `src` and `tests`, compileall, Specify prerequisites with `--require-tasks
--include-tasks`, and `git diff --check` pass. Local Markdown links are checked before commit.

## Full regression

The 2026-09-21 Phase B two-stage rerun is recorded in `.lunar/test-results/feature142-phase-b-20260921/`:

- Current working tree: **8636 passed, 1 skipped, 24 deselected**, 0 failures and 0 errors,
  exit 0 (`current.xml`).
- Frozen Feature 123 registration stage: **24 passed**, 0 skipped, 0 failures and 0 errors,
  exit 0 (`frozen123.xml`).

The current stage executed 8637 collected tests; the 24 deselected nodes are the immutable
historical registration selection. The frozen Feature 123 stage recorded 24 passed tests. These
reports are the final Phase B checkpoint. An accidentally started duplicate run removed the earlier
`feature142-phase-b-final/current.xml` before being stopped; that incomplete directory is not the
final evidence. This rerun restores a complete pair without changing the product or historical
campaign evidence.

## Independent review and retained evidence

Independent budget-boundary review found and resolved typed timeout swallowing (including the
`TimeoutError`/`OSError` inheritance boundary), fresh per-stage allowances, missing scoring timeout
propagation and late publication checks. Independent lifecycle review found and resolved busy
answer consumption, incomplete status records and preparation recovery mutation before admission.
The task discriminator schema refinement and cross-process advisory owner are documented in the
existing SDD; this is a continuation of Feature 142.

Feature 131 retained inventory: **21 files / 155485 bytes**. Feature 134: **97 files / 327394 bytes**.
Each relative path, size and SHA-256 matches its retained `postrun/evidence.json`; no symlinks or
historical SQLite mutation. The product diff contains no Feature 139 source/evidence change.
No provider, real campaign, retained generated program, or WebAgent was executed.

## Release boundary

The 2026-09-21 readiness audit additionally checked the pushed product `65d9ae2` on
[GitHub Actions run 35522272395](https://github.com/vchive/Lunar-Evolution/actions/runs/35522272395).
Its Linux/Python 3.11 installation steps passed, but `Run tests` exited 1 and static checks were
skipped. Python 3.12 and 3.13 were cancelled by matrix fail-fast after that failure. Public metadata
does not identify a failing test or distinguish current from frozen123 failure; full logs require
authentication and no report artifact was uploaded. Root cause and cross-platform acceptance
remain open. The retained local passing reports above are unchanged and are not a claim that
the remote CI matrix passed.

Offline correctness here does not establish evaluator quality, current-model task success,
WebAgent parity or successful real automatic multi-file delivery. Feature 139 remains preparation
1/1 and primary/joint 0/1. Phase C still requires detached solve/resume/answer routing, exact
policy restoration, once-only answer acceptance, exclusive worker ownership, launch/exit and
stale-worker recovery, and foreground/background equivalence with live cancellation. A separately
scoped real acceptance also remains outstanding; this checkpoint does not claim the whole feature
or system release is complete.
