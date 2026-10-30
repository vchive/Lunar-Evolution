"""Original pre-gate persistence and actual read-only recovery after resolver loss."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_external_worker_native_lifecycle as native_fixture
from test_external_worker_native_lifecycle import _run, _same_bytes, _tree
from test_native_trusted_attempt import _materialize_valid_capture

from lunar_evolution import external_worker_native_lifecycle as local
from lunar_evolution import external_worker_native_restart as restart
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution.external_worker_origin import WorkerOriginKey

h = native_fixture.h


def _authority(report):
    for name in restart._AUTHORITY:
        assert report[name] is False


@pytest.fixture
def r(h):
    # The trusted fixture recreates the original worker intent before preparation;
    # the same current OS boot is also checked by the native deadline validator.
    boot = restart._boot_id()
    wire = json.loads(h.raw)
    wire["host_boot_id"] = boot
    h.raw = wrapper.worker_json(wire)
    os.unlink("intent.json", dir_fd=h.chain.fd)
    h.pin = wrapper._publish(h.chain.fd, "intent.json", h.raw, capture_identity=True)
    h.kwargs.update(original_worker_intent=h.raw, original_worker_intent_identity=h.pin)
    key = WorkerOriginKey("worker", "host", boot, "key", b"k" * 32)
    writer = restart.WorkerNativeRestartWriter(key=key, profile_sha256="e" * 64)
    observer = h.resolver.prepare_observer(**h.kwargs, restart_writer=writer)

    def inspect(**kwargs):
        return restart.inspect_native_restart(
            kwargs.pop("anchor", writer.anchor), kwargs.pop("raw", h.lookup),
            key=kwargs.pop("key", key), expected_context=kwargs.pop("context", h.context),
            expected_mapping=kwargs.pop("mapping", h.mapping),
            expected_profile_sha256=kwargs.pop("profile", "e" * 64), **kwargs,
        )

    return SimpleNamespace(h=h, key=key, writer=writer, observer=observer, inspect=inspect)


def _complete(r):
    result = _run(r.h, r.observer)
    assert result.gate_released and result.target_started and result.exit_code == 0
    assert r.writer.anchor is not None
    return result


def test_real_restore_after_original_resolver_and_chains_close_is_read_only(r, monkeypatch):
    _complete(r)
    original_anchor = r.writer.anchor
    assert "canonical_bytes" not in repr(original_anchor)
    r.h.resolver.close()
    r.h.chain.close()
    before = _tree(r.h.workspace), _tree(r.h.job)
    real_recover, real_audit = local.recover_native_trusted_attempt, local.audit_native_trusted_lifecycle
    calls = []

    def recover(*args, **kwargs):
        assert kwargs["cleanup"] is False
        calls.append("recover")
        return real_recover(*args, **kwargs)

    def audit(*args, **kwargs):
        calls.append("audit")
        return real_audit(*args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("restore must not publish, register, spawn or signal")

    monkeypatch.setattr(local, "recover_native_trusted_attempt", recover)
    monkeypatch.setattr(local, "audit_native_trusted_lifecycle", audit)
    monkeypatch.setattr(restart, "_publish", forbidden)
    monkeypatch.setattr(local.WorkerNativeLifecycleResolver, "prepare_observer", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    report = r.inspect(anchor=original_anchor)
    assert calls == ["recover", "audit"]
    assert report["status"] == "process_only"
    assert report["native_process_status"] == "exited_zero"
    assert report["restart_context_authenticated"] is True
    assert report["terminal_sha256"] is not None
    assert (_tree(r.h.workspace), _tree(r.h.job)) == before
    public = wrapper.worker_json(report).decode()
    assert r.h.attestation.nonce not in public and str(r.h.workspace) not in public
    assert '"pid"' not in public and r.key.secret_key.hex() not in public
    _authority(report)


def test_restore_with_complete_existing_capture_runs_lifecycle_audit(r):
    _complete(r)
    terminal = json.loads((r.h.batch / "native-trusted-process-terminal.json").read_bytes())
    _materialize_valid_capture(r.h.batch, r.h.intent, terminal)
    r.h.resolver.close()
    report = r.inspect()
    assert report["status"] == "lifecycle_observed"
    _authority(report)


def test_pre_gate_restore_observes_missing_terminal_without_releasing_gate(r):
    seen = []

    def observer(context):
        assert not (r.h.batch / "work" / "marker").exists()
        r.observer(context)
        before = _tree(r.h.workspace), _tree(r.h.job)
        report = r.inspect()
        assert report["status"] == "recovery_required"
        assert report["reason"] == "native_terminal_missing"
        assert not (r.h.batch / "work" / "marker").exists()
        assert (_tree(r.h.workspace), _tree(r.h.job)) == before
        _authority(report)
        seen.append(report)

    assert _run(r.h, observer).exit_code == 0
    assert len(seen) == 1


def test_no_external_original_anchor_does_not_rebuild_from_hmac_files(r):
    _complete(r)
    before = _tree(r.h.job)
    assert r.inspect(anchor=None)["status"] == "context_unavailable"
    assert _tree(r.h.job) == before


@pytest.mark.parametrize("name", [restart._PACKET, restart._COMPLETE, "intent.json", "native-context.json"])
def test_same_bytes_replaced_inode_is_not_a_restart_original(r, name):
    _complete(r)
    _same_bytes(r.h.job / name)
    report = r.inspect()
    assert report["status"] in {"context_unavailable", "context_drift"}
    assert report["terminal_sha256"] is None
    _authority(report)


@pytest.mark.parametrize("name", [restart._PACKET, restart._COMPLETE])
def test_missing_or_truncated_record_is_unknown_and_never_repaired(r, name):
    _complete(r)
    path = r.h.job / name
    path.write_bytes(b'{"private-nonce":"truncated')
    before = _tree(r.h.job)
    report = r.inspect()
    assert report["status"] == "context_unavailable"
    assert _tree(r.h.job) == before
    assert "private-nonce" not in json.dumps(report)
    path.unlink()
    assert r.inspect()["status"] == "context_unavailable"


@pytest.mark.parametrize("field,value", [("revoked", True), ("key_id", "rotated"),
                                         ("worker_id", "other-worker"), ("host_id", "other-host"),
                                         ("secret_key", b"z" * 32)])
def test_revocation_rotation_and_installed_identity_drift_refuse(r, field, value):
    _complete(r)
    report = r.inspect(key=replace(r.key, **{field: value}))
    assert report["status"] == "context_unavailable"
    _authority(report)


def test_current_boot_drift_refuses_even_with_original_key_and_hmac(r, monkeypatch):
    _complete(r)
    monkeypatch.setattr(restart, "_boot_id", lambda: "new-current-boot")
    assert r.inspect()["status"] == "context_unavailable"


@pytest.mark.parametrize("field,value", [("key_id", "changed"), ("worker_id", "changed"),
                                         ("host_id", "changed"), ("secret_key", b"m" * 32)])
def test_key_mutation_after_observation_discards_diagnostic(r, monkeypatch, field, value):
    _complete(r)
    original = local.WorkerNativeLifecycleResolver.inspect

    def drift(self, raw):
        report = original(self, raw)
        object.__setattr__(r.key, field, value)
        return report

    monkeypatch.setattr(local.WorkerNativeLifecycleResolver, "inspect", drift)
    assert r.inspect()["status"] == "context_unavailable"


@pytest.mark.parametrize("index", range(5))
def test_every_held_chain_mode_is_rechecked_after_observation(r, monkeypatch, index):
    _complete(r)
    paths = (r.h.job, r.h.workspace, r.h.batch, r.h.producer_root, r.h.artifact.path.parent)
    path = paths[index]
    original_mode = stat.S_IMODE(path.stat().st_mode)
    original = local.WorkerNativeLifecycleResolver.inspect

    def drift(self, raw):
        report = original(self, raw)
        path.chmod(original_mode ^ 0o010)
        return report

    monkeypatch.setattr(local.WorkerNativeLifecycleResolver, "inspect", drift)
    try:
        report = r.inspect()
        assert report["status"] == "context_unavailable"
        assert report["terminal_sha256"] is None
        _authority(report)
    finally:
        path.chmod(original_mode)


@pytest.mark.parametrize("field", [3, 4])
def test_native_parent_owner_metadata_is_rechecked_after_observation(r, monkeypatch, field):
    _complete(r)
    original_inspect = local.WorkerNativeLifecycleResolver.inspect
    original_pin = restart._directory_pin
    observed = False
    target = r.h.producer_root.stat()

    def observe(self, raw):
        nonlocal observed
        report = original_inspect(self, raw)
        observed = True
        return report

    def changed_pin(fd):
        row = original_pin(fd)
        if observed and row[:2] == [target.st_dev, target.st_ino]:
            row[field] += 1  # No privileged chown is needed to model numeric owner drift.
        return row

    monkeypatch.setattr(local.WorkerNativeLifecycleResolver, "inspect", observe)
    monkeypatch.setattr(restart, "_directory_pin", changed_pin)
    assert r.inspect()["status"] == "context_unavailable"


@pytest.mark.parametrize("name", ["run_id", "task_id", "controller_id", "episode_id", "context_kind",
                                 "context_sha256", "controller_challenge", "assignment_generation"])
def test_all_original_origin_fields_are_independently_required(r, name):
    _complete(r)
    value = "launch-context" if name == "context_kind" else 2 if name == "assignment_generation" else (
        "f" * 64 if name in {"context_sha256", "controller_challenge"} else "other")
    assert r.inspect(context=replace(r.h.context, **{name: value}))["status"] == "context_unavailable"


@pytest.mark.parametrize("name", local.WorkerNativeTaskMapping.__slots__)
def test_all_six_native_mapping_fields_are_independently_required(r, name):
    _complete(r)
    report = r.inspect(mapping=replace(r.h.mapping, **{name: "other"}))
    assert report["status"] == "context_unavailable"


def test_profile_drift_and_extra_public_selector_fields_refuse(r):
    _complete(r)
    assert r.inspect(profile="f" * 64)["status"] == "context_unavailable"
    lookup = json.loads(r.h.lookup)
    lookup["cleanup"] = True
    assert r.inspect(raw=wrapper.worker_json(lookup))["status"] == "context_unavailable"


def test_oversized_selector_is_bounded_without_hashing_its_payload(r, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("oversized public lookup must not be hashed")

    monkeypatch.setattr(restart.hashlib, "sha256", forbidden)
    report = r.inspect(raw=b"x" * 8193)
    assert report["status"] == "context_unavailable"
    assert report["lookup_sha256"] is None


def test_original_anchor_exact_schema_refuses_extra_acceptance_fields(r):
    _complete(r)
    value = json.loads(r.writer.anchor.canonical_bytes)
    value["accepted"] = True
    malformed = restart.WorkerNativeRestartAnchor(wrapper.worker_json(value))
    assert r.inspect(anchor=malformed)["status"] == "context_unavailable"


def test_completion_contains_packet_creator_pin_and_anchor_holds_completion_pin(r):
    _complete(r)
    anchor = json.loads(r.writer.anchor.canonical_bytes)
    complete = json.loads((r.h.job / restart._COMPLETE).read_bytes())
    assert complete["packet_identity"] == anchor["packet_identity"]
    assert "complete_identity" not in complete and "packet_identity" not in json.loads(
        (r.h.job / restart._PACKET).read_bytes())
    for name, key in ((restart._PACKET, "packet_identity"), (restart._COMPLETE, "complete_identity")):
        pin = anchor[key]
        data = (r.h.job / name).read_bytes()
        info = (r.h.job / name).stat()
        assert pin == [hashlib.sha256(data).hexdigest(), len(data), info.st_dev, info.st_ino,
                       info.st_mtime_ns, info.st_ctime_ns]
    assert r.h.attestation.nonce not in repr(r.writer.anchor)
    assert r.key.secret_key.decode() not in (r.h.job / restart._PACKET).read_text()


def test_writer_crash_after_packet_never_publishes_complete_or_releases_gate(r, monkeypatch):
    real_publish = restart._publish

    def crash(directory, name, raw, **kwargs):
        if name == restart._COMPLETE:
            raise OSError("secret-persistence-detail")
        return real_publish(directory, name, raw, **kwargs)

    monkeypatch.setattr(restart, "_publish", crash)
    result = _run(r.h, r.observer)
    assert result.gate_released is False and result.target_started is False
    assert r.writer.anchor is None
    assert (r.h.job / restart._PACKET).exists()
    assert not (r.h.job / restart._COMPLETE).exists()
    assert not (r.h.batch / "work" / "marker").exists()
    assert r.inspect()["status"] == "context_unavailable"


@pytest.mark.parametrize("field,value", [("key_id", "changed"), ("secret_key", b"m" * 32)])
def test_writer_checks_installed_key_after_complete_publication(r, monkeypatch, field, value):
    real_publish = restart._publish

    def mutate(directory, name, raw, **kwargs):
        pin = real_publish(directory, name, raw, **kwargs)
        if name == restart._COMPLETE:
            object.__setattr__(r.key, field, value)
        return pin

    monkeypatch.setattr(restart, "_publish", mutate)
    result = _run(r.h, r.observer)
    assert result.gate_released is False and result.target_started is False
    assert r.writer.anchor is None
    assert not (r.h.batch / "work" / "marker").exists()


def test_writer_is_create_only_and_an_attempt_cannot_retry_persistence(r):
    captured = []

    def observer(context):
        r.observer(context)
        captured.append(context)

    assert _run(r.h, observer).exit_code == 0
    before = _tree(r.h.job)
    with pytest.raises(local.WorkerNativeLifecycleError, match="binding_replayed"):
        r.observer(captured[0])
    assert _tree(r.h.job) == before


def test_old_default_observer_does_not_write_restart_protocol(h):
    observer = h.resolver.prepare_observer(**h.kwargs)
    assert _run(h, observer).exit_code == 0
    assert not (h.job / restart._PACKET).exists()
    assert not (h.job / restart._COMPLETE).exists()
