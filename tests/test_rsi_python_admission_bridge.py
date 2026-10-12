"""Pure Feature191 live-admission bridge descriptor checks."""

from __future__ import annotations

import pytest
from test_rsi_python_admission import OTHER, _files, _rows, _setup

from lunar_evolution.rsi_python_admission_bridge import (
    PYTHON_ADMISSION_BRS_PIN_HOOK,
    PYTHON_ADMISSION_DRS_PIN_HOOK,
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
    with pytest.raises(PythonAdmissionBridgeError, match="controller_identity_mismatch"):
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
