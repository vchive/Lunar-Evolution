"""Explicit fixture observations, retained failures and original deadline gates."""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_native_guardian_custody as custody_fixture
from _native_target_fixture import compile_native_target

from tools import native_guardian_fault_acceptance as harness

guardian_fault_binaries = custody_fixture.binaries


def test_startup_failure_records_original_children_before_cleanup(tmp_path):
    calls = []

    class Child:
        def __init__(self, name, result):
            self.name, self.result = name, result

        def poll(self):
            calls.append(self.name)
            return self.result

    error = ValueError("private exception text must not be serialized")
    harness._startup_failure(tmp_path, error, Child("target", 2),
                             SimpleNamespace(_watcher=Child("receiver", 79)), 123)
    raw = (tmp_path / "controller-startup-failure.json").read_bytes()
    observed = json.loads(raw)
    assert calls == ["target", "receiver"]
    assert observed["target_returncode"] == 2 and observed["receiver_returncode"] == 79
    assert observed["deadline_monotonic_ns"] == 123 and observed["retries"] == 0
    assert all(observed[key] is False for key in harness._FALSE)
    assert b"private exception" not in raw
    with pytest.raises(FileExistsError):
        harness._create(tmp_path / "controller-startup-failure.json", b"replacement")


@pytest.mark.parametrize("persist_failure", [False, True])
def test_startup_observation_failure_never_masks_startup_error(tmp_path, monkeypatch, persist_failure):
    class Child:
        def poll(self):
            raise OSError("private poll failure")

    error = ValueError("original")
    if persist_failure:
        monkeypatch.setattr(harness, "_save", lambda *a: (_ for _ in ()).throw(OSError()))
    harness._startup_failure(tmp_path, error, Child(), None, 123)
    if persist_failure:
        assert error.__notes__ == ["fixture_startup_observation_persistence_OSError"]
    else:
        observed = json.loads((tmp_path / "controller-startup-failure.json").read_bytes())
        assert observed["target_returncode"] is None and observed["receiver_returncode"] is None
        assert observed["target_observation_error"] == "OSError"


@pytest.fixture(scope="module")
def guardian_fault_target_profile(tmp_path_factory):
    # Explicit trusted-local setup, never inferred from a failed installed
    # image. The compiler/image relationship is not a build attestation.
    source = harness._nanosleep_source_pin()
    image = tmp_path_factory.mktemp("guardian-inert-target") / "nanosleep-fixture"
    compile_native_target(harness._NANOSLEEP_SOURCE, image)
    assert harness._nanosleep_source_pin() == source
    return {"target_profile": harness._NANOSLEEP_PROFILE, "fixture_target": image,
            "fixture_target_sha256": harness._pin(image, elf=True)["sha256"]}


def test_sleep_profiles_are_finite_explicit_paths_without_link_resolution():
    assert harness._target_path("system-sleep") == Path("/usr/bin/sleep")
    with pytest.raises(ValueError, match="fixture_target_profile_sealed_incompatible"):
        harness._target_path("ubuntu-uutils-sleep")
    assert harness._target_path(harness._NANOSLEEP_PROFILE, fixture_target=Path("/explicit/image"),
                                fixture_target_sha256="a" * 64) == Path("/explicit/image")
    with pytest.raises(ValueError, match="fixture_target_profile_invalid"):
        harness._target_path("/arbitrary/target")


@pytest.mark.parametrize("profile,name", [("system-sleep", "sleep"),
    (harness._NANOSLEEP_PROFILE, "lunar-guardian-nanosleep-fixture")])
def test_target_uses_fixed_argv0_single_duration_and_original_sealed_executable(monkeypatch, profile, name):
    calls = []
    original = SimpleNamespace(executable="/proc/self/fd/17", fd=17)
    child = object()

    def start(argv, **kwargs):
        calls.append((argv, kwargs))
        return child

    monkeypatch.setattr(harness.time, "monotonic_ns", lambda: 12_000_000_000)
    monkeypatch.setattr(harness.subprocess, "Popen", start)
    assert harness._start_target(original, 13_000_000_000, target_profile=profile) is child
    assert calls == [([name, "1.0"], {
        "executable": original.executable, "pass_fds": (original.fd,),
        "close_fds": True, "start_new_session": True, "cwd": "/",
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL, "env": {"PATH": os.defpath, "LANG": "C"},
    })]


def test_root_owned_image_pin_refuses_non_root_owned_image(tmp_path, monkeypatch):
    image = tmp_path / "sleep"
    image.write_bytes(b"\x7fELFfixture-only-no-execution")
    image.chmod(0o700)
    actual_fstat = harness.os.fstat

    def non_root(fd):
        info = actual_fstat(fd)
        return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size, st_uid=2110)

    monkeypatch.setattr(harness.os, "fstat", non_root)
    with pytest.raises(ValueError, match="installed_fixture_root_owner_required"):
        harness._pin(image, elf=True, root_owned=True)


@pytest.mark.parametrize("profile,path,digest", [
    (harness._NANOSLEEP_PROFILE, None, None),
    (harness._NANOSLEEP_PROFILE, "relative/image", "a" * 64),
    (harness._NANOSLEEP_PROFILE, "/explicit/image", None),
    (harness._NANOSLEEP_PROFILE, "/explicit/image", "A" * 64),
    (harness._NANOSLEEP_PROFILE, "/explicit/image", "a" * 63),
    ("system-sleep", "/explicit/image", "a" * 64),
])
def test_fixture_configuration_refuses_before_output_or_dispatch(tmp_path, monkeypatch, profile, path, digest):
    receiver, guardian, _ = _fake_images(tmp_path, monkeypatch)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected dispatch"))
    output = tmp_path / "retained"
    with pytest.raises(ValueError, match="fixture_target_profile_configuration_invalid"):
        harness.run(output=output, receiver=receiver, guardian=guardian,
                    fault="controller-exit", budget_seconds=5, target_profile=profile,
                    fixture_target=path, fixture_target_sha256=digest)
    assert not output.exists()


def test_uutils_profile_refuses_before_output_and_never_falls_back(tmp_path, monkeypatch):
    receiver, guardian, _ = _fake_images(tmp_path, monkeypatch)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected dispatch"))
    output = tmp_path / "retained"
    with pytest.raises(ValueError, match="fixture_target_profile_sealed_incompatible"):
        harness.run(output=output, receiver=receiver, guardian=guardian,
                    fault="controller-exit", budget_seconds=5, target_profile="ubuntu-uutils-sleep")
    assert not output.exists()


@pytest.mark.parametrize("drift", ["source", "image"])
def test_compiled_fixture_pin_failure_retains_failure_without_dispatch(tmp_path, monkeypatch, drift):
    receiver, guardian, image = _fake_images(tmp_path, monkeypatch)
    digest = harness._pin(image, elf=True)["sha256"]
    if drift == "source":
        source = tmp_path / "changed-source.c"
        source.write_bytes(harness._NANOSLEEP_SOURCE.read_bytes() + b"\n")
        monkeypatch.setattr(harness, "_NANOSLEEP_SOURCE", source)
    else:
        digest = "0" * 64
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected dispatch"))
    output = tmp_path / "retained"
    result = harness.run(output=output, receiver=receiver, guardian=guardian,
                         fault="controller-exit", budget_seconds=5,
                         target_profile=harness._NANOSLEEP_PROFILE,
                         fixture_target=image, fixture_target_sha256=digest)
    expected = "fixture_nanosleep_source_invalid" if drift == "source" else "fixture_nanosleep_image_digest_mismatch"
    assert result["error_reason"] == expected and result["fixture_observed"] is False
    assert all(result[key] is False for key in harness._FALSE)
    assert not (output / "request.json").exists() and not (output / "sleep-image").exists()
    assert (output / "result.json").exists() and (output / "evidence-manifest.json").exists()


def _report(state="watcher_exit_observed"):
    return {"state": state, "cleanup_status": "unknown", "native_d_observed": False,
            "watcher_exit_kind": 1, "watcher_exit_value": 78,
            **{key: False for key in harness._FALSE}}


def _pins():
    return {"guardian-registration-v1.json": {"sha256": "a" * 64, "size": 123},
            "guardian-event-v1.json": {"sha256": "b" * 64, "size": 123}}


@pytest.mark.parametrize("value", [True, "nan", "inf", "-inf", "4.9", "60.01", "0"])
def test_invalid_budget_refuses_before_any_process(value):
    with pytest.raises(argparse.ArgumentTypeError):
        harness._budget(value)


def test_cli_needs_explicit_fault_images_output_and_budget(monkeypatch):
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("implicit process"))
    with pytest.raises(SystemExit) as failure:
        harness.main(["run", "--fault", "controller-exit"])
    assert failure.value.code == 2


def test_create_only_keeps_prior_original_and_partial_failed_write(tmp_path, monkeypatch):
    path = tmp_path / "original"
    harness._create(path, b"retained")
    with pytest.raises(FileExistsError):
        harness._create(path, b"replacement")
    assert path.read_bytes() == b"retained"
    original_write = os.write
    writes = []

    def partial(fd, raw):
        writes.append(bytes(raw))
        if len(writes) == 1:
            return original_write(fd, raw[:3])
        raise OSError("fixture write failure")

    monkeypatch.setattr(harness.os, "write", partial)
    with pytest.raises(OSError):
        harness._create(tmp_path / "partial", b"abcdef")
    assert (tmp_path / "partial").read_bytes() == b"abc"
    assert len(writes) == 2


def test_pin_refuses_symlink_fifo_and_env_without_reading(tmp_path):
    original = tmp_path / "original"
    original.write_bytes(b"content")
    alias = tmp_path / "alias"
    alias.symlink_to(original)
    with pytest.raises(OSError):
        harness._pin(alias)
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="fixture_file_invalid"):
        harness._pin(fifo)
    with pytest.raises(ValueError, match="fixture_file_path_invalid"):
        harness._pin(tmp_path / ".env")


@pytest.mark.parametrize("drift", [False, True])
def test_reference_pipe_retains_exact_bytes_and_rejects_a_changed_deadline(drift):
    deadline = time.monotonic_ns() + 5_000_000_000
    raw = harness._wire({"deadline_monotonic_ns": deadline + int(drift)})
    read_fd, write_fd = os.pipe()
    captured = bytearray()
    try:
        os.write(write_fd, raw + b"\n")
        os.close(write_fd)
        write_fd = None
        with os.fdopen(read_fd, "rb", buffering=0) as reader:
            child = SimpleNamespace(stdout=reader)
            if drift:
                with pytest.raises(ValueError, match="original_reference_invalid"):
                    harness._read_reference(child, deadline, captured)
            else:
                assert harness._read_reference(child, deadline, captured) == raw
        assert captured == raw + b"\n"
    finally:
        if write_fd is not None:
            os.close(write_fd)


def test_controller_exit_is_only_local_observation_with_unknown_cleanup():
    controller = {"returncode": 79, "timed_out": False}
    result = harness._classify("controller-exit", controller, _report(), 0, _pins(), _pins())
    assert result["fixture_observed"] is True
    assert result["status"] == "fixture_observed"
    assert result["cleanup_status"] == result["execution_status"] == "unknown"
    assert all(result[key] is False for key in harness._FALSE)


@pytest.mark.parametrize("change", ["timeout", "clean-exit", "native-d", "wrong-exit",
                                    "cleanup-promotion", "missing-authority", "reader-failed",
                                    "changed-original", "missing-original", "unknown-fault"])
def test_missing_or_promoted_facts_never_pass(change):
    controller = {"returncode": 79, "timed_out": False}
    report, before, after, reader_status, fault = _report(), _pins(), _pins(), 0, "controller-exit"
    if change == "timeout":
        controller["timed_out"] = True
    elif change == "clean-exit":
        controller["returncode"] = 0
    elif change == "native-d":
        report["native_d_observed"] = True
    elif change == "wrong-exit":
        report["watcher_exit_value"] = 0
    elif change == "cleanup-promotion":
        report["cleanup_authority"] = True
    elif change == "missing-authority":
        report.pop("production_admission")
    elif change == "reader-failed":
        reader_status = 1
    elif change == "changed-original":
        after["guardian-event-v1.json"]["sha256"] = "c" * 64
    elif change == "missing-original":
        before = after = {}
    elif change == "unknown-fault":
        fault = "other"
    result = harness._classify(fault, controller, report, reader_status, before, after)
    assert result["fixture_observed"] is False
    assert all(result[key] is False for key in harness._FALSE)


def test_receiver_kill_never_becomes_a_native_exit_or_cleanup_acknowledgement():
    controller = {"returncode": 0, "timed_out": False}
    child = {"receiver_returncode": -signal.SIGKILL, "owner_cleanup_returned": False}
    result = harness._classify("receiver-kill", controller, _report("registered"),
                               0, _pins(), _pins(), child)
    assert result["fixture_observed"] is True
    assert all(result[key] is False for key in harness._FALSE)
    child["owner_cleanup_returned"] = True
    assert harness._classify("receiver-kill", controller, _report("registered"),
                              0, _pins(), _pins(), child)["fixture_observed"] is False


def test_timeout_kills_only_exact_child_without_renewing_wait_budget(monkeypatch):
    calls = []

    class Child:
        returncode = None

        def communicate(self, *, input=None, timeout):
            calls.append((input, timeout))
            raise subprocess.TimeoutExpired(["owned fixture"], timeout, output=b"partial", stderr=b"err")

        def poll(self):
            return None

        def kill(self):
            calls.append("kill-original")

    instants = iter((12_000_000_000, 13_000_000_000))
    monkeypatch.setattr(harness.time, "monotonic_ns", lambda: next(instants))
    stdout, stderr, result = harness._communicate(Child(), 13_000_000_000, trigger=b"G")
    assert calls == [(b"G", 1.0), "kill-original", (None, 0)]
    assert stdout == b"partial" and stderr == b"err"
    assert result == {"returncode": None, "timed_out": True}


def _fake_images(tmp_path, monkeypatch):
    images = []
    for role in ("receiver", "guardian", "sleep"):
        path = tmp_path / role
        path.write_bytes(b"\x7fELFfixture-only-no-execution")
        path.chmod(0o700)
        images.append(path)
    monkeypatch.setattr(harness, "_TARGET", images[2])
    monkeypatch.setattr(harness.sys, "platform", "linux")
    monkeypatch.setattr(harness.os, "pidfd_open", lambda *a: pytest.fail("contract test opened pidfd"),
                        raising=False)
    return images


def test_sleep_snapshot_keeps_verified_bytes_in_a_fresh_single_link_inode(tmp_path):
    source = tmp_path / "installed-sleep"
    source.write_bytes(b"\x7fELFfixture-only-no-execution")
    source.chmod(0o700)
    (tmp_path / "installed-alias").hardlink_to(source)
    identity = harness._pin(source, elf=True)
    snapshot = tmp_path / "sleep-image"
    copied = harness._snapshot_sleep_image(
        source, identity, snapshot, root_owned=False,
        deadline_ns=time.monotonic_ns() + 5_000_000_000,
    )
    assert source.stat().st_nlink == 2 and snapshot.stat().st_nlink == 1
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o700
    assert source.read_bytes() == snapshot.read_bytes()
    assert copied == harness._pin(snapshot, elf=True)
    assert (copied["device"], copied["inode"]) != (identity["device"], identity["inode"])
    assert harness._pin(source, elf=True) == identity
    with pytest.raises(FileExistsError):
        harness._snapshot_sleep_image(
            source, identity, snapshot, root_owned=False,
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
        )
    assert source.read_bytes() == snapshot.read_bytes()


@pytest.mark.parametrize("drift", ["bytes", "inode"])
def test_sleep_snapshot_refuses_changed_original_pin_before_creating_output(tmp_path, drift):
    source = tmp_path / "installed-sleep"
    original = b"\x7fELFfixture-only-no-execution"
    source.write_bytes(original)
    source.chmod(0o700)
    identity = harness._pin(source, elf=True)
    if drift == "bytes":
        source.write_bytes(original + b"changed")
    else:
        replacement = tmp_path / "replacement"
        replacement.write_bytes(original)
        replacement.chmod(0o700)
        replacement.replace(source)
    snapshot = tmp_path / "sleep-image"
    with pytest.raises(ValueError, match="installed_fixture_image_drift"):
        harness._snapshot_sleep_image(
            source, identity, snapshot, root_owned=False,
            deadline_ns=time.monotonic_ns() + 5_000_000_000,
        )
    assert not snapshot.exists()


def test_sleep_snapshot_fsync_and_close_failures_preserve_primary_and_partial_image(tmp_path, monkeypatch):
    receiver, guardian, target = _fake_images(tmp_path, monkeypatch)
    output = tmp_path / "retained"
    snapshot = output / "sleep-image"
    actual_fsync, actual_close = os.fsync, os.close
    close_failed = False

    def same_image(fd):
        return snapshot.exists() and os.fstat(fd).st_ino == snapshot.stat().st_ino

    def fsync(fd):
        if same_image(fd):
            raise OSError(errno.ENOSPC, "fixture primary fsync failure")
        return actual_fsync(fd)

    def close(fd):
        nonlocal close_failed
        fail = not close_failed and same_image(fd)
        actual_close(fd)
        if fail:
            close_failed = True
            raise OSError(errno.EIO, "fixture secondary close failure")

    monkeypatch.setattr(harness.os, "fsync", fsync)
    monkeypatch.setattr(harness.os, "close", close)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected dispatch"))
    result = harness.run(output=output, receiver=receiver, guardian=guardian,
                         fault="controller-exit", budget_seconds=5)
    assert result["error_phase"] == "snapshot-sleep" and result["error_errno"] == errno.ENOSPC
    assert result["io_cleanup_errors"] == [
        {"operation": "create.close", "error_kind": "OSError", "error_errno": errno.EIO}]
    assert result["fixture_observed"] is False and all(result[key] is False for key in harness._FALSE)
    assert snapshot.read_bytes() == target.read_bytes()
    assert not (output / "request.json").exists()
    manifest = json.loads((output / "evidence-manifest.json").read_bytes())
    assert manifest["sleep-image"] == harness._pin(snapshot)


@pytest.mark.parametrize("failure", [OSError(errno.EIO, "primary read failure"), KeyboardInterrupt()])
def test_source_read_and_close_failure_keep_the_original_exception(tmp_path, monkeypatch, failure):
    source = tmp_path / "installed-sleep"
    source.write_bytes(b"\x7fELFfixture-only-no-execution")
    source.chmod(0o700)
    actual_close = os.close

    def read(fd, size):
        raise failure

    def close(fd):
        actual_close(fd)
        raise OSError(errno.EBADF, "secondary close failure")

    monkeypatch.setattr(harness.os, "read", read)
    monkeypatch.setattr(harness.os, "close", close)
    with pytest.raises(type(failure)) as captured:
        harness._pin(source, elf=True, include_bytes=True)
    assert captured.value is failure
    assert failure._fixture_close_errors == [
        {"operation": "pin.close", "error_kind": "OSError", "error_errno": errno.EBADF}]


def test_default_sleep_symlink_retains_errno_and_never_selects_another_image(tmp_path, monkeypatch):
    receiver, guardian, target = _fake_images(tmp_path, monkeypatch)
    alias = tmp_path / "system-sleep"
    alias.symlink_to(target)
    monkeypatch.setattr(harness, "_TARGET", alias)
    monkeypatch.setattr(harness.subprocess, "Popen", lambda *a, **k: pytest.fail("unexpected dispatch"))
    output = tmp_path / "retained"
    result = harness.run(output=output, receiver=receiver, guardian=guardian,
                         fault="controller-exit", budget_seconds=5)
    assert result["error_kind"] == "OSError" and result["error_errno"] == errno.ELOOP
    assert result["target_profile"] == "system-sleep" and result["fixture_observed"] is False
    assert all(result[key] is False for key in harness._FALSE)
    assert sorted(p.name for p in output.iterdir()) == ["custody", "evidence-manifest.json", "result.json"]


def _mock_coordinator(tmp_path, monkeypatch, *, expire_after_classification=False,
                      fail_reference=False, reader_fault=None, reader_fsync_failure=False,
                      compiled_fixture=False):
    receiver, guardian, target = _fake_images(tmp_path, monkeypatch)
    target_options = ({"target_profile": harness._NANOSLEEP_PROFILE, "fixture_target": target,
                       "fixture_target_sha256": harness._pin(target, elf=True)["sha256"]}
                      if compiled_fixture else {})
    output, launches = tmp_path / "retained", []
    recovery = _report()
    expired = False
    actual_remaining, actual_classify = harness._remaining, harness._classify
    actual_fsync = os.fsync

    def fsync(fd):
        path = output / "read-only-recovery.stdout"
        if (reader_fsync_failure and path.exists()
                and os.fstat(fd).st_ino == path.stat().st_ino):
            raise OSError("fixture reader output fsync failure")
        return actual_fsync(fd)

    def remaining(deadline):
        if expired:
            raise TimeoutError("original_fixture_deadline")
        return actual_remaining(deadline)

    def classify(*args, **kwargs):
        nonlocal expired
        result = actual_classify(*args, **kwargs)
        expired = expire_after_classification
        return result

    class Child:
        returncode = 79

        def __init__(self, command, **kwargs):
            self.reader = command[-2] == "_inspect"
            self.request = json.loads(Path(command[-1]).read_bytes())
            self.communications = 0
            self.kills = 0
            self.timeouts = []
            launches.append(self)
            assert kwargs["env"] == {"PATH": os.defpath, "LANG": "C",
                                     "PYTHONDONTWRITEBYTECODE": "1"}
            if self.reader:
                self.returncode = None
                self.output = kwargs["stdout"]
                self.error = kwargs["stderr"]

        def communicate(self, *, input=None, timeout):
            self.communications += 1
            self.timeouts.append(timeout)
            assert 0 < timeout <= 5
            if self.reader:
                assert input is None
                if self.communications == 1:
                    if reader_fault is not None:
                        self.output.write(b"retained partial recovery output")
                        self.error.write(b"retained reader diagnostic")
                        raise reader_fault("fixture reader communication failed")
                    self.output.write(harness._wire(recovery))
                    self.returncode = 0
                return None, None
            if fail_reference:
                return b"suffix", b"retained startup error"
            assert input == b"G"
            retained = (output / "original-reference.json").read_bytes()
            assert json.loads(retained)["deadline_monotonic_ns"] == self.request["deadline_monotonic_ns"]
            for name in ("guardian-registration-v1.json", "guardian-event-v1.json"):
                (output / "custody" / name).write_bytes(b"original fixture bytes")
            return b"", b"original controller stderr"

        def poll(self):
            return self.returncode

        def kill(self):
            assert self.reader and self.returncode is None
            self.kills += 1
            self.returncode = -signal.SIGKILL

    def reference(child, deadline, captured):
        if fail_reference:
            captured.extend(b"retained-partial-")
            raise ValueError("original_reference_missing")
        raw = harness._wire({"deadline_monotonic_ns": deadline})
        captured.extend(raw + b"\n")
        return raw

    monkeypatch.setattr(harness.subprocess, "Popen", Child)
    monkeypatch.setattr(harness, "_read_reference", reference)
    monkeypatch.setattr(harness, "_remaining", remaining)
    monkeypatch.setattr(harness, "_classify", classify)
    monkeypatch.setattr(harness.os, "fsync", fsync)
    result = harness.run(output=output, receiver=receiver, guardian=guardian,
                         fault="controller-exit", budget_seconds=5, **target_options)
    return result, output, launches


def test_one_dispatch_retains_original_before_trigger_and_fresh_read_is_unchanged(tmp_path, monkeypatch):
    result, output, launches = _mock_coordinator(tmp_path, monkeypatch)
    assert result["fixture_observed"] is True
    assert len(launches) == 2 and [child.reader for child in launches] == [False, True]
    assert launches[0].request == launches[1].request
    assert result["deadline_monotonic_ns"] == launches[0].request["deadline_monotonic_ns"]
    assert (output / "controller.stderr").read_bytes() == b"original controller stderr"
    manifest = json.loads((output / "evidence-manifest.json").read_bytes())
    for relative, pin in manifest.items():
        assert harness._pin(output / relative) == pin
    assert (output / "custody-before-read.json").read_bytes() == (output / "custody-after-read.json").read_bytes()
    with pytest.raises(FileExistsError):
        harness.run(output=output, receiver=tmp_path / "receiver", guardian=tmp_path / "guardian",
                    fault="controller-exit", budget_seconds=5)
    assert len(launches) == 2  # no redispatch into even an apparently successful directory


def test_expiry_after_observation_does_not_leave_a_successful_projection(tmp_path, monkeypatch):
    result, output, _ = _mock_coordinator(tmp_path, monkeypatch, expire_after_classification=True)
    assert result["fixture_observed"] is False and result["timed_out"] is True
    assert json.loads((output / "result.json").read_bytes())["fixture_observed"] is False
    assert (output / "read-only-recovery.stdout").exists()


def test_failed_controller_before_reference_preserves_partial_and_error_without_reader(tmp_path, monkeypatch):
    result, output, launches = _mock_coordinator(tmp_path, monkeypatch, fail_reference=True)
    assert result["fixture_observed"] is False and len(launches) == 1
    assert result["error_phase"] == "controller"
    assert result["error_reason"] == "original_reference_missing"
    assert (output / "failed-controller.stdout").read_bytes() == b"retained-partial-suffix"
    assert (output / "failed-controller.stderr").read_bytes() == b"retained startup error"
    assert not (output / "original-reference.json").exists()
    assert (output / "evidence-manifest.json").exists()


def test_controller_request_cannot_replace_the_selected_finite_target_path(tmp_path, monkeypatch):
    _, output, _ = _mock_coordinator(tmp_path, monkeypatch)
    request = json.loads((output / "request.json").read_bytes())
    request["target_source"]["path"] = "/different/installed/image"
    supplied = tmp_path / "changed-request.json"
    supplied.write_bytes(harness._wire(request))
    with pytest.raises(ValueError, match="fixture_target_profile_path_invalid"):
        harness._request(supplied)


def test_compiled_fixture_retains_original_source_and_image_pins_without_authenticity_claim(tmp_path, monkeypatch):
    result, output, launches = _mock_coordinator(tmp_path, monkeypatch, compiled_fixture=True)
    request = json.loads((output / "request.json").read_bytes())
    assert result["fixture_observed"] is True and len(launches) == 2
    assert harness._request(output / "request.json") == request
    assert request["target_profile"] == harness._NANOSLEEP_PROFILE
    assert request["fixture_target"] == request["target_source"]["path"]
    assert request["fixture_target_sha256"] == request["target_source"]["identity"]["sha256"]
    assert request["fixture_source"] == {
        "path": str(harness._NANOSLEEP_SOURCE), "identity": harness._nanosleep_source_pin(),
        "build_authenticity_verified": False,
    }
    assert request["images"]["target"]["identity"]["inode"] != request["target_source"]["identity"]["inode"]
    assert all(result[key] is False for key in harness._FALSE)


@pytest.mark.parametrize("change", ["digest", "source-path", "source-pin", "source-missing", "promoted-build"])
def test_compiled_fixture_controller_refuses_original_metadata_drift(tmp_path, monkeypatch, change):
    _, output, _ = _mock_coordinator(tmp_path, monkeypatch, compiled_fixture=True)
    request = json.loads((output / "request.json").read_bytes())
    reason = "fixture_nanosleep_source_invalid"
    if change == "digest":
        request["fixture_target_sha256"] = "0" * 64
        reason = "fixture_nanosleep_image_digest_mismatch"
    elif change == "source-path":
        request["fixture_source"]["path"] = "/different/source.c"
    elif change == "source-pin":
        request["fixture_source"]["identity"]["sha256"] = "0" * 64
    elif change == "source-missing":
        request.pop("fixture_source")
    else:
        request["fixture_source"]["build_authenticity_verified"] = True
    supplied = tmp_path / "changed-request.json"
    supplied.write_bytes(harness._wire(request))
    with pytest.raises(ValueError, match=reason):
        harness._request(supplied)


@pytest.mark.parametrize("change", ["path", "bytes", "same-inode"])
def test_controller_request_binds_independent_image_to_original_source_bytes(tmp_path, monkeypatch, change):
    _, output, _ = _mock_coordinator(tmp_path, monkeypatch)
    request = json.loads((output / "request.json").read_bytes())
    assert harness._request(output / "request.json") == request
    source = Path(request["target_source"]["path"])
    image = Path(request["images"]["target"]["path"])
    reason = "fixture_sleep_snapshot_invalid"
    if change == "path":
        request["images"]["target"] = dict(request["target_source"])
        reason = "fixture_target_profile_path_invalid"
    elif change == "bytes":
        image.write_bytes(b"\x7fELFchanged image")
        request["images"]["target"]["identity"] = harness._pin(image, elf=True)
    else:
        image.unlink()
        image.hardlink_to(source)
        request["target_source"]["identity"] = harness._pin(source, elf=True)
        request["images"]["target"]["identity"] = harness._pin(image, elf=True)
    changed = tmp_path / "changed-image-request.json"
    changed.write_bytes(harness._wire(request))
    with pytest.raises(ValueError, match=reason):
        harness._request(changed)


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt])
@pytest.mark.parametrize("fsync_failure", [False, True])
def test_reader_communication_failure_retires_exact_owner_and_retains_raw_files(
    tmp_path, monkeypatch, failure, fsync_failure,
):
    output = tmp_path / "retained"
    if failure is KeyboardInterrupt:
        with pytest.raises(KeyboardInterrupt):
            _mock_coordinator(tmp_path, monkeypatch, reader_fault=failure,
                              reader_fsync_failure=fsync_failure)
        result = json.loads((output / "result.json").read_bytes())
        # The retained result is still written before the interrupt propagates.
        assert result["interrupted"] is True
    else:
        result, _, launches = _mock_coordinator(tmp_path, monkeypatch, reader_fault=failure,
                                              reader_fsync_failure=fsync_failure)
        assert len(launches) == 2
        reader = launches[1]
        assert reader.kills == 1 and reader.communications == 2
        assert reader.timeouts[1] <= reader.timeouts[0]
        assert reader.request["deadline_monotonic_ns"] == result["deadline_monotonic_ns"]
        assert reader.output.closed and reader.error.closed
    assert result["fixture_observed"] is False
    assert result["error_kind"] == failure.__name__
    if fsync_failure:
        assert result["reader_output_persistence_errors"] == [
            {"phase": "fsync", "error_kind": "OSError"}]
    assert result["cleanup_status"] == result["execution_status"] == "unknown"
    assert (output / "read-only-recovery.stdout").read_bytes() == b"retained partial recovery output"
    assert (output / "read-only-recovery.stderr").read_bytes() == b"retained reader diagnostic"
    retirement = json.loads((output / "failed-read-only-recovery-result.json").read_bytes())
    assert retirement["returncode"] == -signal.SIGKILL
    assert retirement["cleanup_status"] == "unknown"
    assert retirement["deadline_monotonic_ns"] == result["deadline_monotonic_ns"]
    assert retirement["retries"] == result["retries"] == 0
    assert (output / "evidence-manifest.json").exists()


def test_reader_stream_failures_close_every_original_without_masking_first_error(monkeypatch):
    calls = []

    class Stream:
        def __init__(self, fd):
            self.fd = fd

        def fileno(self):
            return self.fd

        def close(self):
            calls.append(("close", self.fd))
            if self.fd == 1:
                raise OSError("first close also failed")

    def fsync(fd):
        calls.append(("fsync", fd))
        if fd == 1:
            raise OSError("first fsync failed")

    monkeypatch.setattr(harness.os, "fsync", fsync)
    errors = harness._close_reader_streams([Stream(1), Stream(2)])
    assert calls == [("fsync", 1), ("close", 1), ("fsync", 2), ("close", 2)]
    assert errors == [{"phase": "fsync", "error_kind": "OSError"},
                      {"phase": "close", "error_kind": "OSError"}]


def test_reader_retirement_after_expiry_never_allocates_a_new_reap_budget(monkeypatch):
    calls = []

    class Reader:
        def poll(self):
            return None

        def kill(self):
            calls.append("kill-exact-reader")

        def communicate(self, *, timeout):
            calls.append(timeout)
            raise subprocess.TimeoutExpired(["owned reader"], timeout)

    monkeypatch.setattr(harness.time, "monotonic_ns", lambda: 13_000_000_000)
    result = harness._retire_reader(Reader(), 12_000_000_000)
    assert calls == ["kill-exact-reader", 0]
    assert result["returncode"] is None and result["cleanup_status"] == "unknown"
    assert result["retirement_error_kind"] == "TimeoutExpired"


@pytest.mark.skipif(sys.platform != "linux", reason="actual same-UID Linux native guardian fixture")
@pytest.mark.parametrize("fault", harness._FAULTS)
def test_actual_same_uid_fault_retains_original_for_readonly_recovery(
    tmp_path, guardian_fault_binaries, guardian_fault_target_profile, fault,
):
    # Reuse the existing real native receiver/bootstrap compiler fixture rather
    # than inventing installed credentials, attestation or an alternate guardian.
    installed = guardian_fault_binaries
    output = tmp_path / fault
    report = harness.run(output=output, receiver=installed.receiver, guardian=installed.guardian,
                         fault=fault, budget_seconds=20,
                         **guardian_fault_target_profile)
    assert report["fixture_observed"] is True, (output / "result.json").read_text()
    assert report["target_profile"] == guardian_fault_target_profile["target_profile"]
    request = json.loads((output / "request.json").read_bytes())
    assert request["fixture_target_sha256"] == guardian_fault_target_profile["fixture_target_sha256"]
    assert request["fixture_source"]["build_authenticity_verified"] is False
    assert report["cleanup_status"] == report["execution_status"] == "unknown"
    assert all(report[key] is False for key in harness._FALSE)
    original = (output / "original-reference.json").read_bytes()
    assert hashlib.sha256(original).hexdigest() == json.loads(
        (output / "evidence-manifest.json").read_bytes())["original-reference.json"]["sha256"]
    assert (output / "custody-before-read.json").read_bytes() == (output / "custody-after-read.json").read_bytes()
    assert report["deadline_monotonic_ns"] == json.loads(original)["deadline_monotonic_ns"]
