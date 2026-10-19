"""Provider-free Feature189/193 contract composition tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from lunar_evolution import static_python_acceptance as acceptance
from lunar_evolution.static_python_build_closure import StaticPythonBuildClosure
from lunar_evolution.static_python_input_result import StaticPythonInputResult
from lunar_evolution.static_python_rsi_installation import StaticPythonRSIInstallationDescriptor
from lunar_evolution.static_python_runtime_handoff import StaticPythonRuntimeHandoff
from lunar_evolution.static_python_runtime_startup import StaticPythonRuntimeStartup


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _raw(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _bundle() -> tuple[
    StaticPythonRSIInstallationDescriptor,
    StaticPythonBuildClosure,
    StaticPythonRuntimeStartup,
    StaticPythonInputResult,
    StaticPythonRuntimeHandoff,
]:
    version = "fixture-rsi-v1"
    install_payload = {
        "schema": "lunar-static-python-rsi-installation-contract-v1",
        "descriptor": {"installation_version": version},
        "claims": {name: False for name in (
            "configured_closure_verified", "compilation_performed", "freezer_performed",
            "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
            "runtime_load_protection", "production_admission", "general_code_origin_protection",
        )},
    }
    install_raw = _raw(install_payload)
    installation = StaticPythonRSIInstallationDescriptor(
        install_raw, _sha(install_raw.decode()), _sha("descriptor"), version,
        _sha("artifact"), _sha("frozen"), _sha("main-header"),
    )
    build_payload = {
        "schema": "lunar-static-python-build-closure-v1",
        "installation_version": version,
        "claims": {name: False for name in (
            "configured_closure_verified", "compilation_performed", "freezer_performed",
            "link_performed", "artifact_verified", "runtime_execution_performed",
            "installation_accepted", "input_consumption_verified", "runtime_load_protection",
            "production_admission", "general_code_origin_protection",
        )},
    }
    build_raw = _raw(build_payload)
    build = StaticPythonBuildClosure(
        build_raw, _sha(build_raw.decode()), _sha("source"), _sha("toolchain"),
        _sha("inventory"), _sha("link"), _sha("artifact"), version,
        ("_lunar_static_main",),
    )
    startup_payload = {
        "schema": "lunar-static-python-runtime-startup-v1",
        "installation_version": version,
        "build_closure_sha256": build.contract_sha256,
        "claims": {name: False for name in (
            "startup_performed", "loader_negative_verified", "owner_verified", "production_admission",
        )},
    }
    startup_raw = _raw(startup_payload)
    startup = StaticPythonRuntimeStartup(startup_raw, version, "baseline", "exited")
    startup_sha = _sha(startup_raw.decode())
    input_payload = {
        "schema": "lunar-static-python-input-result-v1",
        "startup_sha256": startup_sha,
        "build_closure_sha256": build.contract_sha256,
        "claims": {name: False for name in (
            "input_authority_verified", "runtime_execution_verified", "solver_result_accepted",
            "memory_use_verified", "production_admission",
        )},
    }
    input_raw = _raw(input_payload)
    input_sha = _sha(input_raw.decode())
    input_result = StaticPythonInputResult(
        input_raw, startup_sha, build.contract_sha256, _sha("binding"), _sha("launch"),
        "lunar-static-python-rsi-input-read-report-v1", _sha("manifest"), _sha("report"),
        _sha("request"), _sha("memory"), 10, 20, 285,
    )
    handoff_payload = {
        "schema": "lunar-static-python-runtime-handoff-v1",
        "startup_sha256": startup_sha,
        "input_result_sha256": input_sha,
        "terminal_state": "completed",
        "publication_state": "prepared",
        "claims": {name: False for name in (
            "runtime_startup_verified", "input_result_verified", "terminal_verified",
            "publication_ready", "recovery_verified", "production_admission",
        )},
    }
    handoff_raw = _raw(handoff_payload)
    handoff = StaticPythonRuntimeHandoff(
        handoff_raw, _sha("handoff-pin"), "completed", "prepared", 8, 1,
    )
    return installation, build, startup, input_result, handoff


def test_composition_returns_provider_free_false_claim_summary():
    bundle = _bundle()
    result = acceptance.compose_static_python_provider_free_acceptance(
        installation=bundle[0], build=bundle[1], startup=bundle[2],
        input_result=bundle[3], handoff=bundle[4],
    )
    summary = result.to_dict()
    assert summary["schema"] == acceptance.ACCEPTANCE_SCHEMA
    assert summary["fixture_case"] == "baseline"
    assert summary["terminal_state"] == "completed"
    assert summary["live_acceptance_ready"] is False
    assert summary["production_admission"] is False
    assert result.summary_sha256 == _sha(result.canonical_bytes.decode())


@pytest.mark.parametrize("mutation,reason", [
    ("input_result", "linkage"), ("handoff", "linkage"),
])
def test_cross_contract_digest_drift_refuses(mutation: str, reason: str):
    installation, build, startup, input_result, handoff = _bundle()
    if mutation == "input_result":
        input_result = replace(input_result, startup_sha256=_sha("drift"))
    else:
        payload = handoff.to_dict()
        payload["startup_sha256"] = _sha("drift")
        handoff = replace(handoff, canonical_bytes=_raw(payload))
    with pytest.raises(acceptance.StaticPythonAcceptanceError) as caught:
        acceptance.compose_static_python_provider_free_acceptance(
            installation=installation, build=build, startup=startup,
            input_result=input_result, handoff=handoff,
        )
    assert caught.value.reason == "static_python_acceptance_" + reason


def test_nonbaseline_or_capability_claim_is_never_ready():
    installation, build, startup, input_result, handoff = _bundle()
    with pytest.raises(acceptance.StaticPythonAcceptanceError, match="_fixture_case$"):
        acceptance.compose_static_python_provider_free_acceptance(
            installation=installation, build=build,
            startup=replace(startup, fixture_case="loader-negative"),
            input_result=input_result, handoff=handoff,
        )
    payload = installation.to_dict()
    payload["claims"]["production_admission"] = True
    changed = _raw(payload)
    with pytest.raises(acceptance.StaticPythonAcceptanceError, match="_claims$"):
        acceptance.compose_static_python_provider_free_acceptance(
            installation=replace(installation, canonical_bytes=changed, contract_sha256=_sha(changed.decode())),
            build=build, startup=startup, input_result=input_result, handoff=handoff,
        )


def test_composition_is_filesystem_and_process_free(monkeypatch):
    bundle = _bundle()
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))
    assert acceptance.compose_static_python_provider_free_acceptance(
        installation=bundle[0], build=bundle[1], startup=bundle[2],
        input_result=bundle[3], handoff=bundle[4],
    ).live_acceptance_ready is False
