# Implementation priorities — 2026-09-29

This plan continues Features 153–160. It reconciles the second Codex audit with the current
repository and does not reset existing architecture or historical acceptance evidence.

## Corrections to the audit

- Feature 142's second fresh real native acceptance completed with independently verified
  preparation/primary/joint 1/1 and eight passing holdouts. The old Feature 139 failure is retained
  history, not evidence that no successful native run exists.
- Feature 153 at `05d05ab` implements offline Shinka import, non-publishing local execution and
  scoring, atomic publication, population/delivery read-back, active execution controls and durable
  all-rejected terminal inspection. These are implemented, not missing work.
- Native bootstrap, process ownership/cleanup, broker IPC and contemporaneous output capture exist
  as tested slices. Their complete producer-to-publication admission is still open.
- RSI's transient missing-module import has been resolved. Its existing complete local fixture
  baseline contains 94 tests; fixture IDs do not imply real OpenEvolve/Shinka campaigns.

## P0 — Recoverable and reproducible baseline

- [ ] Capture the existing RSI implementation together with the already committed Shinka changes
  on a clean, reviewable integration branch, preserving the shared working tree.
- [ ] Persist full controller configuration, initial memory, request and result identities before
  exposing recoverable DRS/BRS execution. Reject contract/evaluator/environment/solver/actor drift.
- [ ] Resume terminal episodes idempotently without another solver invocation. A running/unknown
  invocation without a retained terminal result requires reconciliation rather than replay.
- [ ] Persist BRS wave membership and frozen parent; quarantine uncertain waves and make ordered
  memory merging recoverable without duplicate entries.
- [ ] Connect explicit result-backed reconciliation and controller continuation through API/CLI.
- [ ] Validate interruption windows, process restarts, competing controllers, receipt tampering,
  changed pins and terminal replay before claiming P0 completion.

## P1 — Real local evidence and producer delivery

- [ ] Add a local native SolverGateway and independent verifier that reopen retained candidate
  source, execution and evaluator evidence; locally rerun independent evaluation in an isolated
  snapshot before memory admission. Preserve the distinction from fixture LocalExactVerifier.
- [ ] Complete durable total-budget restoration and unknown/interruption treatment for producer
  transactions, with active-process cancellation and explicit cleanup evidence.
- [ ] Join native trusted output/request receipts to Feature 153 admission, local reevaluation,
  atomic archive publication and parent delivery. Complete broker egress/credential/recovery
  acceptance, not just brokered-request counts.
- [ ] Connect pinned OpenEvolve and Shinka launchers to scheduler/user entry points; run their
  separate real campaign acceptance only after the production boundary is complete.
- [ ] Run current/archived/frozen release regression and supported-platform checks, merge the
  reviewed integration and align public documentation with exact implemented scope.

## P2 — Learning quality and broader orchestration

- [ ] Implement deterministic curriculum ranking by verified coverage, diversity and declared
  failure boundaries, with stable identities and reproducible recovery.
- [ ] Validate frozen-memory transfer across independent local tasks; measure actual benefit before
  claiming improved general capability. LLM curriculum remains optional and separately bounded.
- [ ] Support producer imports into evolved/seeded populations and repeated admissions without
  changing historical lineage or watermarks.
- [ ] Incrementally adapt automatic solve and external producer execution to common WorkerService
  lifecycle/delivery where useful; this architectural convergence does not invalidate the already
  accepted native path and is not a prerequisite for its existing use.

All development checks use local fixtures or local subprocesses. This plan does not launch
WebAgent or remote evaluators. Real campaign evidence and implementation completeness remain
separate acceptance claims.
