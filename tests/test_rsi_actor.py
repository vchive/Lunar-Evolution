from pathlib import Path

import pytest

from lunar_evolution.agent_loop import AgentLoopTimeout
from lunar_evolution.automatic_solve_lifecycle import SolveExecutionCancelled
from lunar_evolution.rsi_actor import AgentLoopActorGateway
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.runtime import RuntimeResult


def _request(*, episode_id="episode-1", budget=None):
    digest = "a" * 64
    return SolverRequest.build(
        episode_id=episode_id,
        contract_sha256=digest,
        evaluator_sha256="b" * 64,
        environment_sha256="c" * 64,
        memory_snapshot_sha256="d" * 64,
        solver_id="lunar-agent-loop",
        budget=budget,
        practice_charter={"capability_gap": "write candidate"},
    )


class RuntimeFixture:
    name = "fixture-runtime"

    def __init__(self, mode="success"):
        self.mode = mode
        self.sink = None
        self.calls = []

    def set_event_sink(self, sink):
        self.sink = sink

    def run(self, prompt, workspace, timeout=None, **kwargs):
        self.calls.append((prompt, workspace, timeout, kwargs))
        if self.mode == "timeout":
            raise AgentLoopTimeout("deadline")
        if self.mode == "cancelled":
            raise SolveExecutionCancelled("cancelled")
        if self.sink:
            self.sink("agent_model_turn", {"turn": 1, "tool_call_count": 1, "has_text": True, "tool_steps": 1})
            self.sink("agent_tool_result", {"tool": "write_file", "success": True, "artifact_count": 1, "output_bytes": 10, "awaiting_input": False})
        (workspace / "candidate.py").write_text("print('candidate')")
        (workspace / "requirements.txt").write_text("example==1\n")
        return RuntimeResult("private final response", ("candidate.py",), {})


def test_agent_loop_success_without_receipts_is_unknown_and_only_public_trace(tmp_path: Path):
    runtime = RuntimeFixture()
    gateway = AgentLoopActorGateway(lambda: runtime, tmp_path)
    result = gateway.run(_request())
    assert result.status == "unknown"
    assert result.candidate_receipt_sha256 is None
    assert result.candidate_source_sha256
    assert result.dependency_sha256
    assert result.actor_fingerprint
    assert result.trace_events
    serialized = str(result.to_dict())
    assert "private final response" not in serialized
    assert "write_file" not in serialized
    assert gateway.workspace_root.joinpath("episodes", "episode-1", "candidate.py").is_file()


def test_dependency_digest_changes_with_dependency_content(tmp_path: Path):
    first_runtime = RuntimeFixture()
    first = AgentLoopActorGateway(lambda: first_runtime, tmp_path).run(_request(episode_id="episode-a"))
    class DifferentDependency(RuntimeFixture):
        def run(self, prompt, workspace, timeout=None, **kwargs):
            result = super().run(prompt, workspace, timeout, **kwargs)
            (workspace / "requirements.txt").write_text("different==2\n")
            return result

    second = AgentLoopActorGateway(lambda: DifferentDependency(), tmp_path).run(_request(episode_id="episode-b"))
    assert first.dependency_sha256 != second.dependency_sha256


def test_receipt_builder_promotes_completed(tmp_path: Path):
    receipt = {"candidate_receipt_sha256": "1" * 64, "execution_receipt_sha256": "2" * 64, "official_evaluation_receipt_sha256": "3" * 64, "solver_score": 1.0}
    calls = []

    def build_receipt(*args):
        calls.append(args)
        return receipt

    gateway = AgentLoopActorGateway(lambda: RuntimeFixture(), tmp_path, receipt_builder=build_receipt)
    result = gateway.run(_request())
    assert result.status == "completed"
    assert result.official_evaluation_receipt_sha256 == "3" * 64
    assert result.solver_score == 1.0
    assert len(calls) == 1


def test_factory_internal_type_error_is_not_retried(tmp_path: Path):
    calls = []

    def factory(workspace):
        calls.append(workspace)
        raise TypeError("factory body failure")

    result = AgentLoopActorGateway(factory, tmp_path).run(_request())
    assert result.status == "failed"
    assert len(calls) == 1


def test_actor_rejects_absolute_and_escaping_paths(tmp_path: Path):
    with pytest.raises(RSILearningError):
        AgentLoopActorGateway(lambda: RuntimeFixture(), tmp_path, candidate_paths=("/tmp/candidate.py",))
    with pytest.raises(RSILearningError):
        AgentLoopActorGateway(lambda: RuntimeFixture(), tmp_path, candidate_paths=("../candidate.py",))
    with pytest.raises(RSILearningError):
        AgentLoopActorGateway(lambda: RuntimeFixture(), tmp_path).run(_request(episode_id="../escape"))


@pytest.mark.parametrize(("mode", "status"), [("timeout", "timed_out"), ("cancelled", "cancelled")])
def test_runtime_terminal_mapping(tmp_path: Path, mode: str, status: str):
    result = AgentLoopActorGateway(lambda: RuntimeFixture(mode), tmp_path).run(_request())
    assert result.status == status
