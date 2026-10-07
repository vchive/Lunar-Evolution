# Data model

`NativeTrustedProducerFailure` is a strict frozen failed/cancelled record. Its canonical wire retains
original native recovery records and independently pinned broker observation/reconstructed closed
projection. `to_dict`, strict `from_dict` and `digest` serialize evidence; construction and self-hash
alone never prove filesystem provenance. Builder uses live attempt pins; recovery requires expected
DTO and verifies filesystem proof without executing or signalling.

`NativeRSIFailureEvidence` exposes `plan`, `failure`, `claim_sha256`, `ledger_identity` and
`provenance_sha256`. Its immutable wire contains the complete NativeRSIExecutionPlan, original input
binding, complete original claim including created_at, ledger database/device/inode and native
failure wire. Exact protocol: `lunar-native-rsi-failure-provenance-v1`; schema version `1`;
file: `native-rsi.failure-provenance.json`. File identity and canonical self-digest are frozen on the
original publishing FD; later caller/result digest pins provide independent replay binding.

The mapper creates SolverResult with failed/cancelled status and failure terminal reason. All
candidate/source/evaluation/publication success fields are null. Failure/terminal/plan/provenance
SHA values appear in explicitly named solver_provenance; the trace digest is a failure evidence
summary. No candidate DTO or success execution receipt is manufactured.

Controller `native_failure_reconciliation_reservations[episode_id]` pins the caller's original
checkpoint, episode record, claim and provenance digests before registration. Identical recovery
is idempotent despite lawful intermediate writes; changed pins cannot reuse a consumed reservation.

Exact native wire fields: schema_version, protocol, status, receipt_scope, publication_eligible,
launch, descriptor, consumption, registration, handoff, bootstrap_evidence, deadline_record,
terminal_record, cleanup_record, stream_capture, broker, failure_sha256. Broker retains original
journal path/identity/SHA/bytes/device/inode and the closed reconstructed snapshot.

Exact RSI payload fields: schema_version, protocol, plan, input_binding_sha256, native_failure,
ledger_identity, claim. Disk adds file_identity and provenance_sha256. Claim is the immutable
NativeEpisodeClaim started projection including created_at; current result-derived status may
change to failed/cancelled but its original fields must remain identical. Failure sidecar is
bounded at 3MiB, preserving the 2MiB native-wire bound and complete plan/claim overhead.

`gateway.inspect_failure` exposes the same strict read-only proof check before controller budget
reservation; `restore_failure` repeats it before create-only result publication. Both retain the
original claim returned before provider invocation, including its creation timestamp.

Failure result publication passes the original NativeEpisodeClaim to the existing ledger
transaction through an optional expected_claim parameter. BEGIN IMMEDIATE precedes comparison
of the full original started projection, including created_at. No SQL schema changes. Controller
restore supplies an explicit before_publish CAS guard after all evidence reads and before the
result transaction. A later post-publication drift keeps the already-written immutable result
and refuses episode/checkpoint progress; it never claims those occurred writes were absent.
