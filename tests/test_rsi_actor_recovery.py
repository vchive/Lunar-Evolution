from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from lunar_evolution.rsi_actor import AgentLoopActorGateway
from lunar_evolution.rsi_controller import RSILearningController
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.runtime import RuntimeResult

HEX = "a" * 64


def request(episode_id: str = "actor-target") -> SolverRequest:
    return SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=HEX,
        evaluator_sha256="b" * 64,
        environment_sha256="c" * 64,
        memory_snapshot_sha256="d" * 64,
        solver_id="lunar-agent-loop",
    )


class SameNameRuntime:
    name = "same-runtime-name"

    def __init__(self, profile: str):
        self.profile = profile
        self.sink = None

    def fingerprint(self):
        return hashlib.sha256(("runtime:" + self.profile).encode()).hexdigest()

    def set_event_sink(self, sink):
        self.sink = sink

    def run(self, _prompt, workspace, _timeout=None, **_kwargs):
        (workspace / "candidate.py").write_text("print('candidate')")
        return RuntimeResult("done", ("candidate.py",), {})


class SameNameFactory:
    def __init__(self, profile: str):
        self.profile = profile

    def fingerprint(self):
        return hashlib.sha256(("runtime:" + self.profile).encode()).hexdigest()

    def __call__(self, _workspace):
        return SameNameRuntime(self.profile)


def test_actor_fingerprint_binds_runtime_profile_and_rejects_opaque_durable_profile(tmp_path: Path):
    first = SameNameFactory("temperature-0")
    second = SameNameFactory("temperature-1")
    first_gateway = AgentLoopActorGateway(
        first, tmp_path / "one", runtime_fingerprint=first.fingerprint(), actor_name="same",
    )
    second_gateway = AgentLoopActorGateway(
        second, tmp_path / "two", runtime_fingerprint=second.fingerprint(), actor_name="same",
    )
    assert first_gateway.fingerprint() != second_gateway.fingerprint()
    assert first_gateway.run(request("one")).actor_fingerprint == first_gateway.fingerprint()
    with pytest.raises(RSILearningError, match="rsi_actor_runtime_fingerprint_required"):
        AgentLoopActorGateway(lambda: SameNameRuntime("opaque"), tmp_path / "opaque").fingerprint()


def test_durable_resume_rejects_same_named_runtime_profile_drift(tmp_path: Path):
    first_factory = SameNameFactory("temperature-0")
    first_gateway = AgentLoopActorGateway(
        first_factory, tmp_path / "episodes", runtime_fingerprint=first_factory.fingerprint(), actor_name="same",
    )
    ledger_path = tmp_path / "rsi.sqlite3"
    first = RSILearningController(
        first_gateway, ledger=RSILedger(ledger_path), actor_fingerprint=first_gateway.fingerprint(),
    )
    first_result = first.run_drs(
        run_id="actor-durable", contract_sha256=HEX, evaluator_sha256="b" * 64,
        environment_sha256="c" * 64, solver_id="lunar-agent-loop", max_target_attempts=1,
    )
    assert first_result.status == "unknown"

    second_factory = SameNameFactory("temperature-1")
    second_gateway = AgentLoopActorGateway(
        second_factory, tmp_path / "episodes", runtime_fingerprint=second_factory.fingerprint(), actor_name="same",
    )
    second = RSILearningController(
        second_gateway, ledger=RSILedger(ledger_path), actor_fingerprint=first_gateway.fingerprint(),
    )
    with pytest.raises(RSILearningError, match="rsi_resume_gateway_fingerprint_drift"):
        second.resume(run_id="actor-durable")



def test_opaque_actor_remains_usable_without_durable_fingerprint(tmp_path):
    gateway = AgentLoopActorGateway(lambda: SameNameRuntime("unregistered"), tmp_path)
    result = gateway.run(request())
    assert result.status == "unknown"
    assert result.actor_fingerprint
    with pytest.raises(RSILearningError, match="actor_runtime_fingerprint_required"):
        RSILearningController(gateway, ledger=RSILedger(tmp_path / "rsi.db"),
                              actor_fingerprint=HEX).run_drs(
            run_id="opaque", contract_sha256=HEX, evaluator_sha256="b" * 64,
            environment_sha256="c" * 64, solver_id="lunar-agent-loop",
        )


@pytest.mark.parametrize("changed", ["root", "candidate", "dependency", "name"])
def test_actor_fingerprint_binds_workspace_and_path_configuration(tmp_path, changed):
    factory = SameNameFactory("stable")
    options = {}
    root = tmp_path
    if changed == "root":
        root = tmp_path / "other"
    elif changed == "candidate":
        options["candidate_paths"] = ("other.py",)
    elif changed == "dependency":
        options["dependency_paths"] = ("other.lock",)
    elif changed == "name":
        options["actor_name"] = "other-name"
    original = AgentLoopActorGateway(factory, tmp_path).fingerprint()
    assert AgentLoopActorGateway(factory, root, **options).fingerprint() != original


def test_actor_receipt_builder_requires_pinned_profile_for_durable_use(tmp_path):
    factory = SameNameFactory("stable")
    builder = lambda *_: {}
    gateway = AgentLoopActorGateway(factory, tmp_path, receipt_builder=builder)
    with pytest.raises(RSILearningError, match="receipt_builder_fingerprint_required"):
        gateway.fingerprint()
    first = AgentLoopActorGateway(factory, tmp_path, receipt_builder=builder,
                                  receipt_builder_fingerprint="1" * 64)
    second = AgentLoopActorGateway(factory, tmp_path, receipt_builder=builder,
                                   receipt_builder_fingerprint="2" * 64)
    assert first.fingerprint() != second.fingerprint()


def test_runtime_self_fingerprint_mismatch_fails_before_execution(tmp_path):
    class MismatchingFactory(SameNameFactory):
        def __call__(self, _workspace):
            return SameNameRuntime("actual")

    gateway = AgentLoopActorGateway(MismatchingFactory("expected"), tmp_path)
    result = gateway.run(request())
    assert result.status == "failed"
    assert not (tmp_path / "episodes/actor-target/candidate.py").exists()
