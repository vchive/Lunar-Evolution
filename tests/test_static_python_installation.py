"""Pure installation descriptor tests; no filesystem, build or runtime launch."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution import static_python_installation as installation


@pytest.fixture
def vector():
    return json.loads(
        (Path(__file__).parents[1] / "specs/189-static-python-fixture/wire-v1-example.json").read_text()
    )


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def parse(vector, payload=None, **pins):
    payload = vector["descriptor"] if payload is None else payload
    defaults = {
        "expected_descriptor_sha256": hashlib.sha256(encode(payload)).hexdigest(),
        "expected_installation_version": payload["installation_version"],
        "expected_artifact_sha256": payload.get("artifact_sha256", vector["descriptor"]["artifact_sha256"]),
    }
    defaults.update(pins)
    return installation.parse_static_python_installation_descriptor(encode(payload), **defaults)


def refused(callback, reason):
    with pytest.raises(installation.StaticPythonInstallationError) as caught:
        callback()
    assert caught.value.reason == "static_python_installation_" + reason
    assert str(caught.value) == caught.value.reason


def test_vector_is_detached_and_external_pins_are_mandatory(vector):
    observed = parse(vector)
    assert observed.descriptor_sha256 == vector["descriptor_sha256"]
    assert observed.artifact_size == 256
    assert observed.to_json() == encode(vector["descriptor"])
    detached = observed.to_dict()
    detached["production_admission"] = True
    assert observed.to_dict()["production_admission"] is False
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_descriptor_sha256="0" * 64)
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_installation_version="other-v1")
    with pytest.raises(installation.StaticPythonInstallationError):
        parse(vector, expected_artifact_sha256="f" * 64)


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.update({"unknown": 1}), "schema"),
    (lambda p: p.pop("artifact_sha256"), "schema"),
    (lambda p: p.update({"execution_performed": True}), "claims"),
    (lambda p: p.update({"artifact_mode": 0o755}), "artifact_mode"),
    (lambda p: p.update({"artifact_size": 0}), "integer"),
    (lambda p: p.update({"source_commit": "1"}), "profile"),
    (lambda p: p["toolchain"].update({"target": "x86_64-linux-gnu"}), "toolchain"),
    (lambda p: p["recipe"]["environment"].append({"name": "HOME", "value": "/tmp"}), "environment"),
    (lambda p: p["embedded_startup_arrays"].append({}), "startup_arrays"),
    (lambda p: p["initialization_profile"]["config"].update({"use_environment": 1}), "initialization"),
    (lambda p: p["elf_profile"].update({"has_pt_interp": True}), "elf_profile"),
    (lambda p: p["frozen_modules"].reverse(), "frozen_inventory"),
])
def test_profile_mutations_refuse_before_any_external_effect(vector, mutation, reason):
    payload = copy.deepcopy(vector["descriptor"])
    mutation(payload)
    refused(lambda: parse(vector, payload), reason)


def test_manifest_digest_is_bound_to_canonical_nested_bytes(vector):
    payload = copy.deepcopy(vector["descriptor"])
    payload["recipe"]["link_flags"].append("-Wl,--as-needed")
    refused(lambda: parse(vector, payload), "manifest_pin")


@pytest.mark.parametrize("raw", [b"", b"null", b"[]", b"{\"x\":1}", b"{\"schema_version\":1}"])
def test_wire_shapes_refuse(raw):
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            raw,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "wire" if raw == b"" else "json_type" if raw == b"null" else "schema",
    )


def test_duplicate_json_keys_and_noncanonical_bytes_refuse(vector):
    raw = encode(vector["descriptor"]) + b" "
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            raw,
            expected_descriptor_sha256=hashlib.sha256(raw).hexdigest(),
            expected_installation_version="synthetic-v1",
            expected_artifact_sha256=vector["descriptor"]["artifact_sha256"],
        ),
        "canonical",
    )
    duplicate = b'{"schema_version":"1","schema_version":"1"}'
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            duplicate,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "duplicate_key",
    )


def test_descriptor_overflow_is_rejected_before_json_parse(monkeypatch):
    monkeypatch.setattr(installation, "_scan", lambda _value: pytest.fail("scan must not run"))
    refused(
        lambda: installation.parse_static_python_installation_descriptor(
            b"{" + b" " * installation.MAX_DESCRIPTOR_BYTES,
            expected_descriptor_sha256="a" * 64,
            expected_installation_version="v1",
            expected_artifact_sha256="b" * 64,
        ),
        "wire",
    )
