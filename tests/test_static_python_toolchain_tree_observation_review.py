"""Independent race and partial-acquisition counterexamples; fixture tools stay inert."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import traceback
from types import SimpleNamespace

import pytest

from tools.static_python_fixture import toolchain_tree_observation as tree_observation

ROOT = "zig-x86_64-linux-0.16.0"
# Assembled from the explicit fixture member table, without observing a tree.
MANIFEST_SHA256 = "4bf46485ec2e9ee1f66db638c4a141ba8aa296257bd6ff3fec835cd4dbce1422"
PRIVATE_DETAIL = "PRIVATE_REVIEW_CONTENT /private/review-input-path"


@pytest.fixture
def tree_fixture(tmp_path):
    root = tmp_path / "ancestor" / ROOT
    (root / "lib").mkdir(parents=True)
    payloads = {"lib/a.h": b"first!\n", "lib/z.h": b"second\n", "zig": b"inert fixture only\n"}
    members = []
    for name in ("", "lib"):
        path = root / name
        path.chmod(0o755)
        members.append({
            "path": ROOT + ("/" + name if name else ""), "kind": "directory",
            "size": 0, "mode": 0o755, "sha256": None,
        })
    for name, raw in payloads.items():
        path = root / name
        path.write_bytes(raw)
        mode = 0o755 if name == "zig" else 0o644
        path.chmod(mode)
        members.append({
            "path": ROOT + "/" + name, "kind": "file", "size": len(raw), "mode": mode,
            "sha256": hashlib.sha256(raw).hexdigest(),
        })
    manifest = json.dumps({
        "schema": "lunar-static-python-extraction-manifest-v1", "archive": "zig", "root": ROOT,
        "archive_sha256": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
        "members": members,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    assert hashlib.sha256(manifest).hexdigest() == MANIFEST_SHA256
    return SimpleNamespace(root=root, manifest=manifest)


def _observe(fixture, **kwargs):
    return tree_observation.observe_extracted_toolchain_tree(
        fixture.manifest, expected_manifest_sha256=MANIFEST_SHA256,
        tree_directory=str(fixture.root), deadline=100.0,
        monotonic=kwargs.pop("monotonic", lambda: 1.0), **kwargs,
    )


def _descriptor_audit(monkeypatch, *, close_error=False):
    original_open, original_dup, original_close = os.open, os.dup, os.close
    state = SimpleNamespace(active=set(), acquired=[], cleanup_error=False)

    def opened(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        state.active.add(fd)
        state.acquired.append((path, fd))
        return fd

    def duplicated(fd):
        duplicate = original_dup(fd)
        state.active.add(duplicate)
        state.acquired.append(("<dup>", duplicate))
        return duplicate

    def closed(fd):
        original_close(fd)
        state.active.discard(fd)
        if close_error and not state.cleanup_error:
            state.cleanup_error = True
            raise OSError(errno.EIO, "cleanup " + PRIVATE_DETAIL)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "dup", duplicated)
    monkeypatch.setattr(os, "close", closed)
    return state


@pytest.mark.parametrize("layer", ["root", "ancestor"])
def test_replaced_path_edge_refuses_even_when_replacement_bytes_match(
    tree_fixture, tmp_path, monkeypatch, layer,
):
    target = tree_fixture.root if layer == "root" else tree_fixture.root.parent
    replacement = tmp_path / "replacement"
    shutil.copytree(target, replacement)
    original_read = os.read
    replaced = False

    def read(fd, size):
        nonlocal replaced
        raw = original_read(fd, size)
        if raw and not replaced:
            replaced = True
            target.rename(tmp_path / "held-original")
            replacement.rename(target)
        return raw

    monkeypatch.setattr(os, "read", read)
    descriptors = _descriptor_audit(monkeypatch)
    with pytest.raises(tree_observation.StaticPythonToolchainTreeObservationError):
        _observe(tree_fixture)
    assert replaced and not descriptors.active


def test_earlier_hashed_file_change_is_found_after_a_later_file_read_even_with_restored_mtime(
    tree_fixture, monkeypatch,
):
    earlier = tree_fixture.root / "lib/a.h"
    earlier_stat = earlier.stat()
    later_stat = (tree_fixture.root / "lib/z.h").stat()
    original_read, original_fstat = os.read, os.fstat
    mutated = False

    def read(fd, size):
        nonlocal mutated
        raw = original_read(fd, size)
        info = original_fstat(fd)
        if raw and not mutated and (info.st_dev, info.st_ino) == (
            later_stat.st_dev, later_stat.st_ino,
        ):
            mutated = True
            earlier.write_bytes(b"forged\n")
            os.utime(earlier, ns=(earlier_stat.st_atime_ns, earlier_stat.st_mtime_ns))
        return raw

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(tree_observation.StaticPythonToolchainTreeObservationError):
        _observe(tree_fixture)
    assert mutated and earlier.stat().st_mtime_ns == earlier_stat.st_mtime_ns


@pytest.mark.parametrize("operation", ["fstat", "named_stat"])
@pytest.mark.parametrize("component", ["ancestor", ROOT, "lib", "a.h"])
def test_every_partial_open_boundary_owns_its_fd_before_stat_failure(
    tree_fixture, monkeypatch, operation, component,
):
    descriptors = _descriptor_audit(monkeypatch)
    original_open, original_fstat, original_stat = os.open, os.fstat, os.stat
    state = SimpleNamespace(pending=None, failed=False)

    def open_then_arm(path, *args, **kwargs):
        fd = original_open(path, *args, **kwargs)
        if path == component and not state.failed:
            state.pending = fd
        return fd

    def fstat(fd):
        if operation == "fstat" and fd == state.pending and not state.failed:
            state.failed = True
            raise OSError(errno.EIO, PRIVATE_DETAIL)
        return original_fstat(fd)

    def named_stat(path, *args, **kwargs):
        if operation == "named_stat" and path == component and state.pending is not None and not state.failed:
            state.failed = True
            raise OSError(errno.EIO, PRIVATE_DETAIL)
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", open_then_arm)
    monkeypatch.setattr(os, "fstat", fstat)
    monkeypatch.setattr(os, "stat", named_stat)
    with pytest.raises(tree_observation.StaticPythonToolchainTreeObservationError) as caught:
        _observe(tree_fixture)
    assert state.failed and descriptors.acquired and not descriptors.active
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(caught.value))


def test_cleanup_failure_preserves_primary_partial_acquisition_error(tree_fixture, monkeypatch):
    descriptors = _descriptor_audit(monkeypatch, close_error=True)
    original_fstat = os.fstat

    def fail(fd):
        if descriptors.acquired[-1] == ("ancestor", fd):
            raise OSError(errno.EIO, PRIVATE_DETAIL)
        return original_fstat(fd)

    monkeypatch.setattr(os, "fstat", fail)
    with pytest.raises(tree_observation.StaticPythonToolchainTreeObservationError) as caught:
        _observe(tree_fixture)
    assert str(caught.value) == "static_python_toolchain_tree_observation_filesystem_observation_failed"
    assert descriptors.cleanup_error and not descriptors.active
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("phase", ["scan", "serialization"])
def test_clock_exception_traceback_is_redacted_after_filesystem_acquisition(
    tree_fixture, monkeypatch, phase,
):
    descriptors = _descriptor_audit(monkeypatch)
    state = SimpleNamespace(fail=False)

    def clock():
        if state.fail:
            raise RuntimeError(PRIVATE_DETAIL)
        return 1.0

    if phase == "scan":
        original = tree_observation.fd_observation._list_children

        def list_children(*args, **kwargs):
            state.fail = True
            return original(*args, **kwargs)

        monkeypatch.setattr(tree_observation.fd_observation, "_list_children", list_children)
    else:
        original = tree_observation._canonical

        def canonical(*args, **kwargs):
            raw = original(*args, **kwargs)
            state.fail = True
            return raw

        monkeypatch.setattr(tree_observation, "_canonical", canonical)
    with pytest.raises(tree_observation.StaticPythonToolchainTreeObservationError) as caught:
        _observe(tree_fixture, monotonic=clock)
    assert str(caught.value) == "static_python_toolchain_tree_observation_clock_invalid"
    assert descriptors.acquired and not descriptors.active
    assert PRIVATE_DETAIL not in "".join(traceback.format_exception(caught.value))
