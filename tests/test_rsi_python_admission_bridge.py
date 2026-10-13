"""Pure Feature191 live-admission bridge descriptor checks."""

from __future__ import annotations

import pytest
from test_rsi_python_admission import OTHER, _files, _rows, _setup

from lunar_evolution.rsi_python_admission_bridge import (
    MAX_PYTHON_ADMISSION_BRIDGE_BYTES,
    PYTHON_ADMISSION_BRS_PIN_HOOK,
    PYTHON_ADMISSION_DRS_PIN_HOOK,
    PythonAdmissionBridgeAdapter,
    PythonAdmissionBridgeError,
    build_python_admission_bridge_descriptor,
    parse_python_admission_bridge_descriptor,
    validate_python_admission_bridge_descriptor,
)


def _descriptor(value):
    return build_python_admission_bridge_descriptor(
        run_id=value.binding.run_id,
        episode_id=value.episode_id,
        native_plan=value.plan,
        prepared_journal=value.journal,
        expected_anchor_sha256=value.anchor.anchor_sha256,
    )


def test_bridge_descriptor_roundtrips_and_binds_controller_identity(tmp_path):
    value = _setup(tmp_path)
    descriptor = _descriptor(value)

    assert descriptor.drs_pin_hook == PYTHON_ADMISSION_DRS_PIN_HOOK
    assert descriptor.brs_pin_hook == PYTHON_ADMISSION_BRS_PIN_HOOK
    assert parse_python_admission_bridge_descriptor(descriptor.to_json()) == descriptor
    assert parse_python_admission_bridge_descriptor(descriptor.to_dict()) == descriptor
    assert validate_python_admission_bridge_descriptor(
        descriptor.to_json(), run_id=value.binding.run_id, episode_id=value.episode_id,
    ) == descriptor


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("schema_version", "2", "schema_invalid"),
        ("drs_pin_hook", "caller-callback", "drs_hook_invalid"),
        ("brs_pin_hook", "caller-callback", "brs_hook_invalid"),
        ("bridge_sha256", OTHER, "bridge_digest_mismatch"),
        ("expected_anchor_sha256", OTHER, "bridge_digest_mismatch"),
    ],
)
def test_bridge_descriptor_rejects_schema_hook_digest_or_anchor_drift(tmp_path, field, value, error):
    fixture = _setup(tmp_path)
    wire = _descriptor(fixture).to_dict()
    wire[field] = value
    with pytest.raises(PythonAdmissionBridgeError, match=error):
        parse_python_admission_bridge_descriptor(wire)


@pytest.mark.parametrize("domain", ["plan", "journal"])
def test_bridge_descriptor_rejects_nested_identity_drift(tmp_path, domain):
    fixture = _setup(tmp_path)
    descriptor = _descriptor(fixture)
    wire = descriptor.to_dict()
    if domain == "plan":
        wire["native_plan"]["run_id"] = "other-run"
    else:
        wire["prepared_journal"]["journal_id"] = "other-journal"
    with pytest.raises(PythonAdmissionBridgeError, match="nested_invalid"):
        parse_python_admission_bridge_descriptor(wire)


def test_bridge_descriptor_rejects_non_prepared_journal(tmp_path):
    fixture = _setup(tmp_path)
    descriptor = _descriptor(fixture)
    wire = descriptor.to_dict()
    wire["prepared_journal"]["state"] = "staged"
    wire["prepared_journal"]["publication_phase"] = "staging"
    with pytest.raises(PythonAdmissionBridgeError, match="nested_invalid"):
        parse_python_admission_bridge_descriptor(wire)


def test_bridge_descriptor_rejects_controller_identity_before_return(tmp_path):
    value = _setup(tmp_path)
    descriptor = _descriptor(value)
    with pytest.raises(PythonAdmissionBridgeError, match="identity_mismatch"):
        validate_python_admission_bridge_descriptor(
            descriptor, run_id="other-run", episode_id=value.episode_id,
        )
    with pytest.raises(PythonAdmissionBridgeError, match="controller_identity_mismatch"):
        validate_python_admission_bridge_descriptor(
            descriptor, run_id=value.binding.run_id, episode_id="other-episode",
        )


def test_bridge_descriptor_is_pure_and_does_not_mutate_fixture(tmp_path):
    value = _setup(tmp_path)
    before_rows, before_files = _rows(value), _files(value)
    descriptor = _descriptor(value)
    for _ in range(3):
        parse_python_admission_bridge_descriptor(descriptor.to_json())
        validate_python_admission_bridge_descriptor(
            descriptor.to_dict(), run_id=value.binding.run_id, episode_id=value.episode_id,
        )
    assert _rows(value) == before_rows
    assert _files(value) == before_files


def test_bridge_descriptor_rejects_noncanonical_wire(tmp_path):
    descriptor = _descriptor(_setup(tmp_path))
    wire = descriptor.to_json()
    with pytest.raises(PythonAdmissionBridgeError, match="noncanonical_json"):
        parse_python_admission_bridge_descriptor(b" " + wire)


def test_bridge_descriptor_rejects_zero_anchor_digest(tmp_path):
    value = _setup(tmp_path)
    with pytest.raises(PythonAdmissionBridgeError, match="anchor_sha256_invalid"):
        build_python_admission_bridge_descriptor(
            run_id=value.binding.run_id,
            episode_id=value.episode_id,
            native_plan=value.plan,
            prepared_journal=value.journal,
            expected_anchor_sha256="0" * 64,
        )


class _Controller:
    def __init__(self):
        self.calls = []

    def _pin_python_admission_for_active_flow(self, *args, **kwargs):
        self.calls.append(("drs", args, kwargs))
        return "1" * 64

    def _request_python_admission_for_brs_worker(self, *args, **kwargs):
        self.calls.append(("brs", args, kwargs))
        kwargs["wait_check"]()
        return "2" * 64


def test_bridge_adapter_maps_existing_drs_and_brs_hooks_without_side_effects(tmp_path):
    value = _setup(tmp_path)
    descriptor = _descriptor(value)
    controller = _Controller()
    stages = []
    adapter = PythonAdmissionBridgeAdapter(controller, descriptor, wait_check=lambda: stages.append("checked"))

    assert adapter.pin_drs(descriptor.to_json()) == "1" * 64
    assert adapter.pin_brs(descriptor.to_dict()) == "2" * 64
    assert stages == ["checked"]
    assert [item[0] for item in controller.calls] == ["drs", "brs"]
    assert controller.calls[0][1] == (value.binding.run_id, value.episode_id)
    assert controller.calls[1][1] == (value.binding.run_id, value.episode_id)


@pytest.mark.parametrize("scope", ["drs", "brs"])
def test_bridge_adapter_pin_live_selects_existing_owner_scope(tmp_path, scope):
    value = _setup(tmp_path)
    descriptor = _descriptor(value)
    controller = _Controller()
    controller._python_admission_flow_local = type("Local", (), {"active": object()})()
    controller._python_admission_brs_local = type("Local", (), {"active": None})()
    if scope == "brs":
        controller._python_admission_flow_local.active = None
        controller._python_admission_brs_local.active = object()
    adapter = PythonAdmissionBridgeAdapter(controller, descriptor, wait_check=lambda: None)
    expected = "1" * 64 if scope == "drs" else "2" * 64
    assert adapter.pin_live(descriptor.to_json()) == expected
    assert [item[0] for item in controller.calls] == [scope]


def test_bridge_adapter_pin_live_requires_an_existing_owner_scope(tmp_path):
    value = _setup(tmp_path)
    controller = _Controller()
    controller._python_admission_flow_local = type("Local", (), {"active": None})()
    controller._python_admission_brs_local = type("Local", (), {"active": None})()
    adapter = PythonAdmissionBridgeAdapter(controller, _descriptor(value), wait_check=lambda: None)
    with pytest.raises(PythonAdmissionBridgeError, match="live_worker_missing"):
        adapter.pin_live(_descriptor(value))
    assert controller.calls == []


def test_bridge_adapter_fails_closed_on_descriptor_drift_and_missing_brs_wait(tmp_path):
    value = _setup(tmp_path)
    descriptor = _descriptor(value)
    controller = _Controller()
    adapter = PythonAdmissionBridgeAdapter(controller, descriptor)
    drifted = descriptor.to_dict()
    drifted["run_id"] = "other-run"
    with pytest.raises(PythonAdmissionBridgeError, match="identity_mismatch"):
        adapter.pin_drs(drifted)
    with pytest.raises(PythonAdmissionBridgeError, match="brs_wait_check_missing"):
        adapter.pin_brs(descriptor)
    assert controller.calls == []


@pytest.mark.parametrize("domain", ["nested_plan", "nested_request", "candidate_list", "scalar"])
def test_bridge_wire_refuses_callback_shapes_before_serialization(tmp_path, domain):
    value = _setup(tmp_path)
    wire = _descriptor(value).to_dict()
    callbacks = []

    class CallbackDict(dict):
        def items(self):
            callbacks.append("items")
            return super().items()

    class CallbackList(list):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

    class CallbackString(str):
        def __eq__(self, other):
            callbacks.append("equal")
            return super().__eq__(other)

    if domain == "nested_plan":
        wire["native_plan"] = CallbackDict(wire["native_plan"])
    elif domain == "nested_request":
        wire["native_plan"]["request"] = CallbackDict(wire["native_plan"]["request"])
    elif domain == "candidate_list":
        wire["prepared_journal"]["candidates"] = CallbackList(wire["prepared_journal"]["candidates"])
    else:
        wire["expected_anchor_sha256"] = CallbackString(wire["expected_anchor_sha256"])
    before = (_rows(value), _files(value))
    with pytest.raises(PythonAdmissionBridgeError, match="shape_invalid"):
        parse_python_admission_bridge_descriptor(wire)
    assert callbacks == []
    assert (_rows(value), _files(value)) == before


@pytest.mark.parametrize("domain", ["string", "unicode", "key", "aggregate", "container", "integer", "depth", "nodes"])
def test_bridge_bounds_shapes_before_json_encoding(tmp_path, monkeypatch, domain):
    wire = _descriptor(_setup(tmp_path)).to_dict()
    if domain == "string":
        wire["expected_anchor_sha256"] = "x" * (MAX_PYTHON_ADMISSION_BRIDGE_BYTES + 1)
    elif domain == "unicode":
        wire["expected_anchor_sha256"] = "é" * (MAX_PYTHON_ADMISSION_BRIDGE_BYTES // 2)
    elif domain == "key":
        wire["native_plan"]["x" * (MAX_PYTHON_ADMISSION_BRIDGE_BYTES + 1)] = None
    elif domain == "aggregate":
        wire["native_plan"]["request"]["solver_settings"] = {
            "first": "x" * (MAX_PYTHON_ADMISSION_BRIDGE_BYTES // 2),
            "second": "x" * (MAX_PYTHON_ADMISSION_BRIDGE_BYTES // 2),
        }
    elif domain == "container":
        wire["prepared_journal"]["candidates"] = [None] * 10_001
    elif domain == "integer":
        wire["native_plan"]["deadline_unix"] = 1 << 4096
    elif domain == "depth":
        nested = []
        for _ in range(49):
            nested = [nested]
        wire["native_plan"]["request"]["solver_settings"] = nested
    else:
        wire["native_plan"]["request"]["solver_settings"] = [[None] * 10_000 for _ in range(11)]
    monkeypatch.setattr(
        "lunar_evolution.rsi_python_admission_bridge.canonical_json",
        lambda *_args, **_kwargs: pytest.fail("unbounded shape reached JSON encoder"),
    )
    with pytest.raises(PythonAdmissionBridgeError, match="shape_invalid"):
        parse_python_admission_bridge_descriptor(wire)


def test_bridge_shape_type_checks_never_invoke_hostile_metaclass(tmp_path):
    value = _setup(tmp_path)
    wire = _descriptor(value).to_dict()
    callbacks = []

    class CallbackMeta(type):
        def __hash__(cls):
            callbacks.append("hash")
            return type.__hash__(cls)

        def __eq__(cls, other):
            callbacks.append("equal")
            return type.__eq__(cls, other)

    class CallerValue(metaclass=CallbackMeta):
        pass

    wire["expected_anchor_sha256"] = CallerValue()
    with pytest.raises(PythonAdmissionBridgeError, match="shape_invalid"):
        parse_python_admission_bridge_descriptor(wire)
    object.__setattr__(value.plan.request, "budget", (("request_limit", CallerValue()),))
    with pytest.raises(PythonAdmissionBridgeError, match="shape_invalid"):
        _descriptor(value)
    assert callbacks == []


@pytest.mark.parametrize(
    "domain", ["request_serializer", "request_fields", "plan_budget", "drs_hook", "brs_hook"],
)
def test_bridge_dto_refuses_callback_shapes_before_nested_serializers(tmp_path, domain):
    value = _setup(tmp_path)
    callbacks = []

    def callback(*_args, **_kwargs):
        callbacks.append("serialize")
        return {}

    class CallbackTuple(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

    class CallbackFields(dict):
        def values(self):
            callbacks.append("fields")
            return super().values()

    class CallbackString(str):
        def __eq__(self, other):
            callbacks.append("equal")
            return super().__eq__(other)

    kwargs = {}
    if domain == "request_serializer":
        object.__setattr__(value.plan.request, "to_dict", callback)
    elif domain == "request_fields":
        object.__setattr__(
            value.plan.request, "__dataclass_fields__",
            CallbackFields(type(value.plan.request).__dataclass_fields__),
        )
    elif domain == "plan_budget":
        object.__setattr__(value.plan.request, "budget", CallbackTuple(value.plan.request.budget))
    else:
        hook = PYTHON_ADMISSION_DRS_PIN_HOOK if domain == "drs_hook" else PYTHON_ADMISSION_BRS_PIN_HOOK
        kwargs["drs_pin_hook" if domain == "drs_hook" else "brs_pin_hook"] = CallbackString(hook)
    before = (_rows(value), _files(value))
    with pytest.raises(PythonAdmissionBridgeError, match="shape_invalid|hook_invalid"):
        build_python_admission_bridge_descriptor(
            run_id=value.binding.run_id,
            episode_id=value.episode_id,
            native_plan=value.plan,
            prepared_journal=value.journal,
            expected_anchor_sha256=value.anchor.anchor_sha256,
            **kwargs,
        )
    assert callbacks == []
    assert (_rows(value), _files(value)) == before
