# Tasks

**Status**: Phase A/B/C are implemented, pushed and pass focused offline subprocess acceptance,
independent review, full local three-stage regression and the Linux/Python 3.11–3.13 matrix.
Exact product/test checkpoints and remaining real-delivery limits are in [validation.md](validation.md).

## Specification

- [x] T001 Record the option name, active-execution scope, explicit continuation semantics,
      immutable identity boundary, parent lifecycle, reuse of cancellation, and phased detach gate.
- [x] T002 Map existing 133/137/141 behavior and actual CLI/Controller/process gaps by read-only
      inspection. Do not treat this mapping as product implementation or regression completion.

## Phase A: Shared budget and foreground parent lifecycle

- [x] T003 Add early parser/mode/value validation for `--solve-wall-timeout` across solve,
      `solve --resume`, resume, and answer, before runtime and mutation side effects.
- [x] T004 Persist explicit solve policy and a lifecycle marker; restore exact values on
      continuation, reject mismatches/legacy injection, and preserve omitted legacy behavior.
- [x] T005 Add one exclusive automatic execution owner and one shared process-local monotonic
      deadline; never reset it per phase, request, candidate, retry, or nested Controller call.
      The same workspace lock also excludes other foreground processes; answer acquires it
      before consuming the pending input. Human waiting closes the prior execution.
- [x] T006 Establish/reuse a parent orchestration task after contract intake and before preparation
      or handoff settlement; prevent ordinary scheduling and premature parent success.
- [x] T007 Route all automatic continuation entry points through the same orchestration, including
      answer. Preserve awaiting-input, preparation recovery, and terminal idempotency semantics.
- [x] T008 Propagate remaining time through intake, preparation lock/checks, compiler/auditor,
      candidate generation, local execution, scoring, selection, and parent delivery.
- [x] T009 Add narrower operational timeout/stop hooks without modifying frozen profile, input,
      contract, source, evaluator, execution admission, plan, or receipt identity. These are
      cooperative admission/result checks; in-flight process cancellation is Phase B.
- [x] T010 Persist one solve-policy budget failure with existing Store terminal precedence; block
      late success/publication and any continuation that would replenish an exhausted solve.
- [x] T011 Add bounded read-only execution status, policy origin, fixed phase, and stopping reason;
      do not infer a live monotonic remainder or remote provider result.
- [x] T012 Verify phase A with deterministic clock and fake-transport native CLI tests, including
      immutable-byte checks and existing preparation/Controller/receipt compatibility suites.

## Phase B: Cancellation and owned process cleanup

- [x] T013 Connect parent cancellation to its exactly verified child and evolution predicate using
      existing Controller/Store cancellation; preserve unrelated runs and terminal winners.
- [x] T014 Register actual local probe/candidate/evaluator process ownership through existing
      process tracking, including independent process groups and ownership release.
- [x] T015 Reuse cancellation/cleanup fan-out for deadline exhaustion and cancellation; continue
      cleanup after callback failure and clean owned subprocesses before the coordinating worker.
- [x] T016 Test cancellation at each phase, before/after linking and delivery, late responses,
      cancellation/deadline races, failed cleanup callbacks, and no remaining owned local process.
- [x] T017 Independently review phase B and record passing process cleanup evidence. Keep
      automatic `--detach` rejected until this task is complete.

Phase B evidence: 146 focused cancellation, process-ownership, deadline-integration and pipeline
regressions pass. The final current regression recorded **8636 passed, 1 skipped, 24 deselected**;
the frozen Feature 123 registration stage recorded **24 passed**, with no failures or errors.
Reports are retained at `.lunar/test-results/feature142-phase-b-20260921/{current,frozen123}.xml`.
At that Phase B checkpoint, detached solve/resume/answer routing, worker ownership and
foreground/background equivalence remained outside acceptance; Phase C below closes that boundary.

## Phase C: Detached automatic execution

- [x] T018 Reuse the existing launch contract for new and continued lifecycle-enabled automatic solves; support
      solve/resume/answer detach routing only after T017 passes.
- [x] T019 Propagate/restore runtime, multi-file, preparation, candidate-step, and solve policies
      exactly without secrets in argv or public state. Keep legacy detach rejection explicit.
- [x] T020 Preserve once-only answer acceptance and parent ID on background continuation; prevent
      duplicate live workers and release only the exiting worker's ownership on every exit path.
- [x] T021 Verify foreground/background equivalence, useful status handles, no waiting worker
      during human input, live cancel, launch failure, stale worker recovery, and process cleanup.

## Completion

- [x] T022 Run focused/shared regressions, current full regression and fixed historical test stage,
      Ruff, compileall, Specify prerequisites, Markdown-link checks, and `git diff --check`.
- [x] T023 Independently verify Feature 131/134 retained file sets, sizes, and SHA-256 values remain
      unchanged; verify this feature did not modify Feature 139 source/evidence or launch a provider.
- [x] T024 Complete independent review and record exact validation results and residual limits;
      update roadmap/handoff to distinguish active-execution from cumulative lifetime budgeting.
- [x] T025 Commit and push the verified Phase B product implementation. Do not claim detached
      availability or real-provider end-to-end success from an offline implementation. Phase C
      remains a separate future delivery.

## Phase C release verification

- [x] T026 Run the new real-subprocess offline quickstart, shared compatibility tests, full current /
      archived / frozen registration regressions, static checks and SDD/link checks.
- [x] T027 Independently review launch/recovery/exit ownership and verify retained 131/134/139
      evidence inventories without modifying or executing their contents.
- [x] T028 Record exact Phase C results and remaining real-delivery / worker-consumer limits;
      commit and push the verified changes and inspect the Linux matrix.

## Provider-free registration preparation

- [x] T029 Define the canonical fresh `attempt-001` registration manifest, nested material and
      holdout pins, fixed budgets, product file pins, frozen identity denylist and registration seal.
- [x] T030 Implement no-follow, read-only checkout preflight for committed manifest/seal bytes,
      pushed clean `HEAD`, product checkpoint ancestry and bytes, and an absent campaign root.
- [x] T031 Add provider-free parser, seal, Git fixture, tamper, dirty, unpushed, drift, root-reuse
      and identity-reuse tests; document the boundary without claiming launch or real acceptance.

## Independent cleanup evidence prerequisite

- [x] T032 Complete Feature 149's cleanup-v1 native receipt, runner observer/probe wiring, and
      read-only acceptance/slot auditor integration. Keep old three-file records compatible but
      cleanup-unknown, and do not authorize a provider until its focused and related regressions
      pass.

## Repeatable offline E2E regression

- [x] T033 Add an explicit `native-e2e` suite to the existing regression runner, preserving the
      default three-stage release gate, checkout import checks, controlled collection and exact
      JUnit count validation without archive setup in the focused path.
- [x] T034 Verify routing and failure/count boundaries, run the actual foreground/background,
      automatic multi-file, cancellation/deadline and installed-package E2E selection, and
      retain a separate JUnit report.
- [x] T035 Record current remaining release/producer work, document the reusable command, and
      commit/push the verified offline change without claiming real-model success.

## Fresh real-acceptance preparation

- [x] T036 Reconstruct the prior effective provider/model/native API mode and byte-exact task and
      input; freeze independent criteria and the eight actual historical holdout probes in new,
      separately tracked Feature 142 materials. Keep generated evaluator/profile digests distinct.
- [x] T037 Check all registered material bytes against committed Git blobs, reject non-regular
      committed file modes, use one pinned HEAD during the read, and recheck checkout stability.
- [ ] T038 Implement a launch runner that verifies the actual remote `main` commit, enforces the
      clean `HEAD == origin/main` gate, atomically claims one fresh campaign root, and retains the
      preregistration/preflight evidence before the sole provider attempt.
- [x] T038a Implement and verify the provider-free remote/root/evidence admission slice described
      in [campaign-admission.md](campaign-admission.md); it does not itself launch an attempt.
- [ ] T039 Bind the native preparation-generated evaluator/profile to the preregistered independent
      criteria and the observation manifest; add provider-free mismatch and interruption tests.
- [ ] T040 Run the new one-slot real attempt and independent postrun six-stage/holdout audit.
      Preserve Feature 139's closed evidence and report `0/1` honestly if a stage fails.
