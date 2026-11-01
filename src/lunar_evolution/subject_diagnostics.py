"""Bounded, non-authoritative failure claims; never a source of scores or receipts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError

from .agent_loop import AgentInputRequired, ProfileBudgetFailure
from .http_transport import MAX_REQUEST_BYTES, TransportObservation, normalize_transport_observation
from .model_profile import BudgetFailureEvidence, UsageSnapshot
from .runtime import (
    MAX_REQUEST_OBSERVATION_MS,
    MODEL_FAILURE_REASONS,
    ModelFailureEvidence,
    ModelRequestFailure,
    ModelRequestFingerprint,
    ModelRequestObservation,
    RuntimeExecutionError,
)

MAX_DIAGNOSTIC_BYTES = 4096
MAX_COUNTER = 1_000_000
MAX_BUDGET_VALUE = 10**15
_STAGES = {"runtime", "model", "tool", "public_projection", "receipt"}
_CODES = {
    "runtime_failed", "model_failed", "model_http_failed", "tool_failed", "step_limit",
    "timeout", "input_required", "budget_exceeded", "usage_invalid",
    "frozen_request_changed", "public_file_set_changed", "public_file_changed",
    "public_symlink", "public_projection_failed", "receipt_invalid",
}
_FIELDS = {
    "schema_version", "kind", "mode", "request_sha256", "run_index", "round_index",
    "stage", "code", "model_turns", "tool_steps", "http_status",
}
_ADDITIONAL_FIELDS = {
    "1": set(), "2": {"budget"}, "3": {"model_failure"},
    "4": {"model_failure", "request_observation"},
    "5": {"model_failure", "request_observation", "transport_observation"},
}
_BUDGET_FIELDS = {
    "limit", "state", "maximum", "accepted_usage", "observed_usage",
    "trigger_recorded", "usage_completeness",
}
_USAGE_FIELDS = {"input_tokens", "output_tokens", "total_tokens", "cost_micros", "rounds"}


def _integer(value: object, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _normalize_usage(value: object) -> dict[str, int | None]:
    if not isinstance(value, dict) or set(value) != _USAGE_FIELDS:
        raise ValueError("invalid diagnostic usage fields")
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        if not _integer(value[key], 0, MAX_BUDGET_VALUE):
            raise ValueError("invalid diagnostic usage counter")
    if not _integer(value["rounds"], 0, MAX_COUNTER):
        raise ValueError("invalid diagnostic usage rounds")
    if value["cost_micros"] is not None and not _integer(value["cost_micros"], 0, MAX_BUDGET_VALUE):
        raise ValueError("invalid diagnostic usage cost")
    if value["input_tokens"] + value["output_tokens"] != value["total_tokens"]:
        raise ValueError("inconsistent diagnostic usage total")
    if value["rounds"] == 0 and (value["total_tokens"] != 0 or value["cost_micros"] not in (None, 0)):
        raise ValueError("inconsistent empty diagnostic ledger")
    return dict(value)


def _normalize_budget(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != _BUDGET_FIELDS:
        raise ValueError("invalid diagnostic budget fields")
    if type(value["limit"]) is not str or value["limit"] not in {"max_total_tokens", "max_cost_micros"}:
        raise ValueError("invalid diagnostic budget limit")
    if type(value["state"]) is not str or value["state"] not in {"exceeded", "exhausted"}:
        raise ValueError("invalid diagnostic budget state")
    exhausted = value["state"] == "exhausted"
    if type(value["trigger_recorded"]) is not bool or value["trigger_recorded"] != exhausted:
        raise ValueError("inconsistent diagnostic trigger accounting")
    if value["usage_completeness"] != "partial":
        raise ValueError("invalid diagnostic usage completeness")
    maximum = value["maximum"]
    if maximum is not None and not _integer(maximum, 1, MAX_BUDGET_VALUE):
        raise ValueError("invalid diagnostic budget maximum")
    accepted = _normalize_usage(value["accepted_usage"]) if value["accepted_usage"] is not None else None
    observed = _normalize_usage(value["observed_usage"]) if value["observed_usage"] is not None else None
    selected = "total_tokens" if value["limit"] == "max_total_tokens" else "cost_micros"
    for usage in (accepted, observed):
        if usage is not None and usage[selected] is None:
            raise ValueError("missing diagnostic usage for selected budget")
    if observed is not None:
        if observed["rounds"] == 0:
            raise ValueError("diagnostic trigger requires an observed response")
        actual = observed[selected]
        if maximum is not None and (actual != maximum if exhausted else actual <= maximum):
            raise ValueError("inconsistent diagnostic budget trigger")
    if accepted is not None:
        if exhausted and accepted["rounds"] == 0:
            raise ValueError("recorded diagnostic trigger requires an accepted response")
        actual = accepted[selected]
        if maximum is not None and (actual != maximum if exhausted else actual > maximum):
            raise ValueError("inconsistent diagnostic accepted budget")
    if accepted is not None and observed is not None:
        if exhausted:
            if accepted != observed:
                raise ValueError("recorded diagnostic trigger must match accepted ledger")
        else:
            if observed["rounds"] != accepted["rounds"] + 1:
                raise ValueError("inconsistent diagnostic trigger rounds")
            for key in ("input_tokens", "output_tokens", "total_tokens", "cost_micros"):
                before, after = accepted[key], observed[key]
                if (before is None) != (after is None) or (before is not None and after < before):
                    raise ValueError("inconsistent diagnostic cumulative usage")
    return {**value, "accepted_usage": accepted, "observed_usage": observed}


def _project_usage(snapshot: UsageSnapshot) -> dict[str, int | None] | None:
    if type(snapshot) is not UsageSnapshot:
        raise ValueError("invalid typed diagnostic snapshot")
    values = snapshot.to_dict()
    for key, value in values.items():
        if key == "cost_micros" and value is None:
            continue
        if type(value) is not int or value < 0:
            raise ValueError("invalid typed diagnostic number")
    if any(
        value is not None and value > (MAX_COUNTER if key == "rounds" else MAX_BUDGET_VALUE)
        for key, value in values.items()
    ):
        return None
    return _normalize_usage(values)


def _project_budget(evidence: BudgetFailureEvidence) -> dict[str, object]:
    if type(evidence) is not BudgetFailureEvidence:
        raise ValueError("invalid typed diagnostic evidence")
    if type(evidence.maximum) is not int or evidence.maximum < 1:
        raise ValueError("invalid typed diagnostic maximum")
    return _normalize_budget({
        "limit": evidence.limit, "state": evidence.state,
        "maximum": evidence.maximum if evidence.maximum <= MAX_BUDGET_VALUE else None,
        "accepted_usage": _project_usage(evidence.accepted_usage),
        "observed_usage": _project_usage(evidence.observed_usage),
        "trigger_recorded": evidence.trigger_recorded, "usage_completeness": "partial",
    })


def _normalize_model_failure(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"reason", "response_status"}:
        raise ValueError("invalid model failure fields")
    reason, status = value["reason"], value["response_status"]
    if type(reason) is not str or reason not in MODEL_FAILURE_REASONS:
        raise ValueError("invalid model failure reason")
    if status is not None and not _integer(status, 100, 599):
        raise ValueError("invalid model response status")
    if status is not None:
        if reason == "http_error" and 200 <= status <= 299:
            raise ValueError("inconsistent HTTP failure status")
        if reason not in {"http_error", "transport_timeout", "transport_error"} and not 200 <= status <= 299:
            raise ValueError("inconsistent response validation status")
    return dict(value)


def _normalize_request_observation(value: object, reason: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {"phase", "elapsed_ms", "request_timeout_ms"}:
        raise ValueError("invalid model request observation fields")
    if reason in {"transport_timeout", "transport_error"}:
        phases = {"open_response", "read_response_body"}
    elif reason == "http_error":
        phases = {"read_http_error_body", "validate_response"}
    else:
        phases = {"validate_response"}
    if type(value["phase"]) is not str or value["phase"] not in phases:
        raise ValueError("inconsistent model request phase")
    if not _integer(value["elapsed_ms"], 0, MAX_REQUEST_OBSERVATION_MS):
        raise ValueError("invalid model request elapsed time")
    timeout = value["request_timeout_ms"]
    if timeout is not None and not _integer(timeout, 0, MAX_REQUEST_OBSERVATION_MS):
        raise ValueError("invalid model request timeout")
    return dict(value)


def _normalize_request_fingerprint(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != {"body_bytes", "body_sha256"}:
        raise ValueError("invalid model request fingerprint fields")
    if not _integer(value["body_bytes"], 1, MAX_REQUEST_BYTES):
        raise ValueError("invalid model request body size")
    digest = value["body_sha256"]
    if type(digest) is not str or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid model request body digest")
    return dict(value)


def normalize_diagnostic(value: object) -> dict[str, object]:
    """Accept only the fixed score-free vocabulary, without arbitrary error strings."""
    if not isinstance(value, dict) or "schema_version" not in value:
        raise ValueError("invalid diagnostic fields")
    version = value.get("schema_version")
    if type(version) is str and version == "7":
        return _normalize_fingerprinted_diagnostic(value)
    if type(version) is str and version == "6":
        return _normalize_accepted_usage_diagnostic(value)
    if type(version) is not str or version not in {"1", "2", "3", "4", "5"}:
        raise ValueError("invalid diagnostic version")
    additional = _ADDITIONAL_FIELDS[version]
    if set(value) != _FIELDS | additional:
        raise ValueError("invalid diagnostic fields")
    if value["kind"] != "subject_failure":
        raise ValueError("invalid diagnostic kind")
    if value["mode"] not in {"normal", "deep_evolution"}:
        raise ValueError("invalid diagnostic mode")
    digest = value["request_sha256"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid diagnostic digest")
    if not _integer(value["run_index"], 1, 1_000_000):
        raise ValueError("invalid diagnostic run")
    if value["mode"] == "normal":
        if value["round_index"] is not None:
            raise ValueError("normal diagnostic must not have a round")
    elif not _integer(value["round_index"], 1, 1000):
        raise ValueError("invalid diagnostic round")
    if value["stage"] not in _STAGES or value["code"] not in _CODES:
        raise ValueError("invalid diagnostic classification")
    if any(not _integer(value[key], 0, MAX_COUNTER) for key in ("model_turns", "tool_steps")):
        raise ValueError("invalid diagnostic counters")
    if value["http_status"] is not None and not _integer(value["http_status"], 100, 599):
        raise ValueError("invalid diagnostic HTTP status")
    if version == "2":
        if (value["stage"], value["code"], value["http_status"]) != ("runtime", "budget_exceeded", None):
            raise ValueError("invalid diagnostic budget classification")
        return {**value, "budget": _normalize_budget(value["budget"])}
    if version in {"3", "4", "5"}:
        if value["stage"] != "model" or value["code"] not in {"model_failed", "model_http_failed", "timeout"}:
            raise ValueError("invalid model failure classification")
        failure = _normalize_model_failure(value["model_failure"])
        status = value["http_status"]
        if status is not None and (failure["reason"] != "http_error" or status != failure["response_status"]):
            raise ValueError("inconsistent model failure status")
        if value["code"] == "model_http_failed" and status is None:
            raise ValueError("missing model HTTP failure status")
        if version in {"4", "5"}:
            normalized = {**value, "model_failure": failure, "request_observation":
                          _normalize_request_observation(value["request_observation"], failure["reason"])}
            if version == "5":
                normalized["transport_observation"] = normalize_transport_observation(
                    value["transport_observation"],
                )
            return normalized
        return {**value, "model_failure": failure}
    return dict(value)


def _normalize_accepted_usage_diagnostic(value: dict[str, object]) -> dict[str, object]:
    """Validate an accepted-response subtotal without completing a failed request's usage."""
    extra = {"accepted_usage", "usage_completeness"}
    if not extra <= value.keys() or value["usage_completeness"] != "partial":
        raise ValueError("invalid accepted usage diagnostic fields")
    legacy_keys = set(value) - extra
    # A budget failure already has its own accepted/observed accounting. Never mix it here.
    for version in ("1", "3", "4", "5"):
        if legacy_keys == _FIELDS | _ADDITIONAL_FIELDS[version]:
            legacy = normalize_diagnostic({
                **{key: value[key] for key in legacy_keys}, "schema_version": version,
            })
            break
    else:
        raise ValueError("invalid accepted usage diagnostic fields")
    if legacy["stage"] != "model" or legacy["code"] not in {
        "model_failed", "model_http_failed", "timeout",
    }:
        raise ValueError("invalid accepted usage failure classification")
    usage = _normalize_usage(value["accepted_usage"])
    if usage["rounds"] < 1 or usage["rounds"] != legacy["model_turns"]:
        raise ValueError("inconsistent accepted usage response count")
    return {**legacy, "schema_version": "6", "accepted_usage": usage,
            "usage_completeness": "partial"}


def _normalize_fingerprinted_diagnostic(value: dict[str, object]) -> dict[str, object]:
    """Wrap one valid model-failure projection; never promote its authority."""
    if "request_fingerprint" not in value:
        raise ValueError("missing model request fingerprint")
    legacy = {key: item for key, item in value.items() if key != "request_fingerprint"}
    if "accepted_usage" in legacy or "usage_completeness" in legacy:
        legacy = normalize_diagnostic({**legacy, "schema_version": "6"})
    else:
        for version in ("3", "4", "5"):
            if set(legacy) == _FIELDS | _ADDITIONAL_FIELDS[version]:
                legacy = normalize_diagnostic({**legacy, "schema_version": version})
                break
        else:
            raise ValueError("invalid fingerprinted diagnostic fields")
    if legacy["stage"] != "model" or "model_failure" not in legacy:
        raise ValueError("invalid fingerprinted failure classification")
    return {**legacy, "schema_version": "7", "request_fingerprint":
            _normalize_request_fingerprint(value["request_fingerprint"])}


def _with_request_fingerprint(
    payload: dict[str, object], fingerprint: dict[str, object] | None,
) -> dict[str, object]:
    if fingerprint is not None:
        try:
            return normalize_diagnostic({
                **payload, "schema_version": "7", "request_fingerprint": fingerprint,
            })
        except (TypeError, ValueError):
            pass
    return payload


def _relative_parts(relative: str) -> list[str]:
    if not isinstance(relative, str) or len(relative.encode("utf-8")) > 1024:
        raise ValueError("invalid diagnostic path")
    parts = relative.split("/")
    if "\\" in relative or "\x00" in relative or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid diagnostic path")
    return parts


def _parent_fd(root: Path, relative: str, *, create: bool = False) -> tuple[int, str]:
    """Walk from / with directory descriptors, refusing every symlink component."""
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("diagnostic root must be absolute")
    parts = _relative_parts(relative)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(root.anchor, flags)
    try:
        root_parts = list(root.parts[1:])
        for index, part in enumerate(root_parts + parts[:-1]):
            if create and index >= len(root_parts):
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def read_bounded_file(root: Path, relative: str, maximum: int = MAX_DIAGNOSTIC_BYTES) -> bytes:
    parent, name = _parent_fd(root, relative)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
                raise ValueError("diagnostic input must be a bounded regular file")
            content = stream.read(maximum + 1)
            if not content or len(content) > maximum:
                raise ValueError("diagnostic input exceeds its bounded size")
            return content
    finally:
        os.close(parent)


def publish_diagnostic(root: Path, relative: str, diagnostic: object) -> None:
    payload = normalize_diagnostic(diagnostic)
    content = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(content) > MAX_DIAGNOSTIC_BYTES:
        raise ValueError("diagnostic exceeds its bounded size")
    parent, name = _parent_fd(root, relative, create=True)
    temporary = ".subject-diagnostic-" + secrets.token_hex(12)
    created = False
    try:
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=parent,
        )
        created = True
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Linking rather than replacing also rejects every preexisting destination type.
        os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
    finally:
        if created:
            os.unlink(temporary, dir_fd=parent)
        os.close(parent)


@dataclass(frozen=True)
class SubjectDiagnosticContext:
    workspace: Path
    sidecar: str
    mode: str
    request_sha256: str
    run_index: int
    round_index: int | None

    @classmethod
    def from_request(
        cls, workspace: Path, request: Mapping[str, object], request_sha256: str,
    ) -> SubjectDiagnosticContext:
        receipt = request["receipt_path"]
        _relative_parts(receipt)  # type: ignore[arg-type]
        context = cls(
            workspace, Path(receipt).with_suffix(".failure.json").as_posix(),  # type: ignore[arg-type]
            request["mode"], request_sha256, request["run_index"],  # type: ignore[arg-type]
            request.get("round_index"),  # type: ignore[arg-type]
        )
        normalize_diagnostic(context.payload("runtime", "runtime_failed", 0, 0, None))
        return context

    def payload(
        self, stage: str, code: str, model_turns: int, tool_steps: int, http_status: int | None,
    ) -> dict[str, object]:
        return {
            "schema_version": "1", "kind": "subject_failure", "mode": self.mode,
            "request_sha256": self.request_sha256, "run_index": self.run_index,
            "round_index": self.round_index, "stage": stage, "code": code,
            "model_turns": model_turns, "tool_steps": tool_steps, "http_status": http_status,
        }

    def emit(self, diagnostic: object) -> None:
        try:
            publish_diagnostic(self.workspace, self.sidecar, diagnostic)
        except Exception:  # noqa: BLE001 - diagnostics must not mask execution failures
            # Diagnostics must never mask the original subject failure.
            return

    def collect(self) -> None:
        try:
            raw = read_bounded_file(self.workspace, self.sidecar)
            payload = normalize_diagnostic(json.loads(raw))
            for key in ("mode", "request_sha256", "run_index", "round_index"):
                if payload[key] != getattr(self, key):
                    return
            name = "subject-failure.json" if self.round_index is None else f"subject-{self.round_index:03d}-failure.json"
            publish_diagnostic(self.workspace.parent, "diagnostics/" + name, payload)
        except Exception:  # noqa: BLE001 - malformed or unavailable evidence is non-authoritative
            # Subject claims cannot affect runner error, score, or recovery authority.
            return


def capture_subject_diagnostic_context(workspace: Path, request_name: str) -> SubjectDiagnosticContext | None:
    try:
        raw = read_bounded_file(workspace, request_name, 2 * 1024 * 1024)
        context = SubjectDiagnosticContext.from_request(workspace, json.loads(raw), hashlib.sha256(raw).hexdigest())
        # An existing same-round sidecar is old evidence, not a new invocation's diagnostic.
        try:
            parent, name = _parent_fd(workspace, context.sidecar)
        except FileNotFoundError:
            return context
        try:
            os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return context
        finally:
            os.close(parent)
    except Exception:  # noqa: BLE001 - diagnostic setup cannot change process behavior
        return None
    return None


class SubjectDiagnosticObserver:
    """Project only fixed event types and integer counts; discard event bodies."""

    def __init__(self) -> None:
        self.stage = "runtime"
        self.code = "runtime_failed"
        self.model_turns = 0
        self.tool_steps = 0

    def event(self, kind: str, payload: dict[str, object]) -> None:
        if kind == "agent_model_turn" and _integer(payload.get("turn"), 0, MAX_COUNTER):
            self.model_turns = int(payload["turn"])  # type: ignore[arg-type]
        elif kind == "agent_tool_result":
            self.tool_steps = min(MAX_COUNTER, self.tool_steps + 1)
        elif kind == "agent_step_limit_reached":
            self.stage, self.code = "runtime", "step_limit"
        elif kind == "agent_runtime_failure":
            phase = payload.get("phase")
            if phase == "model_turn":
                self.stage, self.code = "model", "model_failed"
            elif phase == "tool":
                self.stage, self.code = "tool", "tool_failed"

    def emit_failure(
        self, context: SubjectDiagnosticContext, error: Exception, *, code: str | None = None,
        accepted_usage: UsageSnapshot | None = None,
    ) -> None:
        try:
            payload = self.failure(context, error, code=code)
            if payload["stage"] == "model" and type(accepted_usage) is UsageSnapshot:
                try:
                    usage = _project_usage(accepted_usage)
                    payload = normalize_diagnostic({
                        **payload, "schema_version": "7" if "request_fingerprint" in payload else "6",
                        "accepted_usage": usage,
                        "usage_completeness": "partial",
                    })
                except (TypeError, ValueError):
                    # Bad optional subtotals cannot suppress the original legacy diagnostic.
                    pass
            context.emit(payload)
        except Exception:  # noqa: BLE001 - classification must not mask the original exception
            return

    def failure(
        self, context: SubjectDiagnosticContext, error: Exception, *, code: str | None = None,
    ) -> dict[str, object]:
        http_status = None
        budget = None
        model_failure = None
        request_observation = None
        transport_observation = None
        request_fingerprint = None
        model_failure_checked = False
        current: BaseException | None = error
        seen: set[int] = set()
        for _ in range(8):
            if current is None or id(current) in seen:
                break
            seen.add(id(current))
            if self.stage == "model" and type(current) is ModelRequestFailure and not model_failure_checked:
                model_failure_checked = True
                try:
                    if type(current.evidence) is ModelFailureEvidence:
                        model_failure = _normalize_model_failure({
                            "reason": current.evidence.reason,
                            "response_status": current.evidence.response_status,
                        })
                except (TypeError, ValueError, AttributeError):
                    # Malformed owned evidence cannot prevent the legacy failure projection.
                    pass
                if model_failure is not None:
                    try:
                        fingerprint = current.request_fingerprint
                        if type(fingerprint) is ModelRequestFingerprint:
                            request_fingerprint = _normalize_request_fingerprint({
                                "body_bytes": fingerprint.body_bytes,
                                "body_sha256": fingerprint.body_sha256,
                            })
                    except (TypeError, ValueError, AttributeError):
                        # Optional identity cannot replace the original failure classification.
                        pass
                    try:
                        observation = current.observation
                        if type(observation) is ModelRequestObservation:
                            request_observation = _normalize_request_observation({
                                "phase": observation.phase, "elapsed_ms": observation.elapsed_ms,
                                "request_timeout_ms": observation.request_timeout_ms,
                            }, model_failure["reason"])
                    except (TypeError, ValueError, AttributeError):
                        # Timing belongs only to this accepted evidence node; retain v3 if invalid.
                        pass
                    if request_observation is not None:
                        try:
                            detail = current.transport_observation
                            if type(detail) is TransportObservation:
                                transport_observation = normalize_transport_observation({
                                    "last_milestone": detail.last_milestone,
                                    "http_exchange_index": detail.http_exchange_index,
                                    "elapsed_ms": detail.elapsed_ms,
                                })
                        except (TypeError, ValueError, AttributeError):
                            # Optional detail cannot replace the accepted coarse failure evidence.
                            pass
            if isinstance(current, HTTPError) and _integer(current.code, 100, 599):
                http_status = current.code
                if self.stage == "model":
                    code = "model_http_failed"
                break
            if isinstance(current, TimeoutError) and self.stage in {"model", "runtime", "tool"}:
                code = "timeout"
            if isinstance(current, AgentInputRequired):
                code = "input_required"
            elif type(current) is ProfileBudgetFailure and self.stage == "runtime":
                code = "budget_exceeded"
                try:
                    budget = _project_budget(current.evidence)
                except (TypeError, ValueError, AttributeError):
                    # Invalid evidence must still leave the original bounded v1 classification.
                    budget = None
            elif type(current) is RuntimeExecutionError and self.stage == "runtime":
                # Match only repository-owned fixed messages, never provider/model prose.
                message = str(current)
                if message == "agent loop timed out before the next model turn":
                    code = "timeout"
                elif message in {
                    "model profile usage is required for token/cost ceilings",
                    "model profile usage is invalid",
                }:
                    code = "usage_invalid"
                elif message in {
                    f"model profile budget {state}: {limit}"
                    for state in ("exceeded", "exhausted")
                    for limit in ("max_total_tokens", "max_cost_micros")
                }:
                    code = "budget_exceeded"
            current = current.__cause__
        payload = context.payload(
            self.stage, code or self.code, self.model_turns, self.tool_steps, http_status,
        )
        if budget is not None and code == "budget_exceeded" and http_status is None:
            return {**payload, "schema_version": "2", "budget": budget}
        if model_failure is not None:
            try:
                if request_observation is not None:
                    timed = normalize_diagnostic({
                        **payload, "schema_version": "4", "model_failure": model_failure,
                        "request_observation": request_observation,
                    })
                    if transport_observation is not None:
                        try:
                            return _with_request_fingerprint(normalize_diagnostic({
                                **timed, "schema_version": "5",
                                "transport_observation": transport_observation,
                            }), request_fingerprint)
                        except (TypeError, ValueError):
                            pass
                    return _with_request_fingerprint(timed, request_fingerprint)
            except (TypeError, ValueError):
                pass
            try:
                return _with_request_fingerprint(normalize_diagnostic({
                    **payload, "schema_version": "3", "model_failure": model_failure,
                }), request_fingerprint)
            except (TypeError, ValueError):
                pass
        return payload
