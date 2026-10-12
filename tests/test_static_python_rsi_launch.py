"""Source-only RSI launcher checks; the C harness contains no CPython runtime."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools.static_python_fixture.profile import BUILTINS, CONFIG, FROZEN, PRECONFIG
from tools.static_python_fixture.profile import manifest as original_profile

_ROOT = Path(__file__).resolve().parents[1]
_MARKER = "--lunar-rsi-input-v1"
_DIGEST = "0123456789abcdef" * 4

_FAKE_HEADER = r"""
#ifndef PYTHON_H
#define PYTHON_H
#include <stddef.h>
typedef struct { int unused; } PyStatus;
typedef struct { int unused; } PyPreConfig;
typedef struct { int unused; } PyConfig;
typedef struct { const char *text; } PyObject;
PyStatus PyStatus_Ok(void);
int PyStatus_Exception(PyStatus);
void Py_ExitStatusException(PyStatus);
PyStatus Py_PreInitialize(PyPreConfig *);
PyStatus Py_InitializeFromConfig(const PyConfig *);
void PyConfig_Clear(PyConfig *);
PyObject *PyImport_ImportModule(const char *);
PyObject *PyObject_GetAttrString(PyObject *, const char *);
PyObject *PyUnicode_FromString(const char *);
PyObject *PyObject_CallOneArg(PyObject *, PyObject *);
void PyErr_Print(void);
int Py_FinalizeEx(void);
#define Py_XDECREF(value) ((void)(value))
#endif
"""

_FAKE_RUNTIME = r"""
#include "Python.h"
#include "lunar_fixture_profile.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static PyObject module = {"_lunar_static_main"};
static PyObject callable = {"_rsi_launch"};
static PyObject argument;
static PyObject result = {"inert-result"};
PyStatus PyStatus_Ok(void) { return (PyStatus){0}; }
int PyStatus_Exception(PyStatus s) { (void)s; return 0; }
void Py_ExitStatusException(PyStatus s) { (void)s; exit(90); }
PyStatus lunar_preconfig(PyPreConfig *c) {
    (void)c; puts("PRECONFIG"); return PyStatus_Ok();
}
PyStatus lunar_config(PyConfig *c) {
    (void)c; puts("CONFIG"); return PyStatus_Ok();
}
PyStatus Py_PreInitialize(PyPreConfig *c) {
    (void)c; puts("PREINIT"); return PyStatus_Ok();
}
PyStatus Py_InitializeFromConfig(const PyConfig *c) {
    (void)c; puts("INIT"); return PyStatus_Ok();
}
void PyConfig_Clear(PyConfig *c) { (void)c; }
PyObject *PyImport_ImportModule(const char *name) {
    if (strcmp(name, module.text)) exit(91);
    return &module;
}
PyObject *PyObject_GetAttrString(PyObject *m, const char *name) {
    if (m != &module || strcmp(name, callable.text)) exit(92);
    return &callable;
}
PyObject *PyUnicode_FromString(const char *text) {
    argument.text = text; return &argument;
}
PyObject *PyObject_CallOneArg(PyObject *f, PyObject *a) {
    if (f != &callable || a != &argument) exit(93);
    printf("CALL:%s:%s\n", f->text, a->text);
    return &result;
}
void PyErr_Print(void) { puts("PYERR"); }
int Py_FinalizeEx(void) { puts("FINALIZE"); return 0; }
"""


def _emit(destination: Path) -> Path:
    from tools.static_python_rsi_fixture.recipe import emit_rsi_launch_source_plan

    return emit_rsi_launch_source_plan(destination)


@pytest.fixture(scope="module")
def launcher_probe(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("test-only C compiler unavailable")
    staging = tmp_path_factory.mktemp("rsi-launcher-fake-runtime")
    (staging / "Python.h").write_text(_FAKE_HEADER, encoding="ascii")
    (staging / "lunar_fixture_profile.h").write_bytes(
        (_ROOT / "tools/static_python_fixture/assets/lunar_fixture_profile.h").read_bytes()
    )
    runtime = staging / "fake_runtime.c"
    runtime.write_text(_FAKE_RUNTIME, encoding="ascii")
    output = staging / "inert-argv-probe"
    completed = subprocess.run(
        [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(staging),
         str(_ROOT / "tools/static_python_rsi_fixture/assets/launcher.c"),
         str(runtime), "-o", str(output)],
        capture_output=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return output


@pytest.mark.parametrize("arguments", [
    (), (_MARKER,), (_DIGEST,), ("wrong-marker", _DIGEST),
    (_MARKER, ""), (_MARKER, "0" * 63), (_MARKER, "0" * 65),
    (_MARKER, "A" * 64), (_MARKER, "g" * 64), (_MARKER, "é" * 64),
    (_MARKER, "0" * 63 + "\n"), (_MARKER, "0" * 63 + "/"),
    (_MARKER, _DIGEST, "extra"), (_DIGEST, _MARKER),
    (_MARKER, _DIGEST, _MARKER, _DIGEST),
    ("-c", "pass"), ("-m", "arbitrary.module"), ("./candidate.py",),
])
def test_fixed_launcher_refuses_invalid_arguments_before_any_initialization(
    launcher_probe: Path, arguments: tuple[str, ...],
):
    result = subprocess.run(
        [str(launcher_probe), *arguments], capture_output=True, timeout=5, check=False,
        env={"PATH": os.defpath, "LUNAR_STATIC_FIXTURE_CASE": "baseline",
             "LUNAR_RSI_INPUT_MANIFEST": _DIGEST},
    )
    assert result.returncode == 64
    assert result.stdout == result.stderr == b""


@pytest.mark.parametrize("digest", [_DIGEST, "0" * 64, "f" * 64])
@pytest.mark.parametrize("environment_case", ["baseline", "loader-negative", "arbitrary"])
def test_fixed_launcher_delivers_exact_digest_without_environment_selection(
    launcher_probe: Path, environment_case: str, digest: str,
):
    result = subprocess.run(
        [str(launcher_probe), _MARKER, digest],
        env={"PATH": os.defpath, "LUNAR_STATIC_FIXTURE_CASE": environment_case,
             "LUNAR_RSI_INPUT_MANIFEST": "f" * 64},
        capture_output=True, timeout=5, check=False,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert result.stdout.decode("ascii").splitlines() == [
        "PRECONFIG", "PREINIT", "CONFIG", "INIT", f"CALL:_rsi_launch:{digest}", "FINALIZE",
    ]


def _inert_wrapper(tmp_path: Path):
    plan_path = _emit(tmp_path / "prepared")
    source = (plan_path.parent / "assets/frozen_main.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    wrapper = next(item for item in parsed.body
                   if isinstance(item, ast.FunctionDef) and item.name == "_rsi_launch")
    calls = []
    sentinel = object()

    def fixed_main(case):
        calls.append(case)
        return sentinel

    namespace = {"_main": fixed_main}
    # The fixed wrapper is exercised alone. The original frozen startup code,
    # broker calls, Python observations and candidate code are never executed.
    exec(compile(ast.Module(body=[wrapper], type_ignores=[]), "<inert-rsi-wrapper>", "exec"),  # noqa: S102
         namespace)
    return namespace["_rsi_launch"], calls, sentinel


@pytest.mark.parametrize("digest", [_DIGEST, "0" * 64, "f" * 64])
def test_inert_wrapper_routes_valid_metadata_to_only_baseline(tmp_path: Path, digest: str):
    wrapper, calls, sentinel = _inert_wrapper(tmp_path)
    assert wrapper(digest) is sentinel
    assert calls == ["baseline"]


@pytest.mark.parametrize("digest", [None, b"0" * 64, 42, [], {}, "", "0" * 63,
                                     "0" * 65, "A" * 64, "é" * 64, "g" * 64,
                                     "0" * 63 + "\n"])
def test_inert_wrapper_refuses_invalid_metadata_before_baseline(tmp_path: Path, digest):
    wrapper, calls, _ = _inert_wrapper(tmp_path)
    with pytest.raises((TypeError, ValueError)):
        wrapper(digest)
    assert calls == []


def test_inert_wrapper_refuses_string_subclass_before_invoking_its_methods(tmp_path: Path):
    class HostileString(str):
        def __len__(self):
            raise AssertionError("subclass length must not be trusted")

        def __iter__(self):
            raise AssertionError("subclass iteration must not be trusted")

    wrapper, calls, _ = _inert_wrapper(tmp_path)
    with pytest.raises(ValueError):
        wrapper(HostileString(_DIGEST))
    assert calls == []


def test_wrapper_preserves_reviewed_encoder_with_closed_simulated_profile(tmp_path: Path):
    from test_python_fixture_observation import BROKER, asset_observation
    from test_python_producer_admission_gate import _chain, _installation_inputs

    from lunar_evolution.python_fixture_observation import adapt_static_python_observation
    from lunar_evolution.python_runtime_observation_policy import (
        validate_python_runtime_observation_policy,
    )

    # This executes the reviewed observation encoder only with its finite fake
    # sys/loader/pipe map. The fixture executable and any solver remain inert.
    observe = asset_observation.__wrapped__(tmp_path / "encoder")
    wrapper, _, _ = _inert_wrapper(tmp_path)
    wrapper.__globals__["_main"] = observe
    raw = wrapper(_DIGEST)
    old_encoder = (tmp_path / "encoder/assets/frozen_main.py").read_bytes()
    emitted = (tmp_path / "prepared/assets/frozen_main.py").read_bytes()
    assert emitted.startswith(old_encoder + b"\n")
    chain_root = tmp_path / "chain"
    chain_root.mkdir()
    binding = _chain(chain_root, producer="openevolve")[0]
    item = adapt_static_python_observation(
        raw, binding_sha256=binding.binding_sha256, broker_transcript=BROKER, pycache_absent=True,
    )
    assert validate_python_runtime_observation_policy(
        binding, item, **_installation_inputs(binding),
    ) is None
    assert item.computation_sha256 == hashlib.sha256(b"285").hexdigest()
    assert item.production_admission is False
    assert item.runtime_load_protection is False
    assert item.general_code_origin_protection is False


def test_source_preparation_retains_exact_emitted_bytes_and_old_profile(tmp_path: Path):
    path = _emit(tmp_path / "prepared")
    assert path.name == "manifest.json"
    record = json.loads(path.read_bytes())
    assert record["schema"] == "lunar-static-python-rsi-launch-source-plan-v1"
    assert record["profile"] == "rsi-marker-launch-v1"
    records = record["emitted_sources"]
    assert records
    for item in records:
        raw = (path.parent / item["path"]).read_bytes()
        assert item["sha256"] == hashlib.sha256(raw).hexdigest()
        assert item["size"] == len(raw)
    for name in ("pipe.c", "profile.c", "getpath.c", "lunar_fixture_profile.h"):
        assert (path.parent / "assets" / name).read_bytes() == (
            _ROOT / "tools/static_python_fixture/assets" / name
        ).read_bytes()
    assert (path.parent / "assets/launcher.c").read_bytes() == (
        _ROOT / "tools/static_python_rsi_fixture/assets/launcher.c"
    ).read_bytes()
    inputs = record["source_inputs"]
    assert len(inputs) == 11
    assert [item["origin"] for item in inputs].count("original") == 9
    assert [item["origin"] for item in inputs].count("owned") == 2
    for item in inputs:
        raw = (_ROOT / item["path"]).read_bytes()
        assert item["sha256"] == hashlib.sha256(raw).hexdigest()
        assert item["size"] == len(raw)
    # The separate launcher does not modify Python's configuration or introduce
    # a general imports/package path. This projection remains source facts only.
    profile = record["initialization_profile"]
    old_profile = original_profile()
    assert profile == {key: old_profile[key] for key in (
        "preconfig", "config", "builtins", "frozen", "aliases", "codec_aliases",
        "startup_module_expectation",
    )}
    assert profile["preconfig"] == PRECONFIG
    assert profile["config"] == CONFIG
    assert profile["config"]["argv"] == profile["config"]["orig_argv"] == [
        "lunar-static-python-fixture",
    ]
    assert profile["builtins"] == sorted(BUILTINS)
    assert [item["name"] for item in profile["frozen"]] == sorted(item[0] for item in FROZEN)
    assert record["launch_policy"] == {
        "argc": 3, "marker": _MARKER, "marker_index": 1,
        "manifest_digest_index": 2, "manifest_digest_syntax": "[0-9a-f]{64}",
        "frozen_entrypoint": "_rsi_launch", "baseline_case": "baseline",
        "environment_selector": False, "input_reads": [],
    }
    assert record["claims"] == dict.fromkeys((
        "configured_closure_verified", "compilation_performed", "freezer_performed",
        "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
        "runtime_load_protection", "production_admission", "general_code_origin_protection",
    ), False)
    assert record["artifact_state"] == "pending-builder"
    assert record["startup_state"] == "not-executed"
    assert not list(path.parent.rglob("*.o"))
    assert not list(path.parent.rglob("*.pyc"))
    assert not (path.parent / "build.sh").exists()


def test_source_preparation_is_create_only(tmp_path: Path):
    destination = tmp_path / "prepared"
    path = _emit(destination)
    original = {item.relative_to(destination).as_posix(): item.read_bytes()
                for item in destination.rglob("*") if item.is_file()}
    with pytest.raises((ValueError, OSError)):
        _emit(destination)
    assert path.read_bytes() == original["manifest.json"]
    assert {item.relative_to(destination).as_posix(): item.read_bytes()
            for item in destination.rglob("*") if item.is_file()} == original


def test_source_only_cli_requires_explicit_destination_and_retains_plan(tmp_path: Path):
    module = "tools.static_python_rsi_fixture"
    missing = subprocess.run(
        [sys.executable, "-m", module], cwd=_ROOT, capture_output=True,
        timeout=10, check=False,
    )
    assert missing.returncode != 0
    destination = tmp_path / "source plan with spaces"
    completed = subprocess.run(
        [sys.executable, "-m", module, "--destination", str(destination)],
        cwd=_ROOT, capture_output=True, timeout=10, check=False,
        env={"PATH": os.defpath, "LUNAR_STATIC_EXECUTE": "1",
             "LUNAR_STATIC_FIXTURE_CASE": "loader-negative"},
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    record = json.loads((destination / "manifest.json").read_bytes())
    assert record["schema"] == "lunar-static-python-rsi-launch-source-plan-v1"
    assert record["profile"] == "rsi-marker-launch-v1"
    assert record["claims"]["runtime_execution_performed"] is False
    assert record["claims"]["input_consumption_verified"] is False


@pytest.mark.parametrize("option", ["--build", "--execute", "--admit", "--profile"])
def test_source_only_cli_refuses_execution_or_profile_options_before_output(
    tmp_path: Path, option: str,
):
    destination = tmp_path / "must-not-exist"
    completed = subprocess.run(
        [sys.executable, "-m", "tools.static_python_rsi_fixture", "--destination",
         str(destination), option], cwd=_ROOT, capture_output=True, timeout=10, check=False,
    )
    assert completed.returncode != 0
    assert not destination.exists()
