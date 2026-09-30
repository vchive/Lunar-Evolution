"""Narrow solver-adapter contract for RSI.

The contract is intentionally provider-free.  It gives the controller one lifecycle vocabulary
for local fixtures and future solver processes without allowing an adapter to write RSI memory or
claim verifier authority.  Existing ``SolverGateway`` implementations that only expose ``run``
are accepted by :class:`AdapterContractHarness`; richer adapters may expose the named lifecycle
methods and are called in order.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from .candidate_evaluation_spec import canonical_json
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import RSILearningError

_TERMINAL = frozenset({"completed", "failed", "timed_out", "abandoned", "cancelled", "unknown"})


def _digest(value: object, name: str = "digest") -> str:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise RSILearningError(f"rsi_adapter_{name}_invalid")
    return value


def _identifier(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or any(char in value for char in "\x00\r\n"):
        raise RSILearningError(f"rsi_adapter_{name}_invalid")
    return value


def _record_digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _bounded_mapping(value: Mapping[str, Any] | None, name: str, maximum: int = 32) -> tuple[tuple[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, Mapping) or len(value) > maximum:
        raise RSILearningError(f"rsi_adapter_{name}_invalid")
    items: list[tuple[str, Any]] = []
    for key, item in value.items():
        if type(key) is not str or not key or "\x00" in key:
            raise RSILearningError(f"rsi_adapter_{name}_invalid")
        items.append((key, item))
    return tuple(sorted(items))


class AdapterLifecycle(str, Enum):
    REGISTER = "register"
    PREFLIGHT = "preflight"
    SNAPSHOT = "snapshot"
    EXECUTE = "execute"
    OBSERVE = "observe"
    FINALIZE = "finalize"
    VERIFY = "verify"
    RECOVER = "recover"
    CLOSE = "close"


# Short aliases are retained for callers that use the phase/status terminology.
LifecyclePhase = AdapterLifecycle
AdapterPhase = AdapterLifecycle


class AdapterTerminalStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AdapterCapability:
    """Declared adapter properties; capability is descriptive, never evaluator authority."""

    solver_id: str
    version: str = "1"
    provider_free: bool = True
    supports_snapshot: bool = True
    supports_recovery: bool = True
    supports_verify: bool = False
    memory_write: bool = False
    cleanup: bool = True
    fixture: bool = False
    lifecycle: tuple[str, ...] = tuple(stage.value for stage in AdapterLifecycle)

    def __post_init__(self) -> None:
        _identifier(self.solver_id, "solver_id")
        _identifier(self.version, "version")
        if type(self.lifecycle) is not tuple or not self.lifecycle:
            raise RSILearningError("rsi_adapter_lifecycle_invalid")
        allowed = {stage.value for stage in AdapterLifecycle}
        if any(stage not in allowed for stage in self.lifecycle) or len(set(self.lifecycle)) != len(self.lifecycle):
            raise RSILearningError("rsi_adapter_lifecycle_invalid")
        if self.memory_write:
            raise RSILearningError("rsi_adapter_memory_write_forbidden")

    @classmethod
    def for_fixture(cls, solver_id: str, *, version: str = "fixture-v1") -> AdapterCapability:
        """Declare a local fixture; this never starts an external solver."""

        return cls(solver_id=solver_id, version=version, provider_free=True, fixture=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "solver_id": self.solver_id,
            "version": self.version,
            "provider_free": self.provider_free,
            "supports_snapshot": self.supports_snapshot,
            "supports_recovery": self.supports_recovery,
            "supports_verify": self.supports_verify,
            "memory_write": self.memory_write,
            "cleanup": self.cleanup,
            "fixture": self.fixture,
            "lifecycle": list(self.lifecycle),
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())


@dataclass(frozen=True)
class AdapterPins:
    """Immutable identities shared by request, receipt and recovery."""

    contract_sha256: str
    evaluator_sha256: str
    environment_sha256: str
    memory_snapshot_sha256: str

    def __post_init__(self) -> None:
        for name in ("contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256"):
            _digest(getattr(self, name), name)

    @classmethod
    def from_solver_request(cls, request: SolverRequest) -> AdapterPins:
        return cls(request.contract_sha256, request.evaluator_sha256, request.environment_sha256, request.memory_snapshot_sha256)

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_sha256": self.contract_sha256,
            "evaluator_sha256": self.evaluator_sha256,
            "environment_sha256": self.environment_sha256,
            "memory_snapshot_sha256": self.memory_snapshot_sha256,
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())


@dataclass(frozen=True)
class AdapterBudget:
    """Bounded request budget.  The adapter may consume it but may not increase it."""

    limits: tuple[tuple[str, Any], ...] = ()
    deadline_at: float | None = None

    def __post_init__(self) -> None:
        if type(self.limits) is not tuple or len(self.limits) > 32:
            raise RSILearningError("rsi_adapter_budget_invalid")
        for key, value in self.limits:
            if type(key) is not str or not key:
                raise RSILearningError("rsi_adapter_budget_invalid")
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise RSILearningError("rsi_adapter_budget_invalid")
        if self.deadline_at is not None and (isinstance(self.deadline_at, bool) or not isinstance(self.deadline_at, (int, float)) or not math.isfinite(float(self.deadline_at))):
            raise RSILearningError("rsi_adapter_deadline_invalid")

    @classmethod
    def build(cls, limits: Mapping[str, Any] | None = None, *, deadline_at: float | None = None) -> AdapterBudget:
        return cls(_bounded_mapping(limits, "budget"), deadline_at)

    def to_dict(self) -> dict[str, Any]:
        return {"limits": dict(self.limits), "deadline_at": self.deadline_at}

    def expired(self, now: float | None = None) -> bool:
        return self.deadline_at is not None and (time.monotonic() if now is None else float(now)) >= self.deadline_at


@dataclass(frozen=True)
class AdapterRequest:
    """Contract request containing one immutable ``SolverRequest`` and its execution deadline."""

    episode_id: str
    solver_id: str
    pins: AdapterPins
    budget: AdapterBudget
    solver_settings: tuple[tuple[str, Any], ...] = ()
    practice_charter: tuple[tuple[str, Any], ...] = ()
    source_request_sha256: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.episode_id, "episode_id")
        _identifier(self.solver_id, "solver_id")
        if not isinstance(self.pins, AdapterPins) or not isinstance(self.budget, AdapterBudget):
            raise RSILearningError("rsi_adapter_request_invalid")
        if type(self.solver_settings) is not tuple or type(self.practice_charter) is not tuple:
            raise RSILearningError("rsi_adapter_request_invalid")
        if self.source_request_sha256 is not None:
            _digest(self.source_request_sha256, "request_sha256")

    @classmethod
    def from_solver_request(cls, request: SolverRequest, *, deadline_at: float | None = None) -> AdapterRequest:
        if not isinstance(request, SolverRequest):
            raise RSILearningError("rsi_adapter_request_invalid")
        return cls(
            request.episode_id,
            request.solver_id,
            AdapterPins.from_solver_request(request),
            AdapterBudget(request.budget, deadline_at),
            request.solver_settings,
            request.practice_charter,
            request.digest(),
        )

    @classmethod
    def build(
        cls,
        *,
        episode_id: str,
        solver_id: str,
        pins: AdapterPins,
        budget: Mapping[str, Any] | None = None,
        deadline_at: float | None = None,
        solver_settings: Mapping[str, Any] | None = None,
        practice_charter: Mapping[str, Any] | None = None,
    ) -> AdapterRequest:
        return cls(episode_id, solver_id, pins, AdapterBudget.build(budget, deadline_at=deadline_at), _bounded_mapping(solver_settings, "solver_settings"), _bounded_mapping(practice_charter, "practice_charter"))

    def to_solver_request(self) -> SolverRequest:
        return SolverRequest.build(
            episode_id=self.episode_id,
            contract_sha256=self.pins.contract_sha256,
            evaluator_sha256=self.pins.evaluator_sha256,
            environment_sha256=self.pins.environment_sha256,
            memory_snapshot_sha256=self.pins.memory_snapshot_sha256,
            solver_id=self.solver_id,
            solver_settings=dict(self.solver_settings),
            budget=dict(self.budget.limits),
            practice_charter=dict(self.practice_charter),
        )

    @property
    def request_sha256(self) -> str:
        return self.source_request_sha256 or self.to_solver_request().digest()

    def to_dict(self) -> dict[str, Any]:
        request = self.to_solver_request()
        return {
            "episode_id": self.episode_id,
            "solver_id": self.solver_id,
            "pins": self.pins.to_dict(),
            "budget": self.budget.to_dict(),
            "solver_settings": dict(self.solver_settings),
            "practice_charter": dict(self.practice_charter),
            "request_sha256": request.digest(),
        }


@dataclass(frozen=True)
class AdapterOwnership:
    workspace_owned: bool = True
    process_owned: bool = True
    cleanup_required: bool = True
    memory_write_enabled: bool = False

    def __post_init__(self) -> None:
        if self.memory_write_enabled:
            raise RSILearningError("rsi_adapter_memory_write_forbidden")

    def to_dict(self) -> dict[str, bool]:
        return {
            "workspace_owned": self.workspace_owned,
            "process_owned": self.process_owned,
            "cleanup_required": self.cleanup_required,
            "memory_write_enabled": self.memory_write_enabled,
        }


@dataclass(frozen=True)
class AdapterReceipt:
    status: str
    episode_id: str
    request_sha256: str
    trace_digest: str
    candidate_receipt_sha256: str | None = None
    execution_receipt_sha256: str | None = None
    official_evaluation_receipt_sha256: str | None = None
    terminal_reason: str = ""

    def __post_init__(self) -> None:
        if self.status not in _TERMINAL:
            raise RSILearningError("rsi_adapter_status_invalid")
        _identifier(self.episode_id, "episode_id")
        _digest(self.request_sha256, "request_sha256")
        _digest(self.trace_digest, "trace_digest")
        for name in ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"):
            value = getattr(self, name)
            if value is not None:
                _digest(value, name)

    @classmethod
    def from_solver_result(cls, result: SolverResult) -> AdapterReceipt:
        if not isinstance(result, SolverResult):
            raise RSILearningError("rsi_adapter_result_invalid")
        return cls(result.status, result.episode_id, result.request_sha256, result.trace_digest, result.candidate_receipt_sha256, result.execution_receipt_sha256, result.official_evaluation_receipt_sha256, result.terminal_reason)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "kind": "rsi_adapter_receipt",
            "status": self.status,
            "episode_id": self.episode_id,
            "request_sha256": self.request_sha256,
            "trace_digest": self.trace_digest,
            "candidate_receipt_sha256": self.candidate_receipt_sha256,
            "execution_receipt_sha256": self.execution_receipt_sha256,
            "official_evaluation_receipt_sha256": self.official_evaluation_receipt_sha256,
            "terminal_reason": self.terminal_reason,
        }

    def digest(self) -> str:
        return _record_digest(self.to_dict())


@dataclass(frozen=True)
class AdapterResult:
    receipt: AdapterReceipt
    lifecycle: tuple[str, ...]
    ownership: AdapterOwnership = field(default_factory=AdapterOwnership)
    capability_sha256: str | None = None

    @property
    def status(self) -> str:
        return self.receipt.status

    @property
    def episode_id(self) -> str:
        return self.receipt.episode_id


@runtime_checkable
class SolverAdapterProtocol(Protocol):
    """Optional rich hooks; ``run`` alone remains a valid legacy gateway."""

    def register(self, request: AdapterRequest) -> Any: ...
    def preflight(self, request: AdapterRequest) -> Any: ...
    def snapshot(self, request: AdapterRequest) -> Any: ...
    def execute(self, request: AdapterRequest) -> SolverResult: ...
    def observe(self, request: AdapterRequest, result: AdapterResult) -> Any: ...
    def finalize(self, request: AdapterRequest, result: AdapterResult) -> Any: ...
    def verify(self, request: AdapterRequest, result: AdapterResult) -> Any: ...
    def recover(self, request: AdapterRequest, result: AdapterResult) -> Any: ...
    def close(self, request: AdapterRequest, result: AdapterResult) -> Any: ...
    def run(self, request: SolverRequest) -> SolverResult: ...


class AdapterContractError(RSILearningError):
    """Adapter violated the narrow lifecycle contract."""


def _terminal_from_exception(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if isinstance(exc, TimeoutError) or "timeout" in name or "timedout" in name:
        return "timed_out"
    if "cancel" in name or name in {"keyboardinterrupt", "cancellederror"}:
        return "cancelled"
    if "unknown" in name or "uncertain" in name:
        return "unknown"
    return "failed"


def validate_lifecycle(gateway: object, capability: AdapterCapability | None = None) -> AdapterCapability:
    """Validate declaration and reject adapters that expose a memory-write authority."""

    if capability is None:
        solver_id = getattr(gateway, "solver_id", None) or getattr(gateway, "name", None) or "fixture"
        # ``for_fixture`` is the declaration-only factory.  Keep the implicit
        # capability path equivalent to an explicit ``fixture_capability``
        # declaration without requiring adapters to expose a solver registry.
        capability = AdapterCapability.for_fixture(str(solver_id))
    if not isinstance(capability, AdapterCapability):
        raise AdapterContractError("rsi_adapter_capability_invalid")
    for attr in ("memory_store", "memory_writer", "write_memory", "commit_memory", "publish_memory", "admit_memory"):
        value = getattr(gateway, attr, None)
        if callable(value) or value is not None:
            raise AdapterContractError("rsi_adapter_memory_write_forbidden")
    value = getattr(gateway, "memory_write", None)
    if callable(value) or value is True:
        raise AdapterContractError("rsi_adapter_memory_write_forbidden")
    return capability


class AdapterContractHarness:
    """Run a gateway through the common lifecycle without granting memory-write authority."""

    def __init__(self, gateway: object, *, capability: AdapterCapability | None = None, clock: Any = time.monotonic) -> None:
        self.gateway = gateway
        self.capability = validate_lifecycle(gateway, capability)
        self.clock = clock

    def validate(self) -> AdapterCapability:
        return self.capability

    @staticmethod
    def _invoke(method: Any, request: AdapterRequest, result: AdapterResult | None = None) -> Any:
        """Call a hook once using the first compatible argument shape."""
        try:
            signature = inspect.signature(method)
        except (TypeError, ValueError):
            args = (request, result) if result is not None else (request,)
            return method(*args)
        solver_request = request.to_solver_request()
        # Prefer the rich request for named hooks.  The empty-argument shape is
        # deliberately last when no result is available: otherwise a hook such
        # as ``preflight(request=None)`` would silently receive no request.
        if result is None:
            candidates = ((request,), (solver_request,), ())
        else:
            candidates = (
                (request, result),
                (solver_request, result),
                (request,),
                (solver_request,),
                (),
            )
        for args in candidates:
            try:
                signature.bind(*args)
            except TypeError:
                continue
            return method(*args)
        raise TypeError(f"unsupported adapter hook signature: {method!r}")

    def run(self, request: AdapterRequest | SolverRequest, *, cancel: bool = False, now: float | None = None) -> AdapterResult:
        if isinstance(request, SolverRequest):
            request = AdapterRequest.from_solver_request(request)
        if not isinstance(request, AdapterRequest) or request.solver_id != self.capability.solver_id and self.capability.solver_id != "fixture":
            raise AdapterContractError("rsi_adapter_request_mismatch")
        phases: list[str] = []
        result: AdapterResult | None = None
        solver_result: SolverResult | None = None
        closed = False
        recovery_attempted = False
        close_attempted = False

        def recover(recovery_result: AdapterResult) -> None:
            nonlocal recovery_attempted
            if recovery_attempted or not self.capability.supports_recovery:
                return
            recovery_attempted = True
            phases.append(AdapterLifecycle.RECOVER.value)
            method = getattr(self.gateway, "recover", None)
            if method is not None:
                self._invoke(method, request, recovery_result)

        def close(close_result: AdapterResult | None) -> None:
            nonlocal close_attempted
            if close_attempted:
                return
            close_attempted = True
            phases.append(AdapterLifecycle.CLOSE.value)
            method = getattr(self.gateway, "close", None)
            if method is not None:
                try:
                    self._invoke(method, request, close_result)
                except Exception:  # noqa: BLE001,S110 - cleanup is explicitly best effort
                    # Cleanup is best effort.  The terminal receipt already
                    # records the execution outcome and must not be replaced
                    # by a cleanup implementation error.
                    pass

        try:
            for phase in (AdapterLifecycle.REGISTER, AdapterLifecycle.PREFLIGHT, AdapterLifecycle.SNAPSHOT):
                phases.append(phase.value)
                method = getattr(self.gateway, phase.value, None)
                if method is not None:
                    self._invoke(method, request)
            if cancel or request.budget.expired(self.clock() if now is None else now):
                status = "cancelled" if cancel else "timed_out"
                trace = _record_digest({"episode_id": request.episode_id, "status": status})
                solver_result = SolverResult(request.episode_id, request.to_solver_request().digest(), status, None, None, None, trace, terminal_reason=f"contract_{status}")
            else:
                phases.append(AdapterLifecycle.EXECUTE.value)
                method = getattr(self.gateway, "execute", None) or getattr(self.gateway, "run", None)
                if method is None:
                    raise AdapterContractError("rsi_adapter_execute_missing")
                # The legacy SolverGateway.run contract receives SolverRequest.  Rich
                # adapters may expose execute and receive the richer AdapterRequest.
                if getattr(method, "__name__", "") == "run":
                    raw = method(request.to_solver_request())
                else:
                    raw = self._invoke(method, request)
                solver_result = raw if isinstance(raw, SolverResult) else SolverResult.from_dict(raw)
            if solver_result.episode_id != request.episode_id or solver_result.request_sha256 != request.to_solver_request().digest():
                raise AdapterContractError("rsi_adapter_result_identity_mismatch")
            receipt = AdapterReceipt.from_solver_result(solver_result)
            result = AdapterResult(receipt, tuple(phases), AdapterOwnership(), self.capability.digest())
            for phase in (AdapterLifecycle.OBSERVE, AdapterLifecycle.FINALIZE, AdapterLifecycle.VERIFY):
                phases.append(phase.value)
                method = getattr(self.gateway, phase.value, None)
                if method is not None:
                    self._invoke(method, request, result)
            if result.status in {"failed", "timed_out", "cancelled", "unknown"}:
                recover(result)
            close(result)
            closed = True
            return AdapterResult(result.receipt, tuple(phases), result.ownership, result.capability_sha256)
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            status = _terminal_from_exception(exc)
            trace = _record_digest({"episode_id": request.episode_id, "status": status, "error": type(exc).__name__})
            fallback = SolverResult(request.episode_id, request.to_solver_request().digest(), status, None, None, None, trace, terminal_reason=f"contract_{status}")
            fallback_result = AdapterResult(
                AdapterReceipt.from_solver_result(fallback),
                tuple(phases),
                AdapterOwnership(),
                self.capability.digest(),
            )
            try:
                recover(fallback_result)
            except Exception:  # noqa: BLE001,S110 - recovery cannot mask the primary failure
                # A recovery hook cannot erase the primary failure or prevent
                # cleanup.  Its attempted phase remains journaled once.
                pass
            close(fallback_result)
            closed = True
            return AdapterResult(fallback_result.receipt, tuple(phases), fallback_result.ownership, fallback_result.capability_sha256)
        finally:
            if not closed and not close_attempted:
                close(result)

    execute = run


def fixture_capability(solver_id: str) -> AdapterCapability:
    """Return declaration-only capabilities for provider-free solver names."""

    if solver_id not in {"fixture", "mock", "native_population", "openevolve", "shinka"}:
        raise AdapterContractError("rsi_adapter_solver_invalid")
    return AdapterCapability.for_fixture(solver_id)


OPENEVOLVE_CAPABILITY = fixture_capability("openevolve")
SHINKA_CAPABILITY = fixture_capability("shinka")

__all__ = [
    "OPENEVOLVE_CAPABILITY",
    "SHINKA_CAPABILITY",
    "AdapterBudget",
    "AdapterCapability",
    "AdapterContractError",
    "AdapterContractHarness",
    "AdapterLifecycle",
    "AdapterOwnership",
    "AdapterPhase",
    "AdapterPins",
    "AdapterReceipt",
    "AdapterRequest",
    "AdapterResult",
    "AdapterTerminalStatus",
    "LifecyclePhase",
    "SolverAdapterProtocol",
    "fixture_capability",
    "validate_lifecycle",
]
