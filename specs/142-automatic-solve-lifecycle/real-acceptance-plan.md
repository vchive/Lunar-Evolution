# Feature 142 Phase B real automatic multi-file acceptance plan

**Date**: 2026-09-20
**Status**: Preregistration plan; no provider request has been made
**Related SDD**: [spec.md](spec.md), [plan.md](plan.md), [validation.md](validation.md)

2026-09-27 decision: the next fresh registration retains the previous real acceptance's model
and supported task. The historical effective request was `openai-compatible` / `glm-5.2` /
`chat_completions`; the configured `responses` mode and `gpt-6-astra` label were not the native
request identity. Freeze exact task/input and independent evaluation criteria bytes in the new
manifest. Native preparation generates a separate Python evaluator/profile whose observed bytes
must be retained and independently checked against those criteria. This is a new identity, root and
single attempt; it does not reopen or add requests to Feature 139. The registered Feature 142
budgets and six-stage evidence requirements below remain unchanged. No provider request was made
by recording this decision.

## Purpose and scope

This plan defines the next single real-model acceptance attempt after Feature 142 Phase B's
offline implementation and regression checkpoint. The attempt is intended to observe the
foreground native automatic multi-file path from contract intake through parent delivery:
preparation, candidate generation, isolated execution, independent scoring, validity-first
selection, and verified delivery.

The acceptance covers the foreground behavior implemented and verified offline: one shared
active-execution deadline, durable parent orchestration, unified `solve`/`resume`/`answer`
continuation, terminal precedence, read-only `solve_execution` status, and Phase B local process
ownership/cancellation cleanup. It does not enable or claim detached automatic execution or
establish WebAgent parity. It is a product closure observation, not a model quality study or a
provider authorization.

Feature 139 is a closed historical slot. Its evidence, registration, campaign root, and
`0/1` primary and joint outcomes remain unchanged. Feature 131 and Feature 134 evidence also
remain byte-for-byte immutable.

### Current preparation checklist, 2026-09-21

2026-09-22 update: [Feature 147](../147-acceptance-evidence-observer/spec.md) now supplies a
provider-free observation-manifest/ordered-receipt parser and a retained-directory byte inventory.
The parser reuses canonical native generation receipts and checks source digest, 12-step budget
and exact outcome. Its scope remains structural; every acceptance counter stays at `0/1`.
The inventory verifies bytes in a quiescent directory, not lifecycle semantics.
[Feature 148](../148-artifact-lifecycle-holdout-auditor/spec.md) now supplies a provider-free,
read-only semantic/lifecycle and holdout auditor. Its bounded request/report schemas, private
SQLite snapshot, rowid-ordered event reader, first-terminal-wins lifecycle checks, native artifact
adapter, and holdout receipt checks have local regression coverage. The auditor never registers,
launches, resumes, executes source/evaluators, or changes acceptance counters. Feature 149 now
supplies the provider-free cleanup-v1 receipt publication and runner/auditor wiring. Fresh records
with a verified cleanup receipt can pass the execution boundary; retained legacy three-file records
remain `execution_cleanup_unknown`, so an old chain stays unverifiable for primary eligibility.
Launch preflight/registration sealing and actual real-model acceptance remain pending. These
helpers do not authorize a provider request.

Feature 144 supplies the next candidate-response product checkpoint: invocation-local bundle
instructions, unchanged strict parsing, and canonical failed receipts with optional `phase` and
`failure_cause`. This does not register or launch the next real attempt. Before the manifest gate,
the new acceptance implementation still needs the following work:

1. Reuse the supported task and budget values below in a fresh measurement identity and directory.
   Build new measurement code against the selected, fully verified product; do not edit or invoke
   Feature 139's closed campaign helpers as a way to reopen its slot.
2. Bind the current lifecycle-enabled parent orchestration task, its execution identity, reciprocal
   child link and final delivery receipt. Do not reuse the historical interpretation where an
   intake-only parent could already be succeeded while the child was still running.
3. Retain the independent native/process cleanup receipt produced by Feature 149 for the fresh
   attempt, then verify canonical generation receipts with the current parser/Store contract. Preserve bounded
   failure phase/cause when present, and absence when unknown; neither field nor any later artifact
   can establish parser completion. Cover this observer with offline success, failure and tamper
   fixtures before preregistration.
4. Build the launch preflight and preregistration seal, then retain fresh supervision, read-only
   status and six-stage summary evidence, with an
   independent inventory/audit path. Freeze the actual product/measurement commits and all launch
   conditions only after this implementation's own offline checks pass.

The provider-free registration contract is now specified in
[acceptance-registration.md](acceptance-registration.md). Its canonical manifest/seal parser and
read-only checkout preflight are implemented and covered by 16 tests. This closes the offline
registration-preparation slice; it does not create a real manifest, campaign root, provider request,
or launch authorization. The remaining work is to construct launch-time material bytes and run the
preflight against a separately committed registration when a real attempt is explicitly authorized.

The limits, one-slot denominator and no-repair rules below remain unchanged. Feature 143 T009 and
Feature 142 Phase C are separate release work; this acceptance remains a foreground attempt.

## Admission gates

No provider request may occur until every gate below has a retained, inspectable result.

1. **Offline product gate.** The focused lifecycle suites, shared compatibility suites, full
   three-stage regression (current, archived historical and frozen registration), lint/compile
   checks, SDD prerequisite checks, and local link/diff checks
   pass on the candidate product. The regression evidence is retained separately from the real
   campaign evidence. Phase C implementation and validation are recorded separately; this plan
   does not supply its acceptance evidence.
2. **Immutable checkout gate.** The product commit is fixed, the worktree is clean, and the
   checkout is verified to equal the pushed `origin/main` revision. The exact commit value is
   written into the manifest at launch preparation; this document deliberately does not invent
   it in advance.
3. **Fresh identity gate.** The manifest contains a new opaque `registration_id`,
   `campaign_id`, and `attempt_id=attempt-001`. None may equal or alias an identity from
   Feature 131, 134, or 139. The new campaign root is absent before admission and is unique to
   this attempt.
4. **Manifest gate.** The canonical registration manifest is committed and pushed before the
   launch command. A read-only preflight verifies its commit, canonical bytes, digest, product
   pin, identity values, root, task/input/evaluator pins, provider/model identity, runtime, and
   all budgets. A changed manifest, dirty checkout, unpushed commit, reused root, or failed
   identity check stops before any provider call.
5. **Provider and task gate.** The provider/model identity, API mode, task bytes, input bytes,
   entrypoint, evaluator/profile, and holdout declarations are frozen in the manifest. Secrets,
   prompts, response bodies, endpoint URLs, and generated source are never placed in the public
   registration or report.

The concrete registration and campaign values are therefore **launch-time frozen values**, not
values to be guessed while this plan is being reviewed. An absent or unverified value is a
preflight failure.

## Fixed run conditions

The task may reuse Feature 139's supported fixture so that the acceptance measures the new
lifecycle rather than changing task difficulty: `limit.json` input, an `output/result.json`
result, and at least two Python source files. The independent criteria and eight deterministic
holdouts are fixed before launch; the generated runtime evaluator/profile are separately hashed
and retained in the new campaign. The old evidence is read-only and is not referenced as runtime
state. The eight actual historical `(limit,value)` probes are `(1,-1)`, `(1,0)`, `(1,1)`,
`(1,2)`, `(3,0)`, `(3,2)`, `(3,3)`, `(3,4)`; the old manifest's abbreviated list is not authoritative.

The following values are frozen in the new manifest unless a separate SDD explicitly supersedes
them before registration:

| Authority | Registered value |
| --- | --- |
| Ordinary/provider request timeout | 600 seconds |
| Preparation request timeout | 900 seconds |
| Preparation wall limit | 1,860 seconds |
| Solve wall limit | 3,000 seconds (50 minutes) |
| Provider request ceiling | 20 requests |
| Observed-token stop threshold | 160,000 locally accounted tokens |
| Population | 1 island, population 1 |
| Candidate search | 1 offspring, 1 round |
| Candidate tool-step ceiling | 12 steps per generation request |
| Holdouts | 8, at most 5 seconds each |

The solve wall limit is an **active execution** budget. After static validation and exclusive
execution admission, the controller records one monotonic start/deadline pair. Contract
compilation, evaluator preparation (including its lock wait), candidate generation, candidate
execution, scoring, selection, delivery checks, and publication all consume that one remainder.
Each request or local operation receives the minimum of its existing ceiling and the positive
remaining solve time. A phase check runs after expensive work and before publication.

The solve budget does not accumulate over human waiting or across explicit continuations. A valid
`awaiting_input` answer or admissible nonterminal recovery uses the same persisted policy but gets
a new execution identity and a new active execution. Observed solve-budget exhaustion is terminal
and cannot be repaired by `resume`, `answer`, detached relaunch, or an automatic retry. The run
does not use detached mode; Phase C availability does not change this foreground measurement protocol.

## Evidence chain and stage gates

The campaign retains an ordered, identity-bound receipt for each stage. Every receipt records a
schema version, stage outcome, bounded timing/budget observations, the preceding stage identity,
and SHA-256 digests of private artifacts. Missing, duplicated, conflicting, out-of-order, or
unbound receipts are failure or unknown and cannot be repaired from a later artifact.

1. **Contract and preparation.** Validate the task/input, compile and independently audit the
   generated evaluator/profile against the preregistered criteria, and freeze the eight holdouts.
   The observation manifest binds the generated evaluator digest, while the registration binds
   the earlier criteria digest; these distinct SHA-256 values are never assumed equal.
   Preparation succeeds only with verified contract, evaluator/profile and holdout evidence.
2. **Candidate generation.** Admit a candidate only when the native parser accepts a non-empty
   complete source bundle and the completion diagnostic is `completed`, with matching event/run/
   task/budget/candidate identities and retained source digest. A timeout, tool-budget stop,
   worker failure, malformed response, empty response, or missing receipt produces no candidate.
3. **Isolated execution.** Stage the complete source bundle and registered input in a fresh
   isolated workspace. Retain the entrypoint, process/native exit, output digest, bounded runtime
   observation, and cleanup result. Candidate source and self-reported output are not evidence of
   successful execution by themselves.
4. **Independent scoring.** Run the frozen evaluator against the registered input and execution
   snapshot. The evaluator owns validity and score; its typed report binds the candidate and
   execution identities. A producer claim or self-reported score is not admissible.
5. **Validity-first selection.** Record exactly one verified selection receipt naming an
   independently valid candidate and binding generation, execution, evaluation, and plan
   digests. Ranking cannot promote an invalid, unexecuted, or unscored candidate.
6. **Parent delivery.** Copy the selected verified source, input, output, contract, and score
   evidence into the parent publication package. Inspect the package read-only, verify reciprocal
   links and digests, and settle the parent only after the delivery receipt is durable.

## Phase A lifecycle observations

The real attempt must retain bounded observations that are specific to Phase A:

- The read-only `solve_execution` projection includes the persisted policy and origin,
  execution identity, current fixed stage, active/awaiting-input/terminal state, and a bounded
  stopping reason where present. It must not fabricate a live monotonic remainder from persisted
  wall-clock timestamps.
- One controller-owned orchestration task is created for the new lifecycle-enabled parent,
  reused on a legal continuation, and excluded from ordinary model-task scheduling. Its identity
  and discriminator are cross-checked against the parent and evolution child.
- The parent remains running while preparation, child evolution, scoring, and delivery are in
  progress. Parent success is legal only after verified delivery; child completion alone cannot
  publish success.
- A budget or cancellation terminal write retains Store terminal precedence and is idempotent.
  Late child results, scores, or delivery attempts cannot overwrite a recorded terminal outcome.
  This plan observes the recorded precedence if a terminal boundary is reached; it does not add
  a deliberate cancellation experiment; the campaign observes the implemented local cleanup
  behavior without treating remote provider cancellation as observable.
- Status, events, and retained public results contain bounded reason codes and identities only.
  Prompts, provider bodies, credentials, endpoint values, and arbitrary exception text remain
  private or absent.

## One-slot accounting and failure denominator

This feature has exactly one denominator: `attempt-001`, counted as `0/1` or `1/1`. The attempt
is admitted once after the manifest gate. The following actions are forbidden after admission:
provider retry, request replay, response repair, candidate fallback, automatic resume, slot
replacement, second campaign root, or a post-terminal provider call. A process interruption or
missing evidence is reported as failure/unknown, never inferred as success.

The public result reports separate bounded counts for preparation, parser-complete candidates,
execution, independent scoring, selection, parent delivery, and holdouts. Preparation may be
`1/1` while all later counts remain zero.

- `preparation_success=1/1` requires the verified contract, evaluator/profile, and holdout
  freeze.
- `primary_success=1/1` requires at least one parser-complete candidate, successful bound
  execution, an independent valid score, a verified selection receipt, and verified parent
  delivery.
- `joint_success=1/1` additionally requires all eight holdouts to match their registered
  expected outputs, clean native and process exits, verified cleanup, and no pending or unknown
  stage.
- Preparation failure, malformed candidate, worker failure, request or solve timeout, budget
  exhaustion, missing/unknown receipt, invalid score, failed selection, delivery mismatch, or
  cleanup uncertainty leaves primary and joint at `0/1`.

Known token usage is summed only from completed, identity-bound exchanges. Missing usage, status,
or cleanup observations remain unknown/null rather than zero or successful.

## Retained private evidence

The fresh campaign root retains, at minimum:

- canonical manifest, registration seal, product/task/input/evaluator hashes, and preflight record;
- request, transport, budget, and terminal ledgers;
- contract, input profile, frozen evaluator/profile, probe/holdout declarations, and their digests;
- `solve_execution` observations, owner/lock records, orchestration task and event receipts;
- generation receipts and source bundle for every admitted or rejected generation;
- isolated execution workspace snapshot, output, native/process exit, and cleanup observation;
- independent score report, selection receipt, and parent delivery package;
- expected and actual holdout results, bounded supervision records, public result, and evidence
  inventory.

The inventory is generated once after the attempt and is audited read-only. SQLite inspection uses
the retained read-only-copy path when needed, preserving database/WAL bytes. The postrun report
must expose only allow-listed metadata, stage outcomes, bounded counts/reason codes, safe output
or check summaries, and digests. It must not expose prompts, provider response text, secrets,
endpoint URLs, generated source, or arbitrary exception strings.

## Postrun decision and audit

The independent postrun audit recomputes the manifest and evidence inventory, verifies all stage
identity links and terminal ordering, checks the one-slot ledger, and confirms that the historical
Feature 131/134/139 inventories still match their retained hashes. It reads the campaign only; it
does not call a provider, execute generated source, execute an evaluator or holdout, resume a task,
repair a receipt, or rewrite a result.

The audit records the first failed or unknown stage and preserves later absent stages as absent.
It may report an honest `0/1`; a preparation result, holdout result, self-reported score, partial
source tree, or persisted intake success cannot promote primary or joint success. A successful
real closure is claimed only when the stated primary or joint gates are all evidenced.

## Explicit non-goals and limitations

- This plan is not provider authorization, a permission to bypass the manifest gate, or a claim
  that the registered model will succeed.
- It does not rerun WebAgent, compare WebAgent scores, or infer general quality from eight
  holdouts. WebAgent and prior model measurements remain reference history only.
- It does not enable detached automatic execution. Phase B process ownership and cancellation
  cleanup are implemented and covered offline, but this acceptance does not claim remote provider
  cancellation or detached behavior.
- It does not import OpenEvolve/Shinka producers, add remote scheduling, broaden retry policy,
  migrate historical databases, or alter the strict candidate parser.
- It does not reopen, resume, repair, replace, or rewrite Feature 131, 134, or 139 evidence.

Only the new manifest, campaign root, and this attempt's retained evidence may change as a result
of the run. The concrete launch-time identities, product commit, manifest digest, provider/model
record, and final outcome belong in the new registration and postrun artifacts after the admission
gates pass.
