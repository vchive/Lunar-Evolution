"""Actual original-runner processes with an inert test-only compiler/linker.

No CPython, solver, model or isolated build is executed. The C helper only
exercises process reports, actual filesystem outputs and the consumer's gates.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile

_HELPER = r'''
#define _POSIX_C_SOURCE 200809L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static int emit(const char *path, const char *text, int executable) {
    FILE *f = fopen(path, "wb"); if (!f) return 20;
    if (fputs(text, f) < 0 || fclose(f)) return 21;
    return chmod(path, executable ? 0700 : 0600) ? 22 : 0;
}
static void escaped(FILE *f, const char *path) {
    for (; *path; path++) {
        if (*path == '$') fputc('$', f);
        else if (strchr(" \\:#", *path)) fputc('\\', f);
        fputc(*path, f);
    }
}
static int starts(const char *path, const char *text) {
    char value[32] = {0}; FILE *f = fopen(path, "rb"); if (!f) return 0;
    size_t n = fread(value, 1, sizeof(value) - 1, f); fclose(f);
    return n >= strlen(text) && !strncmp(value, text, strlen(text));
}
int main(int argc, char **argv) {
    if (argc >= 4 && !strcmp(argv[1], "ar")) return emit(argv[3], "inert-archive\n", 0);
    const char *target = NULL, *dep = NULL, *source = NULL, *libdir = getenv("ZIG_LIB_DIR");
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-o") && i + 1 < argc) target = argv[++i];
        else if (!strcmp(argv[i], "-c") && i + 1 < argc) source = argv[++i];
        else if (!strcmp(argv[i], "-MF") && i + 1 < argc) dep = argv[++i];
        else if (!strcmp(argv[i], "--dependency-file") && i + 2 < argc) dep = argv[i + 2];
    }
    if (!target || !dep) return 23;
    if (source && starts(source, "nonzero")) return 19;
    if (emit(target, source ? "inert-object\n" : "inert-linked-image\n", !source)) return 24;
    FILE *f = fopen(dep, "wb"); if (!f) return 25;
    escaped(f, target); fputs(":", f);
    if (source) {
        fputc(' ', f); escaped(f, source);
        if (starts(source, "external")) fputs(" /ambient-private/key.h", f);
    } else {
        for (int i = 1; i < argc; i++) {
            size_t n = strlen(argv[i]);
            if (strcmp(argv[i], target) && n > 2 &&
                (!strcmp(argv[i] + n - 2, ".o") || !strcmp(argv[i] + n - 2, ".a"))) {
                fputc(' ', f); escaped(f, argv[i]);
            }
        }
        char crt[8192];
        if (!libdir || snprintf(crt, sizeof(crt), "%s/crt.o", libdir) >= (int)sizeof(crt)) return 26;
        fputc(' ', f); escaped(f, crt);
        if (starts(crt, "cache")) {
            char cwd[8192]; if (!getcwd(cwd, sizeof(cwd))) return 27;
            fputc(' ', f); escaped(f, cwd); fputs("/.zig-global-cache/compiler_rt.a", f);
        }
    }
    fputc('\n', f); return fclose(f) ? 28 : 0;
}
'''


@pytest.fixture(scope="module")
def inert_dependency_tool(tmp_path_factory):
    root = tmp_path_factory.mktemp("actual-dependency-helper")
    source, target = root / "helper.c", root / "helper"
    source.write_text(_HELPER)
    compiler = shutil.which("cc")
    assert compiler is not None, "native fixture suite requires the local test C compiler"
    subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(target)],
                   check=True, capture_output=True, timeout=30)
    return target


@pytest.fixture
def build(tmp_path, monkeypatch, inert_dependency_tool):
    path = recipe.emit_rsi_launch_source_plan(tmp_path / "preparation")
    prep = prepare_rsi_installation_profile(
        reviewed_build_inputs=(recipe._ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=path.read_bytes(), expected_source_plan_sha256=sha(path.read_bytes()),
        source_assets={p.name: p.read_bytes() for p in (path.parent / "assets").iterdir()},
    )

    def prepare(source_bytes=b"inert", crt_bytes=b"crt"):
        source, tools, workspace = tmp_path / "source", tmp_path / "tools", tmp_path / "attempt with space"
        source.mkdir()
        (tools / "lib").mkdir(parents=True)
        (source / "unit.c").write_bytes(source_bytes)
        shutil.copyfile(inert_dependency_tool, tools / "zig")
        (tools / "zig").chmod(0o700)
        (tools / "lib/crt.o").write_bytes(crt_bytes)
        base = base_recipe(prep.sha256, [record("unit.c", source_bytes)],
                           [record("lib/crt.o", crt_bytes), record("zig", (tools / "zig").read_bytes(), True)])
        generated = instrument(monkeypatch, base)
        return prep, {"recipe_bytes": generated.recipe_bytes, "expected_recipe_sha256": generated.sha256,
                      "manifest_bytes": generated.manifest_bytes,
                      "expected_manifest_sha256": sha(generated.manifest_bytes),
                      "source_root": source, "toolchain_root": tools, "workspace": workspace,
                      "deadline": time.monotonic() + 20}
    return prepare


def test_actual_runner_then_original_report_pinned_fd_readback_and_both_comparisons(build):
    prep, kwargs = build()
    result = consumer.run_dependency_checked_build(prep, **kwargs)
    root = kwargs["workspace"]
    assert result.execution_report.completed_stages == ("configure", "freeze", "compile", "link")
    evidence = (root / "dependency-report.json").read_bytes()
    assert sha(evidence) == result.evidence_sha256
    wire = json.loads(evidence)
    assert wire["status"] == "compared" and wire["compilations"] == 3 and wire["links"] == 2
    assert wire["execution_report_sha256"] == sha((root / "report.json").read_bytes())
    for name in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                 "installation_accepted", "production_admission", "online_publication"):
        assert getattr(result, name) is False and wire[name] is False
    outputs = json.loads((root / "dependency-output-inventory.json").read_bytes())
    assert len(outputs) == 11
    assert json.loads((root / "linker-dependency-comparison.json").read_bytes())["links"]
    assert b"/attempt" not in evidence


@pytest.mark.parametrize("kind", ["output", "report", "source", "symlink"])
def test_actual_post_execution_drift_is_not_replaced_by_current_digests(build, monkeypatch, kind):
    prep, kwargs = build()
    original = consumer.run_pinned_build_v3

    def run(*args, **options):
        report = original(*args, **options)
        root = options["workspace"]
        if kind == "output":
            (root / "work/objects/target.o").write_bytes(b"different")
        elif kind == "report":
            (root / "report.json").write_bytes(b"different")
        elif kind == "source":
            (options["source_root"] / "unit.c").write_bytes(b"different")
        else:
            path = root / "work/dependencies/probe.o.d"
            path.rename(path.with_name("retained-original.d"))
            path.symlink_to(path.with_name("retained-original.d"))
        return report

    monkeypatch.setattr(consumer, "run_pinned_build_v3", run)
    with pytest.raises(consumer.BuildDependencyError) as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.execution_report.status == "complete"
    assert not (kwargs["workspace"] / "dependency-report.json").exists()
    assert (kwargs["workspace"] / "report.json").exists()


@pytest.mark.parametrize("source_bytes,crt_bytes", [(b"external", b"crt"), (b"inert", b"cache")])
def test_actual_depfile_with_unpinned_compiler_or_implicit_cache_input_refuses(build, source_bytes, crt_bytes):
    prep, kwargs = build(source_bytes, crt_bytes)
    with pytest.raises(consumer.BuildDependencyError, match="dependency_refused") as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.execution_report.status == "complete"
    assert "private" not in repr(error.value) and error.value.__context__ is None
    assert (kwargs["workspace"] / "report.json").exists()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_original_failed_command_and_partial_report_are_retained_without_comparison(build):
    prep, kwargs = build(b"nonzero")
    with pytest.raises(consumer.BuildDependencyError, match="execution_failed") as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    report = error.value.execution_report
    assert report.status == "partial" and report.reason == "command_failed"
    assert (kwargs["workspace"] / "report.json").exists()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_post_execution_consumer_does_not_start_a_new_deadline(build, monkeypatch):
    prep, kwargs = build()
    clock = {"now": 10.0}
    kwargs.update(deadline=100.0, monotonic=lambda: clock["now"])
    original = consumer.run_pinned_build_v3

    def run(*args, **options):
        assert options["deadline"] == 100.0 and options["monotonic"] is kwargs["monotonic"]
        report = original(*args, **options)
        clock["now"] = 100.0
        return report

    monkeypatch.setattr(consumer, "run_pinned_build_v3", run)
    with pytest.raises(consumer.BuildDependencyError, match="deadline_expired") as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.execution_report.status == "complete"
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_missing_capture_manifest_refuses_before_process_or_workspace(build, monkeypatch):
    prep, kwargs = build()
    kwargs["manifest_bytes"] += b" "

    def forbidden(*args, **options):
        pytest.fail("invalid capture plan reached runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v3", forbidden)
    with pytest.raises(ValueError, match="manifest_pin"):
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert not kwargs["workspace"].exists()


@pytest.mark.parametrize("deadline", [True, 0, -1, 10**1000, float("inf"), float("nan")])
def test_invalid_or_huge_deadline_refuses_with_fixed_error_before_process(build, monkeypatch, deadline):
    prep, kwargs = build()
    kwargs["deadline"] = deadline

    def forbidden(*args, **options):
        pytest.fail("invalid control reached runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v3", forbidden)
    with pytest.raises(consumer.BuildDependencyError, match="build_dependency_control") as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.__context__ is None and not kwargs["workspace"].exists()


def test_huge_callback_clock_refuses_before_process(build, monkeypatch):
    prep, kwargs = build()
    kwargs["monotonic"] = lambda: 10**1000

    def forbidden(*args, **options):
        pytest.fail("invalid callback clock reached runner")

    monkeypatch.setattr(consumer, "run_pinned_build_v3", forbidden)
    with pytest.raises(consumer.BuildDependencyError, match="build_dependency_control") as error:
        consumer.run_dependency_checked_build(prep, **kwargs)
    assert error.value.__context__ is None and not kwargs["workspace"].exists()


def test_readback_rejects_same_byte_path_replacement_during_its_fd_read(tmp_path, monkeypatch):
    path = tmp_path / "retained"
    path.write_bytes(b"retained bytes")
    original, count = consumer._open_beneath, 0

    def open_beneath(root, relative):
        nonlocal count
        count += 1
        if count == 2:
            replacement = root / "replacement"
            replacement.write_bytes(path.read_bytes())
            os.replace(replacement, path)
        return original(root, relative)

    monkeypatch.setattr(consumer, "_open_beneath", open_beneath)
    with pytest.raises(consumer.BuildDependencyError, match="file_changed"):
        consumer._read_pin(tmp_path, record("retained", b"retained bytes"), lambda: None)
