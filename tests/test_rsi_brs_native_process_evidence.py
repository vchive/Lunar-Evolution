"""Native process evidence is local, read-only, and never BRS thread authority."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from lunar_evolution import native_trusted_receipt as receipt_module
from lunar_evolution import rsi_brs_native_process_evidence as evidence
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_bootstrap import NativeBootstrapArtifact
from lunar_evolution.native_trusted_attempt import _terminal_receipt
from lunar_evolution.native_trusted_cleanup import _record
from lunar_evolution.process_ownership import ProcessCleanupResult, ProcessCleanupStatus
from lunar_evolution.producer_bootstrap import (
    TrustedBootstrapDescriptor,
    build_trusted_bootstrap_launch,
)
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.producer_process import (
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
    _digest_without,
    _identity_digest,
    parse_producer_execution_receipt,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan

H = "a" * 64


def _plan(**overrides) -> NativeRSIExecutionPlan:
    memory = MemorySnapshot("native-process-fixture", H, ())
    request = SolverRequest.build(
        episode_id="episode", contract_sha256=H, evaluator_sha256=H,
        environment_sha256=H, memory_snapshot_sha256=memory.digest(), solver_id="native",
        solver_settings={}, budget={}, practice_charter={},
    )
    kwargs = {
        "request": request, "memory_snapshot": memory, "journal_id": "journal", "launch_id": "launch",
        "run_id": "run", "parent_task_id": "parent", "task_id": "task", "intent_sha256": H,
        "attestation_sha256": H, "bootstrap_descriptor_sha256": H, "bootstrap_artifact_sha256": H,
        "manifest_sha256": H, "candidate_selector_sha256": H, "evaluator_kind": "local",
        "evaluator_fingerprint": H,
    }
    kwargs.update(overrides)
    return NativeRSIExecutionPlan.build(**kwargs)


def _forbidden(*_args, **_kwargs):
    raise AssertionError("unexpected process, native write, or backfill")


def _resign(value: dict) -> dict:
    value["binding_sha256"] = evidence._digest(value, "binding_sha256")
    return value


def test_unknown_capture_is_detached_and_never_backfills(tmp_path, monkeypatch):
    binding = evidence.capture_native_process_binding(workspace=tmp_path, native_plan=_plan())
    assert binding["role"] == "native-producer-process"
    assert binding["status"] == "unknown"
    assert binding["references"] is None and binding["entries"] == {}
    parsed = evidence.parse_native_process_binding(binding)
    binding["workspace"]["inode"] += 1
    assert parsed["workspace"]["inode"] != binding["workspace"]["inode"]
    monkeypatch.setattr(evidence, "_records", _forbidden)
    monkeypatch.setattr(evidence, "_workspace", _forbidden)
    observed = evidence.observe_native_process_binding(parsed, workspace=tmp_path, native_plan=_plan())
    assert observed["status"] == "unknown"
    assert observed["cleanup_confirmed"] is False
    assert observed["reason"] == "original_capture_unknown"


@pytest.mark.parametrize("field,value", [
    ("status", {}), ("role", "brs-thread"), ("reason", "invented"),
    ("references", {"pid": 123}), ("entries", {"current": {}}),
    ("native_plan_sha256", "not-a-digest"),
])
def test_parser_rejects_resigned_invalid_capture_without_hooks(tmp_path, field, value):
    binding = evidence.capture_native_process_binding(workspace=tmp_path, native_plan=_plan())
    binding[field] = value
    _resign(binding)
    with pytest.raises(evidence.BRSNativeProcessEvidenceError):
        evidence.parse_native_process_binding(binding)


def test_parser_rejects_caller_objects_and_digest_drift(tmp_path):
    class Trap(dict):
        def __iter__(self):
            _forbidden()

        def items(self):
            _forbidden()

    with pytest.raises(evidence.BRSNativeProcessEvidenceError, match="wire_invalid"):
        evidence.parse_native_process_binding(Trap())
    binding = evidence.capture_native_process_binding(workspace=tmp_path, native_plan=_plan())
    binding["binding_sha256"] = "b" * 64
    with pytest.raises(evidence.BRSNativeProcessEvidenceError, match="digest_mismatch"):
        evidence.parse_native_process_binding(binding)


def test_absent_or_symlink_workspace_is_unknown_and_read_only(tmp_path):
    missing = tmp_path / "missing"
    binding = evidence.capture_native_process_binding(workspace=missing, native_plan=_plan())
    assert binding["status"] == "unknown" and binding["workspace"] is None
    assert not missing.exists()
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    binding = evidence.capture_native_process_binding(workspace=link, native_plan=_plan())
    assert binding["reason"] == "native_workspace_unavailable"


def _bound(tmp_path, monkeypatch):
    """Real records/readers; only native process terminal/projection are inert doubles.

    Nothing compiles or executes the two inert executable files. OS observations
    are explicitly doubled by each test, and no live PID is claimed as a fixture.
    """
    workspace, producer = tmp_path / "workspace", tmp_path / "producer"
    workspace.mkdir()
    producer.mkdir()
    target, bootstrap = producer / "target", tmp_path / "bootstrap"
    for file in (target, bootstrap):
        file.write_bytes(b"inert nonexecutable fixture bytes\n")
        file.chmod(0o700)
    intent = build_producer_launch_intent(
        producer_root=producer, launch_id="launch", journal_id="journal", run_id="run",
        parent_task_id="parent", task_id="task", contract_sha256=H,
        evaluator_kind="local", evaluator_fingerprint=H, runner_fingerprint=H,
        generator_fingerprint=H, dependency_sha256=H, environment_sha256=H,
        producer_id="fixture", producer_fingerprint=H, executable_relative="target",
        argv=("target",), working_directory="work", output_directory="output",
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024, wall_timeout_seconds=30,
    )
    attestation = build_producer_launch_attestation(intent, "nonce")
    info = bootstrap.stat()
    descriptor = TrustedBootstrapDescriptor(
        implementation_version="inert-native-fixture", bootstrap_sha256=hashlib.sha256(bootstrap.read_bytes()).hexdigest(),
        size=info.st_size, device=info.st_dev, inode=info.st_ino,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns, allowlist_id="fixture",
        platform_execution_mode="darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound",
    )
    artifact = NativeBootstrapArtifact(
        bootstrap, H, descriptor.bootstrap_sha256, "inert-fixture", descriptor.platform_execution_mode,
        descriptor.allowlist_id, descriptor,
    )
    plan = _plan(intent_sha256=intent.intent_sha256, attestation_sha256=attestation.attestation_sha256,
                 bootstrap_descriptor_sha256=descriptor.digest(), bootstrap_artifact_sha256=artifact.artifact_sha256)
    launch = build_trusted_bootstrap_launch(intent, attestation, descriptor)
    pid = 434343
    owner = ({"kind": "darwin-libproc-starttime-v1", "pid": pid, "start_sec": 123, "start_usec": 1}
             if sys.platform == "darwin" else
             {"kind": "linux-proc-starttime-v1", "pid": pid, "boot_id": "inert-boot", "starttime_ticks": 123})
    mode = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-sealed-memfd"
    batch = workspace / "evolution/producer-batches/journal"
    batch.mkdir(parents=True)
    lock = batch / "fixture-original-lock"
    lock.write_bytes(b"")
    lock_info = lock.stat()
    registration = {
        "schema_version": "1", "protocol": "lunar-producer-process-execution-v1",
        **{key: getattr(intent, key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        )},
        "attestation_sha256": attestation.attestation_sha256, "consumption_sha256": H,
        "executable_identity": _identity_digest({
            "sha256": descriptor.bootstrap_sha256, "size": descriptor.size,
            "device": descriptor.device, "inode": descriptor.inode,
            "mtime_ns": descriptor.mtime_ns, "ctime_ns": descriptor.ctime_ns,
        }),
        "owner_identity": owner, "owner_identity_sha256": hashlib.sha256(canonical_json(owner)).hexdigest(),
        "execution_binding": mode,
        "execution_snapshot_relative_path": ".producer-snapshots/bootstrap" if sys.platform == "darwin" else None,
        "execution_snapshot_sha256": descriptor.bootstrap_sha256, "execution_snapshot_size": descriptor.size,
        "pid": pid, "pgid": pid, "recovery_lock_protocol": "journal-flock-v1",
        "recovery_lock_device": lock_info.st_dev, "recovery_lock_inode": lock_info.st_ino,
        "gate_protocol": launch.gate_protocol, "registered_at_unix_ns": 123,
        "launch_sha256": launch.digest(), "bootstrap_descriptor_sha256": descriptor.digest(),
        "target_executable_identity": launch.target_executable_identity,
        "target_execution_binding": mode,
        "target_execution_snapshot_relative_path": ".producer-snapshots/target" if sys.platform == "darwin" else None,
        "target_execution_snapshot_sha256": launch.target_executable_identity,
        "target_execution_snapshot_size": intent.executable_size,
    }
    registration["registration_sha256"] = _digest_without(registration, "registration_sha256")
    cleanup = _record(intent, registration["registration_sha256"], H,
                      ProcessCleanupResult("fixture", pid, pid, ProcessCleanupStatus.ALREADY_EXITED))
    terminal = _terminal_receipt(
        registration, handoff_sha256=H, evidence_sha256=H, gate_released=True, target_started=True,
        exit_code=0, cleanup_status=cleanup["cleanup_status"], deadline_sha256=H,
        stream_capture_sha256=H, cleanup_sha256=cleanup["cleanup_sha256"],
    )
    receipt = ProducerExecutionReceipt(
        **{key: getattr(intent, key) for key in (
            "launch_id", "journal_id", "run_id", "parent_task_id", "task_id", "intent_sha256",
        )},
        attestation_sha256=attestation.attestation_sha256, consumption_sha256=H,
        registration_sha256=registration["registration_sha256"], executable_identity=H,
        pid=pid, pgid=pid, owner_identity=owner, gate_released=True,
        request_timeout_seconds=1, max_requests=1, output_max_bytes=1024, wall_timeout_seconds=30,
        request_count=0, exit_code=0,
        stdout_evidence=ProducerStreamEvidence("stdout", 0, hashlib.sha256(b"").hexdigest(), False, "complete"),
        stderr_evidence=ProducerStreamEvidence("stderr", 0, hashlib.sha256(b"").hexdigest(), False, "complete"),
        envelope_evidence=None, cleanup_status=cleanup["cleanup_status"], cleanup_sha256=cleanup["cleanup_sha256"],
        execution_binding=mode,
        execution_snapshot_relative_path=registration["target_execution_snapshot_relative_path"],
        execution_snapshot_sha256=intent.executable_sha256, execution_snapshot_size=intent.executable_size,
        status="completed", previous_receipt_sha256=registration["registration_sha256"],
        trusted_execution={"terminal_sha256": terminal["terminal_sha256"], "stream_capture_sha256": H,
                           "output_capture_sha256": H, "cleanup_sha256": cleanup["cleanup_sha256"],
                           "broker_coverage": "none"},
    )
    records = dict(zip(evidence._NAMES, (registration, receipt.to_dict(), terminal, cleanup), strict=True))
    for name, record in records.items():
        (batch / name).write_bytes(canonical_json(record))

    def terminal_projection(*_args, **kwargs):
        assert kwargs["cleanup"] is False
        return copy.deepcopy(terminal)

    def receipt_projection(*_args, **kwargs):
        assert kwargs["require_broker"] is True
        return parse_producer_execution_receipt(receipt.to_dict())

    monkeypatch.setattr(evidence, "recover_native_trusted_attempt", terminal_projection)
    monkeypatch.setattr(receipt_module, "build_native_trusted_execution_receipt", receipt_projection)
    context = {"workspace": workspace, "native_plan": plan, "intent": intent, "attestation": attestation, "artifact": artifact}
    return SimpleNamespace(context=context, batch=batch, owner=owner, records=records)


def _os(monkeypatch, *, owner=None, pid="absent", group="absent", pgid=None):
    monkeypatch.setattr(evidence, "_process_owner_identity", lambda _pid: copy.deepcopy(owner))

    def probe(_pid, signal):
        assert signal == 0
        if pid == "absent":
            raise ProcessLookupError()
        if pid == "denied":
            raise PermissionError()

    def probe_group(_pgid, signal):
        assert signal == 0
        if group == "absent":
            raise ProcessLookupError()
        if group == "denied":
            raise PermissionError()

    monkeypatch.setattr(evidence.os, "kill", probe)
    monkeypatch.setattr(evidence.os, "killpg", probe_group)
    monkeypatch.setattr(evidence.os, "getpgid", lambda _pid: pgid or _pid)


def test_real_file_capture_and_double_read_observation_are_detached_and_zero_write(tmp_path, monkeypatch):
    fixture = _bound(tmp_path, monkeypatch)
    before = {p: (p.read_bytes(), p.stat().st_ino) for p in fixture.batch.iterdir()}
    binding = evidence.capture_native_process_binding(**fixture.context)
    assert binding["status"] == "captured", binding["reason"]
    assert binding["entries"]["process-registration.json"]["inode"] == (fixture.batch / "process-registration.json").stat().st_ino
    _os(monkeypatch)
    observed = evidence.observe_native_process_binding(binding, **fixture.context)
    assert observed["status"] == "exited" and observed["cleanup_confirmed"] is True
    assert set(observed).isdisjoint({"terminal_status", "native_claim_sha256", "owner_result_sha256", "result_evidence_sha256"})
    assert before == {p: (p.read_bytes(), p.stat().st_ino) for p in fixture.batch.iterdir()}
    assert observed["observation_sha256"] == evidence._digest(observed, "observation_sha256")
    assert evidence.parse_native_process_binding(json.loads(json.dumps(binding))) == binding


@pytest.mark.parametrize("state,expected", [
    ("running", "running"), ("reused", "drifted"), ("group_changed", "drifted"),
    ("leader_absent_group_present", "unknown"), ("identity_unavailable", "unknown"),
    ("pid_denied", "unknown"), ("group_denied", "unknown"),
])
def test_process_probes_never_signal_or_infer_cleanup(tmp_path, monkeypatch, state, expected):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(**fixture.context)
    owner = fixture.owner if state in {"running", "reused", "group_changed"} else None
    if state == "reused":
        owner = dict(owner, pid=99999)
    _os(monkeypatch, owner=owner, pid="denied" if state == "pid_denied" else "present" if state == "identity_unavailable" else "absent",
        group="denied" if state == "group_denied" else "present",
        pgid=99999 if state == "group_changed" else None)
    observed = evidence.observe_native_process_binding(binding, **fixture.context)
    assert observed["status"] == expected
    assert observed["cleanup_confirmed"] is False


@pytest.mark.parametrize("name", evidence._NAMES)
def test_same_bytes_entry_replacement_is_drift_and_never_adopted(tmp_path, monkeypatch, name):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(**fixture.context)
    path = fixture.batch / name
    raw = path.read_bytes()
    path.rename(fixture.batch / (name + ".original"))
    path.write_bytes(raw)
    _os(monkeypatch)
    for _ in range(2):
        observed = evidence.observe_native_process_binding(binding, **fixture.context)
        assert observed["status"] == "drifted" and observed["cleanup_confirmed"] is False
    assert binding["entries"][name]["inode"] != path.stat().st_ino


def test_missing_original_context_stays_unknown_without_native_reads(tmp_path, monkeypatch):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(**fixture.context)
    monkeypatch.setattr(evidence, "_records", _forbidden)
    observed = evidence.observe_native_process_binding(binding, workspace=fixture.context["workspace"],
                                                       native_plan=fixture.context["native_plan"])
    assert observed["status"] == "unknown" and observed["cleanup_confirmed"] is False


def test_original_capture_unknown_cannot_be_upgraded_when_records_appear(tmp_path, monkeypatch):
    fixture = _bound(tmp_path, monkeypatch)
    unknown = evidence.capture_native_process_binding(workspace=fixture.context["workspace"],
                                                       native_plan=fixture.context["native_plan"])
    monkeypatch.setattr(evidence, "_records", _forbidden)
    observed = evidence.observe_native_process_binding(unknown, **fixture.context)
    assert observed["reason"] == "original_capture_unknown"
    assert observed["status"] == "unknown" and unknown["references"] is None


def test_entry_replacement_during_os_observation_is_drift(tmp_path, monkeypatch):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(**fixture.context)

    def replace_after_verified_read(_refs):
        path = fixture.batch / "native-trusted-cleanup.json"
        raw = path.read_bytes()
        path.rename(fixture.batch / "old-cleanup")
        path.write_bytes(raw)
        return "exited", "absent", None

    monkeypatch.setattr(evidence, "_process", replace_after_verified_read)
    observed = evidence.observe_native_process_binding(binding, **fixture.context)
    assert observed["status"] == "drifted" and observed["cleanup_confirmed"] is False


def test_missing_or_invalid_records_capture_unknown_without_repair(tmp_path, monkeypatch):
    fixture = _bound(tmp_path, monkeypatch)
    path = fixture.batch / "native-trusted-cleanup.json"
    path.unlink()
    binding = evidence.capture_native_process_binding(**fixture.context)
    assert binding["status"] == "unknown" and binding["references"] is None
    assert not path.exists()
    path.write_bytes(b'{"invalid":true}')
    binding = evidence.capture_native_process_binding(**fixture.context)
    assert binding["status"] == "unknown" and binding["entries"] == {}
    assert path.read_bytes() == b'{"invalid":true}'


@pytest.mark.parametrize("captured", [False, True])
def test_changed_plan_or_path_is_drift_even_for_unknown_capture(tmp_path, monkeypatch, captured):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(
        **fixture.context if captured else {key: fixture.context[key] for key in ("workspace", "native_plan")},
    )
    monkeypatch.setattr(evidence, "_records", _forbidden)
    monkeypatch.setattr(evidence, "_workspace", _forbidden)
    context = dict(fixture.context, native_plan=_plan())
    assert evidence.observe_native_process_binding(binding, **context)["status"] == "drifted"
    context = dict(fixture.context, workspace=tmp_path / "foreign")
    assert evidence.observe_native_process_binding(binding, **context)["status"] == "drifted"


@pytest.mark.parametrize("mutation", ["pid_bool", "foreign_group", "identity_digest", "entry_field"])
def test_known_parser_rejects_resigned_invalid_native_identity(tmp_path, monkeypatch, mutation):
    fixture = _bound(tmp_path, monkeypatch)
    binding = evidence.capture_native_process_binding(**fixture.context)
    refs = binding["references"]
    if mutation == "pid_bool":
        refs["pid"] = True
    elif mutation == "foreign_group":
        refs["pgid"] += 1
    elif mutation == "identity_digest":
        refs["owner_identity_sha256"] = "0" * 64
    else:
        binding["entries"]["execution-receipt.json"]["creator_pin"] = True
    _resign(binding)
    with pytest.raises(evidence.BRSNativeProcessEvidenceError):
        evidence.parse_native_process_binding(binding)


@pytest.mark.parametrize("kind", ["symlink", "duplicate_key", "hardlink"])
def test_unsafe_capture_entry_is_unknown_and_keeps_original_objects(tmp_path, monkeypatch, kind):
    fixture = _bound(tmp_path, monkeypatch)
    path = fixture.batch / "native-trusted-cleanup.json"
    original = fixture.batch / "original-cleanup"
    path.rename(original)
    if kind == "symlink":
        path.symlink_to(original)
    elif kind == "duplicate_key":
        path.write_bytes(b'{"cleanup_sha256":"a","cleanup_sha256":"b"}')
    else:
        path.hardlink_to(original)
    before = original.read_bytes()
    binding = evidence.capture_native_process_binding(**fixture.context)
    assert binding["status"] == "unknown" and binding["references"] is None
    assert original.read_bytes() == before and path.exists()
