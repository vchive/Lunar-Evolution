"""Stable local identities for RSI controller components.

This module fingerprints local verifier, curriculum, target-judge and adapter components.  It is
an identity helper, not a provider attestation: it does not authenticate a package, host, model or
remote service.  A component identity commits to source/code plus an explicit, stable
configuration projection.  Runtime counters, caches and process state are intentionally excluded.

Objects should expose ``rsi_fingerprint_config()`` (or the shorter
``fingerprint_config()``) and may expose ``rsi_fingerprint_code()``/``fingerprint_code()`` when
their executable source is generated or otherwise unavailable to :func:`inspect.getsource`.
Without an explicit configuration hook, mutable objects fail closed rather than hashing their
``__dict__``.  This prevents call counters and other runtime state from changing a durable RSI
identity.

Function identities bind immutable defaults and lexical captures. External dependencies such as
module globals, imported helpers and provider/model settings must be projected by the component's
explicit configuration hook; this helper does not discover a complete Python dependency graph.
"""

from __future__ import annotations

import hashlib
import inspect
import math
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import CodeType
from typing import Any, ClassVar

from .candidate_evaluation_spec import canonical_json

RSI_IDENTITY_SCHEMA_VERSION = "1"
RSI_IDENTITY_KIND = "rsi_component_identity"
MAX_IDENTITY_BYTES = 128 * 1024
MAX_CODE_BYTES = 96 * 1024
MAX_CONFIG_DEPTH = 12
MAX_CONFIG_KEYS = 256
MAX_CONFIG_TEXT_BYTES = 16 * 1024


class RSIIdentityError(ValueError):
    """Stable, fail-closed identity construction error."""

    _CODES: ClassVar[frozenset[str]] = frozenset({
        "invalid", "config_hook_required", "config_invalid", "code_hook_required",
        "code_invalid", "code_unavailable", "too_large", "hook_failed",
    })

    def __init__(self, code: str) -> None:
        normalized = code if code in self._CODES else "invalid"
        self.code = f"rsi_identity_{normalized}"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise RSIIdentityError(code)


def _type_identity(value: object) -> dict[str, str]:
    target = value if inspect.isclass(value) or inspect.isfunction(value) or inspect.ismethod(value) else type(value)
    module = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if type(module) is not str or not module or type(qualname) is not str or not qualname:
        _fail("invalid")
    return {"module": module, "qualname": qualname}


def _normalize(value: object, *, depth: int = 0) -> Any:
    """Normalize JSON-compatible configuration while rejecting mutable/runtime objects."""

    if depth > MAX_CONFIG_DEPTH:
        _fail("config_invalid")
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("config_invalid")
        return value
    if type(value) is str:
        if "\x00" in value:
            _fail("config_invalid")
        try:
            if len(value.encode("utf-8")) > MAX_CONFIG_TEXT_BYTES:
                _fail("config_invalid")
        except UnicodeEncodeError as exc:
            raise RSIIdentityError("config_invalid") from exc
        return value
    if isinstance(value, Mapping):
        if len(value) > MAX_CONFIG_KEYS:
            _fail("config_invalid")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str or not key or "\x00" in key:
                _fail("config_invalid")
            normalized[key] = _normalize(item, depth=depth + 1)
        return normalized
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_CONFIG_KEYS:
            _fail("config_invalid")
        return [_normalize(item, depth=depth + 1) for item in value]
    _fail("config_invalid")


def _invoke_hook(value: object, names: Sequence[str]) -> object | None:
    for name in names:
        hook = getattr(value, name, None)
        if hook is None:
            continue
        if not callable(hook):
            _fail("config_invalid")
        try:
            return hook()
        except RSIIdentityError:
            raise
        except Exception as exc:
            raise RSIIdentityError("hook_failed") from exc
    return None


def _immutable_callable_value(value: object, *, depth: int = 0) -> Any:
    """Bind immutable function configuration; mutable captures need a deliberate projection."""

    if depth > MAX_CONFIG_DEPTH:
        _fail("config_invalid")
    if value is None or type(value) in {bool, int, float, str}:
        return _normalize(value, depth=depth)
    if type(value) is tuple:
        if len(value) > MAX_CONFIG_KEYS:
            _fail("config_invalid")
        return [_immutable_callable_value(item, depth=depth + 1) for item in value]
    _fail("config_hook_required")


def _function_config(function: object) -> dict[str, Any]:
    """Include live defaults and captured configuration, which source text cannot identify."""

    if not inspect.isfunction(function):
        _fail("config_hook_required")
    closure = function.__closure__ or ()
    freevars = function.__code__.co_freevars
    if len(closure) != len(freevars):
        _fail("config_invalid")
    try:
        captures = {
            name: _immutable_callable_value(cell.cell_contents)
            for name, cell in zip(freevars, closure)
        }
    except RSIIdentityError:
        raise
    except ValueError as exc:
        raise RSIIdentityError("config_invalid") from exc
    return {
        "defaults": _immutable_callable_value(function.__defaults__),
        "kwdefaults": {
            name: _immutable_callable_value(value)
            for name, value in (function.__kwdefaults__ or {}).items()
        },
        "closure": captures,
    }


def _code_constant(value: object, *, depth: int) -> Any:
    if depth > MAX_CONFIG_DEPTH:
        _fail("code_invalid")
    if isinstance(value, CodeType):
        return {"code": _code_object_payload(value, depth=depth + 1)}
    if value is Ellipsis:
        return {"ellipsis": True}
    if type(value) is bytes:
        return {"bytes": value.hex()}
    if type(value) in {tuple, frozenset}:
        values = [_code_constant(item, depth=depth + 1) for item in value]
        if type(value) is frozenset:
            values.sort(key=lambda item: canonical_json(item, maximum=MAX_CODE_BYTES))
        return {type(value).__name__: values}
    if type(value) is complex:
        return {"complex": [value.real, value.imag]}
    if value is None or type(value) in {bool, int, float, str}:
        return value
    _fail("code_invalid")


def _code_object_payload(code: CodeType, *, depth: int = 0) -> dict[str, Any]:
    return {
        "co_code": code.co_code.hex(),
        "co_consts": [_code_constant(item, depth=depth) for item in code.co_consts],
        "co_names": list(code.co_names),
        "co_varnames": list(code.co_varnames),
        "co_freevars": list(code.co_freevars),
        "co_cellvars": list(code.co_cellvars),
        "co_argcount": code.co_argcount,
        "co_posonlyargcount": code.co_posonlyargcount,
        "co_kwonlyargcount": code.co_kwonlyargcount,
        "co_flags": code.co_flags,
    }


def _code_object_material(code: CodeType) -> str:
    # Include nested executable code and every constant; dropping a nested lambda or tuple would
    # make distinct generated solvers share the same identity.
    try:
        return "bytecode-v2:" + canonical_json(_code_object_payload(code), maximum=MAX_CODE_BYTES).decode("utf-8")
    except RSIIdentityError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise RSIIdentityError("code_invalid") from exc


def _source_material(value: object, explicit: object | None) -> str:
    if explicit is not None:
        if isinstance(explicit, bytes):
            try:
                explicit = explicit.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RSIIdentityError("code_invalid") from exc
        if type(explicit) is not str or not explicit.strip():
            _fail("code_invalid")
        source = explicit
    else:
        target = value
        if not (inspect.isclass(target) or inspect.isfunction(target) or inspect.ismethod(target)):
            target = type(target)
        try:
            source = inspect.getsource(target)
        except (OSError, TypeError):
            code = getattr(target, "__code__", None)
            if isinstance(code, CodeType):
                source = _code_object_material(code)
            else:
                # Include all source-visible class methods when the class declaration itself is
                # generated or unavailable.  If no method has source, an explicit code hook is
                # required; qualname alone is intentionally never accepted.
                members: list[str] = []
                for member in vars(target).values() if inspect.isclass(target) else ():
                    function = member
                    if isinstance(member, (staticmethod, classmethod)):
                        function = member.__func__
                    try:
                        if inspect.isfunction(function):
                            members.append(inspect.getsource(function))
                    except (OSError, TypeError):
                        continue
                if not members:
                    _fail("code_hook_required")
                source = "\n".join(members)
    source = textwrap.dedent(source).replace("\r\n", "\n").replace("\r", "\n").strip()
    try:
        if len(source.encode("utf-8")) > MAX_CODE_BYTES:
            _fail("too_large")
    except UnicodeEncodeError as exc:
        raise RSIIdentityError("code_invalid") from exc
    return source


def _config_material(value: object, explicit: object | None) -> Any:
    if explicit is not None:
        return _normalize(explicit)
    hook_value = _invoke_hook(value, ("rsi_fingerprint_config", "fingerprint_config"))
    if hook_value is not None:
        return _normalize(hook_value)
    if inspect.ismethod(value):
        # Source belongs to the method function, while behavior can depend on a different owner
        # instance each time.  The owner's hook excludes counters but must include real settings.
        owner_config = _invoke_hook(value.__self__, ("rsi_fingerprint_config", "fingerprint_config"))
        if owner_config is None:
            _fail("config_hook_required")
        return {
            "bound_owner": _normalize(owner_config),
            "callable": _function_config(value.__func__),
        }
    if inspect.isfunction(value):
        return _function_config(value)
    # Declarative JSON values are already stable configuration.  Arbitrary instances must opt in;
    # hashing __dict__ would accidentally include counters, caches and process-local handles.
    if value is None or type(value) in {bool, int, float, str} or isinstance(value, (Mapping, list, tuple)):
        return _normalize(value)
    if inspect.isclass(value):
        return {}
    _fail("config_hook_required")


@dataclass(frozen=True)
class ComponentIdentity:
    """Canonical local component identity used as a fingerprint input."""

    component_type: dict[str, str]
    code: str
    config: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RSI_IDENTITY_SCHEMA_VERSION,
            "kind": RSI_IDENTITY_KIND,
            "component_type": dict(self.component_type),
            "code": self.code,
            "config": self.config,
        }

    def to_bytes(self) -> bytes:
        try:
            payload = canonical_json(self.to_dict(), maximum=MAX_IDENTITY_BYTES)
        except Exception as exc:
            raise RSIIdentityError("too_large") from exc
        if len(payload) > MAX_IDENTITY_BYTES:
            raise RSIIdentityError("too_large")
        return payload

    def digest(self) -> str:
        return hashlib.sha256(self.to_bytes()).hexdigest()


def component_identity(
    value: object,
    *,
    config: object | None = None,
    code: object | None = None,
) -> ComponentIdentity:
    """Build a deterministic identity from source/code and explicit stable configuration."""

    config_material = _config_material(value, config)
    code_override = code
    if code_override is None:
        code_override = _invoke_hook(value, ("rsi_fingerprint_code", "fingerprint_code"))
    return ComponentIdentity(_type_identity(value), _source_material(value, code_override), config_material)


def component_fingerprint(
    value: object,
    *,
    config: object | None = None,
    code: object | None = None,
) -> str:
    """Return a stable SHA-256 identity for a local RSI component.

    This fingerprint is suitable for detecting local code/config drift.  It is not a signed
    attestation and must not be treated as proof of a remote provider or host identity.
    """

    return component_identity(value, config=config, code=code).digest()


__all__ = [
    "RSI_IDENTITY_KIND",
    "RSI_IDENTITY_SCHEMA_VERSION",
    "ComponentIdentity",
    "RSIIdentityError",
    "component_fingerprint",
    "component_identity",
]
