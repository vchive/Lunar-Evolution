# Original BRS owner rejection provenance P/C2

## Baseline and boundary

Continue frozen PR128 `3366036297b9a3294519ebda38a353f6a29c4a38` using a
separate worktree. Prerequisite scoped validation, complete GitHub CI and main
merges are independent gates; this document does not declare those results.

The exact original `_BRSLineageCheckpointOwner` may retain provenance only
after its own confirmed ordinal-zero rejected C1. It creates one native
provenance file P and performs one adjacent C2 checkpoint that fills only
`rejection_provenance`. No second DRS owner, DTO, report, recovered pathname or
later matching checkpoint may supply authority.

Keep the original running run/episode, started claim, absent result, null
published head, waiting worker, unused ready channel, original lease/thread/
lock/wave/selection, memory, budget, intents and executions. The private
prepared-reference/evidence ACK protocol remains distinct from actual ready
request/ACK transport. This slice must not relax the empty-channel guard.

All-rejected dispatch, ready-channel integration, worker result/termination,
recovery consumption, root execution settlement, successor accounting, actual
runtime/solver/CLI acceptance and P2 remain subsequent work. Public native BRS,
production admission and online publication stay closed. Execute only local
inert/provider-free fixtures.

## Wire and capacity kernel

Keep the strict C1 parser requiring null provenance. Add a separate strict C2
parser, index and transition validator. A C2 entry preserves the entire C1
entry except for `rejection_provenance`, which has exactly
`{provenance_sha256, file_pin}` and a strict original native rejection pin.
Keep `rejection_schema=lunar-rsi-brs-rejection-c1-v1`; a fresh source policy adds
`rejection_provenance_schema=lunar-rsi-brs-rejection-provenance-c2-v1`.
Do not upgrade existing persisted policies.

The transition preserves every outer wire field and every batch field except
the single provenance field. It accepts only null-to-present, once. The index
still names the same rejected descriptor. Parsing validates bounded plain
shapes and associations but grants no owner permission and performs no I/O.
`provenance_sha256` hashes the canonical evidence body plus file identity;
`file_pin.sha256` hashes the complete canonical file including that digest
field. They are distinct. The pure parser validates their respective shapes;
the owner double-reads the complete P body to verify their actual association.

C1 accounting retains its future 1 MiB P reservation. A separate C2 accounting
kernel uses the captured C1 state, unchanged retained material tables and the
actual native P pin, counting `actual_C1 + P.size` once. Preserve P's 0400 mode
and original physical domain; never recast it as a snapshot pin. Reject any
different path sharing an inode with other retained material. Preserve the
64 MiB aggregate, 16 MiB snapshot, 112 KiB checkpoint and all fingerprint
container/depth/text/code limits. Never increase a cap to fit this feature.
The captured state must contain the original C1 lineage wire; the kernel
validates the exact C1-to-C2 transition before counting. A current C2 wire or
caller-supplied scalar byte total cannot stand in for that capture.

## Original owner protocol

1. Capture the original C1 `(head, payload)` only in C1's final successful
   adoption tail. Require it to equal the current original owner/wave capture,
   with exact prepared-evidence-to-C1 history and null provenance.
2. `rejection_provenance_binding()` verifies the original capture and returns
   `RejectionLineageC1Binding` data, including actual retained bytes without
   the future P reservation. It is not a permit.
3. `retain_rejection_provenance()` alone opens an internal one-shot scope.
   Reobserve the original launch binding, gateway ledger inode, started claim,
   recovered producer receipt/output, rejected descriptor, original terminal
   and ordered native rejection digest arrays; build fresh
   `NativeRSIRejectionEvidence` from those observations. Preserve original
   before snapshots, native material and source/control checks throughout.
4. Reuse the create-only native P writer and strict reader. Preflight worst
   encoded P/checkpoint capacity before creating P. Hold the writer-returned
   digest and original publishing-FD pin exactly once; double-read and compare
   the complete canonical evidence. Never discover/adopt an orphan or derive
   the original pin from a pathname or readback.
5. `acknowledge_rejection_provenance(evidence, file_pin)` operates only in this
   original active scope. Arguments must match held canonical body, digest and
   original pin. An externally matching DTO/pin cannot open the scope.
6. Build the one-field C2 delta. CAS against the captured original C1 head;
   require exactly adjacent C1/C2 history and exact canonical root readback.
   A dedicated postwrite observer must handle durable C2/local C1 without
   refreshing to the latest head or invoking an ordinary stale owner check.
7. Repeat full source/native/P/control observations after the first readback.
   Use the finite canonical final-reader graph, rejecting instance shadows
   and live alias/code drift. After the final material check, call no dynamic
   observation hooks. Advance original owner and wave cursors together only
   after the fixed final gate; phase becomes `rejected-provenance`.
8. `rejection_provenance_file_pin()` returns only the independently held pin
   after successful C2 and verifies it; it cannot recover or replace a pin.

P/C2 has a separate finite numeric allowance tightened by original control
remaining time/deadline. Do not reset wall clock, reserve another execution,
extend an allowance or invoke hooks inside short publication/observation locks.
Original C1 descriptor pin and P pin have separate custody.

Every partial create/write/fsync/readback, CAS ambiguity, cancellation, expiry
or later drift retains files, any existing reconcile fence and old local
capture, poisons the original owner, and forbids retry. No deletion, repair,
matching-file adoption, unknown upgrade or owner reconstruction is permitted.

## Implementation and validation plan

Long methods belong in a dedicated module and are directly aliased on the
original class; only minimal slots/init/aliases may enlarge the class. Fresh
policy pins cover the finite parser/accounting/owner helpers, DTOs, canonical
aliases and runtime call graph within existing identity limits.

Evaluate the complete finite provenance projection on every policy observation,
then persist its canonical SHA256 once. The expanded projection must not be
duplicated across run fingerprints beyond the unchanged 128 KiB run-record cap.
An independent enclosing import-time pin retains each new owner/policy function,
its module globals and original executable code object. Check these pins before
calling a policy helper; source text alone cannot detect a live `__code__` change,
and a mutable checker must not be its own sole guard. Existing callable defaults
and closure fingerprint checks remain active.

Develop in parallel with exclusive file ownership: pure parser/accounting and
their tests; original-owner scope/history/provenance methods; policy wiring
and real original-owner fixtures. First verify one/two candidates and prior
owner compatibility in one process. Cover foreign/type/thread/phase/head/
claim/control/source drift, malformed transitions, original-file inode drift,
existing/partial/orphan/link/mode/parent changes, short write/fsync/readback,
capacity exact/+1 boundaries, post-P/post-C2 drift, duplicate calls and final
reader shadows. Uncertain writes must retain durable files and old captures.

After each implementation change run focused tests, Ruff, compileall and
diff-check. Freeze a final source once for matching macOS/Linux scoped
inventory, source/import/raw evidence and independent product review. Publish
a successor PR only with precise validation scope; fixture acceptance does
not establish complete CI, main merge or production availability.
