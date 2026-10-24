"""Provider-free Zig archive receipts; fixture payloads are never executed."""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import inspect
import json
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_static_python_archive_observation as archive_fixtures

from tools.static_python_fixture import archive_observation as archive
from tools.static_python_fixture import toolchain_observation as observation
from tools.static_python_fixture import verified_inputs

ROOT = "zig-x86_64-linux-0.16.0"
# Retained from a manually specified member table and deterministic USTAR/XZ
# fixture, independently of observe_toolchain_archive's output.
ARCHIVE_SHA256 = "94e9098489bc7dfcfb587a49a15965d36dd52e21a84e54d3ae43957f8e0661e0"
MANIFEST_SHA256 = "e6e38fcdc3c2f3d84a60350814b7002aea1ee43193e2ad0cc51cc269d8fc32c7"
CLAIMS = {
    "extracted_tree_observed", "toolchain_execution_performed", "configure_performed",
    "build_performed", "runtime_execution_performed", "production_admission",
    "online_publication",
}


def _compressed(*, extra: bool = False) -> bytes:
    entries = [
        (archive_fixtures._directory(ROOT), None),
        (archive_fixtures._directory(ROOT + "/lib"), None),
        archive_fixtures._file(ROOT + "/zig", b"inert-tool", mode=0o755),
        archive_fixtures._file(ROOT + "/lib/empty.h", b""),
        archive_fixtures._file(ROOT + "/lib/header.h", b"header\n"),
    ]
    if extra:
        entries.append(archive_fixtures._file(ROOT + "/extra", b"extra"))
    return archive_fixtures._compressed(*entries)


@pytest.fixture
def snapshot():
    raw = _compressed()
    assert len(raw) == 256 and hashlib.sha256(raw).hexdigest() == ARCHIVE_SHA256
    return archive.snapshot_inert_archive_bytes(raw, "zig")


def _observe(snapshot, **kwargs):
    inputs = {
        "expected_manifest_sha256": MANIFEST_SHA256, "deadline": 100.0,
        "monotonic": lambda: 1.0, "require_profile": False,
    }
    inputs.update(kwargs)
    return observation.observe_toolchain_archive(snapshot, **inputs)


def _refuses(snapshot, reason: str, **kwargs) -> None:
    with pytest.raises(observation.StaticPythonToolchainObservationError) as caught:
        _observe(snapshot, **kwargs)
    assert str(caught.value) == "static_python_toolchain_observation_" + reason


def test_complete_manifest_keeps_directories_zero_byte_file_and_original_wire(snapshot):
    result = _observe(snapshot)
    record, manifest = result.to_dict(), result.to_manifest()
    assert record == {
        "schema": observation.TOOLCHAIN_OBSERVATION_SCHEMA,
        "status": "inert-archive-observed", "archive": "zig", "root": ROOT,
        "version": "0.16.0", "archive_size": 256, "archive_sha256": ARCHIVE_SHA256,
        "snapshot_sha256": ARCHIVE_SHA256, "manifest_sha256": MANIFEST_SHA256,
        "source_identity": None, "member_count": 5, "file_count": 3,
        "directory_count": 2, "total_file_bytes": 17, "profile_pin_verified": False,
        "metadata_validation": "skipped-inert-profile",
        "signature_verification": "not-performed", "claims": dict.fromkeys(CLAIMS, False),
    }
    assert manifest["schema"] == "lunar-static-python-extraction-manifest-v1"
    assert [member["path"] for member in manifest["members"]] == [
        ROOT, ROOT + "/lib", ROOT + "/lib/empty.h", ROOT + "/lib/header.h", ROOT + "/zig",
    ]
    assert manifest["members"][2] == {
        "path": ROOT + "/lib/empty.h", "kind": "file", "size": 0, "mode": 0o644,
        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }
    assert "files" not in record and "members" not in record
    assert result.manifest_sha256 == hashlib.sha256(result.manifest_json).hexdigest()
    assert result.manifest_sha256 == MANIFEST_SHA256
    assert result.observation_sha256 == hashlib.sha256(result.canonical_json).hexdigest()
    assert result.canonical_json == json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode()


def test_result_is_immutable_and_projections_are_fresh(snapshot):
    result = _observe(snapshot)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.manifest_json = b"changed"
    record, manifest = result.to_dict(), result.to_manifest()
    record["claims"]["build_performed"] = True
    manifest["members"].clear()
    assert result.to_dict()["claims"]["build_performed"] is False
    assert len(result.to_manifest()["members"]) == 5
    assert _observe(snapshot).canonical_json == result.canonical_json


@pytest.mark.parametrize("pin", [None, "", "0" * 64, "f" * 64, "A" * 64, "a" * 63, 1, True])
def test_external_manifest_pin_is_mandatory_and_strict(snapshot, pin):
    _refuses(snapshot, "manifest_pin_invalid", expected_manifest_sha256=pin)


def test_omitted_pin_is_a_required_python_argument(snapshot):
    assert inspect.signature(observation.observe_toolchain_archive).parameters[
        "expected_manifest_sha256"
    ].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        observation.observe_toolchain_archive(snapshot, deadline=100.0, require_profile=False)


def test_wrong_manifest_pin_and_extra_member_refuse_in_inert_mode(snapshot):
    _refuses(snapshot, "manifest_pin_mismatch", expected_manifest_sha256="a" * 64)
    extra = archive.snapshot_inert_archive_bytes(_compressed(extra=True), "zig")
    _refuses(extra, "manifest_pin_mismatch")


def test_foreign_archive_and_untyped_snapshot_refuse(snapshot):
    _refuses(archive_fixtures._normal_snapshot(), "archive_invalid")
    _refuses(snapshot.compressed_bytes, "snapshot_invalid")


def test_archive_field_types_refuse_before_caller_comparison(snapshot):
    class HostileArchive:
        def __ne__(self, _other):
            raise RuntimeError("/private/path must not appear")

    class ArchiveSubclass(str):
        def __ne__(self, _other):
            raise RuntimeError("/private/path must not appear")

    for value in (None, 1, HostileArchive(), ArchiveSubclass("zig")):
        _refuses(dataclasses.replace(snapshot, archive=value), "archive_invalid")


@pytest.mark.parametrize("flag", [0, 1, None, "false"])
def test_profile_flag_requires_exact_bool(snapshot, flag):
    _refuses(snapshot, "profile_flag_invalid", require_profile=flag)


@pytest.mark.parametrize("deadline", [True, 100, None, float("inf"), float("nan"), 0.0, -1.0])
def test_deadline_requires_positive_finite_float(snapshot, deadline):
    _refuses(snapshot, "deadline_invalid", deadline=deadline)


@pytest.mark.parametrize("value", [True, None, "1", float("nan"), float("inf"), -float("inf")])
def test_clock_rejects_bool_nonfinite_and_non_numeric_results(snapshot, value):
    _refuses(snapshot, "clock_invalid", monotonic=lambda: value)


def test_clock_exceptions_are_redacted_at_entry_and_during_archive_walk(snapshot, monkeypatch):
    def fail():
        raise RuntimeError("/private/path must not appear")

    _refuses(snapshot, "clock_invalid", monotonic=fail)
    state = SimpleNamespace(failed=False)
    original = archive._member_bytes

    def member_bytes(*args, **kwargs):
        state.failed = True
        return original(*args, **kwargs)

    monkeypatch.setattr(archive, "_member_bytes", member_bytes)

    def clock():
        if state.failed:
            fail()
        return 1.0

    _refuses(snapshot, "clock_invalid", monotonic=clock)
    _refuses(snapshot, "clock_invalid", monotonic=None)


@pytest.mark.parametrize("changes,reason", [
    ({"compressed_bytes": b"corrupt"}, "archive_snapshot_integrity_invalid"),
    ({"archive_size": 1}, "archive_snapshot_integrity_invalid"),
    ({"snapshot_sha256": "a" * 64}, "archive_snapshot_integrity_invalid"),
    ({"root": "foreign"}, "archive_snapshot_profile_drift"),
    ({"version": "foreign"}, "archive_snapshot_profile_drift"),
    ({"expected_sha256": "a" * 64}, "archive_snapshot_profile_drift"),
    ({"profile_pin_verified": 1}, "archive_snapshot_profile_drift"),
    ({"source_identity": {}}, "archive_snapshot_integrity_invalid"),
    ({"signature_verification": "verified"}, "archive_signature_status_invalid"),
])
def test_snapshot_tamper_refuses_with_fixed_wrapped_error(snapshot, changes, reason):
    _refuses(dataclasses.replace(snapshot, **changes), reason)


def test_bytes_snapshot_and_forged_verification_do_not_satisfy_acquired_profile(snapshot):
    _refuses(snapshot, "archive_archive_pin_mismatch", require_profile=True)
    _refuses(dataclasses.replace(snapshot, profile_pin_verified=True),
             "archive_archive_pin_mismatch", require_profile=True)
    forged = dataclasses.replace(
        snapshot, profile_pin_verified=True,
        source_identity=archive.ArchiveSourceIdentity(1, 2, snapshot.archive_size, 0o644, 3, 4),
    )
    _refuses(forged, "archive_archive_pin_mismatch", require_profile=True)


def test_profile_observation_retains_acquisition_identity_and_inert_stays_false(
    snapshot, tmp_path, monkeypatch,
):
    # Exercise the real acquisition path with an explicitly pinned inert
    # profile, not a forged snapshot or execution of the fixture payload.
    profile = archive._Profile("zig", ROOT, "0.16.0", 256, ARCHIVE_SHA256)
    monkeypatch.setitem(archive._PROFILES, "zig", profile)
    monkeypatch.setattr(verified_inputs, "_ZIG", dataclasses.replace(
        verified_inputs._ZIG, size=256, sha256=ARCHIVE_SHA256,
    ))
    path = tmp_path / "inert.xz"
    path.write_bytes(snapshot.compressed_bytes)
    acquired = archive.snapshot_archive(path, "zig", deadline=100.0, monotonic=lambda: 1.0)
    record = _observe(acquired, require_profile=True).to_dict()
    assert record["status"] == "profile-pinned-archive-observed"
    assert record["profile_pin_verified"] is True
    assert record["metadata_validation"] == "validated"
    assert record["source_identity"] == dataclasses.asdict(acquired.source_identity)
    assert set(record["source_identity"]) == {
        "device", "inode", "size", "mode", "mtime_ns", "ctime_ns",
    }
    assert record["signature_verification"] == "not-performed"
    assert record["claims"] == dict.fromkeys(CLAIMS, False)
    inert = _observe(acquired).to_dict()
    assert inert["status"] == "inert-archive-observed"
    assert inert["profile_pin_verified"] is False
    assert inert["metadata_validation"] == "skipped-inert-profile"


@pytest.mark.parametrize("phase", [
    "entry", "archive", "member", "record", "serialization", "digest", "return",
])
def test_original_deadline_remains_active_through_final_return(snapshot, monkeypatch, phase):
    state = SimpleNamespace(now=100.0 if phase == "entry" else 1.0)

    def expire_after(function):
        def wrapped(*args, **kwargs):
            result = function(*args, **kwargs)
            state.now = 100.0
            return result
        return wrapped

    if phase == "archive":
        original = observation._observe_archive_snapshot

        def expired_archive(*args, **kwargs):
            state.now = 100.0
            return original(*args, **kwargs)

        monkeypatch.setattr(observation, "_observe_archive_snapshot", expired_archive)
    elif phase == "member":
        monkeypatch.setattr(archive, "_member_bytes", expire_after(archive._member_bytes))
    elif phase == "record":
        monkeypatch.setattr(observation, "_identity_wire", expire_after(observation._identity_wire))
    elif phase == "serialization":
        monkeypatch.setattr(observation, "_canonical", expire_after(observation._canonical))
    elif phase == "digest":
        original_hash = hashlib.sha256

        def hash_then_expire(data=b"", **kwargs):
            result = original_hash(data, **kwargs)
            if observation.TOOLCHAIN_OBSERVATION_SCHEMA.encode() in data:
                state.now = 100.0
            return result

        monkeypatch.setattr(observation.hashlib, "sha256", hash_then_expire)
    elif phase == "return":
        monkeypatch.setattr(observation, "StaticPythonToolchainObservation",
                            expire_after(observation.StaticPythonToolchainObservation))
    _refuses(snapshot, "wall_timeout", monotonic=lambda: state.now)


def test_observation_never_reopens_paths_or_invokes_process_or_network(snapshot, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("archive observation must remain inert")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(archive.os, "open", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert _observe(snapshot).manifest_sha256 == MANIFEST_SHA256


def test_dedicated_record_budget_cannot_emit_an_oversized_receipt(snapshot, monkeypatch):
    monkeypatch.setattr(observation, "MAX_TOOLCHAIN_OBSERVATION_BYTES", 1)
    _refuses(snapshot, "record_budget_exceeded")
