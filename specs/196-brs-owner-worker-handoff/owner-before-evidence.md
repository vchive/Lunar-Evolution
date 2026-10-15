# Original BRS owner before-evidence construction

## Slice and boundary

This successor starts from `05cd548`. It adds only the private original BRS owner's
`validate_before` and `retain_before` facade: validate the original native prepared
journal/admission/population prefix, retain genuine before snapshots and descriptor,
then delegate the exact checkpoint to the existing `checkpoint_before` CAS.

The existing transaction and staging facades remain DRS-only. There is no worker
dispatch, evaluation, admission-reference pin, prepared-journal creation, publication,
mailbox result delivery, rejection, reconcile or successor implementation here.
`online_publication=false` and `production_admission=false` remain durable policy.

## Contract

- The exact registered original owner, owner thread, held run lease, selected child,
  running episode, started claim and absent result remain mandatory. Existing source,
  policy, native context/strategy, control, budget and captured-head gates still run.
- Validation accepts only exact journal/admission DTO shapes, exact bytes and the
  original native strategy. Run/journal/task/authority, handoff identity, admission
  bundles, config, population and live archive/state bytes must match. It returns
  the empty first-ordinal predecessor sequence and creates no retained files or CAS.
- The first successful validation retains an immutable journal/admission capture.
  Repeated validation may observe only that same capture; it cannot refresh a plan
  or permit a successor. `retain_before` requires that successful capture.
- Shared ready-capsule/snapshot accounting and bounded checkpoint serialization run
  before any snapshot or descriptor creation. Per-file bounds remain unchanged.
- Retention uses the existing create-only snapshots, source file pins, before
  descriptor format and full readback. Missing archive is legal only for empty
  original bytes, with its original parent pin retained. All source and descriptor
  pins are verified again by `checkpoint_before` before the original adjacent CAS.
- Source/configuration/control callbacks run outside the short observation mutex
  and workspace publication lock. This facade writes only retained evidence; it
  neither locks nor mutates the shared archive/state. Create conflicts, source drift
  or uncertain CAS/readback preserve evidence and poison the owner, without retry,
  cleanup, latest-head adoption or a manufactured DRS context.
- The original selected channel condition, selected nonce/digest and empty pending
  queues remain live before creates and after the final source/control callbacks.
  Only this retention scope adds the same fixed check immediately before CAS and
  under the original condition at wave advancement. Lost delivery/late close or
  cancellation after the durable write leaves the original captured head stale.
- Newly called methods, persistence helpers and live aliases are explicit original
  policy dependencies. Existing persisted policies are not migrated or backfilled.

## Focused validation

Use only genuine local BRS owner/claim/native-strategy fixtures and inert files.
Refuse subprocess, network, evaluator, transaction, staging and commit entry points.
Verify read-only validation, genuine missing/existing archive retention, exact one-field
owner CAS, compatibility with the original prepared pin/evidence acknowledgment,
repeat/foreign inputs, DTO shadows, source/config/policy/control drift, marker and
population refusal, pre-create capacity gates, source replacement during retention,
create conflict and durable CAS/readback failure. Preserve old DRS-only transaction
and staging owner refusal. Record actual focused/static outcomes separately.

## Development result

The final local product/test bytes pass **34 distinct cases: 31 new cases plus 3
original before/prepared, staged/terminal and retained-reader/prepared composition
cases**. Python 3.11.15 imports this worktree's own editable source. JUnit records
zero failures, errors and skips. Full `ruff check src tests`, `compileall src tests`
and `git diff --check` pass. This is development validation, not integrated Linux,
complete CI, production runtime or online BRS acceptance.

Ignored evidence is under `.lunar-evolution/reports/brs-owner-before-evidence/`.
The initial 24-case development run retains its 21 passes and 3 failures: two
fixture mutations were rejected by DTO construction before the intended operation;
one genuine closed-channel gap allowed before retention. The latter is fixed by
the retention-only channel gates and tested at entry, final source hook and
post-CAS close. The separate intermediate 24-case pass and initial 2-case happy
run are older mutable development sources and are not added to the final count.
