"""Synthetic installation/startup joins for the explicitly selected successor.

No native target, CPython build, model or evaluator runs. These comparisons do
not supply original completion acquisition or accepted build/runtime custody.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_native_trusted_observation_handoff import _call as _handoff_call
from test_native_trusted_observation_handoff import _fixture as _handoff_fixture
from test_static_python_fixed_profile import _closure_raw, _image, _parse, _pins, _raw, _sha
from test_static_python_fixed_runtime_observation import _runtime_vector

from lunar_evolution import native_trusted_scheduler as scheduler
from lunar_evolution import static_python_fixed_live_modules as live
from lunar_evolution import static_python_fixed_runtime_observation as runtime
from lunar_evolution.native_fixed_live_sink import (
    FixedPythonLiveSinkRequest,
    NativeFixedLiveSinkError,
    _pin_fixed_python_live_sink_request,
)
from lunar_evolution.static_python_producer_completion import MAX_COMPLETION_BYTES
from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_ENTRYPOINT_PINS,
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES,
    FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from tools.static_python_rsi_fixture.completion_source import (
    prepare_fixed_producer_completion_sources,
)
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_main


def _replace_source(description, closure, name, record):
    next(item for item in description["frozen_modules"] if item["name"] == name)["source"] = dict(record)
    next(item for item in closure["frozen"] if item["name"] == name).update(
        source=record["path"], source_size=record["size"], source_sha256=record["sha256"],
    )
    existing = next((item for item in closure["sources"] if item["path"] == record["path"]), None)
    if existing is None:
        closure["sources"].append(dict(record))
    else:
        existing.update(record)


def _parse_changed(description, closure):
    closure["sources"].sort(key=lambda item: item["path"])
    description["runtime_closure_sha256"] = _sha(_closure_raw(closure))
    return _parse(description, closure, _pins(description, closure))


def _lifecycle_vector(fault=None):
    original, payload = _runtime_vector()
    description, closure = original.installation.to_dict(), json.loads(original.installation.closure_bytes)
    # Replace unused synthetic frozen declarations; observed startup modules stay
    # untouched because the solver has not yet been imported at this phase.
    old_names = sorted(name for name in original.installation.frozen_names if name.startswith("synthetic_"))[-2:]
    for old_name, name, package in zip(old_names, ("openevolve", "openevolve.lunar_fixed"), (True, False), strict=True):
        record = next(item for item in description["frozen_modules"] if item["name"] == old_name)
        unit = next(item for item in closure["frozen"] if item["name"] == old_name)
        generated = "generated-sources/Python/frozen_modules/" + name + ".h"
        record.update(name=name, generator_id=name, package=package)
        record["generated"]["path"] = generated
        unit.update(name=name, generator_id=name, package=package, output=generated)
    description["frozen_modules"].sort(key=lambda item: item["generator_id"])
    closure["frozen"].sort(key=lambda item: item["generator_id"])
    interim = _parse_changed(description, closure)
    arguments = {
        "frozen_names": tuple(sorted(interim.frozen_names)), "builtin_names": interim.builtin_names,
        "aliases": interim.aliases,
        "frozen_packages": tuple(sorted(item["name"] for item in description["frozen_modules"] if item["package"])),
    }
    prepared = prepare_fixed_producer_completion_sources(
        "openevolve", **arguments, profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
    )
    main = prepared.frozen_main_source
    if fault == "main-drift":
        main += b"\n"
    elif fault == "legacy-main":
        main = prepare_fixed_live_main("openevolve", **arguments, runtime_observation=True)
    _replace_source(description, closure, "_lunar_static_main", {
        "path": "runtime/frozen_main.py", "size": len(main), "sha256": _sha(main),
    })
    size, digest = COMPLETION_ENTRYPOINT_PINS["openevolve"]
    producer = {"path": "producer/openevolve/lunar_fixed.py", "size": size, "sha256": digest}
    if fault == "producer-pin":
        producer.update(size=size + 1, sha256=_sha("different producer"))
    _replace_source(description, closure, "openevolve.lunar_fixed", producer)
    closure["sources"] = [item for item in closure["sources"] if item["path"] != live.FIXED_LIVE_SINK_LAUNCHER_PATH]
    closure["sources"].append({
        "path": COMPLETION_LAUNCHER_PATH, "size": FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES,
        "sha256": FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256,
    })
    if fault == "missing-launcher":
        closure["sources"] = [item for item in closure["sources"] if item["path"] != COMPLETION_LAUNCHER_PATH]
    elif fault == "missing-producer-source":
        closure["sources"] = [item for item in closure["sources"] if item["path"] != producer["path"]]
    elif fault == "launcher-pin":
        next(item for item in closure["sources"] if item["path"] == COMPLETION_LAUNCHER_PATH)["sha256"] = _sha("different launcher")
    installed = _parse_changed(description, closure)
    payload["frozen_names"] = sorted(installed.frozen_names)
    request = FixedPythonLiveSinkRequest(installed, _image(), main, installed.installation_sha256,
                                         source_profile=FIXED_PRODUCER_LIFECYCLE_PROFILE)
    return request, payload


def _compare(request, payload):
    return request.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                           target_pid=123, manifest_sha256=payload["manifest_sha256"])


def test_explicit_lifecycle_profile_compares_new_sources_and_original_startup_binding():
    request, payload = _lifecycle_vector()
    request.validate(target_sha256=_sha(request.image))
    observed = _compare(request, payload)
    result = runtime.validate_fixed_python_runtime_observation_policy(
        request.installation, observed, image=request.image, runtime_main_source=request.runtime_main_source,
        expected_installation_sha256=request.expected_installation_sha256,
        expected_observation_sha256=_sha(observed.canonical_bytes), producer_lifecycle=True,
    )
    assert result.live_modules_observation == observed
    assert not result.live_runtime_authenticated and not result.immutable_custody_verified
    assert not result.production_admission and not result.online_publication
    assert not hasattr(result, "pycache_absent") and not hasattr(result, "computation_sha256")


@pytest.mark.parametrize("profile", (live.FIXED_LIVE_PRIVATE_SINK_PROFILE, live.FIXED_LIVE_RUNTIME_SINK_PROFILE))
def test_old_source_profiles_do_not_accept_versioned_completion_dispatch(profile):
    request, payload = _lifecycle_vector()
    old = replace(request, source_profile=profile)
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        old.validate(target_sha256=_sha(old.image))
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        _compare(old, payload)


@pytest.mark.parametrize("fault", ("missing-launcher", "missing-producer-source", "launcher-pin", "producer-pin", "main-drift", "legacy-main"))
def test_resigned_installation_cannot_replace_reviewed_completion_source_pins(fault):
    request, _payload = _lifecycle_vector(fault)
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        request.validate(target_sha256=_sha(request.image))


@pytest.mark.parametrize("field,value", (("image_device", 20), ("image_inode", 78), ("target_pid", 124), ("manifest_sha256", "f" * 64)))
def test_new_profile_keeps_original_live_source_process_and_manifest_checks(field, value):
    request, payload = _lifecycle_vector()
    arguments = {"image_device": 19, "image_inode": 77, "target_pid": 123,
                 "manifest_sha256": payload["manifest_sha256"]}
    arguments[field] = value
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        request.compare(_raw(payload) + b"\n", **arguments)


def test_default_mapper_cannot_silently_select_completion_dispatch():
    request, payload = _lifecycle_vector()
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        runtime.map_fixed_python_runtime_observation(
            request.installation, _raw(payload) + b"\n", image=request.image,
            runtime_main_source=request.runtime_main_source,
            expected_installation_sha256=request.expected_installation_sha256,
            expected_image_device=19, expected_image_inode=77, expected_target_pid=123,
            expected_manifest_sha256=payload["manifest_sha256"],
        )


def _handoff_vector(tmp_path, monkeypatch):
    value = _handoff_fixture(tmp_path, monkeypatch)
    request, payload = _lifecycle_vector()
    value.sink = request
    object.__setattr__(value.attempt, "live_modules_observation", _compare(request, payload))
    pin = _pin_fixed_python_live_sink_request(request, target_sha256=_sha(request.image))
    run = scheduler.NativeTrustedProducerRun(value.attempt, value.receipt, value.output)
    return value, run, pin


def test_completion_handoff_uses_bounded_projection_and_strong_original_byte_pins(tmp_path, monkeypatch):
    value, run, pin = _handoff_vector(tmp_path, monkeypatch)
    # Inert diagnostics, deliberately not a valid completion protocol. Pinning
    # them must not acquire a lifecycle or confer any runtime authority.
    complete = bytes(bytearray(b"inert-completion-diagnostic\n"))
    partial = bytes(bytearray(complete))
    object.__setattr__(value.attempt, "producer_completion_bytes", complete)
    object.__setattr__(value.attempt, "producer_completion_partial_bytes", partial)
    evidence = scheduler._native_handoff_evidence(run, pin)
    projected = json.loads(evidence[7])
    for name, raw in (("producer_completion_bytes", complete),
                      ("producer_completion_partial_bytes", partial)):
        assert projected[name] == {"size": len(raw), "sha256": _sha(raw)}
    assert evidence[-1] == (("producer_completion_bytes", id(complete), complete),
                            ("producer_completion_partial_bytes", id(partial), partial))
    assert evidence[-1][0][2] is complete and evidence[-1][1][2] is partial
    assert complete not in evidence[7] and partial not in evidence[7]
    assert scheduler._native_handoff_evidence(run, pin) == evidence
    assert not value.attempt.live_modules_observation.production_admission


def test_absent_completion_preserves_legacy_handoff_wire_and_pin_shape(tmp_path, monkeypatch):
    _value, run, pin = _handoff_vector(tmp_path, monkeypatch)
    evidence = scheduler._native_handoff_evidence(run, pin)
    projected = json.loads(evidence[7])
    assert "producer_completion_bytes" not in projected
    assert "producer_completion_partial_bytes" not in projected
    assert len(evidence) == 10


@pytest.mark.parametrize("name", ("producer_completion_bytes", "producer_completion_partial_bytes"))
@pytest.mark.parametrize("replacement", ("same-bytes", "changed", "none"))
def test_supplier_cannot_replace_original_completion_material(tmp_path, monkeypatch, name, replacement):
    value, _run, _pin = _handoff_vector(tmp_path, monkeypatch)
    raw = bytes(bytearray(b"inert original completion diagnostic\n"))
    object.__setattr__(value.attempt, name, raw)

    def supplier(run):
        from test_native_trusted_python_prepublication import _handoff
        retained = _handoff(value.context)
        changed = (bytes(bytearray(raw)) if replacement == "same-bytes"
                   else b"changed\n" if replacement == "changed" else None)
        assert changed is not raw
        object.__setattr__(run.attempt, name, changed)
        return retained

    with pytest.raises(scheduler.NativeTrustedSchedulerError, match="python_handoff_invalid"):
        _handoff_call(value, supplier, wrapper="private")
    assert value.publication_calls == []


@pytest.mark.parametrize("name,value", (
    ("producer_completion_bytes", b""),
    ("producer_completion_bytes", b"x" * (MAX_COMPLETION_BYTES + 1)),
    ("producer_completion_bytes", bytearray(b"mutable")),
    ("producer_completion_bytes", "foreign"),
    ("producer_completion_partial_bytes", b"x" * (MAX_COMPLETION_BYTES + 2)),
    ("producer_completion_partial_bytes", bytearray(b"mutable")),
))
def test_handoff_refuses_unbounded_or_foreign_completion_before_json(tmp_path, monkeypatch, name, value):
    fixture, run, pin = _handoff_vector(tmp_path, monkeypatch)
    object.__setattr__(fixture.attempt, name, value)
    with pytest.raises(ValueError, match="original native completion material required"):
        scheduler._native_handoff_evidence(run, pin)


@pytest.mark.parametrize("partial", (b"", b"x" * (MAX_COMPLETION_BYTES + 1)))
def test_partial_handoff_retains_empty_or_overflow_sentinel_without_completion_claim(tmp_path, monkeypatch, partial):
    value, run, pin = _handoff_vector(tmp_path, monkeypatch)
    object.__setattr__(value.attempt, "producer_completion_partial_bytes", partial)
    evidence = scheduler._native_handoff_evidence(run, pin)
    projected = json.loads(evidence[7])
    assert "producer_completion_bytes" not in projected
    assert projected["producer_completion_partial_bytes"] == {"size": len(partial), "sha256": _sha(partial)}
    assert evidence[-1][0][2] is partial
