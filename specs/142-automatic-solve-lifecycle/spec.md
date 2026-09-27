# Feature Specification: Automatic multi-file solve lifecycle

**Created**: 2026-09-20

**Status**: Phase A/B/C are implemented, pushed and pass offline acceptance, independent review,
full local three-stage regression and Linux/Python 3.11–3.13 CI. Exact checkpoints and release
closeout are recorded in [validation.md](validation.md).

**Input**: Continue product development using SDD; connect full automatic multi-file execution
budgets, parent/child cancellation, and local background execution using existing product controls.

## Problem

Feature 133 bounds evaluator preparation. Feature 137 bounds one active ordinary Controller
`run_agent()` or `resume()` execution. Neither currently supplies one deadline across automatic
contract compilation, evaluator preparation, candidate generation, candidate execution, independent
scoring, selection, and parent delivery. Those stages can each receive a fresh request allowance.

The automatic handoff also supersedes the generated parent tasks and settles the parent before
running its evolution child. An intake-successful parent can therefore become `succeeded` while
its child is still working, making cancellation through the parent ID ineffective. Existing
Controller cancellation handles run/task transitions, active runtimes, and runner process groups;
the missing work is orchestration and propagation between these existing boundaries.

Before this feature, automatic `--multi-file` rejected `--detach`. The ordinary detached-solve launch
contract is reusable, but its argument propagation and cleanup did not cover this pipeline. Local candidate
and evaluator processes use their own process groups, so terminating only the detached controller
group is insufficient.

## Scope and delivery phases

This feature applies to native population `solve --evolve --multi-file` and its conversational
continuations. It does not extend explicit bundle profiles, standalone `evolve-bundle`, single-file
evolution, or external producers. Existing behavior in those modes remains unchanged.

Delivery proceeds in three independently verifiable phases:

1. **Foreground shared budget and parent lifecycle**: one active execution deadline and a durable
   parent orchestration task keep the parent running until delivery or a real terminal outcome.
2. **Cancellation and process cleanup**: propagate cancellation through the verified parent/child
   relationship and stop every locally owned runtime, candidate, evaluator, and probe process.
3. **Detached entry points**: enable automatic background execution only after the cleanup
   acceptance tests pass. Until then, automatic `--detach` retains its existing rejection.

The design is ready for ordinary implementation without a new user attestation or approval flow.
Creating or running a real provider campaign is outside this feature's implementation validation.

## User interface

Add `--solve-wall-timeout SECONDS` to `solve`, `resume`, and `answer`. It is valid only for a new
native automatic multi-file solve or continuation of a persisted automatic handoff. The value
must be a finite number in `(0, 86400]`; booleans and malformed values are invalid. No ordering
constraint against the request or preparation budgets is required: a smaller solve budget may
legitimately narrow every stage.

An explicit value is persisted in `evolution_requested` as `solve_wall_timeout` with
`solve_wall_timeout_source=explicit`. Omission on a new handoff leaves the field absent and does
not introduce a new default limit. Omission on continuation restores the stored value; an explicit
continuation value must match it exactly. A legacy handoff cannot acquire a new policy on resume
or answer. Invalid modes, values, and overrides are rejected before runtime creation, Store/run
mutation, answer artifact creation, preparation, or provider admission.

`--timeout`, both evaluator preparation options, model-profile limits, candidate tool-step limits,
and existing run/task budgets remain independent ceilings. Effective timeouts can only become
smaller. The new option does not rewrite any of those policy values.

After phase 3, `solve --detach`, `solve --resume --detach`, `resume --detach`, and `answer --detach`
may use this automatic pipeline. They return the existing parent run ID, status, workspace, and
`detached` indication. Ordinary `status`, `events`, and `cancel` continue to operate on that ID.
No background thread or process remains waiting for an answer after `awaiting_input` is reached.

A successful launch adds `launch_status: accepted`. A still-nonterminal accepted run returns exit
code zero even if its existing `status` and preparation diagnosis briefly retain the previous
recoverable failure projection. An already observed terminal outcome uses the existing outcome
exit code. Launch acceptance is not completion. A terminal continuation returns its existing
handle without `detached` or launch acceptance and creates no worker.

## Budget lifetime: one active execution, not accumulated lifetime

One explicit foreground invocation or admitted detached worker owns one active execution. It
creates a monotonic deadline immediately before entering contract/preparation work, after static
validation and exclusive execution admission:

```text
deadline = monotonic_start + persisted_solve_wall_timeout
remaining = deadline - monotonic_now
effective_timeout = min(existing_stage_ceiling, positive_remaining)
```

The deadline covers contract compilation, evaluator preparation including its lock wait and local
checks, all candidate generations and local executions, independent scoring, selection, delivery
checks, and publication. It is shared by all participating workers. It is never recreated for a
new phase, request, candidate, retry, or nested Controller call. No positive remainder means no
new work is admitted. Phase checks also run after expensive work and before publication.

Static input validation and the already bounded input staging performed before execution admission
are outside this active execution budget. For detached work, the child starts the deadline after
claiming execution; process-launch delay and the parent's handle construction do not count. Status
must describe this as an **active execution budget**, not an elapsed-time promise from the initial
CLI invocation.

Human waiting is not timed. `awaiting_input` closes the current active execution, and a later
explicit `answer` starts a new active execution with the same policy. An existing recoverable
preparation failure or interrupted nonterminal run may be continued explicitly under its existing
integrity/recovery rules, also with a new active execution. This matches the active-execution scope
of Features 133/137. It does **not** bound the sum of all explicit continuations, user waiting, or
process downtime. No monotonic timestamp is persisted for reuse in another process, and this
feature does not introduce cumulative lifetime accounting.

Observed exhaustion of this new solve budget is a terminal parent failure. It cannot obtain a
fresh allowance through resume, answer, detached relaunch, or automatic recovery. A new user task
is distinct from continuing the exhausted task. An unobserved process interruption is not silently
reclassified as successful completion or as proof of a remotely completed request.

## Parent and child authority

For newly created lifecycle-enabled automatic solves, contract intake remains the existing
controller-owned intake task. After a contract is accepted and before preparation/handoff can
settle the parent, establish one controller-owned orchestration task. It is not executable as an
ordinary model task and is not superseded with the generated plan tasks. It remains unfinished
through preparation and child execution and succeeds only after verified parent delivery.

The same orchestration task and child linkage are reused on continuation. A repeated successful
continuation is read-only/idempotent and creates no candidate, execution, delivery, or background
worker. An awaiting-input parent remains resumable through the existing answer artifact contract.
Recoverable preparation failures retain the existing effective-failure/persisted-nonterminal
distinction. Cancellation and solve budget exhaustion settle the orchestration task terminally.

Persist a bounded lifecycle version marker in new automatic handoffs so continuation can select
the correct behavior. Historical terminal parents are not rewritten or retrofitted with tasks.
Legacy foreground handoffs retain their existing compatibility rules. Automatic background mode
requires the new lifecycle marker; it must not reinterpret a legacy terminal parent as active.

Implementation refinement (2026-09-20): the existing task schema needs one additive
`orchestration INTEGER NOT NULL DEFAULT 0` column. This explicit scheduler discriminator prevents
ordinary `next_task` and `claim_task` from executing a controller-owned task. Initialization adds
the column to a writable Store; read-only legacy task projection treats its absence as false.
Existing rows and historical run states are not reclassified. Task creation/reuse is transactional
and limited to lifecycle-enabled nonterminal parents. A workspace advisory lock supplements the
process-local owner so two foreground processes cannot enter the same active solve concurrently.

## Cancellation and cleanup

`cancel <parent-id>` reuses existing Controller/Store cancellation. Resolve only the verified,
reciprocally bound evolution child belonging to this parent and contract. Do not cancel unrelated
runs, infer ownership from directory names, or add a general recursive cancellation mechanism.

The child cancellation predicate observes both its own state and the parent authority. A parent
cancellation prevents new child requests, local executions, scoring, and delivery. A completed
child may retain its completed evidence while parent delivery is refused after cancellation.
Store terminal precedence remains authoritative: cancellation recorded first stays cancelled;
budget failure recorded first stays failed with one idempotent budget event. Late work cannot
replace either outcome with success.

Connect local preparation probes, candidate processes, and evaluator processes to the existing
process observer/ownership mechanism. Cancellation and deadline cleanup must reach their actual
process groups as well as model runtimes and the detached controller. Cleanup continues when one
callback fails. Stop owned work before terminating the coordinating background process, then
clear only that worker's runner ownership. Successful execution, awaiting input, failure,
cancellation, and failed process launch each release their own runner record.

This feature claims local admission, process termination, and evidence behavior only. It does not
claim that a provider stopped remote computation when a local request timed out or was cancelled.

## Immutable inputs and execution identity

The input bytes and their ledger bindings, contract digest, frozen evaluator/profile bytes,
candidate source identity, execution admission/plan pins, and evaluator specification remain
unchanged by a smaller remaining timeout. A process-local execution control is not serialized into
those immutable objects or their fingerprints.

Pass an optional narrower operational timeout and stop callback at the actual runtime/process
boundary; validate that they can only narrow the registered execution ceiling. Persist any new
effective-timeout observation as separate bounded execution metadata, without falsifying the
original plan, admission, profile, or receipt identity. Existing receipt inspection must continue
to verify the exact original authority. Never regenerate a frozen profile just to encode a new
remainder on resume.

## Status and diagnostics

Existing status projection gains a bounded `solve_execution` section for lifecycle-enabled runs:
policy seconds and origin, execution identity, current fixed stage, active/awaiting-input/terminal
state, and a fixed stopping reason when present. Persisted elapsed observations describe recorded
local observations; read-only status does not fabricate a live monotonic remainder from a UTC
timestamp. Prompts, responses, credentials, endpoint values, arbitrary exception text, and inferred
provider usage are excluded.

Solve-budget exhaustion uses the existing idempotent Store budget-failure mechanism with a
distinct fixed limit name for the solve policy. It must not mislabel that limit as the run's
different `BudgetSpec.max_runtime_seconds`. A cancelled parent retains cancellation if the budget
check arrives later. Status and terminal continuation never start work to fill missing evidence.

## Acceptance criteria

1. All supported entry points accept valid explicit budgets and restore exact persisted policy.
   Invalid bounds, incompatible modes, malformed stored values, legacy-policy injection, and
   continuation mismatches cause no runtime/provider/preparation/answer side effect.
2. A deterministic clock proves that contract, compiler, auditor, candidate generation,
   candidate execution, scoring, and delivery share one deadline. Per-stage/profile ceilings
   and preparation remaining time can narrow it further; no boundary enlarges another ceiling.
3. Exhaustion before admission, during a bounded operation, after a late result, and immediately
   before delivery prevents subsequent work and successful publication. Only one terminal budget
   event is recorded. Repeated continuation of that task starts no work.
4. The parent stays running while its child runs and becomes succeeded only after verified
   delivery. Legacy history is unchanged. Orchestration tasks cannot be claimed by the ordinary
   scheduler or be mistaken for contract intake on continuation.
5. Cancellation during every phase reaches the linked active child and all owned local processes;
   late responses, scored candidates, and delivery attempts cannot overwrite cancellation. An
   unrelated child/run is untouched, and cancellation/budget races retain the Store winner.
6. Existing user questions and recoverable preparation failures preserve explicit recovery.
   Answering or continuing creates one new active execution under the same policy, clearly
   distinguished from cumulative lifetime accounting. Terminal success remains idempotent.
7. All timeout/cancellation fixtures preserve immutable profile, input, contract, evaluator,
   source, admission, and plan identities. New observations accurately distinguish configured
   ceilings from effective operational timeouts.
8. Background entry points remain rejected until cleanup tests pass. Once enabled, fresh and
   continued detached execution use the same policy, honor one live owner, return a useful parent
   handle, expose status, respond to cancellation, and leave no owned process or stale runner.
   No secret appears in argv or public state.
9. Focused, shared, and full two-stage offline regressions pass. Feature 131/134 historical file
   sets, sizes, and hashes remain unchanged. Existing Feature 139 measurement artifacts and
   registration conditions are not rewritten by this product feature.

## Repeatable offline E2E regression (2026-09-27)

The existing regression runner shall expose `--suite native-e2e` for a fixed selection of
current-product automatic multi-file, foreground/background lifecycle, cancellation/deadline,
and installed-package integration tests. These tests use fresh local workspaces and fixture
runtimes; they do not register or launch a real-model acceptance campaign. The runner shall
verify that imports resolve to this checkout, collect the selected tests before execution, and
require the JUnit result to account for that exact collection with no failures or errors.
Platform skips remain visible and do not count as executed successes.

This profile shall not restore archived checkouts or require the historical regression
installer. It shall retain a separate `native-e2e.xml` report and label its output as offline
native integration evidence. User pytest selection and plugin environment settings must not
silently narrow the suite. Omitting `--suite` shall continue to run all three existing release
regression phases; the focused E2E profile does not replace that release gate or real-model
acceptance.

## Non-goals

No cumulative cross-continuation budget, remote cancellation promise, new provider request/token/
cost cap, external producer integration, generic background scheduler, new attestation flow,
automatic repair/retry, historical measurement rewrite, WebAgent rerun, real campaign launch, or
quality/parity claim is included. The only schema change is the additive task discriminator
described above; no worker registry or historical evidence migration is introduced.
