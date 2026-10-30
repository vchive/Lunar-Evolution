"""Inert original-context composition; no producer, model or evaluator runs."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_rsi_python_scheduler_inputs as input_fixture
from test_producer_python_runtime import _inventory
from test_rsi_native_gateway import bundle
from test_rsi_python_scheduler_inputs import _setup

from lunar_evolution.cli import main
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_native_gateway import NativeRSISolverGatewayError
from lunar_evolution.rsi_native_scheduler import NativeRSISchedulerProvider
from lunar_evolution.rsi_producer_gateway import (
    PythonProducerRSIExecutionConfig,
    PythonProducerRSIGatewayError,
    PythonProducerRSISolverGateway,
)
from lunar_evolution.rsi_python_scheduler_inputs import PythonRSISchedulerInputContext
from lunar_evolution.rsi_store import RSILedger


def _strategy():
    raise AssertionError("no actual evaluation in a composition fixture")


def _handoff(_receipt, _output):
    raise AssertionError("no actual Python producer in a composition fixture")


def _wait_check():
    pass


def _fixture(tmp_path, monkeypatch, producer="openevolve"):
    original_build = SolverRequest.build
    original_python_fixture = input_fixture.python_fixture

    def build(**kwargs):
        return original_build(**{**kwargs, "solver_id": producer})

    def python_fixture(root):
        manifest, tree, intent, attestation, budget = original_python_fixture(root)
        intent = replace(intent, producer_id=producer, intent_sha256=None)
        intent = replace(intent, intent_sha256=intent.digest())
        return manifest, tree, intent, attestation, budget

    with monkeypatch.context() as patch:
        patch.setattr(SolverRequest, "build", build)
        patch.setattr(input_fixture, "python_fixture", python_fixture)
        value = _setup(tmp_path / "original")
    value.ledger = RSILedger(tmp_path / "ledger.sqlite3")
    value.native = replace(
        value.native, strategy=_strategy, failure_ledger=value.ledger,
        python_handoff_after_execution=_handoff,
    )
    value.context = PythonRSISchedulerInputContext(value.native, value.sidecar, value.proof)
    value.config = PythonProducerRSIExecutionConfig(producer, value.ledger, value.context)
    value.gateway = PythonProducerRSISolverGateway(value.config)
    value.controller = SimpleNamespace(
        ledger=value.ledger, gateway=value.gateway, producer_sidecar=value.sidecar,
        producer_workspace=value.root, _python_admission_bridge_wait_check=_wait_check,
    )
    return value


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_original_context_composes_stably_without_launch_or_writes(tmp_path, monkeypatch, producer):
    value = _fixture(tmp_path, monkeypatch, producer)
    before = _inventory(value.root)
    fingerprint = component_fingerprint(value.gateway)
    plan = value.gateway._plan(value.request, value.memory)
    assert plan == value.gateway.config.plan_factory(value.request, value.memory)
    assert value.gateway.ledger is value.ledger
    assert value.gateway.production_admission is False
    assert value.gateway.single_episode is True
    value.gateway.bind_python_admission_controller(value.controller)
    value.gateway.bind_python_admission_controller(value.controller)
    assert component_fingerprint(value.gateway) == fingerprint
    assert value.gateway.config.receipt_provider._python_admission_controller is value.controller
    assert _inventory(value.root) == before
    assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=plan.plan_sha256) is None


@pytest.mark.parametrize("producer", [None, True, "native_population"])
def test_unsupported_producer_refuses_before_context_or_ledger_access(producer):
    with pytest.raises(PythonProducerRSIGatewayError, match="producer_invalid"):
        PythonProducerRSIExecutionConfig(producer, object(), object())


def test_failure_ledger_must_be_controller_ledger(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    foreign = RSILedger(tmp_path / "foreign.sqlite3")
    with pytest.raises(PythonProducerRSIGatewayError, match="failure_ledger_mismatch"):
        PythonProducerRSIExecutionConfig("openevolve", foreign, value.context)


@pytest.mark.parametrize("producer", ["openevolve", "shinka"])
def test_producer_label_cannot_replace_original_launch_identity(tmp_path, monkeypatch, producer):
    value = _fixture(tmp_path, monkeypatch, producer)
    other = "shinka" if producer == "openevolve" else "openevolve"
    monkeypatch.setattr(
        "lunar_evolution.rsi_producer_gateway.make_native_rsi_scheduler_provider",
        lambda *_a: pytest.fail("mismatched label reached scheduler factory"),
    )
    with pytest.raises(PythonProducerRSIGatewayError, match="producer_binding_mismatch"):
        PythonProducerRSIExecutionConfig(other, value.ledger, value.context)


def test_python_handoff_is_mandatory(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    inputs = PythonRSISchedulerInputContext(
        replace(value.native, python_handoff_after_execution=None), value.sidecar, value.proof,
    )
    with pytest.raises(PythonProducerRSIGatewayError, match="handoff_supplier_required"):
        PythonProducerRSIExecutionConfig("openevolve", value.ledger, inputs)


def test_execution_config_accepts_explicit_native_supplier_as_the_only_handoff_form(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    # Isolate this facade's either-supplier requirement. The real static sink,
    # immutable input and native launch gates have dedicated component tests;
    # this sentinel must never be offered as an accepted launch configuration.
    monkeypatch.setattr("lunar_evolution.rsi_producer_gateway.PythonRSISchedulerPlanFactory", lambda _inputs: None)
    native = value.context.native_context

    def supplier(_run):
        raise AssertionError("configuration validation must not invoke a supplier")

    object.__setattr__(native, "python_handoff_after_execution", None)
    object.__setattr__(native, "python_handoff_after_native_execution", supplier)
    object.__setattr__(native, "live_modules_sink", object())
    config = PythonProducerRSIExecutionConfig("openevolve", value.ledger, value.context)
    assert config.inputs.native_context.python_handoff_after_native_execution is supplier
    object.__setattr__(native, "python_handoff_after_execution", _handoff)
    with pytest.raises(RSILearningError, match="supplier_conflict"):
        PythonProducerRSIExecutionConfig("openevolve", value.ledger, value.context)


def test_hostile_nested_sidecar_refuses_before_property_or_provider_access(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)

    class Hostile:
        @property
        def binding(self):
            pytest.fail("hostile sidecar property was evaluated")

    object.__setattr__(value.context, "producer_sidecar", Hostile())
    monkeypatch.setattr(
        "lunar_evolution.rsi_producer_gateway.make_native_rsi_scheduler_provider",
        lambda *_a: pytest.fail("invalid sidecar reached provider factory"),
    )
    with pytest.raises(RSILearningError):
        PythonProducerRSIExecutionConfig("openevolve", value.ledger, value.context)


@pytest.mark.parametrize("field", ["solver_id", "episode_id", "evaluator_sha256", "solver_settings"])
def test_request_drift_refuses_before_any_claim(tmp_path, monkeypatch, field):
    value = _fixture(tmp_path, monkeypatch)
    changes = {
        "solver_id": "shinka", "episode_id": "different-episode",
        "evaluator_sha256": "b" * 64, "solver_settings": (("different", True),),
    }
    changed = replace(value.request, **{field: changes[field]})
    with pytest.raises(RSILearningError):
        value.gateway.run(changed, value.memory)
    assert value.ledger.episode_result(value.request.episode_id) is None
    assert value.ledger.inspect_native_episode_claim(
        value.request, plan_sha256=value.gateway.config.plan_factory(value.request, value.memory).plan_sha256,
    ) is None


def test_memory_drift_refuses_before_claim(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    with pytest.raises(RSILearningError):
        value.gateway.run(value.request, MemorySnapshot("different", None, ()))
    assert value.ledger.episode_result(value.request.episode_id) is None


@pytest.mark.parametrize("field", ["producer_config", "config", "broker", "supplier"])
def test_composition_wiring_drift_refuses_before_dispatch(tmp_path, monkeypatch, field):
    value = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer_outcome",
        lambda *_a, **_k: pytest.fail("drift dispatched a producer"),
    )
    if field == "producer_config":
        value.gateway.producer_config = replace(value.config)
    elif field == "config":
        value.gateway.config = replace(value.gateway.config)
    elif field == "broker":
        value.native.broker_config.headers["changed"] = "yes"
    else:
        object.__setattr__(value.native, "python_handoff_after_execution", _strategy)
    with pytest.raises(RSILearningError):
        value.gateway.run(value.request, value.memory)
    assert value.ledger.episode_result(value.request.episode_id) is None


@pytest.mark.parametrize("field", ["ledger", "gateway", "producer_workspace", "producer_sidecar"])
def test_wrong_controller_cannot_bind(tmp_path, monkeypatch, field):
    value = _fixture(tmp_path, monkeypatch)
    replacements = {
        "ledger": object(), "gateway": object(), "producer_workspace": tmp_path / "foreign",
        "producer_sidecar": None,
    }
    setattr(value.controller, field, replacements[field])
    with pytest.raises(PythonProducerRSIGatewayError):
        value.gateway.bind_python_admission_controller(value.controller)
    assert value.gateway.config.receipt_provider._python_admission_controller is None


def test_bound_controller_cannot_be_replaced(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    value.gateway.bind_python_admission_controller(value.controller)
    with pytest.raises(RSILearningError, match="controller_changed"):
        value.gateway.bind_python_admission_controller(SimpleNamespace(**vars(value.controller)))
    assert value.gateway.config.receipt_provider._python_admission_controller is value.controller


def test_fresh_unbound_attempt_refuses_without_creating_a_started_claim(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    plan = value.gateway._plan(value.request, value.memory)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer_outcome",
        lambda *_a, **_k: pytest.fail("unbound fresh attempt dispatched a producer"),
    )
    with pytest.raises(PythonProducerRSIGatewayError, match="controller_required"):
        value.gateway.run(value.request, value.memory)
    assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=plan.plan_sha256) is None
    assert value.ledger.episode_result(value.request.episode_id) is None


def test_real_scheduler_dispatch_failure_preserves_original_claim_without_retry(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    value.gateway.bind_python_admission_controller(value.controller)
    calls = []

    def stop(*_args, **kwargs):
        calls.append(kwargs)
        assert all(callable(kwargs[key]) for key in (
            "python_handoff_after_execution", "prepared_observer", "evidence_revalidator",
        ))
        raise OSError("inert interruption before actual process creation")

    monkeypatch.setattr("lunar_evolution.rsi_native_scheduler.run_native_trusted_producer_outcome", stop)
    plan = value.gateway._plan(value.request, value.memory)
    with pytest.raises(NativeRSISolverGatewayError, match="attempt_unknown"):
        value.gateway.run(value.request, value.memory)
    claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=plan.plan_sha256)
    assert claim.status == "started" and len(calls) == 1
    assert value.ledger.episode_result(value.request.episode_id) is None
    restarted = PythonProducerRSISolverGateway(value.config)
    assert component_fingerprint(restarted) == component_fingerprint(value.gateway)
    with pytest.raises(NativeRSISolverGatewayError, match="recovery_required"):
        restarted.run(value.request, value.memory)
    assert len(calls) == 1
    assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=plan.plan_sha256) == claim


def test_terminal_replay_reopens_original_receipts_without_launch(tmp_path, monkeypatch):
    value = _fixture(tmp_path, monkeypatch)
    plan = value.gateway._plan(value.request, value.memory)
    evidence = bundle(value.request, plan)
    result = value.gateway._map_bundle(value.request, plan, evidence)
    value.ledger.claim_native_episode(value.request, plan_sha256=plan.plan_sha256)
    value.ledger.publish_native_episode_result(value.request, plan_sha256=plan.plan_sha256, result=result)
    recovered = []

    def recover(_self, request, observed_plan):
        assert request == value.request and observed_plan == plan
        recovered.append(True)
        return evidence

    monkeypatch.setattr(NativeRSISchedulerProvider, "recover", recover)
    monkeypatch.setattr(
        "lunar_evolution.rsi_native_scheduler.run_native_trusted_producer_outcome",
        lambda *_a, **_k: pytest.fail("terminal replay launched a producer"),
    )
    reopened = PythonProducerRSISolverGateway(value.config)
    assert reopened.run(value.request, value.memory) == result
    assert reopened.validate_replay(value.request, value.memory, result) == result
    assert len(recovered) == 2
    monkeypatch.setattr(NativeRSISchedulerProvider, "recover", lambda *_a: replace(evidence, worker_terminal_status="unknown"))
    with pytest.raises(NativeRSISolverGatewayError, match="replay_evidence_invalid"):
        reopened.validate_replay(value.request, value.memory, result)
    assert value.ledger.episode_result(value.request.episode_id) == (value.request, result)


@pytest.mark.parametrize("command", ["run", "resume"])
def test_native_cli_opt_in_refuses_before_contract_config_ledger_or_fixture_io(tmp_path, monkeypatch, capsys, command):
    from lunar_evolution import cli

    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("native opt-in initialized local state"))
    monkeypatch.setattr(cli, "fixture_solver_gateway", lambda *_a, **_k: pytest.fail("native opt-in fell back to fixture"))
    home = tmp_path / "absent-home"
    arguments = ["rsi", command, str(tmp_path / "absent-contract") if command == "run" else "absent-run",
                 "--solver-execution", "native-producer", "--json", "--home", str(home)]
    assert main(arguments) == 2
    assert json.loads(capsys.readouterr().err) == {
        "error": "rsi_python_producer_gateway_cli_accepted_runtime_required",
    }
    assert not home.exists()


def test_explicit_fixture_run_and_resume_keep_legacy_results(tmp_path, capsys):
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    home = tmp_path / "home"
    assert main(["rsi", "run", str(contract), "--run-id", "explicit-fixture", "--solver-execution", "fixture",
                 "--json", "--home", str(home)]) == 0
    run = json.loads(capsys.readouterr().out)
    assert main(["rsi", "resume", "explicit-fixture", "--solver-execution", "fixture",
                 "--json", "--home", str(home)]) == 0
    resumed = json.loads(capsys.readouterr().out)
    assert run["solver_execution"] == resumed["solver_execution"] == "provider_free_fixture"
    assert run["production_admission"] is resumed["production_admission"] is False
    assert run["memory_snapshot_sha256"] == resumed["memory_snapshot_sha256"]
