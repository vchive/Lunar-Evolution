# Known rejection v2: implementation tasks and ownership

Status: helpers and controller integration implemented; original product acceptance pending, 2026-10-15. Initial reference source: `a62ac647e692c69f12f9df19d9bc6a20f792c738`; later PR100 test fixes are integrated independently.
Read sibling `known-rejection-v2.md` first. All development uses a separate worktree rooted at the stable PR100 product candidate. Integration development may proceed after helper review; final integration acceptance and release require the accepted PR100 main baseline. The PR100 checkout remains frozen.

## Current execution status — 2026-10-15

| Tasks | Implementation / validation state |
| --- | --- |
| V2-00, A1/A2, B1/B2/B3 | Implemented and cross-reviewed; original 290-case helper checkpoint retained below. |
| V2-I1 through I8 | Implemented; final-source 476-case joint focused plus two nested DTO refusal cases pass, zero failures/errors/skips. Original owner/controller acceptance is still running. |
| V2-T1/T2/T3 | Three original RPP/PRP/RRR fixtures implemented and executing concurrently in independent local workspaces; no result claimed yet. |
| V2-T4 | Maximum-cardinality capacity gate covered by fast tests; original controller multicandidate acceptance remains open. |
| V2-T5 | Original C2 and four successive reconcile crash boundaries executing. Earlier native/C1/orphan interruption acceptance remains open. |
| V2-R1/R2 | Final local inventory/evidence review, accepted PR100 main synchronization, complete CI/artifact audit and release remain open. |

The current source freeze and separate raw XML identities are recorded in
`known-rejection-v2-validation.md`. Earlier failed development runs are retained;
neither unit seams nor pending tests close the product acceptance tasks.

## Fast independent helper streams

| ID | Owner/files | Exact deliverable and API | Depends on | Focused test ownership |
| --- | --- | --- | --- | --- |
| V2-00 | Integrator; next tracked SDD only | Promote fixed fresh-v2 before/0400 pin/C1-P-C2/three-way refusal/mixed-vs-started contracts; freeze exact names, fields, error codes, size/phase/accounting rules and source dependency map. No runtime/schema/service addition. | Stable PR100 product baseline; helper review before integration development; accepted main before release | SDD/source contract review; no producer. |
| V2-A1 | Stream A: new `producer_bundle_lineage_v2.py` | Exact `ProducerLineageBeforeIntentV2` and `ProducerLineageRejectedTerminalV2`; `parse_lineage_v2_descriptor`, `persist_lineage_v2_descriptor`, `read_lineage_v2_descriptor_pinned`. Fixed paths; legacy v1 untouched; original 0600 pin rules. | V2-00 | New `test_producer_bundle_lineage_v2.py`: pure shape/canonical/type/ordinal/nullable predecessor pairs, original create/pin/refusal/cap fixtures, unchanged v1 bytes. |
| V2-A2 | Stream A: `producer_bundle_rejection.py` only | Extract private `_verify_terminal_batch_rejection_evidence` and frozen `VerifiedProducerBundleRejection`; preserve public `_prefix`, native receipt reconstruction, ordered all-candidate verification, final candidate tree and own publication-file absence. No bypass boolean. | V2-00; A1 only for shared naming | New `test_producer_bundle_rejection_immutable.py` plus existing rejection tests: pinned immutable helper under changed later population; public current-head gate still rejects; receipt/order/cardinality and own final-path drift. Lowest inert seam only. |
| V2-B1 | Stream B: new `rsi_native_rejection.py` | Exact `NativeRSIRejectionEvidence`, `RejectionLineageC1Binding`, separate `NativeRSIRejectionFilePin` fixed0400; strict canonical/bounds and pure `map_native_rejection_to_solver_result`. No successful candidate/source/official-pass/score. | V2-00; A1 wire contract frozen, implementation may proceed in parallel | New `test_rsi_native_rejection.py`: pure request/plan/claim/C1/native/order binding, exact failed result and strict subclass/type/shape/digest refusal. Parsing alone never settles ledger. |
| V2-B2 | Stream B: same new module | Create-only `persist_native_rsi_rejection_provenance(...retained_bytes)` returns digest+original publishing-FD pin; `read_native_rsi_rejection_provenance(...expected_file_pin)` compares independently held pin. Existing/orphan refusal, no delete/replace/adoption. | B1 | New `test_rsi_native_rejection_provenance.py`: real local file FD/pin/mode/fsync/link/timestamp/replacement/cap/no-follow tests; no controller/producer. |
| V2-B3 | Stream B: `rsi_native_provenance.py`, `rsi_native_failure.py`; optional private filename-only helper | All old standalone readers/writers refuse rejection sibling; new rejection reader/writer refuses either old sibling. Existing payloads/signatures/type semantics unchanged. | B1 constant/name | Same B2 tests + old provenance/failure focused suites: all six ordered pair conflicts, symlink/partial/race refusal and old canonical compatibility. |

A and B must not edit shared owner/scheduler/gateway/controller files. A1 helper
wire contract should be reviewed first; B may implement against that strict shape
without waiting for full native verifier integration. These are the quickest
independent pieces: pure DTO/filesystem tests do not need expensive multi-episode
controller runs. Review each helper's trust boundary before merging it into the
active original owner path.

## Sequential integration with bounded tests

The sequence below describes API dependencies. Implementation can use distinct
files in parallel against the frozen interfaces; acceptance still follows the
dependency order. Stream A owns the lineage/inspection/capacity files, stream B
owns the scheduler, and the root integrator owns gateway/controller/mode wiring.
Reviewers do not modify another stream's files without an explicit handoff.

| ID | Owner/files | Exact deliverable and API | Depends on | Focused test ownership |
| --- | --- | --- | --- | --- |
| V2-I1 | Integrator: `rsi_publication_lineage.py` + dependency policy | Fresh immutable v2 policy; before-v2 persistence; explicit previous-attempt/published-predecessor continuity; exact `before -> rejected` entry/index; C1 native evidence retention; no deleting before/staged downgrade/head advance. Track all attempted IDs; 8 total. | A1, A2 | New `test_rsi_publication_lineage_rejection.py`: fast isolated owner/CAS/history/source/missing-genesis/continuity/cap/refusal gates. Preserve v1 owner/publication tests. |
| V2-I2 | Same integrator/files; new module types only if unavoidable | `rejection_provenance_binding`, exact `acknowledge_rejection_provenance`; independent 0400 C2 field; original owner/thread/dispatch/CAS; explicit terminal-only evidence accounting; final pin/lock/owner rechecks. | I1, B1-B3 | Same fast suite: C1-P-C2 adjacency, original create-pin replacement, orphan nonadoption, capacity before create, cancellation/parent/native deadline and no additional execution reservation. |
| V2-I3 | Same integrator: `rsi_publication_lineage.py` | `RSIPublicationLineageV2Inspection` for durable terminal mixed chain; `StartedRSIRejectionInspection` separately read-only with exact C2+started claim; immutable history pins survive later evidence-budget checkpoint; original v1 inspector unchanged. | I2 | New `test_rsi_publication_lineage_rejection_inspection.py`: earlier P/R selection, mixed claims/results, historical memory, C1/P without C2 rejection, C2 started-only constraints, no authority/launch/ack methods. |
| V2-I4 | Integrator: `rsi_native_scheduler.py` | Distinct all-rejected branch before successful receipts; real `NativeTrustedProducerRun` recovery with original formal producer receipt/output and all candidate evidence; original owner P acknowledgment; three-kind inventory; terminal `recover` and explicit read-only `recover_rejection(...inspection)` route. | I1-I3, A2, B1-B3 | New `test_rsi_native_scheduler_rejection.py`: inert native result/snapshot chain, unchanged success/process-failure behavior, original input/plan/config/claim/ledger identity and mutually exclusive provenance. |
| V2-I5 | Integrator: `rsi_native_gateway.py` | Exact rejected evidence mapping; repeated provider/native/P checks; existing `publish_native_episode_result(...expected_claim=claim)`; explicit `inspect_rejection`/`restore_rejection`; no ordinary historical fallback for started claims. | I4 | New `test_rsi_native_gateway_rejection.py`: failed result/no fake receipts, expected-claim conflict/idempotency, original pin repetition, strict inspect readonly/restore guard, started refusal and terminal replay. Store tests only, no store schema/API change. |
| V2-I6 | Integrator: `rsi_controller.py`; child resolver/`rsi_producer_gateway.py` only necessary dependency wiring | Distinct `reconcile_native_rejection`; original unknown-evidence budget reservation/checkpoint/episode pins; exact historical child gateway/memory; settle failed native result without solver work; ordinary failed DRS diagnosis/practice/exhaustion and no-promotion behavior. | I5 | New `test_rsi_controller_native_rejection.py`: C2 explicit reconcile, native result-before-episode crash, evidence budget idempotency, historical memory and original child wiring; no solver launch. |
| V2-I7 | Integrator: `rsi_producer_staging_capsule.py` and owner capacity helpers only if needed | Pure v2 aggregate counting for capsules/snapshots/lineage descriptors/new rejection P bytes; full projected rejected entry+C2 including32 candidates; original 64MiB/112KiB/other caps. No full native source duplication or cap widening. | I1-I2 contract; preferably before I4 integration | Focused capacity/property fixtures before file I/O; original capsule compatibility suites. |
| V2-I8 | Integrator: source fingerprint/policy config maps and tracked SDD validation | Bind every new helper/owner/inspection/mapper and changed refusal code source; immutable fresh-run v2 choice; no resume/file upgrade. Preserve production/default/BRS/single-child refusal scope. | All integrations | Policy/dependency/module-source drift and no-mode-I/O tests. |

Keep source overlap sequential. A/B may review integration/tests concurrently, but
only the named integrator edits `rsi_publication_lineage.py`, scheduler, gateway
and controller. Failure in a fast ownership/pin gate should be fixed before any
full controller sequence is run.

## Product acceptance and release work

| ID | Files/evidence | Required result | Depends on |
| --- | --- | --- | --- |
| V2-T1 | New controller integration fixture/test file | Original full inert R-P-P with3 distinct claims,2 actual publications,M1 use and earlier R replay; no fake receipts/head/memory advance from R. | I1-I8 and fast tests passed |
| V2-T2 | Same integration fixture | P-R-P with unchanged archive/state inode/bytes/head across R, no practice memory promotion, original M0 retry, earlier P/R replay under final head. | T1 contract; may run independent test cases in parallel after source freeze |
| V2-T3 | Same integration fixture | R-R-R known failed/exhausted, zero publication events, headnull, original M0, absent genesis at ordinal>0 proved, terminal resume no launch/evaluation/claim/reservation refresh. | I1-I8 |
| V2-T4 | Native/controller all-rejected multicandidate fixture | Ordered complete candidate/receipt cardinality and native reconstruction for at least2 rejects in one batch; no selected candidate/publication artifacts. Also maximum-cardinality capacity refusal fixture. | A2, I1-I8 |
| V2-T5 | Independent interruption tests | Partial native records, no terminal, noC1, C1/noP, orphanP/noC2, C2/noresult, savedfailed/runningepisode, terminalepisode/cachemissing. Preserve failures/unknowns; each case verifies no retry/adoption/successor. | I1-I8 |
| V2-R1 | Exact source/head evidence | Focused tests, ruff, compileall, git diff --check; independent code/evidence review; rawXML plus before/after sourcepins and exact distinct case coverage. | T1-T5 |
| V2-R2 | Complete required CI artifacts/PR | Freeze final source; full required CI on exact head, artifact audit; create/update PR and integrate only after final source/CI/acceptance match. Older/interrupted evidence never closes this slice. | R1 |

## Files intentionally left alone unless a concrete failure proves otherwise

- `rsi_store.py`: use existing claim/result transaction; tests may be added without
  adding tables/schema or broadening settlement.
- `producer_bundle_transaction.py` and `native_trusted_scheduler.py`: existing
  all-rejected native type/callback is sufficient; add no bypass/permit.
- `rsi_native_candidate.py` and `rsi_native_retained.py`: successful selected
  candidate and official-pass contracts remain; rejection has its own evidence.
- v1 descriptor types/parsers/readers: exact current strict rules and wire bytes.
- remote evaluator, CLI production routes, distributed ownership and services:
  outside this slice.

## Local helper checkpoint

V2-A1/A2 and V2-B1/B2/B3 are implemented and independently cross-reviewed.
The combined final helper source passed 290 distinct cases with zero failures,
errors or skips in 13.07 seconds. Full `ruff check src tests tools`, compileall
and diff-check passed. Before/after 781-file source maps match
`520f5d9c107fbc72d44828edb1d81b66aa0d57c5cacba8cda026e3835ccae50f`;
raw combined XML SHA-256 is
`027ec98908962abdc5883f1b4f7486794df8dc7429cafae56d7efb906ced9916`.
The five new pure process-failure writer cases complete the two remaining
success/rejection sibling conflict directions without native target execution.

This closes local helper implementation/review only. V2-I1 through I8, all
product sequences/interruption tests, final CI, artifact audit and main release
remain open. Detached DTOs and file pins do not settle a ledger or authorize a
producer. See `known-rejection-v2-validation.md` for the evidence boundary.
