# Tasks

- [x] T156-01 Define canonical lifecycle, attestation-consumption, registration, stream, envelope, and execution-receipt DTOs with bounded fixed failure codes.
- [x] T156-02 Implement no-follow atomic consume-once nonce claims and exact revalidation of intent, authority IDs, attestation, and source executable identity.
- [x] T156-03 Implement the gate-aware no-shell `Popen` path with a new session, closed descriptors, derived cwd, and exact PID/PGID owner registration for cooperating local producers.
- [x] T156-04 Persist a launch registration receipt with bounded fsync/atomic publication before releasing the producer work gate.
- [ ] T156-05 Add one monotonic wall-clock deadline, independent request/output limits, concurrent bounded stdout/stderr capture, and deterministic overflow handling. The local runner now also observes a caller cancellation callback during capture and process wait; full trusted-path integration remains open.
- [ ] T156-06 Integrate owner-checked process-group cleanup and fail-closed timeout, liveness, signal, and cleanup uncertainty states. The local runner now persists a verified `cancelled` terminal when active cancellation cleanup succeeds; explicit post-crash cleanup still acquires the registered device/inode lifecycle lock, rechecks durable registration, lock path, and OS start identity before signals, and persists a separate recovery receipt. A missing execution receipt remains an unknown outcome even after verified cleanup; full lifecycle acceptance is still open.
- [x] T156-07 Add no-follow, bounded, double-identity output-envelope evidence and bind stable bytes to the execution receipt.
- [x] T156-08 Add read-only controller-interruption recovery that inspects exact registrations and never relaunches or consumes another attestation.
- [ ] T156-09 Add provider-free fixture tests for success, replay, gate, timeout, capture, tampering, cleanup, receipt durability, and recovery. The matrix now explicitly covers simultaneous stdout/stderr overflow and a hostile pre-gate side-effect negative; formal lifecycle acceptance remains open until the trusted-bootstrap and recovery boundaries are integrated.
- [x] T156-10 Run focused tests, Ruff, compileall, diff checks, and the existing offline regression; keep integration entry points unchanged.
- [ ] T156-11 Close the executable replacement window with a platform-supported byte-bound execution contract and a deterministic replacement regression before external admission.
- [x] T156-11a On Darwin, stage the verified bytes into a private immutable snapshot, bind its digest into registration/terminal receipts, and cover replacement-after-check and snapshot-lock failure.
- [x] T156-11b On Linux, execute a sealed memfd through an inherited descriptor and verify source replacement after the final check; other non-Darwin platforms remain prototype-only.
- [ ] T156-12 Define and attest a Lunar-owned producer bootstrap protocol; reject arbitrary direct executables that cannot prove no work occurred before registration-gate release.
- [x] T156-13 Add capture/read and signal/cleanup fault-injection fixtures, including child exit before gate and broken gate delivery; preserve terminal unknown/recovery evidence.
- [ ] T156-14 Integrate Feature 157 only after controller-owned request evidence is host-observed and recovery-safe; producer-declared files remain diagnostics.

The native trusted attempt now requires a stable durable handoff reread before gate release.
It cross-checks the one-time nonce claim, formal registration, and handoff under the existing
wall-clock deadline; missing or tampered handoff keeps the target unstarted. This is pre-gate
evidence only. No full Feature 156 execution receipt or brokered request coverage is claimed.

The `15b8113` supporting checkpoint adds a compiled native trusted bootstrap and a real Darwin
bootstrap → isolated target test. The target can write its declared workspace while outside
writes, controller-secret reads and direct network connections are denied. C execution uses the
verified `target_path`; a differing `argv[0]` cannot select unverified executable bytes. This is
not a Feature 156 runner entry point. T156-05/06/09/11/12/14 remain open until formal registration,
the shared deadline, broker/credential/journal boundaries, cleanup and recovery are connected to
that native path and accepted together.

The cooperative `run_producer_lifecycle` supporting entry point now joins one attested direct
process receipt to a stable envelope reread, verified multi-file bundles, native drafts, and an
admission plan. It retains `request_coverage=cooperative_declaration_only`,
`broker_coverage=not_integrated`, and `publication_status=not_started`. It does not authorize
arbitrary direct executables as trusted bootstrap, provide complete outbound coverage, or stage
or publish candidates. T156-05/06/09/12/14 remain open for the production path.

The preparation result now exposes the verified process terminal, cleanup and execution outcome,
with `deadline_scope=process_attempt_only`. Draft preparation requires a completed zero-exit
terminal, released gate, verified owner cleanup, stable envelope evidence, and matching read-only
receipt recovery. Provider-free regressions reject unknown terminal or cleanup, missing envelope
evidence, and a terminal receipt chain mismatch. This only tightens the cooperative support path;
it does not close the trusted production lifecycle tasks above.

The native trusted runner now writes a separate, create-only
`native-trusted-process-terminal.json` after the exact handoff and bootstrap evidence are
durable, the child has a known exit code, and owner-checked cleanup is verified. The receipt
binds the formal registration, handoff, bootstrap evidence, process status, and cleanup status;
it explicitly says `receipt_scope=process_only` and `publication_eligible=false`. Read-only
recovery verifies that chain. When the terminal is missing, explicit recovery takes the
registered lifecycle lock and may clean only the exact OS start identity, retaining unknown
outcome in a separate recovery receipt. This is a partial T156-06/09 slice. The native path
still lacks a Feature 156 output-envelope receipt, host-observed request evidence, and complete
terminal deadline/capture coverage, so T156-05/06/09/14 remain open.
