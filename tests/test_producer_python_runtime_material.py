"""Inert sealed data, owned FDs and one static reader; never a Python target.

Darwin skips are not Linux sealing evidence. The deliberately delivered reader
FD belongs to this fixture parent and does not extend native control v2.
"""

from __future__ import annotations

import errno
import hashlib
import json
import mmap
import os
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_producer_python_runtime import _inventory, _path
from test_producer_python_runtime_tree import fixture
from test_producer_python_runtime_tree import verify as verify_source_tree

from lunar_evolution import producer_python_runtime_material as material
from lunar_evolution import producer_python_runtime_tree as source_tree

_LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux memfd seals")
_VERSION = "inert-material-v1"
_FALSE_CAPABILITIES = (
    "execution_performed", "runtime_load_protection", "production_admission",
    "archive_contents_complete", "loader_dependencies_complete",
)
_SEALS = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


def create(tree, **changes):
    return material.materialize_sealed_python_runtime_material(tree.closed, **{
        "expected_tree_sha256": tree.closed.tree_sha256,
        "expected_manifest_sha256": tree.original.manifest_sha256,
        "expected_target": tree.target,
        "material_version": _VERSION,
        "deadline": time.monotonic() + 30,
        **changes,
    })


def verify(live, tree, **changes):
    return material.verify_sealed_python_runtime_material(live, **{
        "expected_frame_sha256": live.descriptor.frame_sha256,
        "expected_tree_sha256": tree.closed.tree_sha256,
        "expected_manifest_sha256": tree.original.manifest_sha256,
        "expected_target": tree.target,
        "expected_material_version": _VERSION,
        **changes,
    })


def refused(call, suffix=None):
    with pytest.raises(material.PythonRuntimeMaterialError) as caught:
        call()
    assert caught.value.code.startswith("python_runtime_material_")
    if suffix is not None:
        assert caught.value.code == "python_runtime_material_" + suffix
    return caught.value


def enter_only(tree, **changes):
    with create(tree, **changes):
        pytest.fail("refused materialization yielded a live handle")


def raw_frame(live):
    size = os.fstat(live.fd).st_size
    data = bytearray()
    while len(data) < size:
        chunk = os.pread(live.fd, min(65536, size - len(data)), len(data))
        assert chunk
        data.extend(chunk)
    return bytes(data)


def track_acquisitions(monkeypatch):
    """Track all process-local acquisition routes without consulting owners."""
    descriptors, anchors = set(), []
    original_open = os.open
    original_memfd = os.memfd_create
    original_fcntl = material.fcntl.fcntl

    def tracked_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        descriptors.add(fd)
        return fd

    def tracked_memfd(*args, **kwargs):
        fd = original_memfd(*args, **kwargs)
        descriptors.add(fd)
        anchors.append(fd)
        return fd

    def tracked_fcntl(fd, command, *args):
        result = original_fcntl(fd, command, *args)
        if command == material.fcntl.F_DUPFD_CLOEXEC:
            descriptors.add(result)
        return result

    monkeypatch.setattr(material.os, "open", tracked_open)
    monkeypatch.setattr(material.os, "memfd_create", tracked_memfd)
    monkeypatch.setattr(material.fcntl, "fcntl", tracked_fcntl)
    return SimpleNamespace(descriptors=descriptors, anchors=anchors)


def assert_closed(descriptors):
    for fd in descriptors:
        with pytest.raises(OSError) as caught:
            os.fstat(fd)
        assert caught.value.errno == errno.EBADF


@pytest.mark.parametrize("support", ["host", "memfd", "fcntl", "pread"])
def test_unsupported_host_or_api_refuses_before_source_open(tmp_path, monkeypatch, support):
    tree = fixture(tmp_path)

    def forbidden(*_args, **_kwargs):
        pytest.fail("unsupported mechanism must refuse before source observation/acquisition")

    monkeypatch.setattr(material.os, "open", forbidden)
    monkeypatch.setattr(material.os, "memfd_create", forbidden, raising=False)
    if support == "host":
        monkeypatch.setattr(material.sys, "platform", "darwin")
    else:
        monkeypatch.setattr(material.sys, "platform", "linux")
        if support == "memfd":
            monkeypatch.setattr(material.os, "memfd_create", None)
        elif support == "fcntl":
            monkeypatch.setattr(material, "fcntl", None)
        else:
            monkeypatch.setattr(material.os, "pread", None)
    refused(lambda: enter_only(tree), "unsupported")


@pytest.mark.parametrize("change", ["tree", "manifest", "target", "version", "deadline"])
def test_invalid_external_contract_refuses_before_acquisition(tmp_path, monkeypatch, change):
    tree = fixture(tmp_path)
    changes = {
        "tree": {"expected_tree_sha256": "0" * 64},
        "manifest": {"expected_manifest_sha256": "0" * 64},
        "target": {"expected_target": replace(tree.target, python_version="3.12", abi_tag="cp312")},
        "version": {"material_version": "invalid/version"},
        "deadline": {"deadline": True},
    }[change]

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid caller pins must refuse before effects")

    monkeypatch.setattr(material.os, "open", forbidden)
    monkeypatch.setattr(material.os, "memfd_create", forbidden, raising=False)
    refused(lambda: enter_only(tree, **changes))


@_LINUX
@pytest.mark.parametrize("layout", ["portable-tree", "venv-tree"])
def test_original_payload_graph_and_all_seals_survive_context(tmp_path, monkeypatch, layout):
    tree = fixture(tmp_path, layout=layout)
    before = _inventory(tree.base)
    tracked = track_acquisitions(monkeypatch)
    with create(tree) as live:
        assert len(tracked.anchors) == 1
        assert live.fd != tracked.anchors[0]
        assert os.fstat(live.fd).st_ino == os.fstat(tracked.anchors[0]).st_ino
        assert not os.get_inheritable(live.fd)
        assert not os.get_inheritable(tracked.anchors[0])
        required = sum(getattr(material.fcntl, name) for name in _SEALS)
        assert material.fcntl.fcntl(live.fd, material.fcntl.F_GET_SEALS) & required == required
        raw = raw_frame(live)
        magic, table_size, payload_size = struct.unpack(">16sQQ", raw[:32])
        assert magic == b"LUNARPYMAT" + b"\0" * 5 + b"\1"
        assert len(raw) == 32 + table_size + payload_size
        table_raw, payload = raw[32:32 + table_size], raw[32 + table_size:]
        table = json.loads(table_raw)
        assert table["roots"] == sorted(tree.roots)
        assert table["directories"] == [
            {"root_label": item.root_label, "relative_path": item.relative_path,
             "children": list(item.children)} for item in tree.closed.directories
        ]
        assert any(item["children"] == [] for item in table["directories"])
        expected_payload = b"".join(
            (tree.roots[item.root_label] / item.relative_path).read_bytes()
            for item in tree.original.files
        )
        assert payload == expected_payload
        assert len(table["files"]) == len(tree.original.files)
        assert {item["role"] for item in table["files"]} == {
            item.role for item in tree.original.files
        }
        observation = verify(live, tree, expected_frame_sha256=hashlib.sha256(raw).hexdigest())
        assert observation == live.descriptor
        assert observation.frame_size == len(raw)
        assert observation.table_sha256 == hashlib.sha256(table_raw).hexdigest()
        assert observation.payload_sha256 == hashlib.sha256(payload).hexdigest()
        assert observation.frame_sha256 == hashlib.sha256(raw).hexdigest()
        wire = observation.to_dict()
        assert wire["scope"] == "sealed-runtime-material-only"
        assert wire["binding"] == "linux-sealed-material-memfd-v1"
        assert str(tree.base) not in observation.to_json().decode()
        assert "fd" not in wire and "material_bytes_immutable" not in wire
        for name in _FALSE_CAPABILITIES:
            assert wire[name] is False
    assert_closed(tracked.descriptors)
    assert _inventory(tree.base) == before
    refused(lambda: verify(live, tree), "ownership_invalid")


@_LINUX
@pytest.mark.parametrize("operation", ["write", "pwrite", "shrink", "grow", "shared-map"])
def test_kernel_seals_deny_mutation_of_actual_material(tmp_path, operation):
    tree = fixture(tmp_path)
    with create(tree) as live:
        original = raw_frame(live)
        with pytest.raises(OSError) as caught:
            if operation == "write":
                os.write(live.fd, b"mutation")
            elif operation == "pwrite":
                os.pwrite(live.fd, b"mutation", 0)
            elif operation == "shrink":
                os.ftruncate(live.fd, len(original) - 1)
            elif operation == "grow":
                os.ftruncate(live.fd, len(original) + 1)
            else:
                mmap.mmap(live.fd, 0, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ | mmap.PROT_WRITE)
        assert caught.value.errno in (errno.EPERM, errno.EACCES)
        assert raw_frame(live) == original
        assert verify(live, tree).frame_sha256 == hashlib.sha256(original).hexdigest()


@_LINUX
def test_private_mapping_changes_do_not_mutate_underlying_material(tmp_path):
    tree = fixture(tmp_path)
    with create(tree) as live:
        original = raw_frame(live)
        with mmap.mmap(live.fd, 0, flags=mmap.MAP_PRIVATE,
                       prot=mmap.PROT_READ | mmap.PROT_WRITE) as private:
            private[:4] = b"EDIT"
            assert private[:4] == b"EDIT"
        assert raw_frame(live) == original
        verify(live, tree, expected_frame_sha256=hashlib.sha256(original).hexdigest())


@_LINUX
@pytest.mark.parametrize("missing", [*_SEALS, "future-write-only"])
def test_incomplete_kernel_sealing_never_yields_material(tmp_path, monkeypatch, missing):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    actual = material.fcntl.fcntl

    def partial(fd, command, *args):
        if command == material.fcntl.F_ADD_SEALS:
            seals = 0x10 if missing == "future-write-only" else args[0] & ~getattr(material.fcntl, missing)
            return actual(fd, command, seals)
        return actual(fd, command, *args)

    monkeypatch.setattr(material.fcntl, "fcntl", partial)
    refused(lambda: enter_only(tree))
    assert len(tracked.anchors) == 1
    assert_closed(tracked.descriptors)


@_LINUX
@pytest.mark.parametrize("missing", _SEALS)
def test_live_verifier_independently_requires_every_seal(tmp_path, monkeypatch, missing):
    tree = fixture(tmp_path)
    with create(tree) as live:
        actual = material.fcntl.fcntl

        def incomplete(fd, command, *args):
            result = actual(fd, command, *args)
            return result & ~getattr(material.fcntl, missing) if command == material.fcntl.F_GET_SEALS else result

        monkeypatch.setattr(material.fcntl, "fcntl", incomplete)
        refused(lambda: verify(live, tree), "seals_invalid")


@_LINUX
def test_shared_writable_mapping_blocks_write_seal_and_cleans_owned_fds(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    actual, mappings = material.fcntl.fcntl, []

    def mapped(fd, command, *args):
        if command == material.fcntl.F_ADD_SEALS:
            mappings.append(mmap.mmap(fd, 0, flags=mmap.MAP_SHARED,
                                      prot=mmap.PROT_READ | mmap.PROT_WRITE))
        return actual(fd, command, *args)

    monkeypatch.setattr(material.fcntl, "fcntl", mapped)
    try:
        refused(lambda: enter_only(tree))
        assert len(mappings) == 1
        assert_closed(tracked.descriptors)
    finally:
        for item in mappings:
            item.close()


@_LINUX
@pytest.mark.parametrize("drift", ["bytes", "replacement", "removed-tree"])
def test_live_material_is_independent_of_source_drift_after_sealing(tmp_path, drift):
    tree = fixture(tmp_path)
    source = _path(tree, "project_source")
    with create(tree) as live:
        original = raw_frame(live)
        if drift == "bytes":
            source.write_bytes(b"changed inert source")
        elif drift == "replacement":
            replacement = source.with_name("replacement")
            replacement.write_bytes(source.read_bytes())
            replacement.replace(source)
        else:
            shutil.rmtree(tree.base)
        with pytest.raises(source_tree.PythonRuntimeTreeError) as caught:
            verify_source_tree(tree)
        assert str(caught.value).startswith("python_runtime_tree_")
        observation = verify(live, tree, expected_frame_sha256=hashlib.sha256(original).hexdigest())
        assert observation.frame_sha256 == hashlib.sha256(original).hexdigest()
        assert raw_frame(live) == original


@_LINUX
def test_position_independent_reads_preserve_shared_borrower_offset(tmp_path):
    tree = fixture(tmp_path)
    with create(tree) as live:
        reader = os.dup(live.fd)
        try:
            os.lseek(reader, 23, os.SEEK_SET)
            original = raw_frame(live)
            verify(live, tree, expected_frame_sha256=hashlib.sha256(original).hexdigest())
            assert os.lseek(live.fd, 0, os.SEEK_CUR) == 23
            assert os.lseek(reader, 0, os.SEEK_CUR) == 23
        finally:
            os.close(reader)


@_LINUX
def test_live_verification_handles_short_position_independent_reads(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    with create(tree) as live:
        expected = live.descriptor.frame_sha256
        actual = material.os.pread
        reads = []

        def short(fd, size, offset):
            reads.append((size, offset))
            return actual(fd, min(size, 7), offset)

        monkeypatch.setattr(material.os, "pread", short)
        os.lseek(live.fd, 19, os.SEEK_SET)
        assert verify(live, tree, expected_frame_sha256=expected).frame_sha256 == expected
        assert len(reads) > 10
        assert os.lseek(live.fd, 0, os.SEEK_CUR) == 19


@_LINUX
@pytest.mark.parametrize("stage", ["before", "after-first-source-check"])
@pytest.mark.parametrize("drift", ["bytes", "same-byte-replacement"])
def test_original_source_drift_refuses_and_releases_partial_material(tmp_path, monkeypatch, stage, drift):
    tree = fixture(tmp_path)
    source = _path(tree, "project_source")
    tracked = track_acquisitions(monkeypatch)

    def mutate():
        if drift == "bytes":
            source.write_bytes(b"different inert source bytes")
        else:
            replacement = source.with_name("same-bytes-new-inode")
            replacement.write_bytes(source.read_bytes())
            replacement.replace(source)

    if stage == "before":
        mutate()
    else:
        actual = material.copy_payload

        def drift_before_copy(*args, **kwargs):
            mutate()
            return actual(*args, **kwargs)

        monkeypatch.setattr(material, "copy_payload", drift_before_copy)
    refused(lambda: enter_only(tree))
    assert len(tracked.anchors) == 1
    assert_closed(tracked.descriptors)


@_LINUX
@pytest.mark.parametrize("forgery", ["detached", "clone", "integer", "reader-duplicate"])
def test_detached_or_borrowed_evidence_cannot_create_live_authority(tmp_path, forgery):
    tree = fixture(tmp_path)
    with create(tree) as live:
        detached = material.parse_python_runtime_material_descriptor(live.descriptor.to_json())
        duplicate = -1
        try:
            if forgery == "detached":
                subject = detached
            elif forgery == "integer":
                subject = live.fd
            elif forgery == "clone":
                subject = material.SealedPythonRuntimeMaterial(live.fd, detached)
            else:
                duplicate = os.dup(live.fd)
                subject = material.SealedPythonRuntimeMaterial(duplicate, detached)
            refused(lambda: material.verify_sealed_python_runtime_material(
                subject, expected_frame_sha256=live.descriptor.frame_sha256,
                expected_tree_sha256=tree.closed.tree_sha256,
                expected_manifest_sha256=tree.original.manifest_sha256,
                expected_target=tree.target, expected_material_version=_VERSION,
            ), "ownership_invalid")
            verify(live, tree)
        finally:
            if duplicate >= 0:
                os.close(duplicate)


@_LINUX
@pytest.mark.parametrize("pin", ["frame", "tree", "manifest", "target", "version"])
def test_live_verifier_requires_independent_external_pins(tmp_path, pin):
    tree = fixture(tmp_path)
    with create(tree) as live:
        changes = {
            "frame": {"expected_frame_sha256": "0" * 64},
            "tree": {"expected_tree_sha256": "0" * 64},
            "manifest": {"expected_manifest_sha256": "0" * 64},
            "target": {"expected_target": replace(tree.target, python_version="3.12", abi_tag="cp312")},
            "version": {"expected_material_version": "foreign-material-v2"},
        }[pin]
        refused(lambda: verify(live, tree, **changes))
        verify(live, tree)


@_LINUX
@pytest.mark.parametrize("field", ["fd", "descriptor"])
def test_forced_public_handle_mutation_cannot_redirect_cleanup(tmp_path, monkeypatch, field):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    foreign = os.open(tmp_path / "foreign", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
    tracked.descriptors.discard(foreign)
    try:
        with create(tree) as live:
            frame_sha = live.descriptor.frame_sha256
            if field == "fd":
                object.__setattr__(live, "fd", foreign)
            else:
                object.__setattr__(live.descriptor, "frame_sha256", "0" * 64)
            refused(lambda: verify(live, tree, expected_frame_sha256=frame_sha))
        os.fstat(foreign)
        assert_closed(tracked.descriptors)
    finally:
        os.close(foreign)


@_LINUX
@pytest.mark.parametrize("replacement", ["ordinary", "same-bytes-sealed"])
def test_foreign_reuse_of_borrowed_number_is_refused_and_never_closed(tmp_path, monkeypatch, replacement):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    foreign = borrowed = -1
    try:
        with pytest.raises(material.PythonRuntimeMaterialError) as caught, create(tree) as live:
            borrowed = live.fd
            original = raw_frame(live)
            if replacement == "ordinary":
                foreign = os.open(tmp_path / "foreign", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
                os.write(foreign, original)
            else:
                foreign = os.memfd_create("inert-foreign", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
                os.write(foreign, original)
                required = sum(getattr(material.fcntl, name) for name in _SEALS)
                material.fcntl.fcntl(foreign, material.fcntl.F_ADD_SEALS, required)
            tracked.descriptors.discard(foreign)
            os.dup2(foreign, borrowed, inheritable=False)
            refused(lambda: verify(live, tree), "ownership_invalid")
        assert caught.value.code == "python_runtime_material_cleanup_unknown"
        assert os.fstat(borrowed).st_ino == os.fstat(foreign).st_ino
        assert os.pread(borrowed, len(original), 0) == original
        assert_closed(tracked.descriptors - {borrowed})
    finally:
        for fd in (borrowed, foreign):
            if fd >= 0:
                os.close(fd)


@_LINUX
def test_borrowed_close_is_cleanup_unknown_while_private_anchor_is_released(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    with pytest.raises(material.PythonRuntimeMaterialError) as caught, create(tree) as live:
        os.close(live.fd)
        refused(lambda: verify(live, tree))
    assert caught.value.code == "python_runtime_material_cleanup_unknown"
    assert_closed(tracked.descriptors)


@_LINUX
def test_borrowed_cloexec_mutation_refuses_without_widening_cleanup_authority(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    with create(tree) as live:
        os.set_inheritable(live.fd, True)
        refused(lambda: verify(live, tree), "ownership_invalid")
    assert_closed(tracked.descriptors)


@_LINUX
@pytest.mark.parametrize("stage", ["memfd", "first-fstat", "get-seals", "get-flags", "write", "read", "add-seals", "duplicate"])
@pytest.mark.parametrize("fault", [OSError, KeyboardInterrupt, SystemExit])
def test_refusal_and_interrupt_at_every_material_boundary_release_owned_fds(tmp_path, monkeypatch, stage, fault):
    tree = fixture(tmp_path)
    before = _inventory(tree.base)
    tracked = track_acquisitions(monkeypatch)
    injected = fault("inert-fault")
    triggered = False

    def fail_once(*_args, **_kwargs):
        nonlocal triggered
        triggered = True
        raise injected

    if stage == "memfd":
        monkeypatch.setattr(material.os, "memfd_create", fail_once)
    elif stage == "write":
        monkeypatch.setattr(material.os, "write", fail_once)
    elif stage == "read":
        monkeypatch.setattr(material.os, "pread", fail_once)
    elif stage == "first-fstat":
        actual = material.os.fstat

        def fail_first(fd):
            if not triggered:
                return fail_once()
            return actual(fd)

        monkeypatch.setattr(material.os, "fstat", fail_first)
    else:
        command = {"get-seals": material.fcntl.F_GET_SEALS,
                   "get-flags": material.fcntl.F_GETFD,
                   "add-seals": material.fcntl.F_ADD_SEALS,
                   "duplicate": material.fcntl.F_DUPFD_CLOEXEC}[stage]
        actual = material.fcntl.fcntl

        def fail_command(fd, operation, *args):
            if operation == command:
                return fail_once()
            return actual(fd, operation, *args)

        monkeypatch.setattr(material.fcntl, "fcntl", fail_command)
    expected = material.PythonRuntimeMaterialError if fault is OSError else fault
    with pytest.raises(expected) as caught, create(tree):
        pytest.fail("faulted materialization yielded a live handle")
    assert triggered
    if fault is OSError:
        assert caught.value.__cause__ is injected
    else:
        assert caught.value is injected
    assert_closed(tracked.descriptors)
    assert _inventory(tree.base) == before


@_LINUX
def test_memfd_creation_failure_precedes_any_source_observation(tmp_path, monkeypatch):
    tree = fixture(tmp_path)

    def failed(*_args, **_kwargs):
        raise OSError(errno.EMFILE, "inert-memfd-refusal")

    monkeypatch.setattr(material.os, "memfd_create", failed)
    monkeypatch.setattr(material.os, "open", lambda *_a, **_kw: pytest.fail("source opened before memfd preflight"))
    refused(lambda: enter_only(tree), "materialization_failed")


@_LINUX
def test_get_seals_preflight_failure_precedes_any_source_observation(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    actual = material.fcntl.fcntl

    def refused_get(fd, command, *args):
        if command == material.fcntl.F_GET_SEALS:
            raise OSError(errno.EINVAL, "inert-seals-refusal")
        return actual(fd, command, *args)

    monkeypatch.setattr(material.fcntl, "fcntl", refused_get)
    monkeypatch.setattr(material.os, "open", lambda *_a, **_kw: pytest.fail("source opened before GET_SEALS preflight"))
    refused(lambda: enter_only(tree), "materialization_failed")
    assert len(tracked.anchors) == 1
    assert_closed(tracked.descriptors)


@_LINUX
@pytest.mark.parametrize("primary", [OSError, KeyboardInterrupt, SystemExit])
def test_primary_body_exception_survives_cleanup_uncertainty(tmp_path, monkeypatch, primary):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    original_close = os.close
    injected = primary("inert-primary")
    with pytest.raises(primary) as caught, create(tree) as live:
        borrowed = live.fd

        def close_then_report(fd):
            original_close(fd)
            if fd == borrowed:
                raise OSError(errno.EIO, "inert-cleanup-uncertainty")

        monkeypatch.setattr(material.os, "close", close_then_report)
        raise injected
    assert caught.value is injected
    assert "python_runtime_material_cleanup_unknown" in caught.value.__notes__
    assert_closed(tracked.descriptors)


@_LINUX
def test_cleanup_failure_without_primary_is_explicit_fixed_refusal(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    original_close = os.close
    with pytest.raises(material.PythonRuntimeMaterialError) as caught, create(tree) as live:
        borrowed = live.fd

        def close_then_report(fd):
            original_close(fd)
            if fd == borrowed:
                raise OSError(errno.EIO, "inert-cleanup-uncertainty")

        monkeypatch.setattr(material.os, "close", close_then_report)
    assert caught.value.code == "python_runtime_material_cleanup_unknown"
    assert_closed(tracked.descriptors)


@_LINUX
def test_original_absolute_deadline_is_never_renewed_by_live_verification(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    clock = [10.0]
    monkeypatch.setattr(material.time, "monotonic", lambda: clock[0])
    with create(tree, deadline=11.0) as live:
        verify(live, tree)
        clock[0] = 11.0
        refused(lambda: verify(live, tree), "deadline_exceeded")
    assert_closed(tracked.descriptors)


@_LINUX
def test_expired_original_deadline_refuses_before_memfd_or_source_acquisition(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    monkeypatch.setattr(material.time, "monotonic", lambda: 11.0)

    def forbidden(*_args, **_kwargs):
        pytest.fail("expired deadline permitted acquisition")

    monkeypatch.setattr(material.os, "memfd_create", forbidden)
    monkeypatch.setattr(material.os, "open", forbidden)
    refused(lambda: enter_only(tree, deadline=11.0), "deadline_exceeded")


@_LINUX
@pytest.mark.parametrize("stage", ["creation", "write", "sealing", "duplication"])
def test_deadline_overrun_after_acquisition_still_cleans_all_owned_fds(tmp_path, monkeypatch, stage):
    tree = fixture(tmp_path)
    tracked = track_acquisitions(monkeypatch)
    clock = [10.0]
    monkeypatch.setattr(material.time, "monotonic", lambda: clock[0])
    if stage in {"creation", "write"}:
        field = "memfd_create" if stage == "creation" else "write"
        actual = getattr(material.os, field)

        def expired_after(*args, **kwargs):
            result = actual(*args, **kwargs)
            clock[0] = 11.0
            return result

        monkeypatch.setattr(material.os, field, expired_after)
    else:
        command = material.fcntl.F_ADD_SEALS if stage == "sealing" else material.fcntl.F_DUPFD_CLOEXEC
        actual = material.fcntl.fcntl

        def expired_command(fd, operation, *args):
            result = actual(fd, operation, *args)
            if operation == command:
                clock[0] = 11.0
            return result

        monkeypatch.setattr(material.fcntl, "fcntl", expired_command)
    refused(lambda: enter_only(tree, deadline=11.0), "deadline_exceeded")
    assert len(tracked.anchors) == 1
    assert_closed(tracked.descriptors)


_READER_SOURCE = r'''
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static uint64_t big64(const unsigned char *p) {
    uint64_t result = 0;
    for (unsigned int i = 0; i < 8; ++i) result = (result << 8) | p[i];
    return result;
}
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    char *end = NULL; long value = strtol(argv[1], &end, 10);
    if (!end || *end || value < 3 || value > 1048576) return 3;
    int fd = (int)value;
    struct stat info;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_size < 32 || info.st_size > 32768) return 4;
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    int seals = fcntl(fd, F_GET_SEALS);
    if (seals < 0 || (seals & required) != required) return 5;
    unsigned char bytes[32768]; size_t total = 0;
    while (total < (size_t)info.st_size) {
        ssize_t count = pread(fd, bytes + total, (size_t)info.st_size - total, (off_t)total);
        if (count <= 0) return 6;
        total += (size_t)count;
    }
    const unsigned char magic[16] = {'L','U','N','A','R','P','Y','M','A','T',0,0,0,0,0,1};
    if (memcmp(bytes, magic, sizeof(magic))) return 7;
    uint64_t table = big64(bytes + 16), payload = big64(bytes + 24);
    if (table > 32736 || payload > 32736 || table + payload + 32 != total) return 8;
    DIR *directory = opendir("/proc/self/fd");
    if (!directory) return 9;
    int inspection = dirfd(directory), inherited = 0;
    struct dirent *entry;
    errno = 0;
    while ((entry = readdir(directory))) {
        char *tail = NULL; long number = strtol(entry->d_name, &tail, 10);
        if (!tail || *tail || number <= 2 || number == inspection) continue;
        if (number != fd) { closedir(directory); return 10; }
        ++inherited;
    }
    if (errno || closedir(directory) || inherited != 1) return 11;
    printf("{\"size\":%zu,\"seals\":%d,\"inherited_count\":%d,\"fd\":%d,\"bytes\":\"",
           total, seals, inherited, fd);
    for (size_t i = 0; i < total; ++i) printf("%02x", bytes[i]);
    if (close(fd)) return 12;
    puts("\"}");
    return 0;
}
'''


@_LINUX
def test_inert_static_reader_receives_one_parent_owned_duplicate_only(tmp_path, record_property):
    tree = fixture(tmp_path)
    source, executable = tmp_path / "inert-reader.c", tmp_path / "inert-reader"
    source.write_text(_READER_SOURCE)
    compile_native_target(source, executable)
    decoy = os.open(tmp_path / "not-delivered", os.O_RDONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        with create(tree) as live:
            original = raw_frame(live)
            reader = os.dup(live.fd)
            try:
                assert not os.get_inheritable(reader)
                os.lseek(reader, 17, os.SEEK_SET)
                result = subprocess.run(
                    [str(executable), str(reader)], pass_fds=(reader,), close_fds=True,
                    capture_output=True, check=True, timeout=10,
                    env={"PATH": os.defpath, "LANG": "C"},
                )
                assert not result.stderr
                observed = json.loads(result.stdout)
                delivered = bytes.fromhex(observed["bytes"])
                assert delivered == original
                assert observed["size"] == live.descriptor.frame_size
                assert observed["inherited_count"] == 1 and observed["fd"] == reader
                required = sum(getattr(material.fcntl, name) for name in _SEALS)
                assert observed["seals"] & required == required
                assert hashlib.sha256(delivered).hexdigest() == live.descriptor.frame_sha256
                assert os.lseek(live.fd, 0, os.SEEK_CUR) == 17
                verify(live, tree)
                record_property("inert_reader_frame_sha256", hashlib.sha256(delivered).hexdigest())
                record_property("inert_reader_frame_size", observed["size"])
                record_property("inert_reader_seals", observed["seals"])
                record_property("inert_reader_inherited_fd_count", observed["inherited_count"])
                record_property("runtime_load_protection", False)
                record_property("production_admission", False)
            finally:
                os.close(reader)
    finally:
        os.close(decoy)
