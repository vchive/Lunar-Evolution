"""Focused provider-free tests for the Python/native process adapter seam."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_python_producer_binding import _fixture

from lunar_evolution import python_producer_lifecycle as lifecycle
from lunar_evolution.producer_process import ProducerExecutionReceipt, ProducerStreamEvidence
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import persist_python_producer_binding

D = "a" * 64


def _binding(tmp_path: Path):
    manifest, tree, intent, attestation, budget = _fixture(tmp_path)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    batch = tmp_path / "evolution" / "producer-batches" / binding.intent.journal_id
    batch.mkdir(parents=True)
    return binding, persist_python_producer_binding(tmp_path, binding=binding)


def _receipt(binding) -> ProducerExecutionReceipt:
    return ProducerExecutionReceipt(
        launch_id=binding.intent.launch_id, journal_id=binding.intent.journal_id,
        run_id=binding.run_id, parent_task_id=binding.parent_task_id, task_id=binding.task_id,
        intent_sha256=binding.intent_sha256, attestation_sha256=binding.attestation_sha256,
        consumption_sha256=D, registration_sha256=D, executable_identity=D, pid=41, pgid=41,
        owner_identity={"pid": 41}, gate_released=True, request_timeout_seconds=5,
        max_requests=binding.request_budget, output_max_bytes=binding.output_max_bytes,
        wall_timeout_seconds=binding.wall_timeout_seconds, request_count=1, exit_code=0,
        stdout_evidence=ProducerStreamEvidence("stdout", 0, D, False, "complete"),
        stderr_evidence=ProducerStreamEvidence("stderr", 0, D, False, "complete"),
        envelope_evidence=None, cleanup_status="cleaned", cleanup_sha256=D,
        execution_binding="linux-sealed-memfd", execution_snapshot_relative_path=None,
        execution_snapshot_sha256=binding.interpreter_sha256,
        execution_snapshot_size=binding.interpreter.size, status="completed",
    )


def test_adapter_gates_sidecar_before_and_after_native_process(tmp_path: Path, monkeypatch) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding)
    calls: list[str] = []

    def read_sidecar(*_args, **_kwargs):
        calls.append("sidecar")
        return sidecar

    def run_process(workspace, **kwargs):
        calls.append("process")
        assert workspace == tmp_path
        assert kwargs["intent"] == binding.intent
        assert kwargs["attestation"] == binding.attestation
        return receipt

    monkeypatch.setattr(lifecycle, "read_python_producer_binding_sidecar", read_sidecar)
    monkeypatch.setattr(lifecycle, "run_producer_process", run_process)
    result = lifecycle.run_python_producer_process(
        tmp_path, binding=binding, sidecar=sidecar, producer_root=tmp_path / "producer-root",
    )
    assert result == receipt
    assert calls == ["sidecar", "process", "sidecar"]


def test_adapter_refuses_sidecar_loss_without_native_process(tmp_path: Path, monkeypatch) -> None:
    binding, sidecar = _binding(tmp_path)
    called = False

    def fail_process(*_args, **_kwargs):
        nonlocal called
        called = True
        pytest.fail("native process must not start without the retained sidecar")

    def missing_sidecar(*_args, **_kwargs):
        raise lifecycle.PythonProducerBindingStoreError("missing")

    monkeypatch.setattr(lifecycle, "read_python_producer_binding_sidecar", missing_sidecar)
    monkeypatch.setattr(lifecycle, "run_producer_process", fail_process)
    with pytest.raises(lifecycle.PythonProducerLifecycleError, match="binding_sidecar_invalid"):
        lifecycle.run_python_producer_process(
            tmp_path, binding=binding, sidecar=sidecar, producer_root=tmp_path / "producer-root",
        )
    assert not called


def test_adapter_rejects_native_receipt_binding_drift(tmp_path: Path, monkeypatch) -> None:
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding)
    drifted = ProducerExecutionReceipt(
        **{**receipt.to_dict(), "run_id": "other-run", "receipt_sha256": None,
           "stdout_evidence": receipt.stdout_evidence, "stderr_evidence": receipt.stderr_evidence},
    )
    monkeypatch.setattr(lifecycle, "read_python_producer_binding_sidecar", lambda *_a, **_k: sidecar)
    monkeypatch.setattr(lifecycle, "run_producer_process", lambda *_a, **_k: drifted)
    with pytest.raises(lifecycle.PythonProducerLifecycleError, match="receipt_binding_drift"):
        lifecycle.run_python_producer_process(
            tmp_path, binding=binding, sidecar=sidecar, producer_root=tmp_path / "producer-root",
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("parent_task_id", "other-parent"),
        ("task_id", "other-task"),
        ("request_timeout_seconds", 6),
    ),
)
def test_adapter_rejects_receipt_parent_or_request_limit_drift(
    tmp_path: Path, monkeypatch, field: str, value: object,
) -> None:
    """The Python binding includes the native task and request identity pins."""
    binding, sidecar = _binding(tmp_path)
    receipt = _receipt(binding)
    drifted = ProducerExecutionReceipt(
        **{
            **receipt.to_dict(),
            field: value,
            "receipt_sha256": None,
            "stdout_evidence": receipt.stdout_evidence,
            "stderr_evidence": receipt.stderr_evidence,
        }
    )
    monkeypatch.setattr(lifecycle, "read_python_producer_binding_sidecar", lambda *_a, **_k: sidecar)
    monkeypatch.setattr(lifecycle, "run_producer_process", lambda *_a, **_k: drifted)
    with pytest.raises(lifecycle.PythonProducerLifecycleError, match="receipt_binding_drift"):
        lifecycle.run_python_producer_process(
            tmp_path, binding=binding, sidecar=sidecar, producer_root=tmp_path / "producer-root",
        )
