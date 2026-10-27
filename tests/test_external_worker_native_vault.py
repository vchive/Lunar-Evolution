"""Actual inert wrapper/native custody, fresh-process restore and conservative drift."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_external_worker_native_lifecycle as native_fixture
from test_external_worker_native_lifecycle import _same_bytes, _tree

from lunar_evolution import external_worker_native_bridge as bridge_module
from lunar_evolution import external_worker_native_vault as vault
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.external_worker_native_bridge import (
    InstalledWorkerNativeLaunch,
    WorkerInstalledNativeBridge,
)
from lunar_evolution.external_worker_native_restart import _boot_id
from lunar_evolution.external_worker_origin import WorkerOriginKey

h = native_fixture.h
pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")
PROFILE = "e" * 64


@pytest.fixture
def installed(h, tmp_path):
    # Preserve the original authorized native intent/attestation. Only the worker
    # episode is newly created by the actual wrapper, with its actual write FD.
    h.chain.close()
    (h.job / "intent.json").unlink()
    h.job.rmdir()
    state = tmp_path / "worker-state"
    state.mkdir(mode=0o700)
    directory = tmp_path / "independent-installed-vault"
    directory.mkdir(mode=0o700)
    key = WorkerOriginKey("worker", "host", _boot_id(), "key", b"v" * 32)
    chain = DirectoryChain(directory, "original installed fixture vault")
    try:
        installation = vault.capture_installed_native_vault(
            directory, original_directory_chain=chain, key=key, profile_sha256=PROFILE,
        )
    finally:
        chain.close()
    wire = json.loads(h.raw)
    wire["host_boot_id"] = key.host_boot_id
    raw = wrapper.worker_json({**wire, "action": "run"})
    config = wrapper.WorkerWrapperConfig(
        key, PROFILE, state, (sys.executable, "-c", "raise SystemExit('forbidden fallback')"),
        (h.context.controller_id,), 30,
    )
    launch = InstalledWorkerNativeLaunch(h.context, h.request, h.mapping, h.intent, h.attestation,
                                         h.artifact, h.workspace, h.producer_root)
    bridge = WorkerInstalledNativeBridge(launch, installation=installation, key=key, profile_sha256=PROFILE)
    h.job = state / hashlib.sha256(h.context.episode_id.encode()).hexdigest()

    def inspect(**changes):
        return vault.inspect_installed_native_restart(
            changes.pop("raw", h.lookup), installation=changes.pop("installation", installation),
            key=changes.pop("key", key), expected_context=changes.pop("context", h.context),
            expected_mapping=changes.pop("mapping", h.mapping),
            expected_profile_sha256=changes.pop("profile", PROFILE), **changes,
        )

    return SimpleNamespace(h=h, config=config, key=key, installation=installation,
                           directory=directory, bridge=bridge, raw=raw, inspect=inspect,
                           record=directory / (hashlib.sha256(h.lookup).hexdigest() + ".json"))


def _run(installed):
    response = wrapper.handle_installed_native_worker_request(
        installed.raw, installed.config, native_bridge=installed.bridge,
    )
    assert wrapper.parse_worker_response(response) == ("unknown", None, None)
    return response


def _authority(report):
    for name in ("publication_eligible", "native_success", "remote_cleanup_verified",
                 "publication_authority", "production_admission"):
        assert report[name] is False


def test_real_wrapper_retains_independent_anchor_before_native_gate_and_never_falls_back(installed, monkeypatch):
    real_retain = bridge_module.retain_installed_native_anchor
    seen = []

    def retain(*args, **kwargs):
        assert not (installed.h.batch / "work" / "marker").exists()
        real_retain(*args, **kwargs)
        assert installed.record.exists()
        report = installed.inspect()
        assert report["status"] == "recovery_required"
        assert report["restart_context_authenticated"] is True
        assert report["independent_anchor_custody_observed"] is True
        assert not (installed.h.batch / "work" / "marker").exists()
        _authority(report)
        seen.append(report)

    def forbidden(*args, **kwargs):
        pytest.fail("installed native path must not call the legacy argv producer")

    monkeypatch.setattr(bridge_module, "retain_installed_native_anchor", retain)
    monkeypatch.setattr(wrapper, "run_worker_channel", forbidden)
    _run(installed)
    assert len(seen) == 1
    assert (installed.h.batch / "work" / "marker").read_bytes() == b"started"
    assert not (installed.h.job / "response.json").exists()
    retained = json.loads(installed.record.read_bytes())
    packet = json.loads((installed.h.job / "native-restart-packet.json").read_bytes())
    assert retained["anchor"]["packet_identity"][0] == hashlib.sha256(
        (installed.h.job / "native-restart-packet.json").read_bytes()).hexdigest()
    assert retained["mapping"] == installed.h.mapping.to_dict()
    assert packet["worker_intent_identity"][0] == hashlib.sha256(
        (installed.h.job / "intent.json").read_bytes()).hexdigest()
    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    monkeypatch.setattr(bridge_module, "run_native_trusted_attempt", forbidden)
    _run(installed)
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before


def test_actual_fresh_process_restores_only_from_installed_custody_read_only(installed):
    _run(installed)
    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    # This private fixture payload is supplied by the original trusted caller,
    # not recovered from an episode packet or exposed on the public wire/argv.
    payload = wrapper.worker_json({
        "installation": base64.b64encode(installed.installation.canonical_bytes).decode(),
        "key": {name: getattr(installed.key, name)
                for name in ("worker_id", "host_id", "host_boot_id", "key_id")},
        "secret": base64.b64encode(installed.key.secret_key).decode(),
        "context": installed.h.context.to_dict(), "mapping": installed.h.mapping.to_dict(),
        "lookup": base64.b64encode(installed.h.lookup).decode(), "profile": PROFILE,
    })
    script = """
import base64,json,os,subprocess,sys
from lunar_evolution import external_worker_native_lifecycle as lifecycle
from lunar_evolution import external_worker_native_restart as restart
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution.external_worker_native_lifecycle import WorkerNativeTaskMapping
from lunar_evolution.external_worker_native_vault import InstalledWorkerNativeVault,inspect_installed_native_restart
from lunar_evolution.external_worker_origin import WorkerOriginContext,WorkerOriginKey
def forbidden(*a,**k): raise AssertionError('read-only restart attempted a side effect')
lifecycle.WorkerNativeLifecycleResolver.prepare_observer=forbidden
wrapper._publish=restart._publish=forbidden
os.kill=os.killpg=subprocess.Popen=forbidden
p=json.loads(sys.stdin.buffer.read())
r=inspect_installed_native_restart(base64.b64decode(p['lookup']),
 installation=InstalledWorkerNativeVault(base64.b64decode(p['installation'])),
 key=WorkerOriginKey(**p['key'],secret_key=base64.b64decode(p['secret'])),
 expected_context=WorkerOriginContext.from_dict(p['context']),
 expected_mapping=WorkerNativeTaskMapping(**p['mapping']),expected_profile_sha256=p['profile'])
sys.stdout.buffer.write(wrapper.worker_json(r))
"""
    script = f"import sys\nsys.path.insert(0, {str(Path(wrapper.__file__).resolve().parents[1])!r})\n" + script
    child = subprocess.run([sys.executable, "-c", script], input=payload,
                           capture_output=True, timeout=20, check=False)
    assert child.returncode == 0, child.stderr.decode(errors="replace")
    report = json.loads(child.stdout)
    assert report["status"] == "process_only"
    assert report["native_process_status"] == "exited_zero"
    assert report["restart_context_authenticated"] is True
    assert report["independent_anchor_custody_observed"] is True
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before
    public = child.stdout.decode() + repr(installed.installation) + repr(installed.bridge)
    assert installed.h.attestation.nonce not in public
    assert installed.key.secret_key.decode() not in public
    assert str(installed.h.workspace) not in public
    _authority(report)


@pytest.mark.parametrize("failure", ["before_write", "partial_pending", "after_durable_write"])
def test_vault_failure_refuses_actual_gate_without_repair_or_argv_fallback(installed, monkeypatch, failure):
    real_publish = vault._publish
    real_run = bridge_module.run_native_trusted_attempt
    observations = []

    def fail(directory, name, raw, **kwargs):
        if failure == "partial_pending":
            fd = os.open(name + ".pending", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            try:
                os.write(fd, b"{")
                os.fsync(fd)
            finally:
                os.close(fd)
        elif failure == "after_durable_write":
            real_publish(directory, name, raw, **kwargs)
        raise OSError("private injected persistence detail")

    def run(*args, **kwargs):
        observation = real_run(*args, **kwargs)
        observations.append(observation)
        return observation

    monkeypatch.setattr(vault, "_publish", fail)
    monkeypatch.setattr(bridge_module, "run_native_trusted_attempt", run)
    _run(installed)
    assert len(observations) == 1
    assert observations[0].gate_released is False and observations[0].target_started is False
    assert not (installed.h.batch / "work" / "marker").exists()
    assert not (installed.h.job / "response.json").exists()
    if failure != "after_durable_write":
        assert installed.inspect()["status"] == "context_unavailable"
    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    _run(installed)
    assert len(observations) == 1
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before


def test_missing_independent_record_never_uses_valid_episode_packet(installed):
    _run(installed)
    installed.record.unlink()
    before = _tree(installed.h.job), _tree(installed.directory)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    assert report["independent_anchor_custody_observed"] is False
    assert (installed.h.job / "native-restart-packet.json").exists()
    assert (_tree(installed.h.job), _tree(installed.directory)) == before
    _authority(report)


def test_original_wire_absolute_expiry_after_custody_still_refuses_gate(installed, monkeypatch):
    real_retain = bridge_module.retain_installed_native_anchor
    deadline = json.loads(installed.raw)["deadline_unix"]

    def expire(*args, **kwargs):
        real_retain(*args, **kwargs)
        monkeypatch.setattr(bridge_module.time, "time", lambda: deadline + 1)

    monkeypatch.setattr(bridge_module, "retain_installed_native_anchor", expire)
    _run(installed)
    assert installed.record.exists()
    assert not (installed.h.batch / "work" / "marker").exists()
    assert not (installed.h.job / "response.json").exists()


@pytest.mark.parametrize("drift", ["key_id", "key_secret", "installation"])
def test_post_publication_installed_identity_drift_refuses_native_gate(installed, monkeypatch, drift):
    real_publish = vault._publish

    def change(*args, **kwargs):
        pin = real_publish(*args, **kwargs)
        if drift == "key_id":
            object.__setattr__(installed.key, "key_id", "rotated")
        elif drift == "key_secret":
            object.__setattr__(installed.key, "secret_key", b"r" * 32)
        else:
            value = json.loads(installed.installation.canonical_bytes)
            value["profile_sha256"] = "f" * 64
            object.__setattr__(installed.installation, "canonical_bytes", wrapper.worker_json(value))
        return pin

    monkeypatch.setattr(vault, "_publish", change)
    _run(installed)
    assert not (installed.h.batch / "work" / "marker").exists()
    assert not (installed.h.job / "response.json").exists()


@pytest.mark.parametrize("drift", ["context", "mapping", "profile", "key_id", "key_secret", "unconfigured"])
def test_restart_requires_independent_original_installation_and_assignment(installed, drift):
    _run(installed)
    changes = {}
    if drift == "context":
        changes["context"] = replace(installed.h.context, task_id="other-task")
    elif drift == "mapping":
        changes["mapping"] = replace(installed.h.mapping, native_parent_task_id="other-parent")
    elif drift == "profile":
        changes["profile"] = "f" * 64
    elif drift == "key_id":
        changes["key"] = replace(installed.key, key_id="rotated")
    elif drift == "key_secret":
        changes["key"] = replace(installed.key, secret_key=b"r" * 32)
    else:
        changes["installation"] = None
    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    report = installed.inspect(**changes)
    assert report["status"] == "context_unavailable"
    assert report["independent_anchor_custody_observed"] is False
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before
    _authority(report)


def test_vault_entry_replacement_during_native_read_discards_observation(installed, monkeypatch):
    _run(installed)
    real_inspect = vault.inspect_native_restart

    def drift(*args, **kwargs):
        report = real_inspect(*args, **kwargs)
        _same_bytes(installed.record)
        return report

    monkeypatch.setattr(vault, "inspect_native_restart", drift)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    assert report["terminal_sha256"] is None
    assert report["independent_anchor_custody_observed"] is False
    _authority(report)


@pytest.mark.parametrize("drift", ["key_secret", "installation"])
def test_final_private_chain_check_cannot_outlive_original_key_or_installation(installed, monkeypatch, drift):
    _run(installed)
    real_private_chain = vault._private_chain
    checks = 0

    def change(chain):
        nonlocal checks
        real_private_chain(chain)
        checks += 1
        if checks == 2:
            if drift == "key_secret":
                object.__setattr__(installed.key, "secret_key", b"r" * 32)
            else:
                value = json.loads(installed.installation.canonical_bytes)
                value["profile_sha256"] = "f" * 64
                object.__setattr__(installed.installation, "canonical_bytes", wrapper.worker_json(value))

    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    monkeypatch.setattr(vault, "_private_chain", change)
    report = installed.inspect()
    assert checks == 2
    assert report["status"] == "context_unavailable"
    assert report["terminal_sha256"] is None
    assert report["independent_anchor_custody_observed"] is False
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before
    _authority(report)


@pytest.mark.parametrize("mode", [0o644, 0o660, 0o666])
def test_vault_record_widened_permissions_refuse_before_native_read(installed, monkeypatch, mode):
    _run(installed)
    installed.record.chmod(mode)

    def forbidden(*args, **kwargs):
        pytest.fail("nonprivate installed custody must not reach native inspection")

    monkeypatch.setattr(vault, "inspect_native_restart", forbidden)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    assert report["independent_anchor_custody_observed"] is False
    _authority(report)


@pytest.mark.parametrize("contents", [b"{", b"x" * (256 * 1024 + 1), b'{"extra":true}'],
                         ids=["partial", "oversized", "extra-fields"])
def test_invalid_or_partial_vault_record_never_calls_native_recovery(installed, monkeypatch, contents):
    _run(installed)
    installed.record.write_bytes(contents)

    def forbidden(*args, **kwargs):
        pytest.fail("unauthenticated independent custody must not reach native recovery")

    monkeypatch.setattr(vault, "inspect_native_restart", forbidden)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    assert report["independent_anchor_custody_observed"] is False
    _authority(report)


@pytest.mark.parametrize("name", ["native-restart-packet.json", "native-restart-complete.json"])
def test_custodied_original_creator_pins_still_refuse_same_byte_episode_replacement(installed, name):
    _run(installed)
    _same_bytes(installed.h.job / name)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    assert report["terminal_sha256"] is None
    _authority(report)


def test_installation_directory_replacement_and_changed_permissions_refuse(installed):
    _run(installed)
    old = installed.directory.with_name("old-original-vault")
    installed.directory.rename(old)
    installed.directory.mkdir(mode=0o700)
    installed.record.write_bytes((old / installed.record.name).read_bytes())
    installed.record.chmod(0o600)
    report = installed.inspect()
    assert report["status"] == "context_unavailable"
    installed.directory.chmod(0o755)
    assert installed.inspect()["status"] == "context_unavailable"


def test_independent_store_required_and_explicit_unconfigured_entry_never_launches(installed, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unconfigured installed entry must not execute a producer")

    monkeypatch.setattr(wrapper, "run_worker_channel", forbidden)
    with pytest.raises(wrapper.WorkerWrapperError, match="installed_bridge_unconfigured"):
        wrapper.handle_installed_native_worker_request(installed.raw, installed.config)
    assert not installed.h.job.exists()
    with pytest.raises(vault.WorkerNativeVaultError, match="independent_store_required"):
        vault.check_installed_vault_separation(
            installed.installation, key=installed.key, profile_sha256=PROFILE,
            private_roots=(installed.directory / "episode",),
        )


def test_bounded_malformed_lookup_and_original_attestation_are_not_recreated(installed, monkeypatch):
    from lunar_evolution import producer_launcher

    def forbidden(*args, **kwargs):
        pytest.fail("trusted bridge must use the existing explicitly authorized attestation")

    monkeypatch.setattr(producer_launcher, "build_producer_launch_attestation", forbidden)
    _run(installed)
    before = _tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)
    assert installed.inspect(raw=b"x" * 8193)["status"] == "context_unavailable"
    assert installed.inspect(raw=wrapper.worker_json({"workspace": "/private"}))["status"] == "context_unavailable"
    assert (_tree(installed.h.workspace), _tree(installed.h.job), _tree(installed.directory)) == before
