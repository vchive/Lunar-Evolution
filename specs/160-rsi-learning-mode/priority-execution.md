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

## P1 — controlled runtime composition

- Bridge AgentLoop candidate artifacts into the process clean-room verifier using bounded,
  no-follow reads, separate Actor manifest and raw-byte digest checks, and immutable public input.
- Add an explicit governance gate before a new episode uses a memory snapshot, so revocation
  stops subsequent retrieval without rewriting the immutable snapshot or its digest.
- Still open: default holdout/quarantine scheduling, external worker source/ownership and trusted
  unknown completion, complete producer recovery/transport coverage and real campaign acceptance.
  These must not be closed by fixture evidence.

## P2 — local diagnostics and later composition

- Add strictly read-only usage CLI diagnostics with nullable totals, unknown receipt counts,
  stage breakdown and explicitly estimated costs.
- Later SDD: controlled cross-solver memory translation, shared control primitives and noise
  confidence policy. Model weight training remains a separate research track.

The listed local slices are now implemented; validation is recorded in tasks.md, validation.md
and HANDOFF.md. Shared parent learning/holdout budget, same-run cross-generation governance,
default scheduling, official evaluators and real campaigns remain open. The snapshot gate reads
trusted local latest heads and does not establish historical rollback protection.
