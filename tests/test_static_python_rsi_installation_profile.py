"""Pure RSI source-input preparation; no CPython build or runtime acceptance."""

from __future__ import annotations

import builtins
import copy
import datetime
import hashlib
import io
import json
import os
import socket
import subprocess
import time
import urllib.request
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from lunar_evolution import static_python_installation as installation
from tools.static_python_fixture.build_inputs import (
    StaticPythonBuildInputsError,
    emit_static_python_build_inputs,
)
from tools.static_python_fixture.profile import CONFIG, PRECONFIG
from tools.static_python_rsi_fixture import installation_profile as profile
from tools.static_python_rsi_fixture.recipe import emit_rsi_launch_source_plan

_ROOT = Path(__file__).resolve().parents[1]
_BASE_SHA = "6e2d35188aadc5e00f2d6eb98e90b2f9e34f3a425c8f3575b759f52c3e38ba5c"
_OVERLAY_SHA = "91d808742d567a79b2deca48e977fd696771904e0c6c059a94ffa4274ea599e8"
_PLAN_SHA = "bd95a2c120821d5ff4b72cae740e3abc85ee747881c13aa43ffddd9bd4197175"
_ASSETS = (
    "launcher.c", "pipe.c", "profile.c", "getpath.c", "lunar_fixture_profile.h", "frozen_main.py",
)
_CLAIMS = {
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
}


@pytest.fixture(scope="module")
def reviewed_inputs(tmp_path_factory: pytest.TempPathFactory) -> dict:
    # Source emission is fixture setup, outside the pure preparation call.
    manifest = emit_rsi_launch_source_plan(tmp_path_factory.mktemp("profile-inputs") / "source-plan")
    base = (_ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes()
    overlay = (_ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes()
    plan = manifest.read_bytes()
    assert (len(base), hashlib.sha256(base).hexdigest()) == (80050, _BASE_SHA)
    assert (len(overlay), hashlib.sha256(overlay).hexdigest()) == (2456, _OVERLAY_SHA)
    assert (len(plan), hashlib.sha256(plan).hexdigest()) == (6706, _PLAN_SHA)
    return {
        "reviewed_build_inputs": base,
        "reviewed_overlay": overlay,
        "source_plan": plan,
        "expected_source_plan_sha256": _PLAN_SHA,
        "source_assets": {name: (manifest.parent / "assets" / name).read_bytes() for name in _ASSETS},
    }


@pytest.fixture
def inputs(reviewed_inputs: dict) -> dict:
    return {**reviewed_inputs, "source_assets": reviewed_inputs["source_assets"].copy()}


def _wire(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("ascii")


def _refuse(inputs: dict) -> None:
    with pytest.raises(profile.RSIProfilePreparationError, match="^static_python_rsi_profile_"):
        profile.prepare_rsi_installation_profile(**inputs)


def _bomb(*_args, **_kwargs):
    raise AssertionError("caller callback or external side effect must not run")


class _BytesSubclass(bytes):
    __len__ = _bomb
    __bytes__ = _bomb
    __iter__ = _bomb


class _StringSubclass(str):
    __len__ = _bomb
    __iter__ = _bomb
    encode = _bomb


class _DictSubclass(dict):
    __len__ = _bomb
    __iter__ = _bomb
    items = _bomb
    copy = _bomb
    __getitem__ = _bomb
    __contains__ = _bomb
    get = _bomb
    keys = _bomb
    values = _bomb


class _Clock:
    now = _bomb
    utcnow = _bomb
    today = _bomb


def test_deterministic_canonical_immutable_result_and_detached_inputs(inputs: dict):
    before = copy.deepcopy(inputs)
    result = profile.prepare_rsi_installation_profile(**inputs)
    replay = profile.prepare_rsi_installation_profile(**inputs)
    assert type(result) is profile.RSIProfilePreparation
    assert type(result.wire_bytes) is bytes
    assert result == replay
    assert result.sha256 == hashlib.sha256(result.wire_bytes).hexdigest()
    assert result.wire_bytes == _wire(json.loads(result.wire_bytes))
    assert inputs == before
    with pytest.raises(FrozenInstanceError):
        result.wire_bytes = b"replacement"
    with pytest.raises((AttributeError, TypeError)):
        result.sha256 = "a" * 64
    detached = json.loads(result.wire_bytes)
    detached["claims"]["production_admission"] = True
    inputs["source_assets"]["launcher.c"] = b"replacement"
    assert json.loads(result.wire_bytes)["claims"]["production_admission"] is False
    assert result == replay


def test_exactly_two_complete_record_substitutions_preserve_every_other_field(inputs: dict):
    original = emit_static_python_build_inputs(inputs["reviewed_build_inputs"])
    output = json.loads(profile.prepare_rsi_installation_profile(**inputs).wire_bytes)
    overlay = json.loads(inputs["reviewed_overlay"])
    candidate = output["candidate_build_inputs"]
    assert output["schema"] == "lunar-static-python-rsi-installation-profile-preparation-v1"
    assert candidate["schema"] == "lunar-static-python-rsi-build-input-candidate-v1"
    assert output["profile"] == "rsi-marker-launch-v1"
    assert output["substitutions"] == overlay["substitutions"]
    assert output["base_reviewed_inputs"] == {"size": 80050, "sha256": _BASE_SHA}
    assert output["reviewed_overlay"] == {"size": 2456, "sha256": _OVERLAY_SHA}
    assert output["source_plan"] == {"size": 6706, "sha256": _PLAN_SHA}
    restored = copy.deepcopy(candidate)
    restored["schema"] = original["schema"]
    changed_records = []
    for section in ("target_units", "freeze_tasks"):
        assert len(candidate[section]) == len(original[section])
        changed_records.extend((section, index) for index, (old, new) in enumerate(
            zip(original[section], candidate[section], strict=True),
        ) if old != new)
    assert len(changed_records) == 2
    for change in output["substitutions"]:
        section, key, value = change["section"], change["key"], change["value"]
        index = next(i for i, record in enumerate(original[section]) if record[key] == value)
        assert (section, index) in changed_records
        assert original[section][index] == change["before"]
        assert candidate[section][index] == change["after"]
        restored[section][index] = change["before"]
    assert restored == original
    assert len(candidate["shared_units"]) == 162
    assert len(candidate["freezer_units"]) == 2
    assert len(candidate["target_units"]) == 4
    assert len(candidate["freeze_tasks"]) == 9
    assert len(candidate["generated_sources"]) == 4
    assert len(candidate["fixture_headers"]) == 1


def test_fixed_python_vectors_and_os_marker_policy_remain_separate(inputs: dict):
    output = json.loads(profile.prepare_rsi_installation_profile(**inputs).wire_bytes)
    plan = json.loads(inputs["source_plan"])
    assert output["initialization_profile"] == plan["initialization_profile"]
    assert output["initialization_profile"]["preconfig"] == PRECONFIG
    assert output["initialization_profile"]["config"] == CONFIG
    assert output["initialization_profile"]["config"]["argv"] == ["lunar-static-python-fixture"]
    assert output["initialization_profile"]["config"]["orig_argv"] == [
        "lunar-static-python-fixture",
    ]
    assert output["launch_policy"] == {
        "argc": 3, "marker": "--lunar-rsi-input-v1", "marker_index": 1,
        "manifest_digest_index": 2, "manifest_digest_syntax": "[0-9a-f]{64}",
        "frozen_entrypoint": "_rsi_launch", "baseline_case": "baseline",
        "environment_selector": False, "input_reads": [],
    }


def test_pending_headers_have_no_generated_digest_or_build_runtime_admission_claim(inputs: dict):
    output = json.loads(profile.prepare_rsi_installation_profile(**inputs).wire_bytes)
    candidate = output["candidate_build_inputs"]
    assert set(output) == {
        "schema", "profile", "base_reviewed_inputs", "reviewed_overlay", "source_plan",
        "launch_policy", "initialization_profile", "substitutions", "candidate_build_inputs",
        "pending_frozen_headers", "claims", "artifact_state", "startup_state",
    }
    assert len(output["pending_frozen_headers"]) == 9
    for header, task in zip(output["pending_frozen_headers"], candidate["freeze_tasks"], strict=True):
        assert header == {
            "name": task["name"], "output": task["output"],
            "source_sha256": task["source_sha256"], "state": "pending-freezer",
        }
        assert not ({"sha256", "header_sha256", "generated_sha256", "size"} & set(header))
    main_header = next(item for item in output["pending_frozen_headers"]
                       if item["name"] == "_lunar_static_main")
    assert main_header["source_sha256"] == (
        "e1285d5a8308209067630e9135d828737019b30533701ea86efe859b6461b7f6"
    )
    assert set(output["claims"]) == _CLAIMS
    assert all(value is False for value in output["claims"].values())
    assert all(value is False for value in candidate["states"].values())
    assert output["artifact_state"] == "pending-builder"
    assert output["startup_state"] == "not-executed"


@pytest.mark.parametrize("name", _ASSETS)
@pytest.mark.parametrize("mutation", ["same-size", "truncated", "appended"])
def test_each_source_asset_pin_refuses_drift(inputs: dict, name: str, mutation: str):
    raw = inputs["source_assets"][name]
    if mutation == "same-size":
        raw = bytes([raw[0] ^ 1]) + raw[1:]
    elif mutation == "truncated":
        raw = raw[:-1]
    else:
        raw += b"\n"
    inputs["source_assets"][name] = raw
    _refuse(inputs)


@pytest.mark.parametrize("field", ["reviewed_build_inputs", "reviewed_overlay", "source_plan"])
@pytest.mark.parametrize("kind", ["bytearray", "memoryview", "text", "subclass", "none"])
def test_input_buffers_require_exact_bytes_before_caller_callbacks(
    inputs: dict, field: str, kind: str,
):
    raw = inputs[field]
    inputs[field] = {
        "bytearray": bytearray(raw), "memoryview": memoryview(raw), "text": raw.decode("ascii"),
        "subclass": _BytesSubclass(raw), "none": None,
    }[kind]
    _refuse(inputs)


@pytest.mark.parametrize("field,maximum", [
    ("reviewed_build_inputs", 128 * 1024), ("reviewed_overlay", 8 * 1024),
    ("source_plan", 16 * 1024),
])
@pytest.mark.parametrize("overflow", [False, True])
def test_buffer_bounds_refuse_before_hash_or_json(
    inputs: dict, monkeypatch: pytest.MonkeyPatch, field: str, maximum: int, overflow: bool,
):
    inputs[field] = b"x" * (maximum + 1) if overflow else b""
    with monkeypatch.context() as guard:
        guard.setattr(hashlib, "sha256", _bomb)
        guard.setattr(json, "loads", _bomb)
        _refuse(inputs)


@pytest.mark.parametrize("pin", [
    None, True, b"a" * 64, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64,
    "é" * 64, "a" * 63 + "\n", _StringSubclass(_PLAN_SHA),
], ids=["none", "boolean", "bytes", "empty", "short", "long", "uppercase", "nonhex",
        "unicode", "newline", "subclass"])
def test_malformed_caller_pin_refuses_before_hash_or_json(
    inputs: dict, monkeypatch: pytest.MonkeyPatch, pin: object,
):
    inputs["expected_source_plan_sha256"] = pin
    with monkeypatch.context() as guard:
        guard.setattr(hashlib, "sha256", _bomb)
        guard.setattr(json, "loads", _bomb)
        _refuse(inputs)


@pytest.mark.parametrize("pin", ["0" * 64, "f" * 64, "a" * 64])
def test_well_formed_unreviewed_caller_pin_is_not_authority(inputs: dict, pin: str):
    inputs["expected_source_plan_sha256"] = pin
    _refuse(inputs)


@pytest.mark.parametrize("kind", [
    "subclass-map", "list-map", "missing", "extra", "unknown", "prefixed", "subclass-key",
    "long-key", "integer-key", "bytearray-value", "memoryview-value", "subclass-value",
    "empty-value", "overflow-value", "none-value",
])
def test_asset_map_types_names_and_bounds_refuse_before_hash_or_json(
    inputs: dict, monkeypatch: pytest.MonkeyPatch, kind: str,
):
    assets = inputs["source_assets"]
    if kind == "subclass-map":
        inputs["source_assets"] = _DictSubclass(assets)
    elif kind == "list-map":
        inputs["source_assets"] = list(assets.items())
    elif kind == "missing":
        assets.pop("launcher.c")
    elif kind == "extra":
        assets["extra.c"] = b"x"
    elif kind in {"unknown", "prefixed", "subclass-key", "long-key", "integer-key"}:
        key = {
            "unknown": "other.c", "prefixed": "assets/launcher.c",
            "subclass-key": _StringSubclass("launcher.c"), "long-key": "x" * 65,
            "integer-key": 1,
        }[kind]
        assets[key] = assets.pop("launcher.c")
    else:
        raw = assets["launcher.c"]
        assets["launcher.c"] = {
            "bytearray-value": bytearray(raw), "memoryview-value": memoryview(raw),
            "subclass-value": _BytesSubclass(raw), "empty-value": b"",
            "overflow-value": b"x" * (16 * 1024 + 1), "none-value": None,
        }[kind]
    with monkeypatch.context() as guard:
        guard.setattr(hashlib, "sha256", _bomb)
        guard.setattr(json, "loads", _bomb)
        _refuse(inputs)


@pytest.mark.parametrize("field", ["reviewed_build_inputs", "reviewed_overlay", "source_plan"])
@pytest.mark.parametrize("raw", [
    b"null", b"[]", b"{", b"\xff", b'{"duplicate":1,"duplicate":2}',
    b'{"number":NaN}', b'{"number":Infinity}', b"[" * 2000 + b"]" * 2000,
])
def test_malformed_duplicate_nonfinite_or_deep_json_never_bypasses_fixed_pins(
    inputs: dict, field: str, raw: bytes,
):
    inputs[field] = raw
    if field == "source_plan":
        inputs["expected_source_plan_sha256"] = hashlib.sha256(raw).hexdigest()
    _refuse(inputs)


@pytest.mark.parametrize("field", ["reviewed_build_inputs", "reviewed_overlay", "source_plan"])
def test_same_size_reviewed_input_drift_refuses(inputs: dict, field: str):
    raw = inputs[field]
    inputs[field] = bytes([raw[0] ^ 1]) + raw[1:]
    _refuse(inputs)


@pytest.mark.parametrize("mutation", ["asset-pin", "argv", "orig-argv", "claims", "marker"])
def test_resigned_source_plan_cannot_authorize_changed_payload_or_launch_policy(
    inputs: dict, mutation: str,
):
    plan = json.loads(inputs["source_plan"])
    if mutation == "asset-pin":
        inputs["source_assets"]["launcher.c"] += b"/* attacker-supplied source */\n"
        record = next(item for item in plan["emitted_sources"] if item["path"] == "assets/launcher.c")
        raw = inputs["source_assets"]["launcher.c"]
        record.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    elif mutation in {"argv", "orig-argv"}:
        plan["initialization_profile"]["config"][mutation.replace("-", "_")] = ["-c", "pass"]
    elif mutation == "claims":
        plan["claims"]["installation_accepted"] = True
    else:
        plan["launch_policy"]["marker"] = "--caller-controlled"
    inputs["source_plan"] = _wire(plan)
    inputs["expected_source_plan_sha256"] = hashlib.sha256(inputs["source_plan"]).hexdigest()
    _refuse(inputs)


@pytest.mark.parametrize("mutation", ["source-plan", "base", "before", "after", "extra"])
def test_resigned_overlay_cannot_replace_independently_reviewed_authority(
    inputs: dict, mutation: str,
):
    overlay = json.loads(inputs["reviewed_overlay"])
    if mutation == "source-plan":
        plan = json.loads(inputs["source_plan"])
        plan["launch_policy"]["input_reads"] = ["caller-path"]
        inputs["source_plan"] = _wire(plan)
        inputs["expected_source_plan_sha256"] = hashlib.sha256(inputs["source_plan"]).hexdigest()
        overlay["source_plan"] = {
            "size": len(inputs["source_plan"]), "sha256": inputs["expected_source_plan_sha256"],
        }
    elif mutation == "base":
        base = json.loads(inputs["reviewed_build_inputs"])
        base["target_units"][0]["extra_flags"] = ["-caller-controlled"]
        inputs["reviewed_build_inputs"] = _wire(base)
        overlay["base"] = {
            "size": len(inputs["reviewed_build_inputs"]),
            "sha256": hashlib.sha256(inputs["reviewed_build_inputs"]).hexdigest(),
        }
    elif mutation in {"before", "after"}:
        overlay["substitutions"][0][mutation]["source_sha256"] = "a" * 64
    else:
        overlay["substitutions"].append(copy.deepcopy(overlay["substitutions"][0]))
    inputs["reviewed_overlay"] = _wire(overlay)
    _refuse(inputs)


def test_caller_asset_map_replacement_after_validation_cannot_change_snapshot(
    inputs: dict, monkeypatch: pytest.MonkeyPatch,
):
    expected = profile.prepare_rsi_installation_profile(**inputs)
    original_pin = profile._pin
    changed = False

    def replace_caller_map_after_validation(raw: bytes, size: int, digest: str) -> None:
        nonlocal changed
        if not changed:
            changed = True
            inputs["source_assets"].clear()
            inputs["source_assets"]["launcher.c"] = _BytesSubclass(b"must-not-dispatch")
        original_pin(raw, size, digest)

    monkeypatch.setattr(profile, "_pin", replace_caller_map_after_validation)
    assert profile.prepare_rsi_installation_profile(**inputs) == expected
    assert changed


def test_preparation_call_has_no_filesystem_process_network_clock_or_environment_access(
    inputs: dict, monkeypatch: pytest.MonkeyPatch,
):
    with monkeypatch.context() as guard:
        for owner, names in (
            (builtins, ("open",)), (io, ("open",)),
            (Path, ("open", "read_bytes", "read_text", "write_bytes", "write_text", "stat", "lstat",
                    "resolve", "mkdir", "iterdir", "glob", "rglob")),
            (os, ("open", "read", "write", "stat", "lstat", "getenv", "getcwd", "listdir",
                  "scandir", "system", "fork", "execv", "execve", "spawnv", "urandom")),
            (subprocess, ("Popen", "run", "call", "check_call", "check_output")),
            (socket, ("socket", "create_connection", "getaddrinfo")),
            (urllib.request, ("urlopen",)),
            (time, ("time", "time_ns", "monotonic", "monotonic_ns", "perf_counter", "sleep",
                    "process_time", "thread_time")),
        ):
            for name in names:
                if hasattr(owner, name):
                    guard.setattr(owner, name, _bomb)
        guard.setattr(os, "environ", _DictSubclass())
        guard.setattr(datetime, "datetime", _Clock)
        guard.setattr(datetime, "date", _Clock)
        result = profile.prepare_rsi_installation_profile(**inputs)
    assert result.sha256 == hashlib.sha256(result.wire_bytes).hexdigest()


@pytest.mark.parametrize("which", ["wrapper", "candidate"])
def test_existing_installation_and_build_input_parsers_reject_preparation_types(
    inputs: dict, which: str,
):
    result = profile.prepare_rsi_installation_profile(**inputs)
    raw = result.wire_bytes if which == "wrapper" else _wire(
        json.loads(result.wire_bytes)["candidate_build_inputs"],
    )
    with pytest.raises(installation.StaticPythonInstallationError):
        installation.parse_static_python_installation_descriptor(
            raw, expected_descriptor_sha256=hashlib.sha256(raw).hexdigest(),
            expected_installation_version="rsi-marker-launch-v1", expected_artifact_sha256="a" * 64,
        )
    with pytest.raises(StaticPythonBuildInputsError):
        emit_static_python_build_inputs(raw)
