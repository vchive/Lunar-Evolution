"""Feature191 durable recovery projection over inert native receipt observations."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution import python_producer_lifecycle as lifecycle
from lunar_evolution.producer_process import (
    ProducerExecutionReceipt,
    ProducerProcessError,
    ProducerStreamEvidence,
)
from lunar_evolution.python_producer_binding_store import (
    PYTHON_BINDING_SIDECAR_NAME,
    persist_python_producer_binding,
)
from lunar_evolution.python_producer_lifecycle import (
    PythonProducerLifecycleError,
    recover_python_producer_terminal,
    resume_python_producer_terminal,
)

D = "a" * 64


def _binding(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    from lunar_evolution.python_producer_binding import build_python_producer_binding

    binding = build_python_producer_binding(
        runtime_manifest=manifest,
        runtime_tree=tree,
        intent=intent,
        attestation=attestation,
        deadline_unix=4102444800.0,
        budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    batch.chmod(0o700)
    sidecar = persist_python_producer_binding(tmp_path, binding=binding)
    return binding, sidecar


def _recover(workspace: Path, binding, sidecar, **kwargs):
    return recover_python_producer_terminal(
        workspace, binding=binding, sidecar=sidecar, **kwargs,
    )


def _receipt(binding, **changes) -> ProducerExecutionReceipt:
    value = dict(  # noqa: C408
        launch_id=binding.intent.launch_id,
        journal_id=binding.intent.journal_id,
        run_id=binding.run_id,
        parent_task_id=binding.parent_task_id,
        task_id=binding.task_id,
        intent_sha256=binding.intent_sha256,
        attestation_sha256=binding.attestation_sha256,
        consumption_sha256=D,
        registration_sha256=D,
        executable_identity=D,
        pid=41,
        pgid=41,
        owner_identity={"pid": 41},
        gate_released=True,
        request_timeout_seconds=5,
        max_requests=3,
        output_max_bytes=4096,
        wall_timeout_seconds=10,
        request_count=1,
        exit_code=0,
        stdout_evidence=ProducerStreamEvidence("stdout", 0, D, False, "complete"),
        stderr_evidence=ProducerStreamEvidence("stderr", 0, D, False, "complete"),
        envelope_evidence=None,
        cleanup_status="cleaned",
        cleanup_sha256=D,
        execution_binding="linux-sealed-memfd",
        execution_snapshot_relative_path=None,
        execution_snapshot_sha256=binding.interpreter_sha256,
        execution_snapshot_size=binding.interpreter.size,
        status="completed",
    )
    value.update(changes)
    return ProducerExecutionReceipt(**value)


def test_recovery_projects_existing_receipt_without_upgrading_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding)
    calls = []

    def inspect(workspace, *, journal_id, cleanup):
        calls.append((workspace, journal_id, cleanup))
        return receipt.to_dict()

    monkeypatch.setattr(lifecycle, "recover_producer_process", inspect)
    terminal = _recover(tmp_path, binding, sidecar)
    assert terminal.status == "unknown"
    assert terminal.publication_eligible is False
    assert calls == [(tmp_path, binding.intent.journal_id, False)]
    with pytest.raises(PythonProducerLifecycleError, match="reconcile_required"):
        resume_python_producer_terminal(terminal, expected_binding=binding)


def test_recovery_required_observation_is_a_fixed_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "recover_producer_process",
        lambda *_args, **_kwargs: {
            "status": "recovery_required",
            "reason": "producer_process_terminal_receipt_missing",
        },
    )
    with pytest.raises(PythonProducerLifecycleError, match="recovery_required"):
        _recover(tmp_path, binding, sidecar)


def test_cleanup_unknown_is_rejected_before_python_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding, cleanup_status="unknown", cleanup_sha256=None)
    monkeypatch.setattr(lifecycle, "recover_producer_process", lambda *_args, **_kwargs: receipt.to_dict())
    with pytest.raises(PythonProducerLifecycleError, match="cleanup_unknown"):
        _recover(tmp_path, binding, sidecar)


def test_unknown_cleanup_label_is_rejected_as_invalid_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding, cleanup_status="not-a-native-cleanup-state", cleanup_sha256=None)
    monkeypatch.setattr(lifecycle, "recover_producer_process", lambda *_args, **_kwargs: receipt.to_dict())
    with pytest.raises(PythonProducerLifecycleError, match="recovery_receipt_invalid"):
        _recover(tmp_path, binding, sidecar)


def test_journal_shape_and_receipt_digest_drift_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    monkeypatch.setattr(
        lifecycle,
        "recover_producer_process",
        lambda *_args, **_kwargs: {"status": "unexpected"},
    )
    with pytest.raises(PythonProducerLifecycleError, match="journal_mismatch"):
        _recover(tmp_path, binding, sidecar)

    receipt = _receipt(binding)
    tampered = receipt.to_dict()
    tampered["request_count"] = 2
    monkeypatch.setattr(lifecycle, "recover_producer_process", lambda *_args, **_kwargs: tampered)
    with pytest.raises(PythonProducerLifecycleError, match="recovery_receipt_invalid"):
        _recover(tmp_path, binding, sidecar)


def test_native_recovery_errors_never_become_terminal_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)

    def fail(*_args, **_kwargs):
        raise ProducerProcessError("producer_process_recovery_registration_invalid")

    monkeypatch.setattr(lifecycle, "recover_producer_process", fail)
    with pytest.raises(PythonProducerLifecycleError, match="recovery_observation_invalid"):
        _recover(tmp_path, binding, sidecar)


def test_recovery_facade_cannot_request_native_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    calls = []

    def inspect(workspace, *, journal_id, cleanup):
        calls.append((workspace, journal_id, cleanup))
        return {"status": "recovery_required"}

    monkeypatch.setattr(lifecycle, "recover_producer_process", inspect)
    with pytest.raises(TypeError):
        recover_python_producer_terminal(tmp_path, binding=binding, sidecar=sidecar, cleanup=True)
    assert calls == []


def test_recovery_rejects_missing_sidecar_before_native_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / PYTHON_BINDING_SIDECAR_NAME
    sidecar_path.unlink()
    calls = []
    monkeypatch.setattr(lifecycle, "recover_producer_process", lambda *args, **kwargs: calls.append(1))
    with pytest.raises(PythonProducerLifecycleError, match="binding_sidecar_invalid"):
        _recover(tmp_path, binding, sidecar)
    assert calls == []


def test_recovery_rejects_mutated_binding_before_native_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    object.__setattr__(binding.intent, "journal_id", "changed-journal")
    calls = []
    monkeypatch.setattr(lifecycle, "recover_producer_process", lambda *args, **kwargs: calls.append(1))
    with pytest.raises(PythonProducerLifecycleError, match="binding_invalid"):
        _recover(tmp_path, binding, sidecar)
    assert calls == []


def test_recovery_rejects_sidecar_replacement_after_native_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding)
    sidecar_path = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id / PYTHON_BINDING_SIDECAR_NAME

    def inspect(*_args, **_kwargs):
        replacement = sidecar_path.with_name(".replacement")
        replacement.write_bytes(binding.to_json())
        replacement.chmod(0o600)
        replacement.replace(sidecar_path)
        return receipt.to_dict()

    monkeypatch.setattr(lifecycle, "recover_producer_process", inspect)
    with pytest.raises(PythonProducerLifecycleError, match="binding_sidecar_invalid"):
        _recover(tmp_path, binding, sidecar)
