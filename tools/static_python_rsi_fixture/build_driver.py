"""Mock-only controlled build orchestration for the RSI installation candidate.

The preparation wire is the only input authority.  This driver validates its
independent source/preparation pin, then passes detached candidate plans through
a fixed graph.  It deliberately never invokes a compiler, linker, freezer,
target process, evaluator or runtime.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation

STAGES = ("configure", "freeze", "compile", "link")
PREPARATION_SCHEMA = "lunar-static-python-rsi-installation-profile-preparation-v1"
PREPARATION_SIZE = 73802
PREPARATION_SHA256 = "71b3348ae51b5c5a3e3c092c1d9b25b4d9d04cb63bca22e064509a44ed4d1e9b"
_REAL_OPT_INS = frozenset({"LUNAR_STATIC_EXECUTE", "LUNAR_STATIC_REAL_BUILD"})
_STOCK_FORBIDDEN = frozenset(
    {"Python/frozen.o", "Modules/getpath.o", "Programs/python.o", "Programs/_bootstrap_python.o"}
)
_FREEZER_OBJECTS = frozenset({"Programs/_freeze_module.o", "Modules/getpath_noop.o"})
_TARGET_OBJECTS = frozenset(
    {
        "installation-owned-launcher.o",
        "installation-owned-profile.o",
        "installation-owned-strict-getpath.o",
        "installation-owned-finite-frozen.o",
    }
)
_FREEZE_NAMES = (
    "_frozen_importlib", "_frozen_importlib_external", "abc", "codecs", "io",
    "encodings", "encodings.aliases", "encodings.utf_8", "_lunar_static_main",
)
_FREEZE_GENERATORS = (
    "importlib._bootstrap", "importlib._bootstrap_external", "abc", "codecs", "io",
    "encodings", "encodings.aliases", "encodings.utf_8", "_lunar_static_main",
)
_FALSE_CLAIMS = frozenset(
    {
        "configured_closure_verified", "compilation_performed", "freezer_performed",
        "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
        "runtime_load_protection", "production_admission", "general_code_origin_protection",
    }
)
_STATE_FIELDS = frozenset(
    {
        "source_archive_verified", "toolchain_verified", "configure_performed",
        "compile_performed", "link_performed", "frozen_headers_generated",
        "execution_performed", "runtime_load_protection", "production_admission",
        "general_code_origin_protection",
    }
)
_REVIEWED_PINS = {
    "base_reviewed_inputs": {"size": 80050, "sha256": "c305d56956b75eda286b0e630ceeeaa0f37db2e9f669879eb30a563f8dd2bb31"},
    "reviewed_overlay": {"size": 2456, "sha256": "31e8e064dc5317b3297140f55f07e81ca1aa9c831a4e4bbbf46cc76db0667b8f"},
    "source_plan": {"size": 6706, "sha256": "3399f2f7e8ef9b7c2d6c7ff60985992c0dff1444e463a971ad2560cdbda410ee"},
}


class ControlledBuildError(RuntimeError):
    """Fixed refusal without caller paths or backend exception details."""

    def __init__(self, code: str, *, report: BuildReport | None = None) -> None:
        self.code = "static_python_rsi_build_driver_" + code
        self.report = report
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class BuildReport:
    """Detached mock evidence; acceptance and runtime claims remain false."""

    schema: str
    mode: str
    stages: tuple[str, ...]
    completed_stages: tuple[str, ...]
    stage_evidence: Mapping[str, Mapping[str, Any]]
    partial: bool
    configured_closure_verified: bool = False
    compilation_performed: bool = False
    freezer_performed: bool = False
    link_performed: bool = False
    installation_acceptance: bool = False
    startup_state: str = "not-executed"
    production_admission: bool = False
    simulated_closure: bool = False
    generated_header_count: int = 0


class BuildBackend(Protocol):
    mode: str

    def configure(self, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def freeze(self, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def compile(self, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def link(self, plan: Mapping[str, Any]) -> Mapping[str, Any]: ...


class MockBuildBackend:
    """Trusted in-process test seam. It never claims a real configured closure."""

    mode = "mock"

    def __init__(
        self,
        *,
        simulated_closure: bool = True,
        interrupt_stage: str | None = None,
        partial_stage: str | None = None,
    ) -> None:
        self.simulated_closure = simulated_closure
        self.interrupt_stage = interrupt_stage
        self.partial_stage = partial_stage
        self.calls: list[str] = []

    def _stage(self, name: str) -> dict[str, Any]:
        self.calls.append(name)
        if self.interrupt_stage == name:
            raise ControlledBuildError("interrupted")
        if self.partial_stage == name:
            return {"stage": name, "status": "partial", "evidence": "mock-partial"}
        return {"stage": name, "status": "complete", "evidence": "mock-only"}

    def configure(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        return {**self._stage("configure"), "simulated_closure": self.simulated_closure}

    def freeze(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        result = self._stage("freeze")
        result["headers"] = [
            {"name": item["name"], "generator_id": item["generator_id"],
             "output": item["output"], "state": "mock-generated"}
            for item in plan["freeze_tasks"]
        ]
        return result

    def compile(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._stage("compile")

    def link(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        return self._stage("link")


def _freeze(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) is list:
        return tuple(_freeze(item) for item in value)
    return value


def _report(
    completed: list[str], evidence: dict[str, Mapping[str, Any]], *, partial: bool,
    simulated: bool = False, headers: int = 0,
) -> BuildReport:
    detached = _freeze(json.loads(json.dumps(evidence, sort_keys=True, separators=(",", ":"))))
    return BuildReport(
        schema="lunar-static-python-rsi-build-report-v1", mode="mock", stages=STAGES,
        completed_stages=tuple(completed), stage_evidence=detached,
        partial=partial, simulated_closure=simulated, generated_header_count=headers,
    )


def _refuse(code: str, completed: list[str], evidence: dict[str, Mapping[str, Any]], **kwargs: Any) -> None:
    raise ControlledBuildError(code, report=_report(completed, evidence, **kwargs)) from None


def _attempt(callback: Callable[[], Any], failure_code: str) -> tuple[Any, str | None]:
    """Leave exception handlers before raising a detached fixed refusal."""
    try:
        return callback(), None
    except ControlledBuildError as exc:
        code = "interrupted" if exc.code == "static_python_rsi_build_driver_interrupted" else failure_code
    except KeyboardInterrupt:
        code = "interrupted"
    except Exception:  # noqa: BLE001 - trusted seam details do not enter evidence
        code = failure_code
    return None, code


def _finite_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def _stage_record(value: object, stage: str, plan: dict[str, Any]) -> dict[str, Any] | None:
    """Retain only finite mock fields; never serialize arbitrary backend payloads."""
    fields = {"stage", "status", "evidence"}
    if stage == "configure":
        fields.add("simulated_closure")
    elif stage == "freeze":
        fields.add("headers")
    if type(value) is not dict or set(value) != fields:
        return None
    if any(type(value.get(key)) is not str for key in ("stage", "status", "evidence")):
        return None
    if value["stage"] != stage or value["status"] not in {"complete", "partial"}:
        return None
    expected_label = "mock-only" if value["status"] == "complete" else "mock-partial"
    if value["evidence"] != expected_label:
        return None
    result = {key: value[key] for key in ("stage", "status", "evidence")}
    if stage == "configure":
        if type(value["simulated_closure"]) is not bool:
            return None
        result["simulated_closure"] = value["simulated_closure"]
    elif stage == "freeze":
        headers = value["headers"]
        if type(headers) is not list or len(headers) != 9:
            return None
        checked = []
        for record, task in zip(headers, plan["freeze_tasks"], strict=True):
            if type(record) is not dict or set(record) != {"name", "generator_id", "output", "state"}:
                return None
            if any(type(item) is not str for item in record.values()):
                return None
            if record != {"name": task["name"], "generator_id": task["generator_id"],
                          "output": task["output"], "state": "mock-generated"}:
                return None
            checked.append(record.copy())
        result["headers"] = checked
    return result


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ControlledBuildError("preparation_duplicate_key")
        result[key] = value
    return result


def _preparation_wire(preparation: RSIProfilePreparation) -> dict[str, Any]:
    if type(preparation) is not RSIProfilePreparation:
        raise ControlledBuildError("preparation_type_invalid")
    raw = preparation.wire_bytes
    if type(raw) is not bytes or len(raw) != PREPARATION_SIZE:
        raise ControlledBuildError("preparation_pin_mismatch")
    if hashlib.sha256(raw).hexdigest() != PREPARATION_SHA256:
        raise ControlledBuildError("preparation_pin_mismatch")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except ControlledBuildError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError):
        raise ControlledBuildError("preparation_invalid")
    if type(value) is not dict:
        raise ControlledBuildError("preparation_shape_invalid")
    try:
        canonical = (json.dumps(value, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError):
        raise ControlledBuildError("preparation_invalid") from None
    if canonical != raw:
        raise ControlledBuildError("preparation_noncanonical")
    fields = {
        "schema", "profile", "base_reviewed_inputs", "reviewed_overlay", "source_plan",
        "launch_policy", "initialization_profile", "substitutions", "candidate_build_inputs",
        "pending_frozen_headers", "claims", "artifact_state", "startup_state",
    }
    if set(value) != fields or value["schema"] != PREPARATION_SCHEMA or value["profile"] != "rsi-marker-launch-v1":
        raise ControlledBuildError("preparation_shape_invalid")
    for name, expected in _REVIEWED_PINS.items():
        if value[name] != expected:
            raise ControlledBuildError("source_pin_mismatch")
    claims = value["claims"]
    if type(claims) is not dict or set(claims) != _FALSE_CLAIMS or any(item is not False for item in claims.values()):
        raise ControlledBuildError("claims_invalid")
    if value["artifact_state"] != "pending-builder" or value["startup_state"] != "not-executed":
        raise ControlledBuildError("preparation_state_invalid")
    candidate = value["candidate_build_inputs"]
    if type(candidate) is not dict or candidate.get("schema") != "lunar-static-python-rsi-build-input-candidate-v1":
        raise ControlledBuildError("candidate_shape_invalid")
    _validate_candidate(candidate)
    headers = value["pending_frozen_headers"]
    if type(headers) is not list or len(headers) != 9:
        raise ControlledBuildError("freeze_inventory_invalid")
    expected = tuple((item["name"], item["output"], item["source_sha256"]) for item in candidate["freeze_tasks"])
    actual = []
    for item in headers:
        if type(item) is not dict or set(item) != {"name", "output", "source_sha256", "state"}:
            raise ControlledBuildError("freeze_header_invalid")
        actual.append((item["name"], item["output"], item["source_sha256"]))
        if item["state"] != "pending-freezer":
            raise ControlledBuildError("freeze_header_invalid")
    if tuple(actual) != expected:
        raise ControlledBuildError("freeze_header_invalid")
    return value


def _validate_candidate(candidate: dict[str, Any]) -> None:
    groups = (("shared_units", 162), ("freezer_units", 2), ("target_units", 4))
    objects: set[str] = set()
    grouped: dict[str, set[str]] = {}
    for group, count in groups:
        units = candidate.get(group)
        if type(units) is not list or len(units) != count:
            raise ControlledBuildError("role_inventory_invalid")
        grouped[group] = set()
        for unit in units:
            if type(unit) is not dict or type(unit.get("object")) is not str:
                raise ControlledBuildError("role_record_invalid")
            obj = unit["object"]
            if obj in objects:
                raise ControlledBuildError("role_overlap")
            objects.add(obj)
            grouped[group].add(obj)
            if obj in _STOCK_FORBIDDEN:
                raise ControlledBuildError("stock_input_forbidden")
    if grouped["freezer_units"] != _FREEZER_OBJECTS or grouped["target_units"] != _TARGET_OBJECTS:
        raise ControlledBuildError("role_inventory_invalid")
    excluded = candidate.get("stock_excluded")
    if type(excluded) is not dict or type(excluded.get("both")) is not list:
        raise ControlledBuildError("stock_policy_invalid")
    if set(excluded["both"]) != _STOCK_FORBIDDEN:
        raise ControlledBuildError("stock_policy_incomplete")
    tasks = candidate.get("freeze_tasks")
    if type(tasks) is not list or len(tasks) != 9:
        raise ControlledBuildError("freeze_inventory_invalid")
    if tuple(item.get("name") if type(item) is dict else None for item in tasks) != _FREEZE_NAMES:
        raise ControlledBuildError("freeze_inventory_invalid")
    if tuple(item.get("generator_id") if type(item) is dict else None for item in tasks) != _FREEZE_GENERATORS:
        raise ControlledBuildError("freeze_inventory_invalid")
    for item in tasks:
        if type(item) is not dict:
            raise ControlledBuildError("freeze_task_invalid")
        if item.get("output") != f"generated-sources/Python/frozen_modules/{item.get('generator_id')}.h":
            raise ControlledBuildError("freeze_output_invalid")
        if type(item.get("source_sha256")) is not str or len(item["source_sha256"]) != 64:
            raise ControlledBuildError("freeze_task_invalid")
    states = candidate.get("states")
    if (type(states) is not dict or set(states) != _STATE_FIELDS
            or any(value is not False for value in states.values())):
        raise ControlledBuildError("candidate_claims_invalid")


def run_controlled_build(
    preparation: RSIProfilePreparation,
    *,
    backend: BuildBackend | None = None,
    mode: str = "mock",
    environment: Mapping[str, str] | None = None,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    interrupted: Callable[[], bool] | None = None,
) -> BuildReport:
    """Run the fixed mock graph from one independently pinned preparation wire."""
    if type(mode) is not str or mode != "mock":
        raise ControlledBuildError("real_execution_refused")
    env = dict(os.environ) if environment is None else environment
    if type(env) is not dict:
        raise ControlledBuildError("environment_invalid")
    if any(type(key) is not str or type(value) is not str for key, value in env.items()):
        raise ControlledBuildError("environment_invalid")
    if any(env.get(key) in {"1", "true", "TRUE", "yes"} for key in _REAL_OPT_INS):
        raise ControlledBuildError("real_execution_refused")
    wire = _preparation_wire(preparation)
    if deadline is not None and (not _finite_number(deadline) or deadline <= 0):
        raise ControlledBuildError("deadline_invalid")
    selected = MockBuildBackend() if backend is None else backend
    if not callable(monotonic):
        raise ControlledBuildError("clock_type_invalid")
    if interrupted is not None and not callable(interrupted):
        raise ControlledBuildError("interruption_type_invalid")
    backend_mode, failure = _attempt(lambda: selected.mode, "backend_invalid")
    if failure is not None:
        raise ControlledBuildError(failure)
    if type(backend_mode) is not str or backend_mode != "mock":
        raise ControlledBuildError("backend_not_mock")
    plan = json.loads(json.dumps(wire["candidate_build_inputs"], sort_keys=True, separators=(",", ":")))
    completed: list[str] = []
    evidence: dict[str, Mapping[str, Any]] = {}
    simulated = False
    headers = 0

    def checkpoint() -> None:
        now, failure = _attempt(monotonic, "clock_failure")
        if failure is not None:
            _refuse(failure, completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
        if not _finite_number(now):
            _refuse("clock_invalid", completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
        if deadline is not None and now >= deadline:
            _refuse("deadline_expired", completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
        if interrupted is not None:
            stop, failure = _attempt(interrupted, "interruption_check_failed")
            if failure is not None:
                _refuse(failure, completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
            if type(stop) is not bool:
                _refuse("interruption_type_invalid", completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
            if stop:
                _refuse("interrupted", completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)

    for stage in STAGES:
        checkpoint()
        result, failure = _attempt(
            lambda stage=stage: getattr(selected, stage)(
                json.loads(json.dumps(plan, sort_keys=True, separators=(",", ":")))
            ),
            "backend_failure",
        )
        if failure is not None:
            _refuse(failure, completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
        result = _stage_record(result, stage, plan)
        if result is None:
            _refuse("backend_result_invalid", completed, evidence, partial=bool(completed), simulated=simulated, headers=headers)
        evidence[stage] = result
        if result.get("status") == "partial":
            _refuse("partial_stage", completed, evidence, partial=True, simulated=simulated, headers=headers)
        if stage == "configure":
            simulated = result.get("simulated_closure") is True
            if not simulated:
                _refuse("configured_closure_unverified", completed, evidence, partial=True, simulated=False, headers=headers)
        if stage == "freeze":
            headers = 9
        completed.append(stage)
        checkpoint()
    return _report(completed, evidence, partial=False, simulated=simulated, headers=headers)


__all__ = [
    "PREPARATION_SCHEMA", "PREPARATION_SHA256", "PREPARATION_SIZE", "STAGES",
    "BuildBackend", "BuildReport", "ControlledBuildError", "MockBuildBackend", "run_controlled_build",
]
