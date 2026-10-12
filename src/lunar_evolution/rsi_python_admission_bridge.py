"""Provider-free descriptor for the live Python admission bridge.

Feature191 already has explicit DRS/BRS publication facades, but the live RSI
controller does not yet receive the native plan and prepared publication journal
needed by those facades.  This module freezes that missing input as a detached
descriptor.  Parsing and validation are pure: no file, ledger, process,
evaluator, budget or callback is touched.  A later controller integration can
require this descriptor before dispatch and invoke the named hooks at the
prepared boundary.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .candidate_evaluation_spec import canonical_json, strict_json
from .producer_bundle_publication import ProducerBundlePublicationJournal
from .rsi_native_plan import NativeRSIExecutionPlan

PYTHON_ADMISSION_BRIDGE_PROTOCOL = "lunar-python-admission-bridge-v1"
PYTHON_ADMISSION_BRIDGE_SCHEMA_VERSION = "1"
PYTHON_ADMISSION_DRS_PIN_HOOK = "rsi-python-drs-prepared-pin-v1"
PYTHON_ADMISSION_BRS_PIN_HOOK = "rsi-python-brs-ready-ack-pin-v1"
MAX_PYTHON_ADMISSION_BRIDGE_BYTES = 512 * 1024

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_FIELDS = frozenset({
    "schema_version", "protocol", "run_id", "episode_id", "native_plan",
    "prepared_journal", "expected_anchor_sha256", "drs_pin_hook", "brs_pin_hook",
    "bridge_sha256",
})


class PythonAdmissionBridgeError(ValueError):
    """Fixed-code refusal for malformed or mismatched bridge descriptors."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_python_admission_bridge_" + code
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise PythonAdmissionBridgeError(code)


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        _fail(field + "_invalid")
    return value


def _digest(value: object, field: str) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None or value == "0" * 64:
        _fail(field + "_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        raw = canonical_json(value, maximum=MAX_PYTHON_ADMISSION_BRIDGE_BYTES)
    except Exception as exc:  # pragma: no cover - canonical_json fixes the public code
        raise PythonAdmissionBridgeError("canonical_invalid") from exc
    if len(raw) > MAX_PYTHON_ADMISSION_BRIDGE_BYTES:
        _fail("record_too_large")
    return raw


def _strict_wire(value: object) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _FIELDS:
        _fail("schema_invalid")
    try:
        encoded = _canonical(value)
        parsed = strict_json(encoded, maximum=MAX_PYTHON_ADMISSION_BRIDGE_BYTES)
    except PythonAdmissionBridgeError:
        raise
    except Exception as exc:
        raise PythonAdmissionBridgeError("json_invalid") from exc
    if parsed != value or _canonical(parsed) != encoded:
        _fail("noncanonical_json")
    return value


def _parse_nested(
    native_plan: object, prepared_journal: object,
) -> tuple[NativeRSIExecutionPlan, ProducerBundlePublicationJournal]:
    try:
        plan = NativeRSIExecutionPlan.from_dict(native_plan)
        journal = ProducerBundlePublicationJournal.from_dict(prepared_journal)
    except Exception as exc:
        raise PythonAdmissionBridgeError("nested_invalid") from exc
    if journal.state != "prepared" or journal.publication_phase != "preflight":
        _fail("prepared_journal_not_preflight")
    if (
        plan.run_id != journal.run_id
        or plan.journal_id != journal.journal_id
        or plan.parent_task_id != journal.parent_task_id
        or plan.task_id != journal.task_id
    ):
        _fail("identity_mismatch")
    return plan, journal


@dataclass(frozen=True, slots=True)
class PythonAdmissionBridgeDescriptor:
    """Canonical inputs required before a live Python admission hook can run.

    The two hook fields are protocol identifiers, not callables.  Keeping
    callbacks out of the wire prevents a descriptor from smuggling executable
    authority through canonical JSON.  The future controller bridge must map
    these fixed identifiers to its own DRS/BRS methods.
    """

    run_id: str
    episode_id: str
    native_plan: NativeRSIExecutionPlan
    prepared_journal: ProducerBundlePublicationJournal
    expected_anchor_sha256: str
    drs_pin_hook: str = PYTHON_ADMISSION_DRS_PIN_HOOK
    brs_pin_hook: str = PYTHON_ADMISSION_BRS_PIN_HOOK
    bridge_sha256: str | None = None
    schema_version: str = PYTHON_ADMISSION_BRIDGE_SCHEMA_VERSION
    protocol: str = PYTHON_ADMISSION_BRIDGE_PROTOCOL

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not str
            or type(self.protocol) is not str
            or self.schema_version != PYTHON_ADMISSION_BRIDGE_SCHEMA_VERSION
            or self.protocol != PYTHON_ADMISSION_BRIDGE_PROTOCOL
        ):
            _fail("schema_invalid")
        _identifier(self.run_id, "run_id")
        _identifier(self.episode_id, "episode_id")
        _digest(self.expected_anchor_sha256, "anchor_sha256")
        if self.drs_pin_hook != PYTHON_ADMISSION_DRS_PIN_HOOK:
            _fail("drs_hook_invalid")
        if self.brs_pin_hook != PYTHON_ADMISSION_BRS_PIN_HOOK:
            _fail("brs_hook_invalid")
        if type(self.native_plan) is not NativeRSIExecutionPlan:
            _fail("native_plan_invalid")
        if type(self.prepared_journal) is not ProducerBundlePublicationJournal:
            _fail("prepared_journal_invalid")
        # Reparse nested wires so caller-owned objects cannot be substituted after
        # validation.  The parser also checks the prepared phase and full identity.
        plan, journal = _parse_nested(self.native_plan.to_dict(), self.prepared_journal.to_dict())
        if (
            plan != self.native_plan
            or journal != self.prepared_journal
            or self.run_id != plan.run_id
            or self.episode_id != plan.request.episode_id
        ):
            _fail("identity_mismatch")
        if self.bridge_sha256 is not None:
            _digest(self.bridge_sha256, "bridge_sha256")

    def _body(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "protocol": self.protocol,
            "run_id": self.run_id,
            "episode_id": self.episode_id,
            "native_plan": self.native_plan.to_dict(),
            "prepared_journal": self.prepared_journal.to_dict(),
            "expected_anchor_sha256": self.expected_anchor_sha256,
            "drs_pin_hook": self.drs_pin_hook,
            "brs_pin_hook": self.brs_pin_hook,
        }

    def digest(self) -> str:
        self.__post_init__()
        return hashlib.sha256(_canonical(self._body())).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        digest = self.digest()
        if self.bridge_sha256 is not None and self.bridge_sha256 != digest:
            _fail("bridge_digest_mismatch")
        return self._body() | {"bridge_sha256": digest}

    def to_json(self) -> bytes:
        return _canonical(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> PythonAdmissionBridgeDescriptor:
        raw = _strict_wire(value)
        _digest(raw["bridge_sha256"], "bridge_sha256")
        try:
            result = cls(
                run_id=raw["run_id"], episode_id=raw["episode_id"],
                native_plan=NativeRSIExecutionPlan.from_dict(raw["native_plan"]),
                prepared_journal=ProducerBundlePublicationJournal.from_dict(raw["prepared_journal"]),
                expected_anchor_sha256=raw["expected_anchor_sha256"],
                drs_pin_hook=raw["drs_pin_hook"], brs_pin_hook=raw["brs_pin_hook"],
                bridge_sha256=raw["bridge_sha256"], schema_version=raw["schema_version"],
                protocol=raw["protocol"],
            )
        except PythonAdmissionBridgeError:
            raise
        except Exception as exc:
            raise PythonAdmissionBridgeError("nested_invalid") from exc
        if result.bridge_sha256 != result.digest():
            _fail("bridge_digest_mismatch")
        return result

    @classmethod
    def from_json(cls, value: bytes | str) -> PythonAdmissionBridgeDescriptor:
        if type(value) not in {bytes, str}:
            _fail("json_invalid")
        try:
            encoded = value if type(value) is bytes else value.encode("utf-8")
            if len(encoded) > MAX_PYTHON_ADMISSION_BRIDGE_BYTES:
                _fail("record_too_large")
            parsed = strict_json(encoded, maximum=MAX_PYTHON_ADMISSION_BRIDGE_BYTES)
        except PythonAdmissionBridgeError:
            raise
        except Exception as exc:
            raise PythonAdmissionBridgeError("json_invalid") from exc
        result = cls.from_dict(parsed)
        if result.to_json() != encoded:
            _fail("noncanonical_json")
        return result


def build_python_admission_bridge_descriptor(**kwargs: Any) -> PythonAdmissionBridgeDescriptor:
    """Build a descriptor and derive its immutable digest."""
    descriptor = PythonAdmissionBridgeDescriptor(**kwargs)
    return replace(descriptor, bridge_sha256=descriptor.digest())


def parse_python_admission_bridge_descriptor(
    value: PythonAdmissionBridgeDescriptor | dict[str, Any] | bytes | str,
) -> PythonAdmissionBridgeDescriptor:
    if type(value) is PythonAdmissionBridgeDescriptor:
        return PythonAdmissionBridgeDescriptor.from_dict(value.to_dict())
    if type(value) is dict:
        return PythonAdmissionBridgeDescriptor.from_dict(value)
    return PythonAdmissionBridgeDescriptor.from_json(value)


def validate_python_admission_bridge_descriptor(
    value: PythonAdmissionBridgeDescriptor | dict[str, Any] | bytes | str,
    *, run_id: str, episode_id: str,
) -> PythonAdmissionBridgeDescriptor:
    """Reparse and bind a bridge descriptor to one controller episode."""
    _identifier(run_id, "run_id")
    _identifier(episode_id, "episode_id")
    descriptor = parse_python_admission_bridge_descriptor(value)
    if descriptor.run_id != run_id or descriptor.episode_id != episode_id:
        _fail("controller_identity_mismatch")
    return descriptor


class PythonAdmissionBridge(Protocol):
    """Future controller adapter implemented by the live scheduler integration.

    Implementations must map the fixed hook identifiers to the existing active-flow
    and BRS worker facades.  This protocol deliberately carries no authority itself;
    callers must validate the descriptor before invoking either hook.
    """

    descriptor: PythonAdmissionBridgeDescriptor

    def pin_drs(self, descriptor: PythonAdmissionBridgeDescriptor) -> str:
        """Pin the prepared evidence on the owning DRS controller thread."""

    def pin_brs(self, descriptor: PythonAdmissionBridgeDescriptor) -> str:
        """Request the owning BRS thread to pin prepared evidence and acknowledge it."""


__all__ = [
    "MAX_PYTHON_ADMISSION_BRIDGE_BYTES",
    "PYTHON_ADMISSION_BRIDGE_PROTOCOL",
    "PYTHON_ADMISSION_BRIDGE_SCHEMA_VERSION",
    "PYTHON_ADMISSION_BRS_PIN_HOOK",
    "PYTHON_ADMISSION_DRS_PIN_HOOK",
    "PythonAdmissionBridge",
    "PythonAdmissionBridgeDescriptor",
    "PythonAdmissionBridgeError",
    "build_python_admission_bridge_descriptor",
    "parse_python_admission_bridge_descriptor",
    "validate_python_admission_bridge_descriptor",
]
