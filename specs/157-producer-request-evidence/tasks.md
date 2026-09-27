# Tasks

- [x] T157-01 Define bounded request event/evidence DTOs, canonical self-digest, and fixed parser errors.
- [x] T157-02 Bind evidence to the exact Feature 156 launch tuple, intent digest, and repeated budgets.
- [x] T157-03 Add conservative declaration-only assessment that never claims host enforcement.
- [x] T157-04 Add provider-free round-trip, duplicate/tamper, binding, partial coverage, and timeout fixtures.
- [ ] T157-05 Specify and implement a controller-owned evidence transport or controlled producer SDK.
- [ ] T157-06 Integrate Feature 156 only after transport evidence is host-observed and recovery-safe.

T157-05 progress: `transport-design.md` specifies the controller-owned broker boundary;
`HostRequestLedger` implements bounded host-side admission, count, and monotonic timing,
and `ControllerOwnedRequestBroker` now requires a controlled handle with explicit cancellation
and a confirmed `cancelled` terminal before claiming enforced timeout. Ledger and journal
state transitions are serialized for concurrent broker calls. `HostRequestJournal` records
identity-bound, append-only, fsynced events and read-only crash recovery. A POSIX HTTP worker
now supplies real brokered POST I/O, bounded IPC, process-backed cancellation, and an
in-memory response result. Complete egress coverage, protected production journal ownership,
and Feature 156 integration are still required.
