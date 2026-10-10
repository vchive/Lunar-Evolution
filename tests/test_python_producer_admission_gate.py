"""Provider-free Feature191 admission composition tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_python_producer_binding import _fixture as binding_fixture

from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_publication import (
    ProducerBundlePublicationCandidate,
    build_producer_bundle_publication_journal,
)
from lunar_evolution.producer_handoff import ProducerMaterial, ProducerResultEnvelope
from lunar_evolution.producer_process import (
    ProducerEnvelopeEvidence,
    ProducerExecutionReceipt,
    ProducerStreamEvidence,
)
from lunar_evolution.python_producer_admission_gate import verify_python_producer_admission_gate
from lunar_evolution.python_producer_admission_handoff import (
    build_python_producer_admission_handoff,
    parse_python_producer_admission_handoff_file_pin,
    persist_python_producer_admission_handoff_pinned,
)
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import PythonProducerBindingSidecar
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.python_producer_lifecycle import (
    build_python_producer_runtime_observation,
    build_python_producer_terminal,
)

D = "a" * 64
RAW_ENVELOPE = "b" * 64
BROKER_DEADLINE = 123456789000


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


OWNER_DIGEST = _sha({"kind": "fixture-owner", "pid": 123})


def _chain(tmp_path: Path):
    manifest, tree, intent, attestation, budget = binding_fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    raw = binding.to_json()
    sidecar = PythonProducerBindingSidecar(
        binding=binding, raw_sha256=hashlib.sha256(raw).hexdigest(), raw_size=len(raw),
        file_device=1, file_inode=2, file_mode=0o600, file_nlink=1,
        file_mtime_ns=3, file_ctime_ns=4,
    )
    checkpoint = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    sidecar_pin = hashlib.sha256(
        json.dumps(dict(checkpoint.sidecar_pin), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    interpreter = binding.interpreter
    executable_identity = _sha({
        "sha256": interpreter.sha256,
        "size": interpreter.size, "device": interpreter.device, "inode": interpreter.inode,
        "mtime_ns": interpreter.mtime_ns, "ctime_ns": interpreter.ctime_ns,
    })
    owner = {"kind": "fixture-owner", "pid": 123}
    process_owner_digest = _sha(owner)
    executable_owner_evidence = {
        "kind": "fixture-executable-owner", "sha256": interpreter.sha256,
        "size": interpreter.size, "device": interpreter.device, "inode": interpreter.inode,
        "mtime_ns": interpreter.mtime_ns, "ctime_ns": interpreter.ctime_ns,
    }
    executable_owner_digest = _sha(executable_owner_evidence)
    stream = ProducerStreamEvidence("stdout", 0, D, False, "complete")
    err_stream = ProducerStreamEvidence("stderr", 0, D, False, "complete")
    envelope_identity = _sha({"device": 1, "inode": 3, "size": 10, "mtime_ns": 4, "ctime_ns": 5})
    envelope = ProducerEnvelopeEvidence(
        relative_path="output/producer-result.json", sha256=RAW_ENVELOPE, bytes=10, device=1, inode=3,
        mtime_ns=4, ctime_ns=5, identity_before=envelope_identity, identity_after=envelope_identity,
        read_status="stable",
    )
    receipt = ProducerExecutionReceipt(
        launch_id=binding.intent.launch_id, journal_id=binding.intent.journal_id, run_id=binding.run_id,
        parent_task_id=binding.parent_task_id, task_id=binding.task_id,
        intent_sha256=binding.intent_sha256, attestation_sha256=binding.attestation_sha256,
        consumption_sha256=D, registration_sha256=D, executable_identity=executable_identity,
        pid=123, pgid=123, owner_identity=owner, gate_released=True,
        request_timeout_seconds=binding.intent.request_timeout_seconds, max_requests=binding.request_budget,
        output_max_bytes=binding.output_max_bytes, wall_timeout_seconds=binding.wall_timeout_seconds,
        request_count=1, exit_code=0, stdout_evidence=stream, stderr_evidence=err_stream,
        envelope_evidence=envelope, cleanup_status="cleaned", cleanup_sha256=D,
        execution_binding="pathname_unbound", execution_snapshot_relative_path=None,
        execution_snapshot_sha256=interpreter.sha256, execution_snapshot_size=interpreter.size,
        status="completed", trusted_execution={
            "terminal_sha256": D, "stream_capture_sha256": D, "output_capture_sha256": D,
            "cleanup_sha256": D, "broker_coverage": "brokered_requests_only",
            "broker_journal_relative_path": ".host-request-journal/requests",
            "broker_journal_identity": {
                "launch_id": binding.intent.launch_id, "journal_id": binding.intent.journal_id,
                "run_id": binding.run_id, "parent_task_id": binding.parent_task_id,
                "task_id": binding.task_id, "intent_sha256": binding.intent_sha256,
                "request_timeout_seconds": binding.intent.request_timeout_seconds,
                "max_requests": binding.request_budget,
                "wall_deadline_ns": BROKER_DEADLINE,
            },
            "broker_journal_file_identity": [1, 2], "broker_journal_sha256": D,
            "broker_journal_bytes": 1, "broker_admitted_count": 1,
            "broker_declared_count_matches": True,
        },
    )
    terminal = build_python_producer_terminal(
        binding_sha256=binding.binding_sha256, run_id=binding.run_id, journal_id=binding.intent.journal_id,
        launch_id=binding.intent.launch_id, process_registration_sha256=receipt.registration_sha256,
        owner_identity_sha256=process_owner_digest, executable_sha256=interpreter.sha256,
        executable_size=interpreter.size, executable_device=interpreter.device,
        executable_inode=interpreter.inode, started_unix=10.0, released_unix=11.0,
        exited_unix=12.0, deadline_unix=binding.deadline_unix, status="completed", exit_code=0,
        signal=None, cleanup_status="cleaned", request_journal_sha256=D, request_count=1,
        stdout_sha256=D, stderr_sha256=D, publication_eligible=False,
    )
    observation = build_python_producer_runtime_observation(
        binding_sha256=binding.binding_sha256, execution_performed=True,
        version_major=3, version_minor=11, version_micro=0, cache_tag="cpython-311",
        abi_profile="cp311-ordinary-gil", argv=intent.argv, orig_argv=intent.argv, flags=("-I", "-S", "-B"),
        filesystem_encoding="utf-8", filesystem_errors="surrogateescape", stdio_encoding="utf-8",
        stdio_errors="surrogateescape", sys_path=(".",), startup_modules=("_io",),
        broker_transcript_sha256=D, pycache_absent=True, computation_sha256=D,
    )
    item = ProducerBundleAdmissionItem(
        bundle_id="bundle-1", bundle_sha256=D, draft_bundle_sha256=D,
        entrypoint="pkg/main.py", material_paths=("pkg/main.py",), producer_fingerprint=D,
    )
    plan = ProducerBundleAdmissionPlan(
        contract_sha256=binding.contract_sha256, evaluator_kind="local",
        evaluator_fingerprint=binding.evaluator_fingerprint, runner_fingerprint=binding.intent.runner_fingerprint,
        dependency_sha256=binding.dependency_sha256, environment_sha256=binding.environment_sha256,
        bundles=(item,),
    )
    material = ProducerMaterial(kind="source", path="pkg/main.py", size=1, sha256=D)
    envelope = ProducerResultEnvelope(
        schema_version="1", producer_id=binding.intent.producer_id,
        producer_fingerprint=binding.intent.producer_fingerprint, status="completed",
        contract_sha256=binding.contract_sha256, budget={"requests": 1}, materials=(material,),
        producer_run_id=binding.run_id,
    )
    materials_digest = _sha([material.to_dict()])
    handoff = build_python_producer_admission_handoff(
        run_id=binding.run_id, journal_id=binding.intent.journal_id, parent_task_id=binding.parent_task_id,
        task_id=binding.task_id, binding_sha256=binding.binding_sha256, sidecar_raw_sha256=sidecar.raw_sha256,
        sidecar_pin_sha256=sidecar_pin, launch_intent_sha256=binding.intent_sha256,
        attestation_sha256=binding.attestation_sha256, runtime_manifest_sha256=binding.runtime_manifest_sha256,
        runtime_tree_sha256=binding.runtime_tree_sha256, executable_owner_sha256=executable_owner_digest,
        native_execution_receipt_sha256=receipt.receipt_sha256, terminal_sha256=terminal.terminal_sha256,
        runtime_observation_sha256=observation.observation_sha256,
        broker_transcript_sha256=observation.broker_transcript_sha256,
        envelope_sha256=envelope.envelope_sha256, materials_sha256=materials_digest,
        contract_sha256=binding.contract_sha256,
        evaluator_sha256=binding.evaluator_fingerprint, runner_sha256=binding.intent.runner_fingerprint,
        dependency_sha256=binding.dependency_sha256, environment_sha256=binding.environment_sha256,
        admission_plan_sha256=plan.digest(), request_budget=binding.request_budget,
        wall_timeout_seconds=binding.wall_timeout_seconds, deadline_unix=binding.deadline_unix,
    )
    candidate = ProducerBundlePublicationCandidate(
        candidate_id="candidate-1", bundle_id="bundle-1", bundle_sha256=D, parent_id=None,
        generation=0, iteration=0, island_id=0, preparation_receipt_sha256=D,
    )
    journal = build_producer_bundle_publication_journal(
        journal_id=binding.intent.journal_id, run_id=binding.run_id, parent_task_id=binding.parent_task_id,
        task_id=binding.task_id, admission_sha256=plan.digest(), archive_prefix_sha256=D,
        base_archive_sha256=D, base_state_sha256=D, contract_sha256=binding.contract_sha256,
        evaluator_kind="local", evaluator_fingerprint=binding.evaluator_fingerprint,
        runner_fingerprint=binding.intent.runner_fingerprint, dependency_sha256=binding.dependency_sha256,
        environment_sha256=binding.environment_sha256, budget_sha256=D, strategy="population",
        population_config_sha256=D, num_islands=1, candidates=(candidate,),
        native_execution_receipt_sha256=receipt.receipt_sha256, python_handoff_sha256=handoff.handoff_sha256,
    )
    return binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, executable_owner_evidence


def test_complete_local_evidence_is_eligible_but_not_production_admission(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    assert chain[8].envelope_sha256 != RAW_ENVELOPE
    assert _sha(chain[9]) != _sha(dict(chain[5].owner_identity))
    result = verify_python_producer_admission_gate(
        binding=chain[0], sidecar=chain[1], handoff=chain[2], terminal=chain[3],
        runtime_observation=chain[4], native_receipt=chain[5], admission_plan=chain[6], journal=chain[7],
        envelope=chain[8], envelope_sha256=chain[8].envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=chain[2].materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(chain[9]), executable_owner_evidence=chain[9],
    )
    assert result.eligible is True
    assert result.accepted is True
    assert result.production_admission is False
    assert result.status == "accepted"


def test_digest_identity_and_claim_drift_refuse_without_side_effects(tmp_path: Path) -> None:
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(tmp_path)
    object.__setattr__(handoff, "task_id", "other-task")
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
        envelope=envelope, envelope_sha256=envelope.envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=handoff.materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(owner_evidence), executable_owner_evidence=owner_evidence,
    )
    assert result.refused is True
    assert result.production_admission is False

    second = tmp_path / "second"
    second.mkdir()
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(second)
    object.__setattr__(observation, "pycache_absent", False)
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
        envelope=envelope, envelope_sha256=envelope.envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=handoff.materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(owner_evidence), executable_owner_evidence=owner_evidence,
    )
    assert result.eligible is False


def test_terminal_binding_and_request_journal_drift_refuse(tmp_path: Path) -> None:
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(tmp_path)
    object.__setattr__(terminal, "binding_sha256", "b" * 64)
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
        envelope=envelope, envelope_sha256=envelope.envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=handoff.materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(owner_evidence), executable_owner_evidence=owner_evidence,
    )
    assert result.refused is True
    assert result.reason_code is not None

    second = tmp_path / "journal-drift"
    second.mkdir()
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(second)
    object.__setattr__(terminal, "request_journal_sha256", "b" * 64)
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
        envelope=envelope, envelope_sha256=envelope.envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=handoff.materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(owner_evidence), executable_owner_evidence=owner_evidence,
    )
    assert result.refused is True


def test_missing_material_pin_and_unbrokered_receipt_refuse(tmp_path: Path) -> None:
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(tmp_path)
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
    )
    assert result.reason_code == "python_producer_admission_gate_envelope_unverified"

    second = tmp_path / "unbrokered"
    second.mkdir()
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = _chain(second)
    trusted = dict(receipt.trusted_execution or {})
    trusted["broker_coverage"] = "none"
    object.__setattr__(receipt, "trusted_execution", trusted)
    result = verify_python_producer_admission_gate(
        binding=binding, sidecar=sidecar, handoff=handoff, terminal=terminal,
        runtime_observation=observation, native_receipt=receipt, admission_plan=plan, journal=journal,
        envelope=envelope, envelope_sha256=envelope.envelope_sha256,
        envelope_evidence_sha256=RAW_ENVELOPE, materials_sha256=handoff.materials_sha256,
        broker_deadline_monotonic_ns=BROKER_DEADLINE, executable_owner_sha256=_sha(owner_evidence), executable_owner_evidence=owner_evidence,
    )
    assert result.refused is True


def test_independent_envelope_and_owner_pins_must_match_native_receipt(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = chain
    owner_digest = _sha(owner_evidence)
    kwargs = {
        "binding": binding, "sidecar": sidecar, "handoff": handoff, "terminal": terminal,
        "runtime_observation": observation, "native_receipt": receipt,
        "admission_plan": plan, "journal": journal, "envelope": envelope,
        "envelope_sha256": envelope.envelope_sha256, "envelope_evidence_sha256": RAW_ENVELOPE,
        "executable_owner_sha256": owner_digest, "executable_owner_evidence": owner_evidence,
        "materials_sha256": handoff.materials_sha256,
        "broker_deadline_monotonic_ns": BROKER_DEADLINE,
    }
    assert verify_python_producer_admission_gate(**kwargs).eligible is True
    assert verify_python_producer_admission_gate(**{**kwargs, "envelope_sha256": "b" * 64}).refused
    assert verify_python_producer_admission_gate(**{**kwargs, "executable_owner_sha256": "b" * 64}).refused


def _resigned_chain(chain, **updates):
    """Rebind every downstream digest so a test reaches the semantic gate."""
    binding, sidecar, handoff, terminal, observation, receipt, plan, journal, envelope, owner_evidence = chain
    receipt = updates.get("native_receipt", receipt)
    observation = updates.get("runtime_observation", observation)
    envelope = updates.get("envelope", envelope)
    journal = updates.get("journal", journal)
    if observation.observation_sha256 is None:
        observation = replace(observation, observation_sha256=observation.digest())
    # Handoff deliberately does not support a digest-less DTO; use its official
    # builder to sign the detached changed payload instead of mutating frozen fields.
    handoff_payload = handoff.to_dict()
    handoff_payload.pop("handoff_sha256")
    handoff_payload.update(
        native_execution_receipt_sha256=receipt.receipt_sha256,
        runtime_observation_sha256=observation.observation_sha256,
        broker_transcript_sha256=observation.broker_transcript_sha256,
        envelope_sha256=envelope.envelope_sha256,
    )
    handoff = build_python_producer_admission_handoff(handoff_payload)
    journal = replace(
        journal, native_execution_receipt_sha256=receipt.receipt_sha256,
        python_handoff_sha256=handoff.handoff_sha256, journal_sha256=None,
    )
    return {
        "binding": binding, "sidecar": sidecar, "handoff": handoff, "terminal": terminal,
        "runtime_observation": observation, "native_receipt": receipt,
        "admission_plan": plan, "journal": journal, "envelope": envelope,
        "envelope_sha256": envelope.envelope_sha256,
        "envelope_evidence_sha256": RAW_ENVELOPE,
        "executable_owner_sha256": _sha(owner_evidence),
        "executable_owner_evidence": owner_evidence,
        "materials_sha256": handoff.materials_sha256,
        "broker_deadline_monotonic_ns": BROKER_DEADLINE,
    }


def _assert_semantic_refusal(kwargs, suffix: str) -> None:
    result = verify_python_producer_admission_gate(**kwargs)
    assert result.reason_code == "python_producer_admission_gate_" + suffix
    assert result.refused is True
    assert result.production_admission is False


@pytest.mark.parametrize("drift", [False, True])
def test_optional_journal_file_pin_checks_only_detached_handoff_bytes(tmp_path, monkeypatch, drift):
    chain = _chain(tmp_path)
    sidecar = persist_python_producer_admission_handoff_pinned(
        tmp_path / "handoff.json", handoff=chain[2],
    )
    pin = sidecar.file_pin
    if drift:
        payload = pin.to_dict()
        payload.pop("pin_sha256")
        payload["raw_sha256"] = "f" * 64
        payload["pin_sha256"] = _sha(payload)
        pin = parse_python_producer_admission_handoff_file_pin(payload)
    journal = replace(chain[7], python_handoff_file_pin=pin, journal_sha256=None)
    kwargs = _resigned_chain(chain, journal=journal)

    def no_filesystem(*args, **kwargs):
        pytest.fail("pure gate must not observe a file")

    monkeypatch.setattr("os.open", no_filesystem)
    monkeypatch.setattr("os.stat", no_filesystem)
    result = verify_python_producer_admission_gate(**kwargs)
    assert result.production_admission is False
    if drift:
        assert result.reason_code == "python_producer_admission_gate_journal_handoff_file_pin_mismatch"
        assert result.refused is True
    else:
        assert result.eligible is True


def test_resigned_request_timeout_drift_reaches_native_receipt_gate(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    receipt = chain[5]
    trusted = dict(receipt.trusted_execution)
    broker_identity = dict(trusted["broker_journal_identity"])
    changed_timeout = receipt.request_timeout_seconds + 1
    broker_identity["request_timeout_seconds"] = changed_timeout
    trusted["broker_journal_identity"] = broker_identity
    receipt = replace(
        receipt, request_timeout_seconds=changed_timeout, trusted_execution=trusted,
        receipt_sha256=None,
    )
    kwargs = _resigned_chain(chain, native_receipt=receipt)
    _assert_semantic_refusal(kwargs, "native_receipt_mismatch")


def test_resigned_broker_deadline_drift_refuses_original_retained_pin(tmp_path: Path) -> None:
    chain = _chain(tmp_path)
    receipt = chain[5]
    trusted = dict(receipt.trusted_execution)
    broker_identity = dict(trusted["broker_journal_identity"])
    broker_identity["wall_deadline_ns"] = BROKER_DEADLINE + 1
    trusted["broker_journal_identity"] = broker_identity
    receipt = replace(receipt, trusted_execution=trusted, receipt_sha256=None)
    kwargs = _resigned_chain(chain, native_receipt=receipt)
    _assert_semantic_refusal(kwargs, "broker_journal_mismatch")


@pytest.mark.parametrize("deadline", [None, True, 0, 2**63])
def test_missing_or_invalid_independent_broker_deadline_refuses(tmp_path: Path, deadline: object) -> None:
    kwargs = _resigned_chain(_chain(tmp_path))
    kwargs["broker_deadline_monotonic_ns"] = deadline
    _assert_semantic_refusal(kwargs, "broker_deadline_unverified")


@pytest.mark.parametrize("field,value", [
    ("version_major", 4),
    ("version_minor", 12),
    ("cache_tag", "cpython-312"),
    ("abi_profile", "cp312-ordinary-gil"),
    ("argv", ("runtime/other-python",)),
    ("orig_argv", ("runtime/other-python",)),
    ("flags", ("-I", "-S")),
])
def test_resigned_runtime_target_drift_reaches_target_gate(tmp_path: Path, field: str, value: object) -> None:
    chain = _chain(tmp_path)
    observation = replace(chain[4], **{field: value, "observation_sha256": None})
    kwargs = _resigned_chain(chain, runtime_observation=observation)
    _assert_semantic_refusal(kwargs, "runtime_observation_target_mismatch")


@pytest.mark.parametrize("changes", [
    {"stream": "stderr"},
    {"bytes_observed": -1},
    {"bytes_observed": True},
    {"bytes_observed": 4097},
    {"truncated": True, "capture_status": "limit_exceeded"},
    {"capture_status": "incomplete"},
])
def test_resigned_stream_drift_reaches_output_gate(tmp_path: Path, changes: dict[str, object]) -> None:
    chain = _chain(tmp_path)
    receipt = chain[5]
    receipt = replace(
        receipt, stdout_evidence=replace(receipt.stdout_evidence, **changes),
        receipt_sha256=None,
    )
    kwargs = _resigned_chain(chain, native_receipt=receipt)
    _assert_semantic_refusal(kwargs, "output_evidence_invalid")


@pytest.mark.parametrize("changes", [
    {"relative_path": "output/other.json"},
    {"read_status": "changed"},
    {"identity_before": D, "identity_after": D},
    {"identity_after": D},
    {"device": 2},
    {"inode": 4},
    {"mtime_ns": 5},
    {"ctime_ns": 6},
    {"bytes": -1},
    {"bytes": True},
    {"bytes": 4097},
])
def test_resigned_envelope_capture_drift_reaches_output_gate(tmp_path: Path, changes: dict[str, object]) -> None:
    chain = _chain(tmp_path)
    receipt = chain[5]
    receipt = replace(
        receipt, envelope_evidence=replace(receipt.envelope_evidence, **changes),
        receipt_sha256=None,
    )
    kwargs = _resigned_chain(chain, native_receipt=receipt)
    _assert_semantic_refusal(kwargs, "output_evidence_invalid")


@pytest.mark.parametrize("changes", [
    {"producer_id": "another-producer"},
    {"budget": {"requests": 0}},
    {"budget": {"requests": 2}},
    {"budget": {"requests": 1.0}},
    {"budget": {"other": 1}},
])
def test_resigned_envelope_producer_and_request_drift_reaches_claim_gate(
    tmp_path: Path, changes: dict[str, object],
) -> None:
    chain = _chain(tmp_path)
    envelope = replace(chain[8], **changes)
    kwargs = _resigned_chain(chain, envelope=envelope)
    _assert_semantic_refusal(kwargs, "envelope_claim_invalid")


@pytest.mark.parametrize("state", ["executing", "publishing", "all_rejected"])
def test_resigned_nonprepared_journal_refuses_at_authority_gate(tmp_path: Path, state: str) -> None:
    chain = _chain(tmp_path)
    journal = chain[7]
    candidate = journal.candidates[0]
    changes = {"state": state, "publication_phase": "staged", "journal_sha256": None}
    if state in {"publishing", "all_rejected"}:
        candidate = replace(
            candidate, status="admitted" if state == "publishing" else "rejected",
            execution_receipt_sha256="c" * 64, evaluation_receipt_sha256="d" * 64,
        )
        changes["candidates"] = (candidate,)
    if state == "all_rejected":
        changes.update(
            publication_phase="committed", terminal_marker_sha256="e" * 64,
            archive_after_sha256=journal.base_archive_sha256,
            state_after_sha256=journal.base_state_sha256,
        )
    journal = replace(journal, **changes)
    kwargs = _resigned_chain(chain, journal=journal)
    _assert_semantic_refusal(kwargs, "journal_authority_mismatch")
