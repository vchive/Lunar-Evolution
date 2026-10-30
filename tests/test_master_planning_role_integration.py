"""Observe the Master message contract through real loops and the native fixture receipt gate."""

import hashlib
import json

import pytest
import test_master_plan_envelope_integration as envelopes
from test_effect_adapters import SubjectModel, _subject_request
from test_staged_effect_adapter import _config, _request

from lunar_evolution.agent_loop import HERMES_SYSTEM_PROMPT, AgentLoopRuntime
from lunar_evolution.effect_adapters import run_subject_adapter
from lunar_evolution.staged_workflow import StagedWorkflowRunner
from lunar_evolution.tools import LocalToolRegistry
from lunar_evolution.workflow_checkpoint import WorkflowController

clock = envelopes.clock
ROLE = "Planning stage: your only deliverable in this invocation is a short handoff plan for Build."
CONTEXT_START = "--- task for the later Build stage ---"
CONTEXT_END = "--- end Build task context ---"
UNKNOWN_STEP = (
    "PLAN_SENTINEL: Build must resolve UNKNOWN_PUBLIC_COLUMNS from the public inputs, "
    "then implement the objective scorer and validate the combined_score locally."
)
# Full external system messages, including the fixture's changing budget snapshots.
# Feature 145 updates only the native product name to Lunar Evolution. Restoring the prior
# system prefix reproduces all four original hashes from the pre-077 fixture; budget guidance,
# custom-system snapshots remain unchanged. Originals are retained in Git.
SYSTEM_DIGESTS = {
    "native": (
        "d327bf491a702c5d876aac69f672dfea402f721e58ed4b27bf932e70122bdf4c",
        "03451dcdb1c151d74fdb48f9d2f463a8a6e34da17faf5d47b9cd849081f81a4a",
        "c80ee7517f19577efacae6b3ceb3387bb54d60b1de2f13b305b1531573d454df",
        "eed1cea3a1a0430aac4af7ffbe41d8ae31835f84bdb111bf8cca3cdff8fb2503",
    ),
    "custom": (
        "6dfdf9ad4ceb527daa44fdb18a731e9a324d10787b0b5b696f9351b02cde20d9",
        "7471d29a07f20b6368c87262f9e66a675122ef9eb2a204cb345ac433a988acd1",
        "697af329bcde20038ebdda813e228b324b15ac88e426cda603e66dfa842ffb92",
        "c7b63334f3194217f91d67d0e72935c23636972c865770d02b96d23208922c7c",
    ),
}
# The bounded command-capture continuation updates only its output-limit description.
TOOLS_DIGEST = "b6729293de3b1d7497e36fb31efc444a9d698f50cdfd0fbc66f1ff2982d5e0eb"


class PlanningSubject(envelopes.EnvelopeSubject):
    """Fixed responses observe the protocol; they do not model whether a provider obeys it."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.schemas = []

    def master_text(self):
        return super().master_text().replace("PLAN_SENTINEL: produce the fixture answer.", UNKNOWN_STEP)

    def complete(self, messages, tools=(), timeout=None):
        self.schemas.append(json.loads(json.dumps(tools)))
        return super().complete(messages, tools, timeout)


@pytest.fixture
def native_trials(monkeypatch):
    run_native_trial = envelopes.run_native_trial
    results = []

    def capture(*args, **kwargs):
        result = run_native_trial(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(envelopes, "EnvelopeSubject", PlanningSubject)
    monkeypatch.setattr(envelopes, "run_native_trial", capture)
    return results


def assert_master_contract(model, original):
    for messages in model.messages[:2]:
        prompt = next(message["content"] for message in messages if message["role"] == "user")
        assert prompt.startswith(ROLE)
        assert prompt.count(CONTEXT_START) == original.count(CONTEXT_START) + 1
        assert prompt.count(CONTEXT_END) == original.count(CONTEXT_END) + 1
        assert prompt.count(original) == 1
        content_start = prompt.index(CONTEXT_START) + len(CONTEXT_START)
        original_start = prompt.index(original, content_start)
        assert prompt[original_start:original_start + len(original)] == original
        remainder = prompt[original_start + len(original):]
        assert remainder.lstrip("\n").startswith(CONTEXT_END)
        suffix = remainder.split(CONTEXT_END, 1)[1]
        assert "ONLY a JSON object" in suffix
        assert '{"plan": ["ordered implementation steps"], "expected_paths": ["solution output paths"]}' in suffix
        assert "_agent_summary.md" in suffix
        assert "unresolved" in suffix.lower() and "Build" in suffix


def assert_unchanged_delivery(model, runner, original_system, *, snapshot):
    original = runner._prompt
    master = runner.controller.load_master()
    expected_build = original + "\n\nValidated build plan:\n" + json.dumps(
        {"plan": master["plan"], "expected_paths": master["expected_paths"]}, ensure_ascii=False,
    ) + "\nSave complete candidate files early, check public constraints and finish with _agent_summary.md."
    expected_resume = expected_build + (
        "\nContinue this same attempt from the saved candidate and complete tool history; "
        "finish within the remaining aggregate budget."
    )
    for messages, expected in zip(model.messages[2:], (expected_build, expected_resume), strict=True):
        assert [message["content"] for message in messages if message["role"] == "user"][-1] == expected
        assert ROLE not in json.dumps(messages)
        assert "master-inspection" not in json.dumps(messages)
        assert UNKNOWN_STEP in json.dumps(messages)
        assert model.api_key not in json.dumps(messages) and "sk-1234567890" not in json.dumps(messages)
    guidance = []
    budgets = []
    for messages in model.messages:
        system = [message["content"] for message in messages if message["role"] == "system"]
        assert len(system) == 1
        base, budget_text = system[0].split("\n\n<lunar_runtime_budget>\n", 1)
        budget_json, advice = budget_text.split("\n</lunar_runtime_budget>\n", 1)
        assert base == original_system
        budgets.append(json.loads(budget_json))
        guidance.append(advice)
    assert all(advice == guidance[0] for advice in guidance)
    assert "If solving for files, save a complete candidate" in guidance[0]
    assert "Generated scripts must save their own incremental outputs atomically" in guidance[0]
    assert [budget["remaining_seconds"] for budget in budgets] == model.timeouts
    assert [budget["tokens_remaining"] for budget in budgets] == [100, 97, 94, 91]
    assert [budget["tool_steps_remaining"] for budget in budgets[:3]] == [8, 7, 7]
    system_digests = tuple(hashlib.sha256(next(
        message["content"] for message in messages if message["role"] == "system"
    ).encode()).hexdigest() for messages in model.messages)
    assert system_digests == SYSTEM_DIGESTS[snapshot]
    assert all(schema == model.schemas[0] for schema in model.schemas)
    assert hashlib.sha256(json.dumps(
        model.schemas[0], sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest() == TOOLS_DIGEST
    assert runner.agent.system_prompt == original_system
    assert runner.usage_ledger.snapshot.total_tokens == 12
    assert runner.usage_ledger.snapshot.cost_micros == 12


@pytest.mark.parametrize("envelope", ["raw", "fenced"])
def test_minimal_master_handoff_defers_unknowns_without_changing_build_or_native_authority(
    tmp_path, monkeypatch, clock, native_trials, envelope,
):
    run, attempt, model, runner, phases = envelopes.run_native_trial(
        tmp_path, monkeypatch, clock, envelope, public_vocabulary=True,
    )

    assert len(native_trials) == 1
    assert_master_contract(model, runner._prompt)
    assert_unchanged_delivery(model, runner, HERMES_SYSTEM_PROMPT, snapshot="native")
    assert "Solve the public task below" in runner._prompt
    assert phases == ["subject", "harness"] and model.turn == 4
    assert model.timeouts == [2, 1.75, 8.5, 6.5]
    assert run["ready"] is True and run["validity_score"] == 1 and run["overall_score"] == 0.81
    assert run["usage"] == {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12}
    assert run["interaction_turns"] == 4 and run["elapsed_ms"] == 2750
    assert runner.controller.state()["resume_used"] is True
    assert runner.controller.state()["usage"]["tool_steps"] == 5
    master = runner.controller.load_master()
    assert UNKNOWN_STEP in master["plan"]
    assert not {"score", "validity_score", "overall_score"}.intersection(master)
    receipt = json.loads((attempt / "subject/receipt.json").read_text())
    assert "overall_score" not in receipt and receipt["usage"] == run["usage"]
    assert "combined_score=999" in (attempt / "subject/_agent_summary.md").read_text()


def test_role_prefix_preserves_whitespace_rich_task_custom_system_and_exec_schema(tmp_path, clock):
    profile = envelopes.profile()
    request = _request(tmp_path / "subject", profile)
    config = _config(request, profile, checkpoint_after_rounds=1)
    original = ('\n  PUBLIC_TASK: 求解并交付文件。\r\n```json\n{"literal": "context"}\n```\n'
                + CONTEXT_START + "\nUser-provided delimiter text.\n" + CONTEXT_END + "\n\t")
    custom_system = "CUSTOM_SYSTEM_SENTINEL: preserve every public input and report evidence accurately."
    tools = LocalToolRegistry(allow_exec=True, command_timeout=10)
    model = PlanningSubject(clock, "raw")
    agent = AgentLoopRuntime(model, tools=tools, profile=profile, system_prompt=custom_system)
    runner = StagedWorkflowRunner(WorkflowController(request.parent, config.manifest), agent,
                                  request.parent, policy=config.policy)

    first = runner.run(original)
    assert first.status == "checkpointed" and model.turn == 3
    assert not (request.parent / "receipt.json").exists()
    final = runner.resume()

    assert final.status == "build_ready" and final.resumed is True
    assert_master_contract(model, original)
    assert_unchanged_delivery(model, runner, custom_system, snapshot="custom")
    assert model.schemas[0] == json.loads(json.dumps(tools.schemas()))
    assert "run_command" in {schema["function"]["name"] for schema in model.schemas[0]}
    assert model.timeouts == [2, 1.75, 8.5, 6.5]
    assert not (request.parent / "receipt.json").exists()


@pytest.mark.parametrize("failure", [
    "multiple_fences", "outside_object", "unsafe_path", "reserved_path", "missing_summary",
    "extra_score_field", "actual_key_path", "generic_key_path",
])
def test_master_role_keeps_existing_rejection_usage_and_no_retry_gates(
    tmp_path, monkeypatch, clock, native_trials, failure,
):
    envelopes.test_rejected_envelopes_or_semantics_keep_usage_without_build_receipt_harness_or_retry(
        tmp_path, monkeypatch, clock, failure,
    )
    assert len(native_trials) == 1
    _run, _attempt, model, runner, _phases = native_trials[0]
    assert_master_contract(model, runner._prompt)
    assert runner.agent.system_prompt == HERMES_SYSTEM_PROMPT


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
def test_nonstaged_subject_messages_remain_without_master_role_context(tmp_path, mode):
    request = _subject_request(tmp_path / "subject")
    if mode == "deep_evolution":
        payload = json.loads(request.read_text())
        payload.update(mode=mode, round_index=1, outer_rounds=5, previous_evaluation=None)
        request.write_text(json.dumps(payload))

    class ObservedSubject(SubjectModel):
        def __init__(self):
            super().__init__()
            self.messages = []

        def complete(self, messages, tools=(), timeout=None):
            self.messages.append(json.loads(json.dumps(messages)))
            return super().complete(messages, tools, timeout)

    model = ObservedSubject()
    receipt = run_subject_adapter(request, model_runtime=model, max_steps=4)

    assert receipt["status"] == "completed" and model.turn == 2
    for messages in model.messages:
        assert messages[0]["role"] == "system"
        system = messages[0]["content"]
        assert system.startswith(HERMES_SYSTEM_PROMPT)
        assert system.count("<lunar_runtime_budget>") == 1
        prompt = next(message["content"] for message in messages if message["role"] == "user")
        expected = "normal-mode subject" if mode == "normal" else "deep-evolution subject in outer round 1/5"
        assert prompt.startswith("You are the " + expected)
        assert prompt.count("--- public instruction ---\nwrite solution.json\n--- end instruction ---") == 1
        assert all(marker not in prompt for marker in (ROLE, CONTEXT_START, CONTEXT_END))
    assert not (request.parent / "workflow").exists()


def test_master_role_does_not_turn_build_failure_into_a_new_attempt(
    tmp_path, monkeypatch, clock, native_trials,
):
    envelopes.test_public_plan_build_failure_preserves_checkpoint_and_local_claim_without_score_or_retry(
        tmp_path, monkeypatch, clock,
    )
    assert len(native_trials) == 1
    _run, _attempt, model, runner, _phases = native_trials[0]
    assert_master_contract(model, runner._prompt)
    assert runner.agent.system_prompt == HERMES_SYSTEM_PROMPT
