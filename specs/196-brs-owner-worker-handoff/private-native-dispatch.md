# PB-03h — private original-BRS native transaction dispatch

Status: design for the next implementation slice, based on `855b08e`. No dispatch
implementation or success-path acceptance is supplied by this document. PB-03g's
success retention/precommit facades are a prerequisite. The governing scope is
`owner-publication-bridge.md`; public native BRS remains refused.

## Original authority and shared implementation

Reuse the exact registered `_BRSLineageCheckpointOwner`: original controller TLS,
owner thread, held run lease, selected handoff/channel, captured head/payload,
running episode, started claim and absent result. Recheck that same original scope
at every boundary. Existing phase checks and exact adjacent CAS/readback determine
progress. No new permit registry, byte attestation, DRS flow context, dispatch lease
or mutation of BRS mode/options is needed.

The private entry consumes native drafts recovered through the original retained
reader; mailbox drafts or latest file pins cannot supply authority. It retains the
original context, strategy, sidecar, handoff pin, request, M0, plan and control.
The caller cannot substitute a callable lineage owner or reconstruct one from a
receipt, digest, resumed process or completed worker result.

Keep public `run_native_producer_bundle_publication_transaction` and
`commit_producer_bundle_publication` signatures and DRS-only owner gates intact.
Factor their bodies behind private shared cores as needed; the private BRS wrapper
selects only the exact original BRS method dispatch. Do not copy evaluation,
population projection, staging or commit algorithms. In particular, the existing
`producer_multi_episode_publication` flag is not a BRS authority switch.

## Boundary changes

| Area | Required private change |
| --- | --- |
| Transaction | An explicit original-BRS wrapper and shared-core dispatch to exact unbound owner methods; public `_validate_lineage_owner` / `_lineage_call` retain their DRS-only contract. |
| Population projection | Reuse `derive_population_state_after`'s implementation with explicit private owner selection and the same original prefix proof; do not add a second population algorithm. |
| Preparation | Original owner `validate_before` / `retain_before`, followed by actual native journal/anchor creation and the original prepared-reference pin, then separate evidence acknowledgment. No manufactured channel ready/ACK. |
| Staging / commit | Private exact-BRS dispatch to `retain_staged`, `verify_precommit` and `retain_terminal`, backed by PB-03g. Public commit still rejects BRS. |
| Controller / result | Not connected by this slice; mailbox service, detached result delivery and settlement remain separate PB-03 work. |

## Lock and control order

Source/configuration/continuation/evidence predicates run outside the publication
lock and short controller observation mutex. After each full observation, reread
the original native evidence, consume the original retained
`revalidate_after_observation` allowance, then check fixed owner/channel identity.
Do not acquire the already-held run lease in reverse order.

Native stage and commit call checkpoints both while waiting for a lock and after
acquiring it. The BRS checkpoint projection must inspect actual held-lock state,
not infer it from a stage name. While locked it uses only fixed identity, durable
evidence and the original numeric/local-cancellation revalidator; it must not replay
full owner/source/configuration hooks, control predicates or a caller clock.

Before the existing native unknown marker: verify stage and creator-pinned handoff,
run exact BRS `verify_precommit`, repeat native stage/handoff checks, consume that
same original numeric revalidator, and check the original channel. No callback may
intervene between final evidence and the marker. After commit releases its lock,
retain terminal evidence through the original owner facade and exact CAS/readback.

## Narrow outcome and interruption scope

Start with one original worker, first ordinal, initial native population window and
a nonempty admitted subset. All-rejected/retained-rejection branches remain
explicitly unsupported until the separate C1 → provenance P → C2 continuation is
implemented. Preserve any native formal rejection evidence; never synthesize a BRS
success descriptor, root result or memory update.

Any ambiguous CAS/commit/readback or lost response preserves durable evidence and
stale/poisoned authority. No fresh head adoption, rollback, automatic retry, new
claim, deadline refresh, successor or resumed owner follows. Publication success
alone is not result delivery/settlement.

## Required focused validation

Use only inert local files and fixed evaluator doubles installed before original
policy capture. Exercise the actual shared transaction/staging/commit kernels,
original handoff, journal/anchor and owner reference/evidence CASes. Prove distinct
before/reference/prepared/staged/terminal heads with running/started state, absent
result and unchanged M0/budget. Record owner-thread identity for every effect.

Reject public BRS calls, fake/subclass/instance-shadow owners, foreign thread,
missing lease, stale head, changed channel/nonce, duplicate entry, source/receipt/
handoff inode drift, staged material drift, cancel/timeout during final observation
and every ambiguous write/readback. Instrument callbacks to fail if invoked under
publication lock. Verify exact final-evidence/revalidation/marker ordering and that
all-rejected stays unsupported. Retain existing DRS/no-owner compatibility and all
failure evidence. Freeze exact source before installed-source/platform acceptance.

This design adds no scheduler routing, public flag, remote evaluator, production
runtime, solver campaign, serial successor or multi-machine service. Keep
`online_publication=false` and `production_admission=false`.
