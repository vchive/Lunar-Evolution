"""Original executable ownership; mocked support never proves Linux acceptance.

Linux tests use real source files, memfds, seals and descriptor identities. The
single executed fixture is inert static C, not a Python runtime or an adapter.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target

from lunar_evolution import linux_executable_binding as binding

_LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux executable owner")
_CLEANUP = "linux_execution_cleanup_unknown"
_INVALID = "linux_execution_binding_invalid"
_UNKNOWN = "linux_execution_binding_unknown"
_SEAL_NAMES = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


def _source(tmp_path):
    source = tmp_path / "inert-executable"
    source.write_bytes(b"#!/bin/sh\nexit 0\n" + b"# inert owner bytes\n" * 4000)
    source.chmod(0o755)
    return source


def _pins(source):
    info = source.stat()
    return {
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "size": info.st_size,
        "device": info.st_dev, "inode": info.st_ino,
        "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def _create(source, **changes):
    return binding.sealed_linux_executable(source, _pins(source), **{
        "deadline": time.monotonic() + 30, **changes,
    })


def _verify(live):
    return binding._validate_original_linux_executable(live)


def _refused(call, code):
    with pytest.raises(binding.LinuxExecutableBindingError) as caught:
        call()
    assert caught.value.code == code
    return caught.value


def _enter_only(source, **changes):
    with _create(source, **changes):
        pytest.fail("refused executable must not yield")


def _identity(info):
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _track(monkeypatch, source):
    """Independent fixture acquisitions, without consulting the owner registry."""
    real_open, real_memfd, real_fcntl = os.open, os.memfd_create, binding.fcntl.fcntl
    real_fstat, real_close = os.fstat, os.close
    state = SimpleNamespace(records=[], anchors=[], duplicates=[], source=None)

    def record(role, fd):
        state.records.append((role, fd, _identity(real_fstat(fd))))
        if role == "source":
            state.source = fd
        else:
            getattr(state, role + "s").append(fd)
        return fd

    def opened(path, *args, **kwargs):
        fd = real_open(path, *args, **kwargs)
        return record("source", fd) if Path(path) == source else fd

    def memfd(*args, **kwargs):
        return record("anchor", real_memfd(*args, **kwargs))

    def fcntl(fd, command, *args):
        result = real_fcntl(fd, command, *args)
        return record("duplicate", result) if command == binding.fcntl.F_DUPFD_CLOEXEC else result

    state.real_fstat, state.real_close = real_fstat, real_close
    state.real_memfd = real_memfd
    monkeypatch.setattr(binding.os, "open", opened)
    monkeypatch.setattr(binding.os, "memfd_create", memfd)
    monkeypatch.setattr(binding.fcntl, "fcntl", fcntl)
    return state


def _closed(state):
    for _, fd, _ in state.records:
        with pytest.raises(OSError) as caught:
            state.real_fstat(fd)
        assert caught.value.errno == errno.EBADF


def _release_fixture(state):
    """Clean only this test's independently tracked original objects on failure."""
    for _, fd, original in reversed(state.records):
        try:
            if _identity(state.real_fstat(fd)) == original:
                state.real_close(fd)
        except OSError:
            pass


def _foreign_at(fd, tmp_path, *, sealed=False):
    if sealed:
        foreign = os.memfd_create("foreign-owner-fixture", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        raw = _source(tmp_path).read_bytes()
        os.write(foreign, raw)
        os.fchmod(foreign, 0o755)
        seals = sum(getattr(binding.fcntl, name) for name in _SEAL_NAMES)
        binding.fcntl.fcntl(foreign, binding.fcntl.F_ADD_SEALS, seals)
    else:
        path = tmp_path / "foreign-object"
        path.write_bytes(b"foreign object stays owned by the fixture")
        foreign = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    if foreign != fd:
        os.dup2(foreign, fd, inheritable=False)
        os.close(foreign)
    return fd, _identity(os.fstat(fd))


@pytest.mark.parametrize("deadline", [True, False, float("nan"), float("-inf"), "10"])
def test_invalid_owner_budget_refuses_before_acquisition_with_support_shim(monkeypatch, deadline):
    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid budget acquired or observed source material")

    fake = SimpleNamespace(**{name: 1 << index for index, name in enumerate((
        *_SEAL_NAMES, "F_ADD_SEALS", "F_GET_SEALS", "F_DUPFD_CLOEXEC", "F_GETFD", "FD_CLOEXEC",
    ))})
    monkeypatch.setattr(binding, "fcntl", fake)
    monkeypatch.setattr(binding.sys, "platform", "linux")
    monkeypatch.setattr(binding.os, "memfd_create", forbidden, raising=False)
    monkeypatch.setattr(binding.os, "MFD_ALLOW_SEALING", 2, raising=False)
    monkeypatch.setattr(binding.os, "MFD_CLOEXEC", 1, raising=False)
    monkeypatch.setattr(binding.os, "pread", forbidden, raising=False)
    monkeypatch.setattr(binding.os, "open", forbidden)
    monkeypatch.setattr(binding.Path, "is_dir", lambda _path: True)
    _refused(lambda: _enter_only_with_pins(deadline), _INVALID)


def _enter_only_with_pins(deadline):
    with binding.sealed_linux_executable("missing", {}, deadline=deadline):
        pytest.fail("invalid budget yielded")


@pytest.mark.parametrize("capability", ["host", "memfd", "pread", "duplicate", "seal"])
def test_missing_owner_capability_refuses_before_open(monkeypatch, capability):
    def forbidden(*_args, **_kwargs):
        pytest.fail("unsupported host acquired source material")

    monkeypatch.setattr(binding.os, "open", forbidden)
    if capability == "host":
        monkeypatch.setattr(binding.sys, "platform", "unsupported")
    elif capability in {"memfd", "pread"}:
        monkeypatch.setattr(binding.os, capability + ("_create" if capability == "memfd" else ""),
                            None, raising=False)
    else:
        monkeypatch.delattr(binding.fcntl, "F_DUPFD_CLOEXEC" if capability == "duplicate"
                            else "F_SEAL_WRITE", raising=False)
    with (
        pytest.raises(binding.LinuxExecutableBindingError) as caught,
        binding.sealed_linux_executable("missing", {}, deadline=1),
    ):
        pytest.fail("unsupported binding yielded")
    assert caught.value.code == "linux_execution_binding_unsupported"


@_LINUX
def test_owner_has_one_private_anchor_and_one_borrowed_duplicate(tmp_path, monkeypatch):
    source = _source(tmp_path)
    original = source.read_bytes()
    state = _track(monkeypatch, source)
    try:
        with _create(source) as live:
            assert len(state.anchors) == len(state.duplicates) == 1
            assert live.fd == state.duplicates[0] > 2
            assert live.fd != state.anchors[0]
            assert _verify(live) is None
            for fd in (state.anchors[0], live.fd):
                info = os.fstat(fd)
                assert stat.S_ISREG(info.st_mode) and info.st_nlink == 0
                assert stat.S_IMODE(info.st_mode) == 0o755 and info.st_size == len(original)
                assert binding.fcntl.fcntl(fd, binding.fcntl.F_GETFD) & binding.fcntl.FD_CLOEXEC
                required = sum(getattr(binding.fcntl, name) for name in _SEAL_NAMES)
                assert binding.fcntl.fcntl(fd, binding.fcntl.F_GET_SEALS) & required == required
                assert os.pread(fd, len(original), 0) == original
                with pytest.raises(OSError) as caught:
                    os.write(fd, b"mutation")
                assert caught.value.errno == errno.EPERM
            assert _identity(os.fstat(live.fd)) == _identity(os.fstat(state.anchors[0]))
            assert live.sha256 == hashlib.sha256(original).hexdigest()
            assert live.size == len(original) and live.binding == "linux-sealed-memfd"
            os.lseek(live.fd, 17, os.SEEK_SET)
            assert _verify(live) is None
            assert os.lseek(live.fd, 0, os.SEEK_CUR) == 17
        _closed(state)
        _refused(lambda: _verify(live), _INVALID)
    finally:
        _release_fixture(state)


@_LINUX
@pytest.mark.parametrize("fake", ["constructor", "replace", "number"])
def test_reconstructed_values_do_not_recreate_owner(tmp_path, fake):
    with _create(_source(tmp_path)) as live:
        manufactured = {
            "constructor": lambda: binding.LinuxSealedExecutable(
                live.fd, live.sha256, live.size, live.binding,
            ),
            "replace": lambda: replace(live), "number": lambda: live.fd,
        }[fake]()
        _refused(lambda: _verify(manufactured), _INVALID)
        assert _verify(live) is None


@_LINUX
@pytest.mark.parametrize("field,value", [
    ("fd", -1), ("fd", True), ("sha256", "0" * 64), ("sha256", 1),
    ("size", 1), ("size", True), ("binding", "foreign"), ("binding", 1),
])
def test_forced_public_scalar_mutation_refuses_and_preserves_original_cleanup(
    tmp_path, monkeypatch, field, value,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    try:
        with _create(source) as live:
            object.__setattr__(live, field, value)
            _refused(lambda: _verify(live), _INVALID)
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
def test_public_fd_mutation_does_not_close_unrelated_fixture_fd(tmp_path):
    foreign_path = tmp_path / "foreign"
    foreign_path.write_bytes(b"keep this original unrelated object open")
    foreign = os.open(foreign_path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        with _create(_source(tmp_path)) as live:
            original = live.fd
            object.__setattr__(live, "fd", foreign)
            _refused(lambda: _verify(live), _INVALID)
        with pytest.raises(OSError):
            os.fstat(original)
        assert os.pread(foreign, 4, 0) == b"keep"
    finally:
        os.close(foreign)


@_LINUX
@pytest.mark.parametrize("role", ["borrowed", "anchor"])
@pytest.mark.parametrize("foreign_kind", ["ordinary", "same-byte-sealed"])
def test_known_foreign_numeric_reuse_refuses_and_never_closes_foreign(
    tmp_path, monkeypatch, role, foreign_kind,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    foreign = None
    try:
        with pytest.raises(binding.LinuxExecutableBindingError) as caught, _create(source) as live:
            original_anchor = state.anchors[0]
            target = live.fd if role == "borrowed" else original_anchor
            os.close(target)
            # Avoid tracking the deliberately foreign object as a factory acquisition.
            with monkeypatch.context() as patch:
                patch.setattr(binding.os, "memfd_create", state.real_memfd)
                foreign, identity = _foreign_at(
                    target, tmp_path, sealed=foreign_kind == "same-byte-sealed",
                )
            _refused(lambda: _verify(live), _INVALID)
        assert caught.value.code == _CLEANUP
        assert _identity(os.fstat(foreign)) == identity
        other = original_anchor if role == "borrowed" else live.fd
        with pytest.raises(OSError) as closed:
            os.fstat(other)
        assert closed.value.errno == errno.EBADF
    finally:
        if foreign is not None:
            os.close(foreign)
        _release_fixture(state)


@_LINUX
@pytest.mark.parametrize("defect", ["mode", "cloexec", "size", "seals", "hash", "truncated"])
def test_live_validation_reobserves_actual_image_properties(tmp_path, monkeypatch, defect):
    source = _source(tmp_path)
    with _create(source) as live:
        real_fstat, real_pread, real_fcntl = os.fstat, os.pread, binding.fcntl.fcntl
        with monkeypatch.context() as patch:
            if defect == "mode":
                os.fchmod(live.fd, 0o644)
            elif defect == "cloexec":
                real_fcntl(live.fd, binding.fcntl.F_SETFD, 0)
            elif defect == "size":
                def fstat(fd):
                    info = real_fstat(fd)
                    if fd == live.fd:
                        fields = {name: getattr(info, name) for name in dir(info)
                                  if name.startswith("st_")}
                        fields["st_size"] += 1
                        return SimpleNamespace(**fields)
                    return info
                patch.setattr(binding.os, "fstat", fstat)
            elif defect == "seals":
                def fcntl(fd, command, *args):
                    result = real_fcntl(fd, command, *args)
                    return result & ~binding.fcntl.F_SEAL_SHRINK if (
                        fd == live.fd and command == binding.fcntl.F_GET_SEALS
                    ) else result
                patch.setattr(binding.fcntl, "fcntl", fcntl)
            else:
                def pread(fd, size, offset):
                    raw = real_pread(fd, size, offset)
                    if fd == live.fd and offset == 0:
                        return b"" if defect == "truncated" else bytes([raw[0] ^ 1]) + raw[1:]
                    return raw
                patch.setattr(binding.os, "pread", pread)
            _refused(lambda: _verify(live), _UNKNOWN)
        if defect == "mode":
            os.fchmod(live.fd, 0o755)
        elif defect == "cloexec":
            real_fcntl(live.fd, binding.fcntl.F_SETFD, binding.fcntl.FD_CLOEXEC)
        assert _verify(live) is None


@_LINUX
def test_copy_reads_back_sealed_bytes_instead_of_trusting_input_hash(tmp_path, monkeypatch):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    real_write = os.write

    def corrupted(fd, raw):
        if fd in state.anchors and raw:
            raw = bytes([raw[0] ^ 1]) + raw[1:]
        return real_write(fd, raw)

    monkeypatch.setattr(binding.os, "write", corrupted)
    try:
        _refused(lambda: _enter_only(source), _UNKNOWN)
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
@pytest.mark.parametrize("initially_valid", [True, False])
def test_source_pins_are_snapshotted_once_before_io(tmp_path, monkeypatch, initially_valid):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    expected = _pins(source)
    original_sha = expected["sha256"]
    if not initially_valid:
        expected["sha256"] = "0" * 64
    real_read = os.read
    changed = False

    def read(fd, size):
        nonlocal changed
        raw = real_read(fd, size)
        if fd == state.source and raw and not changed:
            changed = True
            expected["sha256"] = "0" * 64 if initially_valid else original_sha
        return raw

    monkeypatch.setattr(binding.os, "read", read)
    try:
        context = binding.sealed_linux_executable(
            source, expected, deadline=time.monotonic() + 30,
        )
        if initially_valid:
            with context as live:
                assert changed and live.sha256 == original_sha
                assert _verify(live) is None
        else:
            with pytest.raises(binding.LinuxExecutableBindingError) as caught, context:
                pytest.fail("copy-period pin mutation repaired an original wrong SHA")
            assert changed and caught.value.code == "linux_execution_source_changed"
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
def test_real_partial_write_and_pread_keep_exact_image(tmp_path, monkeypatch):
    source = _source(tmp_path)
    real_write, real_pread = os.write, os.pread
    calls = {"write": 0, "pread": 0}

    def partial_write(fd, raw):
        calls["write"] += 1
        return real_write(fd, raw[:1024])

    def partial_pread(fd, size, offset):
        calls["pread"] += 1
        return real_pread(fd, min(size, 1024), offset)

    monkeypatch.setattr(binding.os, "write", partial_write)
    monkeypatch.setattr(binding.os, "pread", partial_pread)
    with _create(source) as live:
        assert _verify(live) is None
        assert live.sha256 == _pins(source)["sha256"]
    assert calls["write"] > 1 and calls["pread"] > 1


def _patch_boundary(monkeypatch, stage, state, callback):
    if stage in {"source-fstat", "anchor-fstat"}:
        real = os.fstat
        selected = state.source if stage == "source-fstat" else None

        def fstat(fd):
            chosen = state.source if stage == "source-fstat" else (
                state.anchors[0] if state.anchors else None
            )
            if fd == chosen:
                callback()
            return real(fd)
        monkeypatch.setattr(binding.os, "fstat", fstat)
        return selected
    commands = {
        "seal": binding.fcntl.F_ADD_SEALS, "seals-read": binding.fcntl.F_GET_SEALS,
        "duplicate": binding.fcntl.F_DUPFD_CLOEXEC,
    }
    if stage in commands:
        real = binding.fcntl.fcntl

        def fcntl(fd, command, *args):
            result = real(fd, command, *args)
            if command == commands[stage]:
                callback()
            return result
        monkeypatch.setattr(binding.fcntl, "fcntl", fcntl)
    else:
        attribute = {"memfd": "memfd_create", "readback": "pread", "seek": "lseek"}.get(
            stage, stage,
        )
        real = getattr(binding.os, attribute)

        def operation(*args, **kwargs):
            result = real(*args, **kwargs)
            callback()
            return result
        monkeypatch.setattr(binding.os, attribute, operation)
    return None


@_LINUX
@pytest.mark.parametrize("stage", ["open", "memfd", "source-fstat", "anchor-fstat", "fchmod",
                                   "read", "write", "fsync", "seal", "seals-read", "seek",
                                   "duplicate", "readback"])
def test_post_operation_deadline_refuses_before_yield_and_still_releases(
    tmp_path, monkeypatch, stage,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    clock = [0.0]
    _patch_boundary(monkeypatch, stage, state, lambda: clock.__setitem__(0, 11.0))
    try:
        _refused(lambda: _enter_only(source, deadline=10.0, monotonic=lambda: clock[0]),
                 "linux_execution_wall_timeout")
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
def test_live_validation_retains_original_clock_and_deadline_after_source_changes(tmp_path):
    source = _source(tmp_path)
    clock = [0.0]
    with _create(source, deadline=10.0, monotonic=lambda: clock[0]) as live:
        source.write_bytes(b"source changes cannot renew or replace the sealed image")
        assert _verify(live) is None
        with pytest.raises(TypeError):
            binding._validate_original_linux_executable(live, deadline=100.0)
        clock[0] = 11.0
        _refused(lambda: _verify(live), "linux_execution_wall_timeout")
    with pytest.raises(OSError):
        os.fstat(live.fd)


@_LINUX
@pytest.mark.parametrize("stage", ["source-fstat", "anchor-fstat", "fchmod", "read", "write",
                                   "fsync", "seal", "readback", "seek"])
@pytest.mark.parametrize("exception_type", [OSError, KeyboardInterrupt, SystemExit])
def test_acquisition_operation_failures_preserve_primary_and_release_remaining_objects(
    tmp_path, monkeypatch, stage, exception_type,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    injected = exception_type("inert owner operation failure")
    fired = False

    def fail_once():
        nonlocal fired
        if not fired:
            fired = True
            raise injected

    _patch_boundary(monkeypatch, stage, state, fail_once)
    try:
        expected = binding.LinuxExecutableBindingError if exception_type is OSError else exception_type
        with pytest.raises(expected) as caught:
            _enter_only(source)
        assert fired
        if exception_type is OSError:
            assert caught.value.code == _UNKNOWN and caught.value.__cause__ is injected
        else:
            assert caught.value is injected
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
@pytest.mark.parametrize("primary_type,release_type", [
    (binding.LinuxExecutableBindingError, OSError),
    (KeyboardInterrupt, OSError), (SystemExit, OSError),
    (binding.LinuxExecutableBindingError, KeyboardInterrupt),
    (binding.LinuxExecutableBindingError, SystemExit),
])
@pytest.mark.parametrize("role", ["borrowed", "anchor"])
def test_cleanup_failure_preserves_same_primary_and_attempts_other_owner(
    tmp_path, monkeypatch, primary_type, release_type, role,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    primary = primary_type("primary-refusal")
    attempts = []
    try:
        with pytest.raises(primary_type) as caught, _create(source) as live:
            victim = live.fd if role == "borrowed" else state.anchors[0]
            other = state.anchors[0] if role == "borrowed" else live.fd
            real_close = os.close

            def close(fd):
                attempts.append(fd)
                if fd == victim:
                    raise release_type("release refused")
                return real_close(fd)

            monkeypatch.setattr(binding.os, "close", close)
            raise primary
        assert caught.value is primary
        assert getattr(primary, "__notes__", []) == [_CLEANUP]
        assert victim in attempts and other in attempts
        with pytest.raises(OSError) as closed:
            state.real_fstat(other)
        assert closed.value.errno == errno.EBADF
        state.real_fstat(victim)
    finally:
        _release_fixture(state)


@_LINUX
@pytest.mark.parametrize("exception_type", [OSError, KeyboardInterrupt, SystemExit])
def test_uncertain_successful_source_close_is_not_retried_and_anchor_is_released(
    tmp_path, monkeypatch, exception_type,
):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    real_close = os.close
    calls = []
    injected = exception_type("source close returned an uncertain result")

    def close(fd):
        calls.append(fd)
        real_close(fd)
        if fd == state.source:
            raise injected

    monkeypatch.setattr(binding.os, "close", close)
    try:
        if exception_type is OSError:
            caught = _refused(lambda: _enter_only(source), _CLEANUP)
            assert caught.__cause__ is injected
        else:
            with pytest.raises(exception_type) as caught:
                _enter_only(source)
            assert caught.value is injected
            assert getattr(injected, "__notes__", []) == [_CLEANUP]
        assert calls.count(state.source) == 1
        assert state.anchors and all(fd in calls for fd in state.anchors)
        _closed(state)
    finally:
        _release_fixture(state)


@_LINUX
def test_closed_original_borrowed_handle_refuses_and_releases_anchor(tmp_path, monkeypatch):
    source = _source(tmp_path)
    state = _track(monkeypatch, source)
    try:
        with pytest.raises(binding.LinuxExecutableBindingError) as caught, _create(source) as live:
            os.close(live.fd)
            _refused(lambda: _verify(live), _INVALID)
        assert caught.value.code == _CLEANUP
        _closed(state)
    finally:
        _release_fixture(state)


_INERT_C = r"""
#define _GNU_SOURCE
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc != 2) return 1;
    int held = atoi(argv[1]);
    struct stat image, running;
    int seals = fcntl(held, F_GET_SEALS);
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    if (held <= 2 || fstat(held, &image) || stat("/proc/self/exe", &running) ||
        !S_ISREG(image.st_mode) || image.st_nlink ||
        image.st_dev != running.st_dev || image.st_ino != running.st_ino ||
        seals < 0 || (seals & required) != required) return 2;
    DIR *directory = opendir("/proc/self/fd");
    if (!directory) return 3;
    int census = dirfd(directory), count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        char *end = NULL;
        long fd = strtol(entry->d_name, &end, 10);
        if (!end || *end || fd <= 2 || fd == census) continue;
        if (fd != held) { closedir(directory); return 4; }
        ++count;
    }
    if (closedir(directory) || count != 1) return 5;
    printf("{\"seals\":%d,\"inherited\":%d,\"size\":%lld}\n", seals, count,
           (long long)image.st_size);
    return 0;
}
"""


@_LINUX
def test_inert_static_image_executes_original_object_with_only_borrowed_fd(
    tmp_path, monkeypatch, record_property,
):
    c_source, image = tmp_path / "inert.c", tmp_path / "inert"
    c_source.write_text(_INERT_C, encoding="ascii")
    compile_native_target(c_source, image)
    original = image.read_bytes()
    state = _track(monkeypatch, image)
    try:
        with _create(image) as live:
            assert _verify(live) is None
            original_identity = _identity(os.fstat(live.fd))
            image.write_bytes(b"mutable pathname must not select a different image")
            result = subprocess.run(
                [live.executable, str(live.fd)], executable=live.executable,
                pass_fds=(live.pass_fd,), close_fds=True,
                env={"PATH": os.defpath, "LANG": "C"}, cwd=tmp_path,
                stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=False,
            )
            assert result.returncode == 0, result.stderr.decode(errors="replace")
            observed = json.loads(result.stdout)
            required = sum(getattr(binding.fcntl, name) for name in _SEAL_NAMES)
            assert observed["seals"] & required == required
            assert observed["size"] == len(original) and observed["inherited"] == 1
            assert _identity(os.fstat(live.fd)) == original_identity
            assert _verify(live) is None
            record_property("original_executable_sha256", hashlib.sha256(original).hexdigest())
            record_property("original_executable_size", len(original))
            record_property("original_executable_seals", observed["seals"])
            record_property("inert_static_inherited_executable_fds", observed["inherited"])
            record_property("runtime_load_protection", False)
            record_property("production_admission", False)
        _closed(state)
    finally:
        _release_fixture(state)
