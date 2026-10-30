"""Real FD trees for original-worker input observations, without Podman execution.

These tests verify an exact finite view at a named boundary. They establish no
continuous immutability, writer exclusion, namespace drain or runtime authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
from contextlib import contextmanager

import pytest

from tests import test_static_python_rsi_vfs_lifetime as lifetime_tests
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

REFUSALS = (ValueError, OSError, BuildExecutionError)


def row(path, raw, *, executable=False):
    return {"path": path, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": executable}


def write(root, path, raw, *, executable=False):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    target.chmod(0o500 if executable else 0o400)
    return target


@contextmanager
def held_root(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        yield fd
    finally:
        os.close(fd)


@pytest.fixture
def input_tree(tmp_path):
    root = tmp_path / "worker-toolchain"
    root.mkdir()
    values = {"bin/zig": (b"never executed executable", True),
              "lib/include/stddef.h": (b"pinned header", False),
              "lib/musl/crt.o": (b"pinned support", False)}
    records = []
    for path, (raw, executable) in sorted(values.items()):
        write(root, path, raw, executable=executable)
        records.append(row(path, raw, executable=executable))
    return root, records


def observe(root, records, checkpoint=lambda: None):
    with held_root(root) as fd:
        return lifetime._observe_worker_inventory(fd, records, checkpoint)


def test_original_fd_view_reads_the_complete_inventory_once(input_tree, monkeypatch):
    root, records = input_tree
    read_bytes = {}
    real_read = os.read

    def count_read(fd, size):
        raw = real_read(fd, size)
        info = os.fstat(fd)
        if raw and stat.S_ISREG(info.st_mode):
            read_bytes[info.st_ino] = read_bytes.get(info.st_ino, 0) + len(raw)
        return raw

    monkeypatch.setattr(lifetime.os, "read", count_read)
    result = observe(root, records)
    assert result == {"inventory_sha256": retained._sha(retained._json(records)),
                      "file_count": 3, "directory_count": 5,
                      "total_bytes": sum(record["size"] for record in records)}
    assert read_bytes == {(root / record["path"]).stat().st_ino: record["size"] for record in records}


def test_empty_prior_view_has_only_its_original_root(tmp_path):
    root = tmp_path / "prior"
    root.mkdir()
    assert observe(root, []) == {"inventory_sha256": retained._sha(retained._json([])),
                                 "file_count": 0, "directory_count": 1, "total_bytes": 0}
    (root / "unapproved-empty-directory").mkdir()
    with pytest.raises(REFUSALS):
        observe(root, [])


@pytest.mark.parametrize("change", ["missing", "extra-file", "extra-directory", "size", "bytes", "execute-bit"])
def test_original_view_refuses_members_and_content_outside_the_pinned_inventory(input_tree, change):
    root, records = input_tree
    path = root / "lib/musl/crt.o"
    if change == "missing":
        path.unlink()
    elif change == "extra-file":
        write(root, "lib/unknown-config", b"ambient configuration")
    elif change == "extra-directory":
        (root / "lib/unknown-cache").mkdir()
    elif change == "size":
        path.chmod(0o600)
        path.write_bytes(b"x")
        path.chmod(0o400)
    elif change == "bytes":
        path.chmod(0o600)
        path.write_bytes(b"X" * records[2]["size"])
        path.chmod(0o400)
    else:
        path.chmod(0o500)
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.mark.parametrize("change", ["leaf-symlink", "parent-symlink", "fifo", "directory-as-file"])
def test_original_view_never_follows_input_symlinks_or_blocks_on_special_files(input_tree, tmp_path, change):
    root, records = input_tree
    path = root / "lib/musl/crt.o"
    if change == "parent-symlink":
        original = root / "lib/musl"
        relocated = tmp_path / "outside"
        original.rename(relocated)
        original.symlink_to(relocated, target_is_directory=True)
    else:
        raw = path.read_bytes()
        path.unlink()
        if change == "leaf-symlink":
            outside = tmp_path / "outside.o"
            outside.write_bytes(raw)
            path.symlink_to(outside)
        elif change == "fifo":
            os.mkfifo(path)
        else:
            path.mkdir()
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.mark.parametrize("change", ["same-bytes-file-replacement", "same-bytes-parent-replacement", "mode-during-read"])
def test_readback_retains_original_named_and_held_objects(input_tree, tmp_path, monkeypatch, change):
    root, records = input_tree
    target = root / "lib/musl/crt.o"
    original_inode = target.stat().st_ino
    original_raw = target.read_bytes()
    real_read = os.read
    changed = False

    def replace_after_original_read(fd, size):
        nonlocal changed
        raw = real_read(fd, size)
        if raw and not changed and os.fstat(fd).st_ino == original_inode:
            changed = True
            if change == "same-bytes-file-replacement":
                target.unlink()
                write(root, "lib/musl/crt.o", original_raw)
            elif change == "same-bytes-parent-replacement":
                target.parent.rename(tmp_path / "original-parent")
                write(root, "lib/musl/crt.o", original_raw)
            else:
                target.chmod(0o500)
        return raw

    monkeypatch.setattr(lifetime.os, "read", replace_after_original_read)
    with pytest.raises(REFUSALS):
        observe(root, records)
    assert changed
    if change != "mode-during-read":
        assert target.read_bytes() == original_raw and target.stat().st_ino != original_inode


@pytest.mark.parametrize("moment", ["before-walk", "after-first-read"])
def test_original_checkpoint_failure_is_preserved_without_replacement_attempt(input_tree, monkeypatch, moment):
    root, records = input_tree
    error = RuntimeError("original cancellation or exhausted deadline")
    real_read = os.read
    has_read = False
    calls = 0

    def read(fd, size):
        nonlocal has_read
        raw = real_read(fd, size)
        has_read |= bool(raw)
        return raw

    def checkpoint():
        nonlocal calls
        calls += 1
        if moment == "before-walk" or has_read:
            raise error

    monkeypatch.setattr(lifetime.os, "read", read)
    with pytest.raises(RuntimeError) as failure:
        observe(root, records, checkpoint)
    assert failure.value is error
    assert calls >= 1 and has_read is (moment == "after-first-read")


def test_closed_original_role_descriptor_is_not_reopened_by_path(input_tree):
    root, records = input_tree
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    os.close(fd)
    with pytest.raises(REFUSALS):
        lifetime._observe_worker_inventory(fd, records, lambda: None)


@pytest.mark.parametrize("change", ["duplicate", "file-parent", "bool-size", "integer-mode", "dotdot", "unknown-key"])
def test_invalid_original_inventory_refuses_before_walking(input_tree, monkeypatch, change):
    root, records = input_tree
    records = [dict(record) for record in records]
    if change == "duplicate":
        records.append(dict(records[0]))
    elif change == "file-parent":
        records.append(row("bin/zig/child", b"x"))
    elif change == "bool-size":
        records[0]["size"] = True
    elif change == "integer-mode":
        records[0]["executable"] = 1
    elif change == "dotdot":
        records[0]["path"] = "../outside"
    else:
        records[0]["approved"] = True
    monkeypatch.setattr(lifetime.os, "scandir", lambda *_args, **_kwargs: pytest.fail("walked invalid inventory"))
    with pytest.raises(REFUSALS):
        observe(root, records)


@pytest.fixture
def worker_owner_vector(tmp_path, monkeypatch):
    original_capture = lifetime._LifetimeCapture

    def capture(*args, **kwargs):
        return original_capture(*args, **{**kwargs, "worker_input_view": True})

    monkeypatch.setattr(lifetime, "_LifetimeCapture", capture)
    yield from lifetime_tests.owner_vector.__wrapped__(tmp_path, monkeypatch)


def worker_inventories(vector):
    values = {"source": [("unit.c", b"original source executable as data", True)],
              "toolchain": [("bin/zig", b"never executed pinned tool", True)],
              "work": [("configuration/probe.o", b"prior generated object", False)]}
    inventories = {}
    for role, files in values.items():
        inventories[role] = []
        for path, raw, executable in files:
            write(vector.root / role, path, raw, executable=executable)
            inventories[role].append(row(path, raw, executable=executable))
    return {role: inventories[role] for role in ("source", "toolchain")}, inventories["work"]


def complete_worker_history(vector, inputs, prior):
    original_create = vector.create

    def create(raw=None):
        owner = original_create(raw)
        owner._bind_worker_inputs(inputs, prior)
        return owner

    vector.create = create
    return lifetime_tests.complete(vector)


def replay_worker_history(vector, inputs, prior, **changes):
    options = {"workspace": vector.destination, "pin": vector.pin, "binding": vector.binding,
               "proof": vector.proof, "view": vector.view, "vfs_pin": vector.vfs_pin,
               "operations": vector.operations, "outputs": vector.outputs,
               "checkpoint": vector.checkpoint, "inputs": inputs, "prior": prior}
    options.update(changes)
    return lifetime.verify_worker_input_lifetime(**options)


def test_original_owner_binds_full_role_views_to_the_before_start_boundary(worker_owner_vector):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    owner = vector.create()
    owner._bind_worker_inputs(inputs, prior)
    owner.before_start()
    view = vector.capture.input_view
    assert view["schema"] == lifetime.WORKER_INPUT_PROFILE and view["phase"] == "before-start"
    assert view["owner_sha256"] == retained._sha(retained._json(owner.owner))
    assert set(view["roles"]) == {"source", "toolchain", "work"}
    for role, records in {**inputs, "work": prior}.items():
        assert view["roles"][role]["root_identity"] == owner.owner["roles"][role]
        assert view["roles"][role]["inventory_sha256"] == retained._sha(retained._json(records))
        assert view["roles"][role]["file_count"] == len(records)
        assert view["roles"][role]["total_bytes"] == sum(record["size"] for record in records)
    assert vector.capture.phases[1]["links"] == {
        "worker_input_view_sha256": retained._sha(retained._json(view))}
    assert all(value is False for value in view["claims"].values())


@pytest.mark.parametrize("action", ["unbound", "rebind", "after-start", "after-close"])
def test_worker_input_binding_belongs_only_to_its_original_prestart_owner(worker_owner_vector, action):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    owner = vector.create()
    if action != "unbound":
        owner._bind_worker_inputs(inputs, prior)
    if action == "after-start":
        owner.before_start()
    elif action == "after-close":
        owner.close()
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        if action == "unbound":
            owner.before_start()
        else:
            owner._bind_worker_inputs(inputs, prior)
    assert not (vector.destination / "custody/compile-0/vfs-lifetime/manifest.json").exists()


@pytest.mark.parametrize("role", ["source", "toolchain", "work"])
def test_original_worker_refuses_an_unapproved_member_before_start(worker_owner_vector, role):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    owner = vector.create()
    owner._bind_worker_inputs(inputs, prior)
    write(vector.root / role, "ambient-config", b"unknown input")
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.before_start()
    assert owner.phase == 1 and vector.capture.input_view is None


def test_worker_view_lifetime_round_trip_is_detached_and_all_claims_remain_false(worker_owner_vector, monkeypatch):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    complete_worker_history(vector, inputs, prior)
    manifest = lifetime_tests.manifest(vector)
    assert manifest["schema"] == lifetime.WORKER_INPUT_SCHEMA
    assert all(value is False for value in manifest["claims"].values())
    monkeypatch.setattr(lifetime.vfs, "_proc_bytes", lambda *_args, **_kwargs: pytest.fail("queried live proc"))
    monkeypatch.setattr(lifetime._VfsExecutionLifetime, "__init__", lambda *_args, **_kwargs: pytest.fail("recreated owner"))
    replay_worker_history(vector, inputs, prior)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        lifetime_tests.replay(vector)


@pytest.mark.parametrize("change", ["input-bytes", "prior-bytes", "cross-role", "owner", "claim", "phase-link", "old-schema"])
def test_detached_worker_view_cannot_change_its_original_binding(worker_owner_vector, change):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    complete_worker_history(vector, inputs, prior)
    value = lifetime_tests.manifest(vector)
    if change == "input-bytes":
        inputs["source"][0]["sha256"] = "d" * 64
    elif change == "prior-bytes":
        prior[0]["sha256"] = "d" * 64
    elif change == "cross-role":
        view = value["worker_input_view"]["roles"]
        view["source"], view["toolchain"] = view["toolchain"], view["source"]
    elif change == "owner":
        value["worker_input_view"]["owner_sha256"] = "d" * 64
    elif change == "claim":
        value["worker_input_view"]["claims"]["immutable_custody_verified"] = True
    elif change == "phase-link":
        value["phases"][1]["links"]["worker_input_view_sha256"] = "d" * 64
    else:
        value["schema"] = lifetime.SCHEMA
    lifetime_tests.rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay_worker_history(vector, inputs, prior)


@pytest.mark.parametrize("location", ["inside-view", "outside-view"])
def test_input_view_rejects_known_hardlink_aliases_even_when_bytes_are_pinned(input_tree, tmp_path, location):
    root, records = input_tree
    target = root / "lib/musl/crt.o"
    if location == "inside-view":
        alias = root / "lib/duplicate.o"
        os.link(target, alias)
        records = sorted([*records, row("lib/duplicate.o", target.read_bytes())], key=lambda record: record["path"])
    else:
        os.link(target, tmp_path / "outside-hardlink.o")
    assert target.stat().st_nlink == 2
    with pytest.raises(REFUSALS):
        observe(root, records)


def test_observation_keeps_the_borrowed_original_role_descriptor_open(input_tree):
    root, records = input_tree
    with held_root(root) as fd:
        original = os.fstat(fd)
        lifetime._observe_worker_inventory(fd, records, lambda: None)
        after = os.fstat(fd)
        assert (after.st_dev, after.st_ino) == (original.st_dev, original.st_ino)


def test_owner_binding_freezes_original_records_before_caller_mutation(worker_owner_vector):
    vector = worker_owner_vector
    inputs, prior = worker_inventories(vector)
    original_pin = retained._sha(retained._json(inputs["source"]))
    owner = vector.create()
    owner._bind_worker_inputs(inputs, prior)
    inputs["source"][0]["sha256"] = "d" * 64
    owner.before_start()
    assert vector.capture.input_view["roles"]["source"]["inventory_sha256"] == original_pin
