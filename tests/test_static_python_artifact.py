"""Detached static artifact bytes checks; no filesystem or runtime launch."""

from __future__ import annotations

import copy
import hashlib
import json
import struct
from dataclasses import fields
from pathlib import Path

import pytest

from lunar_evolution import static_python_artifact as artifact
from lunar_evolution import static_python_elf as elf

_HEADER = struct.Struct("<16sHHIQQQIHHHHHH")
_PROGRAM = struct.Struct("<IIQQQQQQ")
_BASE = 0x400000
_IDENT = b"\x7fELF\x02\x01\x01" + b"\0" * 9
_FIELDS = ("ident", "kind", "machine", "version", "entry", "phoff", "shoff", "flags",
           "ehsize", "phsize", "phcount", "shsize", "shcount", "shnames")


def _image(size: int = 512) -> bytes:
    values = dict(zip(_FIELDS, (_IDENT, 2, 62, 1, _BASE + 128, 64, 0, 0, 64, 56, 1, 0, 0, 0)))
    data = bytearray(size)
    data[:64] = _HEADER.pack(*(values[key] for key in _FIELDS))
    _PROGRAM.pack_into(data, 64, 1, 5, 0, _BASE, 0, size, size, 4096)
    return bytes(data)


def _encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _descriptor(image: bytes, **profile_changes):
    payload = json.loads(
        (Path(__file__).parents[1] / "specs/189-static-python-fixture/wire-v1-example.json").read_text()
    )["descriptor"]
    payload = copy.deepcopy(payload)
    observed = elf.inspect_static_python_elf(image)
    payload["artifact_sha256"] = observed.sha256
    payload["artifact_size"] = observed.size
    for field in fields(elf.StaticPythonELFProfile):
        payload["elf_profile"][field.name] = getattr(observed, field.name)
    payload["elf_profile"].update(profile_changes)
    raw = _encode(payload)
    return raw, {
        "expected_descriptor_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_installation_version": payload["installation_version"],
        "expected_artifact_sha256": observed.sha256,
    }


def _refused(call, reason: str):
    with pytest.raises(artifact.StaticPythonArtifactVerificationError) as caught:
        call()
    assert caught.value.reason == "static_python_artifact_" + reason
    assert str(caught.value) == caught.value.reason


def test_matching_bytes_and_descriptor_return_format_only_evidence():
    image = _image()
    raw, pins = _descriptor(image)
    result = artifact.verify_static_python_artifact_bytes(image, raw, **pins)
    assert result.schema == artifact.ARTIFACT_VERIFICATION_SCHEMA
    assert result.format_verified is True
    assert result.artifact_sha256 == hashlib.sha256(image).hexdigest()
    assert result.artifact_size == len(image)
    assert result.elf_profile.size == len(image)
    assert result.execution_performed is False
    assert result.runtime_load_protection is False
    assert result.production_admission is False
    assert result.general_code_origin_protection is False
    assert result.verification_sha256 == hashlib.sha256(result.to_json()).hexdigest()
    detached = result.to_dict()
    detached["elf_profile"]["size"] = 1
    assert result.to_dict()["elf_profile"]["size"] == len(image)


def test_result_is_frozen():
    image = _image()
    raw, pins = _descriptor(image)
    result = artifact.verify_static_python_artifact_bytes(image, raw, **pins)
    with pytest.raises(AttributeError):
        result.artifact_size = 1


@pytest.mark.parametrize("value", [None, bytearray(b"x"), memoryview(b"x"), "ELF", 1])
def test_exact_builtin_bytes_are_required(value):
    raw, pins = _descriptor(_image())
    _refused(lambda: artifact.verify_static_python_artifact_bytes(value, raw, **pins), "image_type_invalid")


def test_bytes_subclass_is_refused():
    class Subclass(bytes):
        pass

    raw, pins = _descriptor(_image())
    _refused(lambda: artifact.verify_static_python_artifact_bytes(Subclass(_image()), raw, **pins),
             "image_type_invalid")


def test_image_limit_is_checked_before_descriptor_or_elf(monkeypatch):
    monkeypatch.setattr(artifact, "MAX_STATIC_PYTHON_IMAGE_BYTES", 4)
    monkeypatch.setattr(artifact, "parse_static_python_installation_descriptor",
                        lambda *_args, **_kwargs: pytest.fail("descriptor must not be parsed"))
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("ELF must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(
        b"12345", b"not-a-descriptor", expected_descriptor_sha256="a" * 64,
        expected_installation_version="v1", expected_artifact_sha256="b" * 64,
    ), "image_size_invalid")


def test_artifact_pin_drift_is_rejected_after_observation():
    image = _image()
    raw, pins = _descriptor(image)
    changed = image[:500] + b"x" + image[501:]
    _refused(lambda: artifact.verify_static_python_artifact_bytes(changed, raw, **pins),
             "artifact_pin_mismatch")


def test_descriptor_external_pin_mismatch_is_wrapped():
    image = _image()
    raw, pins = _descriptor(image)
    _refused(lambda: artifact.verify_static_python_artifact_bytes(
        image, raw, **{**pins, "expected_artifact_sha256": "a" * 64}
    ), "descriptor_external_pin")


def test_descriptor_elf_projection_drift_is_rejected():
    image = _image()
    raw, pins = _descriptor(image, entry_point=_BASE + 129)
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, raw, **pins),
             "elf_profile_mismatch")


def test_malformed_elf_is_refused_without_runtime_claim():
    raw, pins = _descriptor(_image())
    _refused(lambda: artifact.verify_static_python_artifact_bytes(b"not-elf", raw, **pins),
             "elf_size_invalid")


def test_elf_inspector_is_called_once(monkeypatch):
    image = _image()
    raw, pins = _descriptor(image)
    original = artifact.inspect_static_python_elf
    calls = []

    def wrapped(value):
        calls.append(value)
        return original(value)

    monkeypatch.setattr(artifact, "inspect_static_python_elf", wrapped)
    artifact.verify_static_python_artifact_bytes(image, raw, **pins)
    assert calls == [image]


def test_unknown_descriptor_field_is_refused_before_elf(monkeypatch):
    image = _image()
    raw, pins = _descriptor(image)
    payload = json.loads(raw)
    payload["unknown"] = 1
    changed = _encode(payload)
    pins = {**pins, "expected_descriptor_sha256": hashlib.sha256(changed).hexdigest()}
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("ELF must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, changed, **pins),
             "descriptor_schema")


@pytest.mark.parametrize("field,value", [
    ("osabi", 3), ("entry_point", _BASE + 129), ("program_header_count", 2),
    ("section_header_count", 1), ("load_segment_count", 2),
    ("executable_load_segment_count", 2), ("dynamic_table_count", 1),
    ("dynamic_entry_count", 1),
])
def test_elf_observed_fields_cannot_drift_in_a_valid_resigned_descriptor(field, value):
    image = _image()
    changes = {field: value}
    # Keep the descriptor internally valid so rejection reaches the independent
    # byte observation gate, not merely a stale JSON digest or field bounds.
    if field in {"load_segment_count", "executable_load_segment_count"}:
        changes["program_header_count"] = 2
        changes["load_segment_count"] = 2
    if field in {"dynamic_table_count", "dynamic_entry_count"}:
        changes["dynamic_table_count"] = 1
        changes["dynamic_entry_count"] = 1
    raw, pins = _descriptor(image, **changes)
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, raw, **pins),
             "elf_profile_mismatch")


def test_size_drift_reaches_independent_image_check():
    image = _image()
    raw, pins = _descriptor(image)
    payload = json.loads(raw)
    payload["artifact_size"] = 513
    payload["elf_profile"]["size"] = 513
    changed = _encode(payload)
    pins = {**pins, "expected_descriptor_sha256": hashlib.sha256(changed).hexdigest()}
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, changed, **pins),
             "artifact_size_mismatch")


@pytest.mark.parametrize("pin,value,reason", [
    ("expected_descriptor_sha256", "0" * 64, "descriptor_pin_invalid"),
    ("expected_descriptor_sha256", "f" * 64, "descriptor_pin_invalid"),
    ("expected_artifact_sha256", "0" * 64, "artifact_pin_invalid"),
    ("expected_artifact_sha256", "A" * 64, "artifact_pin_invalid"),
    ("expected_installation_version", "", "installation_version_invalid"),
    ("expected_installation_version", None, "installation_version_invalid"),
])
def test_invalid_external_pins_refuse_before_descriptor_and_image_observation(
    monkeypatch, pin, value, reason,
):
    image = _image()
    raw, pins = _descriptor(image)
    monkeypatch.setattr(artifact, "parse_static_python_installation_descriptor",
                        lambda *_args, **_kwargs: pytest.fail("descriptor must not be parsed"))
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("image must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, raw, **{**pins, pin: value}),
             reason)


def test_real_128_mib_ceiling_is_fixed_and_oversize_is_preparse(monkeypatch):
    assert artifact.MAX_STATIC_PYTHON_IMAGE_BYTES == elf.MAX_STATIC_PYTHON_IMAGE_BYTES == 134217728
    monkeypatch.setattr(artifact, "parse_static_python_installation_descriptor",
                        lambda *_args, **_kwargs: pytest.fail("descriptor must not be parsed"))
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("image must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(
        bytes(134217729), b"", expected_descriptor_sha256="a" * 64,
        expected_installation_version="v1", expected_artifact_sha256="b" * 64,
    ), "image_size_invalid")


@pytest.mark.parametrize("mutation,reason", [
    (lambda raw: raw + b" ", "descriptor_canonical"),
    (lambda raw: raw.replace(b'"schema_version":"1"',
                            b'"schema_version":"1","schema_version":"1"'),
     "descriptor_duplicate_key"),
])
def test_noncanonical_and_duplicate_descriptor_bytes_refuse_before_elf(monkeypatch, mutation, reason):
    image = _image()
    raw, pins = _descriptor(image)
    changed = mutation(raw)
    pins = {**pins, "expected_descriptor_sha256": hashlib.sha256(changed).hexdigest()}
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("ELF must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, changed, **pins), reason)


def test_runtime_claims_refuse_before_elf(monkeypatch):
    image = _image()
    raw, pins = _descriptor(image)
    payload = json.loads(raw)
    payload["production_admission"] = True
    changed = _encode(payload)
    pins = {**pins, "expected_descriptor_sha256": hashlib.sha256(changed).hexdigest()}
    monkeypatch.setattr(artifact, "inspect_static_python_elf",
                        lambda *_args, **_kwargs: pytest.fail("ELF must not be inspected"))
    _refused(lambda: artifact.verify_static_python_artifact_bytes(image, changed, **pins),
             "descriptor_claims")


def test_pure_verification_does_not_touch_filesystem_process_or_network(monkeypatch):
    image = _image()
    raw, pins = _descriptor(image)

    def forbidden(*_args, **_kwargs):
        pytest.fail("pure artifact gate must not perform external effects")

    import builtins
    import os
    import socket
    import subprocess

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    assert artifact.verify_static_python_artifact_bytes(image, raw, **pins).format_verified is True
