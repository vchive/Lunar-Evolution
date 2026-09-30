# Feature 153 quickstart

The bounded offline native transaction is available as a Python API. It consumes prepared drafts
from an existing producer export, locally executes and independently evaluates them, and atomically
publishes the admitted subset. It does not launch Shinka, a scheduler, a remote service, or a real
campaign.

```text
quiescent Shinka programs.sqlite export
  -> explicit bundle grouping and ProducerBundleDraft values
  -> Feature 152 ProducerBundleAdmissionPlan
  -> immutable journal.prepared.json
  -> non-publishing native execution/evaluation and retained receipts
  -> atomic stage/commit
  -> archive/state/active-population read-back
  -> population resume and existing delivery APIs
```

The caller supplies an existing initialized `PopulationStrategy` with a native multi-file pipeline,
plus `drafts` from `prepare_producer_bundle_drafts()` and an `admission_plan` from
`build_producer_bundle_admission_plan()`. Its stored population must have `iteration=0`,
`status=running`, no prior offspring history, no seed admission and no prior producer admission.
Constructing a strategy object alone does not initialize that state. This example is an integration
hook for a caller that already owns it; it does not use private initialization methods.

```python
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionControl
from lunar_evolution.producer_bundle_transaction import (
    run_native_producer_bundle_publication_transaction,
)

# Create this once before preparation, and keep it for any in-process retry.
control = SolveExecutionControl(300)
# strategy, drafts and admission_plan are prepared under the same caller-owned control.
workspace = strategy.context.workspace
journal_id = "shinka-import-001"
batch = workspace / "evolution" / "producer-batches" / journal_id
batch.mkdir(parents=True, exist_ok=True)

result = run_native_producer_bundle_publication_transaction(
    workspace,
    strategy,
    drafts,
    admission_plan,
    journal_id=journal_id,
    run_id="local-import-001",
    parent_task_id="population-task",
    task_id="shinka-import",
    execution_control=control,
)
print(result.publication_status)
print(result.admitted_candidate_ids, result.rejected_candidate_ids)

if result.publication_status == "published":
    # Continue native search from the committed population.
    resumed = strategy.resume()
```

Use a fresh journal ID for a fresh import. `journal.prepared.json` records the complete request
before the first candidate runs; `journal.json` later records staged/published adjudications.
An exact retry after a pre-stage interruption may reuse completed retained execution/evaluation
evidence. Supply the same drafts, plan, journal/run/task identities and budget pin; changed intent
is rejected before another execution. After publication, continue through `strategy.resume()`;
reinvoking the import transaction is not the population resume path.

The native runs remain at their original `evolution/bundle-attempts` paths. Staging and commit
verify retained bytes and file identities before publication. Imported candidates receive Lunar's
local scores; Shinka metrics remain provenance. Admitted candidates enter the archive, while native
ranking and island capacities determine active membership. The transaction checks archive integrity
and the full committed state/population; offline tests also publish and inspect the selected
candidate's material through existing delivery APIs.

`all_rejected` leaves archive/state unchanged and returns `result.terminal_journal`. It retains
the prepared intent, native evidence, rejection receipts and durable terminal journal. An exact
retry independently checks that terminal and returns `evaluations=()` without executing candidates.

`execution_control` shares a fixed active deadline and checks cancellation at stage boundaries,
including lock waits and the last checkpoint before commit. Existing parent limits can only
narrow it. The budget digest is derived from the actual declared limits; supplied digests must
match and cannot disable a previously pinned control. Once the commit critical region begins,
the atomic protocol finishes without a new deadline check.

This clock is process-local. Cross-process elapsed-budget restoration, immediate cancellation of
an active subprocess and the full unknown/interruption recovery matrix remain open. Keep uncertain
evidence for recovery; do not delete it or change the request to force a replay. This API is
separate from the existing `evolve --producer-result` CLI seed warm-start route.
