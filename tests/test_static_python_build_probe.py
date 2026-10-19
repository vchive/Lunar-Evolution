"""Focused tests for the detached real-build probe receipt."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

import lunar_evolution as package
from lunar_evolution import static_python_build_probe as probe


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _vector(*, artifact: bool = True, runtime: str = "failed") -> dict:
    image = {
        "present": artifact,
        "sha256": _sha("static-image") if artifact else None,
        "size": 26673400 if artifact else None,
        "elf": {
            "class": 64,
            "byte_order": "little",
            "type": "ET_EXEC",
            "machine": "x86_64",
            "program_headers": 9,
            "section_headers": 26,
            "pt_interp": False,
            "dt_needed": False,
            "dynamic_section": False,
        } if artifact else None,
    }
    return {
        "schema": probe.BUILD_PROBE_SCHEMA,
        "probe_id": "cp313-core-static-20261019",
        "source_archive_sha256": _sha("archive"),
        "source_tree_sha256": _sha("tree"),
        "toolchain_manifest_sha256": _sha("toolchain"),
        "recipe_sha256": _sha("recipe"),
        "build": {
            "configure_status": "succeeded",
            "target_status": "succeeded",
            "target": "python",
            "optional_module_closure": "open",
            "blocker": None,
        },
        "artifact": image,
        "runtime": {
            "attempted": True,
            "status": runtime,
            "exit_code": 1 if runtime == "failed" else 0,
            "failure": "encodings_not_found" if runtime == "failed" else None,
        } if runtime != "not-run" else {
            "attempted": False, "status": "not-run", "exit_code": None, "failure": None,
        },
        "claims": {name: False for name in probe._CLAIMS},
    }


def _parse(payload: dict) -> probe.StaticPythonBuildProbe:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return probe.parse_static_python_build_probe(raw)


def test_valid_probe_is_canonical_and_detached():
    payload = _vector()
    result = _parse(payload)
    assert result.probe_id == "cp313-core-static-20261019"
    assert result.build_status == "succeeded"
    assert result.runtime_status == "failed"
    assert result.artifact_size == 26673400
    assert result.to_dict() == payload
    assert result.to_json() == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(AttributeError):
        result.build_status = "blocked"  # type: ignore[misc]


def test_probe_parser_is_part_of_the_public_package_surface():
    assert package.BUILD_PROBE_SCHEMA == probe.BUILD_PROBE_SCHEMA
    assert package.MAX_BUILD_PROBE_BYTES == probe.MAX_BUILD_PROBE_BYTES
    assert package.MAX_STATIC_IMAGE_BYTES == probe.MAX_STATIC_IMAGE_BYTES
    assert package.StaticPythonBuildProbe is probe.StaticPythonBuildProbe
    assert package.StaticPythonBuildProbeError is probe.StaticPythonBuildProbeError
    assert package.parse_static_python_build_probe is probe.parse_static_python_build_probe


def test_no_artifact_and_not_run_are_explicit_valid_states():
    payload = _vector(artifact=False, runtime="not-run")
    payload["build"].update(target_status="blocked", blocker="libffi")
    result = _parse(payload)
    assert result.artifact_sha256 is None
    assert result.artifact_size is None
    assert result.runtime_status == "not-run"
    assert result.build_status == "blocked"


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p.update(schema="other"), "schema"),
    (lambda p: p.update(probe_id="../path"), "probe_id"),
    (lambda p: p["artifact"].update(size=probe.MAX_STATIC_IMAGE_BYTES + 1), "integer"),
    (lambda p: p["artifact"]["elf"].update(pt_interp=1), "elf"),
    (lambda p: p["runtime"].update(failure=""), "runtime"),
    (lambda p: p["claims"].update(sealed_runtime=True), "claims"),
    (lambda p: p["build"].update(target_status="blocked"), "build"),
])
def test_invalid_probe_states_refuse(mutation, reason: str):
    payload = _vector()
    mutation(payload)
    with pytest.raises(probe.StaticPythonBuildProbeError) as caught:
        _parse(payload)
    assert caught.value.reason == "static_python_build_probe_" + reason


def test_blocked_build_requires_a_fixed_blocker():
    payload = _vector(artifact=False, runtime="not-run")
    payload["build"].update(target_status="blocked", blocker=None)
    with pytest.raises(probe.StaticPythonBuildProbeError, match="_build$"):
        _parse(payload)

    payload = _vector(artifact=False, runtime="not-run")
    payload["build"].update(blocker="libffi")
    with pytest.raises(probe.StaticPythonBuildProbeError, match="_build$"):
        _parse(payload)


def test_failed_runtime_requires_attempt_and_fixed_failure_label():
    payload = _vector()
    payload["runtime"].update(attempted=False)
    with pytest.raises(probe.StaticPythonBuildProbeError, match="_runtime$"):
        _parse(payload)

    payload = _vector()
    payload["runtime"].update(failure=None)
    with pytest.raises(probe.StaticPythonBuildProbeError, match="_runtime$"):
        _parse(payload)


def test_duplicate_and_noncanonical_json_refuse_without_context():
    payload = _vector()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    duplicate = raw[:-1] + b',"schema":"' + probe.BUILD_PROBE_SCHEMA.encode() + b'"}'
    with pytest.raises(probe.StaticPythonBuildProbeError) as caught:
        probe.parse_static_python_build_probe(duplicate)
    assert caught.value.reason == "static_python_build_probe_duplicate_key"
    pretty = json.dumps(payload, sort_keys=True, indent=2).encode()
    with pytest.raises(probe.StaticPythonBuildProbeError, match="_canonical$"):
        probe.parse_static_python_build_probe(pretty)


def test_parser_has_no_filesystem_or_process_effects(monkeypatch):
    payload = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert _parse(copy.deepcopy(payload)).runtime_status == "failed"


def test_raw_and_claim_failures_do_not_retain_input_context():
    payload = _vector()
    payload["probe_id"] = "x" * 129
    with pytest.raises(probe.StaticPythonBuildProbeError) as caught:
        _parse(payload)
    assert str(caught.value) == "static_python_build_probe_probe_id"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
