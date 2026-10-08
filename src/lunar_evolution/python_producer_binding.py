"""Pure binding for a pinned local Python producer.

This module joins the already validated runtime inventory, closed-tree material and
native launch intent/attestation.  It deliberately does not inspect the filesystem,
start a process, consume a budget, or create a journal.  The binding is a durable
snapshot; lifecycle code remains responsible for rechecking the pins immediately
before release and for recording the process terminal.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

from .producer_launcher import (
    PRODUCER_LAUNCH_PROTOCOL,
    ProducerLaunchAttestation,
    ProducerLaunchError,
    ProducerLaunchIntent,
    parse_producer_launch_attestation,
    parse_producer_launch_intent,
    verify_producer_launch_attestation,
)
from .producer_python_runtime import (
    PythonRuntimeFile,
    PythonRuntimeManifest,
    PythonRuntimeTarget,
    parse_python_runtime_manifest,
)
from .producer_python_runtime_tree import (
    PythonRuntimeTreeManifest,
    parse_python_runtime_tree_manifest,
)
from .rsi_budget import RSIRunBudget

PYTHON_PRODUCER_BINDING_PROTOCOL = "lunar-python-producer-binding-v1"
PYTHON_PRODUCER_BINDING_SCHEMA_VERSION = "1"
MAX_PYTHON_PRODUCER_BINDING_BYTES = 2 * 1024 * 1024

_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_CASES = frozenset({"baseline", "loader-negative"})
_BROKER_POLICIES = frozenset({"existing-native-broker-v1"})
_FIELDS = frozenset({
    "schema_version", "protocol", "fixture_case", "runtime_manifest", "runtime_tree",
    "intent", "attestation", "deadline_unix", "request_budget", "output_max_bytes",
    "wall_timeout_seconds", "broker_policy", "binding_sha256",
})


class PythonProducerBindingError(ValueError):
    """Fixed-code refusal without caller paths, credentials, or child output."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_binding_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerBindingError(code)


def _canonical(value: object) -> bytes:
    try:
        result = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerBindingError("json_invalid") from exc
    if len(result) > MAX_PYTHON_PRODUCER_BINDING_BYTES:
        _fail("binding_too_large")
    return result


def _strict_json(value: bytes | str) -> object:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
        if len(raw) > MAX_PYTHON_PRODUCER_BINDING_BYTES:
            _fail("binding_too_large")
        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("duplicate_json_key")
                result[key] = item
            return result

        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=pairs,
            parse_constant=lambda _value: _fail("json_invalid"),
        )
    except PythonProducerBindingError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PythonProducerBindingError("json_invalid") from exc
    return value


def _object(value: object, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail("schema_invalid")
    return value


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value < 1:
        _fail(code)
    return value


def _deadline(value: object) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _fail("deadline_invalid")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        _fail("deadline_invalid")
    return result


def _digest_without(value: Mapping[str, object], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


def _reparse_runtime(manifest: PythonRuntimeManifest) -> PythonRuntimeManifest:
    if type(manifest) is not PythonRuntimeManifest:
        _fail("runtime_manifest_type_invalid")
    try:
        # Reparse the detached canonical bytes so object.__setattr__ tampering is
        # checked by the original validator before this binding becomes durable.
        parsed = parse_python_runtime_manifest(manifest.to_json())
    except Exception as exc:
        if isinstance(exc, PythonProducerBindingError):
            raise
        _fail("runtime_manifest_invalid")
    if parsed != manifest:
        _fail("runtime_manifest_drift")
    _sha(parsed.manifest_sha256, "runtime_manifest_digest_invalid")
    return parsed


def _reparse_tree(tree: PythonRuntimeTreeManifest) -> PythonRuntimeTreeManifest:
    if type(tree) is not PythonRuntimeTreeManifest:
        _fail("runtime_tree_type_invalid")
    try:
        parsed = parse_python_runtime_tree_manifest(tree.to_json())
    except Exception as exc:
        if isinstance(exc, PythonProducerBindingError):
            raise
        _fail("runtime_tree_invalid")
    if parsed != tree:
        _fail("runtime_tree_drift")
    _sha(parsed.tree_sha256, "runtime_tree_digest_invalid")
    return parsed


def _reparse_intent(intent: ProducerLaunchIntent) -> ProducerLaunchIntent:
    if type(intent) is not ProducerLaunchIntent:
        _fail("intent_type_invalid")
    try:
        parsed = parse_producer_launch_intent(intent.to_dict())
    except (ProducerLaunchError, TypeError, ValueError) as exc:
        raise PythonProducerBindingError("intent_invalid") from exc
    if parsed != intent:
        _fail("intent_drift")
    if parsed.schema_version != "1" or parsed.protocol != PRODUCER_LAUNCH_PROTOCOL:
        _fail("intent_protocol_invalid")
    if parsed.intent_sha256 is None:
        _fail("intent_digest_missing")
    _sha(parsed.intent_sha256, "intent_digest_invalid")
    return parsed


def _reparse_attestation(attestation: ProducerLaunchAttestation) -> ProducerLaunchAttestation:
    if type(attestation) is not ProducerLaunchAttestation:
        _fail("attestation_type_invalid")
    try:
        parsed = parse_producer_launch_attestation(attestation.to_dict())
    except (ProducerLaunchError, TypeError, ValueError) as exc:
        raise PythonProducerBindingError("attestation_invalid") from exc
    if parsed != attestation:
        _fail("attestation_drift")
    if parsed.schema_version != "1" or parsed.protocol != PRODUCER_LAUNCH_PROTOCOL:
        _fail("attestation_protocol_invalid")
    if parsed.attestation_sha256 is None:
        _fail("attestation_digest_missing")
    _sha(parsed.attestation_sha256, "attestation_digest_invalid")
    for name in (
        "executable_size", "executable_device", "executable_inode",
        "executable_mtime_ns", "executable_ctime_ns",
    ):
        value = getattr(parsed, name)
        if type(value) is not int or value < 0:
            _fail("attestation_stat_invalid")
    return parsed


def _interpreter(manifest: PythonRuntimeManifest) -> PythonRuntimeFile:
    matches = tuple(file for file in manifest.files if file.role == "interpreter")
    if len(matches) != 1:
        _fail("interpreter_invalid")
    return matches[0]


def _budget_deadline(budget: RSIRunBudget | Mapping[str, object]) -> float:
    if type(budget) is RSIRunBudget:
        try:
            state = budget.to_dict()
        except Exception as exc:
            raise PythonProducerBindingError("budget_invalid") from exc
        planned = state.get("planned")
    elif type(budget) is dict:
        try:
            if set(budget) == {"planned", "consumed", "remaining"}:
                # A complete mapping is accepted only after the same durable
                # checkpoint validator used by the controller has checked every
                # counter and remaining value.
                planned = RSIRunBudget.load(budget).to_dict()["planned"]
            elif "planned" in budget:
                _fail("budget_checkpoint_invalid")
            else:
                # Detached planned snapshots still use the canonical RSI
                # constructor, which rejects unknown fields and bad limits.
                planned = RSIRunBudget.create(budget).to_dict()["planned"]
        except PythonProducerBindingError:
            raise
        except Exception as exc:
            raise PythonProducerBindingError("budget_invalid") from exc
    else:
        _fail("budget_type_invalid")
    if type(planned) is not dict or "deadline_unix" not in planned:
        _fail("budget_deadline_missing")
    return _deadline(planned["deadline_unix"])


def _validate_parts(
    runtime_manifest: PythonRuntimeManifest,
    runtime_tree: PythonRuntimeTreeManifest,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    *,
    fixture_case: str,
    deadline_unix: float,
    request_budget: int,
    output_max_bytes: int,
    wall_timeout_seconds: int,
    broker_policy: str,
) -> None:
    manifest = _reparse_runtime(runtime_manifest)
    tree = _reparse_tree(runtime_tree)
    parsed_intent = _reparse_intent(intent)
    parsed_attestation = _reparse_attestation(attestation)
    if tree.declared_manifest != manifest:
        _fail("runtime_tree_manifest_mismatch")
    if tree.declared_manifest.target != manifest.target:
        _fail("runtime_target_mismatch")
    try:
        verify_producer_launch_attestation(parsed_intent, parsed_attestation)
    except ProducerLaunchError as exc:
        raise PythonProducerBindingError("attestation_intent_mismatch") from exc
    if type(fixture_case) is not str or fixture_case not in _FIXTURE_CASES:
        _fail("fixture_case_invalid")
    if type(broker_policy) is not str or broker_policy not in _BROKER_POLICIES:
        _fail("broker_policy_invalid")
    deadline = _deadline(deadline_unix)
    _positive_int(request_budget, "request_budget_invalid")
    _positive_int(output_max_bytes, "output_budget_invalid")
    _positive_int(wall_timeout_seconds, "wall_timeout_invalid")
    if request_budget != parsed_intent.max_requests:
        _fail("request_budget_mismatch")
    if output_max_bytes != parsed_intent.output_max_bytes:
        _fail("output_budget_mismatch")
    if wall_timeout_seconds != parsed_intent.wall_timeout_seconds:
        _fail("wall_timeout_mismatch")
    if deadline < float(wall_timeout_seconds):
        _fail("deadline_wall_timeout_invalid")
    interpreter = _interpreter(manifest)
    if (
        # The native launch intent labels its own producer root (currently the
        # fixed ``producer-root`` label); the runtime inventory may use a
        # different logical root label.  The portable relative path and all
        # observed executable identity pins are the binding authority.
        parsed_intent.executable_relative != interpreter.relative_path
        or parsed_intent.executable_sha256 != interpreter.sha256
        or parsed_intent.executable_size != interpreter.size
        or parsed_intent.executable_device != interpreter.device
        or parsed_intent.executable_inode != interpreter.inode
        or parsed_intent.executable_mtime_ns != interpreter.mtime_ns
        or parsed_intent.executable_ctime_ns != interpreter.ctime_ns
    ):
        _fail("interpreter_identity_mismatch")
    if parsed_attestation.intent_sha256 != parsed_intent.intent_sha256:
        _fail("attestation_intent_mismatch")


@dataclass(frozen=True, slots=True)
class PythonProducerBinding:
    """Immutable, canonical join of pinned producer inputs.

    The full RSI budget remains in the controller ledger.  This DTO carries only
    the original absolute deadline and the launch limits which must match the
    existing intent, so a resume cannot refresh or replace budget state.
    """

    runtime_manifest: PythonRuntimeManifest
    runtime_tree: PythonRuntimeTreeManifest
    intent: ProducerLaunchIntent
    attestation: ProducerLaunchAttestation
    fixture_case: str
    deadline_unix: float
    request_budget: int
    output_max_bytes: int
    wall_timeout_seconds: int
    broker_policy: str = "existing-native-broker-v1"
    binding_sha256: str | None = None
    schema_version: str = PYTHON_PRODUCER_BINDING_SCHEMA_VERSION
    protocol: str = PYTHON_PRODUCER_BINDING_PROTOCOL

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != PYTHON_PRODUCER_BINDING_SCHEMA_VERSION:
            _fail("schema_invalid")
        if type(self.protocol) is not str or self.protocol != PYTHON_PRODUCER_BINDING_PROTOCOL:
            _fail("protocol_invalid")
        _deadline(self.deadline_unix)
        _validate_parts(
            self.runtime_manifest, self.runtime_tree, self.intent, self.attestation,
            fixture_case=self.fixture_case, deadline_unix=self.deadline_unix,
            request_budget=self.request_budget, output_max_bytes=self.output_max_bytes,
            wall_timeout_seconds=self.wall_timeout_seconds, broker_policy=self.broker_policy,
        )
        if self.binding_sha256 is not None:
            _sha(self.binding_sha256, "binding_digest_invalid")
            if self.binding_sha256 != self._digest_unchecked():
                _fail("binding_digest_mismatch")

    def _to_dict_unchecked(self, *, include_digest: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "fixture_case": self.fixture_case,
            "runtime_manifest": self.runtime_manifest.to_dict(),
            "runtime_tree": self.runtime_tree.to_dict(),
            "intent": self.intent.to_dict(),
            "attestation": self.attestation.to_dict(),
            "deadline_unix": self.deadline_unix,
            "request_budget": self.request_budget,
            "output_max_bytes": self.output_max_bytes,
            "wall_timeout_seconds": self.wall_timeout_seconds,
            "broker_policy": self.broker_policy,
        }
        if include_digest:
            result["binding_sha256"] = self.binding_sha256
        return result

    def _digest_unchecked(self) -> str:
        return hashlib.sha256(_canonical(self._to_dict_unchecked(include_digest=False))).hexdigest()

    def digest(self) -> str:
        self.__post_init__()
        return self._digest_unchecked()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        return self._to_dict_unchecked()

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    # These projections make the binding convenient to lifecycle code without
    # introducing duplicate wire fields or a second source of truth.
    @property
    def runtime_manifest_sha256(self) -> str:
        return self.runtime_manifest.manifest_sha256

    @property
    def runtime_tree_sha256(self) -> str:
        return self.runtime_tree.tree_sha256

    @property
    def target(self) -> PythonRuntimeTarget:
        return self.runtime_manifest.target

    @property
    def interpreter(self) -> PythonRuntimeFile:
        return _interpreter(self.runtime_manifest)

    @property
    def interpreter_relative_path(self) -> str:
        return self.interpreter.relative_path

    @property
    def interpreter_sha256(self) -> str:
        return self.interpreter.sha256

    @property
    def run_id(self) -> str:
        return self.intent.run_id

    @property
    def parent_task_id(self) -> str:
        return self.intent.parent_task_id

    @property
    def task_id(self) -> str:
        return self.intent.task_id

    @property
    def producer_id(self) -> str:
        return self.intent.producer_id

    @property
    def producer_fingerprint(self) -> str:
        return self.intent.producer_fingerprint

    @property
    def evaluator_kind(self) -> str:
        return self.intent.evaluator_kind

    @property
    def evaluator_fingerprint(self) -> str:
        return self.intent.evaluator_fingerprint

    @property
    def contract_sha256(self) -> str:
        return self.intent.contract_sha256

    @property
    def dependency_sha256(self) -> str:
        return self.intent.dependency_sha256

    @property
    def environment_sha256(self) -> str:
        return self.intent.environment_sha256

    @property
    def intent_sha256(self) -> str:
        # __post_init__ requires a completed intent digest before this DTO is
        # accepted, so this projection is always a string for a valid binding.
        return self.intent.intent_sha256  # type: ignore[return-value]

    @property
    def attestation_sha256(self) -> str:
        return self.attestation.attestation_sha256  # type: ignore[return-value]

    @property
    def argv(self) -> tuple[str, ...]:
        return self.intent.argv

    @property
    def working_directory(self) -> str:
        return self.intent.working_directory

    @property
    def output_directory(self) -> str:
        return self.intent.output_directory

    @property
    def envelope_path(self) -> str:
        return self.intent.envelope_path


def build_python_producer_binding(
    *,
    runtime_manifest: PythonRuntimeManifest,
    runtime_tree: PythonRuntimeTreeManifest,
    intent: ProducerLaunchIntent,
    attestation: ProducerLaunchAttestation,
    deadline_unix: float,
    budget: RSIRunBudget | Mapping[str, object],
    fixture_case: str = "baseline",
    broker_policy: str = "existing-native-broker-v1",
) -> PythonProducerBinding:
    """Build a binding from already prepared DTOs without I/O or side effects."""
    requested_deadline = _deadline(deadline_unix)
    budget_deadline = _budget_deadline(budget)
    if requested_deadline != budget_deadline:
        _fail("budget_deadline_mismatch")
    if type(intent) is not ProducerLaunchIntent:
        _fail("intent_type_invalid")
    binding = PythonProducerBinding(
        runtime_manifest=runtime_manifest, runtime_tree=runtime_tree, intent=intent,
        attestation=attestation, fixture_case=fixture_case, deadline_unix=requested_deadline,
        request_budget=intent.max_requests, output_max_bytes=intent.output_max_bytes,
        wall_timeout_seconds=intent.wall_timeout_seconds, broker_policy=broker_policy,
    )
    return PythonProducerBinding(**{
        **binding.to_dict(),
        "runtime_manifest": runtime_manifest,
        "runtime_tree": runtime_tree,
        "intent": intent,
        "attestation": attestation,
        "binding_sha256": binding.digest(),
    })


def parse_python_producer_binding(value: bytes | str) -> PythonProducerBinding:
    """Parse a canonical detached binding without filesystem, process, or budget effects."""
    payload = _strict_json(value)
    raw = _object(payload, _FIELDS)
    try:
        runtime_manifest = parse_python_runtime_manifest(_canonical(raw["runtime_manifest"]))
        runtime_tree = parse_python_runtime_tree_manifest(_canonical(raw["runtime_tree"]))
        intent = parse_producer_launch_intent(_canonical(raw["intent"]))
        attestation = parse_producer_launch_attestation(_canonical(raw["attestation"]))
        if raw["schema_version"] != PYTHON_PRODUCER_BINDING_SCHEMA_VERSION:
            _fail("schema_invalid")
        if raw["protocol"] != PYTHON_PRODUCER_BINDING_PROTOCOL:
            _fail("protocol_invalid")
        if type(raw["fixture_case"]) is not str or raw["fixture_case"] not in _FIXTURE_CASES:
            _fail("fixture_case_invalid")
        if type(raw["broker_policy"]) is not str or raw["broker_policy"] not in _BROKER_POLICIES:
            _fail("broker_policy_invalid")
        _sha(raw["binding_sha256"], "binding_digest_invalid")
        result = PythonProducerBinding(
            runtime_manifest=runtime_manifest, runtime_tree=runtime_tree, intent=intent,
            attestation=attestation, fixture_case=raw["fixture_case"],
            deadline_unix=_deadline(raw["deadline_unix"]),
            request_budget=_positive_int(raw["request_budget"], "request_budget_invalid"),
            output_max_bytes=_positive_int(raw["output_max_bytes"], "output_budget_invalid"),
            wall_timeout_seconds=_positive_int(raw["wall_timeout_seconds"], "wall_timeout_invalid"),
            broker_policy=raw["broker_policy"], binding_sha256=raw["binding_sha256"],
            schema_version=raw["schema_version"], protocol=raw["protocol"],
        )
        canonical = _canonical(result.to_dict())
        if (canonical != value if type(value) is bytes else canonical.decode("utf-8") != value):
            _fail("noncanonical_json")
        return result
    except PythonProducerBindingError:
        raise
    except (ProducerLaunchError, TypeError, ValueError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerBindingError("schema_invalid") from exc


__all__ = [
    "MAX_PYTHON_PRODUCER_BINDING_BYTES", "PYTHON_PRODUCER_BINDING_PROTOCOL",
    "PYTHON_PRODUCER_BINDING_SCHEMA_VERSION", "PythonProducerBinding",
    "PythonProducerBindingError", "build_python_producer_binding",
    "parse_python_producer_binding",
]
