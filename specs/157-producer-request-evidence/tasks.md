# Tasks

Latest 2026-10-01 local scheduler regression is documented in Feature 156
`local-native-scheduler-validation.md`: actual host broker/journal coverage now composes through
formal receipt and native publication; the local target cannot write the host journal or connect
directly. T157-05/06 still require complete bypass and active transport crash/ownership coverage.

- [x] T157-01 Define bounded request event/evidence DTOs, canonical self-digest, and fixed parser errors.
- [x] T157-02 Bind evidence to the exact Feature 156 launch tuple, intent digest, and repeated budgets.
- [x] T157-03 Add conservative declaration-only assessment that never claims host enforcement.
- [x] T157-04 Add provider-free round-trip, duplicate/tamper, binding, partial coverage, and timeout fixtures.
- [ ] T157-05 Specify and implement a controller-owned evidence transport or controlled producer SDK.
- [ ] T157-06 Integrate Feature 156 only after transport evidence is host-observed and recovery-safe.

T157-05 progress: A native producer isolation policy and C boundary are now available for trusted-bootstrap integration: Darwin deny-default SBPL denies network and grants exact declared paths; Linux requires Landlock + no-new-privileges seccomp and fails closed when unsupported. The boundary runs post-gate/pre-exec and retains a policy digest. This is still not complete egress coverage.

T157-05 progress: `transport-design.md` specifies the controller-owned broker boundary;
`HostRequestLedger` implements bounded host-side admission, count, and monotonic timing,
and `ControllerOwnedRequestBroker` now requires a controlled handle with explicit cancellation
and a confirmed `cancelled` terminal before claiming enforced timeout. Ledger and journal
state transitions are serialized for concurrent broker calls. `HostRequestJournal` records
identity-bound, append-only, fsynced events and read-only crash recovery. A POSIX HTTP worker
now supplies real brokered POST I/O, bounded IPC, process-backed cancellation, and an
in-memory response result. Complete egress coverage, protected production journal ownership,
and Feature 156 integration are still required.

The native trusted attempt now optionally gives its isolated target a bounded anonymous-pipe
request/response protocol. The controller creates a private journal before gate release,
applies the immutable intent budgets through the existing broker and HTTP worker, and keeps
the configured endpoint and headers outside the target environment. A local native fixture
proves one completed request; malformed frames and a second request beyond the budget reach
no provider I/O. This is a request-exit integration slice, not T157-05/06 closure: the
process-only receipt does not bind the journal, and a production scheduler cannot yet treat
the broker observation as publication authority.

The completed native evidence projection now carries the broker coverage into the formal Feature
156 execution receipt, and Feature 153's publication transaction can require that receipt by
digest before writing its prepared intent. This is a narrow receipt/journal handoff; T157-05 and
T157-06 remain open for protected journal ownership, crash-safe transport recovery, bypass
coverage tests, and production scheduler integration.

The broker now also exposes a read-only `recover_producer_broker_observation()` boundary. It
replays the controller-owned journal under a caller deadline, binds an optional retained digest
and byte count, and keeps active or timed-out requests at `recovery_required`; it never reopens
the journal for append or retries provider I/O. This is supporting crash-recovery evidence for
T157-05/T157-06. It does not establish complete egress coverage or authorize a resumed producer.

T157-06 local active cancellation slice is implemented: the native main thread owns a stop event,
the broker polls the same admitted request under its original deadline, and an exact HTTP worker
stop requires both cancellation acknowledgement and a confirmed cancelled terminal. Idle pipe
read/write also stop without transferring descriptor ownership. Actual blocked loopback I/O is
killed/reaped; lost acknowledgement preserves an active/unknown journal and blocks formal success
and publication. Repeated recovery performs no launch/I/O. See `active-cancellation-contract.md`.
This does not close controller-death recovery, complete egress or external project ownership.

T157-06 local controller-death slice: the existing HTTP lifeline is now tested together with a
real broker and fsynced host journal in a separate controller process. Controller-only SIGKILL
before outbound I/O or during blocked headers stops the local worker; retained admission stays
active/unknown. Recovery rejects hash/bytes/budget/inode drift without append, retry, signals or
transport. The six new cases pass locally; broader native process crash ownership, complete
egress and external project acceptance remain open. See `controller-death-contract.md`.
