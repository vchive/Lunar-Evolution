from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from lunar_evolution.bundle_evolution import derive_native_draft_run_id
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)
from lunar_evolution.rsi_native_plan import NativeRSIExecutionPlan
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerProvider,
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
        run_id=derive_native_draft_run_id("journal", candidate_id, digest("bundle")),
        journal_sha256=digest("prepared-journal"),
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
        journal=SimpleNamespace(digest=lambda: digest("prepared-journal")),
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


def test_scheduler_provider_pins_python_admission_before_live_dispatch(monkeypatch, tmp_path) -> None:
    """The provider's optional live hook consumes only fixed prepared evidence."""
    req = request()
    plan = SimpleNamespace(run_id="run", plan_sha256=digest("plan"))
    intent = SimpleNamespace(journal_id="journal")
    context = SimpleNamespace(workspace=tmp_path, intent=intent)
    controller = SimpleNamespace(
        producer_sidecar=object(),
        producer_workspace=tmp_path,
        _python_admission_bridge_wait_check=lambda: None,
    )
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider._brs_native_binding = None
    provider.context = context
    provider._python_admission_controller = controller
    seen = []
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.parse_producer_bundle_publication_journal",
        lambda path: seen.append(("journal", path.name)) or "journal",
    )
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.read_python_producer_admission_attempt_anchor",
        lambda path: seen.append(("anchor", path.name)) or SimpleNamespace(anchor_sha256=digest("anchor")),
    )
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.build_python_admission_bridge_descriptor",
        lambda **kwargs: seen.append(("descriptor", kwargs["episode_id"])) or "descriptor",
    )

    class Bridge:
        def __init__(self, owner, descriptor, *, wait_check):
            seen.append(("bridge", owner is controller, descriptor, callable(wait_check)))

        def pin_live(self, descriptor):
            seen.append(("pin", descriptor))
            return "a" * 64

    monkeypatch.setattr("lunar_evolution.rsi_native_scheduler.PythonAdmissionBridgeAdapter", Bridge)
    provider._pin_python_admission_before_dispatch(req, plan)
    assert seen == [
        ("journal", "journal.prepared.json"),
        ("anchor", "python-producer-admission-anchor.json"),
        ("descriptor", req.episode_id),
        ("bridge", True, "descriptor", True),
        ("pin", "descriptor"),
    ]


def test_scheduler_provider_bridge_binding_is_single_owner() -> None:
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider._brs_native_binding = None
    provider._python_admission_controller = None
    first, second = object(), object()
    provider.bind_python_admission_controller(first)
    provider.bind_python_admission_controller(first)
    with pytest.raises(NativeRSISchedulerProviderError, match="python_admission_controller_changed"):
        provider.bind_python_admission_controller(second)


def test_scheduler_provider_dispatch_does_not_read_python_admission_evidence(
    monkeypatch, tmp_path,
) -> None:
    """Live Python admission is an explicit prepared-boundary hook, never pre-dispatch IO."""
    req = request()
    plan = NativeRSIExecutionPlan.build(
        request=req,
        memory_snapshot=EMPTY_MEMORY_SNAPSHOT,
        journal_id="journal",
        launch_id="launch",
        run_id="run",
        parent_task_id="parent",
        task_id="task",
        intent_sha256=digest("intent"),
        attestation_sha256=digest("attestation"),
        bootstrap_descriptor_sha256=digest("descriptor"),
        bootstrap_artifact_sha256=digest("artifact"),
        manifest_sha256=digest("manifest"),
        candidate_selector_sha256=digest("selector"),
        evaluator_kind="local",
        evaluator_fingerprint=req.evaluator_sha256,
    )
    inputs = SimpleNamespace(
        request=req,
        memory=EMPTY_MEMORY_SNAPSHOT,
        deadline_unix=None,
        launch_binding_sha256=digest("binding"),
    )
    touched: list[str] = []

    def forbidden(*_args, **_kwargs):
        touched.append("evidence")
        raise AssertionError("Python admission evidence must not be read during dispatch")

    for name in (
        "parse_producer_bundle_publication_journal",
        "read_python_producer_admission_attempt_anchor",
        "build_python_admission_bridge_descriptor",
    ):
        monkeypatch.setattr(f"lunar_evolution.rsi_native_scheduler.{name}", forbidden)

    class ForbiddenBridge:
        def __init__(self, *_args, **_kwargs):
            touched.append("bridge")
            raise AssertionError("Python admission bridge must not run during dispatch")

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.PythonAdmissionBridgeAdapter",
        ForbiddenBridge,
    )
    context = SimpleNamespace(
        workspace=tmp_path,
        producer_root=tmp_path,
        intent=SimpleNamespace(journal_id="journal"),
        attestation=object(),
        artifact=object(),
        broker_config=object(),
        contract=object(),
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint=req.evaluator_sha256,
        runner_fingerprint=digest("runner"),
        dependency_sha256=digest("dependency"),
        environment_sha256=req.environment_sha256,
        strategy=object(),
        execution_control=None,
        cancelled=None,
        failure_ledger=None,
    )
    provider = NativeRSISchedulerProvider.__new__(NativeRSISchedulerProvider)
    provider._brs_native_binding = None
    provider.context = context
    provider._failure_ledger_identity = None
    provider._python_admission_controller = SimpleNamespace(
        producer_sidecar=object(),
        producer_workspace=tmp_path,
        _python_admission_bridge_wait_check=lambda: None,
    )
    provider._inputs = lambda *, require_unexpired: inputs

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler._assert_plan_binding",
        lambda *_args, **_kwargs: None,
    )

    dispatch: list[str] = []

    def dispatch_and_stop(*_args, **_kwargs):
        dispatch.append("dispatch")
        raise RuntimeError("stop at native dispatch")

    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer",
        dispatch_and_stop,
    )

    with pytest.raises(NativeRSISchedulerProviderError, match="attempt_failed"):
        provider(req, plan)
    assert dispatch == ["dispatch"]
    assert touched == []


def test_scheduler_plan_binding_rejects_manifest_drift() -> None:
    req = request()
    memory = EMPTY_MEMORY_SNAPSHOT
    def sha(name: str) -> str:
        return digest(name)

    intent = SimpleNamespace(
        journal_id="journal", launch_id="launch", run_id="run",
        parent_task_id="parent", task_id="task", contract_sha256=req.contract_sha256,
        evaluator_fingerprint=req.evaluator_sha256, environment_sha256=req.environment_sha256,
        evaluator_kind="local", runner_fingerprint=sha("runner"), dependency_sha256=sha("dependency"),
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
        runner_fingerprint=sha("runner"), dependency_sha256=sha("dependency"),
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
