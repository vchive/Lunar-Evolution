"""Common, provider-free Python producer result adapter.

OpenEvolve and Shinka use different producer stores, but both can export the
small :class:`ProducerResultEnvelope`. This module binds that envelope to
Feature191's detached Python evidence for inspection and export. It performs
no I/O, process observation, evaluation or admission. The existing complete
admission gate and independently observed runtime remain separate prerequisites.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, NoReturn

from .producer_handoff import (
    ProducerHandoffError,
    ProducerMaterial,
    ProducerResultEnvelope,
)
from .python_producer_binding import (
    PythonProducerBinding,
    PythonProducerBindingError,
    parse_python_producer_binding,
)
from .python_producer_lifecycle import (
    PythonProducerLifecycleError,
    PythonProducerRuntimeObservation,
    PythonProducerTerminal,
    parse_python_producer_runtime_observation,
    parse_python_producer_terminal,
)

PYTHON_PRODUCER_ADAPTER_SCHEMA_VERSION = "1"
PYTHON_PRODUCER_ADAPTER_PROTOCOL = "lunar-python-producer-adapter-v1"
SUPPORTED_PYTHON_PRODUCERS = frozenset({"openevolve", "shinka"})
MAX_PYTHON_PRODUCER_ADAPTER_BYTES = 4 * 1024 * 1024

_SHA = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset({
    "schema_version", "protocol", "producer_id", "binding_sha256", "intent_sha256",
    "attestation_sha256", "runtime_manifest_sha256", "runtime_tree_sha256", "terminal",
    "observation", "result", "production_admission", "adapter_sha256",
})


class PythonProducerAdapterError(ValueError):
    """Fixed-code refusal without producer-controlled paths or process output."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_adapter_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerAdapterError(code)


def _json_shape(value: object, *, depth: int = 0, count: list[int] | None = None) -> None:
    count = [0] if count is None else count
    count[0] += 1
    if depth > 16 or count[0] > 100_000:
        _fail("record_too_large")
    if type(value) in {str, int, float, bool, type(None)}:
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                _fail("json_invalid")
            _json_shape(item, depth=depth + 1, count=count)
    elif type(value) is list:
        for item in value:
            _json_shape(item, depth=depth + 1, count=count)
    else:
        _fail("json_invalid")


def _canonical(value: object) -> bytes:
    _json_shape(value)
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerAdapterError("json_invalid") from exc
    if len(raw) > MAX_PYTHON_PRODUCER_ADAPTER_BYTES:
        _fail("record_too_large")
    return raw


def _sha(value: object, code: str = "digest_invalid") -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None or value == "0" * 64:
        _fail(code)
    return value


def _strict_json(value: bytes | str) -> dict[str, Any]:
    if type(value) not in {bytes, str}:
        _fail("json_invalid")
    try:
        raw = value if type(value) is bytes else value.encode("utf-8")
        if len(raw) > MAX_PYTHON_PRODUCER_ADAPTER_BYTES:
            _fail("record_too_large")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, item in items:
                if key in result:
                    _fail("duplicate_json_key")
                result[key] = item
            return result

        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=lambda _: _fail("json_invalid"))
    except PythonProducerAdapterError:
        raise
    except (UnicodeDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise PythonProducerAdapterError("json_invalid") from exc
    if type(parsed) is not dict or set(parsed) != _FIELDS:
        _fail("schema_invalid")
    if _canonical(parsed) != raw:
        _fail("noncanonical_json")
    return parsed


def _parse_parts(
    value: PythonProducerAdapterEnvelope | bytes | str | Mapping[str, object],
) -> PythonProducerAdapterEnvelope:
    if type(value) is PythonProducerAdapterEnvelope:
        _sha(value.adapter_sha256, "adapter_digest_invalid")
        raw = _strict_json(value.to_json())
    elif type(value) is dict:
        raw = value
        if set(raw) != _FIELDS:
            _fail("schema_invalid")
        _canonical(raw)
    else:
        raw = _strict_json(value)  # type: ignore[arg-type]
    try:
        _sha(raw["adapter_sha256"], "adapter_digest_invalid")
        terminal = parse_python_producer_terminal(raw["terminal"])  # type: ignore[arg-type]
        observation = parse_python_producer_runtime_observation(raw["observation"])  # type: ignore[arg-type]
        result = ProducerResultEnvelope.from_dict(raw["result"])
        return PythonProducerAdapterEnvelope(
            schema_version=raw["schema_version"], protocol=raw["protocol"], producer_id=raw["producer_id"],
            binding_sha256=raw["binding_sha256"], intent_sha256=raw["intent_sha256"],
            attestation_sha256=raw["attestation_sha256"], runtime_manifest_sha256=raw["runtime_manifest_sha256"],
            runtime_tree_sha256=raw["runtime_tree_sha256"], terminal=terminal, observation=observation,
            result=result, production_admission=raw["production_admission"],
            adapter_sha256=raw["adapter_sha256"],
        )
    except PythonProducerAdapterError:
        raise
    except (KeyError, TypeError, ValueError, ProducerHandoffError) as exc:
        raise PythonProducerAdapterError("nested_invalid") from exc


def _result_wire(result: ProducerResultEnvelope) -> dict[str, object]:
    if (type(result) is not ProducerResultEnvelope or type(result.budget) is not dict
            or type(result.materials) is not tuple or type(result.external_evidence) is not dict):
        _fail("result_invalid")
    for item in result.materials:
        if (type(item) is not ProducerMaterial or type(item.lineage) is not tuple
                or type(item.external_evidence) is not dict):
            _fail("result_invalid")
    raw = result.to_dict()
    wire = _canonical(raw)
    try:
        parsed = ProducerResultEnvelope.from_dict(raw)
    except (ProducerHandoffError, TypeError, ValueError) as exc:
        raise PythonProducerAdapterError("result_invalid") from exc
    if _canonical(parsed.to_dict()) != wire:
        _fail("result_invalid")
    return raw


@dataclass(frozen=True, slots=True)
class PythonProducerAdapterEnvelope:
    """One result envelope shared by local OpenEvolve and Shinka adapters."""

    schema_version: str
    protocol: str
    producer_id: str
    binding_sha256: str
    intent_sha256: str
    attestation_sha256: str
    runtime_manifest_sha256: str
    runtime_tree_sha256: str
    terminal: PythonProducerTerminal
    observation: PythonProducerRuntimeObservation
    result: ProducerResultEnvelope
    production_admission: bool = False
    adapter_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != PYTHON_PRODUCER_ADAPTER_SCHEMA_VERSION:
            _fail("schema_invalid")
        if type(self.protocol) is not str or self.protocol != PYTHON_PRODUCER_ADAPTER_PROTOCOL:
            _fail("protocol_invalid")
        if type(self.producer_id) is not str or self.producer_id not in SUPPORTED_PYTHON_PRODUCERS:
            _fail("producer_unsupported")
        for value in (
            self.binding_sha256, self.intent_sha256, self.attestation_sha256,
            self.runtime_manifest_sha256, self.runtime_tree_sha256,
        ):
            _sha(value)
        if type(self.terminal) is not PythonProducerTerminal or type(self.observation) is not PythonProducerRuntimeObservation:
            _fail("nested_invalid")
        if self.production_admission is not False:
            _fail("unsupported_admission_claim")
        try:
            parse_python_producer_terminal(self.terminal.to_json())
            parse_python_producer_runtime_observation(self.observation.to_json())
        except (PythonProducerLifecycleError, TypeError, ValueError) as exc:
            raise PythonProducerAdapterError("nested_invalid") from exc
        _result_wire(self.result)
        if self.result.producer_id != self.producer_id:
            _fail("producer_identity_drift")
        if self.result.status != "completed":
            _fail("result_not_completed")
        if self.terminal.status != "completed":
            _fail("terminal_not_completed")
        if self.observation.execution_performed is not True:
            _fail("runtime_not_observed")
        if self.result.producer_run_id != self.terminal.run_id:
            _fail("result_run_drift")
        requests = self.result.budget.get("requests")
        if type(requests) is not int or requests != self.terminal.request_count:
            _fail("result_request_count_drift")
        if self.terminal.binding_sha256 != self.binding_sha256 or self.observation.binding_sha256 != self.binding_sha256:
            _fail("binding_drift")
        if self.adapter_sha256 is not None:
            _sha(self.adapter_sha256)
            if self.adapter_sha256 != self._digest_unchecked():
                _fail("adapter_digest_mismatch")

    def _to_dict_unchecked(self, *, include_digest: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version, "protocol": self.protocol,
            "producer_id": self.producer_id, "binding_sha256": self.binding_sha256,
            "intent_sha256": self.intent_sha256, "attestation_sha256": self.attestation_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "runtime_tree_sha256": self.runtime_tree_sha256,
            "terminal": self.terminal.to_dict(), "observation": self.observation.to_dict(),
            "result": _result_wire(self.result), "production_admission": self.production_admission,
        }
        if include_digest:
            value["adapter_sha256"] = self.adapter_sha256
        return value

    def _digest_unchecked(self) -> str:
        return hashlib.sha256(_canonical(self._to_dict_unchecked(include_digest=False))).hexdigest()

    def digest(self) -> str:
        self.__post_init__()
        return self._digest_unchecked()

    def to_dict(self) -> dict[str, object]:
        self.__post_init__()
        value = self._to_dict_unchecked()
        if value["adapter_sha256"] is None:
            value["adapter_sha256"] = self.digest()
        return value

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())


def build_python_producer_adapter_envelope(
    binding: PythonProducerBinding,
    terminal: PythonProducerTerminal,
    observation: PythonProducerRuntimeObservation,
    result: ProducerResultEnvelope,
) -> PythonProducerAdapterEnvelope:
    """Bind existing immutable evidence; no filesystem or process effects occur."""
    if type(binding) is not PythonProducerBinding:
        _fail("binding_invalid")
    try:
        binding = parse_python_producer_binding(binding.to_json())
    except (PythonProducerBindingError, TypeError, ValueError) as exc:
        raise PythonProducerAdapterError("binding_invalid") from exc
    if type(result) is not ProducerResultEnvelope:
        _fail("result_invalid")
    result = ProducerResultEnvelope.from_dict(_result_wire(result))
    if result.producer_id != binding.producer_id or result.producer_id not in SUPPORTED_PYTHON_PRODUCERS:
        _fail("producer_identity_drift")
    if result.producer_fingerprint != binding.producer_fingerprint:
        _fail("producer_fingerprint_drift")
    if result.contract_sha256 != binding.contract_sha256:
        _fail("contract_drift")
    if result.producer_run_id != binding.run_id:
        _fail("result_run_drift")
    if type(terminal) is not PythonProducerTerminal or type(observation) is not PythonProducerRuntimeObservation:
        _fail("nested_invalid")
    try:
        terminal = parse_python_producer_terminal(terminal.to_json())
        observation = parse_python_producer_runtime_observation(observation.to_json())
    except (PythonProducerLifecycleError, TypeError, ValueError) as exc:
        raise PythonProducerAdapterError("nested_invalid") from exc
    if terminal.binding_sha256 != binding.binding_sha256 or observation.binding_sha256 != binding.binding_sha256:
        _fail("binding_drift")
    if (terminal.run_id != binding.run_id or terminal.journal_id != binding.intent.journal_id
            or terminal.launch_id != binding.intent.launch_id):
        _fail("terminal_identity_drift")
    if terminal.deadline_unix != binding.deadline_unix:
        _fail("deadline_drift")
    if terminal.request_count > binding.request_budget:
        _fail("request_budget_exceeded")
    interpreter = binding.interpreter
    for name, expected in (
        ("executable_sha256", interpreter.sha256), ("executable_size", interpreter.size),
        ("executable_device", interpreter.device), ("executable_inode", interpreter.inode),
    ):
        if getattr(terminal, name) != expected:
            _fail("executable_identity_drift")
    major, minor = (int(part) for part in binding.target.python_version.split(".", 1))
    if (observation.version_major != major or observation.version_minor != minor
            or observation.cache_tag != f"cpython-{major}{minor}"
            or not observation.abi_profile.startswith(binding.target.abi_tag + "-")
            or observation.flags != tuple(binding.runtime_manifest.to_dict()["policy"]["argv_flags"])
            or observation.argv != binding.argv or observation.orig_argv != binding.argv
            or observation.pycache_absent is not True):
        _fail("runtime_target_drift")
    item = PythonProducerAdapterEnvelope(
        schema_version=PYTHON_PRODUCER_ADAPTER_SCHEMA_VERSION,
        protocol=PYTHON_PRODUCER_ADAPTER_PROTOCOL,
        producer_id=binding.producer_id,
        binding_sha256=binding.binding_sha256, intent_sha256=binding.intent_sha256,
        attestation_sha256=binding.attestation_sha256,
        runtime_manifest_sha256=binding.runtime_manifest_sha256,
        runtime_tree_sha256=binding.runtime_tree_sha256,
        terminal=terminal, observation=observation, result=result,
    )
    return replace(item, adapter_sha256=item._digest_unchecked())


def parse_python_producer_adapter_envelope(
    value: PythonProducerAdapterEnvelope | bytes | str | Mapping[str, object],
) -> PythonProducerAdapterEnvelope:
    """Parse and verify a canonical adapter envelope without I/O."""
    return _parse_parts(value)


def verify_python_producer_adapter_envelope(
    binding: PythonProducerBinding,
    envelope: PythonProducerAdapterEnvelope | bytes | str | Mapping[str, object],
) -> PythonProducerAdapterEnvelope:
    """Compare detached evidence to an original binding without granting admission."""
    parsed = _parse_parts(envelope)
    expected = build_python_producer_adapter_envelope(
        binding, parsed.terminal, parsed.observation, parsed.result,
    )
    if expected.to_json() != parsed.to_json():
        _fail("envelope_binding_drift")
    return parsed


__all__ = [
    "MAX_PYTHON_PRODUCER_ADAPTER_BYTES", "PYTHON_PRODUCER_ADAPTER_PROTOCOL",
    "PYTHON_PRODUCER_ADAPTER_SCHEMA_VERSION", "SUPPORTED_PYTHON_PRODUCERS",
    "PythonProducerAdapterEnvelope", "PythonProducerAdapterError",
    "build_python_producer_adapter_envelope",
    "parse_python_producer_adapter_envelope",
    "verify_python_producer_adapter_envelope",
]
