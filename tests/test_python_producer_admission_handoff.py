"""Feature191 provider-free admission handoff contract and persistence tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lunar_evolution.python_producer_admission_handoff import (
    HANDOFF_STATE_EVALUATING,
    HANDOFF_STATE_PREPARED,
    HANDOFF_STATE_PUBLISHED,
    HANDOFF_STATE_UNKNOWN,
    PythonProducerAdmissionHandoffError,
    build_python_producer_admission_handoff,
    parse_python_producer_admission_handoff,
    persist_python_producer_admission_handoff,
    prepare_python_producer_admission_handoff,
    read_python_producer_admission_handoff,
    reconcile_python_producer_admission_handoff,
    replay_python_producer_admission_handoff,
    replay_python_producer_admission_handoff_file,
)


def _fixture(*, state: str = HANDOFF_STATE_PREPARED) -> dict[str, object]:
    digest = hashlib.sha256(b"fixture").hexdigest()
    return {
        "run_id": "run-1",
        "journal_id": "journal-1",
        "parent_task_id": "parent-1",
        "task_id": "task-1",
        "binding_sha256": digest,
        "sidecar_raw_sha256": digest,
        "sidecar_pin_sha256": digest,
        "launch_intent_sha256": digest,
        "attestation_sha256": digest,
        "runtime_manifest_sha256": digest,
        "runtime_tree_sha256": digest,
        "executable_owner_sha256": digest,
        "native_execution_receipt_sha256": digest,
        "terminal_sha256": digest,
        "runtime_observation_sha256": digest,
        "broker_transcript_sha256": digest,
        "envelope_sha256": digest,
        "materials_sha256": digest,
        "contract_sha256": digest,
        "evaluator_sha256": digest,
        "runner_sha256": digest,
        "dependency_sha256": digest,
        "environment_sha256": digest,
        "admission_plan_sha256": digest,
        "request_budget": 2,
        "wall_timeout_seconds": 30.0,
        "deadline_unix": 4102444800.0,
        "state": state,
    }


def test_builder_emits_sorted_canonical_self_digest_and_detaches_input() -> None:
    payload = _fixture()
    handoff = build_python_producer_admission_handoff(payload)
    payload["run_id"] = "changed-after-build"
    encoded = handoff.to_json()
    assert encoded == json.dumps(
        handoff.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    assert handoff.handoff_sha256 == hashlib.sha256(
        json.dumps(
            {key: value for key, value in handoff.to_dict().items() if key != "handoff_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert parse_python_producer_admission_handoff(encoded) == handoff


def test_parser_rejects_noncanonical_duplicate_missing_and_digest_drift() -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    with pytest.raises(PythonProducerAdmissionHandoffError, match="noncanonical"):
        parse_python_producer_admission_handoff(b" " + handoff.to_json())
    duplicate = handoff.to_json().replace(b'"state":"prepared"', b'"state":"prepared","state":"prepared"')
    with pytest.raises(PythonProducerAdmissionHandoffError, match="duplicate_json_key"):
        parse_python_producer_admission_handoff(duplicate)
    malformed = handoff.to_dict()
    del malformed["envelope_sha256"]
    with pytest.raises(PythonProducerAdmissionHandoffError, match="schema_invalid"):
        parse_python_producer_admission_handoff(malformed)
    forged = handoff.to_dict()
    forged["task_id"] = "task-2"
    with pytest.raises(PythonProducerAdmissionHandoffError, match="digest_mismatch"):
        parse_python_producer_admission_handoff(forged)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="digest_mismatch"):
        prepare_python_producer_admission_handoff(forged)
    object.__setattr__(handoff, "task_id", "task-forged")
    with pytest.raises(PythonProducerAdmissionHandoffError, match="digest_mismatch"):
        parse_python_producer_admission_handoff(handoff)


def test_create_only_persistence_and_identical_replay(tmp_path: Path) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    stored = persist_python_producer_admission_handoff(tmp_path, handoff=handoff)
    path = tmp_path / "python-producer-admission-handoff.json"
    assert stored == handoff
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_nlink == 1
    assert persist_python_producer_admission_handoff(path, handoff=handoff) == handoff
    changed = build_python_producer_admission_handoff({**_fixture(), "task_id": "task-2"})
    with pytest.raises(PythonProducerAdmissionHandoffError, match="already_exists"):
        persist_python_producer_admission_handoff(path, handoff=changed)


def test_read_rejects_missing_expected_digest_and_file_drift(tmp_path: Path) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    persist_python_producer_admission_handoff(tmp_path, handoff=handoff)
    path = tmp_path / "python-producer-admission-handoff.json"
    with pytest.raises(PythonProducerAdmissionHandoffError, match="digest_mismatch"):
        read_python_producer_admission_handoff(path, expected_handoff_sha256="f" * 64)
    path.write_bytes(handoff.to_json().replace(b'"task-1"', b'"task-2"'))
    with pytest.raises(PythonProducerAdmissionHandoffError, match="digest_mismatch"):
        read_python_producer_admission_handoff(path)


def test_prepare_reconcile_and_replay_are_explicit_read_only_state_gates() -> None:
    prepared = build_python_producer_admission_handoff(_fixture())
    assert prepare_python_producer_admission_handoff(prepared) == prepared
    with pytest.raises(PythonProducerAdmissionHandoffError, match="reconcile_state_invalid"):
        reconcile_python_producer_admission_handoff(prepared)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="replay_state_invalid"):
        replay_python_producer_admission_handoff(prepared)

    evaluating = build_python_producer_admission_handoff(
        _fixture(state=HANDOFF_STATE_EVALUATING)
    )
    with pytest.raises(PythonProducerAdmissionHandoffError, match="prepare_state_invalid"):
        prepare_python_producer_admission_handoff(evaluating)

    unknown = build_python_producer_admission_handoff(_fixture(state=HANDOFF_STATE_UNKNOWN))
    assert reconcile_python_producer_admission_handoff(unknown) == unknown
    published = build_python_producer_admission_handoff(_fixture(state=HANDOFF_STATE_PUBLISHED))
    assert replay_python_producer_admission_handoff(published) == published


def test_file_replay_requires_terminal_state_and_retained_digest(tmp_path: Path) -> None:
    prepared = build_python_producer_admission_handoff(_fixture())
    persist_python_producer_admission_handoff(tmp_path, handoff=prepared)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="replay_state_invalid"):
        replay_python_producer_admission_handoff_file(
            tmp_path, expected_handoff_sha256=prepared.handoff_sha256
        )

    # A published projection is a separate create-only record and can be replayed without any
    # evaluator, transaction, or producer callback.
    published = build_python_producer_admission_handoff(_fixture(state=HANDOFF_STATE_PUBLISHED))
    published_path = tmp_path / "published.json"
    persist_python_producer_admission_handoff(published_path, handoff=published)
    assert replay_python_producer_admission_handoff_file(
        published_path, expected_handoff_sha256=published.handoff_sha256
    ) == published


def test_file_io_rejects_symlinked_ancestor_and_destination(tmp_path: Path) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    real = tmp_path / "real"
    real.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real, target_is_directory=True)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="parent_invalid"):
        persist_python_producer_admission_handoff(linked_parent, handoff=handoff)

    destination = real / "python-producer-admission-handoff.json"
    destination.symlink_to(tmp_path / "outside.json")
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_identity_invalid"):
        read_python_producer_admission_handoff(destination)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_identity_invalid"):
        persist_python_producer_admission_handoff(destination, handoff=handoff)


def test_file_io_rejects_oversize_before_read_and_retains_failed_write(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b"{" + b"x" * 262144 + b"}")
    path.chmod(0o600)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="record_too_large"):
        read_python_producer_admission_handoff(path)

    handoff = build_python_producer_admission_handoff(_fixture())
    failed_path = tmp_path / "failed.json"
    original_fsync = os.fsync

    def fail_first_fsync(fd: int) -> None:
        if not hasattr(fail_first_fsync, "called"):
            fail_first_fsync.called = True
            raise OSError("fixture fsync failure")
        original_fsync(fd)

    monkeypatch.setattr(os, "fsync", fail_first_fsync)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="write_unknown"):
        persist_python_producer_admission_handoff(failed_path, handoff=handoff)
    assert failed_path.exists()
    assert failed_path.read_bytes() == handoff.to_json()
