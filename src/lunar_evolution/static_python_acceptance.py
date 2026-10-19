"""Provider-free composition gate for the static Python RSI contracts.

Feature189/193 intentionally stop before a real CPython/toolchain acceptance.  The
individual installation, build, startup, input/result and handoff DTOs are useful
only when their independent digests form one coherent observation.  This module
checks that detached linkage without opening files, launching a process, invoking
a compiler/evaluator, or granting production authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from lunar_evolution.static_python_build_closure import StaticPythonBuildClosure
from lunar_evolution.static_python_input_result import StaticPythonInputResult
from lunar_evolution.static_python_rsi_installation import (
    StaticPythonRSIInstallationDescriptor,
)
from lunar_evolution.static_python_runtime_handoff import StaticPythonRuntimeHandoff
from lunar_evolution.static_python_runtime_startup import StaticPythonRuntimeStartup

ACCEPTANCE_SCHEMA = "lunar-static-python-provider-free-acceptance-v1"
_MAX_WIRE_BYTES = 512 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_INSTALL_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
)
_BUILD_CLAIMS = (
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "link_performed", "artifact_verified", "runtime_execution_performed",
    "installation_accepted", "input_consumption_verified", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
)
_STARTUP_CLAIMS = ("startup_performed", "loader_negative_verified", "owner_verified", "production_admission")
_INPUT_CLAIMS = (
    "input_authority_verified", "runtime_execution_verified", "solver_result_accepted",
    "memory_use_verified", "production_admission",
)
_HANDOFF_CLAIMS = (
    "runtime_startup_verified", "input_result_verified", "terminal_verified",
    "publication_ready", "recovery_verified", "production_admission",
)


class StaticPythonAcceptanceError(ValueError):
    """Fixed refusal reason without retaining caller-controlled evidence."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or not re.fullmatch(r"[a-z_]{1,64}", reason):
            reason = "invalid"
        self.reason = "static_python_acceptance_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _fail(reason: str) -> NoReturn:
    raise _Refusal(reason)


def _sha(value: object, reason: str = "digest") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(reason)
    return value


def _wire_digest(value: object) -> str:
    if type(value) is not bytes or not 0 < len(value) <= _MAX_WIRE_BYTES:
        _fail("wire")
    return hashlib.sha256(value).hexdigest()


def _claims_false(value: object, names: tuple[str, ...]) -> None:
    if type(value) is not dict or set(value) != set(names):
        _fail("claims")
    if any(item is not False for item in value.values()):
        _fail("claims")


def _payload(item: object) -> dict:
    if type(item) not in {
        StaticPythonRSIInstallationDescriptor,
        StaticPythonBuildClosure,
        StaticPythonRuntimeStartup,
        StaticPythonInputResult,
        StaticPythonRuntimeHandoff,
    }:
        _fail("type")
    try:
        raw = item.canonical_bytes
        if type(raw) is not bytes or not 0 < len(raw) <= _MAX_WIRE_BYTES:
            _fail("wire")
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError, OverflowError):
        _fail("wire")
    if type(parsed) is not dict:
        _fail("wire")
    return parsed


def _verify_descriptor(item: StaticPythonRSIInstallationDescriptor) -> dict:
    payload = _payload(item)
    if item.contract_sha256 != _wire_digest(item.canonical_bytes):
        _fail("digest")
    claims = payload.get("claims")
    # F01's descriptor uses the common claim names, while the detached RSI
    # wrapper keeps the same false-only capability boundary.
    _claims_false(claims, _INSTALL_CLAIMS)
    if item.installation_version != payload.get("descriptor", {}).get("installation_version"):
        _fail("version")
    _sha(item.descriptor_sha256)
    _sha(item.artifact_sha256)
    _sha(item.frozen_inventory_sha256)
    _sha(item.main_header_sha256)
    return payload


def _verify_shared_claims(payload: dict, names: tuple[str, ...]) -> None:
    _claims_false(payload.get("claims"), names)


@dataclass(frozen=True, slots=True)
class StaticPythonProviderFreeAcceptance:
    """A coherent local observation summary; never live acceptance authority."""

    canonical_bytes: bytes
    summary_sha256: str
    installation_version: str
    fixture_case: str
    terminal_state: str
    live_acceptance_ready: bool = False
    production_admission: bool = False

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def compose_static_python_provider_free_acceptance(
    *,
    installation: StaticPythonRSIInstallationDescriptor,
    build: StaticPythonBuildClosure,
    startup: StaticPythonRuntimeStartup,
    input_result: StaticPythonInputResult,
    handoff: StaticPythonRuntimeHandoff,
) -> StaticPythonProviderFreeAcceptance:
    """Join already parsed DTOs and return a false-claim local summary.

    The caller must parse each wire with its corresponding independent pins
    first.  This final seam only compares immutable DTOs and their canonical
    bytes; it performs no I/O or process/runtime work.
    """
    try:
        _verify_descriptor(installation)
        build_payload = _payload(build)
        startup_payload = _payload(startup)
        input_payload = _payload(input_result)
        handoff_payload = _payload(handoff)

        if build.contract_sha256 != _wire_digest(build.canonical_bytes):
            _fail("digest")
        if build.installation_version != installation.installation_version:
            _fail("version")
        if startup.installation_version != installation.installation_version:
            _fail("version")
        if build_payload.get("installation_version") != installation.installation_version:
            _fail("version")
        _verify_shared_claims(build_payload, _BUILD_CLAIMS)
        _verify_shared_claims(startup_payload, _STARTUP_CLAIMS)
        _verify_shared_claims(input_payload, _INPUT_CLAIMS)
        _verify_shared_claims(handoff_payload, _HANDOFF_CLAIMS)

        startup_sha = _wire_digest(startup.canonical_bytes)
        input_sha = _wire_digest(input_result.canonical_bytes)
        handoff_sha = _wire_digest(handoff.canonical_bytes)
        if startup.fixture_case != "baseline" or startup.terminal != "exited":
            _fail("fixture_case")
        if input_result.build_closure_sha256 != build.contract_sha256:
            _fail("linkage")
        if input_result.startup_sha256 != startup_sha:
            _fail("linkage")
        if startup_payload.get("build_closure_sha256") != build.contract_sha256:
            _fail("linkage")
        if input_payload.get("startup_sha256") != startup_sha:
            _fail("linkage")
        if handoff_payload.get("startup_sha256") != startup_sha:
            _fail("linkage")
        if handoff_payload.get("input_result_sha256") != input_sha:
            _fail("linkage")
        if handoff.terminal_state != "completed" or handoff.publication_state != "prepared":
            _fail("state")
        if handoff_payload.get("terminal_state") != handoff.terminal_state:
            _fail("state")
        if handoff_payload.get("publication_state") != handoff.publication_state:
            _fail("state")

        summary = {
            "schema": ACCEPTANCE_SCHEMA,
            "installation_version": installation.installation_version,
            "installation_descriptor_sha256": installation.descriptor_sha256,
            "build_closure_sha256": build.contract_sha256,
            "startup_sha256": startup_sha,
            "input_result_sha256": input_sha,
            "handoff_sha256": handoff_sha,
            "fixture_case": startup.fixture_case,
            "terminal_state": handoff.terminal_state,
            "publication_state": handoff.publication_state,
            "live_acceptance_ready": False,
            "production_admission": False,
        }
        raw = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return StaticPythonProviderFreeAcceptance(
            raw, hashlib.sha256(raw).hexdigest(), installation.installation_version,
            startup.fixture_case, handoff.terminal_state,
        )
    except _Refusal as exc:
        raise StaticPythonAcceptanceError(exc.reason) from None
    except (AttributeError, TypeError, ValueError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise StaticPythonAcceptanceError("invalid") from None


__all__ = [
    "ACCEPTANCE_SCHEMA", "StaticPythonAcceptanceError", "StaticPythonProviderFreeAcceptance",
    "compose_static_python_provider_free_acceptance",
]
