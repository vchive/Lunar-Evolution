# Clean-room verifier (Feature 160, P1 narrow slice)

`lunar_evolution.rsi_cleanroom` is a provider-free verifier boundary.  It is intentionally a
standalone interface; the RSI controller does not call it yet.  A future memory gate can persist
the returned `CleanRoomVerdict` and require `outcome == "pass"` together with its receipt.

## Inputs

`CandidateArtifact` accepts source bytes or one source path (exactly one), plus bounded dependency
bytes.  A path is opened with `O_NOFOLLOW`, checked as a regular file, bounded, and copied into a
new private workspace.  Optional expected source/dependency digests pin the artifact to actor
provenance.  Dependency names are safe relative paths and are never read from the actor workspace.

`CleanRoomVerificationRequest` binds the candidate to an episode, contract digest, public task
input and evaluator digest.  The supplied evaluator callable is fingerprinted again with the
local RSI component identity helper; a caller-supplied digest is only accepted on an exact match.
Actor evidence is retained as a bounded digest for lineage only.  Scores and actor receipts never
become verifier authority.  `private_input_sha256` is metadata only: private input bytes are not
written to the clean-room directory or included in `CleanRoomContext`.

The evaluator receives `CleanRoomContext` with the workspace, candidate source/dependency paths,
public task input, and recomputed digests.  It must return `CleanRoomEvaluation`, or the equivalent
strict mapping with `outcome` (`pass`/`fail`) and bounded `evidence`.  An optional receipt digest
must equal the canonical hash of that outcome/evidence pair.  Extra top-level fields are rejected.

## Output and fail-closed rules

`CleanRoomVerdict` is immutable and records source, dependency, input, evaluator, evidence and
receipt digests.  Outcomes are `pass`, `fail`, or `unresolved`.  Evaluator exceptions, timeout,
identity drift, malformed evidence, digest mismatch, unsafe paths, and candidate workspace
mutation are `unresolved` with a bounded `contamination_reason`; they never pass.  A well-formed
evaluator `fail` is a verifier `fail`, while a well-formed `pass` is accepted only after all
integrity checks succeed.

The verifier re-reads the materialized candidate after evaluation.  This catches wrappers that
modify source or dependencies.  The temporary directory is mode `0700`, source/dependencies are
read-only, and it is removed after evaluation.  The Python callable timeout is an observation
bound; a production hard-kill adapter must execute the wrapper in a separate process.

This slice does not persist memory, inspect hidden holdout data, launch remote evaluators, or
replace the existing `LocalExactVerifier`.  It is a reusable local fixture for the next promotion
and provenance work.
