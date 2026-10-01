# Native RSI execution plan

Feature 160/T160-35, 2026-10-02. `NativeRSIExecutionPlan` is the immutable pre-launch
composition DTO between a controller-owned `SolverRequest`/approved memory snapshot and the
native scheduler.

The plan contains the canonical complete request, request and memory digests, original deadline,
launch/attestation/bootstrap identities, create-only input manifest and paths, explicit candidate
selector identity, and independent evaluator identity. Its `plan_sha256` is the SHA-256 of the
canonical wire object without that field. Strict construction and round-trip loading reject
unknown fields, nested request drift, selector/evaluator digest drift, path escapes, expired or
invalid deadline values, and any request/memory digest mismatch.

The plan has no process or publication authority. It does not consume an attestation, claim an
episode, launch a worker, write RSI memory, mark a verifier pass, or infer a successful result.
Those operations remain the native gateway/controller boundaries. A replayed plan is read-only
identity evidence and must be revalidated against the staged input manifest and launch records
before dispatch.
