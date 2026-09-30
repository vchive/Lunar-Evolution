from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import producer_lifecycle
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.native_trusted_scheduler import NativeTrustedSchedulerError
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.producer_lifecycle import (
    ProducerLifecycleError,
    recover_native_trusted_lifecycle,
    run_native_trusted_lifecycle,
    run_producer_lifecycle,
)
from lunar_evolution.producer_process import ProducerProcessError

PIN = "b" * 64


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "producer-lifecycle", "problem_type": "routing",
        "statement": "route", "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
        "decision_variables": ["route"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["valid"],
        "deliverables": ["program"],
        "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _fixture(tmp_path: Path):
    contract = _contract()
    producer_root = tmp_path / "producer-root"
    producer_root.mkdir()
    main = b"from helper import VALUE\nprint(VALUE)\n"
    helper = b"VALUE = 1\n"
    materials = [
        {"kind": "candidate_source", "path": name, "size": len(content),
         "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in (("pkg/main.py", main), ("pkg/helper.py", helper))
    ]
    envelope = {
        "schema_version": "1", "producer_id": "fixture", "producer_fingerprint": PIN,
        "status": "completed", "contract_sha256": contract.digest(),
        "budget": {"requests": 1}, "materials": materials,
    }
    script = producer_root / "producer.py"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib\n"
        "if os.read(int(os.environ['LUNAR_PRODUCER_GATE_FD']), 1) != b'1': raise SystemExit(4)\n"
        "output = pathlib.Path('../output')\n"
        "(output / 'pkg').mkdir()\n"
        f"(output / 'pkg/main.py').write_bytes({main!r})\n"
        f"(output / 'pkg/helper.py').write_bytes({helper!r})\n"
        f"(output / 'producer-result.json').write_text(json.dumps({envelope!r}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    intent = build_producer_launch_intent(
        producer_root=producer_root, launch_id="launch-001", journal_id="journal-001",
        run_id="run-001", parent_task_id="parent-001", task_id="task-001",
        contract_sha256=contract.digest(), evaluator_kind="local", evaluator_fingerprint=PIN,
        runner_fingerprint=PIN, generator_fingerprint=PIN, dependency_sha256=PIN,
        environment_sha256=PIN, producer_id="fixture", producer_fingerprint=PIN,
        executable_relative="producer.py", argv=("producer.py",), working_directory="work",
        output_directory="output", request_timeout_seconds=1, max_requests=2,
        output_max_bytes=65536, wall_timeout_seconds=5,
    )
    return contract, producer_root, intent, build_producer_launch_attestation(intent, "nonce-001")


def test_cooperative_process_prepares_multifile_draft_without_publication(tmp_path: Path) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    result = run_producer_lifecycle(
        tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
        contract=contract, groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN,
        expected_run_id="run-001", expected_parent_task_id="parent-001", expected_task_id="task-001",
    )
    assert result.receipt.status == "completed"
    assert result.terminal_status == "completed"
    assert result.cleanup_status in {"cleaned", "already_exited"}
    assert result.execution_outcome == "completed"
    assert result.deadline_scope == "process_attempt_only"
    assert len(result.drafts) == len(result.admission_plan.bundles) == 1
    assert set(result.drafts[0].draft.source_files) == {"pkg/main.py", "pkg/helper.py"}
    assert result.request_coverage == "cooperative_declaration_only"
    assert result.broker_coverage == "not_integrated"
    assert result.publication_status == "not_started"
    assert not (tmp_path / "evolution/producer-batches/journal-001/journal.json").exists()


@pytest.mark.parametrize(
    ("receipt_change", "error_code"),
    [
        ({"cleanup_status": "cleanup_unverified"}, "producer_lifecycle_cleanup_unverified"),
        ({"status": "unknown"}, "producer_lifecycle_process_incomplete"),
        ({"envelope_evidence": None}, "producer_lifecycle_envelope_unbound"),
    ],
)
def test_unverified_terminal_receipt_cannot_prepare_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    receipt_change: dict[str, object], error_code: str,
) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    real_run = producer_lifecycle.run_producer_process

    def alter_receipt(*args, **kwargs):
        return replace(real_run(*args, **kwargs), **receipt_change, receipt_sha256=None)

    monkeypatch.setattr(producer_lifecycle, "run_producer_process", alter_receipt)
    with pytest.raises(ProducerLifecycleError, match=error_code):
        run_producer_lifecycle(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            contract=contract,
            groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
        )


def test_terminal_receipt_chain_drift_cannot_prepare_drafts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    real_recover = producer_lifecycle.recover_producer_process

    def mismatched_recovery(*args, **kwargs):
        observed = real_recover(*args, **kwargs)
        return {**observed, "receipt_sha256": "0" * 64}

    monkeypatch.setattr(producer_lifecycle, "recover_producer_process", mismatched_recovery)
    with pytest.raises(ProducerLifecycleError, match="producer_lifecycle_receipt_unbound"):
        run_producer_lifecycle(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            contract=contract,
            groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
        )


def test_authority_mismatch_does_not_consume_attestation(tmp_path: Path) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    with pytest.raises(ProducerLifecycleError, match="producer_lifecycle_authority_mismatch"):
        run_producer_lifecycle(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            contract=contract, groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py",))],
            evaluator_kind="other", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
        )
    assert not (tmp_path / "evolution/producer-nonces").exists()


def test_duplicate_call_cannot_reuse_attestation(tmp_path: Path) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    arguments = {
        "intent": intent, "attestation": attestation, "producer_root": producer_root,
        "contract": contract,
        "groups": [BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
        "evaluator_kind": "local", "evaluator_fingerprint": PIN, "runner_fingerprint": PIN,
        "dependency_sha256": PIN, "environment_sha256": PIN,
    }
    run_producer_lifecycle(tmp_path, **arguments)
    with pytest.raises(ProducerProcessError):
        run_producer_lifecycle(tmp_path, **arguments)
    claim = tmp_path / "evolution/producer-batches/journal-001/attestation-consumption.json"
    assert json.loads(claim.read_text(encoding="utf-8"))["nonce"] == "nonce-001"


def test_envelope_replacement_after_execution_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, producer_root, intent, attestation = _fixture(tmp_path)
    real_run = producer_lifecycle.run_producer_process

    def replace_after_run(*args, **kwargs):
        receipt = real_run(*args, **kwargs)
        path = tmp_path / "evolution/producer-batches/journal-001/output/producer-result.json"
        path.write_text("{}", encoding="utf-8")
        return receipt

    monkeypatch.setattr(producer_lifecycle, "run_producer_process", replace_after_run)
    with pytest.raises(ProducerLifecycleError, match="producer_lifecycle_envelope_changed"):
        run_producer_lifecycle(
            tmp_path, intent=intent, attestation=attestation, producer_root=producer_root,
            contract=contract,
            groups=[BundleGroup("bundle-1", "pkg/main.py", ("pkg/main.py", "pkg/helper.py"))],
            evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
            dependency_sha256=PIN, environment_sha256=PIN,
        )


def _native_projection_fixture() -> tuple[object, dict[str, object]]:
    receipt = SimpleNamespace(
        status="completed",
        cleanup_status="cleaned",
        trusted_execution={"broker_coverage": "brokered_requests_only"},
        receipt_sha256="a" * 64,
    )
    output = SimpleNamespace(
        envelope="envelope",
        bundles=("bundle",),
        drafts=("draft",),
        admission_plan="plan",
        request_coverage="brokered_requests_only",
    )
    return SimpleNamespace(
        receipt=receipt,
        output=output,
        publication=SimpleNamespace(publication_status="published"),
        status="published",
    ), {"receipt": receipt, "output": output}


def test_native_trusted_lifecycle_projects_scheduler_and_keeps_publication_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_run, expected = _native_projection_fixture()
    observed: dict[str, object] = {}

    def scheduler_call(*args, **kwargs):
        observed.update(kwargs)
        return native_run

    monkeypatch.setattr(producer_lifecycle, "run_native_trusted_producer", scheduler_call)
    result = run_native_trusted_lifecycle(
        tmp_path,
        producer_root=tmp_path,
        intent=object(),
        attestation=object(),
        artifact=object(),
        broker_config=object(),
        contract=object(),
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint=PIN,
        runner_fingerprint=PIN,
        dependency_sha256=PIN,
        environment_sha256=PIN,
        strategy="strategy",
        execution_control="control",
        cancelled=lambda: False,
        parent_deadline=123.5,
    )

    assert result.receipt is expected["receipt"]
    assert result.envelope == "envelope"
    assert result.bundles == ("bundle",)
    assert result.drafts == ("draft",)
    assert result.admission_plan == "plan"
    assert result.terminal_status == "completed"
    assert result.cleanup_status == "cleaned"
    assert result.deadline_scope == "native_attempt_only"
    assert result.request_coverage == "brokered_requests_only"
    assert result.broker_coverage == "brokered_requests_only"
    assert result.publication_status == "published"
    assert result.native_run is native_run
    assert result.publication is native_run.publication
    assert observed["strategy"] == "strategy"
    assert observed["execution_control"] == "control"
    assert observed["parent_deadline"] == 123.5


def test_native_trusted_lifecycle_without_strategy_is_prepared_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_run, _ = _native_projection_fixture()
    native_run.publication = None
    native_run.status = "prepared"
    monkeypatch.setattr(producer_lifecycle, "run_native_trusted_producer", lambda *a, **k: native_run)
    result = run_native_trusted_lifecycle(
        tmp_path,
        producer_root=tmp_path,
        intent=object(), attestation=object(), artifact=object(), broker_config=object(),
        contract=object(), groups=(), evaluator_kind="local", evaluator_fingerprint=PIN,
        runner_fingerprint=PIN, dependency_sha256=PIN, environment_sha256=PIN,
    )
    assert result.publication is None
    assert result.publication_status == "not_started"


def test_native_trusted_lifecycle_recovery_is_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_run, _ = _native_projection_fixture()
    native_run.publication = None
    native_run.status = "recovered"
    observed: dict[str, object] = {}

    def recovery_call(*args, **kwargs):
        observed.update(kwargs)
        return native_run

    monkeypatch.setattr(producer_lifecycle, "recover_native_trusted_producer", recovery_call)
    result = recover_native_trusted_lifecycle(
        tmp_path,
        intent=object(), attestation=object(), artifact=object(), contract=object(), groups=(),
        evaluator_kind="local", evaluator_fingerprint=PIN, runner_fingerprint=PIN,
        dependency_sha256=PIN, environment_sha256=PIN, require_broker=False,
    )
    assert result.publication is None
    assert result.publication_status == "not_started"
    assert observed["require_broker"] is False


def test_native_trusted_lifecycle_preserves_fixed_scheduler_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise NativeTrustedSchedulerError("native_trusted_scheduler_receipt_unverified")

    monkeypatch.setattr(producer_lifecycle, "run_native_trusted_producer", fail)
    with pytest.raises(
        ProducerLifecycleError,
        match="^producer_lifecycle_native_trusted_scheduler_receipt_unverified$",
    ):
        run_native_trusted_lifecycle(
            tmp_path,
            producer_root=tmp_path,
            intent=object(), attestation=object(), artifact=object(), broker_config=object(),
            contract=object(), groups=(), evaluator_kind="local", evaluator_fingerprint=PIN,
            runner_fingerprint=PIN, dependency_sha256=PIN, environment_sha256=PIN,
        )
