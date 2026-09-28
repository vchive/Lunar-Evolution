"""Bounded supervisor stop observations; interruption never grants completion authority."""

from __future__ import annotations

import hashlib
from typing import Any

from .candidate_evaluation_spec import canonical_json


class CandidateProcessInterrupted(RuntimeError):
    """Carry supervisor evidence to the retaining boundary before re-raising its cause."""

    def __init__(self, cause: Exception, observation: dict[str, Any]) -> None:
        self.cause = cause
        self.observation = observation
        super().__init__("candidate_process_interrupted")


def build_process_interruption_receipt(
    observation: dict[str, Any], *, request_sha256: str, stage: str,
) -> dict[str, Any]:
    fields = {"reason", "stage", "pid", "pgid", "exit_code", "cleanup", "ownership_release", "observed_ms"}
    if type(observation) is not dict or set(observation) != fields:
        raise ValueError("candidate_process_interruption_invalid")
    if type(request_sha256) is not str or len(request_sha256) != 64 or any(c not in "0123456789abcdef" for c in request_sha256):
        raise ValueError("candidate_process_interruption_invalid")
    if stage not in {"candidate_execution", "evaluation"} or observation["stage"] != stage:
        raise ValueError("candidate_process_interruption_invalid")
    if observation["reason"] not in {"cancelled", "timed_out", "control_failed"}:
        raise ValueError("candidate_process_interruption_invalid")
    for name in ("pid", "pgid"):
        if type(observation[name]) is not int or observation[name] <= 1:
            raise ValueError("candidate_process_interruption_invalid")
    exit_code = observation["exit_code"]
    if exit_code is not None and (type(exit_code) is not int or not -(2**31) <= exit_code < 2**31):
        raise ValueError("candidate_process_interruption_invalid")
    if observation["cleanup"] not in {"verified", "failed", "unknown"} or observation["ownership_release"] not in {"observed", "not_observed"}:
        raise ValueError("candidate_process_interruption_invalid")
    if observation["cleanup"] == "verified" and (exit_code is None or observation["ownership_release"] != "observed"):
        raise ValueError("candidate_process_interruption_invalid")
    elapsed = observation["observed_ms"]
    if type(elapsed) is not int or not 0 <= elapsed <= 86_400_000:
        raise ValueError("candidate_process_interruption_invalid")
    body = {"protocol": "lunar-candidate-process-interruption-v1", "request_sha256": request_sha256, **observation}
    body["receipt_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
    return body
