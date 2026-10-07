from __future__ import annotations

import sys
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_native_trusted_attempt import _attempt as native_fixture
from test_native_trusted_scheduler import _attempt, _context, _stub_stages

import lunar_evolution.native_trusted_scheduler as scheduler
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled, SolveExecutionControl
from lunar_evolution.native_trusted_failure import (
    NativeTrustedFailureError,
    NativeTrustedProducerFailure,
)
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig


def call(context, *, success_only=False, **options):
    entry = scheduler.run_native_trusted_producer if success_only else scheduler.run_native_trusted_producer_outcome
    return entry(
        context.workspace, producer_root=getattr(context, "producer", context.workspace), intent=context.intent,
        attestation=context.attestation, artifact=context.artifact, broker_config=context.broker,
        contract=context.contract, groups=(), evaluator_kind="local", evaluator_fingerprint="e" * 64,
        runner_fingerprint="f" * 64, dependency_sha256="1" * 64, environment_sha256="2" * 64,
        **options,
    )


def forbid_success_stages(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("known failure must not admit success receipt, output, evaluation or publication")

    for name in (
        "persist_native_trusted_execution_receipt", "prepare_native_trusted_output",
        "run_native_producer_bundle_publication_transaction",
    ):
        monkeypatch.setattr(scheduler, name, forbidden)


@pytest.mark.skipif(sys.platform not in {"linux", "darwin"}, reason="native local platform")
@pytest.mark.parametrize("cancelled", [False, True])
def test_actual_one_shot_outcome_stops_after_verified_process_failure(tmp_path, monkeypatch, cancelled):
    control_path = tmp_path / "control"
    control_path.mkdir()
    contract = _context(control_path).contract
    target_path = tmp_path / "native"
    target_path.mkdir()
    workspace, producer, intent, attestation, artifact, batch = native_fixture(
        target_path, timeout=8, target_exit=7, target_sleep=12 if cancelled else 0,
        mark_started_before_sleep=cancelled,
    )
    context = SimpleNamespace(
        workspace=workspace, producer=producer, intent=intent, attestation=attestation, artifact=artifact,
        broker=ProducerBrokerConfig("http://127.0.0.1:1", {}), contract=contract,
    )
    marker_seen = [None]

    def cancellation():
        if (batch / "work" / "marker").exists():
            marker_seen[0] = marker_seen[0] or time.monotonic()
        return marker_seen[0] is not None and time.monotonic() - marker_seen[0] >= 0.2

    attempts = []
    runner = scheduler.run_native_trusted_attempt

    def counted(*args, **kwargs):
        attempts.append(True)
        return runner(*args, **kwargs)

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", counted)
    forbid_success_stages(monkeypatch)
    result = call(context, cancelled=cancellation if cancelled else None, strategy=object())
    assert isinstance(result, NativeTrustedProducerFailure)
    assert result.status == ("cancelled" if cancelled else "failed")
    assert result.exit_code is None if cancelled else result.exit_code == 7
    assert attempts == [True]
    assert not (batch / "execution-receipt.json").exists()
    assert not (batch / "producer-output.prepared.json").exists()
    assert not (batch / "journal.prepared.json").exists()
    assert result.to_dict()["publication_eligible"] is False


@pytest.mark.parametrize("with_control", [False, True])
def test_verified_cancellation_precedes_sticky_after_attempt_checkpoint(tmp_path, monkeypatch, with_control):
    context = _context(tmp_path)
    stopped, events, stages = [False], [], []
    control = SolveExecutionControl(8, observe_stage=stages.append) if with_control else None
    result = object()
    observed = replace(_attempt(), exit_code=None, output_capture_sha256=None, reason="unrelated-label")

    def attempt(*args, **kwargs):
        events.append("attempt")
        stopped[0] = True
        return observed

    def verify(*args, **kwargs):
        events.append("proof")
        assert kwargs["attempt"] is observed
        return result

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", verify)
    forbid_success_stages(monkeypatch)
    assert call(context, execution_control=control, cancelled=lambda: stopped[0]) is result
    assert events == ["attempt", "proof"]
    assert "native_producer_after_attempt" not in stages


@pytest.mark.parametrize("reason", [None, "native_trusted_attempt_wall_timeout", "untrusted failure prose"])
def test_only_durable_builder_classifies_nonzero_terminal_not_reason(tmp_path, monkeypatch, reason):
    context = _context(tmp_path)
    events = []
    observed = replace(_attempt(), exit_code=7, reason=reason)
    expected = object()
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *args, **kwargs: events.append("attempt") or observed)
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", lambda *args, **kwargs: events.append("proof") or expected)
    forbid_success_stages(monkeypatch)
    assert call(context) is expected
    assert events == ["attempt", "proof"]


@pytest.mark.parametrize("success_only", [False, True])
def test_missing_terminal_does_not_build_failure_or_success(tmp_path, monkeypatch, success_only):
    context = _context(tmp_path)
    events = []
    observed = replace(_attempt(), exit_code=7, terminal_sha256=None, output_capture_sha256=None)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *args, **kwargs: events.append("attempt") or observed)
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", lambda *args, **kwargs: pytest.fail("missing proof"))
    forbid_success_stages(monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="attempt_unpublishable"):
        call(context, success_only=success_only)
    assert events == ["attempt"]


def test_failure_builder_refusal_is_not_retried_or_promoted(tmp_path, monkeypatch):
    context = _context(tmp_path)
    events = []
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *args, **kwargs: events.append("attempt") or replace(_attempt(), exit_code=7))

    def refuse(*args, **kwargs):
        events.append("proof")
        raise NativeTrustedFailureError("records_invalid")

    monkeypatch.setattr(scheduler, "build_native_trusted_failure", refuse)
    forbid_success_stages(monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="failure_unverified"):
        call(context)
    assert events == ["attempt", "proof"]


def test_historical_success_only_api_still_refuses_known_failure(tmp_path, monkeypatch):
    context = _context(tmp_path)
    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", lambda *args, **kwargs: replace(_attempt(), exit_code=7))
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", lambda *args, **kwargs: pytest.fail("legacy API failure mapping"))
    forbid_success_stages(monkeypatch)
    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="attempt_unpublishable"):
        call(context, success_only=True)


@pytest.mark.parametrize("publication", [False, True])
def test_success_outcome_uses_unchanged_existing_stages(tmp_path, monkeypatch, publication):
    context = _context(tmp_path)
    events = []
    _stub_stages(monkeypatch, events)
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", lambda *args, **kwargs: pytest.fail("success failure mapping"))
    result = call(context, **({"strategy": object()} if publication else {}))
    assert isinstance(result, scheduler.NativeTrustedProducerRun)
    assert events == ["attempt", "receipt", "output"] + (["publication"] if publication else [])
    assert result.status == ("published" if publication else "prepared")


@pytest.mark.parametrize("stop", ["cancelled", "callback_unknown", "callback_invalid", "runner_error"])
def test_callback_and_runner_errors_never_manufacture_failure(tmp_path, monkeypatch, stop):
    context = _context(tmp_path)
    events = []

    def attempt(*args, **kwargs):
        events.append("attempt")
        raise scheduler.NativeTrustedAttemptError("native_trusted_attempt_fixture_unknown")

    def callback():
        if stop == "callback_unknown":
            raise RuntimeError("opaque callback")
        return 1 if stop == "callback_invalid" else stop == "cancelled"

    monkeypatch.setattr(scheduler, "run_native_trusted_attempt", attempt)
    monkeypatch.setattr(scheduler, "build_native_trusted_failure", lambda *args, **kwargs: pytest.fail("exception failure mapping"))
    forbid_success_stages(monkeypatch)
    with pytest.raises(SolveExecutionCancelled if stop == "cancelled" else scheduler.NativeTrustedSchedulerError):
        call(context, cancelled=callback)
    assert events == (["attempt"] if stop == "runner_error" else [])
