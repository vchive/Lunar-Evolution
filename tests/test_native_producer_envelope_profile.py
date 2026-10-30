"""Synthetic v2 installation joins; no target, build or evaluator execution."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from test_native_producer_completion_profile import (
    _compare,
    _lifecycle_vector,
    _parse_changed,
    _replace_source,
)
from test_static_python_fixed_profile import _raw, _sha

from lunar_evolution import static_python_fixed_live_modules as live
from lunar_evolution import static_python_fixed_runtime_observation as runtime
from lunar_evolution.native_fixed_live_sink import (
    FixedPythonLiveSinkRequest,
    NativeFixedLiveSinkError,
)
from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_ENTRYPOINT_PINS,
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_BYTES,
    FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_SHA256,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
)
from tools.static_python_rsi_fixture.envelope_source import (
    prepare_fixed_producer_envelope_sources,
)


def _envelope_vector(fault=None):
    previous, payload = _lifecycle_vector()
    description = previous.installation.to_dict()
    closure = json.loads(previous.installation.closure_bytes)
    prepared = prepare_fixed_producer_envelope_sources(
        "openevolve", frozen_names=tuple(sorted(previous.installation.frozen_names)),
        builtin_names=previous.installation.builtin_names, aliases=previous.installation.aliases,
        frozen_packages=tuple(sorted(item["name"] for item in description["frozen_modules"] if item["package"])),
        profile=FIXED_PRODUCER_ENVELOPE_PROFILE,
    )
    main = prepared.frozen_main_source
    if fault == "main-drift":
        main += b"\n"
    elif fault == "v1-main":
        main = previous.runtime_main_source
    _replace_source(description, closure, "_lunar_static_main", {
        "path": "runtime/frozen_main.py", "size": len(main), "sha256": _sha(main),
    })
    size, digest = ENVELOPE_ENTRYPOINT_PINS["openevolve"]
    producer = {"path": "producer/openevolve/lunar_fixed.py", "size": size, "sha256": digest}
    if fault == "producer-pin":
        producer.update(size=size + 1, sha256=_sha("different envelope producer"))
    elif fault == "v1-producer":
        producer = next(item["source"] for item in previous.installation.to_dict()["frozen_modules"]
                        if item["name"] == "openevolve.lunar_fixed")
    _replace_source(description, closure, "openevolve.lunar_fixed", producer)
    closure["sources"] = [item for item in closure["sources"] if item["path"] != COMPLETION_LAUNCHER_PATH]
    closure["sources"].append({
        "path": ENVELOPE_LAUNCHER_PATH, "size": FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_BYTES,
        "sha256": FIXED_PRODUCER_ENVELOPE_LAUNCHER_SOURCE_SHA256,
    })
    if fault == "missing-launcher":
        closure["sources"] = [item for item in closure["sources"] if item["path"] != ENVELOPE_LAUNCHER_PATH]
    elif fault == "missing-producer-source":
        closure["sources"] = [item for item in closure["sources"] if item["path"] != producer["path"]]
    elif fault == "launcher-pin":
        next(item for item in closure["sources"] if item["path"] == ENVELOPE_LAUNCHER_PATH)["sha256"] = _sha("different envelope launcher")
    installed = _parse_changed(description, closure)
    request = FixedPythonLiveSinkRequest(
        installed, previous.image, main, installed.installation_sha256,
        source_profile=FIXED_PRODUCER_ENVELOPE_PROFILE,
    )
    return request, payload


def test_envelope_profile_compares_reviewed_sources_with_all_authority_false():
    request, payload = _envelope_vector()
    request.validate(target_sha256=_sha(request.image))
    observed = _compare(request, payload)
    facts = runtime.validate_fixed_python_runtime_observation_policy(
        request.installation, observed, image=request.image, runtime_main_source=request.runtime_main_source,
        expected_installation_sha256=request.expected_installation_sha256,
        expected_observation_sha256=_sha(observed.canonical_bytes), producer_envelope=True,
    )
    assert facts.live_modules_observation == observed
    assert all(getattr(facts, name) is False for name in (
        "live_runtime_authenticated", "immutable_custody_verified", "production_admission", "online_publication",
    ))
    assert not hasattr(facts, "pycache_absent") and not hasattr(facts, "computation_sha256")


@pytest.mark.parametrize("profile", (
    live.FIXED_LIVE_PRIVATE_SINK_PROFILE, live.FIXED_LIVE_RUNTIME_SINK_PROFILE,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
))
def test_default_startup_and_v1_profiles_refuse_envelope_sources(profile):
    request, payload = _envelope_vector()
    old = replace(request, source_profile=profile)
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        old.validate(target_sha256=_sha(old.image))
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        _compare(old, payload)


@pytest.mark.parametrize("fault", (
    "main-drift", "v1-main", "producer-pin", "v1-producer", "missing-launcher",
    "missing-producer-source", "launcher-pin",
))
def test_resigned_envelope_installation_cannot_substitute_reviewed_sources(fault):
    request, _payload = _envelope_vector(fault)
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        request.validate(target_sha256=_sha(request.image))


@pytest.mark.parametrize("options", ({}, {"producer_lifecycle": True}))
def test_mapper_requires_separate_envelope_opt_in(options):
    request, payload = _envelope_vector()
    with pytest.raises(runtime.FixedPythonRuntimeObservationError):
        runtime.map_fixed_python_runtime_observation(
            request.installation, _raw(payload) + b"\n", image=request.image,
            runtime_main_source=request.runtime_main_source,
            expected_installation_sha256=request.expected_installation_sha256,
            expected_image_device=19, expected_image_inode=77, expected_target_pid=123,
            expected_manifest_sha256=payload["manifest_sha256"], **options,
        )


@pytest.mark.parametrize("field,value", (
    ("image_device", 20), ("image_inode", 78), ("target_pid", 124), ("manifest_sha256", "f" * 64),
))
def test_envelope_profile_preserves_original_startup_binding(field, value):
    request, payload = _envelope_vector()
    arguments = {"image_device": 19, "image_inode": 77, "target_pid": 123,
                 "manifest_sha256": payload["manifest_sha256"]}
    arguments[field] = value
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        request.compare(_raw(payload) + b"\n", **arguments)
