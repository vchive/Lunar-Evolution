"""Explicit Wilson pass-rate evidence for comparable local repeated observations."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist
from typing import Any, Literal

from .candidate_evaluation_spec import canonical_json
from .rsi_learning import RSILearningError

ARMS = ("no_memory", "old_memory", "current_memory")
MAX_CONFIDENCE_SAMPLES = 4096
MAX_CONFIDENCE_BYTES = 4 * 1024 * 1024
ConfidenceStatus = Literal["pass", "fail", "unresolved"]


class NoiseConfidenceError(RSILearningError):
    """Fixed-code errors for local statistical evidence."""


def _fail(code: str) -> None:
    raise NoiseConfidenceError("rsi_noise_confidence_" + code)


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        _fail("digest_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=MAX_CONFIDENCE_BYTES)
    except Exception as exc:
        raise NoiseConfidenceError("rsi_noise_confidence_record_invalid") from exc


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _finite_rate(value: object) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1


@dataclass(frozen=True)
class ConfidencePolicy:
    """Declared sample limits and conservative official-pass thresholds."""

    min_samples: int = 8
    max_samples: int = 4096
    confidence_level: float = 0.95
    min_pass_rate: float = 0.75
    max_pass_rate_regression: float = 0.0

    def __post_init__(self) -> None:
        if (
            type(self.min_samples) is not int or type(self.max_samples) is not int
            or not 2 <= self.min_samples <= self.max_samples <= MAX_CONFIDENCE_SAMPLES
        ):
            _fail("sample_policy_invalid")
        if not _finite_rate(self.confidence_level) or not 0.5 <= self.confidence_level <= 0.999999:
            _fail("confidence_level_invalid")
        for name in ("min_pass_rate", "max_pass_rate_regression"):
            if not _finite_rate(getattr(self, name)):
                _fail(name + "_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_samples": self.min_samples, "max_samples": self.max_samples,
            "confidence_level": float(self.confidence_level),
            "min_pass_rate": float(self.min_pass_rate),
            "max_pass_rate_regression": float(self.max_pass_rate_regression),
        }


@dataclass(frozen=True)
class PassObservation:
    """One boolean evaluator result with an explicit task/repetition/seed identity."""

    task_sha256: str
    repetition: int
    seed: int
    passed: bool
    receipt_sha256: str
    score: float | None = None

    def __post_init__(self) -> None:
        _digest(self.task_sha256)
        _digest(self.receipt_sha256)
        if type(self.repetition) is not int or not 0 <= self.repetition < MAX_CONFIDENCE_SAMPLES:
            _fail("repetition_invalid")
        if type(self.seed) is not int or not 0 <= self.seed < 2**32:
            _fail("seed_invalid")
        if type(self.passed) is not bool:
            _fail("passed_invalid")
        if self.score is not None and not _finite_rate(self.score):
            _fail("score_invalid")

    @property
    def key(self) -> tuple[str, int, int]:
        return self.task_sha256, self.repetition, self.seed

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_sha256": self.task_sha256, "repetition": self.repetition, "seed": self.seed,
            "passed": self.passed, "receipt_sha256": self.receipt_sha256,
            "score": None if self.score is None else float(self.score),
        }


@dataclass(frozen=True)
class PassRateSummary:
    arm: str
    samples: int
    passes: int
    pass_rate: float
    lower_bound: float
    upper_bound: float
    score_samples: int
    mean_score: float | None
    score_variance: float | None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _summary(arm: str, rows: tuple[PassObservation, ...], policy: ConfidencePolicy) -> PassRateSummary:
    samples = len(rows)
    passes = sum(row.passed for row in rows)
    rate = passes / samples if samples else 0.0
    if samples:
        z = NormalDist().inv_cdf((1 + policy.confidence_level) / 2)
        z2 = z * z
        denominator = 1 + z2 / samples
        center = (rate + z2 / (2 * samples)) / denominator
        margin = z * math.sqrt(rate * (1 - rate) / samples + z2 / (4 * samples**2)) / denominator
        lower, upper = max(0.0, center - margin), min(1.0, center + margin)
    else:
        lower, upper = 0.0, 1.0
    scores = tuple(float(row.score) for row in rows if row.score is not None)
    mean_score = sum(scores) / len(scores) if scores else None
    variance = sum((score - mean_score) ** 2 for score in scores) / len(scores) if scores else None
    return PassRateSummary(arm, samples, passes, rate, lower, upper, len(scores), mean_score, variance)


@dataclass(frozen=True)
class ConfidenceReport:
    """Recomputable immutable evidence; score statistics never grant a pass."""

    task_manifest_sha256: str
    evaluator_fingerprint: str
    policy: ConfidencePolicy
    observations: tuple[tuple[str, tuple[PassObservation, ...]], ...]

    def __post_init__(self) -> None:
        _digest(self.task_manifest_sha256)
        _digest(self.evaluator_fingerprint)
        if not isinstance(self.policy, ConfidencePolicy):
            _fail("policy_invalid")
        if type(self.observations) is not tuple or len(self.observations) != 3:
            _fail("arms_invalid")
        keys: tuple[tuple[str, int, int], ...] | None = None
        for expected_arm, item in zip(ARMS, self.observations, strict=True):
            if type(item) is not tuple or len(item) != 2 or item[0] != expected_arm:
                _fail("arms_invalid")
            rows = item[1]
            if type(rows) is not tuple or len(rows) > self.policy.max_samples:
                _fail("sample_limit")
            if any(not isinstance(row, PassObservation) for row in rows):
                _fail("observation_invalid")
            arm_keys = tuple(row.key for row in rows)
            if (
                len(set(arm_keys)) != len(rows)
                or len({(row.task_sha256, row.repetition) for row in rows}) != len(rows)
                or len({(row.task_sha256, row.seed) for row in rows}) != len(rows)
                or len({row.receipt_sha256 for row in rows}) != len(rows)
            ):
                _fail("duplicate_observation")
            if keys is not None and arm_keys != keys:
                _fail("coverage_drift")
            keys = arm_keys
        _canonical(self._payload())

    @property
    def summaries(self) -> tuple[PassRateSummary, ...]:
        return tuple(_summary(arm, rows, self.policy) for arm, rows in self.observations)

    def _decision(self, summaries: tuple[PassRateSummary, ...]) -> tuple[ConfidenceStatus, tuple[str, ...]]:
        rows = self.observations[0][1]
        counts: dict[str, int] = {}
        for row in rows:
            counts[row.task_sha256] = counts.get(row.task_sha256, 0) + 1
        if len(rows) < self.policy.min_samples or any(count < 2 for count in counts.values()):
            return "unresolved", ("insufficient_samples",)
        current = summaries[2]
        failures = []
        if current.pass_rate < self.policy.min_pass_rate:
            failures.append("minimum_pass_rate_not_met")
        for baseline in summaries[:2]:
            if current.pass_rate < baseline.pass_rate - self.policy.max_pass_rate_regression:
                failures.append("pass_rate_regression_vs_" + baseline.arm)
        if failures:
            return "fail", tuple(failures)
        unresolved = []
        if current.lower_bound < self.policy.min_pass_rate:
            unresolved.append("minimum_confidence_inconclusive")
        for baseline in summaries[:2]:
            if current.lower_bound - baseline.upper_bound < -self.policy.max_pass_rate_regression:
                unresolved.append("regression_confidence_inconclusive_vs_" + baseline.arm)
        return ("unresolved", tuple(unresolved)) if unresolved else ("pass", ())

    @property
    def status(self) -> ConfidenceStatus:
        return self._decision(self.summaries)[0]

    @property
    def reasons(self) -> tuple[str, ...]:
        return self._decision(self.summaries)[1]

    def _payload(self) -> dict[str, Any]:
        summaries = self.summaries
        status, reasons = self._decision(summaries)
        return {
            "protocol": "lunar-rsi-noise-confidence-v1", "schema_version": "1",
            "method": "wilson-score-marginal-v1",
            "task_manifest_sha256": self.task_manifest_sha256,
            "evaluator_fingerprint": self.evaluator_fingerprint, "policy": self.policy.to_dict(),
            "observations": {arm: [row.to_dict() for row in rows] for arm, rows in self.observations},
            "summaries": [summary.to_dict() for summary in summaries],
            "status": status, "reasons": list(reasons), "promotion_eligible": status == "pass",
        }

    @property
    def receipt_sha256(self) -> str:
        return _hash(self._payload())

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_sha256": self.receipt_sha256}

    def to_bytes(self) -> bytes:
        return _canonical(self.to_dict())

    def promotion_evidence(self) -> dict[str, Any]:
        """Additional opt-in evidence; cannot replace official transfer/verifier gates."""
        if self.status != "pass":
            _fail("not_passed")
        return {
            "confidence_receipt_sha256": self.receipt_sha256,
            "confidence_policy_sha256": _hash(self.policy.to_dict()), "confidence_passed": True,
        }


def evaluate_transfer_confidence(
    observations: Mapping[str, Sequence[PassObservation]], *, task_manifest_sha256: str,
    evaluator_fingerprint: str, policy: ConfidencePolicy | None = None,
) -> ConfidenceReport:
    """Freeze a comparable repeated evaluation batch without calling an evaluator."""
    effective_policy = ConfidencePolicy() if policy is None else policy
    if not isinstance(effective_policy, ConfidencePolicy):
        _fail("policy_invalid")
    if not isinstance(observations, Mapping) or set(observations) != set(ARMS):
        _fail("arms_invalid")
    arms = []
    for arm in ARMS:
        rows = observations[arm]
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            _fail("observation_invalid")
        if len(rows) > effective_policy.max_samples:
            _fail("sample_limit")
        arms.append((arm, tuple(rows)))
    return ConfidenceReport(task_manifest_sha256, evaluator_fingerprint, effective_policy, tuple(arms))


def recover_confidence_report(
    receipt_bytes: bytes, *, expected_receipt_sha256: str,
    expected_task_manifest_sha256: str | None = None,
    expected_evaluator_fingerprint: str | None = None,
    expected_policy: ConfidencePolicy | None = None,
) -> ConfidenceReport:
    """Recompute saved evidence read-only; neither retry evaluation nor reuse a verdict flag."""
    if type(receipt_bytes) is not bytes or len(receipt_bytes) > MAX_CONFIDENCE_BYTES:
        _fail("record_invalid")
    _digest(expected_receipt_sha256)
    for value in (expected_task_manifest_sha256, expected_evaluator_fingerprint):
        if value is not None:
            _digest(value)
    if expected_policy is not None and not isinstance(expected_policy, ConfidencePolicy):
        _fail("policy_invalid")
    try:
        payload = json.loads(receipt_bytes)
        if type(payload) is not dict or _canonical(payload) != receipt_bytes:
            _fail("record_invalid")
        policy = ConfidencePolicy(**payload["policy"])
        if policy.to_dict() != payload["policy"]:
            _fail("record_invalid")
        raw = payload["observations"]
        if type(raw) is not dict or any(type(rows) is not list for rows in raw.values()):
            _fail("record_invalid")
        if any(len(rows) > policy.max_samples for rows in raw.values()):
            _fail("sample_limit")
        expected = evaluate_transfer_confidence(
            {arm: tuple(PassObservation(**row) for row in rows) for arm, rows in raw.items()},
            task_manifest_sha256=payload["task_manifest_sha256"],
            evaluator_fingerprint=payload["evaluator_fingerprint"], policy=policy,
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, NoiseConfidenceError):
            raise
        raise NoiseConfidenceError("rsi_noise_confidence_record_invalid") from exc
    if expected.to_bytes() != receipt_bytes or expected.receipt_sha256 != expected_receipt_sha256:
        _fail("receipt_drift")
    if (
        expected_task_manifest_sha256 is not None
        and expected.task_manifest_sha256 != expected_task_manifest_sha256
    ) or (
        expected_evaluator_fingerprint is not None
        and expected.evaluator_fingerprint != expected_evaluator_fingerprint
    ) or (expected_policy is not None and expected.policy != expected_policy):
        _fail("intent_drift")
    return expected
