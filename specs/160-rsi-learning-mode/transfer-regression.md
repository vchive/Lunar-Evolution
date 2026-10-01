# Feature 166 narrow slice: frozen transfer regression

## Purpose

The frozen transfer runner proves that one candidate can execute with a fixed memory snapshot. It
does not prove that a memory item transfers across tasks or targets. This slice adds a provider-free
comparison harness for the promotion decision. It does not start a solver, evaluator, subprocess, or
remote service; the caller supplies a deterministic fixture runner.

## Contract

`TransferRegressionSuite.run()` emits schema version 3 and evaluates every task under three immutable arms:

- `no_memory`: the canonical empty snapshot;
- `old_memory`: the currently active/previous snapshot;
- `current_memory`: the candidate snapshot being considered for promotion.

Each report also binds the old and current memory snapshot digests used by the run. The promotion
adapter rejects a report whose snapshot pair does not match the admission's current snapshot and
parent snapshot. Each arm runs each task at least twice. A task has a stable input digest, family, seen/unseen split,
and target identity. The manifest must contain both seen and unseen tasks, and at least two distinct unseen targets across at least two task families. Reusing one input digest across the two splits is rejected before execution.

The fixture runner receives `(task, memory_snapshot, repetition)` and returns a bounded
`TransferObservation` with pass, score, cost, accessed task IDs, and memory IDs. The harness records
per-arm means and score variance for scores, pass rates, and cost, separately for seen and unseen tasks. Any attempt to
report access to another task or to a memory ID outside the arm snapshot is retained as contamination
and fails promotion.

A report is eligible for promotion only when the current snapshot does not regress against either
empty or old memory on unseen tasks, does not regress on seen tasks, and improves the unseen score
against empty memory. The default additionally requires every current-memory unseen trial to have
`passed=True` (`min_unseen_pass_rate=1.0`), and allows no seen/unseen pass-rate regression against
either baseline. A high score cannot substitute for a failing official pass outcome. Explicit
noise policy may lower the minimum or increase `max_unseen_pass_rate_regression` /
`max_seen_pass_rate_regression`; these finite thresholds are bounded to 0..1, remain immutable for
the report, and must be supplied deliberately.

The canonical report includes the complete `RegressionPolicy`. Holdout and baseline receipt
digests bind the complete ordered manifest (including input/family/split/target identities), policy,
arm snapshot digest and arm evidence. Changing inputs or a threshold changes the receipts even if
aggregate scores happen to remain identical. The adapter revalidates those bindings and pass gates
before appending approval or activation.

Revalidation also derives foreign-task access from every raw trial and memory access from the
empty arm. Every such access must remain represented in `contamination`; clearing the flags and
rehashing the envelope cannot hide those observations. Schema v3 retains only old/current snapshot
digests, so report-only revalidation cannot reconstruct their allowed memory IDs. The suite checks
those against the actual frozen snapshots while recording the observations. These consistency
checks do not authenticate the local runner's assertions about what it accessed.

Policy-less legacy report objects retain their schema version 2 serialized shape and digest for
read-only inspection and failed-report quarantine. They cannot provide new promotion evidence:
the historical score-only eligibility flag does not establish the stricter pass gate. Existing
approved governance rows hold opaque receipt digests; migrating or revalidating those rows is a
separate durable promotion integration task, not an inference from the old digests.

`promotion_evidence()` produces the holdout and baseline receipt digests and the
boolean accepted by `MemoryGovernanceStore.transition(..., state="approved")`. The explicit
`MemoryPromotionAdapter` is the controller-facing bridge: it validates the report digest and all
three evidence fields, then appends `approved`; an explicit activation request appends `active` as
a second revision. A rejected report can still be inspected; it must not be used to set
`regression_passed=True`.

## Failure matrix

| Condition | Result |
| --- | --- |
| Missing split or fewer than two unseen targets | Manifest rejected before runner calls |
| Input digest appears in both splits | Split contamination error |
| Runner returns malformed/non-finite score or cost | Observation error |
| Runner reads another task or foreign memory | Report retained with contamination and rejected |
| Current unseen score regresses vs no/old memory | Report rejected |
| Current unseen score does not improve over no memory | Report rejected |
| Current unseen pass rate below configured minimum, including high-score failing trials | Report rejected |
| Seen/unseen pass rate regresses beyond configured tolerance | Report rejected |
| Inputs/policy/arm evidence change after receipt creation | Promotion evidence rejected |
| Raw foreign-task or no-memory access omitted from contamination, even in a rehashed envelope | Promotion evidence rejected |
| Legacy report lacks policy-bound pass evidence | New promotion rejected; inspection remains available |
| All gates pass | Report is promotable; governance still performs its own CAS and verifier checks |

## Boundary

This is an auditable local regression protocol, not evidence of real model quality. It intentionally
leaves real evaluator integration, statistical confidence intervals, task-family expansion, and
controller/governance orchestration to later slices. Hidden holdout material remains outside the
controller; only its digest and the provider-supplied observation cross this boundary.
