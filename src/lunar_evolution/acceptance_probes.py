"""Bounded native snapshot probes for real-acceptance preparation.

This module runs one frozen evaluator probe through the same snapshot harness used by
bundle preparation.  It records the report and the independently expected projection,
plus process and cleanup observations.  It does not call a provider, write a receipt,
or turn an unknown cleanup observation into a success.
"""
from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import evaluator_bundle as _bundle
from .algorithm import AlgorithmProblemContract, EvaluationReport
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_evaluation_spec import canonical_json

_MAX_EXPECTED_KEYS = frozenset({"validity", "quality", "combined_score", "constraint_code"})


@dataclass(frozen=True)
class AcceptanceSnapshotEvidence:
    """Detached, bounded observation of one native snapshot probe."""

    report: dict[str, Any] | None
    projection: dict[str, Any] | None
    expected: dict[str, Any]
    passed: bool
    reason: str
    duration_ms: int
    process_exit_code: int | None
    native_exit_code: int | None
    cleanup: str
    observer_identity: tuple[int, int | None] | None
    release_identity: tuple[int, int | None] | None
    input_bytes: bytes
    expected_output_bytes: bytes
    actual_output_bytes: bytes
    report_sha256: str | None
    projection_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "projection": self.projection,
            "expected": self.expected,
            "passed": self.passed,
            "reason": self.reason,
            "duration_ms": self.duration_ms,
            "process_exit_code": self.process_exit_code,
            "native_exit_code": self.native_exit_code,
            "cleanup": self.cleanup,
            "observer_identity": self.observer_identity,
            "release_identity": self.release_identity,
            "input_sha256": hashlib.sha256(self.input_bytes).hexdigest(),
            "expected_output_sha256": hashlib.sha256(self.expected_output_bytes).hexdigest(),
            "actual_output_sha256": hashlib.sha256(self.actual_output_bytes).hexdigest(),
            "report_sha256": self.report_sha256,
            "projection_sha256": self.projection_sha256,
        }


class AcceptanceProbeError(ValueError):
    """Fixed error for malformed probe expectations or invocation arguments."""


def _projection(report: EvaluationReport) -> dict[str, Any]:
    def number(value: float | None) -> int | float | None:
        # Native reports normalize scores to float; the frozen integer case materials use
        # JSON integers. Canonicalize integral scores by their value, independently of expected.
        return int(value) if isinstance(value, float) and value.is_integer() else value

    return {
        "validity": report.validity,
        "quality": number(report.quality),
        "combined_score": number(report.combined_score),
        "constraint_code": report.error_info[0]["code"] if report.error_info else None,
    }


def _expected(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _MAX_EXPECTED_KEYS:
        raise AcceptanceProbeError("expected_projection_invalid")
    validity = value["validity"]
    if type(validity) is not int or validity not in (0, 1):
        raise AcceptanceProbeError("expected_projection_invalid")
    quality = value["quality"]
    if quality is not None and (isinstance(quality, bool) or not isinstance(quality, (int, float))
                                or not math.isfinite(quality)):
        raise AcceptanceProbeError("expected_projection_invalid")
    score = value["combined_score"]
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        raise AcceptanceProbeError("expected_projection_invalid")
    constraint = value["constraint_code"]
    if constraint is not None and (not isinstance(constraint, str) or not constraint):
        raise AcceptanceProbeError("expected_projection_invalid")
    result = dict(value)
    if validity == 0 and score != 0:
        raise AcceptanceProbeError("expected_projection_invalid")
    return result


def _input_bytes(probe: Any, contract: AlgorithmProblemContract) -> bytes:
    supplied = {item.path: item.content.encode("utf-8") for item in probe.files}
    values = [supplied["data/raw/" + item.path] for item in contract.inputs]
    if len(values) == 1:
        return values[0]
    return canonical_json([
        {"path": item.path, "content": supplied["data/raw/" + item.path].decode("utf-8")}
        for item in contract.inputs
    ])


def run_acceptance_snapshot_probe(
    evaluator: Path,
    probe: Any,
    contract: AlgorithmProblemContract,
    workspace: Path,
    *,
    expected: Mapping[str, Any],
    timeout_seconds: float = 5,
    check_active: Any = None,
) -> AcceptanceSnapshotEvidence:
    """Execute one probe and return a conservative, digest-bearing observation.

    ``native_exit_code`` is the process result returned by the bounded runner and
    ``process_exit_code`` is the independent exit observer callback. A timeout/cancellation
    or missing release callback leaves cleanup ``unknown``.
    """
    expected_value = _expected(expected)
    if not isinstance(evaluator, Path) or not isinstance(workspace, Path):
        raise AcceptanceProbeError("path_invalid")
    if not isinstance(contract, AlgorithmProblemContract):
        raise AcceptanceProbeError("contract_invalid")
    if (isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise AcceptanceProbeError("timeout_invalid")
    if check_active is not None and not callable(check_active):
        raise AcceptanceProbeError("check_active_invalid")
    input_bytes = _input_bytes(probe, contract)
    expected_bytes = canonical_json(expected_value)
    observed: list[tuple[int, int | None]] = []
    released: list[tuple[int, int | None]] = []
    exits: list[int | None] = []
    captured: dict[str, Any] = {}

    def observer(pid: int, pgid: int | None) -> None:
        observed.append((pid, pgid))

    def release(pid: int, pgid: int | None) -> None:
        released.append((pid, pgid))

    def result_observed(status: str, exit_code: int | None, process_reason: str | None) -> None:
        captured.update(status=status, exit=exit_code, reason=process_reason)

    started = time.monotonic()
    report_dict: dict[str, Any] | None = None
    projection: dict[str, Any] | None = None
    reason = "exception"
    try:
        if check_active is not None:
            check_active()
        report = _bundle._snapshot_probe(
            evaluator, probe, contract, workspace, float(timeout_seconds),
            process_observer=observer,
            process_released=release,
            process_exit_observed=lambda code: exits.append(code),
            process_result_observed=result_observed,
        )
        report_dict = report.to_dict()
        projection = _projection(report)
        if projection != expected_value:
            reason = "projection_mismatch"
        elif captured.get("status") != "succeeded" or captured.get("exit") != 0:
            reason = "process_failed"
        elif len(observed) != 1 or len(released) != 1 or observed[0] != released[0]:
            reason = "cleanup_unknown"
        else:
            reason = "passed"
    except SolveExecutionCancelled:
        reason = "cancelled"
    except SolveExecutionBudgetExceeded:
        reason = "timeout"
    except _bundle.EvaluatorBundleError:
        status = captured.get("status")
        reason = ("process_timed_out" if status == "timed_out" else
                  "process_cleanup_failed" if captured.get("reason") == "process_cleanup_failed" else "process_failed")
    except (OSError, KeyError, TypeError, ValueError, RuntimeError):
        reason = "process_failed" if captured else "exception"
    finally:
        if check_active is not None:
            try:
                check_active()
            except SolveExecutionBudgetExceeded:
                reason = "timeout"
            except (SolveExecutionCancelled, RuntimeError):
                reason = "cancelled"
    duration_ms = max(0, min(86_400_000, math.ceil((time.monotonic() - started) * 1000)))
    exit_code = captured.get("exit")
    process_exit = exits[0] if len(exits) == 1 and type(exits[0]) is int else None
    native_exit = exit_code if type(exit_code) is int else None
    cleanup = "verified" if reason == "passed" else ("failed" if reason == "process_cleanup_failed" else "unknown")
    actual_bytes = canonical_json(projection) if projection is not None else b"{}"
    report_bytes = canonical_json(report_dict) if report_dict is not None else None
    return AcceptanceSnapshotEvidence(
        report=report_dict, projection=projection, expected=expected_value,
        passed=reason == "passed", reason=reason, duration_ms=duration_ms,
        process_exit_code=process_exit, native_exit_code=native_exit, cleanup=cleanup,
        observer_identity=observed[0] if len(observed) == 1 else None,
        release_identity=released[0] if len(released) == 1 else None,
        input_bytes=input_bytes, expected_output_bytes=expected_bytes,
        actual_output_bytes=actual_bytes,
        report_sha256=hashlib.sha256(report_bytes).hexdigest() if report_bytes is not None else None,
        projection_sha256=hashlib.sha256(actual_bytes).hexdigest() if projection is not None else None,
    )


__all__ = ["AcceptanceProbeError", "AcceptanceSnapshotEvidence", "run_acceptance_snapshot_probe"]
