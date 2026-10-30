"""Worker-view successor routing; original process/OCI execution is doubled.

Pinned files, report readback and dependency comparisons remain real. These
cases do not authenticate an actual worker, protected input or installed runtime.
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

BACKEND = "podman-snapshots-source-data-vfs-worker-input-view-v1"
legacy_transport = source_data_tests.transport


@pytest.mark.parametrize("backend", [None, True, custody.SOURCE_DATA_BACKEND,
                                     custody.SOURCE_DATA_VFS_RETAINED_BACKEND,
                                     custody.SOURCE_DATA_VFS_LIFETIME_BACKEND])
def test_worker_view_executor_requires_exact_backend_before_preflight(v2_fixture, monkeypatch, backend):
    prep, _wire, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        execution.run_pinned_build_v4_vfs_worker_input_view(prep, **kwargs, custody_backend=backend)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("runner", [execution.run_pinned_build_v4,
                                    execution.run_pinned_build_v4_vfs,
                                    execution.run_pinned_build_v4_vfs_retained,
                                    execution.run_pinned_build_v4_vfs_lifetime])
def test_old_executors_cannot_select_worker_view_backend(v2_fixture, monkeypatch, runner):
    prep, _wire, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        runner(prep, **kwargs, custody_backend=BACKEND)
    assert not kwargs["workspace"].exists()


def test_worker_view_executor_retains_one_original_partial_report(v2_fixture, monkeypatch):
    prep, wire, kwargs = options(v2_fixture, monkeypatch)
    contents = {"configure": b"#!/not-an-executor\n", "unit.c": b"unit",
                "zig": _elf(), "lib/crt.o": b"crt"}
    for role in ("source", "toolchain"):
        for record in wire["inputs"][role]:
            _write(kwargs[role + "_root"], record["path"], contents[record["path"]],
                   executable=record["executable"])
    selected = []
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["never-executed"])

    def refuse_original_boundary(**options):
        selected.append(options)
        assert all(options[mode] is True for mode in (
            "snapshot_mounts", "source_data", "vfs_roots", "vfs_retained", "vfs_lifetime", "vfs_worker_input_view"))
        raise execution.BuildExecutionError("worker_view_boundary")

    monkeypatch.setattr(custody, "PodmanCustody", refuse_original_boundary)
    with pytest.raises(execution.BuildExecutionError, match="worker_view_boundary") as failure:
        execution.run_pinned_build_v4_vfs_worker_input_view(prep, **kwargs)
    assert len(selected) == 1 and failure.value.report.status == "partial"
    persisted = json.loads((kwargs["workspace"] / "report.json").read_bytes())
    assert persisted["schema"] == "lunar-static-python-build-execution-report-v8"
    assert persisted["custody_backend"] == BACKEND and persisted["completed_stages"] == []
    assert all(persisted[key] is False for key in (
        "configured_closure_verified", "installation_accepted", "runtime_execution_performed",
        "production_admission", "immutable_custody_verified", "driver_inputs_verified",
        "implicit_link_inputs_verified", "online_publication"))


@pytest.fixture
def worker_transport(legacy_transport, monkeypatch):
    kwargs, wire, controls, observed = legacy_transport
    old_runner = consumer.run_pinned_build_v4
    observation = custody.validate_custody_observation_v2

    def runner(preparation, **selected):
        assert selected["custody_backend"] == BACKEND
        report = old_runner(preparation, **{**selected, "custody_backend": custody.SOURCE_DATA_BACKEND})
        path = kwargs["workspace"] / "report.json"
        value = json.loads(path.read_bytes())
        value.update(schema="lunar-static-python-build-execution-report-v8", custody_backend=BACKEND)
        if controls["drift"] == "old_report":
            value["schema"] = "lunar-static-python-build-execution-report-v7"
        elif controls["drift"] == "mixed_backend":
            value["custody_backend"] = custody.SOURCE_DATA_VFS_LIFETIME_BACKEND
        path.write_bytes(canonical(value))
        return report

    def refuse_old(*_args, **_kwargs):
        pytest.fail("worker-view consumer selected older runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v4_vfs_worker_input_view", runner)
    for name in ("run_pinned_build_v4", "run_pinned_build_v4_vfs",
                 "run_pinned_build_v4_vfs_retained", "run_pinned_build_v4_vfs_lifetime"):
        monkeypatch.setattr(consumer, name, refuse_old)
    monkeypatch.setattr(custody, "validate_custody_observation_v6", observation)
    return kwargs, wire, controls, observed


def test_worker_view_consumer_preserves_original_report_and_ordered_prior_groups(worker_transport):
    kwargs, _wire, controls, observed = worker_transport
    result = consumer.run_dependency_checked_build_v4_vfs_worker_input_view_source_directories(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v7"
    assert evidence["custody_backend"] == BACKEND
    assert evidence["dependency_path_profile"] == "source-inventory-directories-v1"
    assert evidence["compilations"] == 3 and evidence["links"] == 2
    prior = []
    for stage in result.execution_report.stage_evidence:
        for command in stage["commands"]:
            actual_stage, index, actual_prior = observed.pop(0)
            assert actual_stage == stage["stage"] and index == command["index"] and actual_prior == prior
            prior.extend(command["outputs"])
    assert not observed
    for key in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                "installation_accepted", "production_admission", "online_publication"):
        assert evidence[key] is False and getattr(result, key) is False


@pytest.mark.parametrize("drift,reason", [
    ("old_report", "file_pin"), ("mixed_backend", "file_pin"),
    ("source_mode", "file_pin"), ("output", "file_pin"),
    ("deadline", "deadline_expired"), ("interrupt", "interrupted"),
])
def test_worker_view_consumer_preserves_original_failure_and_never_retries(worker_transport, drift, reason):
    kwargs, _wire, controls, _observed = worker_transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4_vfs_worker_input_view_source_directories(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


@pytest.mark.parametrize("runner", [consumer.run_dependency_checked_build_v4,
                                    consumer.run_dependency_checked_build_v4_vfs,
                                    consumer.run_dependency_checked_build_v4_vfs_retained,
                                    consumer.run_dependency_checked_build_v4_vfs_retained_source_directories,
                                    consumer.run_dependency_checked_build_v4_vfs_lifetime_source_directories])
def test_old_consumers_refuse_worker_view_backend_before_execution(worker_transport, runner):
    kwargs, _wire, controls, _observed = worker_transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        runner(object(), **kwargs, custody_backend=BACKEND)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


def test_worker_view_consumer_cannot_skip_original_observation_validation(worker_transport, monkeypatch):
    kwargs, _wire, controls, _observed = worker_transport

    def refuse(*_args, **_kwargs):
        raise ValueError("worker_input_view_original_observation")

    monkeypatch.setattr(custody, "validate_custody_observation_v6", refuse)
    with pytest.raises(consumer.BuildDependencyError, match="readback_or_evidence_failure"):
        consumer.run_dependency_checked_build_v4_vfs_worker_input_view_source_directories(object(), **kwargs)
    assert controls["calls"] == 1 and not (kwargs["workspace"] / "dependency-report.json").exists()
