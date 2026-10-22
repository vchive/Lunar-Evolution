"""Bounded read-only observations of a separately pinned Zig extraction tree."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest

from tools.static_python_fixture import toolchain_tree_observation as observation
from tools.static_python_fixture import verified_inputs
from tools.static_python_fixture.toolchain_observation import TOOLCHAIN_OBSERVATION_SCHEMA

ROOT = "zig-x86_64-linux-0.16.0"
# Independently assembled from the fixed member table below, not an observer result.
MANIFEST_SHA256 = "f5e9ebb88c32805ab33223766fd07cad0475c14d6b6ca2c0207950e34e5a99e5"
FILE_BYTES = {
    "zig": (b"inert zig driver\n", 0o755),
    "lib/libc.a": (b"static-library-placeholder\n", 0o644),
    "lib/empty": (b"", 0o644),
}


def _manifest() -> tuple[bytes, str]:
    members = [
        {"path": ROOT, "kind": "directory", "size": 0, "mode": 0o755, "sha256": None},
        {"path": ROOT + "/lib", "kind": "directory", "size": 0, "mode": 0o755, "sha256": None},
    ]
    for path, (raw, mode) in FILE_BYTES.items():
        members.append({
            "path": ROOT + "/" + path, "kind": "file", "size": len(raw),
            "mode": mode, "sha256": hashlib.sha256(raw).hexdigest(),
        })
    members.sort(key=lambda item: item["path"])
    value = {
        "schema": verified_inputs.EXTRACTION_MANIFEST_SCHEMA,
        "archive": "zig", "root": ROOT,
        "archive_sha256": verified_inputs._ZIG.sha256,
        "members": members,
    }
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()


def _tree(parent: Path, *, name: str = "tree") -> Path:
    root = parent / name
    (root / "lib").mkdir(parents=True)
    os.chmod(root, 0o755)
    os.chmod(root / "lib", 0o755)
    for relative, (raw, mode) in FILE_BYTES.items():
        path = root / relative
        path.write_bytes(raw)
        os.chmod(path, mode)
    return root.resolve()


@pytest.fixture
def inputs(tmp_path: Path):
    raw, pin = _manifest()
    assert len(raw) == 842 and pin == MANIFEST_SHA256
    return raw, pin, _tree(tmp_path.resolve())


def _observe(inputs, **overrides):
    raw, pin, root = inputs
    kwargs = {
        "expected_manifest_sha256": pin,
        "tree_directory": str(root),
        "deadline": 100.0,
        "monotonic": lambda: 1.0,
    }
    kwargs.update(overrides)
    return observation.observe_extracted_toolchain_tree(raw, **kwargs)


def _refuses(inputs, reason: str, **overrides) -> None:
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError) as caught:
        _observe(inputs, **overrides)
    assert str(caught.value) == "static_python_toolchain_tree_observation_" + reason


def test_complete_tree_matches_pinned_manifest_and_returns_no_second_inventory(inputs):
    _raw, _pin, root = inputs
    (root.parent / "unrelated-sibling").mkdir()
    result = _observe(inputs)
    record = result.to_dict()
    assert record == {
        "schema": observation.TOOLCHAIN_TREE_OBSERVATION_SCHEMA,
        "status": "pinned-manifest-tree-observed",
        "archive": "zig", "root": ROOT,
        "archive_sha256": verified_inputs._ZIG.sha256,
        "manifest_sha256": result.manifest_sha256,
        "tree_identity": record["tree_identity"],
        "member_count": 5, "file_count": 3, "directory_count": 2,
        "total_file_bytes": sum(len(raw) for raw, _mode in FILE_BYTES.values()),
        "observation_scope": "sequential-held-directory-tree-comparison",
        "signature_verification": "not-performed",
        "claims": dict.fromkeys(observation._CLAIMS, False),
    }
    assert set(record["tree_identity"]) == {
        "device", "inode", "raw_mode", "nlink", "size", "mtime_ns", "ctime_ns",
    }
    assert record["tree_identity"]["raw_mode"] == stat.S_IFDIR | 0o755
    assert "tree_directory" not in record
    assert "members" not in record and "files" not in record
    assert result.manifest_sha256 == hashlib.sha256(result.manifest_json).hexdigest()
    assert result.observation_sha256 == hashlib.sha256(result.canonical_json).hexdigest()
    assert result.canonical_json == json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")
    assert result.manifest_json == inputs[0]


def test_wrong_archive_pin_and_malformed_manifest_refuse(inputs):
    raw, pin, root = inputs
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="manifest_pin_invalid"):
        observation.observe_extracted_toolchain_tree(
            raw, expected_manifest_sha256="0" * 64, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="manifest_canonical_invalid"):
        observation.observe_extracted_toolchain_tree(
            raw + b" ", expected_manifest_sha256=pin, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="manifest_duplicate_key"):
        observation.observe_extracted_toolchain_tree(
            b'{"archive":"zig","archive":"zig"}', expected_manifest_sha256=pin,
            tree_directory=str(root), deadline=100.0, monotonic=lambda: 1.0,
        )
    cpython = json.loads(raw)
    cpython["archive"] = "cpython"
    cpython["archive_sha256"] = verified_inputs._CPYTHON.sha256
    cpython["root"] = verified_inputs._CPYTHON.root
    for member in cpython["members"]:
        member["path"] = member["path"].replace(ROOT, cpython["root"], 1)
    foreign = json.dumps(cpython, sort_keys=True, separators=(",", ":")).encode()
    foreign_pin = hashlib.sha256(foreign).hexdigest()
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="archive_invalid"):
        observation.observe_extracted_toolchain_tree(
            foreign, expected_manifest_sha256=foreign_pin, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )


@pytest.mark.parametrize("pin", [None, True, 1, "", "0" * 64, "f" * 64, "A" * 64, "a" * 63])
def test_bad_external_pin_refuses_before_filesystem_access(inputs, monkeypatch, pin):
    def unexpected_open(*args, **kwargs):
        pytest.fail("invalid metadata must refuse before opening a filesystem path")

    monkeypatch.setattr(observation.os, "open", unexpected_open)
    _refuses(inputs, "manifest_pin_invalid", expected_manifest_sha256=pin)


def test_wrong_external_pin_and_manifest_byte_budget_refuse_before_filesystem_access(inputs, monkeypatch):
    def unexpected_open(*args, **kwargs):
        pytest.fail("invalid metadata must refuse before opening a filesystem path")

    monkeypatch.setattr(observation.os, "open", unexpected_open)
    _refuses(inputs, "manifest_manifest_digest_drift", expected_manifest_sha256="a" * 64)
    monkeypatch.setattr(verified_inputs, "MAX_EXTRACTION_MANIFEST_BYTES", len(inputs[0]) - 1)
    _refuses(inputs, "manifest_wire_invalid")


@pytest.mark.parametrize("raw", [None, "{}", bytearray(b"{}"), memoryview(b"{}"), b"", b"\xff", b"NaN"])
def test_manifest_input_requires_bounded_json_bytes(inputs, raw):
    _original, pin, root = inputs
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError):
        _observe((raw, pin, root))


@pytest.mark.parametrize("path", [None, True, Path("/example"), "relative", "/", "/a/../b", "/a//b", "/a\0b"])
def test_tree_path_requires_canonical_absolute_string(inputs, monkeypatch, path):
    def unexpected_open(*args, **kwargs):
        pytest.fail("invalid paths must refuse before opening a filesystem path")

    monkeypatch.setattr(observation.os, "open", unexpected_open)
    _refuses(inputs, "destination_invalid", tree_directory=path)


def test_manifest_requires_every_parent_directory_explicit(inputs):
    raw, _pin, root = inputs
    value = json.loads(raw)
    value["members"] = [item for item in value["members"] if item["path"] != ROOT + "/lib"]
    changed = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    pin = hashlib.sha256(changed).hexdigest()
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError,
                       match="manifest_parent_directory_missing"):
        observation.observe_extracted_toolchain_tree(
            changed, expected_manifest_sha256=pin, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )


@pytest.mark.parametrize("change,reason", [
    ("content", "file_content_drift"),
    ("size", "file_identity_mismatch"),
    ("file_mode", "file_identity_mismatch"),
    ("directory_mode", "directory_mode_mismatch"),
    ("root_mode", "directory_mode_mismatch"),
    ("extra_file", "root_inventory_mismatch"),
    ("missing_file", "root_inventory_mismatch"),
    ("extra_empty_directory", "directory_inventory_mismatch"),
])
def test_fresh_manifest_comparison_rejects_tree_drift(inputs, change, reason):
    _raw, _pin, root = inputs
    if change == "content":
        (root / "zig").write_bytes(b"other zig driver\n")
    elif change == "size":
        (root / "zig").write_bytes(b"short")
    elif change == "file_mode":
        os.chmod(root / "zig", 0o644)
    elif change == "directory_mode":
        os.chmod(root / "lib", 0o700)
    elif change == "root_mode":
        os.chmod(root, 0o700)
    elif change == "extra_file":
        (root / "extra").write_bytes(b"unexpected")
    elif change == "missing_file":
        (root / "zig").unlink()
    elif change == "extra_empty_directory":
        (root / "lib" / "extra-empty").mkdir()
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError) as caught:
        _observe(inputs)
    assert str(caught.value) == "static_python_toolchain_tree_observation_" + reason


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_file_types_and_link_count_are_rejected(inputs, tmp_path, kind):
    _raw, _pin, root = inputs
    path = root / "zig"
    if kind == "symlink":
        path.unlink()
        path.symlink_to(root / "lib" / "libc.a")
    elif kind == "hardlink":
        os.link(path, tmp_path.resolve() / "external-hardlink")
    else:
        path.unlink()
        os.mkfifo(path)
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError):
        _observe(inputs)


def test_symlinked_tree_root_refuses(tmp_path, inputs):
    _raw, _pin, root = inputs
    alias = tmp_path.resolve() / "alias"
    alias.symlink_to(root, target_is_directory=True)
    _refuses(inputs, "filesystem_observation_failed", tree_directory=str(alias))


def test_invalid_parent_identity_and_root_replacement_refuse(inputs):
    raw, pin, root = inputs
    parent = root.parent
    moved = parent / "moved"
    root.rename(moved)
    root.symlink_to(moved, target_is_directory=True)
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError):
        observation.observe_extracted_toolchain_tree(
            raw, expected_manifest_sha256=pin, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )


@pytest.mark.parametrize("deadline", [True, 100, float("inf"), float("nan"), 0.0, -1.0])
def test_deadline_validation_and_expiry(inputs, deadline):
    _refuses(inputs, "deadline_invalid", deadline=deadline)
    _refuses(inputs, "wall_timeout", deadline=1.0, monotonic=lambda: 1.0)


def test_clock_exceptions_and_invalid_values_are_redacted(inputs):
    def fail():
        raise RuntimeError("/private/toolchain/path")

    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="clock_invalid") as caught:
        _observe(inputs, monotonic=fail)
    assert "/private" not in str(caught.value)
    for value in (True, None, "1", float("inf"), float("nan")):
        _refuses(inputs, "clock_invalid", monotonic=lambda value=value: value)


def test_deadline_expiry_during_inventory_closes_descriptors(inputs):
    raw, pin, root = inputs
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return 1.0 if calls < 8 else 100.0

    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="wall_timeout"):
        observation.observe_extracted_toolchain_tree(
            raw, expected_manifest_sha256=pin, tree_directory=str(root), deadline=100.0,
            monotonic=clock,
        )


@pytest.mark.parametrize("remaining", [0, 1, 2, 3])
def test_original_deadline_remains_enforced_through_serialization_and_final_return(inputs, remaining):
    calls = 0

    def baseline_clock():
        nonlocal calls
        calls += 1
        return 1.0

    _observe(inputs, monotonic=baseline_clock)
    total = calls
    calls = 0

    def clock():
        nonlocal calls
        calls += 1
        return 100.0 if calls >= total - remaining else 1.0

    _refuses(inputs, "wall_timeout", monotonic=clock)
    assert calls == total - remaining


def test_output_record_remains_bounded(inputs, monkeypatch):
    monkeypatch.setattr(observation, "MAX_TOOLCHAIN_TREE_OBSERVATION_BYTES", 1)
    _refuses(inputs, "record_budget_exceeded")


def test_opened_descriptor_closes_if_its_first_fstat_fails(inputs, monkeypatch):
    raw, pin, root = inputs
    real_open, real_fstat = os.open, os.fstat
    opened = []

    def tracked_open(path, flags, *args, **kwargs):
        fd = real_open(path, flags, *args, **kwargs)
        opened.append(fd)
        return fd

    def failing_fstat(fd):
        if fd in opened:
            raise OSError("injected root fstat failure")
        return real_fstat(fd)

    monkeypatch.setattr(observation.os, "open", tracked_open)
    monkeypatch.setattr(observation.os, "fstat", failing_fstat)
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError):
        observation.observe_extracted_toolchain_tree(
            raw, expected_manifest_sha256=pin, tree_directory=str(root), deadline=100.0,
            monotonic=lambda: 1.0,
        )
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            real_fstat(fd)


def test_late_content_change_during_hashing_is_rejected(inputs, monkeypatch):
    _raw, _pin, root = inputs
    real_read = os.read
    mutated = False

    def read_then_mutate(fd, size):
        nonlocal mutated
        block = real_read(fd, size)
        if block and not mutated:
            # The first payload read occurs only after acquisition/inventory.
            (root / "zig").write_bytes(b"other zig driver\n")
            mutated = True
        return block

    monkeypatch.setattr(observation.os, "read", read_then_mutate)
    with pytest.raises(observation.StaticPythonToolchainTreeObservationError, match="file_content_drift"):
        _observe(inputs)
    assert mutated


def test_observer_result_reuses_archive_wire_but_has_its_own_schema(inputs):
    result = _observe(inputs)
    assert result.to_dict()["schema"] == observation.TOOLCHAIN_TREE_OBSERVATION_SCHEMA
    assert result.to_dict()["schema"] != TOOLCHAIN_OBSERVATION_SCHEMA
    assert result.to_manifest()["schema"] == verified_inputs.EXTRACTION_MANIFEST_SCHEMA
    assert result.to_manifest()["archive"] == "zig"


def test_result_is_immutable_with_detached_record_and_manifest_projections(inputs):
    result = _observe(inputs)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.manifest_json = b"changed"
    result.to_dict()["claims"]["build_performed"] = True
    result.to_manifest()["members"].clear()
    assert result.to_dict()["claims"]["build_performed"] is False
    assert len(result.to_manifest()["members"]) == 5
    assert _observe(inputs).canonical_json == result.canonical_json


def test_observer_only_opens_read_only_and_does_not_write_extract_execute_or_connect(inputs, monkeypatch):
    original_open = os.open

    def read_only_open(path, flags, *args, **kwargs):
        assert flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND) == 0
        return original_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("a tree observer cannot write, extract, execute or connect")

    monkeypatch.setattr(observation.os, "open", read_only_open)
    for name in ("write", "mkdir", "rename", "replace", "unlink", "chmod", "system", "execve"):
        monkeypatch.setattr(observation.os, name, forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    assert _observe(inputs).to_dict()["status"] == "pinned-manifest-tree-observed"
