"""Explicit VFS consumer readback using the existing inert transport double.

Actual pinned files and compiler/linker comparisons remain in use. Replacing
the runner and observation validator here establishes no runtime authority.
"""

from __future__ import annotations

import json

import pytest

from tests import test_static_python_source_data_consumer as source_data_tests
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.execution_backend import INPUT_PROJECTION_V4, RECIPE_V4_SCHEMA
from tools.static_python_rsi_fixture.runtime_closure import canonical

VFS_BACKEND = "podman-snapshots-source-data-vfs-v1"
legacy_transport = source_data_tests.transport


@pytest.fixture
def transport(legacy_transport, monkeypatch):
    kwargs, wire, controls, observed = legacy_transport
    original_runner = consumer.run_pinned_build_v4
    observation = custody.validate_custody_observation_v2

    def runner(preparation, **options):
        assert options["custody_backend"] == VFS_BACKEND
        legacy_options = {**options, "custody_backend": custody.SOURCE_DATA_BACKEND}
        report = original_runner(preparation, **legacy_options)
        path = kwargs["workspace"] / "report.json"
        value = json.loads(path.read_bytes())
        value.update(schema="lunar-static-python-build-execution-report-v5", custody_backend=VFS_BACKEND)
        if controls["drift"] == "old_report":
            value["schema"] = "lunar-static-python-build-execution-report-v4"
            del value["custody_backend"]
        elif controls["drift"] == "missing_backend":
            del value["custody_backend"]
        elif controls["drift"] == "wrong_backend":
            value["custody_backend"] = custody.SOURCE_DATA_BACKEND
        path.write_bytes(canonical(value))
        return report

    def old_runner(*_args, **_options):
        pytest.fail("VFS consumer selected original v4 runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v4_vfs", runner)
    monkeypatch.setattr(consumer, "run_pinned_build_v4", old_runner)
    monkeypatch.setattr(custody, "validate_custody_observation_v3", observation)
    return kwargs, wire, controls, observed


def test_vfs_consumer_selects_one_runner_and_exact_report_with_ordered_prior_groups(transport):
    kwargs, wire, controls, observed = transport
    result = consumer.run_dependency_checked_build_v4_vfs(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v3"
    assert evidence["custody_backend"] == VFS_BACKEND
    assert evidence["input_projection"] == INPUT_PROJECTION_V4
    assert evidence["compilations"] == 3 and evidence["links"] == 2
    assert wire["schema"] == RECIPE_V4_SCHEMA
    expected_prior = []
    for stage in result.execution_report.stage_evidence:
        for command in stage["commands"]:
            actual_stage, index, prior = observed.pop(0)
            assert actual_stage == stage["stage"] and index == command["index"]
            assert prior == expected_prior
            expected_prior.extend(command["outputs"])
    assert not observed
    for key in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                "installation_accepted", "production_admission", "online_publication"):
        assert evidence[key] is False and getattr(result, key) is False


@pytest.mark.parametrize("backend", [None, custody.SOURCE_DATA_BACKEND, custody.SNAPSHOT_BACKEND,
                                     "podman", "host", True])
def test_vfs_consumer_never_falls_back_before_execution(transport, backend):
    kwargs, _wire, controls, _observed = transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        consumer.run_dependency_checked_build_v4_vfs(object(), **kwargs, custody_backend=backend)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


def test_original_v4_consumer_rejects_vfs_backend_before_execution(transport):
    kwargs, _wire, controls, _observed = transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        consumer.run_dependency_checked_build_v4(object(), **kwargs, custody_backend=VFS_BACKEND)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


@pytest.mark.parametrize("drift,reason", [
    ("old_report", "file_pin"), ("missing_backend", "file_pin"), ("wrong_backend", "file_pin"),
    ("report", "file_pin"), ("source_mode", "file_pin"), ("output", "file_pin"),
    ("deadline", "deadline_expired"), ("interrupt", "interrupted"),
])
def test_vfs_consumer_preserves_failure_report_without_retry_or_new_budget(transport, drift, reason):
    kwargs, _wire, controls, _observed = transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4_vfs(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_vfs_consumer_does_not_substitute_v2_observation_validation(transport, monkeypatch):
    kwargs, _wire, controls, _observed = transport

    def refuse(*_args, **_options):
        raise ValueError("podman_custody_original_observation_v3")

    monkeypatch.setattr(custody, "validate_custody_observation_v3", refuse)
    with pytest.raises(consumer.BuildDependencyError, match="readback_or_evidence_failure") as failure:
        consumer.run_dependency_checked_build_v4_vfs(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert not (kwargs["workspace"] / "dependency-report.json").exists()
