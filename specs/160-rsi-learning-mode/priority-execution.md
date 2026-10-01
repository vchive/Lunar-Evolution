# RSI remaining work by priority — 2026-10-01

This is the current execution list, extending Feature 160 and the producer lifecycle SDD.
Code and HANDOFF evidence take precedence over historical gap descriptions and design drafts.
All validation in this iteration is local and provider-free.

## P0 — correctness and interruption safety

- Preserve caller cancellation and parent deadline across native attempt, receipt, output and
  publication boundaries; preserve the existing commit critical region and native-attempt-only
  intent deadline scope.
- Require policy-bound unseen pass and pass-rate regression evidence for transfer promotion;
  bind receipts to inputs, policy, memory and trial evidence. Legacy score-only approvals cannot
  establish the new controller approval identity.
- Persist holdout trial intent/result and budget before evaluation. Completed trials replay
  without another call or charge; uncertain calls require evidence-bound reconciliation.
  Runner/component/manifest/policy drift and budget refresh fail closed.
- Shared parent learning/holdout accounting is implemented: original counters/deadline and
  immutable external reservation receipts survive crash, replay and terminal resume. Both
  uncertain child trial and outer generation reconciliation consume parent unknown budget.
- Controller completed generation markers bind the actual independent admission checkpoint;
  hash-valid controller appends cannot turn pending memory into terminal successful learning.

## P1 — controlled runtime composition

- Bridge AgentLoop candidate artifacts into the process clean-room verifier using bounded,
  no-follow reads, separate Actor manifest and raw-byte digest checks, and immutable public input.
- Add an explicit governance gate before a new episode uses a memory snapshot, so revocation
  stops subsequent retrieval without rewriting the immutable snapshot or its digest.
- Complete Actor evidence now has a durable create-only sidecar and first-call claim. Unknown
  claims never restart the evaluator; exact completed replay is read-only. DRS composition passes.
- A configured generation coordinator automatically admits post-practice candidates using the
  frozen manifest, durable child trials and shared parent budget. Same-run inherited generations
  have explicit lineage; rejected memory keeps the parent and unknown blocks the whole run.
- `generation_revalidate_before_dispatch=True` enables one deterministic revalidation per new
  episode, using the same parent budget. Failure quarantines the generation and blocks the solver;
  unknown requires explicit reconciliation. Completed before-run checks replay without evaluation.
- A real local native producer fixture now covers bootstrap/broker/formal receipt/strict output/
  independent candidate evaluation/publication/archive/population/delivery/read-only recovery.
- Still open: external worker source/ownership and trusted
  unknown completion, complete producer recovery/transport coverage and real campaign acceptance.
  These must not be closed by fixture evidence.
- The opt-in local `DurableSolverGateway` now claims an episode before execution and persists
  full results before controller handoff. Completed application records replay without another
  call; `restore_result` repairs a missing controller wire. Pending claims never retry and only
  failure settlements are accepted. This local delegate/SQLite boundary does not authenticate
  external workers or implement unknown-to-success reconciliation.
- Active native broker cancellation now stops real blocked loopback HTTP I/O and reaps its
  exact worker; lost acknowledgement remains unknown. Original request deadlines/counts and
  publication gates are preserved. Controller process death and complete egress remain open.

## P2 — local diagnostics and later composition

- Add strictly read-only usage CLI diagnostics with nullable totals, unknown receipt counts,
  stage breakdown and explicitly estimated costs.
- Explicit controlled cross-solver memory translation and repeated-pass confidence policy are
  implemented as bounded local APIs. Translation only creates unresolved target drafts; Wilson
  marginal confidence evidence never replaces source/holdout/admission authority. Provider billing
  and model weight training remain separate acceptance/research work.

The local P0/P1/P2 slices are implemented; validation is recorded in tasks.md, validation.md and
HANDOFF.md. Official evaluators, external project launch trust/default project registration and
real campaigns remain open. Revalidation is a configured local policy/API, not a distributed or
background scheduler. The governance gates read trusted local latest heads and do not establish
historical database deletion/rollback protection or remote atomic leases. Confidence integration
with actual official campaign raw receipts remains separate from the explicit analysis API.
