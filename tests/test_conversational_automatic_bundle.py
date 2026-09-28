"""Automatic multi-file solve intake preserves its mode across answer and resume."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_bundle_population import build_context, draft_for_score
from test_conversational_bundle import counts

from lunar_evolution import cli
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_generation_receipt import generation_event_id
from lunar_evolution.config import Config
from lunar_evolution.evolution import EvolutionError
from lunar_evolution.runtime import MockRuntime, RuntimeResult
from lunar_evolution.store import Store

SNAPSHOT_SOURCE = '''"""compiled-evaluator-hidden-marker"""
import json
import sys
from pathlib import Path

def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    limit = int(Path("inputs/value").read_text())
    value = json.loads(Path("output/result.json").read_text())["value"]
    valid = int(type(value) is int and 0 <= value <= limit)
    print(json.dumps({"schema_version": "1", "evaluator_id": "compiled-bundle",
        "validity": valid, "quality": float(value) if valid else None,
        "combined_score": float(value) if valid else 0.0, "detailed_scores": {},
        "error_info": [] if valid else [{"code": "out_of_bounds", "message": "Value exceeds the input limit."}]}))

if __name__ == "__main__":
    main()
'''


def _suite(*, audit=False):
    prefix = "audit" if audit else "compiler"
    values = (2, 8, 11) if audit else (1, 9, 999)
    return {
        "schema_version": "1", "constraint_coverage": ["out_of_bounds"],
        "probes": [{
            "name": f"{prefix}-{name}", "constraint_id": None if index < 2 else "out_of_bounds",
            "expected_validity": 1 if index < 2 else 0,
            "files": [{"path": "data/raw/value", "content": "10"},
                      {"path": "output/result.json", "content": json.dumps({"value": value})}],
        } for index, (name, value) in enumerate(zip(("low", "high", "invalid"), values, strict=True))],
        "score_order": [{"better": f"{prefix}-high", "worse": f"{prefix}-low"}],
    }


class AutomaticBundleRuntime(MockRuntime):
    name = "automatic-bundle-fixture"

    def __init__(self, contract, *, clarify=False):
        self.contract, self.clarify = contract, clarify
        self.contract_calls = self.bundle_calls = self.audit_calls = self.generator_calls = 0
        self.isolated_calls = 0
        self.generator_workspaces = []
        self.preparation_timeouts = []
        self.generator_timeouts = []
        self.generator_budgets = []

    def run_isolated(self, prompt, workspace, timeout=None):
        self.isolated_calls += 1
        return self.run(prompt, workspace, timeout)

    def run(self, prompt, workspace, timeout=None, **kwargs):
        if "contract compiler" in prompt:
            self.contract_calls += 1
            if self.clarify and self.contract_calls == 1:
                return RuntimeResult(json.dumps({
                    "status": "needs_input", "questions": [{"question": "Which objective?", "options": ["maximize value"]}],
                }))
            return RuntimeResult(json.dumps({"status": "compiled", "contract": self.contract.to_dict()}))
        if "frozen local evaluator bundle" in prompt:
            self.bundle_calls += 1
            self.preparation_timeouts.append(("compiler", timeout))
            assert "request.json" in prompt
            return RuntimeResult(json.dumps({
                **_suite(), "objective": "Maximize the integer value while remaining within its input bound.",
                "evaluator_source": SNAPSHOT_SOURCE,
            }))
        if "adversarial evaluator auditor" in prompt:
            self.audit_calls += 1
            self.preparation_timeouts.append(("auditor", timeout))
            assert "compiler-high" not in prompt
            return RuntimeResult(json.dumps(_suite(audit=True)))
        assert (workspace / "context/contract.json").is_file(), "ordinary DAG or model evaluator was invoked"
        assert (workspace / "context/inputs/value").read_bytes() == b"10"
        assert all(marker not in prompt for marker in ("compiled-evaluator-hidden-marker", "compiler-high", "audit-high", "scoring_contract"))
        assert not list(workspace.rglob("evaluator.py")) and not (workspace / "scoring").exists()
        self.generator_workspaces.append(workspace)
        self.generator_timeouts.append(timeout)
        if kwargs:
            self.generator_budgets.append(kwargs)
        draft = draft_for_score((1, 2, 999, 9)[self.generator_calls])
        self.generator_calls += 1
        metadata = {} if not kwargs else {
            "candidate_tool_steps_used": "0",
            "candidate_tool_steps_remaining": str(kwargs["max_tool_steps"]),
            "candidate_attempted_tool_calls": "0",
        }
        return RuntimeResult(json.dumps({"files": draft.source_files, "entrypoint": draft.filename}), metadata=metadata)


def automatic_setup(tmp_path, monkeypatch, *, clarify=False):
    context = build_context(tmp_path)
    context.bundle_pipeline.harness_path.unlink()
    payload = context.contract.to_dict()
    payload["hard_constraints"] = [{
        "id": "out_of_bounds", "description": "The selected integer is between zero and the input limit.",
        "source": "user_confirmed", "verification": "independent",
    }]
    runtime = AutomaticBundleRuntime(AlgorithmProblemContract.from_dict(payload), clarify=clarify)
    monkeypatch.setattr(cli, "build_runtime", lambda *_: runtime)
    args = [
        "solve", "Choose a feasible integer and deliver its complete working project.",
        "--runtime", "mock", "--workspace", str(tmp_path / "conversation"),
        "--evolve", "--multi-file", "--input", str(tmp_path / "inputs/value"),
        "--max-rounds", "1", "--stagnation-rounds", "3", "--population-size", "2",
        "--offspring-per-iteration", "2", "--islands", "2", "--seed", "7", "--timeout", "3",
        "--home", str(tmp_path / "home"), "--json",
    ]
    return runtime, args


@pytest.mark.parametrize("arguments", [
    ["--multi-file"],
    ["--evolve", "--multi-file", "--bundle-profile", "missing.json"],
    ["--evolve", "--multi-file", "--evaluator-command", "/not-used"],
    ["--evolve", "--multi-file", "--openevolve-command", "/not-used"],
    ["--evolve", "--multi-file", "--strategy", "openevolve"],
])
def test_automatic_bundle_invalid_modes_fail_before_creating_run(tmp_path, monkeypatch, capsys, arguments):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid options must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main(["solve", "optimize", *arguments, "--home", str(tmp_path / "home"), "--json"]) == 2
    assert "--multi-file" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("extra", [[], ["--compile-evaluator"]])
def test_automatic_bundle_request_has_only_additive_mode_marker(extra):
    parser = cli.build_parser()
    ordinary = parser.parse_args(["solve", "optimize", "--evolve"])
    automatic = parser.parse_args(["solve", "optimize", "--evolve", "--multi-file", *extra])
    cli._prepare_conversational_bundle(automatic)
    old = cli._evolution_request_payload(ordinary)
    new = cli._evolution_request_payload(automatic)
    assert "bundle_mode" not in old and "bundle_profile_sha256" not in old
    assert "evaluator_preparation_timeout" not in old
    assert new == {
        **old,
        "compile_evaluator": True,
        "bundle_mode": "compiled",
        "automatic_lifecycle_version": 1,
        "evaluator_preparation_timeout": 900.0,
        "evaluator_preparation_wall_timeout": 1860.0,
        "timeout_source": "default",
        "evaluator_preparation_timeout_source": "default",
        "evaluator_preparation_wall_timeout_source": "default",
    }
    assert "bundle_profile" not in new and "harness_path" not in new


def test_candidate_generation_budget_is_persisted_only_when_explicit():
    parser = cli.build_parser()
    explicit = parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
        "--candidate-generation-max-steps", "12",
    ])
    payload = cli._evolution_request_payload(explicit)
    assert payload["candidate_generation_max_steps"] == 12
    assert payload["candidate_generation_max_steps_source"] == "explicit"
    assert str(Path.cwd()) not in json.dumps(payload)

    omitted = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
    ]))
    assert "candidate_generation_max_steps" not in omitted
    assert "candidate_generation_max_steps_source" not in omitted


@pytest.mark.parametrize("value", [0, -1, 201])
def test_invalid_candidate_generation_budget_fails_before_run_creation(
    tmp_path, monkeypatch, capsys, value,
):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid candidate budget must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main([
        "solve", "optimize", "--evolve", "--multi-file",
        "--candidate-generation-max-steps", str(value),
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "candidate-generation-max-steps" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("value", ["1.5", "nan", "inf", "true"])
def test_noninteger_candidate_budget_is_rejected_by_parser(tmp_path, value):
    with pytest.raises(SystemExit) as error:
        cli.main([
            "solve", "optimize", "--evolve", "--multi-file",
            "--candidate-generation-max-steps", value,
            "--home", str(tmp_path / "home"),
        ])
    assert error.value.code == 2
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("arguments", [
    [],
    ["--evolve"],
    ["--evolve", "--bundle-profile", "missing.json"],
    ["--evolve", "--evaluator-command", "/not-used"],
    ["--evolve", "--strategy", "openevolve"],
])
def test_candidate_generation_budget_rejects_unsupported_modes(
    tmp_path, monkeypatch, capsys, arguments,
):
    monkeypatch.setattr(cli, "build_runtime", lambda *args, **kwargs: pytest.fail("runtime must not be built"))
    assert cli.main([
        "solve", "optimize", *arguments,
        "--candidate-generation-max-steps", "12",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "candidate-generation-max-steps" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


def test_candidate_generation_budget_continuation_requires_exact_match():
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
        "--candidate-generation-max-steps", "12",
    ]))
    cli._validate_evolution_override(
        parser.parse_args(["resume", "parent", "--candidate-generation-max-steps", "12"]),
        request,
    )
    cli._validate_evolution_override(parser.parse_args(["resume", "parent"]), request)
    with pytest.raises(EvolutionError, match="candidate generation setting"):
        cli._validate_evolution_override(
            parser.parse_args(["resume", "parent", "--candidate-generation-max-steps", "13"]),
            request,
        )

    legacy = dict(request)
    legacy.pop("candidate_generation_max_steps")
    legacy.pop("candidate_generation_max_steps_source")
    with pytest.raises(EvolutionError, match="candidate generation setting"):
        cli._validate_evolution_override(
            parser.parse_args(["resume", "parent", "--candidate-generation-max-steps", "12"]),
            legacy,
        )


@pytest.mark.parametrize("command", [
    ["solve", "--resume", "--run-id", "parent"],
    ["resume", "parent"], ["answer", "parent", "continue"],
])
@pytest.mark.parametrize("steps", [None, 1, 12, 200])
def test_candidate_budget_continuation_restores_stored_authority(command, steps):
    parser = cli.build_parser()
    supplied = [] if steps is None else ["--candidate-generation-max-steps", str(steps)]
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file", "--timeout", "600", *supplied,
    ]))
    for repeat in ([], supplied):
        args = parser.parse_args([*command, *repeat])
        cli._validate_evolution_override(args, request)
        restored = cli._evolution_args(args, request)
        assert restored.candidate_generation_max_steps == steps
        assert restored.timeout == 600
        assert restored.max_steps == args.max_steps


@pytest.mark.parametrize("patch", [
    {"candidate_generation_max_steps": True, "candidate_generation_max_steps_source": "explicit"},
    {"candidate_generation_max_steps": None},
    {"candidate_generation_max_steps_source": None},
    {"candidate_generation_max_steps": 12},
    {"candidate_generation_max_steps": 201, "candidate_generation_max_steps_source": "explicit"},
    {"candidate_generation_max_steps": "12", "candidate_generation_max_steps_source": "explicit"},
    {"candidate_generation_max_steps": 12, "candidate_generation_max_steps_source": "default"},
    {"candidate_generation_max_steps": 12, "candidate_generation_max_steps_source": "explicit", "bundle_mode": "single"},
])
def test_malformed_candidate_budget_authority_is_rejected(patch):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
    ]))
    request.update(patch)
    with pytest.raises(EvolutionError, match="candidate generation"):
        cli._validate_evolution_override(parser.parse_args(["resume", "parent"]), request)


@pytest.mark.parametrize("command", ["solve", "resume", "answer"])
@pytest.mark.parametrize("legacy", [False, True])
def test_candidate_budget_mismatch_has_no_continuation_side_effects(
    tmp_path, monkeypatch, capsys, command, legacy,
):
    from test_preparation_recovery_cli import snapshot

    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    if not legacy:
        args.extend(["--candidate-generation-max-steps", "12"])
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    parent, workspace = initial["run_id"], Path(initial["workspace"])
    before, pending = snapshot(store, parent, workspace), store.pending_input(parent)
    monkeypatch.setattr(cli, "build_runtime", lambda *a, **kw: pytest.fail("runtime must not be built"))
    followup = {
        "solve": ["solve", "--resume", "--run-id", parent],
        "resume": ["resume", parent], "answer": ["answer", parent, "maximize value"],
    }[command]
    assert cli.main([
        *followup, "--candidate-generation-max-steps", "13",
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "candidate generation" in json.loads(capsys.readouterr().err)["error"]
    assert snapshot(store, parent, workspace) == before
    assert store.pending_input(parent) == pending
    assert not (workspace / "evolution-run").exists()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)


@pytest.mark.parametrize("arguments", [
    ["--strategy", "openevolve"], ["--evaluator-command", "/not-used"],
    ["--openevolve-command", "/not-used"],
])
def test_candidate_budget_continuation_mode_switch_fails_before_runtime(
    tmp_path, monkeypatch, capsys, arguments,
):
    _, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    args.extend(["--candidate-generation-max-steps", "12"])
    assert cli.main(args) == 0
    parent = json.loads(capsys.readouterr().out)["run_id"]
    monkeypatch.setattr(cli, "build_runtime", lambda *a, **kw: pytest.fail("runtime must not be built"))
    assert cli.main([
        "solve", "--resume", "--evolve", "--run-id", parent, *arguments,
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "--multi-file" in json.loads(capsys.readouterr().err)["error"]


def test_candidate_budget_requires_multifile_when_adding_evolution_on_resume(tmp_path, monkeypatch):
    args = cli.build_parser().parse_args([
        "solve", "--resume", "--evolve", "--run-id", "parent", "--candidate-generation-max-steps", "12",
    ])
    monkeypatch.setattr(cli, "_latest_evolution_request", lambda *a: None)
    monkeypatch.setattr(cli, "_controller", lambda *a: pytest.fail("controller must not be built"))
    with pytest.raises(ValueError, match="requires --evolve --multi-file"):
        cli._solve(Config(tmp_path / "home"), args)


@pytest.mark.parametrize("arguments", [
    ["evolve", "contract.json"],
    ["evolve-bundle", "contract.json", "--profile", "profile.json", "--workspace", "workspace", "--agent-runtime", "mock"],
])
def test_standalone_parsers_do_not_accept_candidate_budget(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.build_parser().parse_args([*arguments, "--candidate-generation-max-steps", "12"])
    assert error.value.code == 2
    assert "unrecognized arguments: --candidate-generation-max-steps" in capsys.readouterr().err


@pytest.mark.parametrize("clarify", [False, True])
def test_candidate_generation_budget_is_forwarded_and_receipt_bound(
    tmp_path, monkeypatch, capsys, clarify,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=clarify)
    args.extend([
        "--candidate-generation-max-steps", "12", "--evaluator-preparation-timeout", "7",
        "--max-steps", "4",
    ])
    captured = []
    original = cli.AgentCandidateGenerator

    def wrapped(*generator_args, **generator_kwargs):
        captured.append(generator_kwargs.get("candidate_budget"))
        return original(*generator_args, **generator_kwargs)

    monkeypatch.setattr(cli, "AgentCandidateGenerator", wrapped)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    if clarify:
        assert captured == []
        assert cli.main([
            "answer", first["run_id"], "maximize value",
            "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
        ]) == 0
        first = json.loads(capsys.readouterr().out)
    assert len(captured) == 1
    assert captured[0].budget_id == "candidate-generation"
    assert captured[0].max_tool_steps == 12
    assert captured[0].timeout_seconds == 3.0
    assert runtime.generator_budgets == [
        {"max_tool_steps": 12, "budget_id": f"candidate-{iteration:08d}-{call:04d}"}
        for iteration, call in [(0, 1), (0, 2), (1, 3), (1, 4)]
    ]
    assert runtime.generator_timeouts == [3.0] * 4
    assert runtime.preparation_timeouts == [("compiler", 7.0), ("auditor", 7.0)]
    store = Store(tmp_path / "home/state.db")
    request = next(event["payload"] for event in store.list_events(first["run_id"])
                   if event["type"] == "evolution_requested")
    assert request["candidate_generation_max_steps"] == 12
    assert request["candidate_generation_max_steps_source"] == "explicit"
    child_id = first["evolution"]["run_id"]
    receipts = [event for event in store.list_events(child_id)
                if event["type"] == "agent_candidate_generation"]
    assert len(receipts) == 4
    for event, authority in zip(receipts, runtime.generator_budgets, strict=True):
        payload = event["payload"]
        assert event["id"] == generation_event_id(payload)
        assert payload["run_id"] == child_id
        assert payload["task_id"] == event["task_id"]
        assert payload["budget_id"] == authority["budget_id"]
        assert payload["max_tool_steps"] == authority["max_tool_steps"]
        assert payload["outcome"] == "completed"
        assert payload["completion"] is True
        assert payload["candidate_id"]
        assert len(payload["source_bundle_sha256"]) == 64
    assert cli.main([
        "resume", first["run_id"], "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    capsys.readouterr()
    # A completed lifecycle handoff returns its persisted terminal result without allocating a
    # new generator or candidate budget on an idempotent continuation.
    assert captured == [captured[0]]
    assert runtime.generator_calls == 4
    assert receipts == [event for event in store.list_events(child_id)
                        if event["type"] == "agent_candidate_generation"]


@pytest.mark.parametrize("command", [
    ["solve", "--resume", "--run-id", "parent"], ["resume", "parent"], ["answer", "parent", "continue"],
])
def test_automatic_mode_is_restored_without_repeating_flags(command):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
    ]))
    args = parser.parse_args(command)
    cli._prepare_conversational_bundle(args)
    cli._validate_conversational_bundle_request(args, request)
    resumed = cli._evolution_args(args, request)
    assert resumed.multi_file is True and resumed.compile_evaluator is True and resumed.evolve is True
    assert getattr(resumed, "bundle_profile", None) is None
    assert resumed.evaluator_preparation_timeout == 900.0


def test_automatic_preparation_timeout_uses_legacy_timeout_when_request_omits_it():
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file", "--timeout", "3",
    ]))
    del request["evaluator_preparation_timeout"]

    resumed = cli._evolution_args(parser.parse_args(["resume", "parent"]), request)

    assert resumed.evaluator_preparation_timeout == 3.0


def test_automatic_preparation_timeout_override_must_match_persisted_request():
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args([
        "solve", "optimize", "--evolve", "--multi-file",
        "--timeout", "3", "--evaluator-preparation-timeout", "5",
    ]))
    supplied = parser.parse_args([
        "resume", "parent", "--evaluator-preparation-timeout", "7",
    ])

    with pytest.raises(EvolutionError, match="evaluator_preparation_timeout"):
        cli._validate_evolution_override(supplied, request)


@pytest.mark.parametrize("value", ["0", "-1", "86401", "nan", "inf"])
def test_invalid_automatic_preparation_timeout_fails_before_creating_run(
    tmp_path, monkeypatch, capsys, value,
):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid preparation timeout must be rejected before runtime construction")

    monkeypatch.setattr(cli, "build_runtime", forbidden)
    assert cli.main([
        "solve", "optimize", "--evolve", "--multi-file",
        "--evaluator-preparation-timeout", value,
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "evaluator-preparation-timeout" in json.loads(capsys.readouterr().err)["error"]
    assert not (tmp_path / "home/state.db").exists()


@pytest.mark.parametrize("mode", [None, "single", False, {}, "external"])
def test_invalid_automatic_mode_marker_is_rejected(mode):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve"]))
    request.update(bundle_mode=mode, compile_evaluator=True)
    with pytest.raises(EvolutionError, match="mode_invalid"):
        cli._validate_conversational_bundle_request(
            parser.parse_args(["solve", "--resume", "--run-id", "parent"]), request,
        )


@pytest.mark.parametrize("arguments", [["--evaluator-command", "/not-used"], ["--strategy", "openevolve"], ["--bundle-profile", "missing"]])
def test_automatic_resume_rejects_switch_to_another_mode(arguments):
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve", "--multi-file"]))
    args = parser.parse_args(["solve", "--resume", "--run-id", "parent", *arguments])
    with pytest.raises(ValueError, match="--multi-file"):
        cli._validate_conversational_bundle_request(args, request)


def test_existing_single_file_handoff_cannot_switch_to_automatic_bundle():
    parser = cli.build_parser()
    request = cli._evolution_request_payload(parser.parse_args(["solve", "optimize", "--evolve", "--compile-evaluator"]))
    args = parser.parse_args(["solve", "--resume", "--run-id", "parent", "--multi-file"])
    with pytest.raises(EvolutionError, match="mode_mismatch"):
        cli._validate_conversational_bundle_request(args, request)


@pytest.mark.parametrize("resume_command", ["solve", "resume"])
def test_automatic_solve_delivers_scored_bundle_and_resumes_without_compilation(tmp_path, monkeypatch, capsys, resume_command):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    if resume_command == "resume":
        args.append("--compile-evaluator")
    assert not (tmp_path / "profile.json").exists()
    assert not (tmp_path / "harness.py").exists()
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    parent = Path(first["workspace"])
    assert first["status"] == "succeeded"
    assert first["evolution"]["result"]["best_score"] == 9
    assert first["evolution"]["result"]["valid_candidates"] == 3
    delivery = first["evolution"]["materialization"]
    assert delivery["mode"] == "bundle" and delivery["status"] == "succeeded"
    assert json.loads((parent / "output/result.json").read_text())["value"] == 9
    copied = parent / delivery["delivery_path"]
    assert (copied / "source/solve/helper.py").read_text().endswith("return 9\n")
    assert (copied / "evaluation/evaluator.py").read_bytes() == (parent / "evaluator-bundle/evaluator.py").read_bytes()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert runtime.isolated_calls == 3
    store = Store(tmp_path / "home/state.db")
    events = store.list_events(first["run_id"])
    rows = store.list_artifacts(first["run_id"])
    request = next(event["payload"] for event in events if event["type"] == "evolution_requested")
    assert request["bundle_mode"] == "compiled" and request["compile_evaluator"] is True
    assert "bundle_profile_sha256" not in request and "harness_path" not in request
    assert "candidate_generation_max_steps" not in request
    assert runtime.generator_budgets == []
    assert not any(event["type"] == "agent_candidate_generation"
                   for event in store.list_events(first["evolution"]["run_id"]))
    assert str(tmp_path) not in json.dumps(request)
    assert len([event for event in events if event["type"] == "bundle_profile_prepared"]) == 1
    assert (parent / "bundle-profile.json").is_file()
    assert not any(event["type"] == "evolved_candidate_materialized" for event in events)
    before = counts(parent)
    assert len(before) == 4 and set(before.values()) == {b"x"}
    (tmp_path / "inputs/value").write_bytes(b"99")
    followup = ["solve", "--resume", "--run-id", first["run_id"]] if resume_command == "solve" else ["resume", first["run_id"]]
    assert cli.main([*followup, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["evolution"]["materialization"] == delivery
    assert second["evolution"]["run_id"] == first["evolution"]["run_id"]
    assert counts(parent) == before
    assert store.list_artifacts(first["run_id"]) == rows
    assert store.list_events(first["run_id"]) == events
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
    assert cli._status_payload(Config(tmp_path / "home"), first["run_id"])["evolution"]["linked"]["materialization"] == delivery


def test_acceptance_hook_observes_preparation_before_generation(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    seen = []

    def observe(store, parent_id, contract, control):
        assert len([event for event in store.list_events(parent_id)
                    if event["type"] == "bundle_profile_prepared"]) == 1
        assert contract.digest()
        assert control.check("preparation") > 0
        assert runtime.generator_calls == 0
        seen.append(parent_id)

    assert cli.main([*args, "--solve-wall-timeout", "3000"],
                    _acceptance_preparation_hook=observe) == 0
    result = json.loads(capsys.readouterr().out)
    assert seen == [result["run_id"]]
    assert runtime.generator_calls == 4


def test_acceptance_hook_failure_stops_before_generation(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)

    def reject(*_args):
        raise ValueError("acceptance_binding_failed")

    assert cli.main([*args, "--solve-wall-timeout", "3000"],
                    _acceptance_preparation_hook=reject) == 2
    assert json.loads(capsys.readouterr().err)["error"] == "acceptance_binding_failed"
    assert runtime.generator_calls == 0


def test_automatic_preparation_timeout_is_separate_from_candidate_execution(
    tmp_path, monkeypatch, capsys,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    args.extend(("--evaluator-preparation-timeout", "7"))

    assert cli.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    parent = Path(result["workspace"])
    request = next(
        event["payload"]
        for event in Store(tmp_path / "home/state.db").list_events(result["run_id"])
        if event["type"] == "evolution_requested"
    )
    profile = json.loads((parent / "bundle-profile.json").read_text())

    assert request["timeout"] == 3.0
    assert request["evaluator_preparation_timeout"] == 7.0
    assert runtime.preparation_timeouts == [("compiler", 7.0), ("auditor", 7.0)]
    assert runtime.generator_timeouts == [3.0] * 4
    assert profile["timeout_seconds"] == 3.0
    assert profile["evaluator"]["timeout_seconds"] == 3.0


@pytest.mark.parametrize("repeat_mode", [False, True])
def test_automatic_answer_prepares_profile_after_clarification(tmp_path, monkeypatch, capsys, repeat_mode):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    parent = Path(initial["workspace"])
    assert initial["status"] == "awaiting_input"
    assert not (parent / "bundle-profile.json").exists()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)
    extra = ["--multi-file"] if repeat_mode else []
    assert cli.main([
        "answer", initial["run_id"], "maximize value", *extra,
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "succeeded" and second["evolution"]["materialization"]["mode"] == "bundle"
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (2, 1, 1, 4)


@pytest.mark.parametrize("changed", ["profile", "missing_profile", "harness", "input", "link"])
def test_automatic_resume_rejects_changed_preparation_before_compiler_or_candidate(tmp_path, monkeypatch, capsys, changed):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    parent = Path(first["workspace"])
    if changed == "missing_profile":
        (parent / "bundle-profile.json").unlink()
    elif changed == "link":
        store = Store(tmp_path / "home/state.db")
        with store._connect() as connection:
            connection.execute("UPDATE runs SET workspace = ? WHERE id = ?", (str(tmp_path / "wrong-child"), first["evolution"]["run_id"]))
    else:
        target = parent / {"profile": "bundle-profile.json", "harness": "evaluator-bundle/evaluator.py", "input": "data/raw/value"}[changed]
        target.chmod(0o600)
        target.write_bytes(target.read_bytes() + b" ")
    before = counts(parent)
    assert cli.main([
        "resume", first["run_id"], "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert counts(parent) == before
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)


def test_automatic_pending_mode_conflict_preserves_answer_and_compiler_count(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    store = Store(tmp_path / "home/state.db")
    before = store.pending_input(initial["run_id"])
    assert cli.main([
        "answer", initial["run_id"], "maximize value", "--evaluator-command", "/not-used",
        "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert "--multi-file" in json.loads(capsys.readouterr().err)["error"]
    assert store.pending_input(initial["run_id"]) == before
    assert not list(Path(initial["workspace"]).rglob("input-answer.json"))
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)


def test_pending_input_drift_is_rejected_before_answer_and_contract_compiler(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch, clarify=True)
    assert cli.main(args) == 0
    initial = json.loads(capsys.readouterr().out)
    parent = Path(initial["workspace"])
    store = Store(tmp_path / "home/state.db")
    pending = store.pending_input(initial["run_id"])
    (parent / "data/raw/value").write_bytes(b"11")
    assert cli.main([
        "answer", initial["run_id"], "maximize value", "--runtime", "mock",
        "--home", str(tmp_path / "home"), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err)["error"]
    assert store.pending_input(initial["run_id"]) == pending
    assert not list(parent.rglob("input-answer.json"))
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 0, 0, 0)


def test_resume_after_frozen_evaluator_before_profile_does_not_recompile(tmp_path, monkeypatch, capsys):
    from lunar_evolution import automatic_solve_bundle

    class SimulatedCrash(BaseException):
        pass

    def stop_before_profile(*args, **kwargs):
        raise SimulatedCrash("stopped after frozen evaluator publication")

    runtime, args = automatic_setup(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        patch.setattr(automatic_solve_bundle, "_write_profile", stop_before_profile)
        with pytest.raises(SimulatedCrash):
            cli.main(args)
    capsys.readouterr()
    store = Store(tmp_path / "home/state.db")
    parent = store.get_run_by_workspace(tmp_path / "conversation")
    assert parent is not None and parent.current_plan_id is not None
    assert (Path(parent.workspace) / "evaluator-bundle/manifest.json").is_file()
    assert not (Path(parent.workspace) / "bundle-profile.json").exists()
    assert not (Path(parent.workspace) / "evolution-run").exists()
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 0)
    assert cli.main([
        "resume", parent.id, "--runtime", "mock", "--home", str(tmp_path / "home"), "--json",
    ]) == 0
    final = json.loads(capsys.readouterr().out)
    assert final["evolution"]["materialization"]["mode"] == "bundle"
    assert (runtime.contract_calls, runtime.bundle_calls, runtime.audit_calls, runtime.generator_calls) == (1, 1, 1, 4)
