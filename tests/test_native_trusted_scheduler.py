from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from lunar_evolution.native_bootstrap import NativeBootstrapArtifact
from lunar_evolution.native_trusted_attempt import NativeTrustedAttemptObservation
from lunar_evolution.native_trusted_scheduler import (
    NativeTrustedSchedulerError,
    recover_native_trusted_producer,
    run_native_trusted_producer,
)
from lunar_evolution.producer_bootstrap import TrustedBootstrapDescriptor
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)


def _context(tmp_path: Path):
    target = tmp_path / "producer"
    target.mkdir()
    executable = target / "producer"
    executable.write_bytes(b"fixture")
    executable.chmod(0o700)
    pin = "a" * 64
    contract = AlgorithmProblemContract.from_dict(
        {
            "schema_version": "1",
            "problem_id": "scheduler",
            "problem_type": "routing",
            "statement": "route",
            "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "id"}}],
            "decision_variables": ["route"],
            "objective": {"name": "quality", "direction": "maximize"},
            "hard_constraints": [],
            "soft_constraints": [],
            "success_criteria": ["valid"],
            "deliverables": ["program"],
            "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
        }
    )
    intent = build_producer_launch_intent(
        producer_root=target,
        launch_id="launch-001",
        journal_id="journal-001",
        run_id="run-001",
        parent_task_id="parent-001",
        task_id="task-001",
        contract_sha256=contract.digest(),
        evaluator_kind="local",
        evaluator_fingerprint=pin,
        runner_fingerprint=pin,
        generator_fingerprint=pin,
        dependency_sha256=pin,
        environment_sha256=pin,
        producer_id="fixture",
        producer_fingerprint=pin,
        executable_relative="producer",
        argv=("producer",),
        working_directory="work",
        output_directory="output",
        request_timeout_seconds=1,
        max_requests=1,
        output_max_bytes=4096,
        wall_timeout_seconds=5,
    )
    attestation = build_producer_launch_attestation(intent, "nonce-001")
    observed = executable.stat()
    mode = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound"
    descriptor = TrustedBootstrapDescriptor(
        implementation_version="fixture",
        bootstrap_sha256=pin,
        size=1,
        device=observed.st_dev,
        inode=observed.st_ino,
        mtime_ns=observed.st_mtime_ns,
        ctime_ns=observed.st_ctime_ns,
        allowlist_id="fixture",
        platform_execution_mode=mode,
    )
    artifact = NativeBootstrapArtifact(
        path=executable,
        source_sha256=pin,
        artifact_sha256=pin,
        compiler="cc",
        platform_execution_mode=mode,
        allowlist_id="fixture",
        descriptor=descriptor,
    )
    return SimpleNamespace(
        workspace=tmp_path,
        intent=intent,
        attestation=attestation,
        artifact=artifact,
        broker=ProducerBrokerConfig("http://127.0.0.1:1", {}),
        contract=contract,
    )


def _attempt() -> NativeTrustedAttemptObservation:
    return NativeTrustedAttemptObservation(
        launch_id="launch-001",
        journal_id="journal-001",
        status="recovery_required",
        reason="native_trusted_attempt_request_and_output_unverified",
        registration_sha256="a" * 64,
        gate_released=True,
        target_started=True,
        exit_code=0,
        cleanup_status="cleaned",
        terminal_sha256="b" * 64,
        output_capture_sha256="c" * 64,
    )


def test_default_entrypoint_runs_attempt_receipt_and_strict_output_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    events: list[str] = []
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(
        execution_receipt_sha256=receipt.receipt_sha256,
        drafts=("draft",),
        admission_plan="plan",
    )

    def attempt(*args, **kwargs):
        events.append("attempt")
        assert kwargs["broker_config"] is context.broker
        return _attempt()

    def persist(*args, **kwargs):
        events.append("receipt")
        assert kwargs["intent"] is context.intent
        return receipt

    def prepare(*args, **kwargs):
        events.append("output")
        assert kwargs["require_same_attempt_capture"] is True
        assert kwargs["require_execution_receipt"] is True
        return output

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(scheduler, "persist_native_trusted_execution_receipt", persist)
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", prepare)
    result = run_native_trusted_producer(
        context.workspace,
        producer_root=tmp_path,
        intent=context.intent,
        attestation=context.attestation,
        artifact=context.artifact,
        broker_config=context.broker,
        contract=context.contract,
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256="1" * 64,
        environment_sha256="2" * 64,
    )

    assert events == ["attempt", "receipt", "output"]
    assert result.status == "prepared"
    assert result.publication is None
    assert result.receipt is receipt


def test_formal_entrypoint_requires_host_broker_before_spawning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", unexpected)
    with pytest.raises(NativeTrustedSchedulerError, match="input_invalid"):
        run_native_trusted_producer(
            context.workspace,
            producer_root=tmp_path,
            intent=context.intent,
            attestation=context.attestation,
            artifact=context.artifact,
            broker_config=None,
            contract=context.contract,
            groups=(),
            evaluator_kind="local",
            evaluator_fingerprint="e" * 64,
            runner_fingerprint="f" * 64,
            dependency_sha256="1" * 64,
            environment_sha256="2" * 64,
        )
    assert called is False


def _call_context(context, **options):
    return run_native_trusted_producer(
        context.workspace, producer_root=context.workspace, intent=context.intent,
        attestation=context.attestation, artifact=context.artifact, broker_config=context.broker,
        contract=context.contract, groups=(), evaluator_kind="local", evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64, dependency_sha256="1" * 64, environment_sha256="2" * 64,
        **options,
    )


def _stub_stages(monkeypatch, events, *, after=None):
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256=receipt.receipt_sha256, drafts=(), admission_plan="plan")

    def stage(name, result):
        def call(*args, **kwargs):
            events.append(name)
            if after is not None:
                after(name, kwargs)
            return result
        return call

    for attribute, name, result in (
        ("run_native_trusted_attempt", "attempt", _attempt()),
        ("persist_native_trusted_execution_receipt", "receipt", receipt),
        ("prepare_native_trusted_output", "output", output),
        ("run_native_producer_bundle_publication_transaction", "publication", SimpleNamespace(publication_status="published")),
    ):
        monkeypatch.setattr(scheduler, attribute, stage(name, result))


@pytest.mark.parametrize("reason", ["cancelled", "expired", "invalid"])
def test_shared_control_stops_before_attempt(tmp_path, monkeypatch, reason):
    context = _context(tmp_path)
    events = []
    _stub_stages(monkeypatch, events)
    control = SolveExecutionControl(10, clock=lambda: 100.0, started_at=90.0 if reason == "expired" else 100.0)
    if reason == "cancelled":
        control.cancel()
    if reason == "invalid":
        control = object()
    expected = {"cancelled": SolveExecutionCancelled, "expired": SolveExecutionBudgetExceeded,
                "invalid": NativeTrustedSchedulerError}[reason]
    with pytest.raises(expected):
        _call_context(context, execution_control=control)
    assert events == []


@pytest.mark.parametrize("boundary", ["attempt", "receipt", "output"])
@pytest.mark.parametrize("reason", ["cancelled", "expired"])
def test_caller_stop_after_native_stage_does_not_admit_next_stage(tmp_path, monkeypatch, boundary, reason):
    context = _context(tmp_path)
    events = []
    ticks, cancelled = [100.0], [False]
    control = SolveExecutionControl(10, clock=lambda: ticks[0])

    def stop(name, _kwargs):
        if name == boundary:
            if reason == "cancelled":
                cancelled[0] = True
            else:
                ticks[0] = control.deadline

    _stub_stages(monkeypatch, events, after=stop)
    expected = SolveExecutionCancelled if reason == "cancelled" else SolveExecutionBudgetExceeded
    with pytest.raises(expected):
        _call_context(context, execution_control=control, cancelled=lambda: cancelled[0], strategy=object())
    assert events == ["attempt", "receipt", "output"][:["attempt", "receipt", "output"].index(boundary) + 1]


def test_publication_reuses_effective_caller_deadline_without_reset(tmp_path, monkeypatch):
    context = _context(tmp_path)
    events, observed = [], {}
    ticks = [100.0]
    control = SolveExecutionControl(10, clock=lambda: ticks[0])

    def progress(name, kwargs):
        observed[name] = kwargs
        if name in {"attempt", "receipt", "output"}:
            ticks[0] += 1
        else:
            effective = kwargs["execution_control"]
            assert effective.deadline == 108.0
            assert effective.check("publication") == 5.0
            kwargs["continuation_guard"]("publication")

    _stub_stages(monkeypatch, events, after=progress)
    result = _call_context(context, execution_control=control, parent_deadline=108.0, strategy=object())
    effective = observed["publication"]["execution_control"]
    assert observed["attempt"]["parent_deadline"] == effective.deadline
    assert observed["attempt"]["monotonic"] is effective._clock
    assert control.deadline == 110.0 and control.timeout_seconds == 10.0
    assert result.status == "published" and result.deadline_scope == "caller_lifecycle"


def test_cancellation_only_is_forwarded_without_inventing_publication_budget(tmp_path, monkeypatch):
    context = _context(tmp_path)
    events, cancelled = [], [False]

    def publish(name, kwargs):
        if name == "publication":
            assert kwargs["execution_control"] is None
            cancelled[0] = True
            with pytest.raises(SolveExecutionCancelled):
                kwargs["continuation_guard"]("producer_preparation")

    _stub_stages(monkeypatch, events, after=publish)
    result = _call_context(context, cancelled=lambda: cancelled[0], strategy=object())
    # A transaction that completed its atomic commit is not relabeled by a scheduler
    # post-return check, even if cancellation became visible inside that critical region.
    assert result.status == "published"


def test_cancellation_only_after_attempt_cannot_persist_receipt(tmp_path, monkeypatch):
    context = _context(tmp_path)
    events, cancelled = [], [False]

    def stop_after_attempt(name, _kwargs):
        if name == "attempt":
            cancelled[0] = True

    _stub_stages(monkeypatch, events, after=stop_after_attempt)
    with pytest.raises(SolveExecutionCancelled):
        _call_context(context, cancelled=lambda: cancelled[0])
    assert events == ["attempt"]


def test_expired_parent_deadline_cannot_start_attempt(tmp_path, monkeypatch):
    context = _context(tmp_path)
    events = []
    _stub_stages(monkeypatch, events)
    with pytest.raises(SolveExecutionBudgetExceeded):
        _call_context(context, parent_deadline=time.monotonic() - 1)
    assert events == []


@pytest.mark.parametrize("callback,code", [
    (lambda: 1, "cancellation_invalid"),
    (lambda: (_ for _ in ()).throw(RuntimeError("callback error")), "cancellation_unknown"),
])
def test_invalid_caller_cancellation_stops_before_attempt(tmp_path, monkeypatch, callback, code):
    context = _context(tmp_path)
    events = []
    _stub_stages(monkeypatch, events)
    with pytest.raises(NativeTrustedSchedulerError, match=code):
        _call_context(context, cancelled=callback)
    assert events == []


@pytest.mark.parametrize("error", [SolveExecutionCancelled("commit"), SolveExecutionBudgetExceeded(
    "commit", started_at=100.0, deadline=110.0, observed_at=110.0,
)])
def test_publication_preserves_typed_control_errors(tmp_path, monkeypatch, error):
    context = _context(tmp_path)
    _stub_stages(monkeypatch, [])

    def stopped(*args, **kwargs):
        raise error

    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", stopped)
    with pytest.raises(type(error)):
        _call_context(context, strategy=object())


def test_publication_is_explicit_and_binds_receipt_and_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(
        execution_receipt_sha256=receipt.receipt_sha256,
        drafts=("draft",),
        admission_plan="plan",
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *a, **k: _attempt())
    monkeypatch.setattr(
        scheduler, "persist_native_trusted_execution_receipt", lambda *a, **k: receipt
    )
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", lambda *a, **k: output)

    def publish(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(publication_status="published")

    monkeypatch.setattr(scheduler, "run_native_producer_bundle_publication_transaction", publish)
    strategy = object()
    result = run_native_trusted_producer(
        context.workspace,
        producer_root=tmp_path,
        intent=context.intent,
        attestation=context.attestation,
        artifact=context.artifact,
        broker_config=context.broker,
        contract=context.contract,
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256="1" * 64,
        environment_sha256="2" * 64,
        strategy=strategy,
    )

    assert result.status == "published"
    assert calls and calls[0]["journal_id"] == context.intent.journal_id
    assert calls[0]["run_id"] == context.intent.run_id
    assert calls[0]["parent_task_id"] == context.intent.parent_task_id
    assert calls[0]["task_id"] == context.intent.task_id
    assert calls[0]["native_execution_receipt_sha256"] == receipt.receipt_sha256


def test_incomplete_attempt_cannot_project_a_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    incomplete = _attempt()
    incomplete = replace(incomplete, exit_code=1)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *a, **k: incomplete)
    with pytest.raises(NativeTrustedSchedulerError, match="attempt_unpublishable"):
        run_native_trusted_producer(
            context.workspace,
            producer_root=tmp_path,
            intent=context.intent,
            attestation=context.attestation,
            artifact=context.artifact,
            broker_config=context.broker,
            contract=context.contract,
            groups=(),
            evaluator_kind="local",
            evaluator_fingerprint="e" * 64,
            runner_fingerprint="f" * 64,
            dependency_sha256="1" * 64,
            environment_sha256="2" * 64,
        )


def test_recovery_reprojects_durable_receipt_without_running_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    events: list[str] = []
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256=receipt.receipt_sha256)

    def unexpected(*args, **kwargs):
        events.append("attempt")
        raise AssertionError("recovery must not start a new attempt")

    def recover(*args, **kwargs):
        events.append("receipt")
        assert kwargs["require_broker"] is True
        return receipt

    def prepare(*args, **kwargs):
        events.append("output")
        assert kwargs["require_same_attempt_capture"] is True
        assert kwargs["require_execution_receipt"] is True
        return output

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", unexpected)
    monkeypatch.setattr(scheduler, "recover_native_trusted_execution_receipt", recover)
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", prepare)
    result = recover_native_trusted_producer(
        context.workspace,
        intent=context.intent,
        attestation=context.attestation,
        artifact=context.artifact,
        contract=context.contract,
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256="1" * 64,
        environment_sha256="2" * 64,
    )

    assert events == ["receipt", "output"]
    assert result.status == "recovered"
    assert result.receipt is receipt
    assert result.output is output


def test_recovery_rejects_receipt_binding_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(execution_receipt_sha256="e" * 64)
    monkeypatch.setattr(
        scheduler, "recover_native_trusted_execution_receipt", lambda *a, **k: receipt
    )
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", lambda *a, **k: output)
    with pytest.raises(NativeTrustedSchedulerError, match="binding_mismatch"):
        recover_native_trusted_producer(
            context.workspace,
            intent=context.intent,
            attestation=context.attestation,
            artifact=context.artifact,
            contract=context.contract,
            groups=(),
            evaluator_kind="local",
            evaluator_fingerprint="e" * 64,
            runner_fingerprint="f" * 64,
            dependency_sha256="1" * 64,
            environment_sha256="2" * 64,
        )


def test_scheduler_forwards_cancellation_and_parent_deadline_to_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    receipt = SimpleNamespace(receipt_sha256="d" * 64)
    output = SimpleNamespace(
        execution_receipt_sha256=receipt.receipt_sha256,
        drafts=(),
        admission_plan="plan",
    )
    cancellation = lambda: False
    observed: dict[str, object] = {}

    def attempt(*args, **kwargs):
        observed.update(kwargs)
        return _attempt()

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(
        scheduler, "persist_native_trusted_execution_receipt", lambda *a, **k: receipt
    )
    monkeypatch.setattr(scheduler, "prepare_native_trusted_output", lambda *a, **k: output)
    run_native_trusted_producer(
        context.workspace,
        producer_root=tmp_path,
        intent=context.intent,
        attestation=context.attestation,
        artifact=context.artifact,
        broker_config=context.broker,
        contract=context.contract,
        groups=(),
        evaluator_kind="local",
        evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64,
        dependency_sha256="1" * 64,
        environment_sha256="2" * 64,
        cancelled=cancellation,
        parent_deadline=time.monotonic() + 20,
    )

    assert observed["cancelled"]() is False
    assert observed["parent_deadline"] > time.monotonic()


def test_scheduler_rejects_invalid_parent_deadline_before_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(tmp_path)
    called = False

    def unexpected(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", unexpected)
    with pytest.raises(
        NativeTrustedSchedulerError,
        match="parent_deadline_invalid",
    ):
        run_native_trusted_producer(
            context.workspace,
            producer_root=tmp_path,
            intent=context.intent,
            attestation=context.attestation,
            artifact=context.artifact,
            broker_config=context.broker,
            contract=context.contract,
            groups=(),
            evaluator_kind="local",
            evaluator_fingerprint="e" * 64,
            runner_fingerprint="f" * 64,
            dependency_sha256="1" * 64,
            environment_sha256="2" * 64,
            parent_deadline=float("nan"),
        )
    assert called is False
