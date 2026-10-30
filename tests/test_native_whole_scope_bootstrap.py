"""Finite bootstrap ABI and original grants, without a privileged installation."""
from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from lunar_evolution import native_bootstrap as bootstrap
from lunar_evolution.native_trusted_attempt import _original_attempt_grants
from lunar_evolution.producer_grant_anchors import ProducerGrantIdentity, ProducerGrantRequest


def _command_options():
    return {"control_fd": 10, "gate_fd": 11, "frame_fd": 12, "controller_lifeline_fd": 13,
            "scope_enrollment_fd": 14, "scope_lifecycle_fd": 15, "profile_fd": 16,
            "deadline_monotonic_ns": 123456789}


def test_explicit_whole_scope_abi_preserves_exact_flags_and_values():
    command = bootstrap.native_whole_scope_bootstrap_command("/installed/bootstrap", **_command_options())
    assert command == (
        "/installed/bootstrap", "--whole-scope-v1",
        "--control-fd", "10", "--gate-fd", "11", "--frame-fd", "12",
        "--controller-lifeline-fd", "13", "--scope-enrollment-fd", "14",
        "--scope-lifecycle-fd", "15", "--profile-fd", "16",
        "--deadline-monotonic-ns", "123456789",
    )
    assert len(command) == 18
    assert bootstrap.native_bootstrap_command("/installed/bootstrap", control_fd=10, gate_fd=11,
                                              frame_fd=12) == (
        "/installed/bootstrap", "--control-fd", "10", "--gate-fd", "11", "--frame-fd", "12",
    )


@pytest.mark.parametrize("key,value", [
    ("control_fd", True), ("profile_fd", 2), ("scope_lifecycle_fd", 2**31),
    ("scope_enrollment_fd", 13), ("deadline_monotonic_ns", False),
    ("deadline_monotonic_ns", 0), ("deadline_monotonic_ns", 2**64),
])
def test_invalid_whole_scope_arguments_never_produce_a_legacy_command(key, value):
    options = {**_command_options(), key: value}
    with pytest.raises(bootstrap.NativeBootstrapError, match="whole_scope_command_invalid"):
        bootstrap.native_whole_scope_bootstrap_command("/installed/bootstrap", **options)


@pytest.mark.parametrize("changed", range(8))
def test_source_manifest_binds_every_bootstrap_and_transitive_header(tmp_path, monkeypatch, changed):
    original_paths = bootstrap.native_bootstrap_source_paths()
    assert {path.name for path in original_paths} == {
        "native_bootstrap.c", "native_producer_isolation.h", "native_whole_scope_bootstrap.h",
        "native_whole_scope_platform.h", "native_whole_scope_protocol.h",
        "native_whole_scope_successor_protocol.h", "native_whole_scope_successor_bootstrap.h",
        "native_whole_scope_successor_resources.h",
    }
    paths = tuple(tmp_path / path.name for path in original_paths)
    for path in paths:
        path.write_bytes(path.name.encode())
    monkeypatch.setattr(bootstrap, "native_bootstrap_source_paths", lambda: paths)
    expected = hashlib.sha256()
    for path in paths:
        raw = path.read_bytes()
        expected.update(len(path.name).to_bytes(4, "big"))
        expected.update(path.name.encode("ascii"))
        expected.update(len(raw).to_bytes(8, "big"))
        expected.update(raw)
    first = bootstrap._source_pin()
    assert first == expected.hexdigest()
    paths[changed].write_bytes(b"changed source")
    assert bootstrap._source_pin() != first


def test_missing_transitive_header_refuses_before_output_or_compiler(tmp_path, monkeypatch):
    missing = tmp_path / "native_whole_scope_protocol.h"
    monkeypatch.setattr(bootstrap, "native_bootstrap_source_paths", lambda: (missing,))
    output = tmp_path / "output"
    with pytest.raises(bootstrap.NativeBootstrapError, match="source_missing"):
        bootstrap.build_native_bootstrap_artifact(output)
    assert not output.exists()


def test_profile_readonly_grants_join_existing_original_work_and_output(tmp_path):
    batch, runtime = tmp_path / "batch", tmp_path / "runtime"
    batch.mkdir()
    runtime.mkdir()
    working, output = batch / "work", batch / "output"
    working.mkdir()
    output.mkdir()
    info = runtime.stat()
    request = ProducerGrantRequest(str(runtime), "readonly-directory",
                                   ProducerGrantIdentity(info.st_dev, info.st_ino, "directory"))
    scope = SimpleNamespace(original_readonly_grant_requests=lambda: (request,))
    with _original_attempt_grants(None, batch=batch, working=working, output=output,
                                  enabled=True, whole_scope=scope) as owner:
        owner.validate()
        records = {record.path: record for record in owner.manifest.records}
        assert records[str(runtime)].roles == ("readonly-directory",)
        assert records[str(working)].roles == ("cwd", "writable-directory")
        assert records[str(output)].roles == ("writable-directory",)


def test_whole_scope_never_creates_missing_candidate_directories(tmp_path):
    scope = SimpleNamespace(original_readonly_grant_requests=tuple)
    batch = tmp_path / "batch"
    batch.mkdir()
    with pytest.raises(ValueError), _original_attempt_grants(
        None, batch=batch, working=batch / "work", output=batch / "output", enabled=True, whole_scope=scope,
    ):
        pytest.fail("missing original directories must not be created by the grant holder")
    assert not (batch / "work").exists()
    assert not (batch / "output").exists()
