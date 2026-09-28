"""Offline checks for the single registered native acceptance invocation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from test_acceptance_launch import _registered_origin
from test_acceptance_registration import _git, _write_registration

from lunar_evolution import cli
from lunar_evolution.acceptance_campaign_audit import (
    AcceptanceCampaignAuditError,
    verify_native_campaign_audit,
)
from lunar_evolution.acceptance_native_runner import (
    AcceptanceNativeRunnerError,
    run_registered_acceptance,
)
from lunar_evolution.acceptance_request_budget import (
    AcceptanceRequestBudget,
    AcceptanceRequestBudgetError,
    own_request_budget,
)
from lunar_evolution.runtime import ModelTurn, OpenAICompatibleRuntime


def _registered_native(tmp_path: Path):
    checkout, parent, manifest, registration_path, seal_path, _origin = _registered_origin(tmp_path)
    manifest = dict(manifest)
    manifest.update(provider="openai-compatible", model="glm-5.2", api_mode="chat_completions")
    task = b"Make a valid program"
    task_path = checkout / manifest["task_material"]["path"]
    task_path.write_bytes(task)
    manifest["task_material"] = {
        **manifest["task_material"], "size": len(task), "sha256": hashlib.sha256(task).hexdigest(),
    }
    manifest["task_sha256"] = manifest["task_material"]["sha256"]
    manifest = _write_registration(manifest, registration_path, seal_path)
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "native registration")
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/main")
    return checkout, parent, manifest, registration_path, seal_path


def _run(fixture):
    checkout, parent, _manifest, registration_path, seal_path = fixture
    return run_registered_acceptance(
        registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
    )


def test_identity_rejected_before_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, registration_path, seal_path, _origin = fixture
    monkeypatch.setenv("LUNAR_EVOLUTION_MODEL_ENDPOINT", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("LUNAR_EVOLUTION_API_KEY", "fixture-key")
    with pytest.raises(AcceptanceNativeRunnerError, match="^acceptance_native_identity_unsupported$"):
        run_registered_acceptance(
            registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
        )
    assert not (parent / manifest["campaign_root"]).exists()


@pytest.mark.parametrize("reenter", [False, True])
def test_single_native_invocation_retains_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reenter: bool,
) -> None:
    fixture = _registered_native(tmp_path)
    _checkout, parent, manifest, _registration_path, _seal_path = fixture
    monkeypatch.setenv("LUNAR_EVOLUTION_MODEL_ENDPOINT", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("LUNAR_EVOLUTION_API_KEY", "fixture-key")
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.prepare_acceptance_runtime_binding",
        lambda *_args, **_kwargs: {"binding_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.publish_acceptance_observation_binding",
        lambda *_args, **_kwargs: {"binding": {"observation_binding_sha256": "b" * 64}},
    )
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.audit_native_campaign",
        lambda *_args, **_kwargs: {
            "schema_version": "1", "scope": "acceptance_campaign_audit",
            "status": "verified", "primary_success": "1/1", "joint_success": "1/1",
        },
    )
    calls = []

    class Control:
        def check(self, stage):
            assert stage == "preparation"

        def effective_timeout(self, *, stage):
            return 1

    def fake_main(args, *, _acceptance_preparation_hook):
        calls.append(args)
        assert args[:5] == ["solve", "Make a valid program", "--evolve", "--multi-file", "--strategy"]
        assert "--max-steps" in args and args[args.index("--max-steps") + 1] == "12"
        _acceptance_preparation_hook(object(), "parent-1", object(), Control())
        if reenter:
            _acceptance_preparation_hook(object(), "parent-1", object(), Control())
        print(json.dumps({"status": "succeeded", "evolution": {"status": "succeeded"}}))
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    result = _run(fixture)
    root = parent / manifest["campaign_root"]
    assert len(calls) == 1
    assert result["status"] == ("failed" if reenter else "completed")
    assert result["request_count"] == 0
    assert json.loads((root / "native-result.json").read_bytes()) == result
    assert json.loads((root / "native-launch.json").read_bytes())["attempt_claim_sha256"] == result["attempt_claim_sha256"]
    budget = json.loads((root / "native-budget.json").read_bytes())
    assert budget["attempt_claim_sha256"] == result["attempt_claim_sha256"]
    assert budget["registration_sha256"] == result["registration_sha256"]
    assert budget["request_count"] == result["request_count"] == 0
    assert result["provider_call_made"] is False
    assert result["budget_receipt_sha256"] == hashlib.sha256(
        json.dumps(budget, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert (root / "attempt-started.json").exists()
    audit_output = root.with_name(f"{root.name}-audit")
    assert verify_native_campaign_audit(campaign_root=root, output_directory=audit_output)["status"] == "verified"
    report_path = audit_output / "report.json"
    original = report_path.read_bytes()
    altered = json.loads(original)
    altered["joint_success"] = "0/1"
    report_path.write_text(json.dumps(altered, sort_keys=True, separators=(",", ":")))
    with pytest.raises(AcceptanceCampaignAuditError, match="^audit_report_binding_mismatch$"):
        verify_native_campaign_audit(campaign_root=root, output_directory=audit_output)
    report_path.write_bytes(original + b" ")
    with pytest.raises(AcceptanceCampaignAuditError, match="^audit_report_binding_mismatch$"):
        verify_native_campaign_audit(campaign_root=root, output_directory=audit_output)
    with pytest.raises(Exception, match="campaign_root_not_fresh"):
        _run(fixture)


def test_native_cli_success_cannot_bypass_failed_independent_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _registered_native(tmp_path)
    monkeypatch.setenv("LUNAR_EVOLUTION_MODEL_ENDPOINT", "https://example.invalid/v1/chat/completions")
    monkeypatch.setenv("LUNAR_EVOLUTION_API_KEY", "fixture-key")
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.prepare_acceptance_runtime_binding",
        lambda *_args, **_kwargs: {"binding_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.publish_acceptance_observation_binding",
        lambda *_args, **_kwargs: {"binding": {"observation_binding_sha256": "b" * 64}},
    )
    monkeypatch.setattr(
        "lunar_evolution.acceptance_native_runner.audit_native_campaign",
        lambda *_args, **_kwargs: {
            "status": "failed", "primary_success": "0/1", "joint_success": "0/1",
            "reason": "audit_inventory_changed",
        },
    )

    def fake_main(_args, *, _acceptance_preparation_hook):
        class Control:
            def check(self, _stage):
                return None

            def effective_timeout(self, *, stage):
                return 1

        _acceptance_preparation_hook(object(), "parent-1", object(), Control())
        print(json.dumps({"status": "succeeded", "evolution": {"status": "succeeded"}}))
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    result = _run(fixture)
    assert result["status"] == "failed"
    assert result["audit_joint_success"] == "0/1"


def test_request_and_token_limits_stop_following_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OpenAICompatibleRuntime("https://example.invalid/v1", "glm-5.2", "fixture-key")
    calls = []

    def complete(*_args, **_kwargs):
        calls.append(1)
        return ModelTurn("ok", usage={"input_tokens": 2, "output_tokens": 3, "total_tokens": 5})

    monkeypatch.setattr(runtime, "_complete", complete)
    budget = AcceptanceRequestBudget(2, 10)
    with own_request_budget(budget):
        runtime.complete([])
        runtime.complete([])
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_request_limit_exhausted$"):
            runtime.complete([])
    assert len(calls) == 2
    assert budget.snapshot() == {"request_count": 2, "observed_tokens": 10, "usage_unknown": False}

    budget = AcceptanceRequestBudget(20, 4)
    with own_request_budget(budget):
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_token_limit_exhausted$"):
            runtime.complete([])
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_token_limit_exhausted$"):
            runtime.complete([])
    assert budget.snapshot()["observed_tokens"] == 5


def test_missing_usage_stops_following_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OpenAICompatibleRuntime("https://example.invalid/v1", "glm-5.2", "fixture-key")
    monkeypatch.setattr(runtime, "_complete", lambda *_args, **_kwargs: ModelTurn("ok"))
    budget = AcceptanceRequestBudget(20, 160000)
    with own_request_budget(budget):
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_token_usage_unknown$"):
            runtime.complete([])
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_token_usage_unknown$"):
            runtime.complete([])
    assert budget.snapshot() == {"request_count": 1, "observed_tokens": 0, "usage_unknown": True}


def test_transport_failure_stops_following_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = OpenAICompatibleRuntime("https://example.invalid/v1", "glm-5.2", "fixture-key")
    calls = []

    def fail(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError("private provider prose")

    monkeypatch.setattr(runtime, "_complete", fail)
    budget = AcceptanceRequestBudget(20, 160000)
    with own_request_budget(budget):
        with pytest.raises(RuntimeError, match="private provider prose"):
            runtime.complete([])
        with pytest.raises(AcceptanceRequestBudgetError, match="^acceptance_token_usage_unknown$"):
            runtime.complete([])
    assert calls == [1]
    assert budget.snapshot()["usage_unknown"] is True
