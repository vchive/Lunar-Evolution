# Implementation plan

Use three disjoint runtime tracks with root integration:

- A: `native_trusted_failure.py` builder/reader and frozen DTO; explicit typed scheduler outcome.
- B: `rsi_native_failure.py` strict provenance/map and scheduler provider failure branch/recovery.
- C: gateway strict union/replay/explicit restore and controller CAS evidence-only wrapper.

No SQL schema change, C protocol change, relaxed success receipts or generic settlement service.
Native failure recovery is a prerequisite for provider mapping, not a substitute for durable claim
checks. Read-only recovery compares original evidence before and after broker reconstruction.
Provider pins its explicitly supplied ledger before any launch; gateway verifies that same object
and original inode before plan/claim/result operations. Sidecar dispatch checks both terminal files
using no-follow paths; malformed or dual protocols cannot downgrade to success or saved-only replay.

Fault boundaries: terminal before provenance is quarantined; provenance before result permits
explicit restore; result before episode permits CAS settlement; episode before checkpoint permits
identical reservation replay. Different proofs, stale CAS, original inode drift or immutable unknown
results refuse without relaunch. Budget reconciliation consumes only unknown_retries once, retaining
solver_invocations, wall deadline, request allowance and recursion depth.
