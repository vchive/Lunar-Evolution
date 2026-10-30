"""Actual helper-file refusal gates; no tool, daemon or container is executed."""

from __future__ import annotations

import hashlib
import struct

import pytest

from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError


class _Stop(BaseException):
    pass


def _elf(*, segments=(1,)):
    size = max(192, 64 + 56 * len(segments))
    header = struct.pack(
        "<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9,
        2, 62, 1, 0x400080, 64, 0, 0, 64, 56, len(segments), 0, 0, 0,
    )
    rows = []
    for segment in segments:
        rows.append(struct.pack("<IIQQQQQQ", segment, 5, 0, 0x400000, 0,
                                size if segment == 1 else 0, size if segment == 1 else 0, 4096))
    return (header + b"".join(rows)).ljust(size, b"\0")


def _write(root, name, raw, *, executable=True):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o555 if executable else 0o444)
    return {"path": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": executable}


def _bad_elf(change):
    if change == "script":
        return b"#!/ambient/interpreter\n".ljust(192, b" ")
    if change in {"interp", "dynamic"}:
        return _elf(segments=(1, 3 if change == "interp" else 2))
    raw = bytearray(_elf())
    changes = {
        "machine": ("<H", 18, 183), "type": ("<H", 16, 3),
        "version": ("<I", 20, 2), "header_size": ("<H", 52, 63),
        "phsize": ("<H", 54, 55), "phcount": ("<H", 56, 0),
        "phoffset": ("<Q", 32, 0), "table_bounds": ("<Q", 32, len(raw) - 1),
        "file_bounds": ("<Q", 64 + 32, len(raw) + 1),
        "memory_bounds": ("<Q", 64 + 40, 1),
        "address_overflow": ("<Q", 64 + 16, 2**64 - 2),
        "alignment": ("<Q", 64 + 48, 3),
        "load_flags": ("<I", 64 + 4, 13), "no_exec_load": ("<I", 64 + 4, 4),
        "entry_outside": ("<Q", 24, 0x500000), "entry_zero": ("<Q", 24, 0),
    }
    form, offset, value = changes[change]
    struct.pack_into(form, raw, offset, value)
    return bytes(raw)


def test_actual_static_helper_bytes_pass_without_executing_them(tmp_path):
    record = _write(tmp_path, "helper", _elf())
    assert custody._static_executable(tmp_path, record, lambda: None) is None


@pytest.mark.parametrize("change", [
    "script", "interp", "dynamic", "machine", "type", "version", "header_size",
    "phsize", "phcount", "phoffset", "table_bounds", "file_bounds", "memory_bounds",
    "address_overflow", "alignment", "load_flags", "no_exec_load", "entry_outside", "entry_zero",
])
def test_helper_loader_shape_is_refused_even_with_a_matching_declared_digest(tmp_path, change):
    record = _write(tmp_path, "helper", _bad_elf(change))
    with pytest.raises(BuildExecutionError, match="custody_static_executable"):
        custody._static_executable(tmp_path, record, lambda: None)


def test_valid_elf_shape_cannot_replace_the_original_pinned_bytes(tmp_path):
    record = _write(tmp_path, "helper", _elf())
    changed = bytearray(_elf())
    changed[-1] = 1
    (tmp_path / "helper").chmod(0o755)
    (tmp_path / "helper").write_bytes(changed)
    with pytest.raises(BuildExecutionError, match="custody_input_pin"):
        custody._static_executable(tmp_path, record, lambda: None)


@pytest.mark.parametrize("change", ["replace", "write", "mode"])
def test_helper_fd_and_name_must_remain_original_through_its_pinned_read(tmp_path, monkeypatch, change):
    record = _write(tmp_path, "helper", _elf())
    original_read, mutated = custody.os.read, []

    def read(fd, maximum):
        raw = original_read(fd, maximum)
        if maximum == 65536 and raw and not mutated:
            mutated.append(None)
            if change == "replace":
                _write(tmp_path, "replacement", _elf())
                (tmp_path / "replacement").replace(tmp_path / "helper")
            elif change == "write":
                changed = bytearray(_elf())
                changed[-1] = 1
                (tmp_path / "helper").chmod(0o755)
                (tmp_path / "helper").write_bytes(changed)
            else:
                (tmp_path / "helper").chmod(0o444)
        return raw

    monkeypatch.setattr(custody.os, "read", read)
    with pytest.raises(BuildExecutionError, match="custody_input_pin"):
        custody._static_executable(tmp_path, record, lambda: None)
    assert len(mutated) == 1


@pytest.mark.parametrize("change", ["missing", "symlink", "nonexecutable", "role", "size"])
def test_helper_file_must_have_the_original_regular_executable_role(tmp_path, change):
    record = _write(tmp_path, "helper", _elf())
    if change == "missing":
        (tmp_path / "helper").unlink()
    elif change == "symlink":
        (tmp_path / "helper").unlink()
        _write(tmp_path, "other", _elf())
        (tmp_path / "helper").symlink_to("other")
    elif change == "nonexecutable":
        (tmp_path / "helper").chmod(0o444)
    elif change == "role":
        record["executable"] = False
    else:
        record["size"] += 1
    with pytest.raises((BuildExecutionError, OSError)):
        custody._static_executable(tmp_path, record, lambda: None)


def _context(tmp_path, *, snapshot_mounts=False):
    destination = tmp_path / "attempt"
    destination.mkdir()
    roots = {name: tmp_path / name for name in ("source", "toolchain", "work")}
    for root in roots.values():
        root.mkdir()
    inputs = {"source": [_write(roots["source"], "unit.c", b"unit", executable=False)],
              "toolchain": [_write(roots["toolchain"], "zig", _elf())]}
    subject = custody.PodmanCustody(
        destination=destination, prefix=["never-dispatched"], recipe_sha256="a" * 64,
        checkpoint=lambda: None, snapshot_mounts=snapshot_mounts,
    )
    return subject, roots, inputs


def _run(subject, roots, inputs, *, prior=(), index=0):
    subject.run(
        ["@toolchain/zig", "cc"], inputs=inputs,
        snapshots={name: roots[name] for name in ("source", "toolchain")}, prior=list(prior),
        outputs=[], work=roots["work"], environment={}, logs=subject.root,
        evidence={}, stage="configure", index=index,
    )


@pytest.mark.parametrize("snapshot_mounts", [False, True])
@pytest.mark.parametrize("role", ["source", "toolchain", "prior"])
@pytest.mark.parametrize("change", ["script", "interp"])
def test_implicit_helper_refuses_original_run_before_any_daemon_or_command_directory(
    tmp_path, monkeypatch, snapshot_mounts, role, change,
):
    subject, roots, inputs = _context(tmp_path, snapshot_mounts=snapshot_mounts)
    record = _write(roots["work" if role == "prior" else role], "helpers/implicit", _bad_elf(change))
    prior = [record] if role == "prior" else []
    if role != "prior":
        inputs[role].append(record)
    monkeypatch.setattr(subject, "_control", lambda *_args: pytest.fail("daemon was touched"))
    monkeypatch.setattr(subject, "_prepare_image", lambda **_kwargs: pytest.fail("input image was prepared"))
    with pytest.raises(BuildExecutionError, match="custody_static_executable"):
        _run(subject, roots, inputs, prior=prior)
    assert not (subject.root / "configure-0").exists()


@pytest.mark.parametrize("snapshot_mounts", [False, True])
def test_all_actual_helpers_are_checked_before_original_image_dispatch(tmp_path, monkeypatch, snapshot_mounts):
    subject, roots, inputs = _context(tmp_path, snapshot_mounts=snapshot_mounts)
    inputs["source"].append(_write(roots["source"], "helpers/source", _elf()))
    inputs["toolchain"].append(_write(roots["toolchain"], "helpers/driver", _elf()))
    prior = [_write(roots["work"], "bin/generated-freezer", _elf())]
    original, checked = custody._static_executable, []

    def verify(root, record, checkpoint):
        original(root, record, checkpoint)
        checked.append((root, record["path"]))

    def dispatch(**_kwargs):
        assert checked == [(roots["source"], "helpers/source"), (roots["toolchain"], "zig"),
                           (roots["toolchain"], "helpers/driver"), (roots["work"], "bin/generated-freezer")]
        raise _Stop

    monkeypatch.setattr(custody, "_static_executable", verify)
    monkeypatch.setattr(subject, "_prepare_image", dispatch)
    monkeypatch.setattr(subject, "_control", lambda *_args: pytest.fail("daemon was touched"))
    with pytest.raises(_Stop):
        _run(subject, roots, inputs, prior=prior)


def test_each_next_command_rechecks_helper_bytes_without_a_warm_cache(tmp_path, monkeypatch):
    subject, roots, inputs = _context(tmp_path)
    helpers = inputs["toolchain"]
    helpers.append(_write(roots["toolchain"], "helpers/driver", _elf()))
    image_dispatches = []

    def dispatch(**_kwargs):
        image_dispatches.append(None)
        raise _Stop

    monkeypatch.setattr(subject, "_prepare_image", dispatch)
    with pytest.raises(_Stop):
        _run(subject, roots, inputs)
    changed = bytearray(_elf())
    changed[-1] = 1
    (roots["toolchain"] / "helpers/driver").chmod(0o755)
    (roots["toolchain"] / "helpers/driver").write_bytes(changed)
    with pytest.raises(BuildExecutionError, match="custody_input_pin"):
        _run(subject, roots, inputs, index=1)
    assert len(image_dispatches) == 1
    assert not (subject.root / "configure-1").exists()


@pytest.mark.parametrize("boundary", [1, 2, 5])
def test_original_control_refusal_during_helper_acquisition_stops_before_daemon(tmp_path, monkeypatch, boundary):
    subject, roots, inputs = _context(tmp_path)
    checks = []

    def checkpoint():
        checks.append(None)
        if len(checks) == boundary:
            raise _Stop

    subject.checkpoint = checkpoint
    monkeypatch.setattr(subject, "_control", lambda *_args: pytest.fail("daemon was touched"))
    with pytest.raises(_Stop):
        _run(subject, roots, inputs)
    assert len(checks) == boundary
    assert not (subject.root / "configure-0").exists()
