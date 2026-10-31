"""Actual inert commands and pre-dispatch refusal of unreviewed command inputs.

The helper copies its own inert native image to exercise a generated freezer.
No CPython, solver, model, immutable custody or accepted runtime is exercised.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from tests.test_static_python_build_dependency_consumer import _HELPER
from tests.test_static_python_build_dependency_consumer import (
    build as build,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_static_python_concrete_recipe import (
    concrete_inputs as concrete_inputs,  # noqa: PLC0414 - pytest fixture re-export
)
from tests.test_static_python_link_dependency_capture import record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture.command_input_graph import (
    BuildCommandInputError,
    validate_dependency_command_graph,
)
from tools.static_python_rsi_fixture.concrete_recipe import ConcreteBuildRecipe
from tools.static_python_rsi_fixture.execution_backend import RECIPE_V3_SCHEMA
from tools.static_python_rsi_fixture.runtime_closure import canonical

_COPY_IMAGE = r'''
static int copy_image(const char *source, const char *target) {
    unsigned char buffer[8192];
    FILE *input = fopen(source, "rb"); if (!input) return 30;
    FILE *output = fopen(target, "wb"); if (!output) { fclose(input); return 31; }
    size_t count;
    int failed = 0;
    while ((count = fread(buffer, 1, sizeof(buffer), input))) {
        if (fwrite(buffer, 1, count, output) != count) { failed = 1; break; }
    }
    if (ferror(input)) failed = 1;
    if (fclose(input)) failed = 1;
    if (fclose(output)) failed = 1;
    return failed || chmod(target, 0700) ? 32 : 0;
}
'''


@pytest.fixture(scope="module")
def inert_dependency_tool(tmp_path_factory):
    root = tmp_path_factory.mktemp("explicit-command-helper")
    source, target = root / "helper.c", root / "helper"
    helper = _HELPER.replace(
        "int main(int argc, char **argv) {",
        _COPY_IMAGE + "int main(int argc, char **argv) {\n"
        '    if (argc == 4 && !strcmp(argv[1], "inert_module"))\n'
        '        return emit(argv[3], "/* inert frozen header */\\n", 0);',
    ).replace(
        'if (emit(target, source ? "inert-object\\n" : "inert-linked-image\\n", !source)) return 24;',
        'if (source ? emit(target, "inert-object\\n", 0) : copy_image(argv[0], target)) return 24;',
    )
    assert helper != _HELPER and "copy_image(argv[0], target)" in helper
    source.write_text(helper)
    compiler = shutil.which("cc")
    assert compiler is not None, "native fixture suite requires the local test C compiler"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
        check=True, capture_output=True, timeout=30,
    )
    return target


def _change(options, mutation):
    wire = json.loads(options["recipe_bytes"])
    mutation(wire)
    raw = canonical(wire)
    manifest = json.loads(options["manifest_bytes"])
    manifest["recipe_sha256"] = sha(raw)
    options.update(recipe_bytes=raw, expected_recipe_sha256=sha(raw),
                   manifest_bytes=canonical(manifest), expected_manifest_sha256=sha(canonical(manifest)))


def _freezer(wire):
    path = "generated-sources/Python/frozen_modules/inert_module.h"
    wire["stages"][1]["commands"].append({
        "argv": ["@work/bin/lunar-freeze-module", "inert_module", "@source/unit.c", "@work/" + path],
        "outputs": [{"path": path, "max_size": 1024, "executable": False}],
    })


def test_actual_concrete_generator_commands_all_pass_the_finite_graph(concrete_inputs):
    preparation, options = concrete_inputs
    generated = capture.prepare_cpython_link_dependency_recipe(preparation, **options)
    wire, _, _ = capture.validate_dependency_capture_plan(
        generated.recipe_bytes, expected_recipe_sha256=generated.sha256,
        manifest_bytes=generated.manifest_bytes, expected_manifest_sha256=sha(generated.manifest_bytes),
    )
    validate_dependency_command_graph(wire)
    assert len([command for stage in wire["stages"] for command in stage["commands"]
                if command["argv"][0] == "@work/bin/lunar-freeze-module"]) == 9


def test_actual_consumer_runs_all_four_reviewed_command_kinds(build):
    preparation, options = build()
    _change(options, _freezer)
    result = consumer.run_dependency_checked_build(preparation, **options)
    root = options["workspace"]
    assert (root / "work/generated-sources/Python/frozen_modules/inert_module.h").read_bytes() == (
        b"/* inert frozen header */\n"
    )
    assert result.execution_report.completed_stages == ("configure", "freeze", "compile", "link")
    outputs = json.loads((root / "dependency-output-inventory.json").read_bytes())
    assert len(outputs) == 12
    evidence = json.loads((root / "dependency-report.json").read_bytes())
    for key in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                "installation_accepted", "production_admission", "online_publication"):
        assert getattr(result, key) is False and evidence[key] is False


def _forbid_runner(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unreviewed command/input reached the execution runner")
    monkeypatch.setattr(consumer, "run_pinned_build_v3", forbidden)


@pytest.mark.parametrize("arguments", [
    ["--config=/ambient-private/driver.cfg"],
    ["-include", "@source/unit.c"],
    ["-Xclang", "-load", "/ambient-private/plugin.so"],
    ["-Wp,-include,/ambient-private/header.h"],
    ["-B/ambient-private/bin"],
    ["--sysroot=/ambient-private/sysroot"],
    ["@source/unit.c"],
    ["/ambient-private/extra.c"],
    ["relative-extra.c"],
    ["-DUNREVIEWED_MACRO=1"],
])
def test_unknown_driver_options_and_hidden_path_routes_refuse_before_workspace(
    build, monkeypatch, arguments,
):
    preparation, options = build()
    _change(options, lambda wire: wire["stages"][0]["commands"][0]["argv"].__setitem__(
        slice(2, 2), arguments,
    ))
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="compile_option") as error:
        consumer.run_dependency_checked_build(preparation, **options)
    assert "ambient-private" not in str(error.value)
    assert not options["workspace"].exists()


def test_reviewed_sqlite_and_hash_module_defines_remain_valid(build):
    preparation, options = build()

    def mutate(wire):
        wire["stages"][0]["commands"][0]["argv"][2:2] = [
            "-DPY_SQLITE_HAVE_SERIALIZE=1", "-D_BSD_SOURCE", "-D_DEFAULT_SOURCE",
            "-DSQLITE_THREADSAFE=1", "-DSQLITE_OMIT_LOAD_EXTENSION=1", "-DSQLITE_ENABLE_DESERIALIZE=1",
        ]

    _change(options, mutate)
    result = consumer.run_dependency_checked_build(preparation, **options)
    assert result.execution_report.status == "complete"
    assert result.driver_inputs_verified is result.implicit_link_inputs_verified is False


def test_required_compiler_target_cannot_be_implicit(build, monkeypatch):
    preparation, options = build()

    def mutate(wire):
        argv = wire["stages"][0]["commands"][0]["argv"]
        index = argv.index("-target")
        del argv[index:index + 2]

    _change(options, mutate)
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="compile_required_options"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


@pytest.mark.parametrize("kind", ["zig-helper", "other-pinned-executable"])
def test_extra_command_is_not_silently_omitted_from_capture_plan(build, monkeypatch, kind):
    preparation, options = build()

    def mutate(wire):
        executable = "@toolchain/zig"
        if kind == "other-pinned-executable":
            wire["inputs"]["toolchain"].append(record("unreviewed-helper", b"inert", True))
            wire["inputs"]["toolchain"].sort(key=lambda item: item["path"])
            executable = "@toolchain/unreviewed-helper"
        wire["stages"][0]["commands"].append({
            "argv": [executable, "unreviewed-helper"],
            "outputs": [{"path": "unreviewed-output", "max_size": 1024, "executable": False}],
        })

    _change(options, mutate)
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="command"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


@pytest.mark.parametrize("key,value", [
    ("CC", "unreviewed-driver"), ("CFLAGS", "-include /ambient-private/input"),
    ("CONFIG_SITE", "@source/unit.c"), ("LANG", "unreviewed-locale"),
])
def test_unreviewed_environment_input_refuses_before_dispatch(build, monkeypatch, key, value):
    preparation, options = build()
    _change(options, lambda wire: wire["environment"].update({key: value}))
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="environment"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


@pytest.mark.parametrize("kind", ["archive-option", "archive-output", "compile-output", "self-directory"])
def test_exact_outputs_archive_mode_and_prior_inputs_are_required(build, monkeypatch, kind):
    preparation, options = build()

    def mutate(wire):
        if kind.startswith("archive"):
            command = wire["stages"][3]["commands"][0]
            if kind == "archive-option":
                command["argv"][2] = "rcs"
            else:
                command["outputs"][0]["executable"] = True
        else:
            command = wire["stages"][0]["commands"][0]
            if kind == "compile-output":
                command["outputs"].append({"path": "extra-output", "max_size": 10, "executable": False})
            else:
                # Generic v3 permits a current output to establish a directory
                # reference; this consumer requires actual prior generated inputs.
                command["argv"][2:2] = ["-I", "@work-dir/dependencies"]

    _change(options, mutate)
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


def test_generated_freezer_cannot_gain_extra_argv_routes(build, monkeypatch):
    preparation, options = build()

    def mutate(wire):
        _freezer(wire)
        wire["stages"][1]["commands"][-1]["argv"].append("/ambient-private/extra-input")

    _change(options, mutate)
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="freezer"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


def test_pinned_resource_directory_required_without_an_unsupported_compiler_option(build, monkeypatch):
    preparation, options = build()
    _change(options, lambda wire: wire["inputs"]["toolchain"].__setitem__(
        slice(None), [row for row in wire["inputs"]["toolchain"] if not row["path"].startswith("lib/")],
    ))
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="prior_input"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


def test_rejected_real_driver_option_is_refused_before_dispatch(build, monkeypatch):
    preparation, options = build()
    _change(options, lambda wire: wire["stages"][0]["commands"][0]["argv"].__setitem__(
        slice(2, 2), ["--zig-lib-dir", "@toolchain-dir/lib"],
    ))
    _forbid_runner(monkeypatch)
    with pytest.raises(BuildCommandInputError, match="compile_option"):
        consumer.run_dependency_checked_build(preparation, **options)
    assert not options["workspace"].exists()


def _source_language_case(build, version):
    preparation, options = build()
    if version == "v4":
        generated = capture._data_source_capture_successor(
            ConcreteBuildRecipe(options["recipe_bytes"], (), options["manifest_bytes"]),
            original_source_inventory_sha256=sha(canonical(
                json.loads(options["recipe_bytes"])["inputs"]["source"])),
        )
        options.update(recipe_bytes=generated.recipe_bytes, expected_recipe_sha256=generated.sha256,
                       manifest_bytes=generated.manifest_bytes,
                       expected_manifest_sha256=sha(generated.manifest_bytes))
    options["custody_backend"] = ("podman-snapshots-source-data-v2" if version == "v4" else
                                  "podman")
    runner = (consumer.run_dependency_checked_build_v4 if version == "v4" else
              consumer.run_dependency_checked_build)
    return preparation, options, runner


@pytest.mark.parametrize("version", ["v3", "v4"])
@pytest.mark.parametrize("extension", [".s", ".S", ".i", ".cpp", ".o"])
def test_alternate_source_language_refuses_before_original_consumer_preflight(
    build, monkeypatch, version, extension,
):
    preparation, options, runner = _source_language_case(build, version)
    wire, manifest = json.loads(options["recipe_bytes"]), json.loads(options["manifest_bytes"])
    source = "unit" + extension
    wire["inputs"]["source"].append({**wire["inputs"]["source"][0], "path": source})
    wire["inputs"]["source"].sort(key=lambda record: record["path"])
    argv = wire["stages"][0]["commands"][0]["argv"]
    argv[argv.index("-c") + 1] = "@source/" + source
    manifest["compilations"], manifest["links"] = capture._capture_plan(wire, instrumented=True)
    raw = canonical(wire)
    manifest["recipe_sha256"] = sha(raw)
    if version == "v4":
        original = {key: value for key, value in wire.items() if key != "input_projection"}
        original["schema"] = RECIPE_V3_SCHEMA
        manifest.update(base_recipe_sha256=sha(canonical(original)),
                        source_inventory_sha256=sha(canonical(wire["inputs"]["source"])),
                        inputs_sha256=sha(canonical(wire["inputs"])))
    options.update(recipe_bytes=raw, expected_recipe_sha256=sha(raw),
                   manifest_bytes=canonical(manifest), expected_manifest_sha256=sha(canonical(manifest)))

    def forbidden(*args, **kwargs):
        pytest.fail("alternate source language reached original runner or preflight")

    from tools.static_python_rsi_fixture import podman_custody as custody

    monkeypatch.setattr(consumer, "run_pinned_build_v3", forbidden)
    monkeypatch.setattr(consumer, "run_pinned_build_v4", forbidden)
    monkeypatch.setattr(custody, "preflight_podman_custody", forbidden)
    with pytest.raises(BuildCommandInputError, match="^build_command_input_compile$"):
        runner(preparation, **options)
    assert not options["workspace"].exists()


@pytest.mark.parametrize("version", ["v3", "v4"])
def test_reviewed_c_source_reaches_original_consumer_preflight_without_wire_changes(
    build, monkeypatch, version,
):
    preparation, options, runner = _source_language_case(build, version)
    original_wire, original_manifest = options["recipe_bytes"], options["manifest_bytes"]

    class PreflightReached(BaseException):
        pass

    def preflight():
        raise PreflightReached

    from tools.static_python_rsi_fixture import podman_custody as custody

    monkeypatch.setattr(custody, "preflight_podman_custody", preflight)
    with pytest.raises(PreflightReached):
        runner(preparation, **options)
    assert options["recipe_bytes"] == original_wire and options["manifest_bytes"] == original_manifest
    assert not options["workspace"].exists()
