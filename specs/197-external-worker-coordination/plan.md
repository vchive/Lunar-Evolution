# Feature 197 — Implementation plan

## A: origin verification

Add `external_worker_origin.py`, using only `hashlib`, `hmac`, `json` and bounded
immutable data objects. Keep source verification independent from Feature 169's
host-specific process observations and from all ledger mutation.

Public interfaces:

- `WorkerOriginKey`: exact worker/host/boot/key identity, private secret and
  revocation state. The secret is excluded from `repr`; there is no secret export.
- `WorkerOriginRegistry`: trusted immutable registry; duplicate worker/key
  identities and cross-worker secret reuse refuse.
- `WorkerOriginContext`: original controller/run/task/episode, native-claim or
  launch-context digest, controller challenge and assignment generation.
- `sign_worker_origin(...) -> bytes`: canonical signed bytes for actual receipt
  bytes, with no caller-controlled algorithm or destination.
- `verify_worker_origin(...) -> VerifiedWorkerOrigin`: exact registry/context/
  profile/receipt binding and real constant-time HMAC verification. The detached
  result includes its wire digest; it is not a live execution capability.

Validate exact built-in types and byte limits. Parse only bounded original byte
strings, reject duplicate JSON keys, and compare re-encoded canonical bytes to
the original input. Never use a wire-supplied secret or a `source` field as trust.

## B: authoritative assignment, not enabled by A

Reuse the single authoritative controller, original claim and callback journal.
Determine the transaction that simultaneously validates the running claim,
compares the original assignment generation and consumes its challenge before
connecting verified provenance to a receipt. Do not permit timeout-based stealing
of a started native claim. Do not move SQLite to NFS or add a service by default.

## Verification ownership

The implementation agent authors `tests/test_external_worker_origin.py` and
performs AST parsing only. Root runs the combined focused tests, Ruff, compileall
and `git diff --check` once the parallel slices are frozen. No model, provider,
remote evaluator or real remote worker is invoked by these tests.
