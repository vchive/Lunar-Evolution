# Implementation plan and retained records

`EvolutionContext.trusted_native_execution` carries a typed process-local
`OpenEvolveNativeExecution`. It does not change `EvolutionConfig.to_dict()` or legacy configuration
digests. The OpenEvolve strategy branches before legacy subprocess/evaluator work and refuses
missing injections when a trusted companion remains.
Its constructor first inspects the archive read-only, refusing retained seed stage/backup trees
before the ordinary writable archive constructor can automatically repair or delete them.

`producer_launch_inputs.py` owns config/manifest preparation and launch binding. It grants only
the exact config path, reusing held-directory/no-follow and native one-time attestation boundaries.
`native_trusted_attempt.py` validates either this descriptor or RSI inputs at consumption, gate,
terminal and recovery boundaries. Dual markers are rejected; legacy no-input bytes remain intact.

`openevolve_native.py` owns the companion admission transaction:

| Record | Meaning |
| --- | --- |
| `admission-claim.json` | Create-only started ownership, original immutable execution binding and total deadline |
| native batch records | Existing attestation/registration/bootstrap/deadline/cleanup/broker/capture/formal receipt authority |
| `admission.json` | Native receipt, envelope and native plan pins, plus separate local seed evaluator receipt and seed identity |
| canonical `evolution/` | Existing atomic source/record/receipt/archive/state/seed commit transaction |
| `completion.json` | Create-only acknowledgement binding admission and exact canonical byte/inode snapshots |

Companion checkpoints are 0400 and self-inode-bound, canonical bounded JSON with checksums and
fsynced contents/directory entries. First-call ownership is O_EXCL; a concurrent or interrupted
claim never repeats effects. Native workspace and canonical workspace remain distinct.

Admission uses `admit_producer_envelope()` once. `recover_retained_seed_admission()` rechecks the
fresh generic manifest against independently pinned local receipt, source, candidate record,
evaluation report and provenance. `CandidateArchive.validate_initial_seeds()` then validates the
whole canonical commit. Neither prepared native drafts nor producer scores substitute for the
local exact evaluator. Generic seed dependency/environment identities have explicit separate fields.

Conservative monotonic-before-unix mapping fixes the original total budget once. Parent remaining
time is sampled before its callback and can only narrow that control. Native cancellation polls
ownership loss. Cooperative evaluators receive a temporary budget hook restored in `finally`.
Publication callbacks are followed by input/claim/admission/native material revalidation before
commit; the atomic commit/acknowledgement region has no late cancellation/timeout gate. First
success and completed replay both perform strict read-only evidence validation before returning.

Unknown settlement, cross-boot success, full historical rollback resistance and Python project
runtime inventories remain outside this transaction. Generic config preparation accepts arbitrary
canonical non-contract data; the strategy itself requires its exact generated credential-free
config. This boundary is not a general secret scrubber.
