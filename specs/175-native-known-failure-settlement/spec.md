# Feature 175 — Known native failure settlement

Status: local implementation and focused validation complete; final-head CI and merge pending. This continues Features 156/157/160/169/173/174.

A native process that exits nonzero or is formally cancelled currently leaves an RSI started
claim because the scheduler only returns published candidates. Add an explicit process-only
failure outcome and an evidence-bearing registration path. Do not infer failure from exceptions,
callback values, generic worker labels, missing output, EOF, or cleaned unknown observations.

## Required behavior

1. Accept only the existing process-terminal-v1 `exited_nonzero` with a nonzero exit code or
   `cancelled` with a null exit code. Require original consumption-v2 deadline binding,
   registration, handoff, accepted start, current boot, exact process terminal and verified
   cleanup with `alive_after=false`. Reuse read-only native filesystem recovery and the pure
   chain verifier. The cancelled variant may bind the exact unknown bootstrap handshake only
   where the existing formal recovery accepts it.
2. Preserve the live attempt's independent broker path, identity, SHA, byte count and inode pins.
   Read the closed journal under those original pins. A live `complete=false` stop observation
   may be accepted only after this read proves no active, timed-out or uncertain request. Never
   derive zero requests from absent output or reconstruct a lost original pin from today's file.
3. New `run_native_trusted_producer_outcome` returns a distinct frozen failure DTO or the existing
   success run. It invokes the attempt once. Its verified failure branch occurs before sticky
   post-attempt cancellation and successful output checks, and performs no evaluator, candidate,
   execution-success receipt or publication work. The old success-only API stays unchanged.
4. A separately named canonical create-only RSI failure sidecar binds complete request/plan,
   historical memory/input binding, original native records and broker pins, original ledger
   path/device/inode and original claim (including created_at). Provider failure support is an
   explicit optional `failure_ledger` wiring, frozen before launch, shared with the gateway.
   The success sidecar schema and success DTOs remain unchanged. Conflicting sidecars refuse.
5. Map only to `failed` or `cancelled` SolverResult. Candidate, successful execution, evaluation,
   source and score fields remain null. Trace/provenance identify failure evidence explicitly.
   Every failed/cancelled replay requires the provider's actual read-only evidence reader and
   compares all mapped result fields with the immutable saved result.
6. `gateway.restore_failure(request, memory, expected_claim_sha256=...,
   expected_provenance_sha256=...)` only registers existing proof under the original claim.
   A started claim with no result or identical known failure may be settled; an immutable unknown
   or different result cannot be overwritten. Recheck original ledger identity around all reads
   and writes. Do not launch, signal, call a provider transport, evaluate or publish candidates.
7. `controller.reconcile_native_failure(run_id, episode_id, expected_checkpoint_sha256=...,
   expected_episode_record_sha256=..., expected_claim_sha256=...,
   expected_provenance_sha256=...)` uses the original controller lock, fingerprints, budget
   history, historical memory and checkpoint/episode CAS. Persist one evidence-reconciliation
   reservation before result registration. Identical retries reuse that reservation across
   result/episode/checkpoint crash gaps. Return the settled execution without automatically
   driving more practice, curriculum, judging or memory promotion. Evidence registration may
   occur after dispatch expiry; it never extends that deadline or solver allowance.

## Boundaries

No abandoned/timed-out auto classification, unknown recovery-v2 settlement, new cleanup or launch
rights, automatic unknown retry, or repaired original pins. A terminal persisted before the first
failure sidecar, with its live broker pin lost, remains quarantined. Bootstrap-death/pause independent
supervision, full containment/egress, sealed Python runtime, real adapters/campaigns and P2 multi-host
ownership remain separate gaps. Failure evidence proves this attempt's outcome, not complete host
containment. Current process terminal is v1; the required v2 is consumption with deadline anchoring.

Validation uses only inert local C/bootstrap fixtures, loopback and provider-free tests. No model,
WebAgent, remote/company evaluator, upstream campaign or `.env` access.
