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

- [x] Capture the existing RSI implementation together with the already committed Shinka changes
  on a clean, reviewable integration branch, preserving the shared working tree.
- [x] Persist full controller configuration, initial memory, request and result identities before
  exposing recoverable DRS/BRS execution. Reject contract/evaluator/environment/solver/actor drift.
- [x] Resume terminal episodes idempotently without another solver invocation. A running/unknown
  invocation without a retained terminal result requires reconciliation rather than replay.
- [x] Persist BRS wave membership and frozen parent; quarantine uncertain waves and make ordered
  memory merging recoverable without duplicate entries.
- [x] Connect explicit result-backed reconciliation and controller continuation through API/CLI.
- [x] Validate interruption windows, process restarts, competing controllers, receipt tampering,
  changed pins and terminal replay before claiming P0 completion.

## P1 — Real local evidence and producer delivery

- [x] Add a local native SolverGateway and independent verifier that reopen retained candidate
  source, execution and evaluator evidence; locally rerun independent evaluation in an isolated
  snapshot before memory admission. Preserve the distinction from fixture LocalExactVerifier.
- [x] Restore the same producer deadline across same-boot process restarts. Bind it to the original
  prepared intent, clock identity and boot; reject missing/replaced evidence and budget refreshes.
- [x] Bind durable AgentLoop Actor profiles to runtime/receipt settings, implementation and paths;
  opaque runtime configuration cannot silently resume under the same display name.
- [x] Poll the original control during native candidate/evaluator execution, terminate the owned
  process group on cancellation/expiry, and persist interruption/cleanup evidence. Unknown cleanup
  never becomes successful completion or publication.
- [ ] Complete explicit unknown producer reconciliation across process restart. Retaining a
  deadline and stop evidence alone does not resolve an uncertain process outcome.
- [x] Retain trusted output preparation as immutable evidence binding process/capture/request
  journal, explicit source groups, native drafts and admission plan. This receipt still grants no
  publication authority while complete egress authority is missing.
- [ ] Join native trusted output/request receipts to Feature 153 admission, local reevaluation,
  atomic archive publication and parent delivery. Complete broker egress/credential/recovery
  acceptance, not just brokered-request counts.
- [ ] Connect pinned OpenEvolve and Shinka launchers to scheduler/user entry points; run their
  separate real campaign acceptance only after the production boundary is complete.
- [x] Run local current/archived/frozen release regression and a final affected-module supplement;
  record exact versions, counts and platform skips in `integration-validation-20260929.json`.
- [ ] Complete Linux/supported-platform CI and merge the reviewed integration to the default branch.
      The full release workflow now includes macOS/Python 3.12 alongside Linux/Python
      3.11–3.13. Remote workflow results and the default-branch merge remain pending.

The broker preflight now rejects URL userinfo/fragments/ambiguous authority and caller-supplied
authority, proxy, hop-by-hop, framing, control-character, and case-insensitive duplicate headers
before worker launch. Unknown native-attempt inspection snapshots retained interruption receipts
by inode and bytes before and after validation, rejecting replacement or concurrent terminal
evidence. These are defensive slices only; DNS pinning, complete egress proof, owner-checked
post-crash cleanup, publication/delivery, and real launcher acceptance remain open.

## P2 — Learning quality and broader orchestration

- [x] Implement deterministic curriculum ranking by verified coverage, diversity and declared
  failure boundaries, with stable identities and reproducible recovery.
- [x] Reconstruct curriculum feedback from retained practices in the durable controller; reconcile
  uncertain observations before selecting another practice. Initial catalog/history are pinned.
- [x] Implement a frozen-memory comparison panel against an empty-memory baseline with independently
  verified native runs, equal task budgets and retained comparison evidence. Multiple declared
  contracts, improvements/ties/regressions, tampering and no-replay recovery have local tests.
- [ ] Measure benefit with a real model and independent held-out tasks before claiming improved
  general capability. Local fixture deltas prove the measurement path, not generalized learning.
  LLM curriculum remains optional and separately bounded.
- [x] Support repeated producer batches in an iteration-zero running population without seeds or
  offspring history; append immutable admission events and reject ID/provenance collisions before
  evaluating another candidate. Stage validation independently preserves history and integrity pins.
- [ ] Support evolved/seeded population admission while preserving lineage and outcome watermarks.
- [ ] Incrementally adapt automatic solve and external producer execution to common WorkerService
  lifecycle/delivery where useful; this architectural convergence does not invalidate the already
  accepted native path and is not a prerequisite for its existing use. The exact binding, state,
  cancellation and delivery contract is recorded in Feature 142 `worker-service-integration-design.md`;
  implementation tasks WSI-01–07 remain open.

All development checks use local fixtures or local subprocesses. This plan does not launch
WebAgent or remote evaluators. Real campaign evidence and implementation completeness remain
separate acceptance claims.

## Integration and evidence

Development is isolated on `codex/rsi-recovery-integration` in
`/tmp/lunar-rsi-integration-20260929`. The original shared workspace is preserved. Commits are
pushed incrementally; their presence on this branch does not mean they have merged to `main`.

P0 is implemented and focused recovery/store/CLI/curriculum validation passes (80 tests on
2026-09-29, `/tmp/lunar-unknown-reconcile-10.xml`). This includes interrupted launches as well as
persisted `unknown` results reconciled to timeout/abandonment. P1 and P2 remain open wherever a
checkbox is unchecked. A complete release test result and actual campaign efficacy must be
reported separately from these local checks.

Local release runner completed with exit 0: current 8,338 passed / 7 platform skips, archived
2,294 passed, frozen registration 24 passed. Native offline E2E separately passed 226 cases.
The current phase collected before the last producer tests were added; a final 70-case affected
suite passed and covers all 14 added tests. Final inventory is 8,359; these overlapping counts
are not added together. The versioned JSON above retains report hashes and scope limitations.

The follow-up focused release was rerun with the worktree `.venv`: all four previously surfaced
current-suite failures passed in isolation, and the affected producer/transport suite passed
54 cases. A system-Python invocation is invalid for the installed-CLI test and must not be
counted as a product failure. The 2026-09-29 full runner invocation using system Python reported
8,376 passed / 10 skipped / 4 environment failures before this correction; archived 2,294 and
frozen 24 remained green. A correctly configured full current rerun is still recommended before
release publication.
