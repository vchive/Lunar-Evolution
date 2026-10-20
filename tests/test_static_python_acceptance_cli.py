"""Detached static-Python acceptance CLI remains provider-free and read-only."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution import cli

_SECTIONS = ("installation", "build", "startup", "input_result", "handoff")
_PIN_KEYS = {
    "installation": (
        "contract_sha256", "descriptor_sha256", "installation_version",
        "artifact_sha256", "frozen_inventory_sha256", "main_header_sha256",
    ),
    "build": (
        "contract_sha256", "source_tree_sha256", "toolchain_manifest_sha256",
        "frozen_inventory_sha256", "link_manifest_sha256", "artifact_sha256",
        "installation_version", "installation_contract_sha256",
        "installation_descriptor_sha256", "installation_frozen_inventory_sha256",
        "main_header_sha256",
    ),
    "startup": ("build_closure_sha256", "binding_sha256", "launch_intent_sha256"),
    "input_result": (
        "startup_sha256", "build_closure_sha256", "binding_sha256", "launch_intent_sha256",
        "manifest_sha256", "report_sha256", "request_sha256", "memory_sha256",
        "request_size", "memory_size",
    ),
    "handoff": (
        "startup_sha256", "input_result_sha256", "terminal_sha256", "handoff_sha256",
        "binding_sha256", "launch_intent_sha256", "result_sha256",
        "publication_intent_sha256", "request_budget", "request_count",
        "wall_timeout_seconds", "deadline_unix", "terminal_state", "cleanup_status",
        "publication_state",
    ),
}


def _write(path: Path, value: object) -> None:
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _fixture(tmp_path: Path) -> tuple[list[Path], Path]:
    paths = []
    for name in _SECTIONS:
        path = tmp_path / f"{name}.json"
        _write(path, {})
        paths.append(path)
    pins = {"schema": "lunar-static-python-provider-free-acceptance-pins-v1"}
    for section, keys in _PIN_KEYS.items():
        pins[section] = {key: (1 if key.endswith(("size", "budget", "count")) else 1.0 if key.endswith(("seconds", "unix")) else "a" * 64) for key in keys}
        if section == "input_result":
            pins[section]["request_size"] = pins[section]["memory_size"] = 1
        if section == "handoff":
            pins[section]["request_budget"] = pins[section]["request_count"] = 1
            pins[section]["wall_timeout_seconds"] = pins[section]["deadline_unix"] = 1.0
            pins[section]["terminal_state"] = "completed"
            pins[section]["cleanup_status"] = "already_exited"
            pins[section]["publication_state"] = "prepared"
    pins_path = tmp_path / "pins.json"
    _write(pins_path, pins)
    return paths, pins_path


def test_static_python_acceptance_is_detached_and_always_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    paths, pins = _fixture(tmp_path)
    # Keep this test focused on CLI composition/wiring. The DTO parsers and
    # composition seam are covered by test_static_python_acceptance.py.
    import lunar_evolution.static_python_acceptance as acceptance
    import lunar_evolution.static_python_build_closure as build
    import lunar_evolution.static_python_input_result as input_result
    import lunar_evolution.static_python_rsi_installation as installation
    import lunar_evolution.static_python_runtime_handoff as handoff
    import lunar_evolution.static_python_runtime_startup as startup

    fake_result = SimpleNamespace(
        summary_sha256="b" * 64,
        to_dict=lambda: {"schema": acceptance.ACCEPTANCE_SCHEMA, "live_acceptance_ready": False},
    )
    monkeypatch.setattr(installation, "parse_static_python_rsi_installation_descriptor", lambda *a, **k: object())
    monkeypatch.setattr(build, "parse_static_python_build_closure", lambda *a, **k: object())
    monkeypatch.setattr(startup, "parse_static_python_runtime_startup", lambda *a, **k: object())
    monkeypatch.setattr(input_result, "parse_static_python_input_result", lambda *a, **k: object())
    monkeypatch.setattr(handoff, "parse_static_python_runtime_handoff", lambda *a, **k: object())
    monkeypatch.setattr(acceptance, "compose_static_python_provider_free_acceptance", lambda **k: fake_result)
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("detached command initialized state"))

    assert cli.main([
        "rsi", "static-python-acceptance", *(str(path) for path in paths),
        "--pins", str(pins), "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == acceptance.ACCEPTANCE_SCHEMA
    assert payload["status"] == "blocked"
    assert payload["reason"] == "provider_free_only"
    assert payload["summary_sha256"] == "b" * 64
    assert payload["read_only"] is True
    assert payload["live_acceptance_ready"] is False
    assert payload["production_admission"] is False
    assert payload["online_publication"] is False
    assert not (tmp_path / "home").exists()


def test_static_python_acceptance_rejects_noncanonical_pins_before_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    paths, pins = _fixture(tmp_path)
    pins.write_text(json.dumps(json.loads(pins.read_text()), indent=2), encoding="utf-8")
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("detached command initialized state"))

    assert cli.main([
        "rsi", "static-python-acceptance", *(str(path) for path in paths),
        "--pins", str(pins), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "static_python_acceptance_pins_invalid"}
    assert not (tmp_path / "home").exists()


@pytest.mark.parametrize("mutation", ["extra", "missing"])
def test_static_python_acceptance_rejects_non_exact_pin_section_keys_before_state(
    tmp_path: Path,
    mutation: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths, pins_path = _fixture(tmp_path)
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    if mutation == "extra":
        pins["startup"]["unexpected"] = "a" * 64
    else:
        del pins["startup"]["binding_sha256"]
    _write(pins_path, pins)
    monkeypatch.setattr(cli, "_config", lambda *_a, **_k: pytest.fail("detached command initialized state"))

    assert cli.main([
        "rsi", "static-python-acceptance", *(str(path) for path in paths),
        "--pins", str(pins_path), "--json",
    ]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "static_python_acceptance_pins_invalid"}
    assert not (tmp_path / "home").exists()
