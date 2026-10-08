"""Provider-free static fixture observation adapter tests."""

from __future__ import annotations

import hashlib
import json

import pytest

from lunar_evolution.python_fixture_observation import (
    PythonFixtureObservationError,
    adapt_static_python_observation,
)

D = "a" * 64
BROKER = b'{"protocol":"lunar-producer-broker-ipc-v1","request_id":"req-1","status":"completed"}\n'
MODULES = ("__main__", "_abc", "_frozen_importlib", "_io", "abc", "builtins", "codecs")
FLAGS = {
    "isolated": 1, "ignore_environment": 1, "no_site": 1, "no_user_site": 1,
    "utf8_mode": 1, "dont_write_bytecode": 1, "safe_path": 1, "dev_mode": 0,
    "optimize": 0, "hash_randomization": 0,
}


def _raw(case: str = "baseline") -> dict[str, object]:
    return {
        "schema": "lunar-static-python-observation-v1", "fixture_case": case, "computed": 285,
        "version_info": [3, 13, 12, "final", 0], "cache_tag": "cpython-313", "flags": dict(FLAGS),
        "origins": {name: {"origin": "built-in" if name == "builtins" else "frozen", "file": None}
                    for name in MODULES},
        "builtin_names": ["builtins"], "frozen_names": [name for name in MODULES if name != "builtins"],
        "sys_path": [], "executable": "/lunar-static-python-fixture",
        "prefix": "/lunar-static-python-fixture", "base_prefix": "/lunar-static-python-fixture",
        "exec_prefix": "/lunar-static-python-fixture", "base_exec_prefix": "/lunar-static-python-fixture",
        "stdlib_dir": "/lunar-static-python-fixture", "argv": ["lunar-static-python-fixture"],
        "orig_argv": ["lunar-static-python-fixture"], "filesystem_encoding": "utf-8",
        "filesystem_errors": "surrogateescape", "stdio_encoding": "utf-8", "stdio_errors": "strict",
        "stderr_errors": "strict", "loader_negative": None, "broker_response_bytes": len(BROKER),
        "runtime_load_protection": False, "production_admission": False,
        "general_code_origin_protection": False,
    }


def _adapt(value: object, **kwargs):
    return adapt_static_python_observation(
        value, binding_sha256=D, broker_transcript=BROKER, pycache_absent=True, **kwargs
    )


def test_baseline_observation_projects_to_feature191_dto():
    item = _adapt(json.dumps(_raw(), sort_keys=True, separators=(",", ":")))
    assert item.execution_performed is True
    assert item.version_major == 3 and item.version_minor == 13 and item.version_micro == 12
    assert item.sys_path == ()
    assert item.computation_sha256 == hashlib.sha256(b"285").hexdigest()
    assert item.broker_transcript_sha256 == hashlib.sha256(BROKER).hexdigest()
    assert item.runtime_load_protection is False
    assert item.observation_sha256 == item.digest()


def test_loader_negative_requires_all_fixed_routes_to_refuse():
    value = _raw("loader-negative")
    value["loader_negative"] = {"direct": [True] * 8, "ordinary": [True] * 7}
    assert _adapt(value).startup_modules == MODULES
    value["loader_negative"] = {"direct": [True] * 7 + [False], "ordinary": [True] * 7}
    with pytest.raises(PythonFixtureObservationError, match="loader_negative_failed"):
        _adapt(value)


@pytest.mark.parametrize("field,changed", [
    ("executable", "/usr/bin/python3"), ("prefix", "/tmp/host"), ("sys_path", ["/tmp"]),
    ("runtime_load_protection", True), ("computed", 284), ("cache_tag", "cpython-312"),
])
def test_host_substitution_and_claims_are_rejected(field, changed):
    value = _raw()
    value[field] = changed
    with pytest.raises(PythonFixtureObservationError):
        _adapt(value)


def test_missing_independent_pycache_and_broker_evidence_is_rejected():
    value = _raw()
    with pytest.raises(PythonFixtureObservationError, match="pycache_missing"):
        adapt_static_python_observation(value, binding_sha256=D, broker_transcript=BROKER, pycache_absent=False)
    with pytest.raises(PythonFixtureObservationError, match="broker_transcript_mismatch"):
        adapt_static_python_observation(value, binding_sha256=D, broker_transcript=BROKER + b"x", pycache_absent=True)


def test_duplicate_or_noncanonical_json_is_rejected():
    raw = json.dumps(_raw(), sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(PythonFixtureObservationError, match="noncanonical_json"):
        adapt_static_python_observation(raw + b"\n", binding_sha256=D, broker_transcript=BROKER, pycache_absent=True)
    duplicate = raw[:-1] + b',"computed":285}'
    with pytest.raises(PythonFixtureObservationError, match="duplicate_json_key"):
        adapt_static_python_observation(duplicate, binding_sha256=D, broker_transcript=BROKER, pycache_absent=True)
