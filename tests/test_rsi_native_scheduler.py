from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProviderError,
    _assert_plan_binding,
    _build_receipts,
    _journal_for_published_run,
)


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def request() -> SolverRequest:
    return SolverRequest.build(
        episode_id="scheduler-test",
        contract_sha256=digest("contract"),
        evaluator_sha256=digest("evaluator"),
        environment_sha256=digest("environment"),
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        solver_id="native_population",
    )


def published_run(req: SolverRequest):
    candidate_id = "candidate-1"
    candidate = SimpleNamespace(
        candidate_id=candidate_id,
        status="admitted",
        preparation_receipt_sha256=digest("preparation"),
        execution_receipt_sha256=digest("execution"),
        evaluation_receipt_sha256=digest("evaluation"),
        publication_receipt_sha256=digest("publication"),
        bundle_sha256=digest("bundle"),
    )
    journal = SimpleNamespace(
        state="published",
        journal_id="journal",
        run_id="run",
        parent_task_id="parent",
        task_id="task",
        contract_sha256=req.contract_sha256,
        evaluator_fingerprint=req.evaluator_sha256,
        runner_fingerprint=digest("runner"),
        dependency_sha256=digest("dependency"),
        environment_sha256=req.environment_sha256,
        native_execution_receipt_sha256=digest("native-execution"),
        candidates=(candidate,),
        digest=lambda: digest("publication-journal"),
    )
    evaluation = SimpleNamespace(
        candidate_id=candidate_id,
        journal_id="journal",
        run_id="run",
        journal_sha256=digest("publication-journal"),
        evaluation=SimpleNamespace(report={"validity": 1}),
        execution=SimpleNamespace(to_dict=lambda: {
            "candidate_id": candidate_id,
            "runner_result": {"status": "succeeded"},
        }),
        bundle=SimpleNamespace(
            entrypoint="solve/main.py",
            files=(SimpleNamespace(path="solve/main.py", sha256=digest("entrypoint")),),
        ),
    )
    publication = SimpleNamespace(
        publication_status="published",
        admitted_candidate_ids=(candidate_id,),
        evaluations=(evaluation,),
        terminal_journal=journal,
        published_journal=None,
    )
    receipt = SimpleNamespace(receipt_sha256=digest("native-execution"))
    return SimpleNamespace(
        status="published", publication=publication, receipt=receipt,
        output=SimpleNamespace(output_capture_sha256=digest("capture")),
    )


def test_scheduler_sidecar_maps_same_journal_receipts() -> None:
    req = request()
    class Context:
        intent = SimpleNamespace(
            journal_id="journal", run_id="run", parent_task_id="parent", task_id="task",
            evaluator_fingerprint=req.evaluator_sha256,
            environment_sha256=req.environment_sha256,
        )
        runner_fingerprint = digest("runner")
        dependency_sha256 = digest("dependency")

    bundle = _build_receipts(req, Context(), published_run(req))
    assert isinstance(bundle.candidate, NativeCandidateRecord)
    assert isinstance(bundle.execution, NativeExecutionReceipt)
    assert isinstance(bundle.evaluation, NativeEvaluationReceipt)
    assert isinstance(bundle.publication, NativePublicationReceipt)
    assert bundle.candidate.candidate_receipt_sha256 == digest("preparation")
    assert bundle.execution.receipt_sha256 == digest("execution")
    assert bundle.evaluation.receipt_sha256 == digest("evaluation")
    assert bundle.publication.receipt_sha256 == digest("publication")
    assert bundle.execution.trace_digest == digest("capture")
    assert bundle.candidate.candidate_source_sha256 == digest("entrypoint")


def test_scheduler_sidecar_rejects_all_rejected_or_missing_publication() -> None:
    req = request()
    class Context:
        intent = SimpleNamespace(
            journal_id="journal", run_id="run", parent_task_id="parent", task_id="task",
        )
        runner_fingerprint = digest("runner")
        dependency_sha256 = digest("dependency")

    run = published_run(req)
    run.status = "all_rejected"
    with pytest.raises(NativeRSISchedulerProviderError, match="publication_incomplete"):
        _journal_for_published_run(run)

    run = published_run(req)
    run.publication.terminal_journal = None
    run.publication.published_journal = None
    with pytest.raises(NativeRSISchedulerProviderError, match="publication_journal_missing"):
        _build_receipts(req, Context(), run)


def test_scheduler_sidecar_rejects_invalid_official_evaluation() -> None:
    req = request()
    class Context:
        intent = SimpleNamespace(
            journal_id="journal", run_id="run", parent_task_id="parent", task_id="task",
        )
        runner_fingerprint = digest("runner")
        dependency_sha256 = digest("dependency")

    run = published_run(req)
    run.publication.evaluations[0].evaluation.report["validity"] = 0
    with pytest.raises(NativeRSISchedulerProviderError, match="evaluation_not_valid"):
        _build_receipts(req, Context(), run)


def test_scheduler_plan_binding_rejects_manifest_drift() -> None:
    req = request()
    memory = EMPTY_MEMORY_SNAPSHOT
    def sha(name: str) -> str:
        return digest(name)

    intent = SimpleNamespace(
        journal_id="journal", launch_id="launch", run_id="run",
        parent_task_id="parent", task_id="task", contract_sha256=req.contract_sha256,
        evaluator_fingerprint=req.evaluator_sha256, environment_sha256=req.environment_sha256,
        digest=lambda: sha("intent"),
    )
    context = SimpleNamespace(
        intent=intent,
        attestation=SimpleNamespace(digest=lambda: sha("attestation")),
        artifact=SimpleNamespace(
            descriptor=SimpleNamespace(digest=lambda: sha("descriptor")),
            artifact_sha256=sha("artifact"),
        ),
        evaluator_kind="local",
        evaluator_fingerprint=req.evaluator_sha256,
        contract=SimpleNamespace(digest=lambda: req.contract_sha256),
        environment_sha256=req.environment_sha256,
    )
    inputs = SimpleNamespace(
        manifest_sha256=sha("manifest"), deadline_unix=None, request=req, memory=memory,
    )
    attrs = {
        "request_sha256": req.digest(), "memory_snapshot_sha256": memory.digest(),
        "journal_id": "journal", "launch_id": "launch", "run_id": "run",
        "parent_task_id": "parent", "task_id": "task", "intent_sha256": sha("intent"),
        "attestation_sha256": sha("attestation"), "bootstrap_descriptor_sha256": sha("descriptor"),
        "bootstrap_artifact_sha256": sha("artifact"), "manifest_sha256": sha("manifest"),
        "request_relative_path": "../.rsi-input/request.json",
        "memory_relative_path": "../.rsi-input/memory.json", "deadline_unix": None,
        "evaluator_kind": "local", "evaluator_fingerprint": req.evaluator_sha256,
    }
    plan = SimpleNamespace(**attrs, assert_request_memory=lambda *_: None)
    _assert_plan_binding(req, memory, plan, context, inputs)
    plan.manifest_sha256 = sha("drifted-manifest")
    with pytest.raises(NativeRSISchedulerProviderError, match="plan_manifest_sha256_mismatch"):
        _assert_plan_binding(req, memory, plan, context, inputs)
