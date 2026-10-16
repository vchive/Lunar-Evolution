# Draft: independently pinned ready capsule for multi-episode DRS

Status: implementation in progress; not accepted. This is a capacity continuation
of `multi-episode-publication.md`, not a production runtime or BRS extension.

## Observed capacity failure

The actual three-child fixture completed its first publication and settlement,
then refused the next practice in `pure_preflight` with
`rsi_producer_episode_checkpoint_capacity_exhausted`. Its canonical checkpoint
was 70,438 bytes; the child staging entry was 33,338 bytes, including 30,379 bytes
of full ready evidence. The original ceiling remains 112 KiB. Reducing the
conservative reservation alone cannot make the three terminal checkpoints fit.
Failed/interrupted XMLs and the original source inventories remain retained.

## Decision and scope

Only `producer_multi_episode_publication=True` uses a pinned external ready
capsule. Stage the original full ready DTO and validate it through all existing
binding/input/plan/root gates first. Under the original staging permit and
checkpoint CAS, persist its canonical bytes create-only at the system-derived
`evolution/producer-batches/<journal_id>/lineage/rsi-ready.snapshot`.
The current staging entry remains preparing/ready/unknown with unchanged identity
and failure semantics. Its ready value is the explicit capsule reference below.
No legacy ready entry is retrofitted, rewritten or automatically compacted.

Reference fields are exactly `protocol`, `workspace`, `journal_id`,
`workspace_identity`, and `file_pin`. Protocol is
`lunar-rsi-producer-ready-capsule-v1`. Workspace is the original absolute canonical
path; workspace_identity retains the original device/inode. file_pin is an exact
`LineageSnapshotPin` for `rsi-ready.snapshot`, including the original parent,
device/inode, mode 0600, nlink 1, size, SHA-256 and timestamps. Capture the pin from
the newly owned destination, never from an existing disk file. The original
preparing→ready checkpoint CAS is the first durable acknowledgement of this pin.

Full capsule bytes are bounded at 64 KiB; the reference is bounded at 8 KiB.
Every full ready binding retains the original 32 KiB bound, and input bounds,
checkpoint 112 KiB, lineage batch cap and snapshot aggregate cap remain active.
Ready capsules count toward the same 64 MiB aggregate retained-evidence budget;
capacity is an upper bound, not a promise that every maximum-size run fits.
The opted-in pure preflight reserves its exact identity/request/memory growth and
the bounded reference before a new reservation or staging effect; each prospective
ready and complete checkpoint is still bounded before CAS persistence. Late
lineage/result growth may refuse and preserve the original obligation.

## Reader and API boundaries

The new helper module exposes:

- `persist_ready_capsule(workspace, journal_id, ready) -> reference`;
- `materialize_ready(ready, *, allow_capsule=False, expected_workspace=None,
  expected_journal_id=None) -> full_ready`.

Both helpers reject collection/scalar callbacks before serialization/path I/O.
The writer uses the existing held DirectoryChain/create-only snapshot mechanism.
The reader validates reference shape, bounds, exact workspace/journal and pins
before I/O; reads the derived file with no-follow descriptors; compares the
original pin before/during/after and rechecks it after canonical JSON parsing.
It requires full ready inputs and plan to agree with the reference association.
Ordinary full ready values retain their existing shape and validation path.
Capsule readers cannot launch, reconstruct a fresh permit/owner, acknowledge CAS,
refresh a pin, adopt an orphan file or fall back to current disk evidence.

Stager, original ledger selector, controller child sidecar/bridge, episode input
reader and publication owner/inspection materialize only when the immutable
run/checkpoint mode authorizes capsules. Original staging-history equality is
over the retained reference, not an expanded DTO copied back into state. Every
consumer still reparses the full original binding, inputs and native plan and
verifies original child sidecar, request/memory, root proof and receipts.

If the capsule exists but ready CAS did not finish, retain preparing/unknown and
the file; readback cannot adopt it or restage. Missing, changed, touched, linked,
symlinked, foreign-directory or equal-byte replaced capsules refuse without
execution/recovery writes. Default staging/single-child and CLI behavior remain
unchanged, and `production_admission=false`.

## Acceptance

Focused tests must cover create-only persistence, exact shape/pre-I/O gates,
canonical bytes, pin/directory/identity drift, original flag/history association,
partial file/CAS failure and read-only behavior. The complete three-child DRS
publication→practice memory promotion→target retry→historical replay must actually
pass with every checkpoint at or below 112 KiB, distinct original child identities
and no subprocess/network. Default single-child and staging/ledger compatibility
must pass on the same frozen source; independent source review and final CI/raw
source/tree audit remain required before merge. `all_rejected`, BRS and real
runtime/producer CLI remain separate open tasks.
