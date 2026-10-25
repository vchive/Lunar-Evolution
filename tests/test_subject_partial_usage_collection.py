"""A partial failure subtotal never authorizes scoring or a completed receipt."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from test_deep_effect_trial import (
    _deep_config,
    _make_bound_subject_script,
    _make_case,
    _make_constant_harness_script,
    _write_baseline,
    _write_json,
)
from test_effect_trial import _fixture

from lunar_evolution.deep_effect_trial import DeepEffectTrialRunner
from lunar_evolution.effect_trial import EffectTrialConfig, EffectTrialRunner


@pytest.mark.parametrize("mode", ["normal", "deep_evolution"])
@pytest.mark.parametrize("mutation", ["valid", "identity", "complete", "score", "zero_rounds"])
def test_partial_usage_collection_preserves_failed_attempt_boundary(tmp_path, mode, mutation):
    calls = []
    emitted = []

    def executor(command, *, cwd, env, timeout):
        request_path = Path(command[-1])
        request = json.loads(request_path.read_bytes())
        is_harness = "candidate_workspace" in request
        calls.append("harness" if is_harness else "subject")
        fail = not is_harness and (mode == "normal" or request["round_index"] == 2)
        if not fail:
            return subprocess.run(
                command, cwd=cwd, env=env, timeout=timeout, check=False, capture_output=True,
            )
        payload = {
            "schema_version": "6", "kind": "subject_failure", "mode": mode,
            "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
            "run_index": request["run_index"], "round_index": request.get("round_index"),
            "stage": "model", "code": "timeout", "model_turns": 3,
            "tool_steps": 4, "http_status": None,
            "model_failure": {"reason": "transport_timeout", "response_status": None},
            "request_observation": {
                "phase": "open_response", "elapsed_ms": 1000, "request_timeout_ms": 1000,
            },
            "transport_observation": {
                "last_milestone": "wait_response_headers", "http_exchange_index": 1,
                "elapsed_ms": 999,
            },
            "accepted_usage": {
                "input_tokens": 30, "output_tokens": 6, "total_tokens": 36,
                "cost_micros": None, "rounds": 3,
            },
            "usage_completeness": "partial",
        }
        if mutation == "identity":
            payload["request_sha256"] = "0" * 64
        elif mutation == "complete":
            payload["usage_completeness"] = "complete"
        elif mutation == "score":
            payload["overall_score"] = 1.0
        elif mutation == "zero_rounds":
            payload["accepted_usage"]["rounds"] = 0
        sidecar = (cwd / request["receipt_path"]).with_suffix(".failure.json")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_text(json.dumps(payload))
        emitted.append(payload)
        return subprocess.CompletedProcess(command, 2)

    if mode == "normal":
        suite, baseline, public, subject, harness = _fixture(tmp_path)
        runner = EffectTrialRunner(
            suite, baseline, tmp_path / "trial", case_sources={"fixture_case": public},
            config=EffectTrialConfig(
                runs_per_case=1, timeout_seconds=10, requested_model="gpt-5.6-sol",
                subject_command=subject, harness_command=harness,
            ), process_executor=executor,
        )
    else:
        public, suite_data = _make_case(tmp_path)
        suite = _write_json(tmp_path / "suite.json", suite_data)
        baseline = _write_baseline(tmp_path, suite_data)
        subject = _make_bound_subject_script(tmp_path / "subject.py")
        harness = _make_constant_harness_script(tmp_path / "harness.py")
        runner = DeepEffectTrialRunner(
            suite, baseline, tmp_path / "trial", case_sources={"case-a": public},
            config=_deep_config(subject, harness, outer_rounds=2), process_executor=executor,
        )

    record = runner.run().to_dict()["cases"][0]["runs"][0]
    assert calls == (["subject"] if mode == "normal" else ["subject", "harness", "subject"])
    assert record["error_code"] == "process_nonzero_exit" and record["ready"] is False
    assert record["usage"] is None and record.get("cost_micros") is None
    if mode == "normal":
        assert record["overall_score"] is None and record["validity_score"] is None
    else:
        assert len(record["rounds"]) == 1 and record["rounds"][0]["overall_score"] == 0.5
    attempt = tmp_path / "trial" / record["attempt"]
    name = "subject-failure.json" if mode == "normal" else "subject-002-failure.json"
    diagnostic = attempt / "diagnostics" / name
    assert diagnostic.exists() is (mutation == "valid")
    if mutation == "valid":
        assert json.loads(diagnostic.read_bytes()) == emitted[0]
    receipt = "receipt.json" if mode == "normal" else "receipts/002.json"
    assert not (attempt / "subject" / receipt).exists()
