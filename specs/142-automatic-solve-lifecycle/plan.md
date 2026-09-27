# Implementation Plan: Automatic multi-file solve lifecycle

**Date**: 2026-09-20

**Status**: Phase A/B/C are complete, pushed and pass offline subprocess acceptance, independent
review, full local three-stage regression and Linux/Python 3.11–3.13 CI. Release closeout and exact
checkpoints are recorded in [validation.md](validation.md).

**Spec**: [spec.md](spec.md)

## Approach

Extend the existing solve orchestration and Controller boundaries. Do not replace Controller
cancellation, the Store terminal-state rules, Feature 133 preparation policy, Feature 137 request
clipping, or existing frozen candidate/evaluator identities. Keep the feature limited to native
automatic multi-file population solving.

Feature 143 supplies an independent local Worker/WorkerAttempt control plane. This feature may
reuse its ownership and process-observer primitives where a later detached or child worker needs
them, but it does not reinterpret the ordinary task DAG as a worker tree. Feature 143 T009,
explicit delegation consumer migration, is optional and does not block this lifecycle.

## Phase A: Foreground budget and parent lifecycle

1. Add `--solve-wall-timeout` to solve/resume/answer parsers. Validate values and supported modes
   before side effects, and persist only an explicit value, its source, and a lifecycle version
   marker in `evolution_requested`. Extend `_evolution_args` and override validation consistently.
   Historical handoffs keep their absent fields and cannot acquire new policy on continuation.
2. Consolidate the automatic foreground continuation path shared by `_solve`, `_answer`, and the
   resume dispatch. In particular, an automatic answer must not fall through to ordinary
   `controller.resume` and claim the controller-owned orchestration task as model work.
3. Admit one active execution owner and create one process-local control object with monotonic
   start/deadline, stage checks, and cancellation observation. Existing explicit recovery rules
   decide whether a nonterminal interrupted run is admissible; this feature does not infer an
   active worker to be stale merely because another process asked to resume it. Supplement the
   in-process owner with a nonblocking workspace advisory lock; acquire it before consuming an
   automatic answer as well as before intake.
4. After accepted contract intake, establish one parent orchestration task before preparation or
   superseding the generated tasks. Reuse it on continuation and settle it only on delivery,
   cancellation, or terminal failure. Keep it outside ordinary scheduling and preserve historical
   terminal parents. The existing intake task continues to own contract compilation. Add the
   default-false `tasks.orchestration` discriminator described in the specification, with legacy
   read-only row compatibility. Store settlement and budget failure use writer transactions so
   stale task snapshots cannot replace a concurrent terminal outcome.
5. Thread the shared control through contract compilation, `prepare_automatic_solve_bundle`,
   `_solve_evolution`, generation, execution, scoring, and delivery. Preparation composes its own
   remaining callback with the solve remainder, including lock acquisition. Requests and local
   subprocesses receive the minimum of all applicable ceilings. Preserve post-operation checks.
6. Add optional operational timeout/stop hooks to execution/evaluation boundaries where needed.
   Their defaults preserve existing APIs. They must not modify a frozen pipeline/profile,
   evaluator specification, execution admission, plan, source bundle, or input bytes. Any new
   bounded observation records the effective value separately from the configured authority.
7. Reuse `Store.fail_budget` for one fixed solve-policy limit and existing terminal precedence.
   Ensure child completion cannot publish parent success after a parent stop. Reuse the existing
   verified delivery path; do not re-execute a selected candidate to recover delivery evidence.
8. Extend `_solve_payload` and read-only status projection with bounded execution policy/stage/
   outcome metadata. Do not derive a false live remainder from persisted UTC timestamps.

## Phase B: Parent/child cancellation and local cleanup

1. Extend cancellation orchestration only for new lifecycle-enabled automatic handoffs. Validate
   reciprocal parent/child links and contract identity before selecting the linked child.
   Preserve existing Controller/Store terminal transitions and reuse cancellation fan-out.
2. Feed the same parent and child stop authority into evolution admission and phase guards.
   Complete child evidence may remain retained, but cancelled/expired parents cannot deliver it.
3. Trace every local process spawned during preparation, candidate execution, and scoring.
   Connect actual PID/PGID ownership to existing process observers and Store ownership data.
   Candidate/evaluator processes have independent process groups and require their own cleanup.
4. Reuse/extract the existing active-work cleanup logic so budget exhaustion and cancellation
   reach all owned groups and runtime adapters even when one callback fails. End the coordinating
   worker only after owned process cleanup. Do not use unrelated process-tree discovery as an
   authority to terminate arbitrary processes.
5. Add deterministic local-process tests for each phase, parent/child races, callback errors,
   delayed responses, and runner ownership release. These are a prerequisite for phase C.

Phase B acceptance is complete: 146 focused regressions pass, including parent/child cancellation,
real local process-group cleanup, ownership races, failed-cleanup retention and coordinator cleanup
ordering. The final current suite recorded **8636 passed, 1 skipped, 24 deselected** and the frozen
Feature 123 stage **24 passed**, with zero failures or errors. Reports are retained at
`.lunar/test-results/feature142-phase-b-20260921/{current,frozen123}.xml`. At that checkpoint, Phase C was the only
remaining implementation phase: detached routing, exact policy propagation, worker ownership,
launch/exit recovery and foreground/background equivalence.

## Phase C: Detached automatic entry points

1. Phase B's cleanup prerequisite has passed. Keep the current automatic `--detach` rejection
   until Phase C itself is implemented and validated. Reuse the existing launch contract and the
   same execution owner/continuation path; keep ordinary `_detach_solve` behavior compatible.
2. Add detach routing for fresh solve, `solve --resume`, generic resume, and answer. For answer,
   validate the policy first, durably accept the existing pending answer once, then launch a
   continuation of the same parent. A launch failure must not silently discard the accepted
   answer or start a replacement worker.
3. Propagate/restore multi-file mode, all preparation policy, candidate step policy, the solve
   policy, and runtime identity. Credentials retain the existing environment-based propagation;
   they never enter argv or bounded lifecycle events.
4. Return the parent handle without waiting for model work. Prevent concurrent foreground/background owners,
   reject stale ownership substitutions, and clear only the exiting worker's ownership. Exiting
   for awaiting input releases ownership and stops the worker until an explicit answer/continue.
5. Verify equivalence of foreground/background outcomes and all launch/exit cleanup paths with
   fresh synthetic fixtures and no real provider.

The 2026-09-21 code audit confirms the remaining implementation order for T018–T021:

- First establish launch reservation, child ownership claim and conditional exit release. The
  existing launcher writes runner PID/PGID after process creation; direct reuse alone does not
  prevent competing continuations or a fast child exit leaving stale ownership. Reuse the existing
  workspace lock and PID/PGID-conditional clearing, and test loser/late-finalizer behavior.
- Then route fresh solve, solve continuation and generic resume through the shared automatic
  execution path. `_evolution_args` already restores persisted policy; verify exact restoration
  rather than introducing a second policy authority in command-line reconstruction.
- Add answer detach after launch ownership is established. The ordinary launcher's unconditional
  parent cancellation on launch failure must not discard an accepted answer's admissible recovery;
  retain the answer once and allow only explicit continuation under the existing policy.
- Test actual child processes for launch failure, exit before registration, waiting for input,
  foreground/background contention, live cancellation and owned-group cleanup before removing
  the automatic detach gate. No Phase C implementation or acceptance is claimed by this audit.

### Phase C implementation refinement (2026-09-21)

The existing workspace flock is the launch reservation. Expose its descriptor only to a local
worker through `pass_fds`; the parent keeps its ownership until launch returns. A private pipe
gates execution: the parent atomically registers PID/PGID only for a nonterminal run with empty
runner fields, then releases the gate. The child validates the inherited lock against the named
workspace file, checks its exact persisted runner identity, and uses the shared continuation.
Closing a descriptor releases only that process's reference; neither side explicitly unlocks
the shared open file description. EOF before permission starts no model work. The child marks
inherited descriptors non-inheritable before invoking any runtime and conditionally clears only
its own PID/PGID on all exits. No new database column or public capability token is required.

The internal worker entry wraps CLI parsing and runtime validation as well as execution, so an
invalid continuation cannot strand its registration. Persisted `_evolution_args` remains the
only evolution-policy authority; the launcher forwards runtime identity and runtime options.
An available workspace lock alone never authorizes replacing a live runner. Under that lock,
explicit recovery must prove the old runner exited, clean its registered local work, and verify
all owned registrations are released before a new worker can be admitted. Unknown process
liveness or incomplete cleanup refuses continuation. Accepted answers survive launch failure;
no automatic retry or terminal cancellation is introduced.

The automatic launcher lives in `automatic_solve_worker.py`; it reuses the ordinary subprocess
and log contract while adding the ownership handshake. This small separate boundary keeps the
ordinary launcher unchanged and wraps the entire child CLI validation and exit path. The shared
`_resume_automatic_solve` remains the only automatic execution lifecycle.

## Expected code touch points

| Area | Existing attachment point |
| --- | --- |
| CLI policy and routing | `src/lunar_evolution/cli.py`: parsers, `_validate_automatic_bundle_options`, `_evolution_request_payload`, `_evolution_args`, `_solve`, `_answer`, resume dispatch |
| Detached worker | `src/lunar_evolution/automatic_solve_worker.py`: launch gate, runner claim, recovery and exit; CLI runtime arguments and handle projection |
| Shared execution control | Small product helper used by automatic orchestration; no measurement-module dependency |
| Parent lifecycle and cancellation | `src/lunar_evolution/controller.py`: conversational intake, `run_evolution`, `deliver_bundle_to_parent`, `cancel`, existing budget/cleanup helpers |
| Durable state | `src/lunar_evolution/store.py`: existing task, event, fail-budget, cancellation, and runner/process ownership operations |
| Preparation | `src/lunar_evolution/automatic_solve_bundle.py`, `src/lunar_evolution/evaluator_bundle.py`: deadline composition, lock wait, phase guards, process observation |
| Candidate generation | `src/lunar_evolution/agent_evolution.py`, `src/lunar_evolution/agent_bundle_generation.py`: request-local remaining timeout and stop propagation |
| Execution and scoring | `src/lunar_evolution/bundle_evolution.py`, `candidate_execution_evidence.py`, `candidate_execution_runner.py`, `candidate_evaluation.py`: narrower operational limits and local process cleanup |
| Validation | New lifecycle fixtures plus existing automatic preparation, Controller, CLI, process, receipt, and delivery regressions |

Expected touch points are design guidance, not authorization to change all listed modules without
need. Preserve current defaults outside the explicit automatic lifecycle path. Any unavoidable
new evidence version must be specified and tested for backward read compatibility before writing
it; an implementation must not silently re-label old authority as a new profile.

## Risks and decisions

- **Scope of time**: this is one active-execution budget. Explicit continuation after human input
  or an admissible nonterminal interruption starts a new execution under the same policy. Solve
  budget exhaustion itself is terminal. Cross-continuation accounting is explicitly excluded.
- **Parent terminal state**: an orchestration task must prevent early success; merely changing
  status display would leave cancellation and budget writes ineffective in the Store.
- **Identity drift**: effective remaining time belongs to operational control/observation, not
  frozen profile/admission/source identity. Validate this byte-for-byte in focused tests.
- **Process ownership**: local processes use independent groups. Removing the CLI detach ban
  before process registration/cleanup works would expose orphaned work.
- **Recovery**: never broaden existing preparation or child recovery admission. Terminal success,
  cancellation, and solve exhaustion remain non-executing on continuation.

## Offline E2E runner extension (2026-09-27)

Extend `tools/run_tests.py` with `--suite {all,native-e2e}`, defaulting to `all`. Reuse its current
import verification, controlled pytest environment, collection and JUnit validation helpers.
Keep the native selection explicit and separate from archive/registration setup. Exercise the
actual profile against the existing subprocess integration suites and verify the routing,
collection and failure propagation boundaries in `tests/test_regression_runner.py`. Document the
command and report in the quickstart and README, with an explicit offline scope.

## Verification and release

Use deterministic clocks, fake provider transports, and fresh repository-owned local candidate/
evaluator/probe programs. After each phase, run focused tests and shared compatibility tests.
Enable phase C only after phase B is green. Before any product completion claim, run the full
three-stage regression (current product, fixed archived history and frozen registration), Ruff,
compileall, Specify prerequisites, diff/link checks, and independent
historical inventory verification. Record results in [validation.md](validation.md).

No Feature 139 source/evidence changes, provider call, real campaign registration/launch, or
historical experiment replay is part of this implementation plan. Subsequent commit/push belongs
to the verified implementation phase; these specification documents alone do not claim completion.
