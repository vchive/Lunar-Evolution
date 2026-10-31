"""Pre-dispatch argument refusal; no build, driver or container executes."""

from __future__ import annotations

import json
import time

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tests.test_static_python_rsi_build_driver import (
    preparation as preparation,  # noqa: PLC0414 - shared source-only preparation
)
from tools.static_python_rsi_fixture import command_input_graph as graph
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.dependency_capture import MAX_DEPFILE_BYTES
from tools.static_python_rsi_fixture.link_dependency_capture import _link
from tools.static_python_rsi_fixture.runtime_closure import canonical


@pytest.fixture
def link_recipe(monkeypatch):
    base = base_recipe(sha(b"preparation"), [record("unit.c")],
                       [record("lib/crt.o"), record("zig", executable=True)])
    return json.loads(instrument(monkeypatch, base).recipe_bytes)


def link_command(recipe):
    return recipe["stages"][1]["commands"][1]


def validate(recipe, version4):
    if version4:
        recipe.update(schema=execution.RECIPE_V4_SCHEMA,
                      input_projection=execution.INPUT_PROJECTION_V4)
        graph.validate_dependency_command_graph_v4(recipe)
    else:
        graph.validate_dependency_command_graph(recipe)


@pytest.mark.parametrize("version4", [False, True])
def test_complete_original_capture_vector_remains_valid(link_recipe, version4):
    before = canonical(link_recipe)
    validate(link_recipe, version4)
    if not version4:
        assert canonical(link_recipe) == before


@pytest.mark.parametrize("arguments", [
    ["--config=/unreviewed/driver.cfg"],
    ["-B/unreviewed/bin"],
    ["-Xlinker", "-T", "/unreviewed/linker.script"],
    ["-Wl,@/unreviewed/link.rsp"],
    ["--sysroot=/unreviewed/sysroot"],
])
@pytest.mark.parametrize("version4", [False, True])
def test_link_tail_refuses_options_before_its_valid_capture_suffix(link_recipe, arguments, version4):
    command = link_command(link_recipe)
    command["argv"][-4:-4] = arguments
    # The generator helper deliberately recognizes this broader shape; the
    # actual execution graph must add the missing full-vector refusal.
    assert _link(command) is not None
    with pytest.raises(graph.BuildCommandInputError, match="link_capture") as failure:
        validate(link_recipe, version4)
    assert "unreviewed" not in str(failure.value)


@pytest.mark.parametrize("change", ["missing", "extra-after", "duplicate", "wrong-target", "bound"])
def test_implicit_link_requires_one_exact_bounded_capture(link_recipe, change):
    command = link_command(link_recipe)
    if change == "missing":
        del command["argv"][-4:]
    elif change == "extra-after":
        command["argv"].append("-fuse-ld=unreviewed")
    elif change == "duplicate":
        command["argv"].extend(command["argv"][-4:])
    elif change == "wrong-target":
        command["argv"][-1] = "@work/link-dependencies/other.d"
    else:
        command["outputs"][1]["max_size"] = MAX_DEPFILE_BYTES + 1
    with pytest.raises(graph.BuildCommandInputError, match="link_capture"):
        validate(link_recipe, False)


def explicit_link(recipe):
    command = link_command(recipe)
    argv = command["argv"]
    library_index = argv.index("-lm")
    target_index = argv.index("-o") + 1
    files = ["crt1.o", "crti.o", "libc.a", "libcompiler_rt.a", "crtn.o"]
    recipe["inputs"]["toolchain"].extend(record("lunar-support/" + name) for name in files)
    recipe["inputs"]["toolchain"].sort(key=lambda row: row["path"])
    head, *_, tail = ["@toolchain/lunar-support/" + name for name in files]
    command["argv"] = [*argv[:target_index - 1], "-nostdlib", "-o", argv[target_index],
                       head, "@toolchain/lunar-support/crti.o", *argv[target_index + 1:library_index],
                       "-Xlinker", "--start-group", "@toolchain/lunar-support/libc.a",
                       "@toolchain/lunar-support/libcompiler_rt.a", "-Xlinker", "--end-group", tail,
                       *argv[-4:]]
    return command


def test_original_explicit_support_capture_stays_valid(link_recipe):
    explicit_link(link_recipe)
    validate(link_recipe, False)


@pytest.mark.parametrize("change", ["missing", "bound"])
def test_explicit_support_cannot_omit_or_enlarge_capture(link_recipe, change):
    command = explicit_link(link_recipe)
    if change == "missing":
        del command["argv"][-4:]
    else:
        command["outputs"][1]["max_size"] = MAX_DEPFILE_BYTES + 1
    with pytest.raises(graph.BuildCommandInputError, match="link_capture"):
        validate(link_recipe, False)


@pytest.mark.parametrize("version4", [False, True])
def test_original_executor_refuses_before_preflight_or_workspace(
    link_recipe, preparation, tmp_path, monkeypatch, version4,
):
    link_recipe["preparation_sha256"] = preparation.sha256
    link_command(link_recipe)["argv"][-4:-4] = ["--config=/unreviewed/driver.cfg"]
    if version4:
        link_recipe.update(schema=execution.RECIPE_V4_SCHEMA,
                           input_projection=execution.INPUT_PROJECTION_V4)
    raw = canonical(link_recipe)
    monkeypatch.setattr(custody, "preflight_podman_custody",
                        lambda: pytest.fail("unreviewed link reached preflight"))
    runner = execution.run_pinned_build_v4 if version4 else execution.run_pinned_build_v3
    workspace = tmp_path / "must-stay-absent"
    with pytest.raises(graph.BuildCommandInputError, match="link_capture"):
        runner(preparation, recipe_bytes=raw, expected_recipe_sha256=sha(raw),
               source_root=tmp_path / "source", toolchain_root=tmp_path / "tools",
               workspace=workspace, deadline=time.monotonic() + 30,
               **({} if version4 else {"custody_backend": custody.SNAPSHOT_BACKEND}))
    assert not workspace.exists()
