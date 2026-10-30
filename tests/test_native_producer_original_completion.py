"""Real local acquisition with an explicitly inert native-provenance seam.

The broker request/reply, completion pipe, input files, artifact snapshots and
captured envelope reads are real. Native launch/registration/receipt are inert
fixtures; these tests do not accept a static runtime or execute a candidate.
"""

from __future__ import annotations

import copy
import os
import time
from dataclasses import asdict, fields, replace

import pytest
import test_producer_broker_original_exchange as broker_fixture
from test_native_producer_completion_profile import _lifecycle_vector
from test_native_trusted_envelope_acquisition import _original_output
from test_static_python_fixed_producer_evidence import _compose, _fixture
from test_static_python_fixed_profile import _raw, _sha
from test_static_python_producer_completion import _material

from lunar_evolution import native_trusted_attempt as native
from lunar_evolution import producer_broker_ipc as broker
from lunar_evolution import rsi_native_inputs as inputs_module
from lunar_evolution import static_python_fixed_producer_evidence as evidence
from lunar_evolution.native_fixed_live_sink import _pin_fixed_python_live_sink_request
from lunar_evolution.native_trusted_scheduler import _native_handoff_evidence
from lunar_evolution.producer_handoff import ProducerMaterial
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot
from lunar_evolution.static_python_producer_completion import (
    COMPLETION_PROFILE,
    COMPLETION_PROTOCOL,
    FixedProducerCompletionBinding,
    NativeFixedProducerCompletionCapture,
    _original_completion_reader_pin,
)


def _original(tmp_path, monkeypatch, *, input_solver="openevolve", envelope_profile=False, argv_fault=None):
    value = _fixture(tmp_path)
    if envelope_profile:
        from test_native_producer_envelope_profile import _envelope_vector

        request, payload = _envelope_vector()
    else:
        request, payload = _lifecycle_vector()
    memory = MemorySnapshot("completion-memory", None, ())
    solver_request = SolverRequest.build(
        episode_id="completion-fixture", contract_sha256=value.intent.contract_sha256,
        evaluator_sha256=value.intent.evaluator_fingerprint, environment_sha256=value.intent.environment_sha256,
        memory_snapshot_sha256=memory.digest(), solver_id=input_solver,
        solver_settings={"model": "fixture-model", "task": "Remove redundant work.",
                         "initial_program": "# EVOLVE-BLOCK-START\ndef solve(x):\n    return x + 0\n# EVOLVE-BLOCK-END\n"},
        budget={"deadline_unix": time.time() + 120}, practice_charter={},
    )
    inputs = inputs_module.prepare_native_rsi_inputs(
        tmp_path, journal_id=value.intent.journal_id, request=solver_request, memory=memory,
    )
    # Only the launch/registration seam is inert. A real run obtains this binding
    # through validate_native_rsi_launch_inputs while its grants remain held.
    inputs = replace(inputs, launch_binding_sha256="c" * 64)
    argv = (value.intent.argv[0], "--lunar-rsi-input-v1", inputs.manifest_sha256)
    if envelope_profile:
        from lunar_evolution.static_python_producer_envelope_source import (
            fixed_producer_envelope_launch_argv,
        )

        argv = fixed_producer_envelope_launch_argv(
            value.intent.argv[0], run_id=value.intent.run_id,
            producer_fingerprint=value.intent.producer_fingerprint, manifest_sha256=inputs.manifest_sha256,
        )
        if argv_fault is not None:
            changed = list(argv)
            index, replacement = {"run-id": (2, "other-run"), "fingerprint": (3, "f" * 64),
                                  "manifest": (5, "f" * 64), "marker": (1, "--foreign-envelope")}[argv_fault]
            changed[index] = replacement
            argv = tuple(changed)
    intent = replace(value.intent, argv=argv, argv_sha256=_sha(_raw(list(argv))), intent_sha256=None)
    intent = replace(intent, intent_sha256=intent.digest())
    value.intent = intent
    value.attestation = build_producer_launch_attestation(intent, "inert-original-completion")
    value.request = request
    monkeypatch.setattr(broker_fixture, "_intent", lambda _path: (None, intent))
    observed_broker, _calls, _response, deadline_ns, _returned = broker_fixture._serve(tmp_path, monkeypatch)
    broker_pin = broker._original_broker_exchange_pin(observed_broker)
    assert broker_pin is not None
    trusted = dict(value.run.receipt.trusted_execution)
    trusted.update(
        broker_journal_identity=observed_broker.journal_identity.to_dict(),
        broker_journal_sha256=observed_broker.journal_sha256,
        broker_journal_bytes=observed_broker.journal_bytes,
        broker_journal_file_identity=list(observed_broker.journal_file_identity),
    )
    receipt = replace(value.run.receipt, intent_sha256=intent.intent_sha256,
                      attestation_sha256=value.attestation.attestation_sha256,
                      trusted_execution=trusted, receipt_sha256=None)
    # Linux executes a sealed snapshot with a different inode than the original
    # source executable. Both identities must retain their distinct bindings.
    image_identity = (55, 66)
    payload.update(manifest_sha256=inputs.manifest_sha256, pid=receipt.pid)
    payload["image"].update(device=image_identity[0], inode=image_identity[1])
    startup = request.compare(_raw(payload) + b"\n", image_device=55, image_inode=66,
                              target_pid=receipt.pid, manifest_sha256=inputs.manifest_sha256)
    source = b"def solve(x):\n    return x\n"
    wrapper = b'{"candidate_path":"candidate.py"}'
    root = inputs.inputs_path.parent / intent.output_directory
    root.mkdir(exist_ok=True)
    snapshots = []
    for path, raw in (("candidate.py", source), ("result.json", wrapper)):
        (root / path).write_bytes(raw)
        (root / path).chmod(0o400)
        content, info = native._stable_bytes(root / path, limit=256 * 1024, deadline=None, monotonic=time.monotonic)
        snapshots.append((path, content, tuple(sorted(info.items()))))
    material = ProducerMaterial(
        kind="candidate_source", path="candidate.py", size=len(source), sha256=_sha(source),
        lineage=value.run.output.envelope.materials[0].lineage,
        external_evidence={"present": False, "score_present": False, "payload_sha256": None},
    )
    output = replace(value.run.output, envelope=replace(value.run.output.envelope, materials=(material,)))
    attempt = replace(value.run.attempt, reason="native_trusted_attempt_request_and_output_unverified",
                      broker_observation=observed_broker, live_modules_observation=startup)
    value.run = replace(value.run, receipt=receipt, output=output, attempt=attempt)
    _original_output(value, tmp_path, monkeypatch)
    envelope = None
    if envelope_profile:
        raw, info = native._stable_bytes(root / "producer-result.json", limit=128 * 1024,
                                         deadline=None, monotonic=time.monotonic)
        envelope = ("producer-result.json", raw, tuple(sorted(info.items())))
    common = {"protocol": COMPLETION_PROTOCOL, "profile": COMPLETION_PROFILE, "solver": "openevolve",
              "manifest_sha256": inputs.manifest_sha256, "target_pid": receipt.pid,
              "deadline_monotonic_ns": deadline_ns}
    records = [{**common, "seq": 0, "phase": "begun"}, {
        **common, "seq": 1, "phase": "committed", "request": _material(inputs.request_json),
        "memory": _material(inputs.memory_json),
        "broker": {"request_id": "req-1", "request_count": 1, "status": 200,
                   "request_body": _material(broker_pin[2]), "reply": _material(broker_pin[4])},
        "artifacts": [{"path": path, **_material(raw)} for path, raw, _stat in snapshots],
    }]
    if envelope_profile:
        from lunar_evolution.static_python_producer_envelope_source import (
            FIXED_PRODUCER_ENVELOPE_PROFILE,
            FIXED_PRODUCER_ENVELOPE_PROTOCOL,
        )

        for record in records:
            record.update(protocol=FIXED_PRODUCER_ENVELOPE_PROTOCOL, profile=FIXED_PRODUCER_ENVELOPE_PROFILE)
        records[1]["envelope"] = {"path": envelope[0], **_material(envelope[1])}
    wire = b"".join(_raw(record) + b"\n" for record in records)
    read_fd, write_fd = os.pipe()
    capture = NativeFixedProducerCompletionCapture(read_fd, deadline=deadline_ns / 1e9).start()
    os.write(write_fd, wire)
    os.close(write_fd)
    acquired_wire = capture.finish()
    attempt = replace(value.run.attempt, producer_completion_bytes=acquired_wire,
                      producer_completion_partial_bytes=capture.partial_bytes)
    value.run = replace(value.run, attempt=attempt)
    native._retain_original_native_completion(
        native._NATIVE_COMPLETION_TOKEN, attempt, inputs=inputs, intent=intent,
        attestation=value.attestation, request=request, reader=capture,
        binding=FixedProducerCompletionBinding("openevolve", receipt.pid, inputs.manifest_sha256, deadline_ns),
        artifacts=tuple(snapshots), image_identity=image_identity, envelope=envelope,
    )
    return value, inputs, capture, root


def test_original_chain_joins_acquired_material_without_runtime_or_admission(tmp_path, monkeypatch):
    value, inputs, capture, _root = _original(tmp_path, monkeypatch)
    pin = native._original_native_completion_pin(value.run.attempt)
    assert pin is not None and pin[2] is inputs and pin[3] is value.intent
    assert pin[10] == (55, 66) != (value.intent.executable_device, value.intent.executable_inode)
    assert _original_completion_reader_pin(capture, value.run.attempt.producer_completion_bytes)[2] is capture._result
    report = _compose(value).to_dict()
    assert report["original_computation_observation_verified"] is True
    assert "original_computation_observation" not in report["missing_evidence"]
    assert set(report["missing_evidence"]) == {
        "original_pycache_observation", "accepted_build_input_custody", "accepted_runtime_authority_root",
    }
    assert report["production_admission"] is report["online_publication"] is False
    assert "_original_completion_acquisition" not in asdict(value.run.attempt)
    assert "_original_completion_acquisition" not in {field.name for field in fields(value.run.attempt)}
    sink_pin = _pin_fixed_python_live_sink_request(value.request, target_sha256=_sha(value.request.image))
    assert _native_handoff_evidence(value.run, sink_pin)


@pytest.mark.parametrize("kind", ("replace", "copy", "deepcopy", "constructor"))
def test_public_and_detached_attempts_cannot_reconstruct_original_completion(tmp_path, monkeypatch, kind):
    value, _inputs, _capture, _root = _original(tmp_path, monkeypatch)
    attempt = value.run.attempt
    if kind == "replace":
        copied = replace(attempt)
    elif kind in {"copy", "deepcopy"}:
        copied = getattr(copy, kind)(attempt)
    else:
        copied = native.NativeTrustedAttemptObservation(**{field.name: getattr(attempt, field.name) for field in fields(attempt)})
    assert native._original_native_completion_pin(copied) is None
    value.run = replace(value.run, attempt=copied)
    assert "original_computation_observation" in _compose(value).to_dict()["missing_evidence"]


@pytest.mark.parametrize("fault", ("raw-copy", "input-copy", "memory", "pid", "image", "deadline", "broker-copy"))
def test_original_completion_rejects_material_and_identity_drift(tmp_path, monkeypatch, fault):
    value, inputs, _capture, _root = _original(tmp_path, monkeypatch)
    attempt = value.run.attempt
    acquired = attempt._original_completion_acquisition
    if fault == "raw-copy":
        object.__setattr__(attempt, "producer_completion_bytes", bytes(bytearray(attempt.producer_completion_bytes)))
    elif fault == "input-copy":
        acquired.inputs = replace(inputs)
    elif fault == "memory":
        object.__setattr__(inputs, "memory_json", inputs.memory_json + b" ")
    elif fault in {"pid", "image"}:
        field = "target_pid" if fault == "pid" else "image_inode"
        observed = attempt.live_modules_observation
        object.__setattr__(observed, field, getattr(observed, field) + 1)
    elif fault == "deadline":
        object.__setattr__(acquired.binding, "deadline_monotonic_ns", acquired.binding.deadline_monotonic_ns + 1)
    else:
        object.__setattr__(attempt, "broker_observation", replace(attempt.broker_observation))
    with pytest.raises(native.NativeTrustedAttemptError, match="acquisition_changed"):
        native._original_native_completion_pin(attempt)


@pytest.mark.parametrize("fault", ("changed", "same-bytes-inode", "wrapper-format"))
def test_original_source_drift_cannot_be_repaired_by_equivalent_snapshot(tmp_path, monkeypatch, fault):
    value, _inputs, _capture, root = _original(tmp_path, monkeypatch)
    retained = _compose(value)
    path = root / ("result.json" if fault == "wrapper-format" else "candidate.py")
    old = path.read_bytes()
    path.unlink()
    path.write_bytes(b'{ "candidate_path": "candidate.py" }' if fault == "wrapper-format"
                     else old if fault == "same-bytes-inode" else old + b"# changed\n")
    path.chmod(0o400)
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()


def test_missing_original_envelope_retains_computation_gap(tmp_path, monkeypatch):
    value, _inputs, _capture, _root = _original(tmp_path, monkeypatch)
    value.run = replace(value.run, output=replace(value.run.output))
    report = _compose(value).to_dict()
    assert report["original_computation_observation_verified"] is False
    assert "original_computation_observation" in report["missing_evidence"]


def test_changed_completion_helper_is_rejected_before_original_source_io(tmp_path, monkeypatch):
    value, _inputs, _capture, _root = _original(tmp_path, monkeypatch)
    retained = _compose(value)
    monkeypatch.setattr(evidence.completion, "_canonical", lambda _value: b"substituted")
    with pytest.raises(evidence.FixedPythonProducerEvidenceError):
        retained.to_json()


def test_reader_does_not_accept_same_bytes_supplied_as_a_new_object(tmp_path, monkeypatch):
    value, _inputs, capture, _root = _original(tmp_path, monkeypatch)
    raw = value.run.attempt.producer_completion_bytes
    with pytest.raises(ValueError, match="original_reader_changed"):
        _original_completion_reader_pin(capture, bytes(bytearray(raw)))


@pytest.mark.parametrize("input_solver", ("shinka", "native_population"))
def test_original_completion_refuses_cross_solver_input_even_with_matching_wire_bytes(tmp_path, monkeypatch, input_solver):
    with pytest.raises(native.NativeTrustedAttemptError, match="acquisition_changed"):
        _original(tmp_path, monkeypatch, input_solver=input_solver)
