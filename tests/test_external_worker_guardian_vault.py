"""Real installed wrapper/guardian sidecar fixtures, without production claims."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path

import pytest
import test_external_worker_native_lifecycle as native_fixture
import test_external_worker_native_vault as installed_fixture
from _native_target_fixture import compile_native_target
from test_external_worker_native_lifecycle import _tree
from test_external_worker_native_vault import PROFILE, _run

from lunar_evolution import external_worker_guardian_vault as custody
from lunar_evolution import external_worker_native_bridge as bridge_module
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.external_worker_native_bridge import (
    InstalledWorkerNativeLaunch,
    WorkerInstalledNativeBridge,
)
from lunar_evolution.linux_executable_binding import sealed_linux_executable
from lunar_evolution.native_guardian_custody import native_guardian_receiver_source_path
from lunar_evolution.native_guardian_registration import NativeGuardianCustodyRequest
from lunar_evolution.producer_bootstrap import build_trusted_bootstrap_launch

h = native_fixture.h
installed = installed_fixture.installed
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual installed Linux guardian sidecar")


@pytest.fixture(scope="module")
def receiver(tmp_path_factory):
    target = tmp_path_factory.mktemp("installed-guardian-sidecar") / "receiver"
    compile_native_target(native_guardian_receiver_source_path(), target)
    return target


@pytest.fixture
def g(installed, receiver, tmp_path):
    original = installed.h
    directory = tmp_path / "guardian-custody"
    directory.mkdir(mode=0o700)
    chain = DirectoryChain(directory, "fixture guardian directory drift")
    info = receiver.stat()
    identity = {"sha256": hashlib.sha256(receiver.read_bytes()).hexdigest(), "size": info.st_size,
                "device": info.st_dev, "inode": info.st_ino,
                "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
    native_launch = build_trusted_bootstrap_launch(original.intent, original.attestation, original.artifact.descriptor)
    try:
        with ExitStack() as runtime:
            image = runtime.enter_context(sealed_linux_executable(
                receiver, identity, deadline=time.monotonic() + 30,
            ))
            runtime.callback(chain.close)
            request = NativeGuardianCustodyRequest(
                receiver=image, original_directory=directory, original_directory_chain=chain,
                original_context_sha256=hashlib.sha256(wrapper.worker_json(original.context.to_dict())).hexdigest(),
                original_launch_sha256=native_launch.launch_sha256, original_profile_sha256=PROFILE,
            )
            launch = InstalledWorkerNativeLaunch(
                original.context, original.request, original.mapping, original.intent,
                original.attestation, original.artifact, original.workspace, original.producer_root,
            )
            installed.bridge = WorkerInstalledNativeBridge(
                launch, installation=installed.installation, key=installed.key,
                profile_sha256=PROFILE, guardian_custody=request,
            )
            installed.guardian_request, installed.guardian_directory = request, directory
            installed.guardian_image, installed.close_guardian_originals = image, runtime.close
            installed.guardian_record = installed.directory / ("guardian-" + hashlib.sha256(original.lookup).hexdigest() + ".json")

            def inspect(**changes):
                return custody.inspect_installed_guardian_reference(
                    changes.pop("raw", original.lookup),
                    installation=changes.pop("installation", installed.installation),
                    key=changes.pop("key", installed.key),
                    expected_context=changes.pop("context", original.context),
                    expected_mapping=changes.pop("mapping", original.mapping),
                    expected_profile_sha256=changes.pop("profile", PROFILE), **changes,
                )

            installed.guardian_inspect = inspect
            yield installed
    finally:
        chain.close()


def _false(report):
    for name in ("native_success", "production_admission", "publication_authority",
                 "cleanup_authority", "signal_result_known"):
        assert report[name] is False
    assert report["cleanup_status"] == "unknown"
    assert report["execution_status"] == "unknown"


def test_actual_installed_wrapper_retains_original_reference_before_gate_without_changing_v1(g, monkeypatch):
    original_create = custody._create
    observed = []

    def create(*args, **kwargs):
        assert not (g.h.batch / "work" / "marker").exists()
        pin = original_create(*args, **kwargs)
        report = g.guardian_inspect()
        assert report["status"] == "custody_observed"
        assert report["state"] == "registered"
        assert report["guardian_reference_custody_observed"] is True
        _false(report)
        assert not (g.h.batch / "work" / "marker").exists()
        observed.append(pin)
        return pin

    monkeypatch.setattr(custody, "_create", create)
    _run(g)
    assert len(observed) == 1
    assert (g.h.batch / "work" / "marker").read_bytes() == b"started"
    report = g.guardian_inspect()
    assert report["status"] == "custody_observed" and report["state"] == "watcher_exit_observed"
    assert report["native"]["native_process_status"] == "exited_zero"
    _false(report)
    native = json.loads(g.record.read_bytes())
    sidecar = json.loads(g.guardian_record.read_bytes())
    assert native["protocol"] == "lunar-installed-worker-native-vault-v1"
    assert "guardian_reference" not in native
    assert sidecar["native_anchor"] == native["anchor"]
    assert sidecar["native_vault_sha256"] == hashlib.sha256(g.record.read_bytes()).hexdigest()
    assert sidecar["guardian_reference"] == json.loads(g.guardian_request.reference.canonical_bytes)
    native_packet = json.loads((g.h.job / "native-restart-packet.json").read_bytes())
    assert not any("guardian" in field for field in native_packet["native"])


def test_fresh_process_reads_only_independent_installed_sidecar_and_preserves_unknown(g):
    _run(g)
    g.close_guardian_originals()
    before = (_tree(g.h.workspace), _tree(g.h.job), _tree(g.directory), _tree(g.guardian_directory))
    payload = wrapper.worker_json({
        "installation": base64.b64encode(g.installation.canonical_bytes).decode(),
        "key": {name: getattr(g.key, name) for name in ("worker_id", "host_id", "host_boot_id", "key_id")},
        "secret": base64.b64encode(g.key.secret_key).decode(),
        "context": g.h.context.to_dict(), "mapping": g.h.mapping.to_dict(),
        "lookup": base64.b64encode(g.h.lookup).decode(), "profile": PROFILE,
    })
    script = f"import sys\nsys.path.insert(0, {str(Path(custody.__file__).resolve().parents[1])!r})\n" + """
import base64,json,os,subprocess
from lunar_evolution import external_worker_guardian_vault as custody
from lunar_evolution import native_guardian_registration as pairing
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution.external_worker_native_lifecycle import WorkerNativeTaskMapping
from lunar_evolution.external_worker_native_vault import InstalledWorkerNativeVault
from lunar_evolution.external_worker_origin import WorkerOriginContext,WorkerOriginKey
def forbidden(*args,**kwargs):raise AssertionError('read-only installed lookup attempted an effect')
os.kill=os.killpg=subprocess.Popen=forbidden
custody._create=pairing.start_durable_native_guardian=forbidden
p=json.loads(sys.stdin.buffer.read())
report=custody.inspect_installed_guardian_reference(base64.b64decode(p['lookup']),
 installation=InstalledWorkerNativeVault(base64.b64decode(p['installation'])),
 key=WorkerOriginKey(**p['key'],secret_key=base64.b64decode(p['secret'])),
 expected_context=WorkerOriginContext.from_dict(p['context']),
 expected_mapping=WorkerNativeTaskMapping(**p['mapping']),expected_profile_sha256=p['profile'])
sys.stdout.buffer.write(wrapper.worker_json(report))
"""
    child = subprocess.run([sys.executable, "-c", script], input=payload,
                           capture_output=True, timeout=20, check=False)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    report = json.loads(child.stdout)
    assert report["status"] == "custody_observed"
    assert report["guardian_reference_custody_observed"] is True
    _false(report)
    assert (_tree(g.h.workspace), _tree(g.h.job), _tree(g.directory), _tree(g.guardian_directory)) == before
    assert str(g.h.workspace) not in child.stdout.decode()
    assert g.key.secret_key.decode() not in child.stdout.decode()


@pytest.mark.parametrize("stage", ["before-write", "partial-pending", "after-durable"])
def test_sidecar_failure_keeps_gate_closed_and_never_repairs_or_retries(g, monkeypatch, stage):
    original_create, original_run = custody._create, bridge_module.run_native_trusted_attempt
    outcomes = []

    def create(chain, name, raw, checkpoint):
        if stage == "partial-pending":
            fd = os.open(name + ".pending", os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                         0o600, dir_fd=chain.fd)
            try:
                os.write(fd, raw[:13])
                os.fsync(fd)
            finally:
                os.close(fd)
        elif stage == "after-durable":
            original_create(chain, name, raw, checkpoint)
        raise OSError("fixture independent guardian custody failure")

    def run(*args, **kwargs):
        outcome = original_run(*args, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(custody, "_create", create)
    monkeypatch.setattr(bridge_module, "run_native_trusted_attempt", run)
    _run(g)
    assert len(outcomes) == 1 and outcomes[0].gate_released is False and outcomes[0].target_started is False
    assert not (g.h.batch / "work" / "marker").exists()
    assert not (g.h.job / "response.json").exists()
    if stage == "partial-pending":
        assert g.guardian_record.with_name(g.guardian_record.name + ".pending").stat().st_size == 13
    if stage != "after-durable":
        assert g.guardian_inspect()["status"] == "context_unavailable"
    else:
        # A durable prefix is a custody fact; a lost publication acknowledgement
        # still grants no execution/cleanup/native-success authority.
        _false(g.guardian_inspect())
    before = (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory))
    _run(g)
    assert len(outcomes) == 1
    assert (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory)) == before


def test_missing_independent_sidecar_never_discovers_reference_from_receiver_or_native_packet(g):
    _run(g)
    g.guardian_record.unlink()
    before = (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory))
    assert g.inspect()["independent_anchor_custody_observed"] is True
    assert g.guardian_inspect()["status"] == "context_unavailable"
    assert g.guardian_inspect()["guardian_reference_custody_observed"] is False
    assert (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory)) == before


@pytest.mark.parametrize("change", ["key", "context", "mapping", "profile", "pair-inode"])
def test_original_assignment_and_pairing_drift_remain_readonly_unknown(g, change):
    _run(g)
    changes = {}
    if change == "key":
        changes["key"] = replace(g.key, secret_key=b"x" * 32)
    elif change == "context":
        changes["context"] = replace(g.h.context, controller_challenge="f" * 64)
    elif change == "mapping":
        changes["mapping"] = replace(g.h.mapping, native_task_id="other-task")
    elif change == "profile":
        changes["profile"] = "f" * 64
    else:
        path = g.guardian_directory / "guardian-native-registration-v1.json"
        replacement = path.with_name("replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(0o600)
        old_inode = path.stat().st_ino
        replacement.replace(path)
        assert path.stat().st_ino != old_inode
    before = (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory))
    report = g.guardian_inspect(**changes)
    assert report["status"] == "context_unavailable"
    _false(report)
    assert (_tree(g.directory), _tree(g.h.job), _tree(g.guardian_directory)) == before


def test_original_wire_expiry_after_sidecar_refuses_native_gate(g, monkeypatch):
    real_retain = bridge_module.retain_installed_guardian_reference
    deadline = json.loads(g.raw)["deadline_unix"]
    outcomes = []
    real_run = bridge_module.run_native_trusted_attempt

    def retain(*args, **kwargs):
        real_retain(*args, **kwargs)
        monkeypatch.setattr(bridge_module.time, "time", lambda: deadline + 1)

    def run(*args, **kwargs):
        result = real_run(*args, **kwargs)
        outcomes.append(result)
        return result

    monkeypatch.setattr(bridge_module, "retain_installed_guardian_reference", retain)
    monkeypatch.setattr(bridge_module, "run_native_trusted_attempt", run)
    _run(g)
    assert g.guardian_record.exists()
    assert len(outcomes) == 1 and outcomes[0].gate_released is False and outcomes[0].target_started is False
    assert not (g.h.batch / "work" / "marker").exists()


def test_original_bridge_refuses_nested_independent_guardian_store_before_launch(g):
    directory = g.directory / "nested-guardian"
    directory.mkdir(mode=0o700)
    chain = DirectoryChain(directory, "fixture nested guardian chain")
    native = build_trusted_bootstrap_launch(g.h.intent, g.h.attestation, g.h.artifact.descriptor)
    try:
        request = NativeGuardianCustodyRequest(
            receiver=g.guardian_image, original_directory=directory, original_directory_chain=chain,
            original_context_sha256=hashlib.sha256(wrapper.worker_json(g.h.context.to_dict())).hexdigest(),
            original_launch_sha256=native.launch_sha256, original_profile_sha256=PROFILE,
        )
        launch = InstalledWorkerNativeLaunch(
            g.h.context, g.h.request, g.h.mapping, g.h.intent, g.h.attestation,
            g.h.artifact, g.h.workspace, g.h.producer_root,
        )
        with pytest.raises(ValueError, match="independent_store_required"):
            WorkerInstalledNativeBridge(
                launch, installation=g.installation, key=g.key, profile_sha256=PROFILE,
                guardian_custody=request,
            )
        assert list(directory.iterdir()) == []
        assert not (g.h.batch / "process-registration.json").exists()
    finally:
        chain.close()
