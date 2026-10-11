"""Read-only Python/native scheduler joins over inert, never-executed bytes."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from test_algorithm import _contract
from test_producer_python_runtime import _inventory
from test_python_producer_binding import _fixture as python_fixture
from test_rsi_native_inputs import _memory

from lunar_evolution import rsi_native_inputs as native_inputs
from lunar_evolution import rsi_python_scheduler_inputs as scheduler
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.native_bootstrap import NativeBootstrapArtifact
from lunar_evolution.producer_bootstrap import TrustedBootstrapDescriptor
from lunar_evolution.producer_broker_ipc import ProducerBrokerConfig
from lunar_evolution.producer_bundle_handoff import BundleGroup
from lunar_evolution.producer_launcher import build_producer_launch_attestation
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_binding_store import (
    PYTHON_BINDING_SIDECAR_NAME,
    persist_python_producer_binding,
    read_python_producer_binding_sidecar,
)
from lunar_evolution.python_producer_checkpoint import PythonProducerCheckpointBinding
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_native_gateway import (
    NativeRSIExecutionConfig,
    NativeRSISolverGateway,
    NativeRSISolverGatewayError,
)
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    make_native_rsi_scheduler_provider,
)
from lunar_evolution.rsi_store import RSILedger

DEADLINE = 4102444800.125
OTHER = "b" * 64


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


@contextmanager
def _tamper_directory(path):
    mode = stat.S_IMODE(path.parent.stat().st_mode)
    path.parent.chmod(mode | stat.S_IWUSR)
    try:
        yield
    finally:
        path.parent.chmod(mode)


def _inert_bootstrap(root):
    path = root / "inert-bootstrap"
    path.write_bytes(b"inert bootstrap material; never executable code\n")
    path.chmod(0o700)
    info = path.stat()
    mode = "darwin-immutable-snapshot" if sys.platform == "darwin" else "linux-fd-bound"
    descriptor = TrustedBootstrapDescriptor(
        implementation_version="native-bootstrap-v1", bootstrap_sha256=_sha(path.read_bytes()),
        size=info.st_size, device=info.st_dev, inode=info.st_ino,
        mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns,
        allowlist_id="inert-bootstrap-input-fixture", platform_execution_mode=mode,
    )
    return NativeBootstrapArtifact(
        path=path, source_sha256=OTHER, artifact_sha256=descriptor.bootstrap_sha256,
        compiler="not-built-inert-fixture", platform_execution_mode=mode,
        allowlist_id=descriptor.allowlist_id, descriptor=descriptor,
    )


def _setup(root, *, stage=True):
    root.mkdir(exist_ok=True)
    manifest, tree, original, _, _ = python_fixture(root)
    contract = AlgorithmProblemContract.from_dict(_contract())
    memory = _memory()
    request = SolverRequest.build(
        episode_id="python-scheduler-episode", contract_sha256=contract.digest(),
        evaluator_sha256=original.evaluator_fingerprint,
        environment_sha256=original.environment_sha256,
        memory_snapshot_sha256=memory.digest(), solver_id="native_population",
        solver_settings={"bounded": {"width": 2}},
        budget=RSIRunBudget.create({"deadline_unix": DEADLINE, "max_solver_invocations": 3}).to_dict()["planned"],
    )
    descriptor = native_inputs.prepare_native_rsi_inputs(
        root, journal_id=original.journal_id, request=request, memory=memory,
    ) if stage else None
    argv = original.argv + (descriptor.argv_fragment if descriptor else ())
    intent = replace(
        original, contract_sha256=contract.digest(), argv=argv,
        argv_sha256=_sha(canonical_json(list(argv))), intent_sha256=None,
    )
    intent = replace(intent, intent_sha256=intent.digest())
    attestation = build_producer_launch_attestation(intent, "python-scheduler-original-once")
    artifact = _inert_bootstrap(root)
    if stage:
        descriptor = native_inputs.bind_native_rsi_launch(
            root, intent=intent, attestation=attestation, artifact=artifact, inputs=descriptor,
        )
    batch = root / "evolution" / "producer-batches" / intent.journal_id
    batch.mkdir(parents=True, exist_ok=True, mode=0o700)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=DEADLINE,
        budget=RSIRunBudget.create({"deadline_unix": DEADLINE, "max_solver_invocations": 3}),
    )
    sidecar = persist_python_producer_binding(root, binding=binding)
    proof = PythonProducerCheckpointBinding.from_sidecar(sidecar)
    producer_root = root / "inert-python-tree" / "runtime"
    native = NativeRSISchedulerContext(
        workspace=root, producer_root=producer_root, intent=intent, attestation=attestation,
        artifact=artifact, broker_config=ProducerBrokerConfig("http://127.0.0.1:9/unused", {}),
        contract=contract, groups=(BundleGroup("fixture", "solve/main.py", ("solve/main.py",)),),
        evaluator_kind=intent.evaluator_kind, evaluator_fingerprint=intent.evaluator_fingerprint,
        runner_fingerprint=intent.runner_fingerprint, dependency_sha256=intent.dependency_sha256,
        environment_sha256=intent.environment_sha256, strategy=object(),
    )
    context = scheduler.PythonRSISchedulerInputContext(native, sidecar, proof)
    factory = scheduler.PythonRSISchedulerPlanFactory(context)
    return SimpleNamespace(
        root=root, batch=batch, manifest=manifest, tree=tree, native=native, binding=binding,
        sidecar=sidecar, proof=proof, context=context, factory=factory,
        request=request, memory=memory, descriptor=descriptor, producer_root=producer_root,
    )


def _validate(value, **kwargs):
    return scheduler.validate_python_rsi_scheduler_inputs(
        value.context, value.request, value.memory, **kwargs,
    )


def _refuse(value, operation):
    before = _inventory(value.root)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        operation()
    assert _inventory(value.root) == before


def test_canonical_join_and_plan_match_original_native_wire_without_effects(tmp_path):
    value = _setup(tmp_path)
    before = _inventory(value.root)
    expected = make_native_rsi_scheduler_provider(value.native).plan(value.request, value.memory)
    fingerprint = component_fingerprint(value.factory)
    for _ in range(3):
        assert _validate(value) == value.descriptor
        assert value.factory(value.request, value.memory) == expected
        assert value.factory.plan(value.request, value.memory).to_dict() == expected.to_dict()
        assert component_fingerprint(value.factory) == fingerprint
    assert _inventory(value.root) == before
    assert not (value.batch / "process-registration.json").exists()
    assert not (value.batch / "attestation-consumption.json").exists()
    assert not (value.batch / "python-producer-admission-handoff.json").exists()
    assert not hasattr(value.factory, "run")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        value.context.native_context = value.native


@pytest.mark.parametrize("domain", ["sidecar", "proof", "native"])
def test_independently_valid_domains_cannot_be_mixed_across_original_runs(tmp_path, domain):
    first = _setup(tmp_path / "first")
    second = _setup(tmp_path / "second")
    for value in (first, second):
        value.proof.validate_sidecar(value.sidecar)
        read_python_producer_binding_sidecar(value.root, binding=value.binding, expected_sidecar=value.sidecar)
        assert native_inputs.validate_native_rsi_launch_inputs(
            value.root, intent=value.native.intent, attestation=value.native.attestation,
            artifact=value.native.artifact,
        ) == value.descriptor
    arguments = {
        "native": (second.native, first.sidecar, first.proof),
        "sidecar": (first.native, second.sidecar, second.proof),
        "proof": (first.native, first.sidecar, second.proof),
    }[domain]
    before = _inventory(tmp_path)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        context = scheduler.PythonRSISchedulerInputContext(*arguments)
        scheduler.validate_python_rsi_scheduler_inputs(context, first.request, first.memory)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("changed", ["episode", "request", "settings", "memory", "deadline"])
def test_original_request_memory_and_deadline_cannot_be_rebound(tmp_path, changed):
    value = _setup(tmp_path)
    request, memory = value.request, value.memory
    if changed == "episode":
        request = replace(request, episode_id="another-episode")
    elif changed == "request":
        request = replace(request, environment_sha256=OTHER)
    elif changed == "settings":
        request = replace(request, solver_settings=(("bounded", {"width": 3}),))
    elif changed == "memory":
        memory = replace(memory, snapshot_id="another-history")
        request = replace(request, memory_snapshot_sha256=memory.digest())
    else:
        request = replace(request, budget=tuple(sorted(dict(request.budget, deadline_unix=DEADLINE + 1).items())))
    _refuse(value, lambda: scheduler.validate_python_rsi_scheduler_inputs(value.context, request, memory))


@pytest.mark.parametrize("field", [
    "producer_root", "intent", "attestation", "contract", "evaluator_kind", "evaluator_fingerprint",
    "runner_fingerprint", "dependency_sha256", "environment_sha256", "artifact",
])
def test_native_context_drift_cannot_borrow_retained_python_evidence(tmp_path, field):
    value = _setup(tmp_path)
    replacements = {
        "producer_root": tmp_path,
        "intent": replace(value.native.intent, task_id="other-task", intent_sha256=None),
        "attestation": build_producer_launch_attestation(value.native.intent, "other-once"),
        "contract": AlgorithmProblemContract.from_dict(_contract(statement="A different problem.")),
        "evaluator_kind": "another-local",
        "evaluator_fingerprint": OTHER,
        "runner_fingerprint": OTHER,
        "dependency_sha256": OTHER,
        "environment_sha256": OTHER,
        "artifact": replace(value.native.artifact, artifact_sha256=OTHER),
    }
    before = _inventory(value.root)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        context = scheduler.PythonRSISchedulerInputContext(
            replace(value.native, **{field: replacements[field]}), value.sidecar, value.proof,
        )
        scheduler.validate_python_rsi_scheduler_inputs(context, value.request, value.memory)
    assert _inventory(value.root) == before


@pytest.mark.parametrize("file,change", [
    (file, change)
    for file in ("sidecar", "request", "memory", "manifest", "launch")
    for change in ("missing", "replace", "touch", "mode", "link", "symlink")
    if (file, change) not in {("manifest", "touch"), ("launch", "touch")}
])
def test_original_sidecar_and_inputs_metadata_drift_refuses_read_only(tmp_path, file, change):
    value = _setup(tmp_path)
    path = {
        "sidecar": value.batch / PYTHON_BINDING_SIDECAR_NAME,
        "request": value.descriptor.request_path,
        "memory": value.descriptor.memory_path,
        "manifest": value.descriptor.inputs_path / "manifest.json",
        "launch": value.batch / "native-rsi-launch.json",
    }[file]
    with _tamper_directory(path):
        if change == "missing":
            path.unlink()
        elif change == "replace":
            replacement = path.with_name(path.name + ".replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(stat.S_IMODE(path.stat().st_mode))
            os.replace(replacement, path)
        elif change == "touch":
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        elif change == "mode":
            path.chmod(0o644)
        elif change == "link":
            os.link(path, path.with_name(path.name + ".extra"))
        else:
            target = path.with_name(path.name + ".target")
            path.rename(target)
            path.symlink_to(target)
    _refuse(value, lambda: _validate(value))


@pytest.mark.parametrize("file", ["manifest", "launch"])
def test_native_self_binding_preserves_existing_pre_observation_touch_boundary(tmp_path, file):
    value = _setup(tmp_path)
    path = (value.descriptor.inputs_path / "manifest.json" if file == "manifest"
            else value.batch / "native-rsi-launch.json")
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    before = _inventory(value.root)
    # Existing native self-bindings retain bytes/device/inode, without an independently
    # retained original timestamp. This join must not invent that missing evidence.
    assert _validate(value) == value.descriptor
    assert _inventory(value.root) == before


@pytest.mark.parametrize("file", ["interpreter", "stdlib", "project", "resource", "unlisted"])
def test_runtime_closed_tree_is_revalidated_without_host_fallback(tmp_path, file):
    value = _setup(tmp_path)
    if file == "unlisted":
        path = value.producer_root / "unlisted.py"
    else:
        role = {"project": "project_source", "resource": "project_resource"}.get(file, file)
        record = next(item for item in value.manifest.files if item.role == role)
        root = next(item.path for item in value.manifest.roots if item.label == record.root_label)
        path = Path(root) / record.relative_path
    path.write_bytes(b"changed inert bytes")
    _refuse(value, lambda: _validate(value))


def test_expired_deadline_remains_inspectable_but_never_authorizes_fresh_dispatch(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    before = _inventory(value.root)
    monkeypatch.setattr(native_inputs.time, "time", lambda: DEADLINE + 1)
    retained = _validate(value)
    assert retained.deadline_unix == DEADLINE
    assert value.factory(value.request, value.memory).deadline_unix == DEADLINE
    _refuse(value, lambda: _validate(value, require_unexpired=True))
    assert _inventory(value.root) == before


def test_legacy_no_marker_native_input_cannot_be_upgraded_to_python_plan(tmp_path):
    value = _setup(tmp_path, stage=False)
    assert native_inputs.validate_native_rsi_launch_inputs(
        value.root, intent=value.native.intent, attestation=value.native.attestation,
        artifact=value.native.artifact,
    ) is None
    _refuse(value, lambda: _validate(value))


def test_invalid_join_fails_in_real_gateway_plan_gate_before_claim_or_provider(tmp_path, monkeypatch):
    value = _setup(tmp_path / "first")
    other = _setup(tmp_path / "second")
    # Constructing the context may perform a pure join gate. Mutate after construction
    # to exercise the mandatory repeat gate at the actual native gateway boundary.
    object.__setattr__(value.context, "producer_sidecar", other.sidecar)
    ledger = RSILedger(tmp_path / "gateway.sqlite3")
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("provider-or-claim")
        pytest.fail("invalid Python join escaped the preclaim plan gate")
    monkeypatch.setattr(ledger, "claim_native_episode", forbidden)
    gateway = NativeRSISolverGateway(NativeRSIExecutionConfig(ledger, value.factory, forbidden))
    with pytest.raises(NativeRSISolverGatewayError, match="plan_failed"):
        gateway.run(value.request, value.memory)
    assert calls == []
    with sqlite3.connect(ledger.database) as connection:
        assert connection.execute("SELECT count(*) FROM rsi_native_episode_claims").fetchone()[0] == 0


def test_plan_and_validation_have_no_write_compile_launch_or_provider_capability(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    before = _inventory(value.root)
    def forbidden(*args, **kwargs):
        pytest.fail("read-only plan invoked a launch, build, staging or claim capability")
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    for name in ("prepare_native_rsi_inputs", "bind_native_rsi_launch"):
        monkeypatch.setattr(native_inputs, name, forbidden)
    monkeypatch.setattr(RSILedger, "claim_native_episode", forbidden)
    original_open = os.open
    def readonly_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_TRUNC)
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", readonly_open)
    assert _validate(value) == value.descriptor
    value.factory(value.request, value.memory)
    assert _inventory(value.root) == before


@pytest.mark.parametrize("domain", ["sidecar", "native", "runtime"])
def test_drift_between_complete_reads_refuses_without_repair(tmp_path, monkeypatch, domain):
    value = _setup(tmp_path)
    path = {
        "sidecar": value.batch / PYTHON_BINDING_SIDECAR_NAME,
        "native": value.descriptor.request_path,
        "runtime": value.producer_root / "bin" / "python",
    }[domain]
    read_runtime = scheduler._read_runtime
    calls, retained = [], []
    def observed(*args, **kwargs):
        read_runtime(*args, **kwargs)
        calls.append("runtime")
        if len(calls) == 1:
            with _tamper_directory(path):
                replacement = path.with_name(path.name + ".replacement")
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(stat.S_IMODE(path.stat().st_mode))
                os.replace(replacement, path)
            retained.append(_inventory(value.root))
    monkeypatch.setattr(scheduler, "_read_runtime", observed)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        _validate(value)
    assert calls and _inventory(value.root) == retained[0]


@pytest.mark.parametrize("domain", ["request", "memory", "context"])
def test_caller_dto_drift_during_reads_refuses_original_inputs(tmp_path, monkeypatch, domain):
    value = _setup(tmp_path)
    before = _inventory(value.root)
    read_runtime = scheduler._read_runtime
    calls = []
    def observed(*args, **kwargs):
        read_runtime(*args, **kwargs)
        calls.append("runtime")
        if len(calls) == 1:
            if domain == "request":
                value.request.solver_settings[0][1]["width"] = 9
            elif domain == "memory":
                object.__setattr__(value.memory.items[0], "strategy", "changed during read")
            else:
                object.__setattr__(value.native.groups[0], "entrypoint", "solve/other.py")
    monkeypatch.setattr(scheduler, "_read_runtime", observed)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        _validate(value)
    assert calls and _inventory(value.root) == before


@pytest.mark.parametrize("domain", ["request", "settings", "memory", "proof", "sidecar", "path"])
def test_callback_shapes_refuse_before_readers_or_serializers(tmp_path, monkeypatch, domain):
    value = _setup(tmp_path)
    before = _inventory(value.root)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("unexpected-callback")
        pytest.fail("untrusted shape invoked a callback or filesystem reader")
    class RequestSubclass(SolverRequest):
        to_dict = forbidden
    class CallbackDict(dict):
        items = forbidden
        values = forbidden
        __iter__ = forbidden
    class MemorySubclass(type(value.memory)):
        to_bytes = forbidden
    class CallbackPath:
        __fspath__ = forbidden
    request, memory, context = value.request, value.memory, value.context
    if domain == "request":
        request = RequestSubclass(**{item.name: getattr(request, item.name) for item in fields(request)})
    elif domain == "settings":
        request = replace(request, solver_settings=(("bounded", CallbackDict(width=2)),))
    elif domain == "memory":
        memory = MemorySubclass(memory.snapshot_id, memory.parent_snapshot_sha256, memory.items)
    elif domain == "proof":
        object.__setattr__(context.original_producer_checkpoint, "sidecar_pin", CallbackDict())
    elif domain == "sidecar":
        object.__setattr__(context.producer_sidecar.binding, "request_budget", CallbackDict())
    else:
        object.__setattr__(value.native, "workspace", CallbackPath())
    for name in ("_read_native", "_read_sidecar", "_read_runtime"):
        monkeypatch.setattr(scheduler, name, forbidden)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        scheduler.validate_python_rsi_scheduler_inputs(context, request, memory)
    assert calls == [] and _inventory(value.root) == before


def test_original_checkpoint_is_detached_and_never_reminted(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    retained = value.context.original_producer_checkpoint.to_json()
    value.proof.sidecar_pin["file_inode"] += 1
    def forbidden(*args, **kwargs):
        pytest.fail("validation reminted a checkpoint from current sidecar")
    monkeypatch.setattr(PythonProducerCheckpointBinding, "from_sidecar", forbidden)
    assert value.context.original_producer_checkpoint.to_json() == retained
    assert _validate(value) == value.descriptor
    with pytest.raises(TypeError):
        value.context.original_producer_checkpoint.sidecar_pin["file_inode"] = 1


def test_fingerprint_excludes_execution_hooks_credentials_and_wall_clock(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    fingerprint = component_fingerprint(value.factory)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("execution-hook")
        pytest.fail("read-only input identity invoked execution callback")
    native = replace(
        value.native, strategy=forbidden, cancelled=forbidden,
        broker_config=ProducerBrokerConfig("http://127.0.0.1:9/another-unused", {"X-Inert": "fixture-secret"}),
    )
    factory = scheduler.PythonRSISchedulerPlanFactory(scheduler.PythonRSISchedulerInputContext(
        native, value.sidecar, value.proof,
    ))
    monkeypatch.setattr(native_inputs.time, "time", lambda: DEADLINE + 999)
    assert component_fingerprint(factory) == fingerprint
    assert factory(value.request, value.memory) == value.factory(value.request, value.memory)
    assert "fixture-secret" not in str(factory.rsi_fingerprint_config())
    assert calls == []


@pytest.mark.parametrize("changed", ["bootstrap_source", "groups"])
def test_plan_configuration_has_distinct_stable_fingerprint(tmp_path, changed):
    value = _setup(tmp_path)
    if changed == "bootstrap_source":
        native = replace(value.native, artifact=replace(value.native.artifact, source_sha256="c" * 64))
    else:
        native = replace(value.native, groups=(BundleGroup("other", "solve/main.py", ("solve/main.py",)),))
    factory = scheduler.PythonRSISchedulerPlanFactory(scheduler.PythonRSISchedulerInputContext(
        native, value.sidecar, value.proof,
    ))
    assert component_fingerprint(factory) != component_fingerprint(value.factory)


def test_foreign_mapping_proxy_is_rejected_before_underlying_mapping_callbacks(tmp_path):
    value = _setup(tmp_path)
    calls = []
    class CallbackMapping(Mapping):
        def __iter__(self):
            calls.append("iter")
            return iter(value.proof.sidecar_pin)
        def __getitem__(self, key):
            calls.append("getitem")
            return value.proof.sidecar_pin[key]
        def __len__(self):
            calls.append("len")
            return len(value.proof.sidecar_pin)
    proof = replace(value.proof)
    object.__setattr__(proof, "sidecar_pin", MappingProxyType(CallbackMapping()))
    before = _inventory(value.root)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        scheduler.PythonRSISchedulerInputContext(value.native, value.sidecar, proof)
    assert calls == [] and _inventory(value.root) == before


def test_opaque_execution_object_equality_is_never_invoked_between_reads(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    calls = []
    class CallbackEquality:
        def __eq__(self, other):
            calls.append("execution-equality")
            pytest.fail("input comparison invoked opaque execution object")
    read_runtime = scheduler._read_runtime
    reads = []
    def observed(*args, **kwargs):
        read_runtime(*args, **kwargs)
        reads.append("runtime")
        if len(reads) == 1:
            object.__setattr__(value.native, "strategy", CallbackEquality())
    monkeypatch.setattr(scheduler, "_read_runtime", observed)
    assert _validate(value) == value.descriptor
    assert calls == [] and len(reads) == 2


def test_fingerprint_rejects_changed_validator_dependency(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    fingerprint = component_fingerprint(value.factory)
    def changed_validator(*args, **kwargs):
        pytest.fail("fingerprint invoked changed validator")
    monkeypatch.setattr(scheduler, "validate_python_rsi_scheduler_inputs", changed_validator)
    # The context was built with the original code. A changed dependency must either
    # invalidate it or produce a different identity; it must never remain identical.
    try:
        observed = component_fingerprint(value.factory)
    except scheduler.PythonRSISchedulerInputError:
        return
    except ValueError as exc:
        assert "rsi_identity_" in str(exc)
        return
    assert observed != fingerprint


@pytest.mark.parametrize("domain", ["request", "memory_item", "contract"])
def test_exact_dto_instance_cannot_shadow_serializer_with_callback(tmp_path, domain):
    value = _setup(tmp_path)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append("shadowed-serializer")
        pytest.fail("exact DTO invoked instance serializer callback")
    target = {
        "request": value.request,
        "memory_item": value.memory.items[0],
        "contract": value.native.contract,
    }[domain]
    object.__setattr__(target, "to_dict", forbidden)
    before = _inventory(value.root)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        _validate(value)
    assert calls == [] and _inventory(value.root) == before


def test_exact_dto_instance_dictionary_rejects_non_plain_keys_without_hash_callback(tmp_path):
    value = _setup(tmp_path)
    calls = []
    class CallbackKey:
        armed = False
        def __hash__(self):
            if self.armed:
                calls.append("hash")
                pytest.fail("DTO shape invoked non-plain attribute key")
            return 123
    key = CallbackKey()
    value.request.__dict__[key] = None
    key.armed = True
    before = _inventory(value.root)
    with pytest.raises(scheduler.PythonRSISchedulerInputError):
        _validate(value)
    assert calls == [] and _inventory(value.root) == before
