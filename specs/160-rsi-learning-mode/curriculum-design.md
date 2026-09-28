# Deterministic diversity and failure-boundary curriculum

## Scope

`DeterministicDiversityCurriculum` implements the existing `Curriculum.choose(...)` protocol
and returns the existing `CurriculumDecision`. It is a bounded, provider-free policy; it does
not execute a solver, infer a task command, call a model, mutate a ledger, or write memory.
Candidates explicitly declare a family, capability gap, strategy, expected result, failure
boundary, compatible solvers, and stable candidate ID.

This module can be used directly or injected into a durable controller. The default fixture policy
and CLI keep their existing deterministic selection. The durable controller pins both the initial
policy and its history, persists each selected decision, and rebuilds a fresh immutable policy from
retained prior practice evidence before selecting the next task. `observe(...)` never mutates the
initial policy. Uncertain observations are replaced by the explicitly reconciled episode on the
next reconstruction. Finished runs retain the final history fingerprint; resumed runs reuse their
persisted decisions without selecting or launching them again.

## Verified history

`CurriculumObservation` binds the selected decision to a durable `PracticeEpisode`. At the
execution boundary, `from_execution` verifies the request identity, exact practice charter,
result identity/status, and attached verifier decision. Reloaded observations must come from
the caller's reopened ledger, not producer-authored claims.

Only a completed episode with an independent verifier, matching contract/evaluator/environment
and candidate/execution/official receipt pins, and passing named checks counts as coverage.
A verified failure requires a matching independent decision containing a failed check. Raw
solver scores and `unknown`, `unresolved`, timeout, cancellation, abandonment, unverified failure,
or incomplete evidence do not provide either success coverage or a verified failure boundary.
These unresolved attempts remain quarantined and consume budget. Another practice may be selected,
but the policy never retries the quarantined task or reconciles its episode on the caller's behalf.
An uncertain target is rejected before practice selection.

Coverage and failure signals are scoped to the same contract, evaluator, environment, and solver.
Foreign-scope history still consumes declared attempt budgets but cannot imply transfer success.

## Selection contract

Semantic task aliases are deduplicated independently of candidate ID and share attempt budget.
Conflicting definitions of the same ID are rejected. Duplicate observations of the same durable
episode are idempotent; conflicting episode versions require explicit history replacement.

Eligible tasks are compatible with the target solver, below the attempt limit, and unquarantined.
Ranking is deterministic, in this order:

1. task has no verified pass;
2. task exercises a verified failed boundary;
3. family has no verified coverage;
4. failure boundary has no verified coverage;
5. declared capability gap matches the current diagnosis;
6. fewer attempts;
7. lower declared priority;
8. lexical candidate ID.

The decision carries a reason code and the declared practice charter. `choose(..., ordinal=0)`
returns the best task. `choose_wave` assigns distinct ranked tasks to a frozen BRS wave; duplicate
semantic tasks are never emitted in that wave. Repeating the same input is idempotent, not an
implicit reservation or budget debit. The caller must persist decisions before executing work.

Both total attempts and per-task attempts are finite, positive, bounded integers. Unknown history
consumes budget. An over-budget selection fails explicitly. Candidate and history iterables are
bounded before materialization, so an unbounded generator cannot hang policy initialization.

## Resume contract

`fingerprint()` covers the policy version, full candidate declaration (including aliases), and
both limits. Catalog input order does not affect the pin. `history_fingerprint()` separately
covers the immutable, sorted episode evidence. This separation lets a durable controller pin the
static policy at launch while persisting each selected decision and its evolving evidence.
The controller must reuse persisted decisions on resume and reject declaration drift.

`with_observation`, `observe`, and `with_history` create new policies. An explicit reconcile can
replace a quarantined observation using `with_history`; appending a conflicting version is rejected.
No policy method mutates controller state, approved memory, snapshots, or execution evidence.

## Validation

Focused provider-free tests cover verified family/boundary diversity, bounded repair selection,
unknown and unresolved quarantine, foreign-scope isolation, exact charter/receipt binding,
alias deduplication, conflict rejection, finite wave allocation, budgets, deterministic fingerprints,
and immutable history. These tests do not claim real model or real transfer-effectiveness acceptance.
