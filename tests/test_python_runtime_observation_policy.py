"""Inert observation comparison over reviewed asset output and retained pins.

The asset encoder runs with a closed simulated sys/loader/pipe profile. Neither
the ELF fixture nor a solver is executed, and no production authority is claimed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from test_producer_bootstrap import _descriptor as _bootstrap_descriptor
from test_python_fixture_observation import BROKER, asset_observation  # noqa: F401
from test_python_producer_admission_gate import (
    STATIC_FLAGS,
    _chain,
    _installation_inputs,
    _resigned_chain,
    _static_binding_fixture,
)
from test_rsi_native_inputs import _inventory, _memory, _request
from test_static_python_artifact import _descriptor, _image

from lunar_evolution import rsi_native_inputs
from lunar_evolution.native_bootstrap import NativeBootstrapArtifact
from lunar_evolution.python_fixture_observation import adapt_static_python_observation
from lunar_evolution.python_producer_adapter import (
    PythonProducerAdapterError,
    build_python_producer_adapter_envelope,
    parse_python_producer_adapter_envelope,
    verify_python_producer_adapter_envelope,
)
from lunar_evolution.python_producer_admission_gate import verify_python_producer_admission_gate
from lunar_evolution.python_producer_binding import build_python_producer_binding
from lunar_evolution.python_producer_lifecycle import parse_python_producer_runtime_observation
from lunar_evolution.python_runtime_observation_policy import (
    PythonRuntimeObservationPolicyError,
    validate_python_runtime_observation_policy,
)
from lunar_evolution.static_python_installation import (
    StaticPythonInstallationDescriptor,
    parse_static_python_installation_descriptor,
)


@pytest.fixture
def evidence(tmp_path, asset_observation):  # noqa: F811
    chain = _chain(tmp_path, producer="openevolve")
    observation = adapt_static_python_observation(
        asset_observation(), binding_sha256=chain[0].binding_sha256,
        broker_transcript=BROKER, pycache_absent=True,
    )
    return chain, _resigned_chain(chain, runtime_observation=observation)


def _changed(observation, **changes):
    item = replace(observation, **changes, observation_sha256=None)
    return replace(item, observation_sha256=item.digest())


def _adapter_inputs(gate):
    return gate["binding"], gate["terminal"], gate["runtime_observation"], gate["envelope"]


def _policy_refused(binding, observation, pins, code):
    with pytest.raises(PythonRuntimeObservationPolicyError) as caught:
        validate_python_runtime_observation_policy(binding, observation, **pins)
    assert caught.value.code == code
    assert str(caught.value) == code


def _all_profile_gates_refuse(gate, pins, code):
    binding, terminal, observation, result = _adapter_inputs(gate)
    original_pins = _installation_inputs(binding)
    adapter = build_python_producer_adapter_envelope(
        binding, terminal, observation, result, **original_pins,
    )
    _policy_refused(binding, observation, pins, code)
    refused = verify_python_producer_admission_gate(**{**gate, **pins})
    assert refused.reason_code == "python_producer_admission_gate_runtime_profile_" + code
    assert refused.refused and refused.production_admission is False
    for operation in (
        lambda: build_python_producer_adapter_envelope(
            binding, terminal, observation, result, **pins,
        ),
        lambda: verify_python_producer_adapter_envelope(binding, adapter, **pins),
    ):
        with pytest.raises(PythonProducerAdapterError) as caught:
            operation()
        assert caught.value.code == "python_producer_adapter_runtime_profile_" + code


def test_asset_observation_satisfies_policy_gate_and_adapter(evidence):
    _, gate = evidence
    binding, terminal, observation, result = _adapter_inputs(gate)
    pins = _installation_inputs(binding)
    assert observation.flags == STATIC_FLAGS
    assert binding.intent.argv == ("bin/python",)
    assert observation.argv == observation.orig_argv == ("lunar-static-python-fixture",)
    assert observation.argv != binding.intent.argv
    assert validate_python_runtime_observation_policy(binding, observation, **pins) is None
    accepted = verify_python_producer_admission_gate(**gate)
    assert accepted.eligible and accepted.production_admission is False
    adapter = build_python_producer_adapter_envelope(
        binding, terminal, observation, result, **pins,
    )
    assert verify_python_producer_adapter_envelope(binding, adapter.to_json(), **pins) == adapter
    assert observation.runtime_load_protection is False
    assert observation.general_code_origin_protection is False
    assert observation.production_admission is False and adapter.production_admission is False


def test_static_single_argument_intent_refuses_staged_native_rsi_inputs(evidence, tmp_path, monkeypatch):
    _, gate = evidence
    binding = gate["binding"]
    workspace = tmp_path / "native-input-workspace"
    workspace.mkdir()
    memory = _memory()
    inputs = rsi_native_inputs.prepare_native_rsi_inputs(
        workspace, journal_id=binding.intent.journal_id,
        request=_request(memory, deadline=4102444800.0), memory=memory,
    )
    assert len(binding.intent.argv) == 1
    assert len((*binding.intent.argv, *inputs.argv_fragment)) == 3
    # This non-authoritative DTO is never loaded: the missing original intent
    # marker must refuse before bootstrap validation or any executable launch.
    artifact = NativeBootstrapArtifact(
        path=tmp_path / "never-installed-bootstrap", source_sha256="a" * 64,
        artifact_sha256="a" * 64, compiler="fixture-only", platform_execution_mode="fixture-only",
        allowlist_id="local-bootstrap", descriptor=_bootstrap_descriptor(),
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("missing-marker refusal reached bootstrap validation")

    monkeypatch.setattr(rsi_native_inputs, "load_native_bootstrap_artifact", forbidden)
    before = _inventory(workspace)
    try:
        with pytest.raises(rsi_native_inputs.NativeRSIInputError) as caught:
            rsi_native_inputs.validate_native_rsi_launch_inputs(
                workspace, intent=binding.intent, attestation=binding.attestation,
                artifact=artifact, require_unexpired=True,
            )
        assert caught.value.code == "rsi_native_inputs_marker_missing"
        assert _inventory(workspace) == before
        assert not (inputs.inputs_path.parent / "native-rsi-launch.json").exists()
    finally:
        inputs.inputs_path.chmod(0o700)


@pytest.mark.parametrize("field,value", [
    ("flags", STATIC_FLAGS[:-1]),
    ("flags", STATIC_FLAGS + ("verbose=0",)),
    ("flags", STATIC_FLAGS + (STATIC_FLAGS[0],)),
    ("flags", tuple(reversed(STATIC_FLAGS))),
    ("flags", ("-I", "-S", "-B")),
    ("flags", tuple("isolated=0" if item == "isolated=1" else item for item in STATIC_FLAGS)),
    ("flags", tuple("isolated=True" if item == "isolated=1" else item for item in STATIC_FLAGS)),
    ("argv", ("bin/python",)), ("orig_argv", ("bin/python",)),
    ("argv", ("lunar-static-python-fixture", "candidate.py")),
    ("orig_argv", ("lunar-static-python-fixture", "candidate.py")),
    ("version_major", 4), ("version_minor", 12), ("version_micro", 11),
    ("cache_tag", "cpython-312"), ("abi_profile", "cp313-free-threaded"),
    ("filesystem_encoding", "ascii"), ("filesystem_errors", "strict"),
    ("stdio_encoding", "ascii"), ("stdio_errors", "surrogateescape"),
    ("sys_path", ("candidate",)), ("startup_modules", ("sys",)),
    ("startup_modules", ()),
])
def test_resigned_asset_drift_cannot_pass_any_policy_entry(evidence, field, value):
    chain, gate = evidence
    binding, terminal, observation, result = _adapter_inputs(gate)
    pins = _installation_inputs(binding)
    original = build_python_producer_adapter_envelope(
        binding, terminal, observation, result, **pins,
    )
    observation = _changed(observation, **{field: value})
    _policy_refused(binding, observation, pins, "observation_target_mismatch")
    gate = _resigned_chain(chain, runtime_observation=observation)
    refused = verify_python_producer_admission_gate(**gate)
    assert refused.reason_code == "python_producer_admission_gate_runtime_observation_target_mismatch"
    assert refused.refused and refused.production_admission is False
    with pytest.raises(PythonProducerAdapterError, match="runtime_target_drift"):
        build_python_producer_adapter_envelope(binding, terminal, observation, result, **pins)
    # Parsing remains a historical inspection operation, never a policy bypass.
    changed_adapter = replace(original, observation=observation, adapter_sha256=None)
    assert parse_python_producer_adapter_envelope(changed_adapter.to_json()).observation == observation
    assert parse_python_producer_runtime_observation(observation.to_json()) == observation
    with pytest.raises(PythonProducerAdapterError, match="runtime_target_drift"):
        verify_python_producer_adapter_envelope(binding, changed_adapter.to_json(), **pins)


@pytest.mark.parametrize("name,code", [
    ("installation_descriptor", "installation_invalid"),
    ("installation_descriptor_sha256", "installation_pin_unverified"),
    ("installation_version", "installation_pin_unverified"),
    ("initialization_profile_sha256", "installation_pin_unverified"),
])
def test_each_independent_pin_is_required_by_all_entry_points(evidence, name, code):
    _, gate = evidence
    pins = _installation_inputs(gate["binding"])
    # Explicit None mirrors omission under all public keyword defaults.
    _all_profile_gates_refuse(gate, {**pins, name: None}, code)


@pytest.mark.parametrize("name,value,code", [
    ("installation_descriptor_sha256", "f" * 64, "installation_invalid"),
    ("initialization_profile_sha256", "f" * 64, "installation_invalid"),
    ("installation_version", "different-installation", "installation_invalid"),
    ("installation_descriptor_sha256", "0" * 64, "installation_pin_unverified"),
    ("initialization_profile_sha256", True, "installation_pin_unverified"),
    ("installation_version", "", "installation_pin_unverified"),
    ("installation_version", "x" * 129, "installation_pin_unverified"),
])
def test_independent_pin_drift_is_not_replaced_with_descriptor_values(evidence, name, value, code):
    _, gate = evidence
    pins = _installation_inputs(gate["binding"])
    _all_profile_gates_refuse(gate, {**pins, name: value}, code)


@pytest.mark.parametrize("field,value", [
    ("canonical_bytes", b"{}"), ("descriptor_sha256", "f" * 64),
    ("installation_version", "different-installation"), ("artifact_sha256", "f" * 64),
    ("artifact_size", 513), ("artifact_size", True),
])
def test_descriptor_dto_tamper_is_not_an_independent_expected_pin(evidence, field, value):
    _, gate = evidence
    pins = _installation_inputs(gate["binding"])
    descriptor = replace(pins["installation_descriptor"], **{field: value})
    _all_profile_gates_refuse(
        gate, {**pins, "installation_descriptor": descriptor}, "installation_invalid",
    )


def test_valid_descriptor_for_another_artifact_cannot_bind_this_interpreter(evidence):
    _, gate = evidence
    raw, external = _descriptor(_image(600))
    descriptor = parse_static_python_installation_descriptor(raw, **external)
    pins = {
        "installation_descriptor": descriptor,
        "installation_descriptor_sha256": external["expected_descriptor_sha256"],
        "installation_version": external["expected_installation_version"],
        "initialization_profile_sha256": descriptor.to_dict()["initialization_profile_sha256"],
    }
    _all_profile_gates_refuse(gate, pins, "installation_invalid")


@pytest.mark.parametrize("target", [
    {"python_version": "3.11", "abi_tag": "cp311"},
    {"platform": "darwin"}, {"architecture": "aarch64"},
])
def test_valid_binding_with_other_target_cannot_choose_the_installation(tmp_path, target):
    manifest, tree, intent, attestation, budget = _static_binding_fixture(
        tmp_path, target_changes=target,
    )
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    other = tmp_path / "observation"
    other.mkdir()
    observation = _changed(_chain(other)[4], binding_sha256=binding.binding_sha256)
    _policy_refused(binding, observation, _installation_inputs(binding), "installation_binding_mismatch")


@pytest.mark.parametrize("mode", [0o500, 0o700, 0o755])
def test_valid_binding_with_other_executable_mode_cannot_match_static_profile(tmp_path, mode):
    manifest, tree, intent, attestation, budget = _static_binding_fixture(tmp_path, mode=mode)
    binding = build_python_producer_binding(
        runtime_manifest=manifest, runtime_tree=tree, intent=intent, attestation=attestation,
        deadline_unix=4102444800.0, budget=budget,
    )
    other = tmp_path / "observation"
    other.mkdir()
    observation = _changed(_chain(other)[4], binding_sha256=binding.binding_sha256)
    _policy_refused(binding, observation, _installation_inputs(binding), "installation_binding_mismatch")


@pytest.mark.parametrize("mode", ["subclass", "callback_mapping", "callback_bytes", "callback_text"])
def test_untrusted_descriptor_types_refuse_before_callbacks(evidence, mode):
    _, gate = evidence
    pins = _installation_inputs(gate["binding"])
    descriptor = pins["installation_descriptor"]

    class HostileDescriptor(StaticPythonInstallationDescriptor):
        def to_dict(self):
            pytest.fail("descriptor subclass callback")

    class HostileMapping(dict):
        def items(self):
            pytest.fail("descriptor mapping callback")

    class HostileBytes(bytes):
        def decode(self, *args, **kwargs):
            pytest.fail("descriptor bytes callback")

    class HostileText(str):
        def __eq__(self, _other):
            pytest.fail("descriptor text equality callback")

    if mode == "subclass":
        descriptor = HostileDescriptor(
            descriptor.canonical_bytes, descriptor.descriptor_sha256,
            descriptor.installation_version, descriptor.artifact_sha256, descriptor.artifact_size,
        )
    elif mode == "callback_mapping":
        descriptor = HostileMapping(descriptor.to_dict())
    elif mode == "callback_bytes":
        descriptor = replace(descriptor, canonical_bytes=HostileBytes(descriptor.canonical_bytes))
    else:
        descriptor = replace(descriptor, artifact_sha256=HostileText(descriptor.artifact_sha256))
    _all_profile_gates_refuse(
        gate, {**pins, "installation_descriptor": descriptor}, "installation_invalid",
    )


@pytest.mark.parametrize("mode", [
    "binding_nested_collection", "binding_integer", "observation_collection", "observation_string",
])
def test_original_dto_mutations_refuse_before_caller_callbacks(evidence, mode):
    _, gate = evidence
    binding, _, observation, _ = _adapter_inputs(gate)
    pins = _installation_inputs(binding)

    class HostileTuple(tuple):
        def __iter__(self):
            pytest.fail("caller-controlled tuple iterated")

    class HostileInteger(int):
        def __lt__(self, _other):
            pytest.fail("caller-controlled integer compared")

    class HostileString(str):
        def encode(self, *_args, **_kwargs):
            pytest.fail("caller-controlled string encoded")

    if mode == "binding_nested_collection":
        object.__setattr__(binding.runtime_manifest, "files", HostileTuple(binding.runtime_manifest.files))
    elif mode == "binding_integer":
        object.__setattr__(binding, "request_budget", HostileInteger(binding.request_budget))
    elif mode == "observation_collection":
        object.__setattr__(observation, "flags", HostileTuple(observation.flags))
    else:
        object.__setattr__(observation, "filesystem_encoding", HostileString("utf-8"))
    _policy_refused(binding, observation, pins, "observation_target_mismatch")


@pytest.mark.parametrize("subject", ["binding", "observation", "installation_descriptor"])
@pytest.mark.parametrize("name", ["to_json", "to_dict", "__post_init__"])
def test_exact_slotted_dtos_disallow_instance_serializer_or_validator_shadow(evidence, subject, name):
    _, gate = evidence
    binding, _, observation, _ = _adapter_inputs(gate)
    pins = _installation_inputs(binding)
    item = {"binding": binding, "observation": observation, **pins}[subject]

    def callback(*_args, **_kwargs):
        pytest.fail("caller-controlled method invoked")

    with pytest.raises(AttributeError):
        object.__setattr__(item, name, callback)
    assert not hasattr(item, "__dict__")
    assert validate_python_runtime_observation_policy(binding, observation, **pins) is None


def test_policy_and_composed_consumers_do_not_launch_read_evaluate_or_check_time(evidence, monkeypatch):
    import os
    import subprocess
    import time

    _, gate = evidence
    binding, terminal, observation, result = _adapter_inputs(gate)
    pins = _installation_inputs(binding)

    def forbidden(*_args, **_kwargs):
        pytest.fail("pure comparison attempted external work")

    for module, names in (
        (os, ("open", "stat", "lstat", "system")),
        (subprocess, ("Popen", "run")),
        (time, ("time", "monotonic")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    validate_python_runtime_observation_policy(binding, observation, **pins)
    assert verify_python_producer_admission_gate(**gate).eligible
    adapter = build_python_producer_adapter_envelope(binding, terminal, observation, result, **pins)
    assert verify_python_producer_adapter_envelope(binding, adapter, **pins) == adapter


def test_historical_token_shaped_wire_stays_inspectable_without_becoming_eligible(evidence):
    chain, gate = evidence
    binding, terminal, observation, result = _adapter_inputs(gate)
    pins = _installation_inputs(binding)
    adapter = build_python_producer_adapter_envelope(binding, terminal, observation, result, **pins)
    observation = _changed(
        observation, flags=("-I", "-S", "-B"),
        argv=binding.intent.argv, orig_argv=binding.intent.argv,
    )
    wire = adapter.to_dict()
    wire["observation"] = observation.to_dict()
    wire.pop("adapter_sha256")
    wire["adapter_sha256"] = hashlib.sha256(
        json.dumps(wire, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
    ).hexdigest()
    assert parse_python_producer_adapter_envelope(wire).observation == observation
    assert parse_python_producer_runtime_observation(observation.to_json()) == observation
    with pytest.raises(PythonProducerAdapterError, match="runtime_target_drift"):
        verify_python_producer_adapter_envelope(binding, wire, **pins)
    refused = verify_python_producer_admission_gate(
        **_resigned_chain(chain, runtime_observation=observation),
    )
    assert refused.refused and refused.production_admission is False
