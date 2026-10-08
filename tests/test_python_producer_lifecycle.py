"""Pure Feature191 terminal/observation and unknown-reconcile contracts."""

from __future__ import annotations

import json
from collections.abc import Mapping

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution.producer_process import ProducerExecutionReceipt, ProducerStreamEvidence
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_lifecycle import (
    PythonProducerLifecycleError,
    PythonProducerRuntimeObservation,
    bind_python_producer_receipt,
    build_python_producer_runtime_observation,
    build_python_producer_terminal,
    parse_python_producer_runtime_observation,
    parse_python_producer_terminal,
    reconcile_python_producer_terminal,
    resume_python_producer_terminal,
)

D = "a" * 64


def terminal(**changes):
    value = {
        "binding_sha256": D,
        "run_id": "run-1",
        "journal_id": "journal-1",
        "launch_id": "launch-1",
        "process_registration_sha256": None,
        "owner_identity_sha256": None,
        "executable_sha256": None,
        "executable_size": None,
        "executable_device": None,
        "executable_inode": None,
        "started_unix": 10.0,
        "released_unix": None,
        "exited_unix": None,
        "deadline_unix": 100.0,
        "status": "unknown",
        "exit_code": None,
        "signal": None,
        "cleanup_status": "missing",
        "request_journal_sha256": None,
        "request_count": 0,
        "stdout_sha256": D,
        "stderr_sha256": D,
        "publication_eligible": False,
    }
    value.update(changes)
    return build_python_producer_terminal(**value)


def completed_terminal(**changes):
    value = {
        "process_registration_sha256": D,
        "owner_identity_sha256": D,
        "executable_sha256": D,
        "executable_size": 10,
        "executable_device": 1,
        "executable_inode": 2,
        "released_unix": 11.0,
        "exited_unix": 12.0,
        "status": "completed",
        "exit_code": 0,
        "cleanup_status": "cleaned",
        "request_journal_sha256": D,
        "request_count": 1,
    }
    value.update(changes)
    return terminal(**value)


def observation():
    return build_python_producer_runtime_observation(
        binding_sha256=D,
        execution_performed=True,
        version_major=3,
        version_minor=13,
        version_micro=12,
        cache_tag="cpython-313",
        abi_profile="cp313-ordinary-gil",
        argv=("fixture", "--fixed"),
        orig_argv=("fixture", "--fixed"),
        flags=("-B", "-I", "-S"),
        filesystem_encoding="utf-8",
        filesystem_errors="surrogateescape",
        stdio_encoding="utf-8",
        stdio_errors="surrogateescape",
        sys_path=(".",),
        startup_modules=("_io", "site"),
        broker_transcript_sha256=D,
        pycache_absent=True,
        computation_sha256=D,
    )


def test_unknown_terminal_roundtrip_is_not_publication_eligible():
    item = terminal()
    assert item.terminal_sha256 == item.digest()
    assert parse_python_producer_terminal(item.to_json()) == item
    assert item.publication_eligible is False


def test_completed_terminal_roundtrip_and_resume_is_read_only():
    item = completed_terminal()
    replay = resume_python_producer_terminal(
        item.to_json(), expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    )
    assert replay == item
    assert parse_python_producer_terminal(item.to_json()) == item


def test_unknown_reconcile_requires_complete_process_and_cleanup_evidence():
    old = terminal()
    current = completed_terminal()
    assert reconcile_python_producer_terminal(
        old, current, expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    ) == current
    assert reconcile_python_producer_terminal(
        old, old, expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
    ) == old
    with pytest.raises(PythonProducerLifecycleError, match="terminal_evidence_missing"):
        reconcile_python_producer_terminal(
            old, terminal(status="failed", cleanup_status="unknown"),
            expected_binding={"binding_sha256": D, "deadline_unix": 100.0},
        )


def test_reconcile_rejects_binding_or_deadline_drift_and_terminal_mutation():
    old = completed_terminal()
    with pytest.raises(PythonProducerLifecycleError, match="binding_drift"):
        reconcile_python_producer_terminal(old, old, expected_binding={"binding_sha256": "b" * 64, "deadline_unix": 100.0})
    with pytest.raises(PythonProducerLifecycleError, match="deadline_drift"):
        reconcile_python_producer_terminal(old, old, expected_binding={"binding_sha256": D, "deadline_unix": 101.0})
    with pytest.raises(PythonProducerLifecycleError, match="terminal_immutable"):
        reconcile_python_producer_terminal(
            old, completed_terminal(request_count=2), expected_binding={"binding_sha256": D, "deadline_unix": 100.0}
        )


def test_observation_is_canonical_and_protection_claims_stay_false():
    item = observation()
    assert item.observation_sha256 == item.digest()
    assert parse_python_producer_runtime_observation(item.to_json()) == item
    payload = json.loads(item.to_json())
    payload["production_admission"] = True
    with pytest.raises(PythonProducerLifecycleError, match="unsupported_protection_claim"):
        parse_python_producer_runtime_observation(payload)


def test_parser_rejects_duplicate_and_noncanonical_json():
    raw = terminal().to_json()
    with pytest.raises(PythonProducerLifecycleError, match="duplicate_json_key"):
        parse_python_producer_terminal(raw[:-1] + b',"status":"unknown"}')
    with pytest.raises(PythonProducerLifecycleError, match="noncanonical_json"):
        parse_python_producer_terminal(json.dumps(json.loads(raw), indent=2))
    with pytest.raises(PythonProducerLifecycleError, match="reconcile_required"):
        resume_python_producer_terminal(terminal(), expected_binding={"binding_sha256": D, "deadline_unix": 100.0})


@pytest.mark.parametrize("operation", ["resume", "reconcile"])
def test_retained_dto_tampering_is_rejected_before_replay(operation):
    item = completed_terminal()
    object.__setattr__(item, "request_count", 2)
    with pytest.raises(PythonProducerLifecycleError, match="terminal_digest_mismatch"):
        if operation == "resume":
            resume_python_producer_terminal(item, expected_binding=D)
        else:
            reconcile_python_producer_terminal(item, item, expected_binding=D)


@pytest.mark.parametrize("field", [
    "process_registration_sha256", "owner_identity_sha256", "executable_sha256", "request_journal_sha256",
    "executable_size", "executable_device", "executable_inode", "started_unix", "released_unix", "exited_unix",
])
def test_unknown_reconcile_preserves_each_available_original_pin(field):
    old = completed_terminal(status="unknown")
    values = {
        "process_registration_sha256": "b" * 64, "owner_identity_sha256": "b" * 64,
        "executable_sha256": "b" * 64, "request_journal_sha256": "b" * 64,
        "executable_size": 11, "executable_device": 2, "executable_inode": 3,
        "started_unix": 9.0, "released_unix": 10.5, "exited_unix": 13.0,
    }
    current = completed_terminal(**{field: values[field]})
    with pytest.raises(PythonProducerLifecycleError, match="retained_evidence_drift"):
        reconcile_python_producer_terminal(old, current, expected_binding=D)


def test_reconcile_without_explicit_deadline_still_preserves_original_deadline():
    with pytest.raises(PythonProducerLifecycleError, match="deadline_drift"):
        reconcile_python_producer_terminal(terminal(), completed_terminal(deadline_unix=101.0), expected_binding=D)
    with pytest.raises(PythonProducerLifecycleError, match="deadline_drift"):
        resume_python_producer_terminal(
            completed_terminal(), expected_binding={"binding_sha256": D, "deadline_unix": 101.0},
            expected_deadline_unix=100.0,
        )


@pytest.mark.parametrize("field", [
    "process_registration_sha256", "owner_identity_sha256", "executable_sha256", "request_journal_sha256",
    "executable_size", "executable_device", "executable_inode", "started_unix", "released_unix", "exited_unix",
])
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_known_terminal_requires_complete_process_identity_and_timestamps(field, status):
    with pytest.raises(PythonProducerLifecycleError, match="terminal_evidence_missing"):
        completed_terminal(**{field: None, "status": status})


@pytest.mark.parametrize("changes,code", [
    ({"started_unix": 11.5}, "terminal_time_order_invalid"),
    ({"released_unix": 13.0}, "terminal_time_order_invalid"),
    ({"exited_unix": 100.0}, "completed_deadline_exceeded"),
    ({"deadline_unix": 0.0}, "deadline_unix_invalid"),
    ({"executable_inode": 0}, "terminal_executable_identity_invalid"),
    ({"publication_eligible": True}, "unsupported_publication_claim"),
])
def test_terminal_time_identity_and_publication_gates(changes, code):
    with pytest.raises(PythonProducerLifecycleError, match=code):
        completed_terminal(**changes)


def test_reconcile_cannot_refresh_retained_request_journal_count():
    old = completed_terminal(status="unknown")
    with pytest.raises(PythonProducerLifecycleError, match="request_count_drift"):
        reconcile_python_producer_terminal(old, completed_terminal(request_count=2), expected_binding=D)


@pytest.mark.parametrize("record,digest", [
    (terminal, "terminal_sha256"), (observation, "observation_sha256"),
])
@pytest.mark.parametrize("value", [None, "0" * 64])
def test_detached_record_cannot_replace_missing_or_placeholder_digest(record, digest, value):
    payload = record().to_dict()
    payload[digest] = value
    parse = parse_python_producer_terminal if digest == "terminal_sha256" else parse_python_producer_runtime_observation
    with pytest.raises(PythonProducerLifecycleError, match="digest_invalid"):
        parse(payload)


class CallbackMapping(Mapping):
    def __iter__(self):
        pytest.fail("mapping iteration callback")

    def __len__(self):
        raise AssertionError("mapping length callback")

    def __getitem__(self, _key):
        pytest.fail("mapping lookup callback")


class CallbackIterable:
    def __iter__(self):
        pytest.fail("collection iteration callback")


@pytest.mark.parametrize("parse", [parse_python_producer_terminal, parse_python_producer_runtime_observation])
def test_parser_rejects_callback_mapping_without_inspection(parse):
    with pytest.raises(PythonProducerLifecycleError, match="json_invalid"):
        parse(CallbackMapping())


def test_resume_rejects_callback_expected_binding_without_inspection():
    with pytest.raises(PythonProducerLifecycleError, match="binding_invalid"):
        resume_python_producer_terminal(completed_terminal(), expected_binding=CallbackMapping())


@pytest.mark.parametrize("field", ["argv", "orig_argv", "flags", "sys_path", "startup_modules"])
@pytest.mark.parametrize("value", ["abc", {"abc": 1}, CallbackIterable()])
def test_observation_parser_requires_exact_bounded_list_before_conversion(field, value):
    payload = observation().to_dict()
    payload[field] = value
    with pytest.raises(PythonProducerLifecycleError, match=f"{field}_invalid"):
        parse_python_producer_runtime_observation(payload)


def test_observation_rejects_mutated_collection_before_serialization():
    item = observation()
    object.__setattr__(item, "argv", CallbackIterable())
    with pytest.raises(PythonProducerLifecycleError, match="argv_invalid"):
        item.to_json()
    payload = observation().to_dict()
    payload["argv"] = ["fixture"] * 257
    with pytest.raises(PythonProducerLifecycleError, match="argv_invalid"):
        parse_python_producer_runtime_observation(payload)


def test_runtime_observation_constructor_requires_immutable_tuple():
    item = observation()
    raw = dict(item.__dataclass_fields__)
    kwargs = {key: getattr(item, key) for key in raw}
    kwargs["argv"] = ["fixture"]
    with pytest.raises(PythonProducerLifecycleError, match="argv_invalid"):
        PythonProducerRuntimeObservation(**kwargs)


def bound_fixture(tmp_path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    return build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )


def bound_terminal(binding, **changes):
    return completed_terminal(**({
        "binding_sha256": binding.binding_sha256, "deadline_unix": binding.deadline_unix,
        "executable_sha256": binding.interpreter_sha256, "executable_size": binding.interpreter.size,
        "executable_device": binding.interpreter.device, "executable_inode": binding.interpreter.inode,
    } | changes))


@pytest.mark.parametrize("field,value", [
    ("run_id", "other"), ("executable_sha256", "b" * 64), ("executable_inode", 1),
    ("request_count", 4),
])
def test_full_binding_checks_terminal_identity_interpreter_and_original_budget(tmp_path, field, value):
    binding = bound_fixture(tmp_path)
    with pytest.raises(PythonProducerLifecycleError, match="binding_identity_drift|request_budget_exceeded"):
        resume_python_producer_terminal(bound_terminal(binding, **{field: value}), expected_binding=binding)
    assert resume_python_producer_terminal(bound_terminal(binding), expected_binding=binding).status == "completed"


def test_reused_binding_digest_is_verified_before_terminal_replay(tmp_path):
    binding = bound_fixture(tmp_path)
    item = bound_terminal(binding)
    object.__setattr__(binding, "deadline_unix", binding.deadline_unix + 1)
    with pytest.raises(PythonProducerLifecycleError, match="binding_invalid"):
        resume_python_producer_terminal(item, expected_binding=binding)


def receipt_fixture(binding, *, status="completed"):
    return ProducerExecutionReceipt(
        launch_id=binding.intent.launch_id, journal_id=binding.intent.journal_id, run_id=binding.run_id,
        parent_task_id=binding.parent_task_id, task_id=binding.task_id,
        intent_sha256=binding.intent_sha256, attestation_sha256=binding.attestation_sha256,
        consumption_sha256=D, registration_sha256=D, executable_identity=D, pid=41, pgid=41,
        owner_identity={"pid": 41}, gate_released=True, request_timeout_seconds=5, max_requests=3,
        output_max_bytes=4096, wall_timeout_seconds=10, request_count=1, exit_code=0,
        stdout_evidence=ProducerStreamEvidence("stdout", 0, D, False, "complete"),
        stderr_evidence=ProducerStreamEvidence("stderr", 0, D, False, "complete"),
        envelope_evidence=None, cleanup_status="cleaned", cleanup_sha256=D,
        execution_binding="linux-sealed-memfd", execution_snapshot_relative_path=None,
        execution_snapshot_sha256=binding.interpreter_sha256, execution_snapshot_size=binding.interpreter.size,
        status=status,
    )


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_process_receipt_projection_keeps_missing_runtime_terminal_unknown(tmp_path, status):
    binding = bound_fixture(tmp_path)
    receipt = receipt_fixture(binding, status=status)
    item = bind_python_producer_receipt(binding, receipt)
    assert item.status == "unknown"
    assert item.executable_sha256 == binding.interpreter_sha256
    assert item.executable_size == binding.interpreter.size
    assert item.started_unix is None and item.executable_inode is None
    assert item.publication_eligible is False
    assert receipt.status == status


def test_process_receipt_projection_rechecks_retained_receipt_digest(tmp_path):
    binding = bound_fixture(tmp_path)
    receipt = receipt_fixture(binding)
    object.__setattr__(receipt, "request_count", 2)
    with pytest.raises(PythonProducerLifecycleError, match="receipt_invalid"):
        bind_python_producer_receipt(binding, receipt)


def test_process_receipt_projection_accepts_fresh_builder_without_self_digest(tmp_path):
    binding = bound_fixture(tmp_path)
    receipt = receipt_fixture(binding)
    object.__setattr__(receipt, "receipt_sha256", None)
    item = bind_python_producer_receipt(binding, receipt)
    assert item.status == "unknown" and item.publication_eligible is False
    assert receipt.receipt_sha256 is None
