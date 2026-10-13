"""Read-only composition of original Python and native RSI scheduler inputs.

This boundary requires an independently retained producer checkpoint. It never derives a
checkpoint from the sidecar it is inspecting. Runtime inventory and closed-tree files are
rechecked, while bootstrap installation checks remain owned by the native input validator.
Returned descriptors and plans are observations, not authority to launch or publish a worker.
No producer, evaluator, request provider, budget, ledger, or admission state is accessed here.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn

from .algorithm import (
    AlgorithmProblemContract,
    ConstraintSpec,
    EvolutionSpec,
    InputSpec,
    MetricSpec,
    ObjectiveSpec,
    OutputSpec,
    SourceCheckSpec,
)
from .candidate_evaluation_spec import canonical_json, strict_json
from .native_bootstrap import NativeBootstrapArtifact
from .producer_bootstrap import TrustedBootstrapDescriptor
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_handoff import BundleGroup
from .producer_launcher import ProducerLaunchAttestation, ProducerLaunchIntent
from .producer_python_runtime import (
    PythonRuntimeDirectory,
    PythonRuntimeFile,
    PythonRuntimeFileDeclaration,
    PythonRuntimeImportRoot,
    PythonRuntimeManifest,
    PythonRuntimeRoot,
    PythonRuntimeTarget,
)
from .producer_python_runtime_tree import (
    PythonRuntimeTreeDirectory,
    PythonRuntimeTreeManifest,
    verify_python_runtime_tree_manifest,
)
from .python_producer_binding import PythonProducerBinding, parse_python_producer_binding
from .python_producer_binding_store import (
    PythonProducerBindingSidecar,
    _validated_sidecar_pin,
    read_python_producer_binding_sidecar,
)
from .python_producer_checkpoint import PythonProducerCheckpointBinding
from .rsi_gateway import SolverRequest
from .rsi_identity import component_fingerprint
from .rsi_learning import MAX_RSI_RECORD_BYTES, MemoryItem, MemorySnapshot, RSILearningError
from .rsi_native_candidate import select_native_candidate
from .rsi_native_inputs import NativeRSIInputDescriptor, validate_native_rsi_launch_inputs
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_native_scheduler import NativeRSISchedulerContext, _assert_plan_binding

PYTHON_RSI_SCHEDULER_INPUT_PROTOCOL = "lunar-python-rsi-scheduler-inputs-v1"
_DTO_TYPES = (
    AlgorithmProblemContract, ConstraintSpec, EvolutionSpec, InputSpec, MetricSpec,
    ObjectiveSpec, OutputSpec, SourceCheckSpec, BundleGroup, ProducerLaunchIntent,
    ProducerLaunchAttestation, TrustedBootstrapDescriptor, PythonProducerBinding,
    PythonProducerBindingSidecar, PythonRuntimeDirectory, PythonRuntimeFile,
    PythonRuntimeFileDeclaration, PythonRuntimeImportRoot, PythonRuntimeManifest,
    PythonRuntimeRoot, PythonRuntimeTarget, PythonRuntimeTreeDirectory,
    PythonRuntimeTreeManifest, SolverRequest, MemorySnapshot, MemoryItem,
)


class PythonRSISchedulerInputError(RSILearningError):
    """Fixed refusal codes without caller paths, credentials, or child output."""

    def __init__(self, code: str) -> None:
        self.code = "rsi_python_scheduler_inputs_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonRSISchedulerInputError(code)


def _shape(value: object, *, depth: int = 0, remaining: list[int] | None = None) -> None:
    """Bound exact DTOs and detached collections before invoking older serializers."""
    if remaining is None:
        remaining = [100_000]
    remaining[0] -= 1
    if depth > 48 or remaining[0] < 0:
        _fail("shape_invalid")
    kind = type(value)
    if value is None or kind is bool:
        return
    if kind is str:
        if len(value) > 128 * 1024:
            _fail("shape_invalid")
        return
    if kind is int:
        if value.bit_length() > 4096:
            _fail("shape_invalid")
        return
    if kind is float:
        if not math.isfinite(value):
            _fail("shape_invalid")
        return
    if kind is dict:
        if len(value) > 10_000 or any(type(key) is not str for key in value):
            _fail("shape_invalid")
        # Keys are untrusted input too.  Visit them before serializers so their size contributes
        # to the same bounded shape walk and custom string-like objects cannot be substituted.
        for key in value:
            _shape(key, depth=depth + 1, remaining=remaining)
        items = value.values()
    elif kind in {list, tuple, frozenset}:
        if len(value) > 10_000:
            _fail("shape_invalid")
        items = value
    elif kind in _DTO_TYPES:
        declared = fields(value)
        try:
            attributes = object.__getattribute__(value, "__dict__")
        except AttributeError:
            pass
        else:
            # Frozen non-slotted DTOs can still be modified through object.__setattr__, including
            # an instance ``to_dict`` method that would run before older parsers see the value.
            if (type(attributes) is not dict
                    or any(type(key) is not str for key in attributes)
                    or set(attributes) - {item.name for item in declared}):
                _fail("shape_invalid")
        try:
            items = [object.__getattribute__(value, item.name) for item in declared]
        except AttributeError as exc:
            raise PythonRSISchedulerInputError("shape_invalid") from exc
    else:
        _fail("shape_invalid")
    for item in items:
        _shape(item, depth=depth + 1, remaining=remaining)


def _path(value: object) -> Path:
    if type(value) not in {str, type(Path())}:
        _fail("path_invalid")
    try:
        path = Path(value).expanduser().absolute()
        text = path.as_posix()
        # Do not resolve links or parent traversal before the retained validators read.
        if ".." in path.parts or "\x00" in text or len(text.encode()) > 4096:
            _fail("path_invalid")
        return path
    except PythonRSISchedulerInputError:
        raise
    except (OSError, TypeError, ValueError, RuntimeError, UnicodeError) as exc:
        raise PythonRSISchedulerInputError("path_invalid") from exc


def _checkpoint(
    value: object, *, retained_pin: MappingProxyType | None = None,
) -> PythonProducerCheckpointBinding:
    if type(value) is not PythonProducerCheckpointBinding:
        _fail("checkpoint_invalid")
    try:
        pin = value.sidecar_pin
        schema_version, protocol = value.schema_version, value.protocol
        binding_sha256, run_id, journal_id = value.binding_sha256, value.run_id, value.journal_id
    except AttributeError as exc:
        raise PythonRSISchedulerInputError("checkpoint_invalid") from exc
    if type(pin) is dict:
        pin_wire = dict(pin)
    elif type(pin) is MappingProxyType and pin is retained_pin:
        # Only the proxy retained by this context is trusted.  An arbitrary proxy may
        # wrap a mapping whose __iter__/__getitem__ callbacks execute during ``dict(pin)``.
        pin_wire = dict(pin)
    else:
        _fail("checkpoint_invalid")
    wire = {
        "schema_version": schema_version, "protocol": protocol,
        "binding_sha256": binding_sha256, "run_id": run_id,
        "journal_id": journal_id, "sidecar_pin": pin_wire,
    }
    _shape(wire)
    try:
        parsed = PythonProducerCheckpointBinding.from_dict(wire)
        # Retain a separate, immutable pin; never stat or mint a proof from current evidence.
        frozen_pin = MappingProxyType(dict(parsed.sidecar_pin))
        return replace(parsed, sidecar_pin=frozen_pin)
    except Exception as exc:
        raise PythonRSISchedulerInputError("checkpoint_invalid") from exc


def _sidecar(value: object, proof: PythonProducerCheckpointBinding) -> PythonProducerBindingSidecar:
    if type(value) is not PythonProducerBindingSidecar:
        _fail("sidecar_invalid")
    _shape(value)
    try:
        binding = parse_python_producer_binding(value.binding.to_json())
        _validated_sidecar_pin(value, binding)
        parsed = replace(value, binding=binding)
        proof.validate_sidecar(parsed)
        raw = binding.to_json()
        if len(raw) != parsed.raw_size or hashlib.sha256(raw).hexdigest() != parsed.raw_sha256:
            _fail("sidecar_invalid")
        return parsed
    except PythonRSISchedulerInputError:
        raise
    except Exception as exc:
        raise PythonRSISchedulerInputError("sidecar_invalid") from exc


def _broker(value: object) -> ProducerBrokerConfig:
    """Copy the host-only broker config and bind its mutable headers by digest.

    The scheduler input context is read-only. A caller-owned headers dictionary must not
    remain aliased into a returned child preview, while later mutation of the original
    context must still be detected by ``_projection`` before any plan is rebuilt.
    """
    if type(value) is not ProducerBrokerConfig:
        _fail("broker_invalid")
    try:
        endpoint = value.endpoint
        headers = dict(value.headers)
    except (AttributeError, TypeError, ValueError) as exc:
        raise PythonRSISchedulerInputError("broker_invalid") from exc
    if (type(endpoint) is not str or not endpoint or "\x00" in endpoint
            or type(value.headers) is not dict
            or any(type(key) is not str or type(item) is not str for key, item in headers.items())):
        _fail("broker_invalid")
    try:
        return ProducerBrokerConfig(endpoint, headers)
    except Exception as exc:
        raise PythonRSISchedulerInputError("broker_invalid") from exc


def _native(value: object, binding: PythonProducerBinding) -> NativeRSISchedulerContext:
    if type(value) is not NativeRSISchedulerContext:
        _fail("native_context_invalid")
    for item in (value.intent, value.attestation, value.contract, value.groups):
        _shape(item)
    broker = _broker(value.broker_config)
    if (type(value.intent) is not ProducerLaunchIntent
            or type(value.attestation) is not ProducerLaunchAttestation
            or type(value.contract) is not AlgorithmProblemContract
            or type(value.groups) is not tuple or not value.groups
            or any(type(group) is not BundleGroup for group in value.groups)):
        _fail("native_context_invalid")
    artifact = value.artifact
    if type(artifact) is not NativeBootstrapArtifact:
        _fail("bootstrap_invalid")
    _shape(artifact.descriptor)
    if type(artifact.descriptor) is not TrustedBootstrapDescriptor:
        _fail("bootstrap_invalid")
    for item in (
        artifact.source_sha256, artifact.artifact_sha256, artifact.compiler,
        artifact.platform_execution_mode, artifact.allowlist_id, value.evaluator_kind,
        value.evaluator_fingerprint, value.runner_fingerprint, value.dependency_sha256,
        value.environment_sha256,
    ):
        if type(item) is not str or not item or len(item) > 4096:
            _fail("native_context_invalid")
    try:
        artifact.descriptor.__post_init__()
        if (value.intent != binding.intent or value.attestation != binding.attestation
                or value.intent.digest() != binding.intent_sha256
                or value.attestation.digest() != binding.attestation_sha256):
            _fail("launch_binding_mismatch")
        contract = AlgorithmProblemContract.from_dict(value.contract.to_dict())
        if (contract.digest() != binding.contract_sha256
                or value.evaluator_kind != binding.evaluator_kind
                or value.evaluator_fingerprint != binding.evaluator_fingerprint
                or value.runner_fingerprint != binding.intent.runner_fingerprint
                or value.dependency_sha256 != binding.dependency_sha256
                or value.environment_sha256 != binding.environment_sha256):
            _fail("native_identity_mismatch")
        root = next(
            item for item in binding.runtime_manifest.roots
            if item.label == binding.interpreter.root_label
        )
        if _path(value.producer_root) != _path(root.path):
            _fail("producer_root_mismatch")
        if (artifact.artifact_sha256 != artifact.descriptor.bootstrap_sha256
                or artifact.allowlist_id != artifact.descriptor.allowlist_id
                or artifact.platform_execution_mode != artifact.descriptor.platform_execution_mode):
            _fail("bootstrap_invalid")
        # The legacy strategy, broker, control and ledger are intentionally not invoked or
        # cloned. This seam observes only inputs; execution wiring has its own fingerprint.
        return replace(
            value, workspace=_path(value.workspace), producer_root=_path(value.producer_root),
            intent=binding.intent, attestation=binding.attestation, contract=contract,
            artifact=replace(artifact, path=_path(artifact.path)),
            broker_config=broker,
            groups=tuple(BundleGroup(group.bundle_id, group.entrypoint, group.material_paths)
                         for group in value.groups),
        )
    except PythonRSISchedulerInputError:
        raise
    except Exception as exc:
        raise PythonRSISchedulerInputError("native_context_invalid") from exc


def _projection(
    native: NativeRSISchedulerContext, sidecar: PythonProducerBindingSidecar,
    proof: PythonProducerCheckpointBinding,
) -> dict[str, Any]:
    artifact = native.artifact
    return {
        "protocol": PYTHON_RSI_SCHEDULER_INPUT_PROTOCOL,
        "production_admission": False,
        "workspace": str(native.workspace), "producer_root": str(native.producer_root),
        "producer_binding_sha256": sidecar.binding.binding_sha256,
        "original_producer_checkpoint_sha256": hashlib.sha256(proof.to_json()).hexdigest(),
        "intent_sha256": sidecar.binding.intent_sha256,
        "attestation_sha256": sidecar.binding.attestation_sha256,
        "runtime_manifest_sha256": sidecar.binding.runtime_manifest_sha256,
        "runtime_tree_sha256": sidecar.binding.runtime_tree_sha256,
        "original_deadline_unix": sidecar.binding.deadline_unix,
        "bootstrap_path": str(artifact.path),
        "bootstrap_descriptor_sha256": artifact.descriptor.digest(),
        "bootstrap_artifact_sha256": artifact.artifact_sha256,
        "bootstrap_source_sha256": artifact.source_sha256,
        "bootstrap_compiler": artifact.compiler,
        "bootstrap_platform_execution_mode": artifact.platform_execution_mode,
        "bootstrap_allowlist_id": artifact.allowlist_id,
        "broker_endpoint": native.broker_config.endpoint,
        "broker_headers_sha256": hashlib.sha256(canonical_json(
            native.broker_config.headers, maximum=MAX_RSI_RECORD_BYTES,
        )).hexdigest(),
        "contract_sha256": native.contract.digest(),
        "groups": [group.to_dict() for group in native.groups],
        "evaluator_kind": native.evaluator_kind,
        "evaluator_fingerprint": native.evaluator_fingerprint,
        "runner_fingerprint": native.runner_fingerprint,
        "dependency_sha256": native.dependency_sha256,
        "environment_sha256": native.environment_sha256,
        "candidate_selector_id": "native-selector-v1",
        "candidate_selector_sha256": component_fingerprint(select_native_candidate),
    }


@dataclass(frozen=True, slots=True)
class PythonRSISchedulerInputContext:
    """Immutable original proof and explicit native inputs, with no execution authority.

    The caller must supply the checkpoint retained independently by its controller. Its pin
    mapping is copied and frozen. Plan identities are frozen as a canonical projection; later
    mutation of nested caller DTOs refuses validation rather than refreshing that projection.
    """

    native_context: NativeRSISchedulerContext
    producer_sidecar: PythonProducerBindingSidecar
    original_producer_checkpoint: PythonProducerCheckpointBinding
    _projection_json: bytes = field(init=False, repr=False, compare=False)
    _retained_sidecar_pin: MappingProxyType = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        proof = _checkpoint(self.original_producer_checkpoint)
        sidecar = _sidecar(self.producer_sidecar, proof)
        native = _native(self.native_context, sidecar.binding)
        object.__setattr__(self, "original_producer_checkpoint", proof)
        object.__setattr__(self, "_retained_sidecar_pin", proof.sidecar_pin)
        object.__setattr__(self, "producer_sidecar", sidecar)
        object.__setattr__(self, "_projection_json", canonical_json(
            _projection(native, sidecar, proof), maximum=MAX_RSI_RECORD_BYTES,
        ))


def _context(
    value: object,
) -> tuple[NativeRSISchedulerContext, PythonProducerBindingSidecar]:
    if type(value) is not PythonRSISchedulerInputContext:
        _fail("context_invalid")
    proof = _checkpoint(value.original_producer_checkpoint, retained_pin=value._retained_sidecar_pin)
    sidecar = _sidecar(value.producer_sidecar, proof)
    native = _native(value.native_context, sidecar.binding)
    projection = canonical_json(_projection(native, sidecar, proof), maximum=MAX_RSI_RECORD_BYTES)
    if type(value._projection_json) is not bytes or projection != value._projection_json:
        _fail("context_drift")
    return native, sidecar


def _request_memory(request: object, memory: object) -> tuple[SolverRequest, MemorySnapshot]:
    if type(request) is not SolverRequest or type(memory) is not MemorySnapshot:
        _fail("request_memory_invalid")
    _shape(request)
    _shape(memory)
    try:
        detached_request = SolverRequest.from_dict(strict_json(
            canonical_json(request.to_dict(), maximum=MAX_RSI_RECORD_BYTES),
            MAX_RSI_RECORD_BYTES,
        ))
        detached_memory = MemorySnapshot.from_dict(strict_json(memory.to_bytes(), MAX_RSI_RECORD_BYTES))
        if (detached_request != request or detached_memory != memory
                or detached_request.memory_snapshot_sha256 != detached_memory.digest()):
            _fail("request_memory_invalid")
        return detached_request, detached_memory
    except PythonRSISchedulerInputError:
        raise
    except Exception as exc:
        raise PythonRSISchedulerInputError("request_memory_invalid") from exc


def _read_native(native: NativeRSISchedulerContext, *, require_unexpired: bool) -> NativeRSIInputDescriptor:
    try:
        inputs = validate_native_rsi_launch_inputs(
            native.workspace, intent=native.intent, attestation=native.attestation,
            artifact=native.artifact, require_unexpired=require_unexpired,
        )
        if type(inputs) is not NativeRSIInputDescriptor:
            _fail("native_inputs_missing")
        return inputs
    except PythonRSISchedulerInputError:
        raise
    except Exception as exc:
        raise PythonRSISchedulerInputError("native_inputs_invalid") from exc


def _read_sidecar(native: NativeRSISchedulerContext, sidecar: PythonProducerBindingSidecar) -> None:
    try:
        read_python_producer_binding_sidecar(
            native.workspace, binding=sidecar.binding, expected_sidecar=sidecar,
        )
    except Exception as exc:
        raise PythonRSISchedulerInputError("sidecar_drift") from exc


def _read_runtime(sidecar: PythonProducerBindingSidecar) -> None:
    binding = sidecar.binding
    try:
        # This reuses the full original inventory plus closed-tree observer. It reads declared
        # file bytes and all pinned directories; it does not import or execute these files.
        verify_python_runtime_tree_manifest(
            binding.runtime_tree, expected_tree_sha256=binding.runtime_tree_sha256,
            expected_manifest_sha256=binding.runtime_manifest_sha256, expected_target=binding.target,
        )
    except Exception as exc:
        raise PythonRSISchedulerInputError("runtime_drift") from exc


def _plan(
    native: NativeRSISchedulerContext, inputs: NativeRSIInputDescriptor,
    request: SolverRequest, memory: MemorySnapshot,
) -> NativeRSIExecutionPlan:
    try:
        plan = NativeRSIExecutionPlan.from_native_inputs(
            request=request, memory=memory, inputs=inputs, intent=native.intent,
            attestation=native.attestation, artifact=native.artifact,
            candidate_selector_id="native-selector-v1",
            candidate_selector_sha256=component_fingerprint(select_native_candidate),
            evaluator_kind=native.evaluator_kind, evaluator_fingerprint=native.evaluator_fingerprint,
        )
        _assert_plan_binding(request, memory, plan, native, inputs)
        return plan
    except Exception as exc:
        raise PythonRSISchedulerInputError("plan_binding_invalid") from exc


def validate_python_rsi_scheduler_inputs(
    context: PythonRSISchedulerInputContext,
    request: SolverRequest,
    memory: MemorySnapshot,
    *,
    require_unexpired: bool = False,
) -> NativeRSIInputDescriptor:
    """Observe exact pre-staged inputs twice without changing any retained evidence.

    Expired original deadlines remain inspectable by default. Requiring an unexpired deadline
    only narrows this read-only observation; neither setting authorizes dispatch. Runtime tree
    observations are bounded checks, not a held runtime owner or a post-execution receipt.
    """
    if type(require_unexpired) is not bool:
        _fail("expiry_policy_invalid")
    native, sidecar = _context(context)
    original_request, original_memory = request, memory
    request, memory = _request_memory(request, memory)
    _read_sidecar(native, sidecar)
    inputs = _read_native(native, require_unexpired=require_unexpired)
    _read_runtime(sidecar)
    _plan(native, inputs, request, memory)
    # Match the original fractional absolute deadline; do not truncate or refresh it.
    if canonical_json({"deadline": inputs.deadline_unix}) != canonical_json({
        "deadline": sidecar.binding.deadline_unix,
    }):
        _fail("deadline_mismatch")
    reread = _read_native(native, require_unexpired=require_unexpired)
    _read_sidecar(native, sidecar)
    _read_runtime(sidecar)
    if reread != inputs:
        _fail("input_drift")
    # _context verifies only the retained pure projection.  Comparing entire native contexts
    # would invoke equality on excluded strategies, broker objects or other execution hooks.
    _context(context)
    current_request, current_memory = _request_memory(original_request, original_memory)
    if current_request != request or current_memory != memory:
        _fail("input_drift")
    return inputs


def _code_dependencies() -> dict[str, str]:
    """Bind the deliberately listed local code dependencies without executing their hooks.

    Component identities do not discover imported globals.  This finite projection names this
    seam's helpers plus the native plan/input and Python runtime/binding boundaries it uses;
    it is a local code-drift identity, not package or interpreter authentication.
    """
    components = {
        "dependency_projection": _code_dependencies,
        "error": PythonRSISchedulerInputError,
        "fail": _fail, "shape": _shape, "path": _path,
        "checkpoint": _checkpoint, "sidecar": _sidecar, "native": _native,
        "projection": _projection, "context": _context,
        "input_context": PythonRSISchedulerInputContext,
        "request_memory": _request_memory,
        "read_native": _read_native, "read_sidecar": _read_sidecar,
        "read_runtime": _read_runtime, "plan": _plan,
        "validator": validate_python_rsi_scheduler_inputs,
        "native_input_validator": validate_native_rsi_launch_inputs,
        "native_input_descriptor": NativeRSIInputDescriptor,
        "native_execution_plan": NativeRSIExecutionPlan,
        "native_plan_from_inputs": NativeRSIExecutionPlan.from_native_inputs.__func__,
        "native_plan_binding": _assert_plan_binding,
        "runtime_tree_verifier": verify_python_runtime_tree_manifest,
        "python_binding": PythonProducerBinding,
        "python_binding_parser": parse_python_producer_binding,
        "python_sidecar_reader": read_python_producer_binding_sidecar,
        "python_sidecar_pin_validator": _validated_sidecar_pin,
        "python_checkpoint_binding": PythonProducerCheckpointBinding,
        "candidate_selector": select_native_candidate,
        "canonical_json": canonical_json, "strict_json": strict_json,
    }
    return {name: component_fingerprint(component) for name, component in components.items()}


@dataclass(frozen=True, slots=True)
class PythonRSISchedulerPlanFactory:
    """Pure plan-factory seam for NativeRSIExecutionConfig; no receipt-provider method."""

    context: PythonRSISchedulerInputContext

    def __post_init__(self) -> None:
        _context(self.context)

    def rsi_fingerprint_config(self) -> dict[str, Any]:
        _context(self.context)
        projection = strict_json(self.context._projection_json, MAX_RSI_RECORD_BYTES)
        projection["code_dependencies"] = _code_dependencies()
        return projection

    def plan(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        inputs = validate_python_rsi_scheduler_inputs(self.context, request, memory)
        native, _sidecar_pin = _context(self.context)
        detached_request, detached_memory = _request_memory(request, memory)
        return _plan(native, inputs, detached_request, detached_memory)

    def __call__(self, request: SolverRequest, memory: MemorySnapshot) -> NativeRSIExecutionPlan:
        return self.plan(request, memory)


__all__ = [
    "PYTHON_RSI_SCHEDULER_INPUT_PROTOCOL", "PythonRSISchedulerInputContext",
    "PythonRSISchedulerInputError", "PythonRSISchedulerPlanFactory",
    "validate_python_rsi_scheduler_inputs",
]
