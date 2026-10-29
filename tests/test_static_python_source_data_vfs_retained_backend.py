"""Explicit retained VFS executor transport; custody is replaced with a refusal double.

These cases exercise the original runner's preparation/report lifecycle. They
neither launch Podman nor establish an actual root or production authority.
"""

from __future__ import annotations

import json
import time

import pytest

from tests.test_static_python_podman_helper_inputs import _elf, _write
from tests.test_static_python_source_data_backend import data_payload, sha
from tests.test_static_python_source_data_backend import (
    inert_v2_tool as inert_v2_tool,  # noqa: PLC0414
)
from tests.test_static_python_source_data_backend import (
    v2_fixture as v2_fixture,  # noqa: PLC0414
)
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.runtime_closure import canonical

RETAINED_BACKEND = "podman-snapshots-source-data-vfs-retained-v1"


def options(fixture, monkeypatch):
    prep, source, tools, workspace, _payload = fixture
    value = data_payload(prep.sha256, monkeypatch=monkeypatch)
    raw = canonical(value)
    return prep, value, {
        "recipe_bytes": raw, "expected_recipe_sha256": sha(raw),
        "source_root": source, "toolchain_root": tools,
        "workspace": workspace, "deadline": time.monotonic() + 10,
    }


@pytest.mark.parametrize("backend", [None, custody.SOURCE_DATA_BACKEND, custody.SNAPSHOT_BACKEND,
                                     "podman-snapshots-source-data-vfs-v1", "podman", "host", True])
def test_retained_executor_requires_its_explicit_backend_before_preflight(v2_fixture, monkeypatch, backend):
    prep, _value, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("unexpected preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        execution.run_pinned_build_v4_vfs_retained(prep, **kwargs, custody_backend=backend)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("runner", [execution.run_pinned_build_v4, execution.run_pinned_build_v4_vfs])
def test_older_executors_never_select_retention_implicitly(v2_fixture, monkeypatch, runner):
    prep, _value, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("unexpected preflight"))
    with pytest.raises(execution.BuildExecutionError, match="custody_backend"):
        runner(prep, **kwargs, custody_backend=RETAINED_BACKEND)
    assert not kwargs["workspace"].exists()


def test_retained_executor_uses_original_source_pins_and_retains_one_partial_report(v2_fixture, monkeypatch):
    prep, value, kwargs = options(v2_fixture, monkeypatch)
    contents = {"configure": b"#!/not-an-executor\n", "unit.c": b"unit",
                "zig": _elf(), "lib/crt.o": b"crt"}
    for role in ("source", "toolchain"):
        for row in value["inputs"][role]:
            _write(kwargs[role + "_root"], row["path"], contents[row["path"]],
                   executable=row["executable"])
    calls = []
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["not-executed"])

    def boundary(**selected):
        calls.append(selected)
        assert selected["snapshot_mounts"] is True
        assert selected["source_data"] is True and selected["vfs_roots"] is True
        assert selected["vfs_retained"] is True
        for row in value["inputs"]["source"]:
            assert execution._observe(selected["destination"] / "source", row["path"], 65536) == row
        raise execution.BuildExecutionError("selected_vfs_boundary")

    monkeypatch.setattr(custody, "PodmanCustody", boundary)
    with pytest.raises(execution.BuildExecutionError, match="selected_vfs_boundary") as failure:
        execution.run_pinned_build_v4_vfs_retained(prep, **kwargs)
    assert len(calls) == 1
    persisted = json.loads((kwargs["workspace"] / "report.json").read_bytes())
    assert persisted["schema"] == "lunar-static-python-build-execution-report-v6"
    assert persisted["custody_backend"] == RETAINED_BACKEND
    assert persisted["input_projection"] == execution.INPUT_PROJECTION_V4
    assert persisted["completed_stages"] == [] and persisted["status"] == "partial"
    assert failure.value.report.status == "partial"
    for name in ("configured_closure_verified", "installation_accepted", "runtime_execution_performed",
                 "production_admission", "immutable_custody_verified", "driver_inputs_verified",
                 "implicit_link_inputs_verified", "online_publication"):
        assert persisted[name] is False


@pytest.mark.parametrize("stop", ["deadline", "interrupted"])
def test_retained_executor_preserves_absolute_budget_before_workspace(v2_fixture, monkeypatch, stop):
    prep, _value, kwargs = options(v2_fixture, monkeypatch)
    kwargs.update(deadline=time.monotonic() - 1 if stop == "deadline" else time.monotonic() + 10,
                  interrupted=(lambda: True) if stop == "interrupted" else None)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["not-executed"])
    reason = "deadline_expired" if stop == "deadline" else "interrupted"
    with pytest.raises(execution.BuildExecutionError, match=reason):
        execution.run_pinned_build_v4_vfs_retained(prep, **kwargs)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("flags", [
    {"version4": False, "vfs_roots": True, "vfs_retained": True},
    {"version4": True, "vfs_roots": False, "vfs_retained": True},
    {"version4": True, "vfs_roots": True, "vfs_retained": 1},
])
def test_retained_executor_internal_mode_cannot_be_downgraded(v2_fixture, monkeypatch, flags):
    prep, _value, kwargs = options(v2_fixture, monkeypatch)
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: pytest.fail("unexpected preflight"))
    with pytest.raises(execution.BuildExecutionError):
        execution._run_pinned_build(prep, **kwargs, custody_backend=RETAINED_BACKEND, **flags)
    assert not kwargs["workspace"].exists()
