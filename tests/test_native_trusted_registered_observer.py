"""Original native registration observer ordering; real blocked native targets."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import FrozenInstanceError, fields

import pytest
from test_native_trusted_attempt import _attempt

from lunar_evolution import native_trusted_attempt as runner
from lunar_evolution.native_trusted_attempt import (
    NativeTrustedAttemptError,
    NativeTrustedRegisteredContext,
    run_native_trusted_attempt,
)
from lunar_evolution.trusted_bootstrap_registration import PublishedTrustedBootstrapRegistration

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")


def _run(prepared, observer):
    workspace, producer_root, intent, attestation, artifact, _ = prepared
    return run_native_trusted_attempt(
        workspace, producer_root=producer_root, intent=intent,
        attestation=attestation, artifact=artifact, registered_observer=observer,
    )


def _track_native_cleanup(monkeypatch):
    original_cleanup = runner._cleanup
    calls = []

    def record_cleanup(owner, process, **kwargs):
        # Observe the real primitive without replacing its result or owner checks.
        observed = original_cleanup(owner, process, **kwargs)
        calls.append((process, kwargs, observed))
        return observed

    monkeypatch.setattr(runner, "_cleanup", record_cleanup)
    return calls


def _assert_original_cleanup_record(batch, calls):
    assert len(calls) == 1
    process, kwargs, observed = calls[0]
    registration = json.loads((batch / "process-registration.json").read_bytes())
    deadline = json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
    cleanup = json.loads((batch / "native-trusted-cleanup.json").read_bytes())
    assert kwargs["deadline"] == deadline["deadline_monotonic"]
    assert cleanup["registration_sha256"] == registration["registration_sha256"]
    assert cleanup["deadline_sha256"] == deadline["deadline_sha256"]
    assert (cleanup["pid"], cleanup["pgid"]) == (observed.pid, observed.pgid)
    assert cleanup["cleanup_status"] == observed.status.value
    assert cleanup["term_sent"] is observed.term_sent
    assert cleanup["kill_sent"] is observed.kill_sent
    assert cleanup["alive_after"] is observed.alive_after
    assert cleanup["publication_eligible"] is False
    assert cleanup["cleanup_sha256"] == runner._digest_without(cleanup, "cleanup_sha256")
    # Exact-child exit is a separate fact: it cannot prove its whole group clean.
    assert process.poll() is not None
    assert not (batch / "work" / "marker").exists()
    assert not (batch / "native-trusted-process-terminal.json").exists()
    evidence = json.loads((batch / "trusted-bootstrap-evidence.json").read_bytes())
    assert evidence["status"] == "unknown"
    assert evidence["release_observed"] is False
    assert evidence["target_started_observed"] is False
    assert evidence["target_start_count"] == 0
    return observed


def _assert_pregate_refusal(batch, result, calls, original_reason):
    observed = _assert_original_cleanup_record(batch, calls)
    assert result.status == "recovery_required"
    assert result.registration_sha256 is not None
    assert result.gate_released is False and result.target_started is False
    assert result.cleanup_status == observed.status.value
    if observed.status.value in {"cleaned", "already_exited"}:
        assert result.reason == original_reason
    else:
        # The existing conservative cleanup refusal takes precedence. Never
        # infer success from an exited leader or discard the real group result.
        assert result.reason == "native_trusted_attempt_cleanup_unknown"


def test_trusted_observer_receives_original_detached_context_before_target_release(tmp_path):
    prepared = _attempt(tmp_path)
    workspace, producer_root, intent, attestation, artifact, batch = prepared
    marker = batch / "work" / "marker"
    seen = []
    pin = batch / "installed-observer-binding.json"

    def observer(context):
        assert type(context) is NativeTrustedRegisteredContext
        assert not marker.exists()
        assert context.workspace == str(workspace)
        assert context.producer_root == str(producer_root)
        assert context.artifact_path == str(artifact.path)
        assert (context.run_id, context.parent_task_id, context.task_id) == (
            intent.run_id, intent.parent_task_id, intent.task_id,
        )
        assert (context.launch_id, context.journal_id) == (intent.launch_id, intent.journal_id)
        assert context.intent_sha256 == intent.intent_sha256
        assert context.attestation_sha256 == attestation.attestation_sha256
        assert context.bootstrap_descriptor_sha256 == artifact.descriptor.descriptor_sha256
        assert context.bootstrap_artifact_sha256 == artifact.artifact_sha256
        assert json.loads(context.registration_json) == json.loads((batch / "process-registration.json").read_bytes())
        assert json.loads(context.handoff_json) == json.loads((batch / "trusted-bootstrap-handoff.json").read_bytes())
        assert json.loads(context.deadline_json) == json.loads((batch / "native-trusted-attempt-deadline.json").read_bytes())
        assert json.loads(context.deadline_binding_json)["deadline_sha256"] == json.loads(context.deadline_json)["deadline_sha256"]
        names = {item.name for item in fields(context)}
        assert not names & {"gate_nonce", "nonce", "secret_key", "gate_fd", "fd", "process",
                            "launch", "intent", "attestation", "artifact"}
        assert attestation.nonce not in repr(context)
        assert all(type(getattr(context, item.name)) in {str, bytes, tuple, bool} for item in fields(context))
        assert context.publication_eligible is False
        with pytest.raises(FrozenInstanceError):
            context.launch_id = "changed"
        # A detached decode cannot modify the internally retained registration.
        detached = json.loads(context.registration_json)
        detached["pid"] = 1
        assert json.loads(context.registration_json)["pid"] != 1
        # Stand-in for a trusted launcher's create-only durable assignment pin.
        with pin.open("xb") as stream:
            stream.write(context.registration_json)
            stream.flush()
            os.fsync(stream.fileno())
        seen.append(context)

    result = _run(prepared, observer)
    assert len(seen) == 1
    assert pin.read_bytes() == seen[0].registration_json
    assert result.gate_released and result.target_started and result.exit_code == 0
    assert result.registration_sha256 == json.loads(seen[0].registration_json)["registration_sha256"]
    assert marker.read_text() == "started"
    terminal = json.loads((batch / "native-trusted-process-terminal.json").read_bytes())
    assert terminal["publication_eligible"] is False


@pytest.mark.parametrize("failure", ["raise", "non-none-return"])
def test_observer_failure_keeps_gate_closed_and_runs_existing_native_cleanup(tmp_path, monkeypatch, failure):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    seen = []
    cleanup_calls = _track_native_cleanup(monkeypatch)

    def observer(context):
        seen.append(context)
        assert not (batch / "work" / "marker").exists()
        if failure == "raise":
            raise RuntimeError("fixture private error text must not become a reason")
        return False

    result = _run(prepared, observer)
    assert len(seen) == 1
    _assert_pregate_refusal(
        batch, result, cleanup_calls, "native_trusted_attempt_registered_observer_failed",
    )


def test_observer_base_exception_propagates_only_after_original_native_cleanup(tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    cleanup_calls = _track_native_cleanup(monkeypatch)

    class ObserverAbort(BaseException):
        pass

    def observer(context):
        assert type(context) is NativeTrustedRegisteredContext
        assert not (batch / "work" / "marker").exists()
        raise ObserverAbort("fixture abort")

    with pytest.raises(ObserverAbort, match="fixture abort"):
        _run(prepared, observer)
    _assert_original_cleanup_record(batch, cleanup_calls)


@pytest.mark.parametrize("name", ["process-registration.json", "trusted-bootstrap-handoff.json"])
def test_same_byte_entry_replacement_during_observer_refuses_gate(tmp_path, monkeypatch, name):
    prepared = _attempt(tmp_path)
    *_, batch = prepared

    cleanup_calls = _track_native_cleanup(monkeypatch)
    replaced = []

    def observer(_context):
        path = batch / name
        original_inode = path.stat().st_ino
        replacement = batch / (name + ".replacement")
        replacement.write_bytes(path.read_bytes())
        replacement.chmod(path.stat().st_mode & 0o777)
        replacement.replace(path)
        assert path.stat().st_ino != original_inode
        replaced.append(name)

    result = _run(prepared, observer)
    assert replaced == [name]
    _assert_pregate_refusal(
        batch, result, cleanup_calls, "native_trusted_attempt_registered_context_drift",
    )


def test_context_mutation_cannot_rewrite_internal_original_pin(tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared

    cleanup_calls = _track_native_cleanup(monkeypatch)

    mutated = []

    def observer(context):
        object.__setattr__(context, "registration_json", b"{}")
        object.__setattr__(context, "publication_eligible", True)
        mutated.append((context.registration_json, context.publication_eligible))

    result = _run(prepared, observer)
    assert mutated == [(b"{}", True)]
    _assert_pregate_refusal(
        batch, result, cleanup_calls, "native_trusted_attempt_registered_context_drift",
    )


def test_invalid_observer_is_rejected_before_nonce_consumption_or_spawn(tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared

    def forbidden(*_args, **_kwargs):
        pytest.fail("invalid installed observer reached native spawn")

    monkeypatch.setattr(runner.subprocess, "Popen", forbidden)
    with pytest.raises(NativeTrustedAttemptError, match="native_trusted_attempt_registered_observer_invalid"):
        _run(prepared, object())
    assert not batch.exists()


@pytest.mark.parametrize("name", ["process-registration.json", "trusted-bootstrap-handoff.json"])
def test_same_byte_entry_replacement_before_publisher_return_refuses_observer_and_gate(
    tmp_path, monkeypatch, name,
):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    publish = runner.publish_trusted_bootstrap_registration
    seen = []
    replaced = []
    cleanup_calls = _track_native_cleanup(monkeypatch)

    def replace_before_return(*args, **kwargs):
        assert kwargs["retain_creation_identity"] is True
        published = publish(*args, **kwargs)
        path = batch / name
        original_inode = path.stat().st_ino
        expected = (published.registration_file_identity if name == "process-registration.json"
                    else published.handoff_file_identity)
        assert expected is not None and expected[3] == original_inode
        replacement = batch / (name + ".replacement-before-return")
        data = path.read_bytes()
        replacement.write_bytes(data)
        replacement.chmod(path.stat().st_mode & 0o777)
        replacement.replace(path)
        assert path.read_bytes() == data and path.stat().st_ino != original_inode
        replaced.append(name)
        return published

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", replace_before_return)
    result = _run(prepared, seen.append)
    assert replaced == [name] and seen == []
    _assert_pregate_refusal(
        batch, result, cleanup_calls, "native_trusted_attempt_registered_context_drift",
    )


def test_observer_refuses_legacy_publication_without_original_creation_pins(tmp_path, monkeypatch):
    prepared = _attempt(tmp_path)
    *_, batch = prepared
    publish = runner.publish_trusted_bootstrap_registration
    seen = []
    cleanup_calls = _track_native_cleanup(monkeypatch)
    legacy_returned = []

    def legacy_result(*args, **kwargs):
        published = publish(*args, **kwargs)
        legacy = PublishedTrustedBootstrapRegistration(published.registration, published.handoff)
        legacy_returned.append((legacy.registration_file_identity, legacy.handoff_file_identity))
        return legacy

    monkeypatch.setattr(runner, "publish_trusted_bootstrap_registration", legacy_result)
    result = _run(prepared, seen.append)
    assert legacy_returned == [(None, None)]
    assert seen == []
    _assert_pregate_refusal(
        batch, result, cleanup_calls, "native_trusted_attempt_registered_context_drift",
    )
