# Draft: multi-episode DRS publication and historical recovery

**Status: experimental implementation in progress; not accepted.** This document extends
the experimental [single-child execution flow](child-execution-flow.md). It does
not mark that flow, real runtime acceptance or multi-episode execution complete.
The existing Feature 153 publication contract and default refusals remain active
until a separately reviewed implementation passes the acceptance below.

## Problem and decision

The controller already describes target → practice → memory commit → target.
The native publication boundary cannot yet support that sequence in one original
workspace:

- `producer_bundle_transaction._ensure_initial_population_window` rejects any
  prior producer admission. The first child adds `producer_admissions`, so the
  second child cannot publish.
- `producer_bundle_recovery._terminal` compares the entire current archive/state
  to the selected batch's terminal after-digests. A legitimate successor would
  invalidate an older child's retained read and terminal RSI replay.

These limits are explicit in [Feature 153](../153-producer-bundle-publication-transaction/spec.md),
particularly its initial-window and immutable-prefix contracts. Neither removing
the history gate nor skipping whole-file digest checks is a valid implementation.

Choose **same-workspace, explicitly bound append lineage with historical
recovery**. Preserve the original controller, ledger, producer gateway, root
sidecar/proof, workspace and native context. Children retain distinct original
episode, request, journal, launch, attestation and candidate identities. A
separate workspace per child would introduce new workspace creation, runtime
mapping, ownership and cleanup contracts; that alternative is excluded here.

## Strict scope and compatibility

This slice supports sequential DRS producer admissions only. Every population
snapshot must remain `iteration=0`, `status=running`, with the same original
population configuration, native integrity authority and island count. Existing
ordinary iteration-0 baseline candidates may remain. No seed admission/commit,
seed-handoff record, offspring/outcome history, nonzero candidate iteration or
evolved/terminal population is admitted. Native candidate generation/parent
mapping remains the original producer-import mapping; RSI learning relationships
are recorded by episode parent and memory evidence, not invented native ancestry.

Proposed experimental Python configuration:

```python
RSILearningController(
    original_gateway,
    # existing ledger, producer root and stager configuration
    producer_child_execution=True,
    producer_multi_episode_publication=True,
)
```

The second option is independent, strictly boolean and defaults to `False`. It
requires the existing child-execution opt-in and exact original Python producer
gateway/ledger/stager. Unsupported configuration and BRS refuse before run
creation. Single-child opt-in alone does not authorize repeated publication.

The publication owner must also hold the exact fresh dispatch lease from the
adjacent original one-call child continuation. The lease exists only while that
continuation is executing, and binds the original state, child gateway, request,
historical memory and native plan. Construction and every subsequent observation
check the original provider/controller binding, started claim and running episode,
as well as the live DTO contents. Exiting the dispatch clears the lease even on
interruption. Opening an owner scope or reading ready/started evidence does not
create a lease. A separate read-only chain inspection may verify retained terminal
materials; it cannot create this owner, dispatch, acknowledge a checkpoint or
grant permission to publish.

For a new opted-in run only, retain the option, policy/dependency fingerprint,
original workspace identity, original run/proof association and bounded episode
capacity in the immutable RSI run request and every controller checkpoint. Check
all run and checkpoint revisions, including intermediate ones. Addition, removal
or replacement on resume/reconcile refuses. Legacy runs cannot be retrofitted.
Do not infer opt-in from disk files or from the presence of multiple candidates.

Keep existing binding, launch, plan, claim, prepared/staged/published journal,
manifest, receipt and population admission-event wire schemas unchanged. Default
calls retain their existing canonical bytes and initial-only gates. New lineage
evidence is an explicitly named opt-in sidecar extension, with independently held
pins in the opted-in controller checkpoint. It does not become a second ledger
or a replacement execution/admission receipt. CLI behavior remains unchanged;
`production_admission=false` and real campaign limits remain unchanged.

Excluded: seed/evolved imports, BRS or concurrent commit scheduling, new child
workspace lifecycle, automatic repair/retry, a production CLI, real toolchain or
project campaign acceptance, remote evaluator/worker/scheduler, service API and
model weight training.

## Evidence model

Use bounded, exact-shape, canonical JSON for new descriptors. Store files only
under system-derived `evolution/producer-batches/<journal_id>/lineage/`; callers
cannot supply a sibling path. Snapshot files are create-only regular single-link
files with the existing no-follow/read-before-during-after identity discipline.
Retain original raw bytes, size, SHA-256 and file/stat pins independently in the
controller. A sidecar's own self-digest never supplies its missing expected pin.

Three associations are distinct to avoid a circular digest:

1. **Before intent:** original run/root proof/workspace, episode/request/memory
   and native plan identities; original policy/authority/configuration; exact
   predecessor batch/terminal/lineage digest or an explicit genesis association;
   and exact before archive/state snapshots. Persist its held pins before the
   batch enters candidate evaluation/staging. The first before-snapshot must
   satisfy the unchanged initial-window contract; a successor before-snapshot
   must exactly equal the verified predecessor after-snapshot.
2. **Staged transition:** before-intent digest, original prepared/staged journal
   and manifest digests, ordered admitted candidate IDs, after archive/state
   snapshot descriptors, and unchanged authority/configuration. Construct it
   after existing staging has produced the exact manifest and projection,
   before the first final move. It binds the manifest; the manifest is not
   changed to hash this extension. Persist the descriptor and independently
   held pins using controller checkpoint CAS before commit.
3. **Terminal association:** after the original publication terminal is durable,
   retain that published journal/terminal digest with the already pinned staged
   transition in the original controller history. Verify its after-digests and
   candidate order agree. A successor cannot use a merely staged association
   as its predecessor. Do not rewrite the immutable descriptor to add the
   terminal digest after publication.

Snapshots cover exact before/after `archive.jsonl` and `state.json` bytes. Current
staging moves its after files at commit, so the new immutable evidence must be
retained separately before those moves. Copying a snapshot does not manufacture
authority: its bytes must match the original verified live/staged file and the
independently retained journal/manifest prefix and after-digests.

The checkpoint retains a bounded ordered collection of these existing batch
associations and its current verified terminal head. A pending association does
not advance the head. Keep full snapshots on disk, not duplicated in controller
JSON. This is a controller-owned projection of original publication evidence;
it cannot authorize a foreign producer, another run, a fork or current-disk
adoption. Existing native results remain the source of RSI result settlement.

The population `producer_admissions` event format remains unchanged. Under the
new branch, append one event to the exact validated existing event list rather
than replacing it. Reuse native population reconstruction/ranking and verify
complete candidate membership, active capacity, best candidate, stagnation and
integrity projection. An event list alone does not prove batch lineage.

A known `all_rejected` batch does not append candidates/events or advance the
publication lineage head. Keep its existing independently verified rejection
terminal and unchanged before/after archive/state evidence. It does not supply a
published predecessor or a reason to replay evaluation. The minimal acceptance
uses validity 1 throughout, so target threshold failure is not confused with
this separate rejection outcome.

The native receipt mapper currently preserves `solver_score=None`; its immutable
receipt wires do not carry scalar quality. The acceptance fixture must configure
the existing `target_judge` interface with a frozen report-threshold judge. That
judge reads the native evaluator report through the original evaluation-receipt
builder and verifies the receipt digest against both the published journal and
the mapped result before testing the report's `combined_score`. It must not
inject a score into `SolverResult`, infer quality from a producer envelope, or
modify native receipt/provenance schemas. "Original judge" below means this
original configured judge. Default native judging continues to accept a valid,
completed result when no separate quality criterion is configured.

## Fresh publication, locks and CAS

Continue to use the existing owning controller lock and native publication lock.
No extra ownership table or reusable durable execution permit is introduced.
The new authority comes only from the current original DRS owner, exact retained
opt-in and adjacent guarded child continuation; reading a lineage descriptor
cannot mint that authority.

For each child:

1. Validate original run/proof/policy, current controller checkpoint and original
   historical request memory. Verify every predecessor is fully terminal and
   its retained transition chain reaches the current exact archive/state head.
   Check the shared cancellation/deadline and capacity before reservation or
   a new staging side effect.
2. Retain the child's before-intent association from original verified bytes.
   Preserve existing durable child input, ready proof, atomic claim-before-running
   and one-call owner/thread continuation. The lineage path does not reclaim a
   started child or add another solver reservation.
3. Run the original scheduler, capture, prepared admission, independent native
   evaluation and per-candidate receipt construction. A completed low-score
   target may publish a valid candidate yet fail the RSI target judge.
4. Before native staging, revalidate controller head, predecessor terminal head,
   exact live prefix and retained authority under the publication lock. Derive
   the deterministic after-projection by appending only this original journal's
   admitted records/events. Retain immutable before/after evidence and the staged
   transition. The controller CAS acknowledges its pins before commit; owner
   admission hooks must track this acknowledged head rather than adopting a
   checkpoint observed later from disk.
5. Immediately before the original durable unknown marker/first final move,
   compare the original controller CAS head and predecessor association again;
   compare live archive/state to the before-snapshot and staged files to the
   after-snapshot. Verify retained file pins, handoff and original attempt anchor.
   A stale comparison refuses before any final candidate/archive/state change.
6. Perform the existing publication commit protocol. After its terminal is
   durable and original unknown marker cleared, verify the original terminal
   association and acknowledge it with controller CAS. Only this verified
   terminal head can admit the next child. Finish the original mapper/result,
   verifier and RSI settlement; do not substitute the archive's global best.

All acquisition follows controller owner → publication lock order. Pure native
publication/recovery helpers must not acquire a controller lock in reverse or
call arbitrary user callbacks while both locks are held. The implementation
must prove its owner-acknowledgment hook respects this ordering and the existing
admission observer's identity/fingerprint/CAS checks before integration.

A staged/unknown workspace marker, pending terminal association or partial
commit prevents a successor. Before-final-move interruptions retain partial
create-only evidence; after-unknown-marker interruptions retain the existing
unknown obligation. No deletion, overwrite, automatic repair, head reset,
attestation refresh or provider/evaluator replay is permitted. If the native
result and full terminal evidence are already durable, existing settlement may
complete against the original staged association. Publication-only evidence
without a durable native result retains the unknown gate. Missing original
precommit pins cannot be reconstructed from current files.

## Historical recovery

Legacy recovery still requires its original whole current archive/state
after-digests. New historical recovery is an explicit internal composition
requiring the original opted-in controller proof and independently retained
ordered batch/pin collection. It does not fall back to a weaker path when
legacy recovery refuses or discover authorization by scanning batch directories.

For a selected historical child:

1. Validate the immutable opt-in and complete controller/run history, original
   selected child/request/memory, original plan/claim/native result and selected
   published journal/terminal association. Reuse exact original authority,
   handoff, source/receipt/material and attempt-anchor checks.
2. Verify the complete bounded chain from genesis through the selected batch
   and every successor to the held terminal head. Each before-snapshot must
   equal the preceding after-snapshot byte-for-byte, size and digest; each
   snapshot file independently retains its own held inode/stat pin.
   Journal IDs, candidates and transition ordinals must be unique and ordered;
   there must be no fork, skipped batch or unknown/staged successor.
3. For every transition, verify exact archive prefix plus original plan-order
   admitted additions, original prepared/staged/manifest/terminal agreement and
   deterministic population state projection. Verify all retained material
   required by the native integrity boundary. Arbitrary appended rows, a valid
   JSON state or recomputed self-digests do not establish a successor.
4. Compare the current entire archive/state to the held head's after-snapshots
   and original terminal digests. Compare workspace identity and absence of the
   existing publication marker. Repeat observations around material copying;
   reject a changing controller head, bytes or file identity.
5. Return only the selected historical child's original candidate/result and
   receipts, using its historical memory. No source execution, provider/evaluator
   invocation, ledger/checkpoint write, directory/lock creation, reservation or
   reconcile takes place in the retained reader. Old after-digests remain exact
   authority for old snapshots; they are not replaced with today's digests.

Refactor the selected batch's terminal verification into immutable batch evidence
and current-head checks so the new chain reader can reuse the former without
recursive current-head recovery of each predecessor. Do not bypass retained
source/receipt/handoff checks or introduce recursion without fixed limits.

Completed run resume is read-only even after its dispatch deadline has passed;
it retains the old deadline and does not authorize new work. A nonterminal DRS
may prepare a genuinely unattempted future child only through its original
fresh intent/owner path after all prior evidence settles and the original budget
permits it. A retained ready/started/unknown child never gains a continuation
through recovery. BRS and foreign direct native calls cannot use this path.

## Budget, memory and bounds

Use the original RSI run budget and absolute deadline. The minimal campaign
reserves exactly three solver invocations, two target attempts and one practice;
the original evaluator/verifier ceilings still apply. No per-child deadline
renewal, second claim/reservation, independent episode budget or extra ledger is
introduced. Local evidence verification and snapshot retention do not count as
solver/evaluator dispatch; they still obey bounded IO and active admission checks.

Limit lineage batches to the original `max_episodes` capacity, at most eight.
Retain the existing archive/state/file/parser bounds. Before reserving or staging,
measure projected controller growth including lineage descriptors and original
historical memory: binding 32 KiB, request/memory input 8 KiB and checkpoint
112 KiB remain unchanged. A descriptor and aggregate snapshot storage bound must
be fixed by the implementation review within these existing limits. Reject excess
before effects; do not silently raise limits to accept the fixture.

Target 0 and practice use M0. Independently passed practice evidence permits the
existing `RSIMemoryStore.commit` to produce M1. Target 1's request, staged native
input and candidate evidence must bind M1; historical target 0/practice replay
continues to use M0. Basic approved practice memory does not imply holdout-governed
generation promotion or measured transfer benefit; those are separate extensions.

## Minimal three-episode acceptance

Use a fresh inert local fixture with the real controller/gateway/scheduler,
original native capture, Python handoff/prepared admission, independent evaluation,
publication/receipt mapping, verifier and memory commit. Forbid real subprocess
launch; replace only the lowest process/evaluator observation seams. Keep one
immutable scenario fingerprint and distinct per-episode source/output material.

| Episode | Original memory | Independent result | Controller behavior |
| --- | --- | --- | --- |
| `run-1-target-0` | M0 | Completed, validity 1, score 0.0 | Original target judge rejects the threshold; valid candidate still publishes. |
| `run-1-practice-0-0` | M0 | Completed, validity 1, score 9.0 | Persisted curriculum charter and target parent; independent verifier approves practice, commit M1. |
| `run-1-target-1` | M1 | Completed, validity 1, score 9.0 | New child/request/journal/launch/nonce/candidate; original judge accepts. |

Required positive assertions:

- Three distinct original child identities, three atomic claims before their
  own running episode, original root gateway/proof/workspace unchanged.
- Three publication batches and exact append-order candidate/event associations;
  each batch has immutable before/after evidence and the correct predecessor.
- Real receipt/handoff/attempt/admission links and per-child mapping, including
  the published Python handoff in evaluation receipt reconstruction.
- Persisted curriculum and correct M0 → approved practice → M1 binding; no
  fabricated high-level solver result or global-best substitution.
- Exact budget usage and original deadline; no new account or reservation during
  terminal replay. Measured checkpoint size remains within the original bounds.
- Reopened completed controller validates all three historical children against
  the final head. Ledger/file snapshots and observation counts remain unchanged;
  provider/evaluator hooks are never invoked by that completed resume.

Required refusal/interruption cases:

- Missing/false/nonboolean opt-in, legacy retrofit/removal, intermediate history
  drift, incompatible original root/ledger/workspace/policy and BRS selection.
- Prior seed/offspring/evolved/terminal population, configuration/authority drift
  or illegal native candidate parent/generation/iteration mapping.
- Stale controller CAS or native before-prefix at preflight, staging and final
  commit; a competing head must not publish a subset or consume another claim.
- Fork, reordered/skipped predecessor, duplicate journal/candidate, foreign run
  association, missing precommit pins or self-digest-only disk adoption.
- Rehashed old snapshot/lineage, current archive truncation/reorder/extra row,
  incorrect active/best/stagnation/integrity projection, source/receipt/handoff
  change, replaced/touched/linked/symlinked/oversized evidence.
- Child 2/3 interruption before/after claim, running, prepared admission,
  lineage acknowledgment, unknown marker, commit and native-result settlement.
  Preserve evidence; unknown forbids a successor and relaunch. Durable complete
  result permits original settlement only; publication-only stays unknown.
- Cancellation/expiry before the next child and at commit admission, unchanged
  original budgets/deadline on restart, and capacity exhaustion before effects.
- Legacy single-batch success/refusal/canonical bytes remain unchanged, including
  the existing whole current archive/state digest gate and unknown-marker refusal.

## Code task breakdown after design review

All tasks below are **pending**. Keep production/default paths disabled until
their combined acceptance and final-source validation pass.

| Task | Work and likely files | Prerequisite / completion evidence |
| --- | --- | --- |
| MEP-01 | Freeze new opt-in policy and sidecar shapes/pin/file/aggregate bounds; add strict pure parsing, dependency fingerprint and original-history validation. `rsi_controller.py`, `rsi_producer_gateway.py`, focused lineage helper module if justified. | Independent review of non-circular authority, default-wire compatibility, owner/CAS and storage limits. Pure/negative tests. |
| MEP-02 | Retain original before/after snapshots and staged transition create-only; bind exact prepared/staged journal and manifest. `producer_bundle_transaction.py`, `producer_bundle_intent.py`, `producer_bundle_staging.py`. | MEP-01. No new evaluation/publication authority; zero-final-write drift cases and retained partial evidence. |
| MEP-03 | Opt-in predecessor verification, append-event derivation and final current-head/prefix CAS through original publication lock/owner admission hooks. `producer_bundle_preflight.py`, `producer_bundle_transaction.py`, `producer_bundle_staging.py`, `evolution.py`, `rsi_python_controller_bridge.py`, `rsi_controller.py`. | MEP-01/02. Lock-order proof, same-iteration producer-only two-batch fixture, stale/fork/interruption/legacy refusals. |
| MEP-04 | Split immutable terminal evidence verification from legacy current-head checks; add explicit bounded chain/current-head reader and original child historical mapping. `producer_bundle_recovery.py`, `rsi_native_retained.py`, provider/replay composition. | MEP-02/03. Earlier child reads after valid successors, original pins preserved, complete-chain and source/receipt negative tests. |
| MEP-05 | Compose three-episode DRS with real memory commit, original budget/control and settlement/unknown recovery. `tests/test_rsi_child_execution_flow.py` plus focused publication/lineage tests. | MEP-03/04. All positive/negative acceptance above with subprocess dispatch forbidden; measured real checkpoint capacity. |
| MEP-06 | Frozen-source focused regression, Ruff, compileall, diff checks; final CI and independent source/tree audit; update completion evidence only then. | MEP-01–05. Unique test counts and exact source/CI revision; no real-runtime or production claim. |

MEP-01 pure contract tests and preparation of inert acceptance fixtures may run in
parallel after review. Product snapshot/CAS/history changes share publication
boundaries and must follow the dependencies above; use disjoint file ownership.
This document itself runs no acceptance and records no completed code task.
