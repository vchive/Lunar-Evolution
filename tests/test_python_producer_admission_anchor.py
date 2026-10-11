import json
from collections import UserDict
from dataclasses import replace

import pytest

from lunar_evolution.python_producer_admission_anchor import (
    MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES,
    PythonProducerAdmissionAnchorError,
    build_python_producer_admission_attempt_anchor,
    parse_python_producer_admission_attempt_anchor,
    persist_python_producer_admission_attempt_anchor,
    read_python_producer_admission_attempt_anchor,
    verify_python_producer_admission_attempt_anchor,
)


def _anchor(**updates):
    digest = "a" * 64
    values = {
        "attempt_id": "attempt-1",
        "run_id": "run-1",
        "journal_id": "journal-1",
        "binding_sha256": digest,
        "handoff_sha256": "b" * 64,
        "terminal_sha256": "c" * 64,
        "runtime_observation_sha256": "d" * 64,
        "native_execution_receipt_sha256": "e" * 64,
        "admission_plan_sha256": "f" * 64,
        "fingerprints": {"contract": "1" * 64, "runtime": "2" * 64},
        "request_budget": 4,
        "wall_timeout_seconds": 30,
        "deadline_unix": 1_900_000_000,
    }
    values.update(updates)
    return build_python_producer_admission_attempt_anchor(**values)


def test_anchor_is_canonical_and_digest_bound():
    anchor = _anchor()
    wire = anchor.to_json()
    assert parse_python_producer_admission_attempt_anchor(wire) == anchor
    assert json.loads(wire) == anchor.to_dict()
    assert anchor.to_dict()["anchor_sha256"] == anchor.digest()


def test_anchor_rejects_digest_or_field_drift():
    anchor = _anchor()
    wire = anchor.to_dict()
    wire["request_budget"] = 5
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_mismatch"):
        parse_python_producer_admission_attempt_anchor(wire)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="drift"):
        verify_python_producer_admission_attempt_anchor(
            _anchor(request_budget=5), anchor,
        )


def test_anchor_rejects_missing_evidence_and_replacement():
    anchor = _anchor()
    wire = anchor.to_dict()
    del wire["runtime_observation_sha256"]
    with pytest.raises(PythonProducerAdmissionAnchorError, match="schema_invalid"):
        parse_python_producer_admission_attempt_anchor(wire)
    replacement = _anchor(attempt_id="attempt-2")
    with pytest.raises(PythonProducerAdmissionAnchorError, match="drift"):
        verify_python_producer_admission_attempt_anchor(replacement, anchor)



def test_anchor_create_only_persistence_and_revalidation(tmp_path):
    anchor = _anchor()
    stored = persist_python_producer_admission_attempt_anchor(tmp_path, anchor=anchor)
    assert stored == anchor
    path = tmp_path / "python-producer-admission-anchor.json"
    assert path.stat().st_mode & 0o777 == 0o600
    assert read_python_producer_admission_attempt_anchor(path, expected_anchor_sha256=anchor.anchor_sha256) == anchor
    assert persist_python_producer_admission_attempt_anchor(path, anchor=anchor) == anchor
    changed = _anchor(request_budget=5)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="already_exists"):
        persist_python_producer_admission_attempt_anchor(path, anchor=changed)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_mismatch"):
        read_python_producer_admission_attempt_anchor(path, expected_anchor_sha256="f" * 64)


def test_anchor_rejects_file_replacement_and_symlink(tmp_path):
    anchor = _anchor()
    persist_python_producer_admission_attempt_anchor(tmp_path, anchor=anchor)
    path = tmp_path / "python-producer-admission-anchor.json"
    path.unlink()
    path.write_bytes(_anchor(request_budget=7).to_json())
    path.chmod(0o600)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_mismatch"):
        read_python_producer_admission_attempt_anchor(path, expected_anchor_sha256=anchor.anchor_sha256)
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_bytes(anchor.to_json())
    outside.chmod(0o600)
    path.symlink_to(outside)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="file_identity_invalid"):
        read_python_producer_admission_attempt_anchor(path)


def test_anchor_preserves_fractional_original_deadline_and_timeout():
    anchor = _anchor(wall_timeout_seconds=0.375, deadline_unix=1_900_000_000.125)
    parsed = parse_python_producer_admission_attempt_anchor(anchor.to_json())
    assert parsed.wall_timeout_seconds == 0.375
    assert parsed.deadline_unix == 1_900_000_000.125
    assert parsed.to_json() == anchor.to_json()


@pytest.mark.parametrize("field", ["wall_timeout_seconds", "deadline_unix"])
@pytest.mark.parametrize("value", [False, 0, -1, float("inf"), float("nan"), "30"])
def test_anchor_rejects_invalid_original_deadline_or_timeout(field, value):
    with pytest.raises(PythonProducerAdmissionAnchorError, match=field + "_invalid"):
        _anchor(**{field: value})


@pytest.mark.parametrize("field", ["schema_version", "protocol", "request_budget"])
def test_anchor_revalidates_mutated_scalar_dto_before_hashing(field):
    anchor = _anchor()
    object.__setattr__(anchor, field, False)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="invalid"):
        parse_python_producer_admission_attempt_anchor(anchor)


@pytest.mark.parametrize("value", [None, "0" * 64, "bad"])
def test_anchor_retained_dto_requires_original_nonzero_digest(value):
    anchor = _anchor()
    object.__setattr__(anchor, "anchor_sha256", value)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_invalid"):
        parse_python_producer_admission_attempt_anchor(anchor)


@pytest.mark.parametrize("value", [None, "0" * 64, "bad", False])
def test_anchor_retained_wire_requires_original_nonzero_digest(value):
    wire = _anchor().to_dict()
    wire["anchor_sha256"] = value
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_invalid"):
        parse_python_producer_admission_attempt_anchor(wire)


@pytest.mark.parametrize("value", [False, 0, -1, 1.0, "4"])
def test_anchor_request_budget_is_positive_exact_integer(value):
    with pytest.raises(PythonProducerAdmissionAnchorError, match="request_budget_invalid"):
        _anchor(request_budget=value)


@pytest.mark.parametrize("value", [{}, {"bad key": "a" * 64}, {"runtime": "0" * 64}, {"runtime": False}])
def test_anchor_fingerprints_reject_invalid_values(value):
    with pytest.raises(PythonProducerAdmissionAnchorError, match="fingerprint.*invalid"):
        _anchor(fingerprints=value)


def test_anchor_fingerprint_mutation_cannot_refresh_retained_digest():
    anchor = _anchor()
    anchor.fingerprints["runtime"] = "3" * 64
    with pytest.raises(PythonProducerAdmissionAnchorError, match="anchor_digest_mismatch"):
        parse_python_producer_admission_attempt_anchor(anchor)


def test_anchor_refuses_callback_mapping_without_invoking_it():
    class Trap(UserDict):
        def items(self):
            pytest.fail("callback mapping was invoked")

        def __iter__(self):
            pytest.fail("callback mapping was invoked")

    with pytest.raises(PythonProducerAdmissionAnchorError, match="fingerprints_invalid"):
        replace(_anchor(), fingerprints=Trap())
    with pytest.raises(PythonProducerAdmissionAnchorError, match="json_invalid"):
        parse_python_producer_admission_attempt_anchor(Trap())


@pytest.mark.parametrize("wire,code", [
    (b'{"x":1,"x":2}', "duplicate_json_key"),
    (b'{"x":NaN}', "json_invalid"),
    (b'{"x":Infinity}', "json_invalid"),
    (b'\xff', "json_invalid"),
    (b'[]', "schema_invalid"),
])
def test_anchor_strict_json_refuses_ambiguous_or_invalid_wire(wire, code):
    with pytest.raises(PythonProducerAdmissionAnchorError, match=code):
        parse_python_producer_admission_attempt_anchor(wire)


def test_anchor_refuses_noncanonical_json():
    wire = json.dumps(_anchor().to_dict())
    with pytest.raises(PythonProducerAdmissionAnchorError, match="noncanonical_json"):
        parse_python_producer_admission_attempt_anchor(wire)


def test_anchor_limits_wire_before_json_parsing():
    wire = b" " * (MAX_PYTHON_PRODUCER_ADMISSION_ANCHOR_BYTES + 1)
    with pytest.raises(PythonProducerAdmissionAnchorError, match="record_too_large"):
        parse_python_producer_admission_attempt_anchor(wire)
