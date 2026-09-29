# Tasks

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

The controller HTTP worker now rejects redirects and bypasses ambient proxy settings on the
broker path. Broker configuration copies and freezes host headers before execution. Local
two-server and proxy fixtures verify that neither a 30x target nor an ambient proxy receives
the credential. This narrows the fixed-endpoint authority; DNS resolution, complete target
egress isolation, journal ownership across crash, and receipt/publication integration remain
open.
