from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import time

import pytest

from tools.static_python_rsi_fixture import execution_backend, recipe
from tools.static_python_rsi_fixture.build_driver import PREPARATION_SHA256
from tools.static_python_rsi_fixture.execution_backend import (
    RECIPE_SCHEMA,
    RECIPE_V2_SCHEMA,
    BuildExecutionError,
    run_pinned_build,
)
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile

_STAGES = ("configure", "freeze", "compile", "link")
_TINY_HEADER = b"#define LUNAR_TINY_FIXTURE 1\n"
_HEADERS = [f"generated-sources/Python/frozen_modules/tiny-{index}.h" for index in range(9)]


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")


def _record(path):
    raw = path.read_bytes()
    return {"path": path.name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "executable": bool(path.stat().st_mode & 0o111)}


def _output(path, *, executable=False, maximum=128):
    return {"path": path, "max_size": maximum, "executable": executable}


def _command(argv, *outputs):
    return {"argv": argv, "outputs": list(outputs)}


@pytest.fixture(scope="module")
def inert_v2_tool(tmp_path_factory):
    directory = tmp_path_factory.mktemp("inert-command-output-tool")
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
    if (fwrite(text, 1, length, stream) != length) { fclose(stream); return 21; }
    return fclose(stream) == 0 ? 0 : 22;
}
static int copy_file(const char *source, const char *target, int executable) {
    FILE *input = fopen(source, "rb");
    if (!input) return 23;
    FILE *output = fopen(target, "wb");
    if (!output) { fclose(input); return 24; }
    unsigned char buffer[4096]; size_t count; int result = 0;
    while ((count = fread(buffer, 1, sizeof(buffer), input)) != 0) {
        if (fwrite(buffer, 1, count, output) != count) { result = 25; break; }
    }
    if (ferror(input)) result = 26;
    if (fclose(input)) result = 27;
    if (fclose(output)) result = 28;
    if (!result && chmod(target, executable ? 0755 : 0644)) result = 29;
    return result;
}
int main(int argc, char **argv) {
    if (argc < 3) return 30;
    if (strcmp(argv[1], "hang") == 0) for (;;) pause();
    if (strcmp(argv[1], "nine") == 0) {
        if (argc != 11) return 31;
        for (int index = 2; index < argc; index++) {
            if (write_file(argv[index], "#define LUNAR_TINY_FIXTURE 1\n")) return 32;
        }
        return 0;
    }
    if (strcmp(argv[1], "clone") == 0) return copy_file(argv[0], argv[2], 1);
    if (strcmp(argv[1], "group-missing") == 0) return copy_file(argv[0], argv[2], 1);
    if (strcmp(argv[1], "group-large") == 0 || strcmp(argv[1], "group-mode") == 0) {
        if (argc != 4 || copy_file(argv[0], argv[2], 1)) return 33;
        if (write_file(argv[3], "too-large")) return 34;
        return strcmp(argv[1], "group-mode") == 0 ? chmod(argv[3], 0755) : 0;
    }
    if (strcmp(argv[1], "clone-rewrite") == 0 || strcmp(argv[1], "rewrite") == 0) {
        if (argc != 4) return 35;
        if (strcmp(argv[1], "clone-rewrite") == 0) {
            if (copy_file(argv[0], argv[2], 1)) return 36;
        } else if (write_file(argv[2], "mutation-command")) return 37;
        if (chmod(argv[3], 0644) || write_file(argv[3], "changed")) return 38;
        return 0;
    }
    if (strcmp(argv[1], "nonzero") == 0) {
        if (write_file(argv[2], "partial")) return 39;
        return 9;
    }
    if (strcmp(argv[1], "emit-extra") == 0) {
        if (argc != 4 || write_file(argv[2], "declared")) return 40;
        return write_file(argv[3], "undeclared-existing");
    }
    if (strcmp(argv[1], "copy") == 0 && argc == 4) return copy_file(argv[2], argv[3], 0);
    return 41;
}
''')
    output = directory / "tool"
    # This builds only our inert helper; it never builds CPython, Zig or a solver.
    subprocess.run(["cc", "-std=c99", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(output)],
                   check=True, capture_output=True)
    return output


@pytest.fixture
def v2_fixture(tmp_path, inert_v2_tool):
    plan = recipe.emit_rsi_launch_source_plan(tmp_path / "prepared")
    preparation = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=plan.read_bytes(),
        expected_source_plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
        source_assets={path.name: path.read_bytes() for path in (plan.parent / "assets").iterdir()},
    )
    source, tools = tmp_path / "source", tmp_path / "tools"
    source.mkdir()
    tools.mkdir()
    (source / "seed.data").write_bytes(b"inert-source")
    (source / "seed.data").chmod(0o444)
    shutil.copyfile(inert_v2_tool, tools / "tool")
    (tools / "tool").chmod(0o555)
    stages = [
        {"stage": "configure", "commands": [
            _command(["@toolchain/tool", "copy", "@source/seed.data", "@work/configure.out"],
                     _output("configure.out")),
        ]},
        {"stage": "freeze", "commands": [
            _command(["@toolchain/tool", "clone", "@work/tools/freezer"],
                     _output("tools/freezer", executable=True, maximum=8 * 1024 * 1024)),
            _command(["@work/tools/freezer", "nine", *("@work/" + path for path in _HEADERS)],
                     *(_output(path) for path in _HEADERS)),
        ]},
        {"stage": "compile", "commands": [
            _command(["@toolchain/tool", "copy", "@work/" + _HEADERS[0], "@work/objects/tiny.o"],
                     _output("objects/tiny.o")),
        ]},
        {"stage": "link", "commands": [
            _command(["@toolchain/tool", "copy", "@work/objects/tiny.o", "@work/image.out"],
                     _output("image.out")),
        ]},
    ]
    payload = {"schema": RECIPE_V2_SCHEMA, "preparation_sha256": PREPARATION_SHA256,
               "inputs": {"source": [_record(source / "seed.data")],
                          "toolchain": [_record(tools / "tool")]},
               "environment": {"LANG": "C", "LC_ALL": "C"}, "stages": stages}
    return preparation, source, tools, tmp_path / "attempt", payload


def _run(fixture, *, deadline=None, **kwargs):
    preparation, source, tools, workspace, payload = fixture
    raw = _canonical(payload)
    return run_pinned_build(
        preparation, recipe_bytes=raw, expected_recipe_sha256=hashlib.sha256(raw).hexdigest(),
        source_root=source, toolchain_root=tools, workspace=workspace,
        deadline=time.monotonic() + 10 if deadline is None else deadline, **kwargs,
    )


def test_same_stage_generated_executable_emits_nine_tiny_headers(v2_fixture):
    report = _run(v2_fixture)
    workspace = v2_fixture[3]
    assert report.status == "complete" and report.completed_stages == _STAGES
    assert not any((report.configured_closure_verified, report.installation_accepted,
                    report.runtime_execution_performed, report.production_admission))
    freeze = report.stage_evidence[1]
    assert len(freeze["commands"]) == 2 and len(freeze["outputs"]) == 10
    assert freeze["commands"][0]["outputs"][0]["executable"] is True
    assert len(freeze["commands"][1]["outputs"]) == 9
    for path, observed in zip(_HEADERS, freeze["commands"][1]["outputs"], strict=True):
        assert (workspace / "work" / path).read_bytes() == _TINY_HEADER
        assert dict(observed) == {"path": path, "size": len(_TINY_HEADER),
                                  "sha256": hashlib.sha256(_TINY_HEADER).hexdigest(),
                                  "executable": False}
    assert (workspace / "work/image.out").read_bytes() == _TINY_HEADER
    for stage in report.stage_evidence:
        for command in stage["commands"]:
            assert command["status"] == "complete" and command["returncode"] == 0
            assert command["direct_child_reaped"] is True
            assert command["descendant_cleanup_verified"] is False
    wire = json.loads((workspace / "report.json").read_bytes())
    assert wire["schema"] == "lunar-static-python-build-execution-report-v2"
    with pytest.raises(TypeError):
        freeze["commands"][0]["outputs"][0]["sha256"] = "forged"


@pytest.mark.parametrize("mutation,code", [
    ("forward_executable", "executable_not_pinned"),
    ("self_executable", "executable_not_pinned"),
    ("nonexecutable", "executable_not_pinned"),
    ("undefined_data", "reference_not_available"),
    ("forward_data", "reference_not_available"),
    ("late_undefined_data", "reference_not_available"),
    ("environment_work", "reference_not_available"),
    ("duplicate_output", "output_duplicate"),
    ("ancestor_output", "output_path_overlap"),
    ("descendant_output", "output_path_overlap"),
    ("v1_stage_shape", "stage_invalid"),
    ("v1_command_shape", "command_invalid"),
    ("boolean_output_size", "output_record_invalid"),
    ("stage_output_budget", "output_budget_exceeded"),
])
def test_v2_graph_refuses_completely_before_workspace_or_spawn(v2_fixture, monkeypatch,
                                                             mutation, code):
    payload = v2_fixture[4]
    freeze = payload["stages"][1]["commands"]
    if mutation == "forward_executable":
        freeze.reverse()
    elif mutation == "self_executable":
        freeze[0]["argv"][0] = "@work/tools/freezer"
    elif mutation == "nonexecutable":
        freeze[0]["outputs"][0]["executable"] = False
    elif mutation in {"undefined_data", "forward_data", "late_undefined_data"}:
        index = 3 if mutation == "late_undefined_data" else 0
        path = "image.out" if mutation == "forward_data" else "never-declared"
        payload["stages"][index]["commands"][0]["argv"].append("@work/" + path)
    elif mutation == "environment_work":
        payload["environment"]["CC"] = "@work/tools/freezer"
    elif mutation == "duplicate_output":
        freeze[0]["outputs"].append(copy.deepcopy(freeze[0]["outputs"][0]))
    elif mutation == "ancestor_output":
        freeze[1]["outputs"].append(_output("tools"))
    elif mutation == "descendant_output":
        freeze[1]["outputs"].append(_output("tools/freezer/child"))
    elif mutation == "v1_stage_shape":
        payload["stages"][0]["outputs"] = [_output("unused")]
    elif mutation == "v1_command_shape":
        payload["stages"][0]["commands"][0] = payload["stages"][0]["commands"][0]["argv"]
    elif mutation == "boolean_output_size":
        freeze[0]["outputs"][0]["max_size"] = True
    else:
        freeze[1]["outputs"] = [_output(f"many/{index}.out") for index in range(256)]
    called = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: called.append(args))
    with pytest.raises(BuildExecutionError, match=code):
        _run(v2_fixture)
    assert called == [] and not v2_fixture[3].exists()


@pytest.mark.parametrize("mode,code", [
    ("group-missing", "attempt_io_failure"),
    ("group-large", "file_invalid"),
    ("group-mode", "file_mode_mismatch"),
])
def test_entire_output_group_must_pass_before_generated_tool_dispatch(v2_fixture, mode, code):
    command = v2_fixture[4]["stages"][1]["commands"][0]
    command["argv"][1] = mode
    command["argv"].append("@work/group/other.out")
    command["outputs"].append(_output("group/other.out", maximum=2 if mode == "group-large" else 128))
    with pytest.raises(BuildExecutionError, match=code) as caught:
        _run(v2_fixture)
    report = caught.value.report
    assert report.completed_stages == ("configure",)
    freeze = report.stage_evidence[-1]
    assert len(freeze["commands"]) == 1 and freeze["outputs"] == ()
    assert freeze["commands"][0]["status"] == "partial"
    assert freeze["commands"][0]["direct_child_reaped"] is True
    assert len(freeze["commands"][0]["outputs"]) == 1
    assert (v2_fixture[3] / "work/tools/freezer").is_file()
    assert not (v2_fixture[3] / "work" / _HEADERS[0]).exists()


@pytest.mark.parametrize("target", ["original", "snapshot", "prior_output"])
def test_input_and_prior_output_drift_block_generated_tool(v2_fixture, target):
    command = v2_fixture[4]["stages"][1]["commands"][0]
    command["argv"][1] = "clone-rewrite"
    command["argv"].append({"original": str(v2_fixture[1] / "seed.data"),
                            "snapshot": "@source/seed.data",
                            "prior_output": "@work/configure.out"}[target])
    code = "output_drift" if target == "prior_output" else "input_drift"
    with pytest.raises(BuildExecutionError, match=code) as caught:
        _run(v2_fixture)
    assert caught.value.report.completed_stages == ("configure",)
    assert len(caught.value.report.stage_evidence[-1]["commands"]) == 1
    assert not (v2_fixture[3] / "work" / _HEADERS[0]).exists()


def test_generated_executable_drift_between_commands_blocks_consumer(v2_fixture):
    commands = v2_fixture[4]["stages"][1]["commands"]
    commands.insert(1, _command(
        ["@toolchain/tool", "rewrite", "@work/mutator.out", "@work/tools/freezer"],
        _output("mutator.out"),
    ))
    with pytest.raises(BuildExecutionError, match="output_drift") as caught:
        _run(v2_fixture)
    freeze = caught.value.report.stage_evidence[-1]
    assert len(freeze["commands"]) == 2
    assert freeze["commands"][0]["status"] == "complete"
    assert freeze["commands"][1]["status"] == "partial"
    assert not (v2_fixture[3] / "work" / _HEADERS[0]).exists()


@pytest.mark.parametrize("stop", ["deadline", "cancel"])
def test_original_control_stops_between_generation_and_consumer(v2_fixture, monkeypatch, stop):
    original = execution_backend._command
    generated = False

    def command(argv, **kwargs):
        nonlocal generated
        original(argv, **kwargs)
        if argv[1] == "clone":
            generated = True

    monkeypatch.setattr(execution_backend, "_command", command)
    code = "deadline_expired" if stop == "deadline" else "interrupted"
    with pytest.raises(BuildExecutionError, match=code) as caught:
        _run(v2_fixture, deadline=1, monotonic=lambda: 1 if generated and stop == "deadline" else 0,
             interrupted=lambda: generated and stop == "cancel")
    freeze = caught.value.report.stage_evidence[-1]
    assert len(freeze["commands"]) == 1 and freeze["commands"][0]["status"] == "partial"
    assert freeze["commands"][0]["returncode"] == 0
    assert freeze["commands"][0]["direct_child_reaped"] is True
    assert freeze["commands"][0]["outputs"] == ()
    assert (v2_fixture[3] / "work/tools/freezer").is_file()
    assert not (v2_fixture[3] / "work" / _HEADERS[0]).exists()


def test_deadline_reaps_generated_direct_child(v2_fixture, monkeypatch):
    v2_fixture[4]["stages"][1]["commands"][1]["argv"][1] = "hang"
    original = subprocess.Popen
    processes = []
    consumer_started = False

    def launch(argv, **kwargs):
        nonlocal consumer_started
        process = original(argv, **kwargs)
        processes.append(process)
        if argv[0] == str(v2_fixture[3] / "work/tools/freezer"):
            consumer_started = True
        return process

    monkeypatch.setattr(subprocess, "Popen", launch)
    with pytest.raises(BuildExecutionError, match="deadline_expired") as caught:
        _run(v2_fixture, deadline=1, monotonic=lambda: int(consumer_started))
    assert len(processes) == 3 and all(process.poll() is not None for process in processes)
    consumer = caught.value.report.stage_evidence[-1]["commands"][-1]
    assert consumer["status"] == "partial" and consumer["direct_child_reaped"] is True
    assert consumer["descendant_cleanup_verified"] is False


def test_nonzero_generator_leaves_partial_and_never_dispatches_consumer(v2_fixture):
    command = v2_fixture[4]["stages"][1]["commands"][0]
    command["argv"][1] = "nonzero"
    with pytest.raises(BuildExecutionError, match="command_failed") as caught:
        _run(v2_fixture)
    freeze = caught.value.report.stage_evidence[-1]
    assert len(freeze["commands"]) == 1
    assert freeze["commands"][0]["returncode"] == 9
    assert freeze["commands"][0]["direct_child_reaped"] is True
    assert (v2_fixture[3] / "work/tools/freezer").read_bytes() == b"partial"
    assert not (v2_fixture[3] / "work" / _HEADERS[0]).exists()


def test_undeclared_existing_future_output_is_never_overwritten(v2_fixture):
    configure = v2_fixture[4]["stages"][0]["commands"][0]
    # Literal paths remain trusted-tool arguments; the later output freshness
    # gate must still refuse a file created outside its producing command.
    extra = v2_fixture[3] / "work/future-tool"
    configure["argv"] = ["@toolchain/tool", "emit-extra", "@work/configure.out", str(extra)]
    freeze = v2_fixture[4]["stages"][1]["commands"]
    freeze[0]["argv"][-1] = "@work/future-tool"
    freeze[0]["outputs"][0]["path"] = "future-tool"
    freeze[1]["argv"][0] = "@work/future-tool"
    with pytest.raises(BuildExecutionError, match="output_not_fresh") as caught:
        _run(v2_fixture)
    assert caught.value.report.completed_stages == ("configure",)
    assert caught.value.report.stage_evidence[-1]["commands"] == ()
    assert extra.read_bytes() == b"undeclared-existing"


@pytest.mark.parametrize("schema", [RECIPE_SCHEMA, RECIPE_V2_SCHEMA])
def test_original_per_role_input_inventory_limit_is_retained(v2_fixture, schema):
    payload = v2_fixture[4]
    payload["schema"] = schema
    # The count gate precedes individual records. Keep this synthetic inventory
    # inside the independent recipe byte limit so the intended gate is reached.
    payload["inputs"]["toolchain"] = [None] * 16385
    with pytest.raises(BuildExecutionError, match="input_inventory_invalid"):
        _run(v2_fixture)
    assert not v2_fixture[3].exists()


@pytest.mark.parametrize("dict_command", [False, True])
def test_v1_does_not_implicitly_adopt_v2_command_semantics(v2_fixture, dict_command):
    payload = v2_fixture[4]
    payload["schema"] = RECIPE_SCHEMA
    for stage in payload["stages"]:
        stage["outputs"] = [output for command in stage["commands"] for output in command["outputs"]]
        if not dict_command:
            stage["commands"] = [command["argv"] for command in stage["commands"]]
    code = "argv_invalid" if dict_command else "executable_not_pinned"
    with pytest.raises(BuildExecutionError, match=code):
        _run(v2_fixture)
    assert not v2_fixture[3].exists()
