"""Focused tests for the detached F03 startup/loader comparison wire."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from lunar_evolution import static_python_runtime_startup as startup


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _record(path: str, label: str, *, size: int = 4096) -> dict:
    return {"path": path, "sha256": _sha(label), "size": size}


def _vector(case: str = "baseline") -> tuple[dict, dict[str, str]]:
    loader = {
        "pt_interp": case == "loader-negative",
        "dt_needed": False,
        "dependencies": [],
        "sealed_material_sha256": _sha("sealed-material"),
    }
    lifecycle = {
        "events": ["started", "loader_refused" if case == "loader-negative" else "exited"],
        "terminal": "loader_refused" if case == "loader-negative" else "exited",
    }
    payload = {
        "schema": startup.RUNTIME_STARTUP_SCHEMA,
        "installation_version": "synthetic-f03-v1",
        "build_closure_sha256": _sha("build-closure"),
        "binding_sha256": _sha("binding"),
        "launch_intent_sha256": _sha("launch-intent"),
        "fixture_case": case,
        "argv": ["bin/lunar-static", "--fixture"],
        "marker": {"name": "LUNAR_RSI_INPUT", "value": _sha("request")},
        "startup": {
            "exit_code": 0 if case == "baseline" else 127,
            "module": "lunar_static_main",
            "callable": "main",
            "stdout_sha256": _sha("stdout"),
            "stderr_sha256": _sha("stderr"),
        },
        "loader": loader,
        "owner": {
            "device": 2049,
            "inode": 4001,
            "mode": 0o755,
            "executable": _record("bin/lunar-static", "executable"),
        },
        "lifecycle": lifecycle,
        "claims": {name: False for name in startup._CLAIMS},
    }
    pins = {
        "expected_build_closure_sha256": payload["build_closure_sha256"],
        "expected_binding_sha256": payload["binding_sha256"],
        "expected_launch_intent_sha256": payload["launch_intent_sha256"],
    }
    return payload, pins


def _parse(payload: dict, pins: dict[str, str]) -> startup.StaticPythonRuntimeStartup:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return startup.parse_static_python_runtime_startup(raw, **pins)


@pytest.mark.parametrize("case,terminal", [("baseline", "exited"), ("loader-negative", "loader_refused")])
def test_valid_vectors_are_immutable_and_canonical(case: str, terminal: str):
    payload, pins = _vector(case)
    result = _parse(payload, pins)
    assert result.fixture_case == case
    assert result.terminal == terminal
    assert result.to_dict() == payload
    assert result.to_json() == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(AttributeError):
        result.terminal = "exited"  # type: ignore[misc]


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["build_closure_sha256"] == _sha("drift"), "pin"),
    (lambda p: p["loader"].update(pt_interp=True), "startup"),
    (lambda p: p["lifecycle"].update(terminal="loader_refused"), "startup"),
    (lambda p: p["claims"].update(owner_verified=True), "claims"),
    (lambda p: p["owner"].update(inode=0), "integer"),
    (lambda p: p["loader"].update(dependencies=["z.so", "a.so"]), "loader"),
])
def test_mutations_refuse(mutation, reason: str):
    payload, pins = _vector()
    if reason == "pin":
        payload["build_closure_sha256"] = _sha("drift")
    else:
        mutation(payload)
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        _parse(payload, pins)
    assert caught.value.reason == "static_python_runtime_startup_" + reason


def test_loader_negative_requires_a_loader_violation():
    payload, pins = _vector("loader-negative")
    payload["loader"]["pt_interp"] = False
    payload["loader"]["dt_needed"] = False
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        _parse(payload, pins)
    assert caught.value.reason.endswith("loader_negative")


def test_duplicate_key_and_noncanonical_bytes_refuse():
    payload, pins = _vector()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    duplicate = raw[:-1] + b',"schema":"' + startup.RUNTIME_STARTUP_SCHEMA.encode() + b'"}'
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        startup.parse_static_python_runtime_startup(duplicate, **pins)
    assert caught.value.reason.endswith("duplicate_key")

    pretty = json.dumps(payload, sort_keys=True, indent=2).encode()
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        startup.parse_static_python_runtime_startup(pretty, **pins)
    assert caught.value.reason.endswith("canonical")


def test_exact_types_bounds_and_no_external_effects(monkeypatch):
    payload, pins = _vector()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = _parse(payload, pins)
    assert result.installation_version == "synthetic-f03-v1"

    oversized = b" " * (startup.MAX_RUNTIME_STARTUP_BYTES + 1)
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        startup.parse_static_python_runtime_startup(oversized, **pins)
    assert caught.value.reason.endswith("raw")


def test_error_does_not_retain_input_or_parser_context():
    payload, pins = _vector()
    payload["marker"]["value"] = "x" * 64
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        _parse(copy.deepcopy(payload), pins)
    assert str(caught.value) == "static_python_runtime_startup_marker"
    assert "x" not in str(caught.value)
    assert caught.value.__cause__ is None
