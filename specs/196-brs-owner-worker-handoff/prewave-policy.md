# PB-03c — persisted original BRS checkpoint policy

Status: selection A implemented within Feature 196 at `399958c`; the frozen
402-case local acceptance and static/install/source checks passed. Final integrated
source CI remains separate. No online runtime availability is implied.

## Gap and smallest compatible selection

PB-03b pins `_policy()` only when constructing the private BRS checkpoint owner.
The original run record and its pre-wave checkpoints do not contain that policy.
The existing DRS `producer_multi_episode_publication_policy` cannot be reused: its
mode and facade remain DRS-specific. The genuine BRS owner fixture intentionally
uses a sidecar-bound inert gateway with both legacy child/publication flags false.

The selection is metadata-only: a newly created run with `mode=brs`, an
original producer sidecar and exact `plan.max_workers=1` retains the dedicated
`producer_brs_checkpoint_policy` object. No new public constructor or CLI flag is
introduced. Ordinary provider-free runs, DRS runs and multi-worker BRS runs retain
their existing field selection. Pin-only BRS runs in the selected class gain this
non-authorizing metadata; the private BRS owner consumes it as a mandatory
original-policy assertion. This does not require the legacy child/publication flags
to be true and does not change their DRS-specific policy contract.

## Durable contract

The selected policy must enter the original create-run payload before its first
running transition and controller checkpoint. The exact same policy also belongs
to the original run fingerprint's solver settings and every controller checkpoint
in that run. The policy continues to declare `mode=brs`, `max_workers=1`,
`online_publication=false` and `production_admission=false`.

The private checkpoint owner must validate the current policy against the original
create-run record, original run fingerprint and complete checkpoint history before
construction and before mutation. Missing, added, removed or changed policy refuses;
neither latest state nor a later checkpoint can repair the original record. Existing
runs lacking the pin are not migrated and cannot acquire a new checkpoint owner.
No JSON wire schema, SQL schema or descriptor format changes are required.

## Implementation boundary

- `rsi_controller.py`: mode-aware fingerprint inputs; original `_start_run` payload;
  `_flow_state`; original/historical policy validation; existing BRS selected pins
  and resume checks. No budget synchronization or source gate is relaxed.
- `rsi_brs_publication_lineage.py`: select the dedicated policy, retain original
  persisted policy identity and reject absent/drifting pins in the private owner.
- Focused inert tests: original pre-wave persistence, exact fingerprint/checkpoint
  identity, old-run refusal, altered original/intermediate/latest policy refusal,
  unchanged DRS/provider-free selection, and original before/prepared compatibility.

Every existing `_run_fingerprint` call supplies the original run or flow's mode/plan
when recomputing this metadata; the new keywords default to `None`, preserving the
previous projection for callers without explicit BRS context. Historical JSON
comparison may run under the existing observation mutex, but does not regenerate
the policy or invoke fingerprint/source/configuration hooks there. The existing
selected-pin and owner policy gates continue to recompute current dependencies
outside the short mutex. The new selection, policy and history validator identities
are themselves pinned dependencies.

This slice performs no dispatch, evaluation, publication transaction, staged or
terminal checkpoint, rejection C1/P/C2, recovery, retry, mailbox integration or
serial successor. Public native BRS remains closed. A retained policy is an identity
contract, never permission to execute or publish.

## Validation record

The initial development run passed 21 new cases with zero failures/errors/skips;
its original source map, argv, XML and exit remain in ignored
`.lunar-evolution/reports/brs-prewave-policy-20261015/development-1/`.
The separate frozen source is `399958c79e21fb300c661bd3366c58f21f24d546`, tree
`4892b1c0ae6290353cb92629657aa72a5d4bbc9a`. Its final four-process run passed
**402 = 21 new + 381 original** cases with zero failures/errors/skips. Disjoint
groups contain 73/166/134/29 nodes. All nine exits are zero: installed origin,
collection, four pytest groups, full Ruff over `src tests tools`, compileall over
the same scope, and `git diff --check`. All 2,038 tracked files match before/after.
The own-worktree Python 3.11.15 editable install was used without `PYTHONPATH`.

Exact module inventories, raw XML, argv/cwd, exits, source identity and evidence
digests are recorded in `publication-validation.md`; the raw directory is
`.lunar-evolution/reports/brs-prewave-policy-20261015/final-candidate/`.
Independent code review of the frozen product/test source passed with no blockers.
Use provider-free local fixtures only. This acceptance belongs to that source;
it does not claim the separate selected-owner terminal race fix is present or
replace final integrated-source validation.
