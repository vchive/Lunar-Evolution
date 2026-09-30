# Feature 166 narrow slice: frozen transfer regression

## Purpose

The frozen transfer runner proves that one candidate can execute with a fixed memory snapshot. It
does not prove that a memory item transfers across tasks or targets. This slice adds a provider-free
comparison harness for the promotion decision. It does not start a solver, evaluator, subprocess, or
remote service; the caller supplies a deterministic fixture runner.

## Contract

`TransferRegressionSuite.run()` emits schema version 2 and evaluates every task under three immutable arms:

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
against empty memory. `promotion_evidence()` produces the holdout and baseline receipt digests and the
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
| All gates pass | Report is promotable; governance still performs its own CAS and verifier checks |

## Boundary

This is an auditable local regression protocol, not evidence of real model quality. It intentionally
leaves real evaluator integration, statistical confidence intervals, task-family expansion, and
controller/governance orchestration to later slices. Hidden holdout material remains outside the
controller; only its digest and the provider-supplied observation cross this boundary.
