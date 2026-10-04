# Unified local worker evidence verifier

The provider-free `verify_trusted_worker_evidence()` API composes the existing producer
attestation, trusted bootstrap process registration, handoff receipt and terminal evidence.
It rebinds every record to the same launch, task and executable identity and returns one of:

- `trusted_completed`: independent terminal evidence is `passed`;
- `trusted_failed`: independent terminal evidence is `failed`;
- `unknown_recovery_required`: terminal evidence is missing or explicitly `unknown`;
- `identity_drift`: a source record, digest or binding does not match.

The verifier is strictly read-only. It does not inspect a process, access the filesystem,
consume an attestation, send a signal, write the ledger, retry a worker or grant a distributed
lease. The classification is therefore local evidence validation, not external source
authentication or multi-host exactly-once ownership.

Unknown evidence cannot be upgraded by a caller-provided status. A production adapter still
needs a separately trusted worker source, process ownership protocol and durable terminal
acknowledgement before it can claim external recovery.
