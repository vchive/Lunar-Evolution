"""Local repeated-pass confidence evidence, explicit uncertainty and fixed provenance."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_noise_confidence import (
    ConfidencePolicy,
    NoiseConfidenceError,
    PassObservation,
    evaluate_transfer_confidence,
    recover_confidence_report,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def observations(samples: int = 64, *, baseline_passes: int = 32, current_passes: int | None = None):
    current_passes = samples if current_passes is None else current_passes
    return {
        arm: tuple(PassObservation(
            digest("task"), repetition=index, seed=100 + index,
            passed=index < (current_passes if arm == "current_memory" else baseline_passes),
            receipt_sha256=digest(f"{arm}:{index}"), score=1.0,
        ) for index in range(samples))
        for arm in ("no_memory", "old_memory", "current_memory")
    }


def evaluate(rows=None, policy=None):
    return evaluate_transfer_confidence(
        observations() if rows is None else rows, policy=policy,
        task_manifest_sha256=digest("manifest"), evaluator_fingerprint=digest("evaluator"),
    )


def test_wilson_values_and_sufficiently_better_candidate_confidence_gate() -> None:
    report = evaluate()
    baseline, _old, current = report.summaries
    assert baseline.lower_bound == pytest.approx(0.381020947439470, abs=1e-12)
    assert baseline.upper_bound == pytest.approx(0.618979052560530, abs=1e-12)
    assert current.lower_bound == pytest.approx(0.9433759402071946, abs=1e-12)
    assert current.upper_bound == pytest.approx(1.0)
    assert report.status == "pass" and report.reasons == ()
    assert report.promotion_evidence()["confidence_passed"] is True
    assert recover_confidence_report(
        report.to_bytes(), expected_receipt_sha256=report.receipt_sha256,
    ).to_bytes() == report.to_bytes()


@pytest.mark.parametrize("samples", [0, 1, 2, 7])
def test_insufficient_samples_are_unresolved_even_if_all_pass(samples: int) -> None:
    report = evaluate(observations(samples, baseline_passes=samples))
    assert report.status == "unresolved" and report.reasons == ("insufficient_samples",)
    with pytest.raises(NoiseConfidenceError, match="not_passed"):
        report.promotion_evidence()
    assert recover_confidence_report(
        report.to_bytes(), expected_receipt_sha256=report.receipt_sha256,
    ).status == "unresolved"


def test_many_single_task_observations_do_not_replace_repeated_tasks() -> None:
    rows = observations(8)
    for arm in rows:
        rows[arm] = tuple(replace(row, task_sha256=digest(f"task:{i}"), repetition=0) for i, row in enumerate(rows[arm]))
    assert evaluate(rows).status == "unresolved"


def test_equal_good_arms_remain_uncertain_until_tolerance_is_explicit() -> None:
    rows = observations(baseline_passes=64)
    strict = evaluate(rows)
    assert strict.status == "unresolved"
    assert "regression_confidence_inconclusive_vs_no_memory" in strict.reasons
    deliberate = evaluate(rows, ConfidencePolicy(max_pass_rate_regression=0.1))
    assert deliberate.status == "pass"
    assert deliberate.receipt_sha256 != strict.receipt_sha256


@pytest.mark.parametrize("current_passes", [0, 16, 32])
def test_perfect_scores_cannot_substitute_for_official_passes(current_passes: int) -> None:
    report = evaluate(observations(current_passes=current_passes))
    assert all(summary.mean_score == 1.0 for summary in report.summaries)
    assert report.status == "fail"
    assert "minimum_pass_rate_not_met" in report.reasons
    with pytest.raises(NoiseConfidenceError, match="not_passed"):
        report.promotion_evidence()


def test_observed_regression_rejects_even_when_minimum_pass_gate_is_met() -> None:
    report = evaluate(observations(baseline_passes=60, current_passes=56))
    assert report.status == "fail"
    assert report.reasons == ("pass_rate_regression_vs_no_memory", "pass_rate_regression_vs_old_memory")


@pytest.mark.parametrize("name", ["confidence_level", "min_pass_rate", "max_pass_rate_regression"])
@pytest.mark.parametrize("value", [True, -0.1, 1.1, float("nan"), float("inf"), "0.9"])
def test_nonfinite_or_unbounded_policy_rejects(name: str, value: object) -> None:
    with pytest.raises(NoiseConfidenceError):
        ConfidencePolicy(**{name: value})


@pytest.mark.parametrize("values", [
    {"min_samples": 1}, {"min_samples": True}, {"max_samples": 4097},
    {"min_samples": 20, "max_samples": 10}, {"confidence_level": 0.49},
    {"confidence_level": 1.0},
])
def test_sample_and_confidence_policy_are_bounded(values) -> None:
    with pytest.raises(NoiseConfidenceError):
        ConfidencePolicy(**values)


@pytest.mark.parametrize("field", ["passed", "seed", "repetition", "score"])
def test_observation_inputs_are_strict(field: str) -> None:
    invalid = {"passed": 1, "seed": True, "repetition": -1, "score": float("nan")}[field]
    with pytest.raises(NoiseConfidenceError):
        replace(observations()["current_memory"][0], **{field: invalid})


@pytest.mark.parametrize("changed", ["duplicate", "same_seed", "same_repetition", "receipt", "seed_drift", "missing"])
def test_duplicate_or_unmatched_coverage_rejects(changed: str) -> None:
    rows = observations()
    current = list(rows["current_memory"])
    if changed == "duplicate":
        current[1] = current[0]
    elif changed == "same_seed":
        current[1] = replace(current[1], seed=current[0].seed)
    elif changed == "same_repetition":
        current[1] = replace(current[1], repetition=current[0].repetition)
    elif changed == "receipt":
        current[1] = replace(current[1], receipt_sha256=current[0].receipt_sha256)
    elif changed == "seed_drift":
        current[1] = replace(current[1], seed=999)
    else:
        current.pop()
    rows["current_memory"] = current
    with pytest.raises(NoiseConfidenceError):
        evaluate(rows)


def test_sample_limit_checked_before_freezing_batch() -> None:
    with pytest.raises(NoiseConfidenceError, match="sample_limit"):
        evaluate(observations(9), ConfidencePolicy(min_samples=8, max_samples=8))


def test_returned_projections_and_caller_lists_do_not_mutate_evidence() -> None:
    rows = {arm: list(arm_rows) for arm, arm_rows in observations().items()}
    report = evaluate(rows)
    before = report.to_bytes()
    rows["current_memory"].clear()
    payload = report.to_dict()
    payload["policy"]["min_pass_rate"] = 0.0
    payload["observations"]["current_memory"].clear()
    assert report.to_bytes() == before


@pytest.mark.parametrize("changed", ["verdict", "summary", "policy", "extra", "format", "duplicate"])
def test_recovery_recomputes_report_even_after_self_digest_rewrite(changed: str) -> None:
    original = evaluate(observations(current_passes=0))
    payload = original.to_dict()
    if changed == "verdict":
        payload.update(status="pass", reasons=[], promotion_eligible=True)
    elif changed == "summary":
        payload["summaries"][2]["pass_rate"] = 1.0
    elif changed == "policy":
        payload["policy"].pop("min_samples")
    elif changed == "extra":
        payload["extra"] = True
    payload.pop("receipt_sha256")
    payload["receipt_sha256"] = hashlib.sha256(canonical_json(payload, maximum=4 * 1024 * 1024)).hexdigest()
    content = canonical_json(payload, maximum=4 * 1024 * 1024)
    if changed == "format":
        content = json.dumps(payload, indent=2).encode()
    elif changed == "duplicate":
        content = b'{"status":"pass",' + content[1:]
    with pytest.raises(NoiseConfidenceError):
        # Supply the rewritten digest too: consistency checks must still reject forged verdicts.
        recover_confidence_report(content, expected_receipt_sha256=payload["receipt_sha256"])


def test_legitimate_policy_change_cannot_replace_the_pinned_report() -> None:
    original = evaluate()
    replacement = evaluate(policy=ConfidencePolicy(min_pass_rate=0.5))
    with pytest.raises(NoiseConfidenceError, match="receipt_drift"):
        recover_confidence_report(replacement.to_bytes(), expected_receipt_sha256=original.receipt_sha256)


@pytest.mark.parametrize("changed", ["manifest", "evaluator", "policy"])
def test_recovery_rechecks_independent_caller_intent_pins(changed: str) -> None:
    report = evaluate()
    pins = {
        "expected_task_manifest_sha256": digest("manifest"),
        "expected_evaluator_fingerprint": digest("evaluator"),
        "expected_policy": report.policy,
    }
    if changed == "manifest":
        pins["expected_task_manifest_sha256"] = digest("new-manifest")
    elif changed == "evaluator":
        pins["expected_evaluator_fingerprint"] = digest("new-evaluator")
    else:
        pins["expected_policy"] = ConfidencePolicy(min_pass_rate=0.5)
    with pytest.raises(NoiseConfidenceError, match="intent_drift"):
        recover_confidence_report(report.to_bytes(), expected_receipt_sha256=report.receipt_sha256, **pins)
