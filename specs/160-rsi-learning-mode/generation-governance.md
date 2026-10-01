# Generation-aware memory governance coordinator

## Scope and controller boundary

`RSIGovernanceCoordinator` is an explicit provider-free policy that becomes the default
admission/holdout/quarantine scheduler only when a controller is configured with it. The existing
single-snapshot gate and ordinary ungoverned controller API are unchanged. The coordinator owns
generation intent, item provenance, lifecycle CAS and the effective snapshot decision; the
controller owns candidate memory construction, solver execution and the shared run budget.

The coordinator is configured with one governance database, one RSI journal, scope, immutable
compatibility map and `GenerationGovernancePolicy`. Its component fingerprint binds policy,
database paths/device/inode and implementation, excluding evolving generation heads.

## Public interface

- `validate(snapshot)` accepts empty bootstrap memory or a fully active registered generation;
  every item must have its exact admission, independent source proof or inherited lineage, matching
  scope/compatibility, holdout/baseline receipts and an active source lineage.
- `admit_generation(generation_id, current_memory, parent_memory, source_verifiers,
  regression_runner)` automatically admits every item through `observed -> verified -> candidate
  -> shadow`, freezes both snapshots, runs holdout, and only then advances all items through
  `approved -> active`. Result status is active/rejected/unknown and `effective_snapshot` is
  candidate only for active; otherwise it is the validated frozen parent.
- The trusted local regression callback accepts immutable `GenerationRegressionRequest`, including
  generation ID, parent/current snapshots, regression policy, admission mapping and intent identity.
  It must expose an explicit fingerprint configuration hook and return a full
  `TransferRegressionReport`. The controller supplies its frozen task manifest, durable campaign
  and parent budget through this callback. It must not independently mutate governance.
- `reconcile_holdout()` registers an already-observed report and bound local evidence for an
  uncertain outer callback. It never invokes the callback or refreshes its budget.
- `revalidate_generation(generation_id, validation_id, regression_runner)` checks an active
  generation again; a rejected valid report automatically revokes all its admissions and returns
  the parent, while unknown results block retrieval until explicit reconciliation.
- `inspect(generation_id)` exposes the verified append-only generation journal.

## Full-snapshot provenance

Generation/snapshot identities and per-item admission IDs are deterministic and journalled before
governance writes. New items require an independent passing `VerifierDecision` with exact episode,
receipt and compatible contract pins. The item itself declaring success is insufficient.

Unchanged inherited items must exist in the validated parent and refer explicitly to their parent
admission and head digest. They are re-admitted for the new exact snapshot, retaining source
episode/verifier receipt and parent lineage; they still undergo this generation's holdout. Reusing
a parent memory ID for changed content is rejected. Dropped items do not gain a new admission.
The mapping must cover every item, and source revocation blocks descendant retrieval.

## Recovery and side effects

Generation journals use the existing controller lock, append-only hash chain and checkpoint CAS.
Each governance lifecycle write uses its current head digest. A crash between a completed item
transition and generation checkpoint can reuse the exact compatible head without repeating the
transition. Completed reports persist full trials and policy, not only a summary; replay rebuilds
summaries, validates report/policy/receipt digests, snapshot identity and access contamination.

The outer holdout callback has its own durable started/completed gate. A started outer callback
without a result must not automatically run again, even when its injected child
`DurableRegressionCampaign` can resume individual trials. A completed child's trusted local
report can be supplied to explicit outer reconciliation; otherwise the parent remains effective.
No unknown result is promoted or silently converted to a retry. A completed outer report is reused
without re-running the callback, including after a crash during approval/activation.

Rejected candidate reports leave candidates inactive and keep parent memory. During active
revalidation, the whole snapshot is blocked until a known result; a valid rejection quarantines
the whole generation via per-admission CAS. Partial revocation already makes whole-snapshot
validation fail, and restart completes remaining revocations without repeating holdout.

## Validation boundary

Focused local fixtures cover first/second generation activation, full inherited lineage,
missing/changed/non-independent proofs, policy/database drift, rejected/unknown holdout,
completed-callback replay, mid-admission/mid-activation crashes, evidence-bound reconciliation,
active regression quarantine, retrieval after source revocation, malformed/forged report and CAS
conflicts. Ruff, compileall and diff checks are required.

This local control plane does not authenticate external workers/evaluators, train model weights,
contact a provider, or replace the controller's shared budget. Real Actor/evaluator/campaign
acceptance remains separate from these fixture guarantees.

## Implemented local boundary

`rsi_governance_coordinator.py` implements the interface above. New-item source proof keys are
memory IDs; inherited items are omitted from that proof mapping and must match exact parent item
bytes. `GenerationGovernancePolicy.regression` freezes the transfer thresholds. Requests expose
`generation_id`, `parent_memory`, `current_memory`, `policy`, `admissions`, `intent_sha256` and the
optional `validation_id`/`manifest`; admission mappings and task manifests are immutable. A runner's
standard configuration hook may project `manifest: [task.to_dict(), ...]`; the coordinator freezes
that manifest in admission/revalidation intent, enforces policy coverage and the 1024-trial bound,
and rejects any callback or reconciled report whose tasks differ. Legacy explicitly trusted local
hooks without that field retain their prior callback-owned manifest contract.

Completed reports retain every trial and are independently reconstructed on reads. The generation
report and each completed revalidation must also match their completed outer callback, including
its request/runner binding. Pending revalidation has phase/status `revalidating`, blocks the current
snapshot and retains the parent; an older completed validation cannot clear a newer pending call.
Budget exhaustion and identity errors propagate to the parent controller while preserving the
outer started gate. The parent controller owns budget termination; the coordinator never refreshes
or replaces that account.

A standard runner hook can also project its `parent` run identity. The coordinator binds this
same-ledger/path/device/inode/request/planned-budget identity in both generation and revalidation
intent. Mutation lock order is parent run, then generation, then callback. Explicit outer recovery
prevalidates the complete report, expected callback checkpoint and bound evidence before reserving
one parent `unknown_retries` unit. Its idempotency receipt commits to outer callback scope/ID and
binding/result/evidence digests. A crash after the parent charge cannot consume a second unit;
changing the recovery evidence conflicts with the existing receipt. Completed exact reconciliation
replay verifies the existing parent receipt and performs no new charge. Child-trial recovery and
outer-call recovery are separate uncertain boundaries and each consumes its own recovery unit.
Recording already-observed evidence after a dispatch deadline never refreshes that deadline.

`inspect()` returns the verified generation checkpoint. For explicit local reconciliation,
`expected_checkpoint_sha256` refers to the *outer callback* checkpoint, and evidence binds the
callback's binding/result digests plus a named source and receipt digest. This is a trusted local
evidence protocol, not external worker authentication. SQLite history verification detects altered
hash-chain rows; without an external anchor it does not prove that an administrator has never
deleted/truncated history or restored an earlier database backup. Database path/device/inode pins
detect replacement during a configured coordinator's lifetime. There is no remote atomic lease.

Focused fixtures cover generation cases and a separate parent-reconciliation suite, including CAS
conflict, reconstructed-coordinator recovery, budget stop propagation, forbidden pending-validation
bypass, hidden current-arm contamination, zero recovery budget, charge/publication interruption,
evidence drift, same-ledger identity and deadline-preserving recovery.
The governance/callback/promotion/transfer supporting suite is also required when integrating the
controller. Production solver/model/evaluator acceptance remains open.
