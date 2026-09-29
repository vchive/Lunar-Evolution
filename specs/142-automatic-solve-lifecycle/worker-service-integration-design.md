# Opt-in automatic solve / WorkerService integration design

**Status: partial foundation implemented, 2026-09-29.** WSI-01/02 durable binding DTOs,
Store migration/CAS, typed continuation and shared-control seam are implemented. WSI-03 now
provides an explicit foreground WorkerService bridge and native result projection; process
observer composition, durable generation resume and full native evidence reopening remain
open. Feature 142's existing foreground/background execution,
answer/resume, cancellation and delivery remain the supported default. This integration is an
optional P2 extension; its absence does not mean automatic solve lacks a lifecycle.

## Existing contracts and the missing seam

| Existing code | Responsibility | Integration constraint |
| --- | --- | --- |
| [`cli.py`](../../src/lunar_evolution/cli.py), `_continue_automatic_solve`, `_resume_automatic_solve` | Acquire automatic ownership, recover, prepare, evolve and deliver | The synchronous orchestration entry is CLI-private and takes a mutable argparse namespace. |
| [`cli.py`](../../src/lunar_evolution/cli.py), `_bind_solve_execution_control` | Create one active solve control | It currently replaces the namespace's control with a new deadline; an injected outer control would be lost. |
| [`automatic_solve_worker.py`](../../src/lunar_evolution/automatic_solve_worker.py), `launch_automatic_solve`, `prepare_automatic_continuation` | Detached gate/lock handoff, runner registration and explicit recovery | Existing runner identity and ownership checks must remain authoritative. |
| [`automatic_solve_lifecycle.py`](../../src/lunar_evolution/automatic_solve_lifecycle.py), `own_automatic_solve`, `SolveExecutionControl` | Exclusive parent execution and active execution budget | A worker is not another permission to execute the same Run or reset its active deadline. |
| [`workers.py`](../../src/lunar_evolution/workers.py), `WorkerService._start`, `_execute`, `resume`, `reconcile` | Worker attempt admission, execution ownership, process cleanup and result persistence | Generic resume creates a fresh attempt, and generic reconcile does not inspect automatic Run evidence. |
| [`agents.py`](../../src/lunar_evolution/agents.py), `AgentAdapter`, `AgentResult`, `AgentRegistry.create_execution_adapter` | Fresh per-attempt adapter instances; success/failure/cancelled results | No result status represents waiting for input or an unresolved Run. |
| [`models.py`](../../src/lunar_evolution/models.py), `WorkerOutcome`, `WorkerStopReason` | `success`, `failure`, `stopped`, `lost` and bounded stop reasons | There is no current `unknown` or `awaiting_input` worker outcome/reason. |
| [`store.py`](../../src/lunar_evolution/store.py), `bind_worker`, `complete_worker_binding` | One scheduler task attempt paired with one worker attempt | This binding requires a running task and owns task-result delivery; it cannot represent an entire automatic Run. |
| [`controller.py`](../../src/lunar_evolution/controller.py), `observe_attempt_runtime`, `attempt_process_observers`, `cleanup_automatic_solve` | Automatic attempt process observation, guards and cleanup | The context installs and clears runtime callbacks; installing a second outer observer silently loses one side. |
| [`cli.py`](../../src/lunar_evolution/cli.py), `_solve_evolution_impl`, `_solve_payload` | Parent/child linkage, automatic delivery and effective status | Parent status alone, CLI exit zero or detached launch acceptance is insufficient evidence of delivery. |

Wrapping `_resume_automatic_solve` in an adapter without addressing these constraints would
duplicate ownership or misreport a suspended Run as success, cancellation or terminal failure.
The existing single-task `delegate` consumer is not a whole-Run orchestration bridge.

## Bounded first implementation

Provide an explicit library bridge and a fresh `AutomaticSolveWorkerAdapter` for an already
created lifecycle-enabled automatic Run. The caller must select this path; ordinary `solve`,
`resume`, `answer`, `delegate`, detached launch and adapter selection do not change.

The first implementation runs foreground orchestration inside a WorkerService attempt. It does
not place the service process itself in a worker-owned process group. Detached bridge support
and recursive worker tools during automatic candidate generation are separate follow-ups.
Wrapping automatic solve in WorkerService does not by itself enable recursive AgentLoop tools.

The Run/controller remains the sole owner of contract compilation, preparation, evolution
archive, evaluator receipts, parent/child linkage and delivered artifacts. WorkerService supplies
the outer execution handle, wait/notification and exact-attempt cancellation. A worker result
is an observed reference to the native result, never a second evaluation or delivery authority.

## Durable Run-to-worker binding

Add a separate versioned Store record, provisionally `automatic_solve_worker_bindings`.
Do not repurpose `worker_bindings`, synthesize a scheduler task solely for the bridge, or let
the bridge claim the orchestration task that `_solve_evolution_impl` already owns.

Each binding records:

- external owner ID, native Run ID and workspace identity;
- worker ID, worker attempt ID, service owner ID and binding generation;
- automatic lifecycle/request digest, immutable adapter/runtime configuration fingerprint,
  configured budget policy and accepted contract digest when available;
- native child identity only after verifying the existing reciprocal parent/child link;
- binding state (`admitted`, `active`, `awaiting_input`, `recovery_required`, `unknown`,
  `terminal`), prior binding generation and bounded observation/stop reason;
- terminal result-reference digest and native receipt/delivery identities when available.

Before releasing a queued executor, create the binding transactionally through the existing
`before_start` admission boundary. Require the exact running worker attempt and current owner,
and enforce at most one unresolved/executing binding for a Run. The automatic workspace lock
must still be acquired before starting work; a binding does not bypass it. A concurrent ordinary
CLI continuation must lose the same ownership race without issuing work.

Before intake there may be no contract or evolution child. Represent those pins as explicitly
unbound, then permit a one-way CAS to the native accepted contract/link. Never let a later
worker replace a bound digest. Keep generations append-only so a late old attempt cannot attach
to a resumed Run, cancel replacement work or overwrite a result reference.

Generic `WorkerService.resume` and direct adapter invocation must not bypass this admission.
The bridge's explicit resume reopens the native binding, verifies unchanged policy/configuration,
checks pending input and cleanup, and only then binds a new worker attempt to the same Run.
Confirmed native terminal results can be observed again without starting an adapter or Run.

## Nonterminal state mapping

The binding is authoritative for the native Run state. The worker outcome only describes the
last outer execution attempt; it must not overwrite the Run's native recovery semantics.

| Native observation | Binding state | Proposed worker projection | Continuation |
| --- | --- | --- | --- |
| Verified successful child, native delivery and parent settlement; cleanup confirmed | `terminal` | `success` | Read the same native result reference. |
| Verified native failure, including an exhausted active budget | `terminal` | `failure`, typed timeout/runtime reason | Native failure policy applies; no silent restart. |
| Verified native cancellation; cleanup confirmed | `terminal` | `stopped`, `cancelled` | Native cancellation policy applies. |
| Pending user input | `awaiting_input` | `stopped`, new `awaiting_input` reason | Answer through the native input contract, then explicitly resume. |
| Recoverable preparation failure; no unresolved owned process | `recovery_required` | `stopped`, new `recovery_required` reason | Explicit native preparation validation before another active execution. |
| Interrupted owner without a retained terminal result, or cleanup cannot be proved | `unknown` | `lost`, new `recovery_required` reason | Reconcile both ownership systems and native evidence; no automatic re-execution. |
| Observer wait timeout while the execution owner remains live | `active` | Remain running | Return only an observation timeout. |

The new reasons and a typed, bridge-specific suspension result/exception need an explicit
WorkerService handling path. They must not be represented by `AgentResult(status="cancelled")`
unless native cancellation actually occurred. Keep ordinary adapter result handling unchanged.
Likewise, worker `lost` is not evidence that the native Run is safe to retry: an `unknown`
binding continues to block admission until its native recovery checks pass.

Reconcile must acquire the exact prior worker owner lock and automatic workspace ownership,
then inspect native runner/attempt registrations and retained preparation/delivery evidence.
A missing lock, live owner, changed binding or uncertain cleanup leaves `unknown`. Reconcile
does not issue model requests, evaluate a candidate, regenerate a receipt or relaunch work.

## One active control seam

### WSI-02 implementation contract (2026-09-29)

`automatic_solve_continuation.py` exposes an immutable `AutomaticSolveContinuation` captured
from a lifecycle-enabled Run and `continue_automatic_solve(controller, continuation, ...)`.
The captured configuration pins the native workspace, complete persisted evolution request,
compiler manifest and runtime fingerprint. Continuation reopens those pins before ownership
admission and delegates to the existing synchronous CLI orchestration; no second solver,
preparation, evaluation or delivery path is introduced. This first seam is foreground-only.
Runtime credentials stay in the caller's already constructed controller and are not copied into
the continuation configuration. Existing CLI entry points retain their defaults.

The CLI control binder preserves an explicitly supplied `SolveExecutionControl` object. Native
wall policy and an optional worker active timeout only narrow its deadline, and native Run
cancellation plus existing stage observation compose with prior callbacks. An optional parent
control supplies a live remaining-budget/cancellation ceiling. Different controls may use
different monotonic clock origins: only sampled durations are transferred between them, with
time spent obtaining a parent sample charged against the child. A parent becoming cancelled,
expired or more tightly constrained blocks subsequent work. Rebinding or polling never extends
an admitted deadline. Default construction remains after native ownership admission.

Focused local acceptance covers preserved object identity, repeated binding, native/worker/parent
minimum budgets, cross-clock parent composition, cancellation at each stage, request/runtime
drift and the typed seam reaching the existing synchronous orchestration. This historical note
predates the current integration slice: WorkerService admission, process-observer composition and
result-reference delivery are implemented in WSI-01 through WSI-06. WSI-07 remains the complete
release regression gate.

Extract a typed public orchestration seam from the existing synchronous path, provisionally
`continue_automatic_solve(..., execution_control=None, ownership=...)`. It must reuse the
existing preparation, evolution and delivery functions, rather than implement a parallel solve.
The typed configuration must retain all persisted request settings and runtime fingerprints;
credentials remain runtime-only and never enter a binding, prompt or result reference.

For an opted-in worker, create one `SolveExecutionControl` when active execution begins after
ownership admission. Its ceiling is the minimum of the persisted native solve policy, explicit
worker active timeout and any caller-owned parent remainder. All stage ceilings remain narrower
limits on that same control. Pass the same control through intake, preparation, generation,
candidate/evaluator processes and delivery. The CLI binder must preserve an explicitly supplied
control rather than replace it, with existing default construction unchanged.

Compose exact worker-attempt cancellation with native Run/child cancellation. A service wait
timeout is not an execution deadline. Repeated observations must not create a new control, and
an adapter cannot replace or broaden a control already admitted for that active execution.

Feature 142 budgets active execution, not cumulative lifetime across human input and explicit
continuations. A later eligible active execution retains that existing policy. Do not serialize
a process-local monotonic timestamp into the bridge or silently import Feature 153's separate
boot-scoped publication budget contract. A future lifetime budget would require separate SDD.

## Process observation and cancellation authority

Add an explicit composable observer seam at the controller's existing attempt observation
boundary. It must fan out registration/guard/release observations under one exact binding,
without allowing nested runtime setters to overwrite or clear the other owner callbacks.

Bind each actual private subprocess group to the native Run/task attempt and outer worker
attempt before permitting subsequent work. Persist the identities required by both existing
ownership contracts, and validate the binding generation and process start identity before
signals or release. If either registration fails, no success can be published; cleanup must be
attempted for the exact newly created child, retaining uncertainty when release is unproved.

Use one composed cleanup decision for the bridge instead of competing generic and native
finalizers. Native cleanup selects only the reciprocally bound Run/child attempts; the bridge
records a WorkerService release only after that exact group is verified gone. The opted-in
service cleanup path must delegate to this authority-aware decision, preserving registrations
on failure. Default worker cleanup remains unchanged. No callback may signal the current
controller/service group or assume that a numeric PID is still the originally registered process.

Worker cancellation maps to the bound native Run cancellation. Native cancellation must also
stop the exact active bridge attempt and revoke further work. Revocation happens before
callbacks/signals; callbacks must be idempotent and avoid re-entering a cancellation cycle.
Old finalizers cannot clear replacement generations. Closing a service, observer failure and
cleanup failure use the same mapping, and can never produce a native success receipt.

Detached bridge support, if later implemented, needs a separate dual-registration/gate design:
both durable ownership records must exist before native work is released, and lock FD handoff
must preserve the current automatic launch contract. It is excluded from this first slice.

## Exactly-once native delivery and worker observation

The existing native controller performs delivery once. The bridge must not call the ordinary
delegated-task consumer's materialization/evaluation or `complete_worker_binding` for that Run.
It must not copy native outputs into a second archive, publish candidate IDs or rescore a result.

After native completion, independently reopen the current Run, reciprocal child link, terminal
receipt, delivered artifacts and cleanup evidence. Only then write a bounded, versioned result
reference inside the worker attempt workspace. It names the Run, binding generation, exact
native artifact/receipt digests and effective terminal outcome. Use stable confined reads; a
workspace path, producer score, CLI exit code or unverified parent `succeeded` is insufficient.

Publish that reference create-only, then persist the worker result and terminal binding using
exact-generation CAS/idempotent operations. Result text and metadata contain only bounded
observations. Reading a successful bridge result must revalidate its native reference through
the bridge reader; the generic worker envelope digest alone does not attest native artifacts.

Crash handling must preserve these boundaries:

1. Crash before native delivery: follow native recovery; worker success remains unavailable.
2. Native delivery committed but worker reference absent: reopen and observe the existing
   native result; do not rerun solver/evaluator or deliver again.
3. Reference persisted but worker settlement interrupted: verify the same bytes and complete
   only that exact binding/attempt settlement.
4. Duplicate observer or stale completion: return the same verified terminal reference or
   reject a different generation; never delete the winning native artifacts.
5. Missing/changed native evidence or uncertain cleanup: retain `unknown`, with no successful
   worker result, new native receipt or publication authority.

## Implementation tasks and acceptance

The checklist below records the current integration slice. WSI-01 through WSI-06 are implemented on the integration branch; WSI-07 is the focused regression/release evidence gate. They do not reopen completed Feature 142 lifecycle acceptance.

- [x] WSI-01 Define the binding/result-reference DTOs, exact-generation CAS, Store migration,
  state mapping and bridge-only suspension handling. Cover duplicate admission and drift before
  implementing execution.
- [x] WSI-02 Extract the typed synchronous orchestration/control seam with default CLI behavior
  preserved. Prove shared-deadline identity, parent ceiling and stage cancellation without
  new model/provider calls.
- [x] WSI-03 Implement a fresh per-attempt adapter and explicit library dispatch/resume/read API.
  Reject unbound invocation, generic-resume bypass, wrong owner and already live native owner.
- [x] WSI-04 Compose controller process observers and cleanup with exact bridge authority.
  Cover registration failure, cancelled queued work, descendant cleanup, PID reuse, replaced
  attempts, service close and stale finalizers using local subprocess fixtures.
- [x] WSI-05 Implement native-only delivery plus create-only worker result references and
  read-only terminal recovery. Fault-inject every native-delivery/reference/settlement boundary;
  prove no second solver call, evaluator call, candidate publication or output promotion.
- [x] WSI-06 Implement pending-input/preparation-recovery projections and explicit owner-scoped
  reconciliation. Cover live/unknown owners, unchanged policy, answer then resume, terminal
  idempotence and cleanup uncertainty. Unknown cannot be resumed through generic worker APIs.
- [ ] WSI-07 Run focused bridge, WorkerService, automatic foreground/background, answer/resume,
  cleanup, candidate receipt and delivery regressions. Run the existing native E2E and release
  gates before declaring the integration complete. Record local fixture evidence separately
  from any later real-model or external-producer acceptance.

Likely implementation files are a new `automatic_solve_worker_adapter.py` and typed execution
module, narrowly scoped changes to `cli.py`, `controller.py`, `workers.py`, `models.py` and
`store.py`, plus `test_automatic_solve_worker_adapter.py` and
`test_worker_service_automatic_solve.py`. Final file boundaries should follow WSI-01/02, not
force an adapter-only change that cannot express the required states and authority.

This document was checked against current source and existing specifications only. No product
code changed and no tests, model requests, remote evaluators or producer campaigns were run
for this design review.
