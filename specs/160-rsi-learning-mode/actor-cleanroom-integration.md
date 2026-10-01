# Local AgentLoop actor to independent clean-room verifier

## Scope

`AgentLoopCleanRoomVerifier` implements the existing
`verify(PracticeEpisode, SolverRequest, SolverResult) -> VerifierDecision` protocol. It is an
explicit, provider-free bridge from a completed local `AgentLoopActorGateway` episode to
`CleanRoomProcessVerifier`. The caller freezes public task-input bytes and supplies a locally
importable module-level trusted evaluator plus evaluator/contract/environment pins.

This bridge uses a local runtime fixture in acceptance tests. It does not provide an official
evaluator, model-quality evidence, OS/network sandbox, external receipt authenticity or automatic
memory-governance promotion. No controller, CLI, Actor or existing verifier schema is changed.

## Configuration

The constructor takes `workspace_root`, frozen `task_input`, `evaluator`, `evaluator_sha256`,
`contract_sha256`, `environment_sha256`, one `candidate_path`, ordered `dependency_paths` and a
bounded `timeout_seconds`. Paths are canonical relative POSIX paths, without traversal or
symlinks; at most 32 unique dependencies are supported, with source/dependency aggregate byte
limits inherited from the clean-room protocol. Empty declared dependencies are allowed.

The fingerprint hook binds task-input digest/size, paths/order, pins, timeout, evaluator identity
and the implementation helpers/process verifier. Runtime observations do not alter the identity.
Invalid configuration is rejected; a live evaluator fingerprint drift fails before evaluation.

## Verification and evidence

1. Require completed episode/result, matching episode/request/result identity, solver/memory
   pins, configured contract/evaluator/environment pins, complete Actor receipts and matching
   episode/result provenance. Unknown, failed, missing-receipt or drifted input cannot launch an
   evaluator or be promoted to success.
2. Open `workspace_root/episodes/<episode_id>` and each artifact through pinned directory file
   descriptors with `O_NOFOLLOW`. Reject final/intermediate symlinks, nonregular files, missing
   declared files, oversize material and identity changes during reads. The bridge does not
   create/write Actor workspace files.
3. Recompute the Actor manifest SHA independently: canonical ordered `(relative_path, raw_sha)`
   pairs, exactly as Actor `_file_digest` does. Compare candidate/dependency manifest digests to
   both episode and result. Never treat a manifest SHA as the raw source SHA.
4. Separately compute raw source SHA and the clean-room dependency digest (sorted path/SHA/size
   manifest). Build `CandidateArtifact` from frozen bytes with those raw pins and pass only
   frozen public task input to a fresh clean-room spawn process.
5. Convert clean-room pass/fail/unresolved to a complete `VerifierDecision`. Timeout, exceptions,
   malformed evidence or clean-room workspace mutation remain unresolved. Actor score and private
   response text are not evaluator authority.

`verify_with_evidence()` additionally returns immutable `ActorCleanRoomEvidence`, containing
original request identity, Actor manifest digests, raw artifact/task digests, reason and the full
clean-room verdict. Its canonical digest binds the decision receipt and evidence check. It is
returned to the caller and is not silently persisted or admitted to memory governance.

The current controller callback protocol requires `decision.evidence_sha256` to equal the hash of
the Actor's three receipt fields plus trace. The durable episode protocol also requires the
`official_evaluator` check to bind the original official receipt. The bridge preserves those
fields as input lineage and adds a separate `cleanroom_evaluator` check plus the independently
computed evidence/decision receipt. It does not relabel the clean-room receipt as the Actor's
official receipt or infer external authenticity from a caller-supplied digest.

## Acceptance

Focused tests exercise local RuntimeFixture → completed practice → independent process pass,
well-formed independent failure despite Actor success/score, process timeout/exception/mutation,
missing receipts and identity/pin drift before evaluator invocation, source/dependency tampering,
final/intermediate symlink rejection, manifest/raw digest separation, frozen task input and stable
component fingerprint. Existing Actor and clean-room process tests remain green.

Controller-level composition and durable replay are validated separately by the integrating
controller tests. A provider-free pass does not imply real model, production campaign or official
evaluator acceptance.
