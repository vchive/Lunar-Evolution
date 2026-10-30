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
import threading
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, NoReturn

from . import producer_python_runtime as declared_runtime
from . import producer_python_runtime_tree as closed_runtime
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
    PythonRuntimeDirectory,
    PythonRuntimeFile,
    PythonRuntimeFileDeclaration,
    PythonRuntimeImportRoot,
    PythonRuntimeManifest,
    PythonRuntimeRoot,
    PythonRuntimeTarget,
    parse_python_runtime_manifest,
)
from .producer_python_runtime_tree import (
    PythonRuntimeTreeDirectory,
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
    if type(value) is not bytes and type(value) is not str:
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
    if type(value) is not int and type(value) is not float:
        _fail("deadline_invalid")
    try:
        result = float(value)
    except (ValueError, OverflowError):
        _fail("deadline_invalid")
    if not math.isfinite(result) or result <= 0:
        _fail("deadline_invalid")
    return result


def _digest_without(value: Mapping[str, object], field: str) -> str:
    body = dict(value)
    body.pop(field, None)
    return hashlib.sha256(_canonical(body)).hexdigest()


# Runtime manifests and closed-tree manifests are immutable DTO graphs.  A binding
# serializer still has to revalidate its caller-owned graph on every public call,
# because ``object.__setattr__`` can deliberately tamper with a frozen DTO.  The
# old path reparsed and reserialized the same large tree for every lifecycle poll.
# Keep a bounded, process-local cache of *validated projections* keyed by an exact
# structural token.  The token builder only walks the known DTO classes and plain
# scalar/tuple values; callback-bearing subclasses return ``None`` and therefore
# take the unchanged full refusal path before any user code is touched.
# Keep this deliberately small: a detached manifest/tree may be megabytes, and
# retaining the source plus validated projection is more expensive than a miss.
_VALIDATION_CACHE_LIMIT = 16
_VALIDATION_CACHE_LOCK = threading.RLock()
_RUNTIME_VALIDATION_CACHE: dict[int, tuple[object, tuple[object, ...], PythonRuntimeManifest]] = {}
_TREE_VALIDATION_CACHE: dict[int, tuple[object, tuple[object, ...], PythonRuntimeTreeManifest]] = {}


def _safe_validation_token(value: object) -> tuple[object, ...] | None:
    """Build a callback-free immutable token for runtime/tree DTO graphs.

    This is intentionally stricter than the DTO validators: unknown objects and
    subclasses are not tokenizable, so they cannot gain a cache hit.  Returning
    ``None`` merely disables the optimization; the existing validators then retain
    their exact refusal order and callback protection.
    """

    dto_types = (
        PythonRuntimeTarget, PythonRuntimeFileDeclaration, PythonRuntimeImportRoot,
        PythonRuntimeDirectory, PythonRuntimeRoot, PythonRuntimeFile, PythonRuntimeManifest,
        PythonRuntimeTreeDirectory, PythonRuntimeTreeManifest,
    )
    remaining = 100_000

    def walk(item: object, depth: int = 0) -> tuple[object, ...] | None:
        nonlocal remaining
        remaining -= 1
        if depth > 48 or remaining < 0:
            return None
        item_type = type(item)
        if (item is None or item_type is str or item_type is int or item_type is float
                or item_type is bool or item_type is bytes):
            return (item_type, item)
        if item_type is tuple:
            parts: list[tuple[object, ...]] = []
            for child in item:
                token = walk(child, depth + 1)
                if token is None:
                    return None
                parts.append(token)
            return (tuple, tuple(parts))
        if not any(item_type is approved for approved in dto_types):
            return None
        parts = []
        try:
            for field in fields(item_type):
                # All tokenizable classes are exact frozen DTOs.  Bypass an
                # instance-level ``__getattribute__`` replacement so the fast
                # path itself never invokes caller code.
                token = walk(object.__getattribute__(item, field.name), depth + 1)
                if token is None:
                    return None
                parts.append((field.name, token))
        except (AttributeError, TypeError, ValueError):
            return None
        return (item_type, tuple(parts))

    return walk(value)


def _cached_validation(
    cache: dict[int, tuple[object, tuple[object, ...], object]],
    source: object,
    token: tuple[object, ...] | None,
) -> object | None:
    if token is None:
        return None
    with _VALIDATION_CACHE_LOCK:
        entry = cache.get(id(source))
        if entry is not None and entry[0] is source and entry[1] == token:
            return entry[2]
    return None


def _remember_validation(
    cache: dict[int, tuple[object, tuple[object, ...], object]],
    source: object,
    token: tuple[object, ...] | None,
    parsed: object,
) -> None:
    if token is None:
        return
    with _VALIDATION_CACHE_LOCK:
        cache[id(source)] = (source, token, parsed)
        if len(cache) > _VALIDATION_CACHE_LIMIT:
            cache.pop(next(iter(cache)))


def _reparse_runtime(manifest: PythonRuntimeManifest) -> PythonRuntimeManifest:
    if type(manifest) is not PythonRuntimeManifest:
        _fail("runtime_manifest_type_invalid")
    token = _safe_validation_token(manifest)
    cached = _cached_validation(_RUNTIME_VALIDATION_CACHE, manifest, token)
    if cached is not None:
        return cached  # type: ignore[return-value]
    try:
        # Feature177's exact bounded shape gate refuses callback-bearing nested
        # collections before the original validator or serialization sees them.
        closed_runtime._declared_shape(manifest)
        manifest.__post_init__()
        parsed = parse_python_runtime_manifest(manifest.to_json())
    except Exception as exc:
        if isinstance(exc, PythonProducerBindingError):
            raise
        _fail("runtime_manifest_invalid")
    if parsed != manifest:
        _fail("runtime_manifest_drift")
    _sha(parsed.manifest_sha256, "runtime_manifest_digest_invalid")
    _remember_validation(_RUNTIME_VALIDATION_CACHE, manifest, token, parsed)
    return parsed


def _fresh_runtime_helpers_current() -> bool:
    """Reuse only this call's unescaped parse under the original pure machinery.

    These finite pins are compatibility guards, not filesystem or launch
    authority. A replaced helper, DTO implementation, codec or module alias
    selects the existing caller-DTO reparse path instead of trusting a digest.
    """
    if (_FRESH_RUNTIME_FUNCTION_PINS is not _FRESH_RUNTIME_ORIGINAL_FUNCTION_PINS
            or _FRESH_RUNTIME_VALUE_PINS is not _FRESH_RUNTIME_ORIGINAL_VALUE_PINS
            or _FRESH_RUNTIME_CLASS_PINS is not _FRESH_RUNTIME_ORIGINAL_CLASS_PINS
            or _FRESH_RUNTIME_ROLE_SLOTS is not _FRESH_RUNTIME_ORIGINAL_ROLE_SLOTS
            or _fresh_runtime_helpers_current.__code__ is not _FRESH_RUNTIME_GUARD_CODE
            or _fresh_runtime_helpers_current.__defaults__ is not _FRESH_RUNTIME_GUARD_DEFAULTS
            or _fresh_runtime_helpers_current.__kwdefaults__ is not _FRESH_RUNTIME_GUARD_KWDEFAULTS):
        return False
    for namespace, name, original in _FRESH_RUNTIME_VALUE_PINS:
        if namespace.get(name) is not original:
            return False
    for namespace, name, descriptor, function, code, defaults, kwdefaults, kwitems, closure, captures in (
            _FRESH_RUNTIME_FUNCTION_PINS):
        if (namespace.get(name) is not descriptor or function.__code__ is not code
                or function.__defaults__ is not defaults or function.__kwdefaults__ is not kwdefaults
                or function.__closure__ is not closure
                or any(cell.cell_contents is not original
                       for cell, original in zip(closure or (), captures, strict=True))
                or (kwdefaults is not None and (
                    len(kwdefaults) != len(kwitems)
                    or any(key not in kwdefaults or kwdefaults[key] is not item for key, item in kwitems)))):
            return False
    for namespace, original in _FRESH_RUNTIME_CLASS_PINS:
        if len(namespace) != len(original) or any(namespace.get(name) is not item for name, item in original):
            return False
    if (len(declared_runtime._ROLE_SLOTS) != len(_FRESH_RUNTIME_ROLE_SLOTS)
            or any(declared_runtime._ROLE_SLOTS.get(name) is not item for name, item in _FRESH_RUNTIME_ROLE_SLOTS)):
        return False
    decoder = json._default_decoder
    if decoder is not _FRESH_RUNTIME_DECODER:
        return False
    namespace = object.__getattribute__(decoder, "__dict__")
    return ("decode" not in namespace and "raw_decode" not in namespace
            and namespace.get("scan_once") is _FRESH_RUNTIME_SCAN_ONCE)


def _reparse_tree(tree: PythonRuntimeTreeManifest) -> PythonRuntimeTreeManifest:
    if type(tree) is not PythonRuntimeTreeManifest:
        _fail("runtime_tree_type_invalid")
    token = _safe_validation_token(tree)
    cached = _cached_validation(_TREE_VALIDATION_CACHE, tree, token)
    if cached is not None:
        return cached  # type: ignore[return-value]
    try:
        tree.__post_init__()
        parsed = parse_python_runtime_tree_manifest(tree.to_json())
    except Exception as exc:
        if isinstance(exc, PythonProducerBindingError):
            raise
        _fail("runtime_tree_invalid")
    if parsed != tree:
        _fail("runtime_tree_drift")
    _sha(parsed.tree_sha256, "runtime_tree_digest_invalid")
    _remember_validation(_TREE_VALIDATION_CACHE, tree, token, parsed)
    return parsed


_LAUNCH_STAT_FIELDS = frozenset({
    "executable_size", "executable_device", "executable_inode", "executable_mtime_ns",
    "executable_ctime_ns", "request_timeout_seconds", "max_requests", "output_max_bytes",
    "wall_timeout_seconds",
})


def _launch_shape(value: ProducerLaunchIntent | ProducerLaunchAttestation, *, attestation: bool) -> None:
    # Both DTOs predate the exact-shape Python boundary.  Bound their scalar
    # fields and argv before to_dict() or their isinstance-based validators.
    from dataclasses import fields

    for field in fields(type(value)):
        item = getattr(value, field.name)
        if field.name == "argv":
            if type(item) is not tuple or not 1 <= len(item) <= 64:
                _fail("intent_shape_invalid")
            if any(type(arg) is not str or not 1 <= len(arg) <= 4096 for arg in item):
                _fail("intent_shape_invalid")
        elif field.name in _LAUNCH_STAT_FIELDS:
            if type(item) is not int or not 0 <= item <= 2**64 - 1:
                _fail("attestation_shape_invalid" if attestation else "intent_shape_invalid")
        elif type(item) is not str or not 1 <= len(item) <= 4096:
            _fail("attestation_shape_invalid" if attestation else "intent_shape_invalid")


def _reparse_intent(intent: ProducerLaunchIntent) -> ProducerLaunchIntent:
    if type(intent) is not ProducerLaunchIntent:
        _fail("intent_type_invalid")
    _launch_shape(intent, attestation=False)
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
    _launch_shape(attestation, attestation=True)
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
        _budget_shape(budget.state)
        try:
            state = budget.to_dict()
        except Exception as exc:
            raise PythonProducerBindingError("budget_invalid") from exc
        planned = state.get("planned")
    elif type(budget) is dict:
        _budget_shape(budget)
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


def _budget_shape(value: object, *, depth: int = 0) -> None:
    """Refuse callback-bearing values before deepcopy or budget validation."""
    if type(value) is not dict or depth > 1 or len(value) > 32:
        _fail("budget_shape_invalid")
    for key, item in value.items():
        if type(key) is not str or not 1 <= len(key) <= 128:
            _fail("budget_shape_invalid")
        if type(item) is dict:
            _budget_shape(item, depth=depth + 1)
        elif (item is not None and type(item) is not int and type(item) is not float
                or type(item) is int and item.bit_length() > 4096):
            _fail("budget_shape_invalid")


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
        self._validate_header()
        manifest = _reparse_runtime(self.runtime_manifest)
        tree = _reparse_tree(self.runtime_tree)
        intent = _reparse_intent(self.intent)
        attestation = _reparse_attestation(self.attestation)
        self._validate_join(manifest, tree, intent, attestation)
        self._validate_digest()

    def _validate_header(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != PYTHON_PRODUCER_BINDING_SCHEMA_VERSION:
            _fail("schema_invalid")
        if type(self.protocol) is not str or self.protocol != PYTHON_PRODUCER_BINDING_PROTOCOL:
            _fail("protocol_invalid")
        _deadline(self.deadline_unix)

    def _validate_join(
        self, manifest: PythonRuntimeManifest, tree: PythonRuntimeTreeManifest,
        intent: ProducerLaunchIntent, attestation: ProducerLaunchAttestation,
    ) -> None:
        if tree.declared_manifest != manifest:
            _fail("runtime_tree_manifest_mismatch")
        if tree.declared_manifest.target != manifest.target:
            _fail("runtime_target_mismatch")
        try:
            verify_producer_launch_attestation(intent, attestation)
        except ProducerLaunchError as exc:
            raise PythonProducerBindingError("attestation_intent_mismatch") from exc
        if type(self.fixture_case) is not str or self.fixture_case not in _FIXTURE_CASES:
            _fail("fixture_case_invalid")
        if type(self.broker_policy) is not str or self.broker_policy not in _BROKER_POLICIES:
            _fail("broker_policy_invalid")
        deadline = _deadline(self.deadline_unix)
        _positive_int(self.request_budget, "request_budget_invalid")
        _positive_int(self.output_max_bytes, "output_budget_invalid")
        _positive_int(self.wall_timeout_seconds, "wall_timeout_invalid")
        if self.request_budget != intent.max_requests:
            _fail("request_budget_mismatch")
        if self.output_max_bytes != intent.output_max_bytes:
            _fail("output_budget_mismatch")
        if self.wall_timeout_seconds != intent.wall_timeout_seconds:
            _fail("wall_timeout_mismatch")
        if deadline < float(self.wall_timeout_seconds):
            _fail("deadline_wall_timeout_invalid")
        interpreter = _interpreter(manifest)
        if (
            # The native launch intent labels its own producer root (currently the
            # fixed ``producer-root`` label); the runtime inventory may use a
            # different logical root label.  The portable relative path and all
            # observed executable identity pins are the binding authority.
            intent.executable_relative != interpreter.relative_path
            or intent.executable_sha256 != interpreter.sha256
            or intent.executable_size != interpreter.size
            or intent.executable_device != interpreter.device
            or intent.executable_inode != interpreter.inode
            or intent.executable_mtime_ns != interpreter.mtime_ns
            or intent.executable_ctime_ns != interpreter.ctime_ns
        ):
            _fail("interpreter_identity_mismatch")
        if attestation.intent_sha256 != intent.intent_sha256:
            _fail("attestation_intent_mismatch")

    def _validate_digest(self) -> None:
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
        # Do not turn a fresh parse into a reusable caller-DTO assertion. Its
        # exact structural token lives only in this operation, and any unknown
        # or replaced pure seam keeps the original reparse behavior.
        fresh_runtime = (
            _fresh_runtime_helpers_current is _FRESH_RUNTIME_GUARD
            and _fresh_runtime_helpers_current.__code__ is _FRESH_RUNTIME_GUARD_CODE
            and _fresh_runtime_helpers_current()
        )
        runtime_manifest = parse_python_runtime_manifest(_canonical(raw["runtime_manifest"]))
        runtime_token = _safe_validation_token(runtime_manifest) if fresh_runtime else None
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
        # The tree was parsed and fully validated above from strict JSON. It
        # has never escaped this operation. Keep the public constructor's full
        # caller-DTO reparse gate; only this parser-local assembly reuses fresh
        # material while retaining runtime/launch checks in their old order.
        result = object.__new__(PythonProducerBinding)
        values = {
            "runtime_manifest": runtime_manifest, "runtime_tree": runtime_tree,
            "intent": intent, "attestation": attestation, "fixture_case": raw["fixture_case"],
            "deadline_unix": _deadline(raw["deadline_unix"]),
            "request_budget": _positive_int(raw["request_budget"], "request_budget_invalid"),
            "output_max_bytes": _positive_int(raw["output_max_bytes"], "output_budget_invalid"),
            "wall_timeout_seconds": _positive_int(raw["wall_timeout_seconds"], "wall_timeout_invalid"),
            "broker_policy": raw["broker_policy"], "binding_sha256": raw["binding_sha256"],
            "schema_version": raw["schema_version"], "protocol": raw["protocol"],
        }
        for name, item in values.items():
            object.__setattr__(result, name, item)
        result._validate_header()
        if (runtime_token is not None
                and _fresh_runtime_helpers_current is _FRESH_RUNTIME_GUARD
                and _fresh_runtime_helpers_current.__code__ is _FRESH_RUNTIME_GUARD_CODE
                and _fresh_runtime_helpers_current()
                and _safe_validation_token(runtime_manifest) == runtime_token):
            # This exact DTO was already fully validated by the runtime parser.
            # Keep the stricter closed-tree shape gate in its previous position;
            # only the second runtime validation/serialization/parse is omitted.
            try:
                closed_runtime._declared_shape(runtime_manifest)
            except Exception as exc:
                if isinstance(exc, PythonProducerBindingError):
                    raise
                _fail("runtime_manifest_invalid")
            _sha(runtime_manifest.manifest_sha256, "runtime_manifest_digest_invalid")
            manifest = runtime_manifest
        else:
            manifest = _reparse_runtime(runtime_manifest)
        _sha(runtime_tree.tree_sha256, "runtime_tree_digest_invalid")
        checked_intent = _reparse_intent(intent)
        checked_attestation = _reparse_attestation(attestation)
        result._validate_join(manifest, runtime_tree, checked_intent, checked_attestation)
        result._validate_digest()
        # Keep the previous parser-local canonical wire comparison, without
        # re-entering the public caller-DTO validator before the result escapes.
        canonical = _canonical(result._to_dict_unchecked())
        if (canonical != value if type(value) is bytes else canonical.decode("utf-8") != value):
            _fail("noncanonical_json")
        return result
    except PythonProducerBindingError:
        raise
    except (ProducerLaunchError, TypeError, ValueError, AttributeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise PythonProducerBindingError("schema_invalid") from exc


def _pin_fresh_runtime_helpers():
    """Capture the small pure runtime parse/validation graph once at import."""
    functions, values, classes = [], [], []

    def capture(namespace, names):
        for name in names:
            descriptor = namespace[name]
            function = descriptor.__func__ if type(descriptor) in (staticmethod, classmethod) else descriptor
            if hasattr(function, "__code__"):
                functions.append((namespace, name, descriptor, function, function.__code__,
                                  function.__defaults__, function.__kwdefaults__,
                                  tuple((function.__kwdefaults__ or {}).items()), function.__closure__,
                                  tuple(cell.cell_contents for cell in (function.__closure__ or ()))))
            else:
                values.append((namespace, name, descriptor))

    capture(globals(), (
        "declared_runtime", "closed_runtime", "json", "hashlib", "fields", "_canonical", "_sha",
        "_safe_validation_token", "_reparse_runtime", "parse_python_runtime_manifest",
        "PythonRuntimeDirectory", "PythonRuntimeFile", "PythonRuntimeFileDeclaration",
        "PythonRuntimeImportRoot", "PythonRuntimeManifest", "PythonRuntimeRoot", "PythonRuntimeTarget",
    ))
    runtime_names = (
        "_fail", "_canonical", "_digest", "_integer", "_mode", "_label", "_sha", "_path", "_policy",
        "_slot_digests", "_file_key", "_import_key", "_sequence", "_root_paths", "_declarations",
        "_directory_paths", "_validate_manifest", "_object", "_list", "_target", "_declaration",
        "_pairs", "parse_python_runtime_manifest", "json", "hashlib", "Path", "Mapping", "Sequence",
        "PythonRuntimeError", "PythonRuntimeDirectory", "PythonRuntimeFile", "PythonRuntimeFileDeclaration",
        "PythonRuntimeImportRoot", "PythonRuntimeManifest", "PythonRuntimeRoot", "PythonRuntimeTarget",
        "_DTO", "_LABEL", "_SHA", "_PROTOCOL", "_SCOPE", "_SLOTS", "_ROLE_SLOTS", "_MANIFEST_FIELDS",
        "_MAX_IMPORT_ROOTS", "_MAX_PATH_BYTES", "_MAX_PATH_PARTS", "_MAX_DIRECTORY_PINS",
        "MAX_PYTHON_RUNTIME_ROOTS", "MAX_PYTHON_RUNTIME_FILES", "MAX_PYTHON_RUNTIME_FILE_BYTES",
        "MAX_PYTHON_RUNTIME_TOTAL_BYTES", "MAX_PYTHON_RUNTIME_MANIFEST_BYTES",
    )
    capture(vars(declared_runtime), runtime_names)
    for kind in (declared_runtime._DTO, PythonRuntimeTarget, PythonRuntimeFileDeclaration,
                 PythonRuntimeImportRoot, PythonRuntimeDirectory, PythonRuntimeRoot,
                 PythonRuntimeFile, PythonRuntimeManifest):
        namespace = vars(kind)
        classes.append((namespace, tuple(namespace.items())))
        capture(namespace, tuple(name for name, value in namespace.items() if hasattr(value, "__code__")))
    capture(vars(closed_runtime), (
        "declared", "_declared_shape", "_collection", "_text", "_target_text", "_declaration_text",
        "_relative", "_sha", "_fail", "MAX_PYTHON_RUNTIME_TREE_ENTRIES", "MAX_PYTHON_RUNTIME_TREE_DEPTH",
        "_MAX_ROLE_TEXT", "_TARGET_TEXT_LIMITS",
    ))
    capture(vars(json), ("loads", "dumps", "JSONDecoder", "JSONEncoder", "decoder", "encoder"))
    for kind, names in ((json.JSONDecoder, ("__init__", "decode", "raw_decode")),
                        (json.JSONEncoder, ("__init__", "encode", "iterencode"))):
        capture(vars(kind), names)
    capture(vars(json.encoder), ("_make_iterencode", "c_make_encoder", "encode_basestring", "encode_basestring_ascii"))
    capture(vars(json.decoder), ("scanstring", "WHITESPACE", "WHITESPACE_STR"))
    capture(vars(hashlib), ("sha256",))
    return tuple(functions), tuple(values), tuple(classes)


_FRESH_RUNTIME_GUARD = _fresh_runtime_helpers_current
_FRESH_RUNTIME_GUARD_CODE = _FRESH_RUNTIME_GUARD.__code__
_FRESH_RUNTIME_GUARD_DEFAULTS = _FRESH_RUNTIME_GUARD.__defaults__
_FRESH_RUNTIME_GUARD_KWDEFAULTS = _FRESH_RUNTIME_GUARD.__kwdefaults__
_FRESH_RUNTIME_FUNCTION_PINS, _FRESH_RUNTIME_VALUE_PINS, _FRESH_RUNTIME_CLASS_PINS = _pin_fresh_runtime_helpers()
_FRESH_RUNTIME_ROLE_SLOTS = tuple(declared_runtime._ROLE_SLOTS.items())
_FRESH_RUNTIME_ORIGINAL_FUNCTION_PINS = _FRESH_RUNTIME_FUNCTION_PINS
_FRESH_RUNTIME_ORIGINAL_VALUE_PINS = _FRESH_RUNTIME_VALUE_PINS
_FRESH_RUNTIME_ORIGINAL_CLASS_PINS = _FRESH_RUNTIME_CLASS_PINS
_FRESH_RUNTIME_ORIGINAL_ROLE_SLOTS = _FRESH_RUNTIME_ROLE_SLOTS
_FRESH_RUNTIME_DECODER = json._default_decoder
_FRESH_RUNTIME_SCAN_ONCE = _FRESH_RUNTIME_DECODER.scan_once


__all__ = [
    "MAX_PYTHON_PRODUCER_BINDING_BYTES", "PYTHON_PRODUCER_BINDING_PROTOCOL",
    "PYTHON_PRODUCER_BINDING_SCHEMA_VERSION", "PythonProducerBinding",
    "PythonProducerBindingError", "build_python_producer_binding",
    "parse_python_producer_binding",
]
