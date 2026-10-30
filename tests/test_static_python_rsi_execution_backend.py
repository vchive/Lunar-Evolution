from __future__ import annotations

import errno
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture.build_driver import PREPARATION_SHA256
from tools.static_python_rsi_fixture.execution_backend import (
    RECIPE_SCHEMA,
    BuildExecutionError,
    run_pinned_build,
)
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _record(path):
    raw = path.read_bytes()
    return {"path": path.name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": bool(path.stat().st_mode & 0o111)}


@pytest.fixture(scope="module")
def inert_tool(tmp_path_factory):
    directory = tmp_path_factory.mktemp("inert-build-tool")
    source = directory / "tool.c"
    source.write_text(r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>
static int write_file(const char *name, const char *text) {
    FILE *stream = fopen(name, "wb");
    if (!stream) return 20;
    size_t length = strlen(text);
    if (fwrite(text, 1, length, stream) != length) return 21;
    return fclose(stream) == 0 ? 0 : 22;
}
int main(int argc, char **argv) {
    if (argc < 4) return 23;
    if (strcmp(argv[1], "hang") == 0) for (;;) pause();
    if (strcmp(argv[1], "overflow") == 0) for (;;) { fputs("1234567890", stdout); fflush(stdout); }
    if (strcmp(argv[1], "missing") == 0) return 0;
    if (strcmp(argv[1], "interrupt") == 0) {
        if (write_file(argv[3], "started")) return 24;
        for (;;) pause();
    }
    if (strcmp(argv[1], "nonzero") == 0) {
        if (write_file(argv[3], "partial")) return 25;
        fputs("failure", stderr); return 9;
    }
    if (strcmp(argv[1], "environment") == 0) {
        if (getenv("LUNAR_EVOLUTION_API_KEY") || argc < 5 || !getenv("PATH")
                || strcmp(getenv("PATH"), argv[4]) != 0) return 26;
    }
    if (strcmp(argv[1], "compiler") == 0 && (argc < 5 || strcmp(argv[4], "-c") != 0)) return 29;
    FILE *input = fopen(argv[2], "rb");
    if (!input) return 27;
    char data[128] = {0}; size_t size = fread(data, 1, sizeof(data) - 1, input);
    fclose(input); data[size] = 0;
    if (write_file(argv[3], data)) return 28;
    if (strcmp(argv[1], "rewrite") == 0) {
        if (argc < 5 || chmod(argv[4], 0644) || write_file(argv[4], "changed")) return 30;
    }
    fputs("fixture-log", stdout);
    return 0;
}
''')
    output = directory / "tool"
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
                   check=True, capture_output=True)
    return output


@pytest.fixture
def build_fixture(tmp_path, inert_tool):
    plan = recipe.emit_rsi_launch_source_plan(tmp_path / "prepared")
    preparation = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=plan.read_bytes(),
        expected_source_plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
        source_assets={path.name: path.read_bytes() for path in (plan.parent / "assets").iterdir()},
    )
    source = tmp_path / "source"
    tools = tmp_path / "tools"
    source.mkdir()
    tools.mkdir()
    # This compiler-built inert test helper is not a CPython/toolchain build.
    shutil.copyfile(inert_tool, tools / "tool")
    (tools / "tool").chmod(0o555)
    stages = []
    for stage in ("configure", "freeze", "compile", "link"):
        script = source / (stage + ".data")
        script.write_text(stage)
        script.chmod(0o444)
        stages.append({"stage": stage,
                       "commands": [["@toolchain/tool", "complete", "@source/" + script.name, "@work/" + stage + ".out"]],
                       "outputs": [{"path": stage + ".out", "max_size": 128, "executable": False}]})
    payload = {"schema": RECIPE_SCHEMA, "preparation_sha256": PREPARATION_SHA256,
               "inputs": {"source": [_record(path) for path in sorted(source.iterdir())],
                          "toolchain": [_record(tools / "tool")]},
               "environment": {"LANG": "C", "LC_ALL": "C"}, "stages": stages}
    return preparation, source, tools, tmp_path / "attempt", payload


def _run(fixture, *, payload=None, deadline=None, **kwargs):
    preparation, source, tools, workspace, default = fixture
    raw = _canonical(default if payload is None else payload)
    return run_pinned_build(
        preparation, recipe_bytes=raw, expected_recipe_sha256=hashlib.sha256(raw).hexdigest(),
        source_root=source, toolchain_root=tools, workspace=workspace,
        deadline=time.monotonic() + 10 if deadline is None else deadline, **kwargs,
    )


def _mode(fixture, stage, mode):
    index = ("configure", "freeze", "compile", "link").index(stage)
    fixture[4]["stages"][index]["commands"][0][1] = mode


def test_real_inert_children_complete_fixed_graph_and_retain_evidence(build_fixture):
    report = _run(build_fixture)
    workspace = build_fixture[3]
    assert report.completed_stages == ("configure", "freeze", "compile", "link")
    assert report.status == "complete"
    assert report.configured_closure_verified is False
    assert report.installation_accepted is False
    assert report.runtime_execution_performed is False
    assert report.production_admission is False
    assert json.loads((workspace / "attempt.json").read_bytes())["status"] == "started"
    wire = json.loads((workspace / "report.json").read_bytes())
    assert wire["status"] == "complete"
    assert set(wire) == {
        "schema", "recipe_sha256", "completed_stages", "stage_evidence", "status", "reason",
        "configured_closure_verified", "installation_accepted", "runtime_execution_performed",
        "production_admission",
    }
    assert report.failure_detail is report.persistence_error is None
    for stage in report.stage_evidence:
        command = stage["commands"][0]
        assert command["direct_child_reaped"] is True
        assert command["returncode"] == 0
        assert command["logs"]["stdout"]["size"] == 11
        assert (workspace / "work" / stage["outputs"][0]["path"]).read_bytes() == stage["stage"].encode()
    with pytest.raises(TypeError):
        report.stage_evidence[0]["status"] = "forged"


def test_environment_does_not_inherit_credentials_or_path(build_fixture, monkeypatch):
    monkeypatch.setenv("LUNAR_EVOLUTION_API_KEY", "fixture-secret")
    monkeypatch.setenv("PATH", "/ambient/host/tools")
    _mode(build_fixture, "configure", "environment")
    workspace = build_fixture[3]
    build_fixture[4]["stages"][0]["commands"][0].append(str(workspace / "toolchain" / "bin"))
    assert _run(build_fixture).status == "complete"


def test_recipe_pin_mismatch_has_no_workspace_or_process(build_fixture, monkeypatch):
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    preparation, source, tools, workspace, payload = build_fixture
    with pytest.raises(BuildExecutionError, match="recipe_pin_mismatch"):
        run_pinned_build(preparation, recipe_bytes=_canonical(payload), expected_recipe_sha256="1" * 64,
                         source_root=source, toolchain_root=tools, workspace=workspace,
                         deadline=time.monotonic() + 10)
    assert called == [] and not workspace.exists()


@pytest.mark.parametrize("mutation,code", [
    ("preparation", "preparation_pin_mismatch"),
    ("stage_order", "stage_invalid"),
    ("host_executable", "executable_not_pinned"),
    ("escape", "path_invalid"),
    ("boolean_size", "input_record_invalid"),
    ("credential_environment", "environment_invalid"),
])
def test_preflight_refuses_before_workspace_or_process(build_fixture, mutation, code, monkeypatch):
    payload = build_fixture[4]
    if mutation == "preparation":
        payload["preparation_sha256"] = "1" * 64
    elif mutation == "stage_order":
        payload["stages"].reverse()
    elif mutation == "host_executable":
        payload["stages"][0]["commands"][0][0] = "/bin/sh"
    elif mutation == "escape":
        payload["inputs"]["source"][0]["path"] = "../escape"
    elif mutation == "boolean_size":
        payload["inputs"]["source"][0]["size"] = True
    else:
        payload["environment"]["API_KEY"] = "fixture-secret"
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    with pytest.raises(BuildExecutionError, match=code):
        _run(build_fixture)
    assert called == [] and not build_fixture[3].exists()


def test_input_pin_drift_retains_partial_before_dispatch(build_fixture, monkeypatch):
    (build_fixture[1] / "configure.data").chmod(0o644)
    (build_fixture[1] / "configure.data").write_text("changed")
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    with pytest.raises(BuildExecutionError, match="input_pin_mismatch") as caught:
        _run(build_fixture)
    assert called == []
    assert caught.value.report.status == "partial"
    assert caught.value.report.completed_stages == ()
    assert json.loads((build_fixture[3] / "report.json").read_bytes())["reason"] == "input_pin_mismatch"


def test_symlink_input_is_refused_and_never_executed(build_fixture, monkeypatch):
    source = build_fixture[1]
    original = source / "configure.data"
    original.rename(source / "original")
    original.symlink_to(source / "original")
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    with pytest.raises(BuildExecutionError, match="attempt_io_failure"):
        _run(build_fixture)
    assert called == []


def test_existing_workspace_is_not_modified(build_fixture):
    workspace = build_fixture[3]
    workspace.mkdir()
    (workspace / "retained").write_bytes(b"original")
    with pytest.raises(BuildExecutionError, match="workspace_not_fresh"):
        _run(build_fixture)
    assert list(workspace.iterdir()) == [workspace / "retained"]
    assert (workspace / "retained").read_bytes() == b"original"


def test_nonzero_command_retains_first_failure_and_partial_output(build_fixture):
    _mode(build_fixture, "freeze", "nonzero")
    with pytest.raises(BuildExecutionError, match="command_failed") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert report.completed_stages == ("configure",)
    assert report.stage_evidence[-1]["commands"][0]["returncode"] == 9
    assert report.stage_evidence[-1]["commands"][0]["direct_child_reaped"] is True
    assert (build_fixture[3] / "work/freeze.out").read_bytes() == b"partial"
    assert not (build_fixture[3] / "work/compile.out").exists()
    assert (build_fixture[3] / "logs/freeze/0/stderr.log").read_bytes() == b"failure"


def test_shared_deadline_kills_and_reaps_running_child(build_fixture, monkeypatch):
    _mode(build_fixture, "freeze", "hang")
    processes = []
    original = subprocess.Popen

    def launch(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(BuildExecutionError, match="deadline_expired") as caught:
        _run(build_fixture, deadline=time.monotonic() + 0.25)
    assert caught.value.report.completed_stages == ("configure",)
    assert processes and all(process.poll() is not None for process in processes)
    assert caught.value.report.stage_evidence[-1]["commands"][0]["direct_child_reaped"] is True


def test_interruption_preserves_started_attempt_and_reaps(build_fixture):
    _mode(build_fixture, "configure", "interrupt")
    with pytest.raises(BuildExecutionError, match="interrupted") as caught:
        _run(build_fixture, interrupted=lambda: (build_fixture[3] / "work/configure.out").exists())
    assert caught.value.report.completed_stages == ()
    command = caught.value.report.stage_evidence[0]["commands"][0]
    assert command["status"] == "partial" and command["direct_child_reaped"] is True
    assert (build_fixture[3] / "work/configure.out").read_bytes() == b"started"


def test_log_overflow_is_bounded_and_blocks_later_stages(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    monkeypatch.setattr(execution_backend, "MAX_LOG_BYTES", 128)
    _mode(build_fixture, "configure", "overflow")
    with pytest.raises(BuildExecutionError, match="log_budget_exceeded") as caught:
        _run(build_fixture)
    command = caught.value.report.stage_evidence[0]["commands"][0]
    assert sum(item["size"] for item in command["logs"].values()) == 128
    assert command["direct_child_reaped"] is True
    assert (build_fixture[3] / "logs/configure/0/stdout.log").stat().st_size == 128


def test_missing_output_cannot_complete_stage(build_fixture):
    _mode(build_fixture, "compile", "missing")
    with pytest.raises(BuildExecutionError, match="attempt_io_failure") as caught:
        _run(build_fixture)
    assert caught.value.report.completed_stages == ("configure", "freeze")
    assert caught.value.report.stage_evidence[-1]["status"] == "partial"


def test_prior_output_drift_stops_before_next_stage(build_fixture):
    _mode(build_fixture, "freeze", "rewrite")
    build_fixture[4]["stages"][1]["commands"][0].append("@work/configure.out")
    with pytest.raises(BuildExecutionError, match="output_drift") as caught:
        _run(build_fixture)
    assert caught.value.report.completed_stages == ("configure",)
    assert not (build_fixture[3] / "work/compile.out").exists()


def test_snapshot_drift_stops_before_next_command(build_fixture):
    _mode(build_fixture, "configure", "rewrite")
    build_fixture[4]["stages"][0]["commands"][0].append("@source/freeze.data")
    with pytest.raises(BuildExecutionError, match="input_drift") as caught:
        _run(build_fixture)
    assert caught.value.report.completed_stages == ()
    assert not (build_fixture[3] / "work/freeze.out").exists()


def test_expired_deadline_has_no_workspace(build_fixture):
    with pytest.raises(BuildExecutionError, match="deadline_expired"):
        _run(build_fixture, deadline=time.monotonic() - 1)
    assert not build_fixture[3].exists()


def test_successful_reaped_process_is_never_signalled_by_numeric_pid(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    signalled = []
    monkeypatch.setattr(execution_backend.os, "killpg", lambda *args: signalled.append(args))
    assert _run(build_fixture).status == "complete"
    assert signalled == []


def test_compiler_c_flag_is_passed_as_literal_argv(build_fixture):
    _mode(build_fixture, "compile", "compiler")
    build_fixture[4]["stages"][2]["commands"][0].append("-c")
    assert _run(build_fixture).status == "complete"


def test_environment_reference_refuses_before_workspace(build_fixture):
    build_fixture[4]["environment"]["CC"] = "@foreign/compiler"
    with pytest.raises(BuildExecutionError, match="reference_invalid"):
        _run(build_fixture)
    assert not build_fixture[3].exists()


def test_report_write_failure_carries_partial_report(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    original = execution_backend._write_once

    def write(path, raw):
        if path.name == "report.json":
            raise OSError("fixture path details")
        original(path, raw)

    monkeypatch.setattr(execution_backend, "_write_once", write)
    with pytest.raises(BuildExecutionError, match="report_write_failed") as caught:
        _run(build_fixture)
    assert caught.value.report.status == "partial"
    assert caught.value.report.reason == "report_write_failed"
    assert caught.value.report.failure_detail is None
    assert caught.value.report.persistence_error == {
        "stage": None, "command_index": None, "operation": "report.write", "errno": None,
    }
    assert caught.value.__context__ is None


def test_huge_deadline_is_normalized_before_filesystem_effects(build_fixture):
    with pytest.raises(BuildExecutionError, match="control_invalid") as caught:
        _run(build_fixture, deadline=10**1000)
    assert caught.value.__context__ is None
    assert not build_fixture[3].exists()


def test_interruption_inside_input_copy_stops_before_any_child(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    source = build_fixture[1]
    path = source / "compile.data"
    path.chmod(0o644)
    path.write_bytes(b"x" * 65537)
    path.chmod(0o444)
    build_fixture[4]["inputs"]["source"] = [_record(item) for item in sorted(source.iterdir())]
    original_read = execution_backend.os.read
    reads = []
    called = []

    def read(fd, size):
        result = original_read(fd, size)
        reads.append(len(result))
        return result

    monkeypatch.setattr(execution_backend.os, "read", read)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    with pytest.raises(BuildExecutionError, match="interrupted") as caught:
        _run(build_fixture, interrupted=lambda: len(reads) >= 2)
    assert reads == [65536, 1]
    assert called == []
    assert caught.value.report.completed_stages == ()
    assert (build_fixture[3] / "source/compile.data").stat().st_size == 65536


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EDQUOT])
def test_workspace_resource_failure_is_not_a_freshness_refusal(build_fixture, monkeypatch, error_number):
    workspace = build_fixture[3]
    mkdir = Path.mkdir
    launched = []
    original_error = OSError(error_number, "private fixture details", str(workspace))

    def fail_workspace(path, *args, **kwargs):
        if path == workspace:
            raise original_error
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_workspace)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: launched.append(args))
    with pytest.raises(BuildExecutionError, match="workspace_io_failure") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert report.status == "partial" and report.completed_stages == report.stage_evidence == ()
    assert report.failure_detail == {
        "stage": None, "command_index": None, "operation": "workspace.mkdir", "errno": error_number,
    }
    assert report.persistence_error is None
    assert launched == [] and not workspace.exists()
    assert caught.value.__context__ is None
    assert "private" not in str(caught.value) and str(workspace) not in str(caught.value)
    original_error.errno = errno.EINVAL
    assert report.failure_detail["errno"] == error_number
    with pytest.raises(TypeError):
        report.failure_detail["errno"] = errno.EINVAL


def test_attempt_write_failure_preserves_errno_and_stops_before_children(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    original = execution_backend._write_once
    launched = []

    def write(path, raw):
        if path.name == "attempt.json":
            raise OSError(errno.ENOSPC, "private fixture details", str(path))
        return original(path, raw)

    monkeypatch.setattr(execution_backend, "_write_once", write)
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: launched.append(args))
    with pytest.raises(BuildExecutionError, match="attempt_io_failure") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert report.failure_detail == {
        "stage": None, "command_index": None, "operation": "attempt.write", "errno": errno.ENOSPC,
    }
    assert report.completed_stages == () and report.persistence_error is None
    wire = json.loads((build_fixture[3] / "report.json").read_bytes())
    assert wire["failure_detail"] == report.failure_detail
    assert wire["reason"] == "attempt_io_failure" and "private" not in json.dumps(wire)
    assert (build_fixture[3] / "recipe.json").is_file() and launched == []


def test_stage_directory_failure_retains_stage_command_and_errno(build_fixture, monkeypatch):
    workspace = build_fixture[3]
    mkdir = Path.mkdir

    def fail_logs(path, *args, **kwargs):
        if path == workspace / "logs/freeze/0":
            raise OSError(errno.EDQUOT, "private fixture details", str(path))
        return mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_logs)
    with pytest.raises(BuildExecutionError, match="attempt_io_failure") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert report.completed_stages == ("configure",)
    assert report.failure_detail == {
        "stage": "freeze", "command_index": 0, "operation": "logs.mkdir", "errno": errno.EDQUOT,
    }
    assert report.stage_evidence[-1]["stage"] == "freeze"
    assert report.stage_evidence[-1]["commands"] == ()
    assert not (workspace / "work/freeze.out").exists()
    assert not (workspace / "work/compile.out").exists()


def test_command_spawn_failure_retains_errno_without_retry(build_fixture, monkeypatch):
    popen = subprocess.Popen
    dispatches = []

    def fail_freeze(argv, **kwargs):
        dispatches.append(argv)
        if len(dispatches) == 2:
            raise OSError(errno.EDQUOT, "private fixture details")
        return popen(argv, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", fail_freeze)
    with pytest.raises(BuildExecutionError, match="command_io_failure") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert len(dispatches) == 2 and report.completed_stages == ("configure",)
    assert report.failure_detail == {
        "stage": "freeze", "command_index": 0, "operation": "command.spawn", "errno": errno.EDQUOT,
    }
    command = report.stage_evidence[-1]["commands"][0]
    assert command["failure_detail"] == report.failure_detail
    assert command["returncode"] is None and command["direct_child_reaped"] is False
    assert not (build_fixture[3] / "work/compile.out").exists()


@pytest.mark.parametrize("primary_failure", ["command_failed", "deadline_expired"])
def test_terminal_write_failure_preserves_original_reason(build_fixture, monkeypatch, primary_failure):
    from tools.static_python_rsi_fixture import execution_backend

    original = execution_backend._write_once
    writes = []

    def write(path, raw):
        writes.append(path.name)
        if path.name == "report.json":
            raise OSError(errno.ENOSPC, "private fixture details", str(path))
        return original(path, raw)

    monkeypatch.setattr(execution_backend, "_write_once", write)
    if primary_failure == "command_failed":
        _mode(build_fixture, "freeze", "nonzero")
        controls = {}
    else:
        controls = {"deadline": 1, "monotonic": lambda: 1 if
                    (build_fixture[3] / "work/configure.out").exists() else 0}
    with pytest.raises(BuildExecutionError, match=primary_failure) as caught:
        _run(build_fixture, **controls)
    report = caught.value.report
    assert report.reason == primary_failure and report.status == "partial"
    assert report.completed_stages == (("configure",) if primary_failure == "command_failed" else ())
    assert report.stage_evidence[-1]["commands"][0]["direct_child_reaped"] is True
    assert report.failure_detail is None
    assert report.persistence_error == {
        "stage": None, "command_index": None, "operation": "report.write", "errno": errno.ENOSPC,
    }
    assert writes.count("report.json") == 1 and caught.value.__context__ is None
    assert not (build_fixture[3] / "report.json").exists()
    assert not (build_fixture[3] / "work/compile.out").exists()
    with pytest.raises(TypeError):
        report.persistence_error["errno"] = errno.EINVAL


def test_terminal_write_failure_separately_retains_primary_io_error(build_fixture, monkeypatch):
    from tools.static_python_rsi_fixture import execution_backend

    original = execution_backend._write_once
    writes = []

    def write(path, raw):
        writes.append(path.name)
        if path.name == "attempt.json":
            raise OSError(errno.EDQUOT, "private attempt details", str(path))
        if path.name == "report.json":
            raise OSError(errno.ENOSPC, "private report details", str(path))
        return original(path, raw)

    monkeypatch.setattr(execution_backend, "_write_once", write)
    with pytest.raises(BuildExecutionError, match="attempt_io_failure") as caught:
        _run(build_fixture)
    report = caught.value.report
    assert report.reason == "attempt_io_failure" and report.completed_stages == ()
    assert report.failure_detail == {
        "stage": None, "command_index": None, "operation": "attempt.write", "errno": errno.EDQUOT,
    }
    assert report.persistence_error == {
        "stage": None, "command_index": None, "operation": "report.write", "errno": errno.ENOSPC,
    }
    assert writes == ["recipe.json", "attempt.json", "report.json"]
    assert (build_fixture[3] / "recipe.json").is_file()
    assert caught.value.__context__ is None
