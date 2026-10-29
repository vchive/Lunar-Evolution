"""Retain original local buffers and verify them without consulting live state."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_static_python_podman_vfs_root import CID, IMAGE, vfs_vector
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.runtime_closure import canonical

MOUNTINFO = b"1 0 0:1 / / rw - tmpfs tmpfs rw\n"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path, raw):
    return {"path": path, "size": len(raw), "sha256": sha(raw)}


def original_controls(destination, raw_info, raw_inspect):
    operations = []
    for operation, raw in (("vfs-store-selection", raw_info), ("runtime-selection", raw_inspect)):
        logs = destination / "custody/compile-0" / operation
        logs.mkdir()
        (logs / "stdout.log").write_bytes(raw)
        operations.append({"operation": operation, "logs": {"stdout": {"size": len(raw), "sha256": sha(raw)}}})
    return operations


@pytest.fixture
def vector(tmp_path, monkeypatch):
    base, destination = tmp_path / "source", tmp_path / "attempt"
    base.mkdir()
    destination.mkdir()
    (destination / "custody").mkdir(mode=0o700)
    (destination / "custody/compile-0").mkdir()
    source = vfs_vector(base)
    ancillary = []
    for name, target, raw in (("resolver", "/etc/resolv.conf", b""),
                               ("passwd", "/etc/passwd", b"root:x:0:0:root:/tmp/home:/nonexistent\n"),
                               ("group", "/etc/group", b"root:x:0:\n"),
                               ("containerenv", "/run/.containerenv", b"engine=podman\n")):
        path = source.oci.parent / name
        path.write_bytes(raw)
        ancillary.append({"destination": target, "type": "bind", "source": str(path)})
    mounts = [{"destination": "/source", "type": "bind", "source": source.mounts["source"]["source"]},
              {"destination": "/tmp", "type": "tmpfs", "source": "tmpfs"}, *ancillary]
    source.oci.write_bytes(canonical({"root": {"path": str(source.root), "readonly": True}, "mounts": mounts}))
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=1024**2: MOUNTINFO)
    store = retained.VfsSnapshotStore(destination, lambda: None)
    capture = store.command("compile", 0)
    raw_info, raw_inspect = canonical(source.info), canonical(source.selected)
    operations = original_controls(destination, raw_info, raw_inspect)
    capture.record("info", "selection", raw_info)
    capture.record("inspect", "selection", raw_inspect)
    _, proof = vfs.acquire(source.service, raw_info, source.selected, CID, IMAGE,
                           source.mounts, lambda: None, snapshots=capture)
    vfs.check_mount_tables(source.service, [source.graph, source.run, Path(source.mounts["source"]["source"])],
                           lambda: None, snapshots=capture, phase="final-view")
    binding = {"recipe_sha256": "f" * 64, "stage": "compile", "index": 0,
               "container_id": CID, "image_id": IMAGE, "root_acquisition_sha256": sha(retained._json(proof))}
    manifest_pin = capture.complete(binding)
    value = SimpleNamespace(source=source, destination=destination, store=store, capture=capture,
                            proof=proof, operations=operations, binding=binding, pin=manifest_pin)
    try:
        yield value
    finally:
        os.close(source.service.root_fd)


def verify(vector, **overrides):
    values = {"workspace": vector.destination, "pin": vector.pin, "binding": vector.binding,
              "proof": vector.proof, "operations": vector.operations, "checkpoint": lambda: None}
    values.update(overrides)
    return retained.verify_snapshots(**values)


def manifest(vector):
    return json.loads((vector.destination / vector.pin["path"]).read_bytes())


def rewrite_manifest(vector, value):
    raw = retained._json(value)
    (vector.destination / vector.pin["path"]).write_bytes(raw)
    vector.pin = pin(vector.pin["path"], raw)


def test_original_buffers_are_retained_private_deduplicated_and_independently_replayed(vector, monkeypatch):
    original = vector.source.oci.read_bytes()
    # Source queries are unavailable after the original acquisition.
    monkeypatch.setattr(vfs, "read_at", lambda *_args, **_kwargs: pytest.fail("live source read"))
    monkeypatch.setattr(vfs, "_proc_bytes", lambda *_args, **_kwargs: pytest.fail("live proc read"))
    assert verify(vector) == json.loads(original)
    rows = manifest(vector)["records"]
    assert len(rows) == 21
    assert len({row["sha256"] for row in rows}) < len(rows)
    assert len(list((vector.destination / "custody/vfs-raw/blobs").iterdir())) == len(vector.store.blobs)
    for row in rows:
        path = vector.destination / "custody/vfs-raw/blobs" / (row["sha256"] + ".bin")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert row["blob_identity"] == retained._file_identity(path.stat())
    assert stat.S_IMODE((vector.destination / vector.pin["path"]).parent.stat().st_mode) == 0o700
    assert manifest(vector)["production_admission"] is False
    assert manifest(vector)["online_publication"] is False


@pytest.mark.parametrize("change", ["bytes", "same-byte-inode", "symlink", "hardlink", "public-mode", "deleted"])
def test_blob_substitution_refuses_even_equal_bytes(vector, change):
    row = manifest(vector)["records"][0]
    path = vector.destination / "custody/vfs-raw/blobs" / (row["sha256"] + ".bin")
    raw = path.read_bytes()
    if change == "bytes":
        path.write_bytes(raw + b" ")
    elif change == "public-mode":
        path.chmod(0o644)
    elif change == "hardlink":
        os.link(path, path.with_name("alias"))
    else:
        backup = path.with_name("original")
        path.rename(backup)
        if change == "same-byte-inode":
            path.write_bytes(raw)
            path.chmod(0o600)
        elif change == "symlink":
            path.symlink_to(backup)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector)


@pytest.mark.parametrize("change", ["missing", "duplicate", "unknown-role", "unknown-phase", "source-identity", "blob-identity",
                                     "public-manifest", "missing-receipt", "receipt-bytes", "incomplete", "schema", "admission"])
def test_manifest_and_event_integrity_refuses(vector, change):
    value = manifest(vector)
    if change == "missing":
        value["records"].pop()
    elif change == "duplicate":
        value["records"].append(copy.deepcopy(value["records"][0]))
    elif change == "unknown-role":
        value["records"][0]["role"] = "argv"
    elif change == "unknown-phase":
        value["records"][0]["phase"] = "later"
    elif change == "source-identity":
        value["records"][0]["source_identity"] = {}
    elif change == "blob-identity":
        value["records"][0]["blob_identity"]["inode"] += 1
    elif change == "incomplete":
        value["complete"] = False
    elif change == "schema":
        value["schema"] += "-other"
    elif change == "admission":
        value["production_admission"] = True
    elif change == "public-manifest":
        (vector.destination / vector.pin["path"]).chmod(0o644)
    elif change == "missing-receipt":
        (vector.destination / vector.pin["path"]).with_name("record-00.json").unlink()
    elif change == "receipt-bytes":
        (vector.destination / vector.pin["path"]).with_name("record-00.json").write_bytes(b"{}\n")
    if change not in {"public-manifest", "missing-receipt", "receipt-bytes"}:
        rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector)


@pytest.mark.parametrize("field,value", [("stage", "link"), ("index", 1), ("index", True), ("container_id", "d" * 64),
                                         ("image_id", "d" * 64), ("recipe_sha256", "d" * 64),
                                         ("root_acquisition_sha256", "d" * 64)])
def test_exact_original_binding_is_required(vector, field, value):
    binding = {**vector.binding, field: value}
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector, binding=binding)


@pytest.mark.parametrize("role", ["vfs-store-selection", "runtime-selection"])
@pytest.mark.parametrize("change", ["pin", "body", "symlink", "duplicate"])
def test_original_control_output_is_replayed_without_live_query(vector, role, change):
    operation = next(item for item in vector.operations if item["operation"] == role)
    path = vector.destination / "custody/compile-0" / role / "stdout.log"
    if change == "pin":
        operation["logs"]["stdout"]["sha256"] = "d" * 64
    elif change == "body":
        path.write_bytes(path.read_bytes() + b" ")
    elif change == "duplicate":
        vector.operations.append(copy.deepcopy(operation))
    else:
        original = path.with_name("other.log")
        path.rename(original)
        path.symlink_to(original)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector)


@pytest.mark.parametrize("change", ["metadata", "oci", "mounts", "ancillary"])
def test_retained_original_bodies_must_bind_the_original_proof(vector, change):
    proof = copy.deepcopy(vector.proof)
    if change == "metadata":
        proof["metadata"]["containers_sha256"] = "d" * 64
    elif change == "oci":
        proof["metadata"]["oci_identity"]["inode"] += 1
    elif change == "mounts":
        proof["mount_tables"]["service_sha256"] = "d" * 64
    else:
        proof["ancillary_mounts"][0]["sha256"] = "d" * 64
    binding = {**vector.binding, "root_acquisition_sha256": sha(retained._json(proof))}
    value = manifest(vector)
    value["binding"] = binding
    rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector, proof=proof, binding=binding)


def store_only(tmp_path):
    (tmp_path / "custody").mkdir(mode=0o700)
    (tmp_path / "custody/compile-0").mkdir()
    store = retained.VfsSnapshotStore(tmp_path, lambda: None)
    return store, store.command("compile", 0)


def test_unknown_preexisting_cas_body_cannot_be_adopted(tmp_path):
    store, capture = store_only(tmp_path)
    raw = b"{}\n"
    body = tmp_path / "custody/vfs-raw/blobs" / (sha(raw) + ".bin")
    body.write_bytes(raw)
    body.chmod(0o600)
    with pytest.raises(FileExistsError):
        capture.record("info", "selection", raw)
    assert not capture.records and not store.blobs


@pytest.mark.parametrize("role,phase,raw,identity", [
    ("info", "selection", b"x" * 16385, None), ("inspect", "selection", b"x" * 32769, None),
    ("mountinfo-client", "unexpected", b"", None), ("argv", "selection", b"", None),
    ("containers", "before", b"[]", None), ("info", "selection", "{}", None),
    ("info", "selection", b"{}", {}), ("ancillary-resolver", "host", b"xx", {}),
])
def test_each_role_is_bounded_and_has_exact_identity_kind(tmp_path, role, phase, raw, identity):
    _, capture = store_only(tmp_path)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        capture.record(role, phase, raw, identity)
    assert not list((tmp_path / "custody/vfs-raw/blobs").iterdir())


def test_attempt_total_budget_includes_receipts_and_keeps_partial_body(tmp_path, monkeypatch):
    store, capture = store_only(tmp_path)
    monkeypatch.setattr(retained, "MAX_STORED_BYTES", 4)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        capture.record("info", "selection", b"{}\n")
    assert len(list((tmp_path / "custody/vfs-raw/blobs").iterdir())) == 1
    assert not capture.records and store.stored_bytes == 3
    assert not (tmp_path / "custody/compile-0/vfs-raw/manifest.json").exists()


@pytest.mark.parametrize("failure", ["zero-write", "fsync", "cancel"])
def test_io_or_cancellation_failure_retains_partial_without_completion(tmp_path, monkeypatch, failure):
    store, capture = store_only(tmp_path)
    if failure == "zero-write":
        monkeypatch.setattr(retained.os, "write", lambda *_args: 0)
    elif failure == "fsync":
        monkeypatch.setattr(retained.os, "fsync", lambda *_args: (_ for _ in ()).throw(OSError("storage")))
    else:
        def expired():
            raise RuntimeError("original deadline")
        store.checkpoint = expired
    with pytest.raises((ValueError, OSError, RuntimeError)):
        capture.record("info", "selection", b"{}\n")
    assert not capture.completed
    assert not (tmp_path / "custody/compile-0/vfs-raw/manifest.json").exists()


def test_duplicate_event_command_and_completion_are_refused(vector):
    with pytest.raises(ValueError, match="podman_vfs_snapshots"):
        vector.capture.record("info", "selection", b"{}")
    with pytest.raises(ValueError, match="podman_vfs_snapshots"):
        vector.store.command("compile", 0)
    with pytest.raises(ValueError, match="podman_vfs_snapshots"):
        vector.capture.complete(vector.binding)


def test_partial_events_remain_readable_without_complete_claim(tmp_path):
    _, capture = store_only(tmp_path)
    capture.record("info", "selection", b"{}\n")
    capture.record("inspect", "selection", b"{}\n")
    with pytest.raises(ValueError, match="podman_vfs_snapshots"):
        capture.complete({"recipe_sha256": "a" * 64, "stage": "compile", "index": 0,
                          "container_id": CID, "image_id": IMAGE, "root_acquisition_sha256": "b" * 64})
    folder = tmp_path / "custody/compile-0/vfs-raw"
    assert len(list(folder.glob("record-*.json"))) == 2
    assert not (folder / "manifest.json").exists()
    assert len(list((tmp_path / "custody/vfs-raw/blobs").iterdir())) == 1


def replace_retained_body(vector, value, role, phase, raw):
    """Coordinate every local body/descriptor pin so semantics, not hash drift, decide."""
    index, row = next((index, row) for index, row in enumerate(value["records"])
                      if (row["role"], row["phase"]) == (role, phase))
    body = vector.destination / "custody/vfs-raw/blobs" / (sha(raw) + ".bin")
    if not body.exists():
        body.write_bytes(raw)
        body.chmod(0o600)
    row.update(size=len(raw), sha256=sha(raw), blob_identity=retained._file_identity(body.stat()))
    if row["source_identity"] is not None:
        row["source_identity"]["size"] = len(raw)
    receipt = (vector.destination / vector.pin["path"]).with_name(f"record-{index:02d}.json")
    receipt.write_bytes(retained._json(row))
    return row


@pytest.mark.parametrize("field", ["hostname", "hosts"])
def test_coordinated_inspect_control_and_manifest_edits_cannot_add_ambient_metadata(vector, field):
    value = manifest(vector)
    selected = dict(vector.source.selected)
    selected[field] = "/ambient/generated-data"
    raw = canonical(selected)
    replace_retained_body(vector, value, "inspect", "selection", raw)
    path = vector.destination / "custody/compile-0/runtime-selection/stdout.log"
    path.write_bytes(raw)
    operation = next(row for row in vector.operations if row["operation"] == "runtime-selection")
    operation["logs"]["stdout"] = {"size": len(raw), "sha256": sha(raw)}
    rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector)


def test_coordinated_mountinfo_and_proof_edits_still_refuse_subordinate_mount_alias(vector):
    raw = MOUNTINFO + f"2 1 0:2 / {vector.source.graph}/vfs rw - tmpfs tmpfs rw\n".encode()
    value, proof = manifest(vector), copy.deepcopy(vector.proof)
    for role in ("service", "client"):
        proof["mount_tables"][role + "_sha256"] = sha(raw)
        for phase in ("acquire-before", "acquire-after", "final-view"):
            replace_retained_body(vector, value, "mountinfo-" + role, phase, raw)
    binding = {**vector.binding, "root_acquisition_sha256": sha(retained._json(proof))}
    value["binding"] = binding
    rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector, proof=proof, binding=binding)


@pytest.mark.parametrize("target", ["", "custody", "custody/vfs-raw", "custody/vfs-raw/blobs",
                                     "custody/compile-0", "custody/compile-0/vfs-raw"])
def test_live_store_refuses_original_directory_name_replacement(tmp_path, target):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store, capture = store_only(workspace)
    path = workspace / target if target else workspace
    backup = path.with_name(path.name + "-original")
    path.rename(backup)
    path.mkdir(mode=0o700)
    try:
        with pytest.raises((ValueError, OSError)):
            capture.record("info", "selection", b"{}\n")
        assert not list(path.iterdir())
        assert not store.blobs
    finally:
        path.rmdir()
        backup.rename(path)


@pytest.mark.parametrize("target", ["custody/vfs-raw/blobs", "custody/compile-0/vfs-raw"])
def test_directory_substitution_during_original_write_is_not_accepted(tmp_path, monkeypatch, target):
    _store, capture = store_only(tmp_path)
    original_write = retained.os.write
    changed = []
    path = tmp_path / target
    backup = path.with_name(path.name + "-original")

    def substitute(fd, raw):
        count = original_write(fd, raw)
        if not changed:
            changed.append(True)
            path.rename(backup)
            path.mkdir(mode=0o700)
        return count

    monkeypatch.setattr(retained.os, "write", substitute)
    try:
        with pytest.raises((ValueError, OSError)):
            capture.record("info", "selection", b"{}\n")
        assert not capture.records and not capture.completed
    finally:
        path.rmdir()
        backup.rename(path)


def test_detached_reader_requires_original_directory_identity(vector):
    path = vector.destination / "custody/compile-0/vfs-raw"
    original = path.with_name("vfs-raw-original")
    path.rename(original)
    path.mkdir(mode=0o700)
    # Move original artifact inodes so all file bodies and pins remain exact.
    for entry in original.iterdir():
        entry.rename(path / entry.name)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        verify(vector)


def test_read_at_retention_identity_comes_from_the_same_original_buffer_fd(tmp_path, monkeypatch):
    path = tmp_path / "original"
    path.write_bytes(b"original bytes")
    expected = retained._file_identity(path.stat())
    recorded = []
    capture = SimpleNamespace(record=lambda *args: recorded.append(args))
    monkeypatch.setattr(vfs, "file_identity_at", lambda *_args: pytest.fail("separate identity query"))
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        assert vfs.read_at(root_fd, path, 1024, lambda: None, snapshots=capture,
                           role="oci", phase="acquire") == b"original bytes"
    finally:
        os.close(root_fd)
    assert recorded == [("oci", "acquire", b"original bytes", expected)]


def test_first_successful_metadata_buffer_is_preserved_when_next_source_read_fails(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    value = vfs_vector(source)
    original_read = vfs.read_at
    recorded = []
    capture = SimpleNamespace(record=lambda *args: recorded.append(args))
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=1024**2: MOUNTINFO)

    def interrupted(root_fd, path, maximum, checkpoint, **kwargs):
        if path == value.layers:
            raise OSError("original layers unavailable")
        return original_read(root_fd, path, maximum, checkpoint, **kwargs)

    monkeypatch.setattr(vfs, "read_at", interrupted)
    try:
        with pytest.raises(OSError, match="original layers unavailable"):
            vfs.acquire(value.service, canonical(value.info), value.selected, CID, IMAGE,
                        value.mounts, lambda: None, snapshots=capture)
    finally:
        os.close(value.service.root_fd)
    assert [(row[0], row[1]) for row in recorded] == [
        ("mountinfo-service", "acquire-before"), ("mountinfo-client", "acquire-before"),
        ("containers", "before")]
    assert recorded[-1][2] == value.containers.read_bytes()
    assert recorded[-1][3] == retained._file_identity(value.containers.stat())
