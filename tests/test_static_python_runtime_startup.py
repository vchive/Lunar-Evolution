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
        "argv": ["bin/lunar-static", "--lunar-rsi-input-v1", _sha("request")],
        "marker": {"name": "--lunar-rsi-input-v1", "value": _sha("request")},
        "startup": {
            "exit_code": 0 if case == "baseline" else 127,
            "module": "_lunar_static_main",
            "callable": "_rsi_launch",
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
    (lambda p: p.update(build_closure_sha256=_sha("drift")), "pin"),
    (lambda p: p["loader"].update(pt_interp=True), "startup"),
    (lambda p: p["lifecycle"].update(terminal="loader_refused"), "lifecycle"),
    (lambda p: p["claims"].update(owner_verified=True), "claims"),
    (lambda p: p["owner"].update(inode=0), "integer"),
    (lambda p: p["loader"].update(dependencies=["z.so", "a.so"]), "loader"),
])
def test_mutations_refuse(mutation, reason: str):
    payload, pins = _vector()
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
    assert caught.value.__context__ is None


@pytest.mark.parametrize("argv", [
    ["bin/lunar-static"],
    ["bin/lunar-static", "--fixture"],
    ["bin/lunar-static", "-c", _sha("request")],
    ["bin/lunar-static", "-m", _sha("request")],
    ["bin/lunar-static", _sha("request"), "--lunar-rsi-input-v1"],
    ["bin/lunar-static", "--lunar-rsi-input-v1", _sha("drift")],
    ["bin/lunar-static", "--lunar-rsi-input-v1", _sha("request"), "extra"],
])
def test_os_argv_must_follow_reviewed_launcher(argv):
    payload, pins = _vector()
    payload["argv"] = argv
    with pytest.raises(startup.StaticPythonRuntimeStartupError, match="_argv$"):
        _parse(payload, pins)


@pytest.mark.parametrize("field,value,reason", [
    ("module", "other_module", "entrypoint"),
    ("callable", "main", "entrypoint"),
    ("exit_code", 1, "startup"),
    ("exit_code", True, "integer"),
])
def test_baseline_cannot_select_another_entrypoint_or_claim_failed_startup(field, value, reason):
    payload, pins = _vector()
    payload["startup"][field] = value
    with pytest.raises(startup.StaticPythonRuntimeStartupError, match="_" + reason + "$"):
        _parse(payload, pins)


@pytest.mark.parametrize("mutation,reason", [
    (lambda p: p["owner"]["executable"].update(path="bin/decoy"), "owner"),
    (lambda p: p["owner"].update(mode=0o644), "owner"),
    (lambda p: p["lifecycle"].update(events=["started"]), "lifecycle"),
    (lambda p: p["lifecycle"].update(events=["exited", "started"]), "lifecycle"),
    (lambda p: p["lifecycle"].update(events=["started", "started", "exited"]), "lifecycle"),
])
def test_executable_and_lifecycle_must_match_launch(mutation, reason):
    payload, pins = _vector()
    mutation(payload)
    with pytest.raises(startup.StaticPythonRuntimeStartupError, match="_" + reason + "$"):
        _parse(payload, pins)


def test_loader_negative_cannot_report_success_exit():
    payload, pins = _vector("loader-negative")
    payload["startup"]["exit_code"] = 0
    with pytest.raises(startup.StaticPythonRuntimeStartupError, match="_loader_negative$"):
        _parse(payload, pins)


def test_json_failure_has_no_retained_decode_context():
    _, pins = _vector()
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        startup.parse_static_python_runtime_startup(b'{"private":"never",', **pins)
    assert str(caught.value) == "static_python_runtime_startup_json"
    assert caught.value.__cause__ is caught.value.__context__ is None


@pytest.mark.parametrize(
    "stderr,code",
    [
        (
            (b"Fatal Python error: Failed to import encodings module\n"
             b"ModuleNotFoundError: No module named 'encodings'\n"),
            "missing_encodings",
        ),
        (b"Fatal Python error: Failed to import _frozen_importlib\n", "missing_import_bootstrap"),
        (b"Could not find platform independent libraries <prefix>\n", "getpath_configuration"),
        (b"compiler output without a known bootstrap marker\n", "unknown_startup_failure"),
        (b"", "no_stderr"),
    ],
)
def test_startup_diagnostic_classifies_known_bootstrap_failures_without_claims(stderr, code):
    result = startup.diagnose_static_python_runtime_startup(
        stderr, expected_stderr_sha256=hashlib.sha256(stderr).hexdigest(),
    )
    payload = result.to_dict()
    assert result.failure_code == payload["failure_code"] == code
    assert payload["schema"] == startup.RUNTIME_STARTUP_DIAGNOSTIC_SCHEMA
    assert payload["phase"] == "startup"
    assert payload["stderr_size"] == len(stderr)
    assert payload["stderr_sha256"] == hashlib.sha256(stderr).hexdigest()
    assert payload["claims"] == {"production_admission": False, "runtime_execution_performed": False}
    assert result.to_json() == json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


@pytest.mark.parametrize(
    "stderr,expected,reason",
    [
        (b"stderr is retained by digest only", _sha("different"), "stderr_pin"),
        (b"x" * (startup.MAX_RUNTIME_STARTUP_DIAGNOSTIC_BYTES + 1), _sha("oversized"), "diagnostic_raw"),
    ],
)
def test_startup_diagnostic_rejects_stale_or_oversized_stderr(stderr, expected, reason):
    with pytest.raises(startup.StaticPythonRuntimeStartupError) as caught:
        startup.diagnose_static_python_runtime_startup(
            stderr, expected_stderr_sha256=expected,
        )
    assert caught.value.reason == "static_python_runtime_startup_" + reason


def test_startup_diagnostic_does_not_retain_stderr_content_or_execute(monkeypatch):
    stderr = b"private marker that must not be retained"
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    result = startup.diagnose_static_python_runtime_startup(
        stderr, expected_stderr_sha256=hashlib.sha256(stderr).hexdigest(),
    )
    assert "private marker" not in result.to_json().decode()
