"""Inert original-deadline pins, filesystem drift and publisher fault fixtures."""

from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

import lunar_evolution.native_deadline_binding as module
from lunar_evolution.native_deadline_binding import (
    DEADLINE_NAME,
    NativeDeadlineBindingError,
    capture_native_deadline_binding,
    deadline_binding_digest,
    persist_native_deadline_binding,
    validate_native_deadline_binding,
    verify_native_deadline_binding,
    verify_native_deadline_record_binding,
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _record(deadline=120.0):
    record = {
        "schema_version": "1", "protocol": "lunar-native-trusted-attempt-deadline-v1",
        "launch_id": "fixture-launch", "journal_id": "fixture-journal",
        "launch_sha256": "a" * 64, "intent_sha256": "b" * 64,
        "attestation_sha256": "c" * 64, "started_monotonic": 100.0,
        "deadline_monotonic": deadline, "boot_id": "fixture-boot",
    }
    record["deadline_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
    return record


def _file(tmp_path, raw=None):
    path = tmp_path / DEADLINE_NAME
    path.write_bytes(_canonical(_record()) if raw is None else raw)
    path.chmod(0o600)
    return path


@pytest.fixture
def pinned(tmp_path):
    path = _file(tmp_path)
    binding = capture_native_deadline_binding(tmp_path, expected_record=_record())
    return path, binding


def test_capture_and_verify_pin_every_original_file_field_without_writing(pinned):
    path, binding = pinned
    original = path.stat()
    assert binding == {
        "schema_version": "1", "protocol": "lunar-native-deadline-file-binding-v1",
        "name": DEADLINE_NAME, "deadline_sha256": _record()["deadline_sha256"],
        "raw_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": original.st_size, "device": original.st_dev, "inode": original.st_ino,
        "mode": 0o600, "mtime_ns": original.st_mtime_ns, "ctime_ns": original.st_ctime_ns,
    }
    assert verify_native_deadline_binding(path.parent, binding=binding) == _record()
    assert verify_native_deadline_binding(
        path.parent, binding=binding, expected_record=_record(),
    ) == _record()
    assert verify_native_deadline_record_binding(_record(), binding) is None
    assert deadline_binding_digest(binding) == hashlib.sha256(_canonical(binding)).hexdigest()
    assert path.stat().st_mtime_ns == original.st_mtime_ns
    assert path.stat().st_ctime_ns == original.st_ctime_ns
    assert tuple(path.parent.iterdir()) == (path,)
    copy = validate_native_deadline_binding(binding)
    copy["inode"] += 1
    assert copy != binding


@pytest.mark.parametrize("field", [
    "schema_version", "protocol", "name", "deadline_sha256", "raw_sha256", "size",
    "device", "inode", "mode", "mtime_ns", "ctime_ns",
])
def test_binding_requires_every_exact_field(pinned, field):
    _, binding = pinned
    del binding[field]
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        validate_native_deadline_binding(binding)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 1), ("schema_version", "2"), ("protocol", "other"),
    ("name", "../" + DEADLINE_NAME), ("name", "other.json"),
    ("deadline_sha256", "A" * 64), ("raw_sha256", "z" * 64),
    ("raw_sha256", "a" * 63), ("raw_sha256", "a" * 65),
    ("deadline_sha256", None), ("mode", 0o400), ("mode", 0o660),
    ("mode", stat.S_IFREG | 0o600), ("inode", 0), ("size", 0),
    ("size", module.MAX_NATIVE_DEADLINE_BYTES + 1),
])
def test_binding_rejects_wrong_literals_digests_and_ranges(pinned, field, value):
    _, binding = pinned
    binding[field] = value
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        validate_native_deadline_binding(binding)


@pytest.mark.parametrize("field", ["size", "device", "inode", "mode", "mtime_ns", "ctime_ns"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, -1, 2**64])
def test_binding_stat_pins_require_bounded_non_boolean_integers(pinned, field, value):
    _, binding = pinned
    binding[field] = value
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        validate_native_deadline_binding(binding)


@pytest.mark.parametrize("value", [None, [], "binding", 42, {"extra": "a" * 5000}])
def test_binding_rejects_non_mapping_and_extra_fields(value):
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        validate_native_deadline_binding(value)


def test_binding_rejects_extra_field(pinned):
    _, binding = pinned
    binding["extra"] = 1
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        deadline_binding_digest(binding)


@pytest.mark.parametrize("deadline", [110.0, 999.0])
def test_pure_record_and_capture_refuse_legally_rehashed_changed_budget(pinned, deadline):
    path, binding = pinned
    changed = _record(deadline)
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_mismatch"):
        verify_native_deadline_record_binding(changed, binding)
    path.write_bytes(_canonical(changed))
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_mismatch"):
        capture_native_deadline_binding(path.parent, expected_record=_record())
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_mismatch"):
        verify_native_deadline_binding(path.parent, binding=binding)


def test_pure_record_verifies_its_self_digest(pinned):
    _, binding = pinned
    changed = _record()
    changed["deadline_monotonic"] = 200.0
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_mismatch"):
        verify_native_deadline_record_binding(changed, binding)


@pytest.mark.parametrize("field", ["raw_sha256", "deadline_sha256", "size"])
def test_pure_record_refuses_independent_pin_mismatch(pinned, field):
    _, binding = pinned
    binding[field] = binding[field] + 1 if field == "size" else "0" * 64
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_mismatch"):
        verify_native_deadline_record_binding(_record(), binding)


@pytest.mark.parametrize("raw", [
    b"{}", b"[]", b"null", b"\xff", b"{", b'{"deadline_sha256":NaN}',
    _canonical(_record()) + b"\n", b" " + _canonical(_record()),
    _canonical(_record()).replace(b'{', b'{"schema_version":"1",', 1),
])
def test_capture_rejects_noncanonical_or_duplicate_json(tmp_path, raw):
    _file(tmp_path, raw)
    with pytest.raises(NativeDeadlineBindingError):
        capture_native_deadline_binding(tmp_path, expected_record=_record())


def test_raw_and_expected_records_are_bounded(tmp_path):
    path = _file(tmp_path, b" " * (module.MAX_NATIVE_DEADLINE_BYTES + 1))
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_too_large"):
        capture_native_deadline_binding(tmp_path, expected_record=_record())
    oversized = _record()
    oversized["padding"] = "a" * module.MAX_NATIVE_DEADLINE_BYTES
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_too_large"):
        capture_native_deadline_binding(tmp_path, expected_record=oversized)
    assert path.stat().st_size == module.MAX_NATIVE_DEADLINE_BYTES + 1


@pytest.mark.parametrize("kind", ["replace", "touch", "chmod", "hardlink", "symlink",
                                  "directory", "fifo"])
def test_verify_refuses_bytes_identity_mode_links_and_special_file_drift(pinned, kind):
    path, binding = pinned
    if kind == "replace":
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        replacement.replace(path)
    elif kind == "touch":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
    elif kind == "chmod":
        path.chmod(0o400)
    elif kind == "hardlink":
        os.link(path, path.with_name("alias"))
    else:
        path.unlink()
        if kind == "symlink":
            target = path.with_name("target")
            target.write_bytes(_canonical(_record()))
            path.symlink_to(target)
        elif kind == "directory":
            path.mkdir()
        else:
            os.mkfifo(path, 0o600)
    with pytest.raises(NativeDeadlineBindingError):
        verify_native_deadline_binding(path.parent, binding=binding)


def test_capture_refuses_symlink_ancestor(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    _file(original)
    alias = tmp_path / "alias"
    alias.symlink_to(original, target_is_directory=True)
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_unavailable"):
        capture_native_deadline_binding(alias, expected_record=_record())


def test_capture_and_publish_refuse_parent_traversal_alias(tmp_path):
    for call in (capture_native_deadline_binding, persist_native_deadline_binding):
        keyword = "expected_record" if call is capture_native_deadline_binding else "record"
        with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
            call(tmp_path / ".." / tmp_path.name, **{keyword: _record()})


@pytest.mark.parametrize("batch", [None, [], 1, "\x00", "\ud800"])
@pytest.mark.parametrize("call", [capture_native_deadline_binding, persist_native_deadline_binding])
def test_bad_directory_inputs_have_fixed_codes_without_access(batch, call):
    keyword = "expected_record" if call is capture_native_deadline_binding else "record"
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_invalid"):
        call(batch, **{keyword: _record()})


@pytest.mark.parametrize("kind", ["replace", "metadata", "hardlink", "append"])
def test_verify_rechecks_file_after_read(pinned, monkeypatch, kind):
    path, binding = pinned
    original_read = os.read
    changed = False

    def read(fd, size):
        nonlocal changed
        raw = original_read(fd, size)
        if not changed and raw:
            changed = True
            if kind == "replace":
                replacement = path.with_name("replacement")
                replacement.write_bytes(_canonical(_record()))
                replacement.chmod(0o600)
                replacement.replace(path)
            elif kind == "metadata":
                info = path.stat()
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
            elif kind == "hardlink":
                os.link(path, path.with_name("alias"))
            else:
                with path.open("ab") as stream:
                    stream.write(b"\n")
        return raw

    monkeypatch.setattr(module.os, "read", read)
    with pytest.raises(NativeDeadlineBindingError):
        verify_native_deadline_binding(path.parent, binding=binding)
    assert changed


def test_verify_rechecks_held_ancestor_after_digest_validation(pinned, monkeypatch):
    path, binding = pinned
    original = module.verify_native_deadline_record_binding

    def verify(record, expected):
        original(record, expected)
        retired = path.parent.with_name(path.parent.name + "-retired")
        path.parent.rename(retired)
        path.parent.mkdir()

    monkeypatch.setattr(module, "verify_native_deadline_record_binding", verify)
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_unavailable"):
        verify_native_deadline_binding(path.parent, binding=binding)


@pytest.mark.parametrize("error", [OSError("inert read fault"), KeyboardInterrupt(), SystemExit(1)])
def test_read_errors_and_interrupts_close_every_acquired_descriptor(pinned, monkeypatch, error):
    path, binding = pinned
    opened = set()
    original_open, original_close = os.open, os.close

    def open_fd(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def close_fd(fd):
        original_close(fd)
        opened.remove(fd)

    def read(_fd, _size):
        raise error

    monkeypatch.setattr(module.os, "open", open_fd)
    monkeypatch.setattr(module.os, "close", close_fd)
    monkeypatch.setattr(module.os, "read", read)
    expected = NativeDeadlineBindingError if isinstance(error, OSError) else type(error)
    with pytest.raises(expected):
        verify_native_deadline_binding(path.parent, binding=binding)
    assert not opened


def test_publisher_creates_once_and_keeps_original_descriptor(tmp_path, monkeypatch):
    batch = tmp_path / "nested" / "batch"
    target_descriptors = []
    read_descriptors = []
    original_open, original_read = os.open, os.read

    def open_fd(name, flags, *args, **kwargs):
        fd = original_open(name, flags, *args, **kwargs)
        if str(name).startswith(".native-deadline-"):
            target_descriptors.append(fd)
        assert str(name) != DEADLINE_NAME
        return fd

    def read(fd, size):
        read_descriptors.append(fd)
        return original_read(fd, size)

    with monkeypatch.context() as patch:
        patch.setattr(module.os, "open", open_fd)
        patch.setattr(module.os, "read", read)
        binding = persist_native_deadline_binding(batch, record=_record())
    assert read_descriptors and set(read_descriptors) == set(target_descriptors)
    assert verify_native_deadline_binding(batch, binding=binding) == _record()
    assert sorted(item.name for item in batch.iterdir()) == [DEADLINE_NAME]
    inode = (batch / DEADLINE_NAME).stat().st_ino
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_conflict"):
        persist_native_deadline_binding(batch, record=_record(200.0))
    assert (batch / DEADLINE_NAME).stat().st_ino == inode
    assert (batch / DEADLINE_NAME).read_bytes() == _canonical(_record())
    assert sorted(item.name for item in batch.iterdir()) == [DEADLINE_NAME]


@pytest.mark.parametrize("fsync_number", [1, 2])
def test_publisher_fsync_fault_preserves_published_final_and_closes_fds(
    tmp_path, monkeypatch, fsync_number,
):
    opened = set()
    original_open, original_close, original_fsync = os.open, os.close, os.fsync
    calls = 0

    def open_fd(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def close_fd(fd):
        original_close(fd)
        opened.remove(fd)

    def fsync(fd):
        nonlocal calls
        calls += 1
        if calls == fsync_number:
            raise OSError("inert durability fault")
        original_fsync(fd)

    monkeypatch.setattr(module.os, "open", open_fd)
    monkeypatch.setattr(module.os, "close", close_fd)
    monkeypatch.setattr(module.os, "fsync", fsync)
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_unavailable"):
        persist_native_deadline_binding(tmp_path, record=_record())
    assert not opened
    assert (tmp_path / DEADLINE_NAME).exists() == (fsync_number == 2)
    assert not tuple(tmp_path.glob(".native-deadline-*.tmp"))


def test_publisher_refuses_same_bytes_replacement_after_publication(tmp_path, monkeypatch):
    original_fsync = os.fsync
    replaced = False

    def fsync(fd):
        nonlocal replaced
        original_fsync(fd)
        if stat.S_ISDIR(os.fstat(fd).st_mode) and not replaced:
            replaced = True
            replacement = tmp_path / "replacement"
            replacement.write_bytes(_canonical(_record()))
            replacement.chmod(0o600)
            replacement.replace(tmp_path / DEADLINE_NAME)

    monkeypatch.setattr(module.os, "fsync", fsync)
    with pytest.raises(NativeDeadlineBindingError):
        persist_native_deadline_binding(tmp_path, record=_record())
    assert replaced
    assert (tmp_path / DEADLINE_NAME).read_bytes() == _canonical(_record())
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_conflict"):
        persist_native_deadline_binding(tmp_path, record=_record())


def test_publisher_refuses_temporary_name_replaced_before_link(tmp_path, monkeypatch):
    original_link = os.link

    def link(source, destination, **kwargs):
        replacement = tmp_path / "replacement"
        replacement.write_bytes(_canonical(_record()))
        replacement.chmod(0o600)
        replacement.replace(tmp_path / source)
        return original_link(source, destination, **kwargs)

    monkeypatch.setattr(module.os, "link", link)
    with pytest.raises(NativeDeadlineBindingError):
        persist_native_deadline_binding(tmp_path, record=_record())
    assert sorted(item.name for item in tmp_path.iterdir()) == [DEADLINE_NAME]


def test_publisher_handles_short_writes(tmp_path, monkeypatch):
    original_write = os.write
    monkeypatch.setattr(module.os, "write", lambda fd, raw: original_write(fd, raw[:7]))
    binding = persist_native_deadline_binding(tmp_path, record=_record())
    assert verify_native_deadline_binding(tmp_path, binding=binding) == _record()


def test_publisher_zero_write_does_not_publish(tmp_path, monkeypatch):
    monkeypatch.setattr(module.os, "write", lambda _fd, _raw: 0)
    with pytest.raises(NativeDeadlineBindingError, match="native_deadline_binding_unavailable"):
        persist_native_deadline_binding(tmp_path, record=_record())
    assert not tuple(tmp_path.iterdir())


def test_publisher_interruption_retains_final_and_cleans_temporary_and_fds(tmp_path, monkeypatch):
    opened = set()
    original_open, original_close, original_fsync = os.open, os.close, os.fsync

    def open_fd(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def close_fd(fd):
        original_close(fd)
        opened.remove(fd)

    def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise KeyboardInterrupt()
        original_fsync(fd)

    monkeypatch.setattr(module.os, "open", open_fd)
    monkeypatch.setattr(module.os, "close", close_fd)
    monkeypatch.setattr(module.os, "fsync", fsync)
    with pytest.raises(KeyboardInterrupt):
        persist_native_deadline_binding(tmp_path, record=_record())
    assert not opened
    assert sorted(item.name for item in tmp_path.iterdir()) == [DEADLINE_NAME]
