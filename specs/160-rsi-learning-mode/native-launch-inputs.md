# Native RSI launch inputs

Feature 160 continuation, 2026-10-02. This slice delivers a complete original `SolverRequest`
and an approved frozen `MemorySnapshot` to one manually configured native producer. It extends
the trusted local lifecycle; it does not implement a complete solver gateway or memory promotion.

## Problem and scope

The retained native reader cannot attribute an old launch to an RSI request or memory. The native
launch needs to bind those inputs before any attestation consumption or target execution. A hash
added after execution is insufficient, as is a copy in the producer's writable work/output tree.

Add an independent `.rsi-input` directory in the reserved producer batch, with exactly
`request.json`, `memory.json` and `manifest.json`. The first two contain complete canonical original
records, including nested solver settings, practice charter, original budget and every approved
memory item's provenance. The input manifest pins both exact bytes and original file/directory
identities. The directory/files use private read-only modes, and native isolation permits only
the two exact regular files as read paths. It grants no input write directory or host record read.
Linux Landlock does not mediate chmod: profiles with read paths therefore also deny chmod,
fchmod, fchmodat and fchmodat2 through seccomp for the entire target. Ordinary work/output creation
modes and writes remain allowed; changing those files' permissions at runtime is unavailable in
this profile. This is a bounded permission gate, not complete filesystem metadata protection.

## APIs and ordering

`prepare_native_rsi_inputs(workspace, *, journal_id, request, memory)` returns an immutable
`NativeRSIInputDescriptor`. The descriptor retains copied canonical bytes, exact digest identities,
nullable original `deadline_unix`, two `read_paths` and `argv_fragment`.

1. Prepare the two inputs create-only, before constructing the producer intent.
2. Append `('--lunar-rsi-input-v1', manifest_sha256)` to the original target argv. This reserved
   marker must be a unique complete terminal pair; the native intent's existing argv digest thus
   binds the original complete input manifest without changing historical intent wire formats.
3. Build the original intent and its one-shot attestation.
4. `bind_native_rsi_launch(workspace, *, intent, attestation, artifact, inputs)` creates
   `native-rsi-launch.json` once. It binds the manifest, exact intent/attestation/bootstrap,
   episode/request/memory identities and fixed producer input filenames.
5. Native dispatch calls `validate_native_rsi_launch_inputs(..., require_unexpired=True)` before
   attestation consumption and again before gate release. It passes only the descriptor's two
   exact `read_paths` into the existing isolation policy. The target starts after the existing
   durable native registration and gate transition.

This local profile uses `working_directory='work'`. A producer reads
`../.rsi-input/request.json` and `../.rsi-input/memory.json` after release; output must be disjoint
from the input directory. No new C bootstrap control format, general runtime allowlist, inherited
credential environment or direct network authority is needed.

`validate_native_rsi_launch_inputs(workspace, *, intent, attestation, artifact,
require_unexpired=False)` is read-only: it takes no recovery lock, creates no directories and
does not consume an attestation. A legacy batch without any marker, staged input directory or
launch binding returns `None`. Any of these reserved artifacts requires the complete original
marker/binding; stripping a marker cannot downgrade a staged/bound RSI launch to a legacy launch.
Original history may be inspected after its deadline; such inspection grants no new dispatch.

## Durable and identity boundaries

- Input staging and binding hold the original no-follow directory descriptors and existing
  recovery lock. Every file is created exclusive, fsynced, and checked against its opened inode;
  its original directory names are rechecked. Existing or partial staging is never overwritten,
  deleted, repaired or implicitly retried.
- Manifest and binding records include their own original device/inode. Allocate each file
  exclusive, obtain its identity from its open descriptor, canonicalize that identity into the
  record, then write/fsync. The manifest digest enters the original argv/intent. Same bytes in a
  substituted inode, symlinked ancestors, hard links, changed modes and changed file bytes reject.
- Binding refuses any existing attempt deadline, attestation consumption, registration, evidence,
  receipt or publication. It allows only its own staging, recovery lock and empty ordinary
  work/output directories. It checks this admission boundary before and after binding, under the
  same lock used by the native attempt. Historical attempts cannot acquire an RSI label later.
- The complete request's memory digest must match the exact approved snapshot. Original contract,
  evaluator and environment pins must match the original intent. Attestation and installed
  bootstrap identity are verified; copied descriptor fields are not authority by themselves.
- Validation canonically reparses request and memory, preserving full item provenance, and rereads
  inputs after checking launch/installation records. A replaced record or alias is refused.
  Recheck the binding's named inode and exact bytes after reading the inputs as well, so a
  same-byte replacement between initial identity capture and the binding read cannot pass.

## Budgets and approval

The request's full original budget is retained without replacement, defaults or renewal. A
non-null `deadline_unix` must be finite and unexpired at preparation, binding and new launch/gate
admission. Native dispatch converts that original absolute deadline to its monotonic clock once,
then takes the earlier of that boundary, the caller deadline and intent wall allowance. Gate
validation checks expiry again but cannot recompute a later deadline or widen the original limit.
Solver/evaluator/unknown counters remain the controller's admission/accounting responsibility.
This slice narrows the native attempt, not a new end-to-end gateway lifecycle. Later candidate
evaluation/publication must still receive the original caller execution control; this input
helper does not synthesize that control or extend the request's authority into those stages.

The typed snapshot requires approved entries and verified provenance structure. This does not
replace a configured governed-memory admission gate, certify a ledger episode admission, prove
remote authenticity, or demonstrate that a producer used memory effectively. Delivery and causal
performance are separate claims. The input helper never constructs a `SolverResult`, starts a
worker/evaluator, refreshes a budget, publishes candidates or grants RSI memory authority.

## Local acceptance

Offline tests cover canonical deep copies, complete request/item provenance, original memory and
launch pins, exact argv marker, missing/broken/partial/late binding, expired dispatch versus
historical inspection, create-only replay, inode substitutions and no-write validation.

An actual native C target fixture must open both input files inside the existing isolation, produce
observable fixture output conditional on the complete request and approved memory contents, and prove input writes/host record reads
remain denied. Verify the binding is durable and target work absent before gate release. Missing
inputs, changed input during the pre-gate window and marker stripping must prevent target work;
after execution, repeated recovery reads original input bytes and never relaunches the target.
This fixture validates local input delivery, not a model-quality or official campaign result.

Real RSI solver gateway composition, independent native-to-RSI verifier/receipt mapping,
durable controller admission, real project trust/runtime profiles, native controller ownership
and actual OpenEvolve/Shinka campaigns remain separate work. No WebAgent, remote evaluator,
company platform, real model or credential file is used for this slice.
