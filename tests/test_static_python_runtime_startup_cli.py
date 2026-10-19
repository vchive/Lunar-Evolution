"""CLI coverage for detached static-Python startup receipts."""

from __future__ import annotations

import hashlib
import json

from lunar_evolution.cli import main
from lunar_evolution.static_python_runtime_startup import RUNTIME_STARTUP_SCHEMA


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _receipt() -> tuple[dict[str, object], dict[str, str]]:
    pins = {
        "expected_build_closure_sha256": _sha("build"),
        "expected_binding_sha256": _sha("binding"),
        "expected_launch_intent_sha256": _sha("launch"),
    }
    request = _sha("request")
    payload = {
        "schema": RUNTIME_STARTUP_SCHEMA,
        "installation_version": "synthetic-f03-v1",
        "build_closure_sha256": pins["expected_build_closure_sha256"],
        "binding_sha256": pins["expected_binding_sha256"],
        "launch_intent_sha256": pins["expected_launch_intent_sha256"],
        "fixture_case": "baseline",
        "argv": ["bin/lunar-static", "--lunar-rsi-input-v1", request],
        "marker": {"name": "--lunar-rsi-input-v1", "value": request},
        "startup": {
            "exit_code": 0,
            "module": "_lunar_static_main",
            "callable": "_rsi_launch",
            "stdout_sha256": _sha("stdout"),
            "stderr_sha256": _sha("stderr"),
        },
        "loader": {
            "pt_interp": False,
            "dt_needed": False,
            "dependencies": [],
            "sealed_material_sha256": _sha("sealed"),
        },
        "owner": {
            "device": 2049,
            "inode": 4001,
            "mode": 0o755,
            "executable": {"path": "bin/lunar-static", "sha256": _sha("exe"), "size": 4096},
        },
        "lifecycle": {"events": ["started", "exited"], "terminal": "exited"},
        "claims": {
            "startup_performed": False,
            "loader_negative_verified": False,
            "owner_verified": False,
            "production_admission": False,
        },
    }
    return payload, pins


def test_inspect_runtime_startup_emits_detached_observation(tmp_path, capsys):
    payload, pins = _receipt()
    receipt_path = tmp_path / "startup.json"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    receipt_path.write_bytes(raw)
    arguments = [
        "inspect-static-python-runtime-startup", str(receipt_path), "--json",
        "--expected-build-closure-sha256", pins["expected_build_closure_sha256"],
        "--expected-binding-sha256", pins["expected_binding_sha256"],
        "--expected-launch-intent-sha256", pins["expected_launch_intent_sha256"],
    ]

    assert main(arguments) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["status"] == "observed"
    assert observed["fixture_case"] == "baseline"
    assert observed["terminal"] == "exited"
    assert observed["production_admission"] is False
    assert observed["receipt_sha256"] == hashlib.sha256(raw).hexdigest()


def test_inspect_runtime_startup_refuses_pin_drift_without_home(tmp_path, capsys):
    payload, pins = _receipt()
    receipt_path = tmp_path / "startup.json"
    receipt_path.write_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    arguments = [
        "inspect-static-python-runtime-startup", str(receipt_path), "--json",
        "--expected-build-closure-sha256", _sha("drift"),
        "--expected-binding-sha256", pins["expected_binding_sha256"],
        "--expected-launch-intent-sha256", pins["expected_launch_intent_sha256"],
    ]

    assert main(arguments) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "static_python_runtime_startup_pin"}
    assert not (tmp_path / ".lunar-evolution").exists()
