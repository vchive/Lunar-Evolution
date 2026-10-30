"""Worker-local original-context inspection; real local native fixtures only."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_attempt import _attempt, _materialize_valid_capture

from lunar_evolution import external_worker_native_lifecycle as local
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution._candidate_workspace_io import DirectoryChain
from lunar_evolution.external_worker_native_lifecycle import (
    WorkerNativeLifecycleError,
    WorkerNativeLifecycleResolver,
    WorkerNativeTaskMapping,
    native_lifecycle_lookup,
)
from lunar_evolution.external_worker_origin import WorkerOriginContext
from lunar_evolution.native_trusted_attempt import run_native_trusted_attempt
from lunar_evolution.producer_process import _file_identity
from lunar_evolution.rsi_gateway import SolverRequest

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")


def _authority(report):
    for field in ("publication_eligible", "native_success", "remote_cleanup_verified", "publication_authority"):
        assert report[field] is False


def _tree(path):
    return {str(p.relative_to(path)): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_ino,
                                       p.stat().st_mtime_ns, p.stat().st_ctime_ns)
            for p in path.rglob("*") if p.is_file()}


def _same_bytes(path):
    raw = path.read_bytes()
    other = path.with_name(path.name + ".replacement")
    other.write_bytes(raw)
    other.chmod(0o600)
    old = path.stat().st_ino
    os.replace(other, path)
    assert path.read_bytes() == raw and path.stat().st_ino != old


@pytest.fixture
def h(tmp_path):
    prepared = _attempt(tmp_path)
    workspace, producer_root, intent, attestation, artifact, batch = prepared
    context = WorkerOriginContext("controller", "controller-run", "controller-task", "episode-1",
                                  "native-claim", "b" * 64, "c" * 64, 1)
    request = SolverRequest.build(
        episode_id=context.episode_id, contract_sha256=intent.contract_sha256,
        evaluator_sha256=intent.evaluator_fingerprint, environment_sha256=intent.environment_sha256,
        memory_snapshot_sha256="d" * 64, solver_id="native-fixture",
        budget={"wall_timeout_seconds": 30, "deadline_unix": time.time() + 30},
        practice_charter={"goal": "local 原始上下文"},
    )
    profile = "e" * 64
    mapping = WorkerNativeTaskMapping(context.run_id, context.task_id, context.episode_id,
                                      intent.run_id, intent.parent_task_id, intent.task_id)
    job = tmp_path / hashlib.sha256(context.episode_id.encode()).hexdigest()
    job.mkdir(mode=0o700)
    chain = DirectoryChain(job, "fixture worker chain changed")
    wire = {"schema_version": "lunar-external-worker-channel-v1", "context": context.to_dict(),
            "request": request.to_dict(), "request_sha256": request.digest(), "profile_sha256": profile,
            "timeout_seconds": 30, "deadline_unix": dict(request.budget)["deadline_unix"],
            "worker_id": "worker", "host_id": "host", "host_boot_id": "boot", "key_id": "key"}
    raw = wrapper.worker_json(wire)
    pin = wrapper._publish(chain.fd, "intent.json", raw, capture_identity=True)
    resolver = WorkerNativeLifecycleResolver()
    kwargs = {"context": context, "request": request, "profile_sha256": profile, "mapping": mapping,
              "intent": intent, "attestation": attestation, "artifact": artifact, "workspace": workspace,
              "producer_root": producer_root, "episode_directory": job, "original_episode_chain": chain,
              "original_worker_intent": raw, "original_worker_intent_identity": pin}
    lookup = native_lifecycle_lookup(context=context, request_sha256=request.digest(), profile_sha256=profile)
    result = SimpleNamespace(prepared=prepared, workspace=workspace, producer_root=producer_root,
                             intent=intent, attestation=attestation, artifact=artifact, batch=batch,
                             job=job, chain=chain, raw=raw, pin=pin, kwargs=kwargs, resolver=resolver,
                             lookup=lookup, context=context, request=request, mapping=mapping)
    try:
        yield result
    finally:
        resolver.close()
        chain.close()


def _run(h, observer):
    return run_native_trusted_attempt(h.workspace, producer_root=h.producer_root,
                                     intent=h.intent, attestation=h.attestation, artifact=h.artifact,
                                     registered_observer=observer)


def _bind_and_run(h):
    observer = h.resolver.prepare_observer(**h.kwargs)
    result = _run(h, observer)
    assert result.gate_released and result.target_started and result.exit_code == 0
    return observer


def test_real_pregate_binding_and_missing_terminal_then_process_only_are_read_only(h):
    bind = h.resolver.prepare_observer(**h.kwargs)
    seen = []
    assert h.resolver.inspect(h.lookup)["status"] == "context_unavailable"

    def observer(context):
        assert not (h.batch / "work" / "marker").exists()
        bind(context)
        assert (h.job / "native-context.json").exists()
        before = _tree(h.workspace), _tree(h.job)
        report = h.resolver.inspect(h.lookup)
        assert (report["status"], report["reason"]) == ("recovery_required", "native_terminal_missing")
        assert (_tree(h.workspace), _tree(h.job)) == before
        _authority(report)
        seen.append(report)

    result = _run(h, observer)
    assert len(seen) == 1 and result.gate_released and result.exit_code == 0
    before = _tree(h.workspace), _tree(h.job)
    report = h.resolver.inspect(h.lookup)
    assert report["status"] == "process_only" and report["native_process_status"] == "exited_zero"
    assert report["terminal_sha256"] is not None and report["binding_sha256"] is not None
    assert (_tree(h.workspace), _tree(h.job)) == before
    _authority(report)
    public = wrapper.worker_json(report).decode()
    assert str(h.workspace) not in public and str(h.artifact.path) not in public
    assert h.attestation.nonce not in public and '"pid"' not in public


def test_complete_existing_capture_is_diagnostic_and_does_not_change_authority(h):
    _bind_and_run(h)
    terminal = json.loads((h.batch / "native-trusted-process-terminal.json").read_bytes())
    _materialize_valid_capture(h.batch, h.intent, terminal)
    before = _tree(h.workspace), _tree(h.job)
    report = h.resolver.inspect(h.lookup)
    assert report["status"] == "lifecycle_observed"
    assert (_tree(h.workspace), _tree(h.job)) == before
    _authority(report)


def test_new_resolver_does_not_reconstruct_original_objects_from_durable_pin(h):
    _bind_and_run(h)
    assert (h.job / "native-context.json").exists()
    restarted = WorkerNativeLifecycleResolver()
    try:
        report = restarted.inspect(h.lookup)
        assert report["status"] == "context_unavailable"
        _authority(report)
    finally:
        restarted.close()
    h.resolver.close()
    assert h.resolver.inspect(h.lookup)["status"] == "context_unavailable"


def test_replayed_preparation_and_observer_never_replace_original_pin(h):
    observer = h.resolver.prepare_observer(**h.kwargs)
    with pytest.raises(WorkerNativeLifecycleError, match="binding_replayed"):
        h.resolver.prepare_observer(**h.kwargs)
    captured = []

    def bind(context):
        observer(context)
        captured.append(context)

    assert _run(h, bind).exit_code == 0 and len(captured) == 1
    before = _tree(h.job)
    with pytest.raises(WorkerNativeLifecycleError, match="binding_replayed"):
        observer(captured[0])
    assert _tree(h.job) == before


@pytest.mark.parametrize("field", ["workspace", "artifact", "attestation", "pid", "cleanup", "action"])
def test_public_selector_refuses_path_pid_attestation_and_action_fields(h, monkeypatch, field):
    def forbidden(*args, **kwargs):
        raise AssertionError("native recovery must not be reached")

    monkeypatch.setattr(local, "recover_native_trusted_attempt", forbidden)
    value = json.loads(h.lookup)
    value[field] = "caller-selected"
    with pytest.raises(WorkerNativeLifecycleError, match="lookup_invalid"):
        h.resolver.inspect(wrapper.worker_json(value))
    assert not h.batch.exists()


@pytest.mark.parametrize("field", ["worker_run_id", "worker_task_id", "episode_id",
                                    "native_run_id", "native_parent_task_id", "native_task_id"])
def test_explicit_original_assignment_and_native_mapping_must_match_every_identity(h, field):
    kwargs = {**h.kwargs, "mapping": replace(h.mapping, **{field: "wrong"})}
    with pytest.raises(WorkerNativeLifecycleError, match="mapping_mismatch"):
        h.resolver.prepare_observer(**kwargs)
    assert not h.batch.exists() and not (h.job / "native-context.json").exists()


@pytest.mark.parametrize("field", ["contract_sha256", "evaluator_sha256", "environment_sha256"])
def test_original_request_fingerprints_must_match_native_intent(h, field):
    request = replace(h.request, **{field: "f" * 64})
    wire = json.loads(h.raw)
    wire.update(request=request.to_dict(), request_sha256=request.digest())
    raw = wrapper.worker_json(wire)
    # New trusted fixture publication supplies its actual creator pin.
    (h.job / "intent.json").unlink()
    pin = wrapper._publish(h.chain.fd, "intent.json", raw, capture_identity=True)
    with pytest.raises(WorkerNativeLifecycleError, match="mapping_mismatch"):
        h.resolver.prepare_observer(**{**h.kwargs, "request": request,
                                       "original_worker_intent": raw, "original_worker_intent_identity": pin})
    assert not h.batch.exists()


@pytest.mark.parametrize("target", ["worker-intent", "registration", "handoff", "deadline", "binding"])
def test_same_byte_inode_replacement_is_drift_even_when_contents_are_unchanged(h, target):
    _bind_and_run(h)
    path = {"worker-intent": h.job / "intent.json", "binding": h.job / "native-context.json",
            "registration": h.batch / "process-registration.json",
            "handoff": h.batch / "trusted-bootstrap-handoff.json",
            "deadline": h.batch / "native-trusted-attempt-deadline.json"}[target]
    _same_bytes(path)
    report = h.resolver.inspect(h.lookup)
    assert report["status"] == "context_drift" and report["terminal_sha256"] is None
    _authority(report)


def test_replacement_during_recovery_discards_observation_and_never_requests_cleanup(h, monkeypatch):
    _bind_and_run(h)
    recover = local.recover_native_trusted_attempt
    calls = []

    def observe(*args, **kwargs):
        assert kwargs["cleanup"] is False
        result = recover(*args, **kwargs)
        calls.append(result)
        _same_bytes(h.batch / "process-registration.json")
        return result

    monkeypatch.setattr(local, "recover_native_trusted_attempt", observe)
    report = h.resolver.inspect(h.lookup)
    assert len(calls) == 1 and report["status"] == "context_drift"
    assert report["terminal_sha256"] is None
    _authority(report)


def test_inspection_calls_existing_readers_without_publish_signal_or_launch(h, monkeypatch):
    _bind_and_run(h)
    recover = local.recover_native_trusted_attempt
    audit = local.audit_native_trusted_lifecycle
    calls = []

    def forbidden(*args, **kwargs):
        raise AssertionError("read-only inspection attempted a side effect")

    def observe(*args, **kwargs):
        assert kwargs["cleanup"] is False
        calls.append("recover")
        return recover(*args, **kwargs)

    def observe_audit(*args, **kwargs):
        calls.append("audit")
        return audit(*args, **kwargs)

    monkeypatch.setattr(local, "recover_native_trusted_attempt", observe)
    monkeypatch.setattr(local, "audit_native_trusted_lifecycle", observe_audit)
    monkeypatch.setattr(local, "_publish", forbidden)
    monkeypatch.setattr(os, "kill", forbidden)
    monkeypatch.setattr(os, "killpg", forbidden)
    before = _tree(h.workspace), _tree(h.job)
    report = h.resolver.inspect(h.lookup)
    assert calls == ["recover", "audit"] and report["status"] == "process_only"
    assert (_tree(h.workspace), _tree(h.job)) == before
    _authority(report)


def test_original_object_mutation_is_not_rebased_to_current_request(h):
    _bind_and_run(h)
    object.__setattr__(h.request, "contract_sha256", "f" * 64)
    report = h.resolver.inspect(h.lookup)
    assert report["status"] == "context_drift"
    _authority(report)


def test_same_byte_worker_intent_replacement_before_preparation_is_not_original_creator(h):
    _same_bytes(h.job / "intent.json")
    with pytest.raises(WorkerNativeLifecycleError, match="context_drift"):
        h.resolver.prepare_observer(**h.kwargs)
    assert not h.batch.exists()


def test_registered_context_must_use_original_installed_workspace(h):
    observer = h.resolver.prepare_observer(**h.kwargs)
    called = []

    def wrong_workspace(context):
        called.append(True)
        observer(replace(context, workspace=str(h.job)))

    result = _run(h, wrong_workspace)
    assert called == [True] and not result.gate_released and not result.target_started
    assert not (h.job / "native-context.json").exists()
    assert not (h.batch / "work" / "marker").exists()
    assert h.resolver.inspect(h.lookup)["status"] == "context_unavailable"


def test_native_creator_pin_replacement_before_binding_keeps_target_gate_closed(h):
    observer = h.resolver.prepare_observer(**h.kwargs)
    called = []

    def changed_registration(context):
        _same_bytes(h.batch / "process-registration.json")
        called.append(True)
        observer(context)

    result = _run(h, changed_registration)
    assert called == [True] and not result.gate_released and not result.target_started
    assert not (h.job / "native-context.json").exists()
    assert not (h.batch / "work" / "marker").exists()


def test_worker_writer_retains_exact_non_ascii_bytes_and_creator_identity(tmp_path):
    job = tmp_path / "job"
    job.mkdir(mode=0o700)
    chain = DirectoryChain(job, "fixture directory changed")
    try:
        raw = wrapper.worker_json({"goal": "原始字节"})
        pin = wrapper._publish(chain.fd, "intent.json", raw, capture_identity=True)
        assert (job / "intent.json").read_bytes() == raw and b"\\u" not in raw
        assert pin == tuple(_file_identity(job / "intent.json").values())
        assert wrapper._publish(chain.fd, "default.json", raw) is None
        with pytest.raises(FileExistsError):
            wrapper._publish(chain.fd, "intent.json", b"different", capture_identity=True)
        assert (job / "intent.json").read_bytes() == raw
    finally:
        chain.close()


@pytest.mark.parametrize("capture", [False, True])
def test_worker_writer_capture_opt_in_alone_holds_write_fd_through_directory_fsync(tmp_path, monkeypatch, capture):
    job = tmp_path / "job"
    job.mkdir(mode=0o700)
    chain = DirectoryChain(job, "fixture directory changed")
    original_open, original_fsync = os.open, os.fsync
    writes, observations = [], []

    def opened(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if path == "intent.json.pending":
            writes.append(fd)
        return fd

    def synced(fd):
        if fd == chain.fd:
            try:
                os.fstat(writes[0])
                observations.append(True)
            except OSError:
                observations.append(False)
        return original_fsync(fd)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "fsync", synced)
    try:
        pin = wrapper._publish(chain.fd, "intent.json", b"{}", capture_identity=capture)
        assert observations == [capture]
        assert (pin is not None) is capture
        with pytest.raises(OSError):
            os.fstat(writes[0])
    finally:
        chain.close()


def test_worker_writer_detects_same_byte_replacement_before_return_from_publication(tmp_path, monkeypatch):
    job = tmp_path / "job"
    job.mkdir(mode=0o700)
    chain = DirectoryChain(job, "fixture directory changed")
    original = os.fsync
    replacements = []

    def synced(fd):
        original(fd)
        if fd == chain.fd:
            _same_bytes(job / "intent.json")
            replacements.append(True)

    monkeypatch.setattr(os, "fsync", synced)
    try:
        with pytest.raises(wrapper.WorkerWrapperError, match="state_write_failed"):
            wrapper._publish(chain.fd, "intent.json", b"{}", capture_identity=True)
        assert replacements == [True]
    finally:
        chain.close()


@pytest.mark.parametrize("failure", ["write", "file-fsync", "published-stat"])
def test_worker_capture_writer_closes_original_fd_on_failure(tmp_path, monkeypatch, failure):
    job = tmp_path / "job"
    job.mkdir(mode=0o700)
    chain = DirectoryChain(job, "fixture directory changed")
    original_open, original_write, original_fsync, original_stat = os.open, os.write, os.fsync, os.stat
    writes = []

    def opened(path, flags, *args, **kwargs):
        fd = original_open(path, flags, *args, **kwargs)
        if path == "intent.json.pending":
            writes.append(fd)
        return fd

    def written(fd, data):
        if failure == "write" and fd in writes:
            raise OSError("fixture private write failure")
        return original_write(fd, data)

    def synced(fd):
        if failure == "file-fsync" and fd in writes:
            raise OSError("fixture private sync failure")
        return original_fsync(fd)

    def stated(path, *args, **kwargs):
        if failure == "published-stat" and path == "intent.json" and kwargs.get("dir_fd") == chain.fd:
            raise OSError("fixture private stat failure")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "write", written)
    monkeypatch.setattr(os, "fsync", synced)
    monkeypatch.setattr(os, "stat", stated)
    try:
        with pytest.raises(OSError):
            wrapper._publish(chain.fd, "intent.json", b"{}", capture_identity=True)
        assert len(writes) == 1
        with pytest.raises(OSError):
            os.fstat(writes[0])
    finally:
        chain.close()


def test_equal_intent_bytes_in_different_private_directory_cannot_supply_original_chain(h):
    other = h.job.with_name("other-private-episode")
    other.mkdir(mode=0o700)
    other_chain = DirectoryChain(other, "fixture other directory changed")
    try:
        other_pin = wrapper._publish(other_chain.fd, "intent.json", h.raw, capture_identity=True)
        assert (other / "intent.json").read_bytes() == (h.job / "intent.json").read_bytes()
        assert other_pin != h.pin
        with pytest.raises(WorkerNativeLifecycleError, match="context_drift"):
            h.resolver.prepare_observer(**{**h.kwargs, "original_episode_chain": other_chain})
        assert not h.batch.exists()
        assert not (h.job / "native-context.json").exists()
        assert not (other / "native-context.json").exists()
    finally:
        other_chain.close()
