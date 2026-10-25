"""Fresh opt-in subject transcripts; fake models only, with no evaluator calls."""

import copy
import json
import os
import stat
from dataclasses import replace

import pytest
from test_effect_adapters import SubjectModel, _subject_request
from test_staged_effect_adapter import StagedSubject, _config
from test_staged_effect_adapter import _profile as _staged_profile

from lunar_evolution.cli import build_parser, main
from lunar_evolution.effect_adapters import (
    EffectAdapterError,
    _model_profile_digest,
    run_subject_adapter,
)
from lunar_evolution.profiles import ModelProfile
from lunar_evolution.runtime import ModelRequestFailure, ModelTurn, ToolCall

SECRET = "SUBJECT-HISTORY-KEY-SENTINEL"


def _profile():
    return ModelProfile(
        "history-fixture", SubjectModel.model, max_steps=4, timeout_seconds=10,
        max_total_tokens=1000,
    )


def _configure(request, profile, *, deep=False, round_index=1):
    payload = json.loads(request.read_bytes())
    payload["model_profile_sha256"] = _model_profile_digest(profile)
    if deep:
        payload.update(
            mode="deep_evolution", round_index=round_index, outer_rounds=2,
            previous_evaluation=None if round_index == 1 else {
                "round_index": round_index - 1, "validity_score": 1.0,
                "quality_score": 0.5, "overall_score": 0.5,
            },
            receipt_path=f"receipts/{round_index:03d}.json",
        )
    request.write_text(json.dumps(payload))
    return payload


class RecordingSubject(SubjectModel):
    def __init__(self, final_text="done"):
        super().__init__()
        self.requests = []
        self.final_text = final_text

    def complete(self, messages, tools=(), timeout=None):
        self.requests.append(copy.deepcopy((messages, tools, timeout)))
        turn = super().complete(messages, tools, timeout)
        return replace(turn, text=self.final_text) if not turn.tool_calls else turn


@pytest.mark.parametrize("deep", [False, True])
def test_opt_in_keeps_requests_receipt_bytes_and_budgets_with_equal_tool_results(
    tmp_path, monkeypatch, deep,
):
    monkeypatch.setattr("lunar_evolution.agent_loop.time.monotonic", lambda: 100.0)
    profile = _profile()
    requests = []
    receipts = []
    payloads = []
    for history in (False, True):
        request = _subject_request(tmp_path / str(history))
        payload = _configure(request, profile, deep=deep)
        raw_request = request.read_bytes()
        public = {path: path.read_bytes() for path in (request.parent / "case").rglob("*") if path.is_file()}
        model = RecordingSubject()
        receipt = run_subject_adapter(
            request, model_runtime=model, model_profile=profile,
            max_steps=4, timeout=10, session_history=history,
        )
        requests.append(model.requests)
        receipts.append((request.parent / payload["receipt_path"]).read_bytes())
        payloads.append(receipt)
        assert model.turn == 2 and receipt["interaction_turns"] == 2
        assert request.read_bytes() == raw_request
        assert all(path.read_bytes() == raw for path, raw in public.items())
        history_path = request.parent / "sessions" / ("subject-001.jsonl" if deep else "subject.jsonl")
        assert history_path.is_file() is history
        if history:
            transcript = [json.loads(line) for line in history_path.read_text().splitlines()]
            assert [message["role"] for message in transcript] == [
                "system", "user", "assistant", "tool", "tool", "assistant",
            ]
            assert stat.S_IMODE(history_path.stat().st_mode) == 0o600
            assert "lunar_runtime_budget" not in history_path.read_text()
        else:
            assert not (request.parent / "sessions").exists()
    assert requests[0] == requests[1]
    assert receipts[0] == receipts[1] and payloads[0] == payloads[1]


class FailingSubject(SubjectModel):
    api_key = SECRET

    def __init__(self):
        super().__init__()
        self.error = ModelRequestFailure(SECRET, "transport_timeout")

    def complete(self, messages, tools=(), timeout=None):
        self.turn += 1
        if self.turn == 3:
            raise self.error from TimeoutError(SECRET)
        call = ToolCall(
            f"call-{self.turn}", "write_file" if self.turn == 1 else "read_file",
            {"path": "debug.txt", **({"content": SECRET} if self.turn == 1 else {})},
        )
        return ModelTurn(
            "", (call,), response_model=self.model,
            usage={"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        )


@pytest.mark.parametrize("deep", [False, True])
def test_later_failure_retains_redacted_tool_exchanges_without_a_success_receipt(tmp_path, deep):
    profile = _profile()
    request = _subject_request(tmp_path / "subject")
    payload = _configure(request, profile, deep=deep)
    model = FailingSubject()
    with pytest.raises(EffectAdapterError) as caught:
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile, session_history=True,
        )
    assert caught.value.__cause__ is model.error and model.turn == 3
    history_path = request.parent / "sessions" / ("subject-001.jsonl" if deep else "subject.jsonl")
    raw = history_path.read_text()
    assert SECRET not in raw and "[REDACTED]" in raw
    transcript = [json.loads(line) for line in raw.splitlines()]
    assert [message["role"] for message in transcript] == [
        "system", "user", "assistant", "tool", "assistant", "tool",
    ]
    assert [message["tool_calls"][0]["function"]["name"] for message in transcript if "tool_calls" in message] == ["write_file", "read_file"]
    receipt_path = request.parent / payload["receipt_path"]
    assert not receipt_path.exists()
    diagnostic = json.loads(receipt_path.with_suffix(".failure.json").read_bytes())
    assert diagnostic["schema_version"] == "6" and diagnostic["model_turns"] == 2
    assert diagnostic["tool_steps"] == 2 and diagnostic["usage_completeness"] == "partial"
    assert SECRET not in json.dumps(diagnostic) and "debug.txt" not in json.dumps(diagnostic)


@pytest.mark.parametrize("unsafe", [
    "file", "directory", "fifo", "symlink", "dangling", "hardlink",
    "ancestor_symlink", "ancestor_file",
])
def test_existing_or_unsafe_history_is_rejected_before_model_calls(tmp_path, unsafe):
    request = _subject_request(tmp_path / "subject")
    parent = request.parent / "sessions"
    path = parent / "subject.jsonl"
    external = tmp_path / "external"
    external.mkdir()
    old = external / "old.jsonl"
    old.write_text(json.dumps({"role": "user", "content": SECRET}) + "\n")
    before = old.read_bytes()
    if unsafe == "ancestor_symlink":
        parent.symlink_to(external, target_is_directory=True)
    elif unsafe == "ancestor_file":
        parent.write_text("keep this file")
    else:
        parent.mkdir()
        if unsafe == "file":
            path.write_bytes(before)
        elif unsafe == "directory":
            path.mkdir()
        elif unsafe == "fifo":
            os.mkfifo(path)
        elif unsafe == "hardlink":
            os.link(old, path)
        else:
            path.symlink_to(old if unsafe == "symlink" else external / "absent")
    model = RecordingSubject()
    with pytest.raises((OSError, ValueError)):
        run_subject_adapter(request, model_runtime=model, session_history=True)
    assert model.turn == 0 and not model.requests
    assert old.read_bytes() == before
    assert not (request.parent / "receipt.json").exists()
    if unsafe == "ancestor_symlink":
        assert not (external / "subject.jsonl").exists()
    if unsafe == "file":
        assert path.read_bytes() == before


def test_deep_rounds_have_separate_fresh_history_without_prior_round_replay(tmp_path):
    request = _subject_request(tmp_path / "subject")
    profile = _profile()
    _configure(request, profile, deep=True)
    first = RecordingSubject("ROUND-ONE-HISTORY-SENTINEL")
    run_subject_adapter(request, model_runtime=first, model_profile=profile, session_history=True)
    old_path = request.parent / "sessions/subject-001.jsonl"
    old = old_path.read_bytes()
    _configure(request, profile, deep=True, round_index=2)
    second = RecordingSubject()
    run_subject_adapter(request, model_runtime=second, model_profile=profile, session_history=True)
    assert (request.parent / "sessions/subject-002.jsonl").is_file()
    assert "ROUND-ONE-HISTORY-SENTINEL" not in json.dumps(second.requests)
    assert old_path.read_bytes() == old
    assert first.turn == second.turn == 2


def test_staged_combination_is_rejected_before_model_and_keeps_staged_ownership(tmp_path):
    profile = _staged_profile()
    request = _subject_request(tmp_path / "subject")
    _configure(request, profile)
    model = StagedSubject()
    with pytest.raises(EffectAdapterError, match="staged workflow"):
        run_subject_adapter(
            request, model_runtime=model, model_profile=profile,
            workflow_config=_config(request, profile), session_history=True,
        )
    assert model.turn == 0
    assert not (request.parent / "workflow").exists()
    assert not (request.parent / "sessions").exists()


def test_subject_cli_opt_in_reaches_fresh_history_without_keys_in_output(tmp_path, monkeypatch, capsys):
    request = _subject_request(tmp_path / "subject")
    model = RecordingSubject()
    monkeypatch.setattr("lunar_evolution.effect_adapters.OpenAICompatibleRuntime", lambda **kwargs: model)
    assert build_parser().parse_args(["effect-subject", str(request)]).session_history is False
    assert main(["effect-subject", str(request), "--session-history", "--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["status"] == "completed" and model.api_key not in output
    assert (request.parent / "sessions/subject.jsonl").is_file()
