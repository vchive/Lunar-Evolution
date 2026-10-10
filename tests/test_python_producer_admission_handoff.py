"""Feature191 provider-free admission handoff contract and persistence tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from lunar_evolution import python_producer_admission_handoff as handoff_module
from lunar_evolution.python_producer_admission_handoff import (
    HANDOFF_STATE_EVALUATING,
    HANDOFF_STATE_PREPARED,
    HANDOFF_STATE_PUBLISHED,
    HANDOFF_STATE_UNKNOWN,
    PythonProducerAdmissionHandoffError,
    PythonProducerAdmissionHandoffFilePin,
    build_python_producer_admission_handoff,
    parse_python_producer_admission_handoff,
    parse_python_producer_admission_handoff_file_pin,
    persist_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
    prepare_python_producer_admission_handoff,
    read_python_producer_admission_handoff,
    read_python_producer_admission_handoff_pinned,
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


def _resigned_pin(pin: PythonProducerAdmissionHandoffFilePin, **changes: object) -> dict[str, object]:
    payload = {**pin.to_dict(), **changes}
    payload.pop("pin_sha256")
    payload["pin_sha256"] = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return payload


def test_pinned_creator_retains_final_file_and_parent_identity_and_exact_replay(tmp_path: Path, monkeypatch) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    pin = sidecar.file_pin
    path = tmp_path / "python-producer-admission-handoff.json"
    before = path.stat()
    assert sidecar.handoff == handoff
    assert pin.handoff_sha256 == handoff.handoff_sha256
    assert pin.raw_sha256 == hashlib.sha256(handoff.to_json()).hexdigest()
    assert pin.raw_sha256 != handoff.handoff_sha256
    assert pin.raw_size == len(handoff.to_json())
    assert (pin.file_device, pin.file_inode) == (before.st_dev, before.st_ino)
    assert (pin.file_mtime_ns, pin.file_ctime_ns) == (before.st_mtime_ns, before.st_ctime_ns)
    assert (pin.parent_device, pin.parent_inode) == (tmp_path.stat().st_dev, tmp_path.stat().st_ino)
    assert pin.file_mode == 0o600 and pin.file_nlink == 1
    assert parse_python_producer_admission_handoff_file_pin(pin.to_json()) == pin
    assert PythonProducerAdmissionHandoffFilePin.from_dict(pin.to_dict()) == pin
    assert PythonProducerAdmissionHandoffFilePin.from_json(pin.to_json()) == pin

    # Creating publication journals changes directory metadata legitimately; only
    # the original parent device/inode belongs in this pin.
    (tmp_path / "journal.prepared.json").write_text("fixture")

    def no_write(*args, **kwargs):
        pytest.fail("retained-pin replay must not write or fsync")

    monkeypatch.setattr(os, "write", no_write)
    monkeypatch.setattr(os, "fsync", no_write)
    assert read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=pin) == sidecar
    assert persist_python_producer_admission_handoff_pinned(
        path, handoff=handoff, expected_file_pin=pin,
    ) == sidecar
    after = path.stat()
    assert handoff_module._metadata(after) == handoff_module._metadata(before)


def test_pinned_creator_does_not_adopt_existing_bytes_or_recreate_missing_original(tmp_path: Path) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    path = tmp_path / "python-producer-admission-handoff.json"
    original = path.stat()
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_required"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    assert path.stat().st_ino == original.st_ino
    path.unlink()
    with pytest.raises(PythonProducerAdmissionHandoffError, match="missing"):
        persist_python_producer_admission_handoff_pinned(
            tmp_path, handoff=handoff, expected_file_pin=sidecar.file_pin,
        )
    assert not path.exists()


@pytest.mark.parametrize("changes", [
    {"raw_size": 0}, {"raw_size": 262145}, {"raw_size": True},
    {"file_device": -1}, {"file_device": 2**64}, {"file_device": True},
    {"file_inode": 0}, {"file_inode": True},
    {"parent_device": -1}, {"parent_device": True},
    {"parent_inode": 0}, {"parent_inode": 2**64}, {"parent_inode": True},
    {"file_mode": 0o644}, {"file_mode": True},
    {"file_nlink": 2}, {"file_nlink": True},
    {"file_mtime_ns": -1}, {"file_mtime_ns": True},
    {"file_ctime_ns": 2**64}, {"file_ctime_ns": True},
    {"run_id": "secret=do-not-use"}, {"handoff_sha256": "0" * 64},
    {"raw_sha256": "invalid"}, {"extra": 1},
])
def test_malformed_resigned_pin_refuses_before_filesystem_io(tmp_path: Path, monkeypatch, changes) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    payload = _resigned_pin(sidecar.file_pin, **changes)

    def no_io(*args, **kwargs):
        pytest.fail("invalid retained pin reached path/filesystem access")

    monkeypatch.setattr(handoff_module, "_path", no_io)
    monkeypatch.setattr(handoff_module, "_directory", no_io)
    with pytest.raises(PythonProducerAdmissionHandoffError):
        read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=payload)
    with pytest.raises(PythonProducerAdmissionHandoffError):
        persist_python_producer_admission_handoff_pinned(
            tmp_path, handoff=handoff, expected_file_pin=payload,
        )


def test_pin_parser_rejects_noncanonical_duplicate_digest_and_reused_dto_drift(tmp_path: Path, monkeypatch) -> None:
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=_fixture())
    pin = sidecar.file_pin
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_noncanonical"):
        parse_python_producer_admission_handoff_file_pin(b" " + pin.to_json())
    duplicated = pin.to_json().replace(b'"file_nlink":1', b'"file_nlink":1,"file_nlink":1')
    with pytest.raises(PythonProducerAdmissionHandoffError, match="duplicate_json_key"):
        parse_python_producer_admission_handoff_file_pin(duplicated)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_digest_mismatch"):
        parse_python_producer_admission_handoff_file_pin({**pin.to_dict(), "task_id": "task-2"})
    object.__setattr__(pin, "file_inode", pin.file_inode + 1)
    monkeypatch.setattr(handoff_module, "_directory", lambda path: pytest.fail("mutated pin reached I/O"))
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_digest_mismatch"):
        read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=pin)


@pytest.mark.parametrize("drift", ["replacement", "touch", "chmod", "hardlink", "symlink", "bytes"])
def test_pinned_reader_refuses_cross_read_original_identity_drift(tmp_path: Path, drift: str) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    path = tmp_path / "python-producer-admission-handoff.json"
    original = path.stat()
    if drift == "replacement":
        replacement = tmp_path / "replacement.json"
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        os.replace(replacement, path)
        assert path.stat().st_ino != original.st_ino
    elif drift == "touch":
        os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    elif drift == "chmod":
        path.chmod(0o644)
    elif drift == "hardlink":
        os.link(path, tmp_path / "alias.json")
    elif drift == "symlink":
        path.rename(tmp_path / "original.json")
        path.symlink_to(tmp_path / "original.json")
    else:
        path.write_bytes(handoff.to_json().replace(b'"task-1"', b'"task-2"'))
    with pytest.raises(PythonProducerAdmissionHandoffError):
        read_python_producer_admission_handoff_pinned(path, expected_file_pin=sidecar.file_pin)
    with pytest.raises(PythonProducerAdmissionHandoffError):
        persist_python_producer_admission_handoff_pinned(
            path, handoff=handoff, expected_file_pin=sidecar.file_pin,
        )


def test_pinned_reader_refuses_original_batch_route_replacement(tmp_path: Path) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(batch, handoff=handoff)
    batch.rename(tmp_path / "original-batch")
    batch.mkdir()
    path = batch / "python-producer-admission-handoff.json"
    path.write_bytes(handoff.to_json())
    path.chmod(0o600)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_parent_drift"):
        read_python_producer_admission_handoff_pinned(batch, expected_file_pin=sidecar.file_pin)


@pytest.mark.parametrize("boundary", ["write", "fsync", "readback"])
def test_pinned_creator_refuses_replacement_during_original_write_or_readback(tmp_path: Path, monkeypatch, boundary: str) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    path = tmp_path / "python-producer-admission-handoff.json"
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(handoff.to_json())
    replacement.chmod(0o600)
    replacement_inode = replacement.stat().st_ino
    fired = False

    def swap() -> None:
        nonlocal fired
        if not fired:
            fired = True
            os.replace(replacement, path)

    if boundary == "write":
        original_write = os.write

        def changed_write(fd, data):
            count = original_write(fd, data)
            swap()
            return count

        monkeypatch.setattr(os, "write", changed_write)
    elif boundary == "fsync":
        original_fsync = os.fsync

        def changed_fsync(fd):
            original_fsync(fd)
            swap()

        monkeypatch.setattr(os, "fsync", changed_fsync)
    else:
        original_read = handoff_module._read_file_observation

        def changed_read(*args, **kwargs):
            result = original_read(*args, **kwargs)
            swap()
            return result

        monkeypatch.setattr(handoff_module, "_read_file_observation", changed_read)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_identity_drift"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    assert fired
    assert path.stat().st_ino == replacement_inode
    assert path.read_bytes() == handoff.to_json()


def test_pinned_creator_retains_partial_unknown_write_without_minting_or_adopting(tmp_path: Path, monkeypatch) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    path = tmp_path / "python-producer-admission-handoff.json"
    original_write = os.write
    calls = 0

    def partial_write(fd, data):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(fd, data[:25])
        raise OSError("fixture unknown write")

    monkeypatch.setattr(os, "write", partial_write)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="write_unknown"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    original_inode = path.stat().st_ino
    assert path.read_bytes() == handoff.to_json()[:25]
    monkeypatch.setattr(os, "write", original_write)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_required"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    assert path.stat().st_ino == original_inode
    assert path.read_bytes() == handoff.to_json()[:25]


@pytest.mark.parametrize("changes", [
    {"raw_sha256": hashlib.sha256(b"forged").hexdigest()},
    {"raw_size": 1},
    {"task_id": "task-2"},
    {"handoff_sha256": hashlib.sha256(b"forged").hexdigest()},
])
def test_validly_signed_pin_cannot_authorize_a_different_handoff_or_raw_file(tmp_path: Path, monkeypatch, changes) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    pin = parse_python_producer_admission_handoff_file_pin(_resigned_pin(sidecar.file_pin, **changes))
    # A detached pin parses independently; the reader must join it with the original
    # file and the replay request must join it before opening any pathname.
    with pytest.raises(PythonProducerAdmissionHandoffError):
        read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=pin)
    monkeypatch.setattr(handoff_module, "_path", lambda path: pytest.fail("mismatched replay reached I/O"))
    with pytest.raises(PythonProducerAdmissionHandoffError):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff, expected_file_pin=pin)


def test_pin_parser_does_not_invoke_mapping_subclass_callbacks(tmp_path: Path, monkeypatch) -> None:
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=_fixture())

    class CallbackMapping(dict):
        def __iter__(self):
            pytest.fail("pin validation invoked caller mapping callback")

        def __getitem__(self, key):
            pytest.fail("pin validation invoked caller mapping callback")

    pin = CallbackMapping(sidecar.file_pin.to_dict())
    monkeypatch.setattr(handoff_module, "_path", lambda path: pytest.fail("callback pin reached I/O"))
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_schema_invalid"):
        read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=pin)


@pytest.mark.parametrize("drift", ["replacement", "touch"])
def test_pinned_reader_refuses_drift_during_held_fd_read(tmp_path: Path, monkeypatch, drift: str) -> None:
    sidecar = persist_python_producer_admission_handoff_pinned(tmp_path, handoff=_fixture())
    path = tmp_path / "python-producer-admission-handoff.json"
    original = path.stat()
    raw = path.read_bytes()
    original_read = os.read
    fired = False

    def changed_read(fd, count):
        nonlocal fired
        result = original_read(fd, count)
        if not fired:
            fired = True
            if drift == "replacement":
                replacement = tmp_path / "replacement.json"
                replacement.write_bytes(raw)
                replacement.chmod(0o600)
                os.replace(replacement, path)
            else:
                os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
        return result

    monkeypatch.setattr(os, "read", changed_read)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_identity_drift"):
        read_python_producer_admission_handoff_pinned(tmp_path, expected_file_pin=sidecar.file_pin)
    assert fired
    assert path.read_bytes() == raw


def test_pinned_creator_does_not_adopt_complete_orphan_after_fsync_unknown(tmp_path: Path, monkeypatch) -> None:
    handoff = build_python_producer_admission_handoff(_fixture())
    path = tmp_path / "python-producer-admission-handoff.json"
    original_fsync = os.fsync

    def failed_fsync(fd):
        raise OSError("fixture unknown fsync")

    monkeypatch.setattr(os, "fsync", failed_fsync)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="write_unknown"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    original_inode = path.stat().st_ino
    assert path.read_bytes() == handoff.to_json()
    monkeypatch.setattr(os, "fsync", original_fsync)
    with pytest.raises(PythonProducerAdmissionHandoffError, match="file_pin_required"):
        persist_python_producer_admission_handoff_pinned(tmp_path, handoff=handoff)
    assert path.stat().st_ino == original_inode
    assert path.read_bytes() == handoff.to_json()
