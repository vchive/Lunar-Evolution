"""Actual native-attempt opt-in pairing; no installed-account acceptance."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target
from test_native_trusted_attempt import _attempt

from lunar_evolution import native_guardian_registration as pairing
from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.linux_executable_binding import (
    LinuxExecutableBindingError,
    sealed_linux_executable,
)
from lunar_evolution.native_guardian_custody import native_guardian_receiver_source_path
from lunar_evolution.native_guardian_registration import (
    GuardianNativeRegistrationReference,
    NativeGuardianCustodyRequest,
    inspect_registered_native_guardian_custody,
)
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux native registration/receiver")
_NAME = "guardian-native-registration-v1.json"


@pytest.fixture(scope="module")
def receiver(tmp_path_factory):
    path = tmp_path_factory.mktemp("native-pairing") / "receiver"
    compile_native_target(native_guardian_receiver_source_path(), path)
    return path


@contextmanager
def _request(prepared, root, receiver):
    _workspace, _producer_root, intent, attestation, artifact, _batch = prepared
    directory = root / "guardian-custody"
    directory.mkdir(mode=0o700)
    chain = DirectoryChain(directory, "original guardian pairing fixture directory")
    info = receiver.stat()
    identity = {"sha256": hashlib.sha256(receiver.read_bytes()).hexdigest(), "size": info.st_size,
                "device": info.st_dev, "inode": info.st_ino,
                "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    launch = build_trusted_bootstrap_launch(intent, attestation, artifact.descriptor)
    try:
        with sealed_linux_executable(receiver, identity, deadline=time.monotonic() + 20) as original:
            request = NativeGuardianCustodyRequest(
                receiver=original, original_directory=directory, original_directory_chain=chain,
                original_context_sha256="a" * 64, original_launch_sha256=launch.launch_sha256,
                original_profile_sha256="b" * 64,
            )
            yield request, directory
    finally:
        chain.close()


def _run(prepared, request, observer):
    workspace, producer_root, intent, attestation, artifact, _batch = prepared
    return runner.run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, guardian_custody=request, registered_observer=observer,
    )


def _false(report):
    for key in ("native_success", "publication_authority", "cleanup_authority", "production_admission",
                "signal_result_known"):
        assert report[key] is False
    assert report["cleanup_status"] == "unknown"


def test_actual_registration_pair_is_read_back_before_gate_and_normal_native_finish(receiver, tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    original_references = []
    contexts = []

    def forbidden(*args, **kwargs):
        pytest.fail("opt-in must start the independent receiver rather than the default guardian")

    monkeypatch.setattr(runner, "start_native_guardian", forbidden)
    with _request(prepared, tmp_path, receiver) as (request, directory):
        assert request.reference is None

        def observer(context):
            assert not (batch / "work" / "marker").exists()
            reference = request.reference
            assert type(reference) is GuardianNativeRegistrationReference
            report = inspect_registered_native_guardian_custody(reference)
            assert report["state"] == "registered"
            assert report["native_registration_binding_observed"] is True
            native = json.loads(reference.canonical_bytes)["native_binding"]["native"]
            assert native["registration_file_identity"] == list(context.registration_file_identity)
            assert native["handoff_file_identity"] == list(context.handoff_file_identity)
            assert native["recovery_lock_identity"] == list(context.recovery_lock_identity)
            assert report["registration_sha256"] == json.loads(context.registration_json)["registration_sha256"]
            _false(report)
            original_references.append(reference)
            contexts.append(context)

        result = _run(prepared, request, observer)
        assert result.gate_released and result.target_started and result.exit_code == 0
        assert len(contexts) == len(original_references) == 1
        report = inspect_registered_native_guardian_custody(original_references[0])
        assert report["state"] == "watcher_exit_observed"
        assert (report["native_d_observed"], report["watcher_exit_kind"], report["watcher_exit_value"]) == (True, 1, 0)
        _false(report)
        assert (batch / "work" / "marker").read_bytes() == b"started"
        binding_before = (directory / _NAME).read_bytes()
        with pytest.raises(runner.NativeTrustedAttemptError, match="guardian_custody_invalid"):
            _run(prepared, request, observer)
        assert (directory / _NAME).read_bytes() == binding_before


@pytest.mark.parametrize("failure", ["entry-inode", "directory-mode"])
def test_pairing_or_directory_drift_in_original_observer_refuses_gate(receiver, tmp_path, failure):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    references = []
    with _request(prepared, tmp_path, receiver) as (request, directory):
        def observer(_context):
            assert not (batch / "work" / "marker").exists()
            references.append(request.reference)
            if failure == "directory-mode":
                directory.chmod(0o755)
                return
            path = directory / _NAME
            old_inode = path.stat().st_ino
            replacement = directory / "replacement"
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o600)
            os.replace(replacement, path)
            assert path.stat().st_ino != old_inode

        result = _run(prepared, request, observer)
        assert len(references) == 1
        assert result.gate_released is False and result.target_started is False
        assert not (batch / "work" / "marker").exists()
        assert inspect_registered_native_guardian_custody(references[0])["state"] == "unavailable"
        assert (directory / _NAME).exists()


def test_partial_pairing_write_is_retained_without_observer_or_gate(receiver, tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    with _request(prepared, tmp_path, receiver) as (request, directory):
        real_write = os.write
        written = False

        def fail_after_partial(fd, raw):
            nonlocal written
            named = directory / _NAME
            if named.exists():
                held, current = os.fstat(fd), named.stat()
                if (held.st_dev, held.st_ino) == (current.st_dev, current.st_ino):
                    if not written:
                        written = True
                        return real_write(fd, raw[:13])
                    raise OSError("fixture pairing writer failure")
            return real_write(fd, raw)

        monkeypatch.setattr(pairing.os, "write", fail_after_partial)
        seen = []
        result = _run(prepared, request, lambda context: seen.append(context))
        assert result.gate_released is False and result.target_started is False
        assert request.reference is None and seen == []
        assert written and len((directory / _NAME).read_bytes()) == 13
        assert not (batch / "work" / "marker").exists()
        with pytest.raises(runner.NativeTrustedAttemptError, match="guardian_custody_invalid"):
            _run(prepared, request, lambda context: seen.append(context))
        assert len((directory / _NAME).read_bytes()) == 13


def test_reference_survives_fresh_process_only_for_readonly_inspection(receiver, tmp_path):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    references = []
    with _request(prepared, tmp_path, receiver) as (request, directory):
        result = _run(prepared, request, lambda _context: references.append(request.reference))
        assert result.gate_released and result.exit_code == 0
        original = references[0]
    before = {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
              for p in directory.iterdir()}
    script = f"import sys\nsys.path.insert(0, {str(Path(pairing.__file__).resolve().parents[1])!r})\n" + """
import json,os,subprocess
from lunar_evolution import native_guardian_registration as pairing
def forbidden(*args,**kwargs):raise AssertionError('read-only inspection attempted effect')
os.kill=os.killpg=subprocess.Popen=forbidden
pairing.start_durable_native_guardian=forbidden
reference=pairing.GuardianNativeRegistrationReference(sys.stdin.buffer.read())
print(json.dumps(pairing.inspect_registered_native_guardian_custody(reference)))
"""
    child = subprocess.run([sys.executable, "-c", script], input=original.canonical_bytes,
                           capture_output=True, timeout=10, check=False)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    report = json.loads(child.stdout)
    assert report["state"] == "watcher_exit_observed"
    assert report["native_registration_binding_observed"] is True
    _false(report)
    assert {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns)
            for p in directory.iterdir()} == before
    assert str(batch) not in child.stdout.decode()


def test_custody_requires_original_observer_before_any_native_attempt(receiver, tmp_path):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    with _request(prepared, tmp_path, receiver) as (request, directory):
        with pytest.raises(runner.NativeTrustedAttemptError, match="guardian_custody_observer_required"):
            _run(prepared, request, None)
        assert request.reference is None and list(directory.iterdir()) == []
        assert not (batch / "process-registration.json").exists()


@pytest.mark.parametrize("failure", ["image-owner", "directory-shape"])
def test_original_start_validation_after_spawn_keeps_fixed_attempt_error(receiver, tmp_path, monkeypatch, failure):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    with _request(prepared, tmp_path, receiver) as (request, directory):
        name = "_elf" if failure == "image-owner" else "_private_chain"
        original = getattr(pairing, name)
        calls = 0

        def fail_second(value):
            nonlocal calls
            calls += 1
            if calls == 2:
                if failure == "image-owner":
                    raise LinuxExecutableBindingError("linux_execution_wall_timeout")
                raise ValueError("fixture original directory shape drift")
            return original(value)

        monkeypatch.setattr(pairing, name, fail_second)
        observed = []
        result = _run(prepared, request, lambda context: observed.append(context))
        assert calls == 2 and observed == []
        assert result.gate_released is False and result.target_started is False
        assert result.reason == "native_guardian_registration_binding_invalid"
        assert request.reference is None and list(directory.iterdir()) == []
        assert not (batch / "process-registration.json").exists()
