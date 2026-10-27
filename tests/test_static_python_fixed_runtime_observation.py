"""Synthetic expanded-runtime observations; never static CPython/solver acceptance."""

from __future__ import annotations

import builtins
import hashlib
import json
from dataclasses import replace
from types import ModuleType, SimpleNamespace

import pytest
from test_native_fixed_live_sink import _request_vector
from test_static_python_fixed_live_modules import ASSET
from test_static_python_fixed_profile import _closure_raw, _image, _parse, _pins, _raw, _sha
from test_static_python_fixed_runtime_closure import (
    closure_inputs as closure_inputs,  # noqa: PLC0414
)

from lunar_evolution import python_runtime_observation_policy as policy
from lunar_evolution import static_python_fixed_live_modules as live
from lunar_evolution import static_python_fixed_runtime_observation as runtime
from lunar_evolution.native_fixed_live_sink import (
    FixedPythonLiveSinkRequest,
    NativeFixedLiveSinkError,
)
from tools.static_python_rsi_fixture import runtime_closure as closure
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_main

RUNTIME_ASSET = ASSET.with_name("fixed_live_runtime.py")


def _runtime_namespace(imports=None):
    runtime_builtins = dict(vars(builtins))
    if imports is not None:
        runtime_builtins["__import__"] = lambda name, *_args, **_kwargs: imports[name]
    namespace = {"__builtins__": runtime_builtins}
    exec(compile(ASSET.read_bytes(), str(ASSET), "exec"), namespace)  # noqa: S102
    exec(compile(RUNTIME_ASSET.read_bytes(), str(RUNTIME_ASSET), "exec"), namespace)  # noqa: S102
    return namespace


def _observed_sys():
    class Stream:
        def __init__(self, errors):
            self.encoding, self.errors = "utf-8", errors

    sys = ModuleType("sys")
    sys.modules = {"_io": SimpleNamespace(TextIOWrapper=Stream)}
    sys.stdin, sys.stdout, sys.stderr = Stream("strict"), Stream("strict"), Stream("backslashreplace")
    sys.argv, sys.orig_argv = ["lunar-static-python-fixture"], ["lunar-static-python-fixture"]
    sys.version_info = SimpleNamespace(major=3, minor=13, micro=12, releaselevel="final", serial=0)
    sys.implementation = SimpleNamespace(name="cpython", cache_tag="cpython-313")
    sys.abiflags, sys.platform, sys.maxsize = "", "linux", 2**63 - 1
    sys._is_gil_enabled = lambda: True
    sys.flags = SimpleNamespace(**live._FLAGS, hash_randomization=0)
    sys.getfilesystemencoding = lambda: "utf-8"
    sys.getfilesystemencodeerrors = lambda: "surrogateescape"
    posix = SimpleNamespace(uname=lambda: SimpleNamespace(machine="x86_64"))
    return sys, posix


def _runtime_vector():
    request, payload = _request_vector()
    installed = request.installation
    records = installed.to_dict()["frozen_modules"]
    main = prepare_fixed_live_main(
        "openevolve", frozen_names=tuple(sorted(installed.frozen_names)), builtin_names=installed.builtin_names,
        aliases=installed.aliases, frozen_packages=tuple(sorted(item["name"] for item in records if item["package"])),
        runtime_observation=True,
    )
    description, source_closure = installed.to_dict(), json.loads(installed.closure_bytes)
    source = {"path": "runtime/frozen_main.py", "size": len(main), "sha256": _sha(main)}
    next(item for item in description["frozen_modules"] if item["name"] == "_lunar_static_main")["source"] = source
    next(item for item in source_closure["frozen"] if item["name"] == "_lunar_static_main").update(
        source_size=len(main), source_sha256=_sha(main),
    )
    next(item for item in source_closure["sources"] if item["path"] == "runtime/frozen_main.py").update(source)
    description["runtime_closure_sha256"] = _sha(_closure_raw(source_closure))
    installed = _parse(description, source_closure, _pins(description, source_closure))
    payload.update(schema=live.FIXED_LIVE_RUNTIME_SCHEMA, collector_profile=live.FIXED_LIVE_RUNTIME_PROFILE,
                   runtime_source_sha256=live.FIXED_LIVE_RUNTIME_SOURCE_SHA256,
                   runtime=_runtime_namespace()["_lunar_live_runtime_facts"](*_observed_sys()))
    return FixedPythonLiveSinkRequest(installed, _image(), main, installed.installation_sha256,
                                     source_profile=live.FIXED_LIVE_RUNTIME_SINK_PROFILE), payload


def _compare(request, payload, **overrides):
    raw = _raw(payload) + b"\n"
    arguments = {"image": request.image, "runtime_main_source": request.runtime_main_source,
                 "expected_installation_sha256": request.expected_installation_sha256,
                 "expected_image_device": 19, "expected_image_inode": 77, "expected_target_pid": 123,
                 "expected_manifest_sha256": payload["manifest_sha256"]}
    arguments.update(overrides)
    return runtime.map_fixed_python_runtime_observation(request.installation, raw, **arguments)


def test_supplement_reports_actual_values_without_an_expected_configuration():
    sys, posix = _observed_sys()
    sys.version_info.micro = 99
    sys.implementation.cache_tag = "cpython-399"
    sys.argv = ["observed-custom-argv"]
    sys.orig_argv = ["observed-custom-orig-argv"]
    sys.abiflags = "t"
    sys._is_gil_enabled = lambda: False
    actual = _runtime_namespace()["_lunar_live_runtime_facts"](sys, posix)
    assert actual["version"] == [3, 13, 99]
    assert actual["cache_tag"] == "cpython-399"
    assert actual["argv"] == ["observed-custom-argv"]
    assert actual["orig_argv"] == ["observed-custom-orig-argv"]
    assert actual["abiflags"] == "t" and actual["gil_enabled"] is False
    assert actual["stdio"][-1]["errors"] == "backslashreplace"


@pytest.mark.parametrize("field", ["version_info", "orig_argv", "abiflags", "getfilesystemencoding", "_is_gil_enabled"])
def test_collector_missing_actual_facts_fail_without_expected_fallback(field):
    sys, posix = _observed_sys()
    delattr(sys, field)
    with pytest.raises(AttributeError):
        _runtime_namespace()["_lunar_live_runtime_facts"](sys, posix)


def test_real_sink_mapper_uses_captured_startup_facts_and_preserves_no_authority():
    request, payload = _runtime_vector()
    request.validate(target_sha256=_sha(_image()))
    result = _compare(request, payload)
    assert (result.version_major, result.version_minor, result.version_micro) == (3, 13, 12)
    assert result.cache_tag == "cpython-313" and result.abi_profile == "cp313-release-gil"
    assert result.argv == result.orig_argv == ("lunar-static-python-fixture",)
    assert result.startup_modules == tuple(item["name"] for item in payload["modules"])
    assert result.stdio[-1] == ("utf-8", "backslashreplace")
    assert "hash_randomization=0" in result.flags
    assert not result.live_runtime_authenticated and not result.immutable_custody_verified
    assert not result.production_admission and not result.online_publication
    assert not hasattr(result, "pycache_absent") and not hasattr(result, "computation_sha256")
    original = request.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                               target_pid=123, manifest_sha256=payload["manifest_sha256"])
    assert original == result.live_modules_observation
    assert policy.validate_fixed_python_runtime_observation_policy(
        request.installation, original, image=request.image, runtime_main_source=request.runtime_main_source,
        expected_installation_sha256=request.expected_installation_sha256,
        expected_observation_sha256=_sha(original.canonical_bytes),
    ) == result


@pytest.mark.parametrize("field,value", [
    ("version", [3, 13, True]), ("version", [3, 13, 11]), ("cache_tag", "cpython-312"),
    ("abiflags", "t"), ("debug_build", True), ("gil_enabled", False),
    ("implementation", "pypy"), ("platform", "darwin"), ("architecture", "aarch64"),
    ("maxsize", 2**31 - 1), ("releaselevel", "candidate"), ("serial", True),
    ("argv", ["bin/lunar-openevolve"]), ("orig_argv", ["bin/lunar-openevolve", "--lunar-rsi-input-v1"]),
    ("hash_randomization", True), ("filesystem_encoding", "ascii"), ("filesystem_errors", "strict"),
    ("stdio", [{"encoding": "utf-8", "errors": "strict"}] * 3),
])
def test_resigned_observation_cannot_substitute_expected_runtime_facts(field, value):
    request, payload = _runtime_vector()
    payload["runtime"][field] = value
    with pytest.raises(runtime.FixedPythonRuntimeObservationError, match="^fixed_python_runtime_observation_refused$"):
        _compare(request, payload)
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        request.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                        target_pid=123, manifest_sha256=payload["manifest_sha256"])


@pytest.mark.parametrize("field", sorted(runtime._RUNTIME_FIELDS))
def test_missing_runtime_facts_cannot_be_filled_from_installation(field):
    request, payload = _runtime_vector()
    del payload["runtime"][field]
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        _compare(request, payload)


@pytest.mark.parametrize("argument,value", [
    ("expected_image_device", 20), ("expected_image_inode", 78), ("expected_target_pid", 124),
    ("expected_manifest_sha256", "b" * 64), ("expected_installation_sha256", "b" * 64),
    ("runtime_main_source", b"foreign"), ("image", _image()[:-1]),
])
def test_mapper_preserves_original_source_image_owner_and_manifest_checks(argument, value):
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        _compare(*_runtime_vector(), **{argument: value})


def test_old_modules_only_snapshot_never_satisfies_expanded_runtime_policy():
    request, payload = _request_vector()
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        _compare(request, payload)
    # The old comparison still accepts only its old complete, pinned source.
    old = request.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                          target_pid=123, manifest_sha256=payload["manifest_sha256"])
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        policy.validate_fixed_python_runtime_observation_policy(
            request.installation, old, image=request.image, runtime_main_source=request.runtime_main_source,
            expected_installation_sha256=request.expected_installation_sha256,
            expected_observation_sha256=old.observation_sha256,
        )


@pytest.mark.parametrize("fault", ["wire", "pin", "dto", "claim", "module", "source-profile", "runtime-source"])
def test_source_and_snapshot_drift_are_refused(fault):
    request, payload = _runtime_vector()
    result = _compare(request, payload)
    observed = result.live_modules_observation
    arguments = {"image": request.image, "runtime_main_source": request.runtime_main_source,
                 "expected_installation_sha256": request.expected_installation_sha256,
                 "expected_observation_sha256": observed.observation_sha256}
    if fault == "wire":
        observed = replace(observed, canonical_bytes=observed.canonical_bytes + b" ")
    elif fault == "pin":
        arguments["expected_observation_sha256"] = "b" * 64
    elif fault == "dto":
        observed = replace(observed, target_pid=True)
    elif fault == "claim":
        observed = replace(observed, production_admission=True)
    elif fault == "module":
        observed = replace(observed, module_names=observed.module_names[:-1])
    elif fault == "source-profile":
        request = replace(request, source_profile=live.FIXED_LIVE_PRIVATE_SINK_PROFILE)
        with pytest.raises(NativeFixedLiveSinkError):
            request.validate(target_sha256=_sha(_image()))
        return
    else:
        payload["runtime_source_sha256"] = "b" * 64
        with pytest.raises(runtime.FixedPythonRuntimeObservationError):
            _compare(request, payload)
        return
    with pytest.raises(runtime.FixedPythonRuntimeObservationError) as caught:
        policy.validate_fixed_python_runtime_observation_policy(request.installation, observed, **arguments)
    assert caught.value.__suppress_context__


def test_opt_in_source_pin_and_runtime_closure_preserve_all_default_bytes(closure_inputs):
    baseline = closure.prepare_fixed_runtime_closure(**closure_inputs)
    legacy = closure.prepare_fixed_runtime_closure(**closure_inputs, live_modules_profile=live.FIXED_LIVE_PRIVATE_SINK_PROFILE)
    selected = closure.prepare_fixed_runtime_closure(**closure_inputs, live_modules_profile=live.FIXED_LIVE_RUNTIME_SINK_PROFILE)
    assert closure.prepare_fixed_runtime_closure(**closure_inputs) == baseline
    legacy_sources, selected_sources = dict(legacy.sources), dict(selected.sources)
    assert selected_sources[live.FIXED_LIVE_SINK_LAUNCHER_PATH] == legacy_sources[live.FIXED_LIVE_SINK_LAUNCHER_PATH]
    assert selected_sources["runtime/frozen_main.py"].startswith(legacy_sources["runtime/frozen_main.py"])
    assert RUNTIME_ASSET.read_bytes() == selected_sources["runtime/frozen_main.py"][-live.FIXED_LIVE_RUNTIME_SOURCE_BYTES:]
    assert hashlib.sha256(RUNTIME_ASSET.read_bytes()).hexdigest() == live.FIXED_LIVE_RUNTIME_SOURCE_SHA256
    assert baseline != selected and legacy != selected


def test_expanded_installation_never_weakens_legacy_exact_type_policy():
    request, _payload = _runtime_vector()
    with pytest.raises(policy.PythonRuntimeObservationPolicyError) as caught:
        policy.validate_python_runtime_observation_policy(
            None, None, installation_descriptor=request.installation,
            installation_descriptor_sha256=request.installation.installation_sha256,
            installation_version=request.installation.installation_version,
            initialization_profile_sha256="b" * 64,
        )
    assert caught.value.code == "installation_invalid"


@pytest.mark.parametrize("supplement", [b"", b"foreign", False, None], ids=["empty", "wrong", "bool", "missing"])
def test_runtime_profile_requires_separately_pinned_source_supplement(supplement):
    request, _payload = _runtime_vector()
    installed = request.installation
    arguments = {
        "frozen_names": tuple(sorted(installed.frozen_names)), "builtin_names": installed.builtin_names,
        "aliases": installed.aliases,
        "frozen_packages": tuple(sorted(record["name"] for record in installed.to_dict()["frozen_modules"]
                                        if record["package"])),
        "collector_source": ASSET.read_bytes(), "runtime_observation_source": supplement,
    }
    if supplement is None:
        main = live.compose_fixed_python_live_main("openevolve", **arguments)
        with pytest.raises(NativeFixedLiveSinkError):
            replace(request, runtime_main_source=main).validate(target_sha256=_sha(_image()))
    else:
        with pytest.raises(live.FixedPythonLiveModulesError):
            live.compose_fixed_python_live_main("openevolve", **arguments)


@pytest.mark.parametrize("drift", [False, True], ids=["stable-actual-facts", "observation-window-drift"])
def test_selected_collector_captures_actual_facts_and_rechecks_observation_window(drift):
    sys, posix = _observed_sys()
    sys.argv, sys.orig_argv = ["actual-argv"], ["actual-orig-argv"]
    sys.path = []
    posix.getpid = lambda: 123
    namespace = _runtime_namespace({"sys": sys, "posix": posix, "_imp": object(),
                                    "_sha2": SimpleNamespace(sha256=hashlib.sha256)})
    namespace.update(_LUNAR_LIVE_SOLVER="openevolve", _LUNAR_LIVE_BUILTINS=("_io",),
                     _LUNAR_LIVE_FROZEN=(), _LUNAR_LIVE_COLLECTOR_SHA256=live.FIXED_LIVE_COLLECTOR_SOURCE_SHA256,
                     _LUNAR_LIVE_RUNTIME_SHA256=live.FIXED_LIVE_RUNTIME_SOURCE_SHA256)
    # These two existing helpers have their own complete module/image focused
    # suite. Keep this test on the real supplement's independent runtime window.
    namespace["_lunar_live_snapshot"] = lambda *_args: ([], dict(live._FLAGS))

    def image(*_args):
        if drift:
            sys.orig_argv.append("changed-during-image-observation")
        return {"device": 19, "inode": 77, "mode": 0o755, "size": 512, "sha256": _sha(_image())}

    namespace["_lunar_live_image"] = image
    if drift:
        with pytest.raises(RuntimeError, match="^fixed_live_runtime_drift$"):
            namespace["_lunar_collect_live_modules"]("b" * 64)
    else:
        captured = json.loads(namespace["_lunar_collect_live_modules"]("b" * 64))
        assert captured["runtime"]["argv"] == ["actual-argv"]
        assert captured["runtime"]["orig_argv"] == ["actual-orig-argv"]
        assert captured["sys_path"] == []
        assert captured["schema"] == live.FIXED_LIVE_RUNTIME_SCHEMA
        assert all(value is False for value in captured["claims"].values())


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_collector_never_supplies_default_encoding_for_a_missing_stream(stream):
    sys, posix = _observed_sys()
    setattr(sys, stream, None)
    with pytest.raises(RuntimeError, match="^fixed_live_runtime_stdio$"):
        _runtime_namespace()["_lunar_live_runtime_facts"](sys, posix)


def test_resigned_bound_dto_cannot_bypass_full_module_metadata_comparison():
    request, payload = _runtime_vector()
    observed = _compare(request, payload).live_modules_observation
    payload["modules"][0]["loader"] = "SourceFileLoader"
    raw = _raw(payload) + b"\n"
    forged = replace(observed, canonical_bytes=raw, observation_sha256=_sha(raw))
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        policy.validate_fixed_python_runtime_observation_policy(
            request.installation, forged, image=request.image, runtime_main_source=request.runtime_main_source,
            expected_installation_sha256=request.installation.installation_sha256,
            expected_observation_sha256=_sha(raw),
        )
