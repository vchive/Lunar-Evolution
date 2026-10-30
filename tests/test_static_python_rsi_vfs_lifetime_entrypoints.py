"""Explicit lifetime transport; execution and OCI boundaries are doubles.

Real pinned files, report readback and compiler/linker comparisons remain active.
These cases establish neither original kernel-owner observations nor admission.
"""

from __future__ import annotations

import json

import pytest

from tests import test_static_python_source_data_consumer as source_data_tests
from tests.test_static_python_podman_helper_inputs import _elf, _write
from tests.test_static_python_source_data_backend import (
    inert_v2_tool as inert_v2_tool,  # noqa: PLC0414
)
from tests.test_static_python_source_data_backend import (
    v2_fixture as v2_fixture,  # noqa: PLC0414
)
from tests.test_static_python_source_data_vfs_retained_backend import options
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.runtime_closure import canonical

BACKEND = "podman-snapshots-source-data-vfs-lifetime-v1"
legacy_transport = source_data_tests.transport


@pytest.mark.parametrize("backend", [None, True, "podman", custody.SOURCE_DATA_BACKEND,
                                     custody.SOURCE_DATA_VFS_BACKEND,
                                     custody.SOURCE_DATA_VFS_RETAINED_BACKEND])
def test_lifetime_executor_requires_exact_backend_before_preflight(v2_fixture, monkeypatch, backend):
    prep, _wire, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        execution.run_pinned_build_v4_vfs_lifetime(prep, **kwargs, custody_backend=backend)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("runner", [execution.run_pinned_build_v4,
                                    execution.run_pinned_build_v4_vfs,
                                    execution.run_pinned_build_v4_vfs_retained])
def test_old_executors_cannot_select_lifetime_backend(v2_fixture, monkeypatch, runner):
    prep, _wire, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        runner(prep, **kwargs, custody_backend=BACKEND)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("flags", [
    {"version4": False, "vfs_roots": True, "vfs_retained": True, "vfs_lifetime": True},
    {"version4": True, "vfs_roots": False, "vfs_retained": True, "vfs_lifetime": True},
    {"version4": True, "vfs_roots": True, "vfs_retained": False, "vfs_lifetime": True},
    {"version4": True, "vfs_roots": True, "vfs_retained": True, "vfs_lifetime": 1},
], ids=["recipe", "roots", "retention", "not-bool"])
def test_lifetime_executor_modes_refuse_before_effects(v2_fixture, monkeypatch, flags):
    prep, _wire, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight"))
    with pytest.raises(execution.BuildExecutionError):
        execution._run_pinned_build(prep, **kwargs, custody_backend=BACKEND, **flags)
    assert not kwargs["workspace"].exists()


def test_lifetime_executor_retains_original_partial_report_once(v2_fixture, monkeypatch):
    prep, wire, kwargs = options(v2_fixture, monkeypatch)
    contents = {"configure": b"#!/not-an-executor\n", "unit.c": b"unit",
                "zig": _elf(), "lib/crt.o": b"crt"}
    for role in ("source", "toolchain"):
        for row in wire["inputs"][role]:
            _write(kwargs[role + "_root"], row["path"], contents[row["path"]],
                   executable=row["executable"])
    calls = []
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["never-executed"])

    def boundary(**selected):
        calls.append(selected)
        assert all(selected[mode] is True for mode in (
            "snapshot_mounts", "source_data", "vfs_roots", "vfs_retained", "vfs_lifetime"))
        for row in wire["inputs"]["source"]:
            assert execution._observe(selected["destination"] / "source", row["path"], 65536) == row
        raise execution.BuildExecutionError("lifetime_boundary")

    monkeypatch.setattr(custody, "PodmanCustody", boundary)
    with pytest.raises(execution.BuildExecutionError, match="lifetime_boundary") as failure:
        execution.run_pinned_build_v4_vfs_lifetime(prep, **kwargs)
    assert len(calls) == 1 and failure.value.report.status == "partial"
    persisted = json.loads((kwargs["workspace"] / "report.json").read_bytes())
    assert persisted["schema"] == "lunar-static-python-build-execution-report-v7"
    assert persisted["custody_backend"] == BACKEND and persisted["completed_stages"] == []
    for name in ("configured_closure_verified", "installation_accepted", "runtime_execution_performed",
                 "production_admission", "immutable_custody_verified", "driver_inputs_verified",
                 "implicit_link_inputs_verified", "online_publication"):
        assert persisted[name] is False


@pytest.fixture
def lifetime_transport(legacy_transport, monkeypatch):
    kwargs, wire, controls, observed = legacy_transport
    original_runner = consumer.run_pinned_build_v4
    observation = custody.validate_custody_observation_v2

    def runner(preparation, **selected):
        assert selected["custody_backend"] == BACKEND
        report = original_runner(preparation, **{**selected, "custody_backend": custody.SOURCE_DATA_BACKEND})
        path = kwargs["workspace"] / "report.json"
        value = json.loads(path.read_bytes())
        value.update(schema="lunar-static-python-build-execution-report-v7", custody_backend=BACKEND)
        if controls["drift"] == "retained_report":
            value.update(schema="lunar-static-python-build-execution-report-v6",
                         custody_backend=custody.SOURCE_DATA_VFS_RETAINED_BACKEND)
        elif controls["drift"] == "mixed_backend":
            value["custody_backend"] = custody.SOURCE_DATA_VFS_RETAINED_BACKEND
        path.write_bytes(canonical(value))
        return report

    def refuse_old(*_args, **_kwargs):
        pytest.fail("lifetime consumer selected older executor")

    monkeypatch.setattr(consumer, "run_pinned_build_v4_vfs_lifetime", runner)
    for name in ("run_pinned_build_v4", "run_pinned_build_v4_vfs", "run_pinned_build_v4_vfs_retained"):
        monkeypatch.setattr(consumer, name, refuse_old)
    monkeypatch.setattr(custody, "validate_custody_observation_v5", observation)
    return kwargs, wire, controls, observed


def test_lifetime_consumer_uses_one_original_runner_and_exact_persisted_report(lifetime_transport):
    kwargs, _wire, controls, observed = lifetime_transport
    result = consumer.run_dependency_checked_build_v4_vfs_lifetime_source_directories(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v6"
    assert evidence["custody_backend"] == BACKEND
    assert evidence["dependency_path_profile"] == "source-inventory-directories-v1"
    assert evidence["compilations"] == 3 and evidence["links"] == 2
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


@pytest.mark.parametrize("drift,reason", [
    ("retained_report", "file_pin"), ("mixed_backend", "file_pin"),
    ("source_mode", "file_pin"), ("output", "file_pin"),
    ("deadline", "deadline_expired"), ("interrupt", "interrupted"),
])
def test_lifetime_consumer_preserves_failure_without_retry(lifetime_transport, drift, reason):
    kwargs, _wire, controls, _observed = lifetime_transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4_vfs_lifetime_source_directories(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


@pytest.mark.parametrize("runner", [consumer.run_dependency_checked_build_v4,
                                    consumer.run_dependency_checked_build_v4_vfs,
                                    consumer.run_dependency_checked_build_v4_vfs_retained,
                                    consumer.run_dependency_checked_build_v4_vfs_retained_source_directories])
def test_old_consumers_refuse_lifetime_backend_before_execution(lifetime_transport, runner):
    kwargs, _wire, controls, _observed = lifetime_transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        runner(object(), **kwargs, custody_backend=BACKEND)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


@pytest.mark.parametrize("flags", [
    {"version4": True, "vfs_roots": True, "vfs_retained": False,
     "vfs_lifetime": True, "source_directories": True},
    {"version4": True, "vfs_roots": True, "vfs_retained": True,
     "vfs_lifetime": True, "source_directories": False},
    {"version4": True, "vfs_roots": True, "vfs_retained": True,
     "vfs_lifetime": 1, "source_directories": True},
], ids=["retention", "comparison", "not-bool"])
def test_lifetime_consumer_rejects_partial_modes_before_execution(lifetime_transport, flags):
    kwargs, _wire, controls, _observed = lifetime_transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend|dependency_path_profile"):
        consumer._run_dependency_checked_build(object(), **kwargs, custody_backend=BACKEND, **flags)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


def test_lifetime_consumer_cannot_skip_its_observation_validator(lifetime_transport, monkeypatch):
    kwargs, _wire, controls, _observed = lifetime_transport

    def refuse(*_args, **_kwargs):
        raise ValueError("podman_custody_original_observation_v5")

    monkeypatch.setattr(custody, "validate_custody_observation_v5", refuse)
    with pytest.raises(consumer.BuildDependencyError, match="readback_or_evidence_failure"):
        consumer.run_dependency_checked_build_v4_vfs_lifetime_source_directories(object(), **kwargs)
    assert controls["calls"] == 1 and not (kwargs["workspace"] / "dependency-report.json").exists()
