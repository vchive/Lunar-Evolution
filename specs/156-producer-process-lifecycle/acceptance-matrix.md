# Producer lifecycle acceptance matrix

**Revision**: 2026-09-30
**Scope**: Feature 156 producer lifecycle, Feature 157 controller-owned request evidence,
and Feature 158 trusted bootstrap.  
**Execution class**: provider-free local fixtures only.

This is the living acceptance matrix for the three connected lifecycle features. A row marked
`offline-verified` proves the bounded local contract exercised by its listed fixtures. A row marked
`supporting-only` proves a boundary in isolation but is not yet connected to the Feature 156
production runner. A row marked `integration-open` is a release gate and has no claim of execution.
No row in this document authorizes a provider call, a campaign, or a second attempt.

| Case | Feature | Scenario and required observation | Evidence | Status | Release gate |
| --- | --- | --- | --- | --- | --- |
| L156-01 | 156 | Exact attestation tuple, executable bytes, inode, and nonce are checked before spawn; replay is rejected. | `tests/test_producer_process.py::test_attestation_nonce_is_consumed_once`; `tests/test_producer_process.py::test_nonce_cannot_be_reused_by_a_different_launch`; `tests/test_producer_process.py::test_executable_drift_rejected_before_attestation_consumption` | offline-verified | none |
| L156-02 | 156 | Process uses an argument vector, no shell, a new session, closed stdin/descriptors, and a derived working directory. | `tests/test_producer_process.py::test_process_creation_uses_isolated_no_shell_contract`; `tests/test_producer_process.py::test_launch_environment_does_not_inherit_parent_values` | offline-verified | none |
| L156-03 | 156 | Registration is durable before the one-byte work gate is released; PID/PGID and owner identity are bound. | `tests/test_producer_process.py::test_attested_process_is_registered_before_gate_and_emits_receipt`; `tests/test_producer_process.py::test_registration_is_durable_before_gate_write` | offline-verified | none |
| L156-04 | 156 | Child exit before gate release and broken gate delivery remain failed/recovery evidence, never success. | `tests/test_producer_process.py::test_child_exit_before_gate_requires_recovery`; `tests/test_producer_process.py::test_broken_gate_delivery_requires_recovery` | offline-verified | none |
| L156-05 | 156 | One absolute wall deadline covers preparation, wait, capture, cleanup, and envelope observation. | `tests/test_producer_process.py::test_preparation_time_counts_toward_wall_deadline`; `tests/test_producer_process.py::test_capture_timeout_does_not_read_open_pipe_after_deadline`; `tests/test_producer_process.py::test_remaining_timeout_never_extends_absolute_deadline`; `tests/test_producer_process.py::test_timeout_is_terminal_without_relaunch` | offline-verified | production runner must carry the same deadline through trusted bootstrap |
| L156-06 | 156 | Stdout and stderr are drained concurrently, bounded, hashed, and overflow is deterministic. | `tests/test_producer_process.py::test_output_limit_is_bounded`; `tests/test_producer_process.py::test_simultaneous_stdout_stderr_overflow_does_not_deadlock`; `tests/test_producer_process.py::test_capture_read_failure_is_unknown` | offline-verified | none |
| L156-07 | 156 | Cleanup rechecks owner identity and process-group identity before signals; uncertainty remains unknown. | `tests/test_producer_process.py::test_cleanup_signal_uncertainty_is_persisted_as_unknown`; `tests/test_producer_process.py::test_explicit_recovery_denies_changed_owner_without_signal`; `tests/test_producer_process.py::test_explicit_recovery_loses_authority_if_lock_changes_before_signal` | offline-verified | production runner must share cleanup and recovery receipts with bootstrap |
| L156-08 | 156 | Envelope is regular, single-link, no-follow, bounded, stable across read, and digest-bound. | `tests/test_producer_process.py::test_symlink_envelope_is_rejected_with_terminal_receipt`; `tests/test_producer_process.py::test_replaced_envelope_during_read_is_rejected`; `tests/test_producer_process.py::test_envelope_mutation_after_open_is_rejected`; `tests/test_producer_process.py::test_envelope_read_obeys_wall_deadline` | offline-verified | none |
| L156-09 | 156 | Receipt publication is atomic/fsynced; write failure and missing terminal evidence require recovery. | `tests/test_producer_process.py::test_terminal_receipt_write_failure_requires_recovery`; `tests/test_producer_process.py::test_atomic_receipt_fsync_failure_does_not_publish_target`; `tests/test_producer_process.py::test_missing_terminal_receipt_requires_recovery_without_relaunch`; `tests/test_producer_process.py::test_recovery_reads_terminal_receipt_without_relaunch` | offline-verified | none |
| L156-10 | 156 | A hostile direct executable that writes before the gate cannot be treated as trusted bootstrap evidence. | `tests/test_producer_process.py::test_hostile_pre_gate_side_effect_is_observable_but_not_trusted_bootstrap` | supporting-only | T156-12 trusted bootstrap must become the only admitted entry point |
| L156-11 | 156 | Source replacement between final identity check and process creation cannot change executed bytes. | `tests/test_producer_process.py::test_linux_sealed_executable_survives_source_replacement_after_final_check`; `tests/test_producer_process.py::test_darwin_snapshot_survives_source_replacement_after_final_check` | offline-verified | platform-specific production bootstrap handoff |
| L156-12 | 156 | Caller cancellation is observed during active capture/wait and a parent monotonic deadline narrows the intent budget; verified cleanup publishes `cancelled`, uncertainty stays `unknown`. | `tests/test_producer_process.py::test_active_cancellation_terminates_child_and_persists_cancelled_receipt`; `tests/test_producer_process.py::test_active_cancellation_cleanup_uncertainty_is_unknown`; `tests/test_producer_process.py::test_parent_deadline_narrows_intent_wall_budget` | offline-verified | Feature 153/158 must pass the same callback and deadline into the production runner |
| L157-01 | 157 | Host admission counts before I/O and enforces independent request/time budgets. | `tests/test_producer_request_transport.py::test_admission_counts_before_io_and_denies_over_budget`; `tests/test_producer_request_transport.py::test_host_clock_marks_late_completion_and_expiration` | offline-verified | none |
| L157-02 | 157 | Controller-owned journal is append-only, fsynced, identity-bound, and conservative on replay/tampering. | `tests/test_producer_request_transport.py::test_durable_journal_replays_completed_and_uncertain_requests`; `tests/test_producer_request_transport.py::test_journal_recovery_checks_identity_and_detects_tampering`; `tests/test_producer_request_transport.py::test_concurrent_journal_appends_preserve_ordinal_and_hash_chain` | offline-verified | journal directory must be protected from the producer |
| L157-03 | 157 | Broker cancellation is confirmed only after transport cancellation and terminal state are both observed. | `tests/test_producer_request_transport.py::test_controller_broker_requires_cancel_ack_and_terminal_confirmation`; `tests/test_producer_request_transport.py::test_controller_broker_keeps_unconfirmed_timeout_fail_closed`; `tests/test_producer_request_transport.py::test_controller_broker_cancels_after_wait_failure` | offline-verified | actual provider egress must have no bypass path |
| L157-04 | 157 | POSIX HTTP transport bounds request/response IPC, cancellation, worker reaping, and response exposure. | `tests/test_controller_http_transport.py::test_success_response_is_local_and_worker_has_no_secret_arguments`; `tests/test_controller_http_transport.py::test_broker_deadline_cancels_and_reaps_blocked_io`; `tests/test_controller_http_transport.py::test_oversized_worker_stdout_is_rejected_and_child_reaped` | offline-verified | transport must be owned by the production controller |
| L157-05 | 157 | Producer cannot bypass the broker or write the protected host journal; complete egress coverage is not inferred from a ledger. | `specs/157-producer-request-evidence/transport-design.md` (required production boundary) | integration-open | T157-05/T157-06 and Feature 156 integration |
| L158-01 | 158 | Bootstrap emits ready, blocks until exactly one gate byte, then starts the target; duplicate/early EOF fails closed. | `tests/test_trusted_bootstrap_runtime.py::test_child_does_not_inspect_target_before_gate_release`; `tests/test_trusted_bootstrap_runtime.py::test_runtime_durably_registers_before_release_and_starts_target_after_gate`; `tests/test_trusted_bootstrap_runtime.py::test_child_rejects_duplicate_gate_token_and_early_gate_eof` | supporting-only | bootstrap must be invoked by the formal runner |
| L158-02 | 158 | Bootstrap and target identities, target PID/PGID, and launch digests cross-bind independently. | `tests/test_trusted_bootstrap_binding.py::test_darwin_pair_has_distinct_immutable_bytes_after_sources_change`; `tests/test_trusted_bootstrap_handoff.py::test_handoff_verifier_rebinds_all_source_records` | supporting-only | Feature 156 registration must emit these records |
| L158-03 | 158 | Native isolation applies before target exec and denies undeclared writes, controller-secret reads, and network access. | `tests/test_producer_isolation.py::test_darwin_native_boundary_denies_network_and_outside_write`; `tests/test_trusted_bootstrap_runtime.py::test_runtime_durably_registers_before_release_and_starts_target_after_gate` | supporting-only | platform artifact must be allowlisted and attested |
| L158-04 | 158 | Bootstrap, registration, cleanup, recovery, broker evidence, and one monotonic attempt form one production lifecycle. | `specs/158-trusted-producer-bootstrap/tasks.md` T158-04; `specs/157-producer-request-evidence/transport-design.md` required production integration | integration-open | T158-04, T156-14, T157-06 |

## Acceptance reading rule

The matrix is accepted only when all rows are either `offline-verified` with their supporting
integration gates closed, or have an explicit terminal `integration-open` disposition approved by
the release plan. `supporting-only` never upgrades an arbitrary direct executable into a trusted
producer. A successful local fixture run is therefore evidence for the named row only; it does not
count as a real model attempt or as a Feature 139 primary/joint result.

The focused provider-free command for the rows implemented in this repository is:

```text
.venv/bin/python -m pytest -q --basetemp=/tmp/lunar-lifecycle-matrix \
  tests/test_producer_process.py tests/test_producer_request_transport.py \
  tests/test_controller_http_transport.py tests/test_trusted_bootstrap_runtime.py \
  tests/test_trusted_bootstrap_binding.py tests/test_trusted_bootstrap_handoff.py \
  tests/test_producer_isolation.py tests/test_lifecycle_acceptance_matrix.py
```

This command must remain provider-free. It must not be used as evidence that a production provider,
external producer, scheduler campaign, or WebAgent was run.
