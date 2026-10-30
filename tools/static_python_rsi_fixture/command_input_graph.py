"""Finite explicit command inputs for the actual dependency build consumer.

Every command must use one of the reviewed compiler, linker, archive or native
freezer forms. This pre-dispatch refusal boundary does not establish all implicit
driver reads, descendant behavior, immutable input custody or build acceptance.
The generic v1/v2/v3 execution mechanisms retain their separate contracts.
"""

from __future__ import annotations

import re

from tools.static_python_rsi_fixture.dependency_capture import MAX_DEPFILE_BYTES
from tools.static_python_rsi_fixture.link_dependency_capture import _link
from tools.static_python_rsi_fixture.standalone_linker import LINKER_PATH

_ENVIRONMENT = {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"}
# Only options emitted by the reviewed concrete/fixed-runtime recipe generators.
# In particular, no response/config/plugin/pass-through/search-path flag is learned
# from a caller's recipe, a successful driver invocation or a dependency report.
_COMPILE_FLAGS = frozenset({
    "-std=c11", "-O2", "-g0", "-fno-strict-aliasing", "-fno-common",
    "-fno-strict-overflow", "-fvisibility=hidden", "-Werror=implicit-function-declaration",
    "-D_GNU_SOURCE", "-DNDEBUG", "-DPy_BUILD_CORE", "-DPy_BUILD_CORE_BUILTIN",
    '-DDATE="Jan 01 1970"', '-DTIME="00:00:00"', '-DGITVERSION=""',
    '-DGITTAG=""', '-DGITBRANCH=""', "-DPY_SQLITE_HAVE_SERIALIZE=1",
    "-D_BSD_SOURCE", "-D_DEFAULT_SOURCE", "-DSQLITE_THREADSAFE=1",
    "-DSQLITE_OMIT_LOAD_EXTENSION=1", "-DSQLITE_ENABLE_DESERIALIZE=1",
})
_GENERATOR = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\Z")


class BuildCommandInputError(ValueError):
    """Fixed pre-dispatch refusal without commands, source or private paths."""


def _fail(reason: str) -> None:
    raise BuildCommandInputError("build_command_input_" + reason)


def _outputs(command: dict, expected: list[tuple[str, bool]]) -> None:
    if (len(command["outputs"]) != len(expected)
            or any(record["path"] != reference.removeprefix("@work/")
                   or record["executable"] is not executable
                   for record, (reference, executable) in zip(
                       command["outputs"], expected, strict=True))):
        _fail("outputs")


def _prior(reference: str, available: dict[str, bool], *, executable: bool = False,
           source_data: bool = False) -> None:
    if (reference not in available
            or (not (source_data and not executable and reference.startswith("@source/"))
                and available[reference] is not executable)):
        _fail("prior_input")


def _directory(reference: str, available: dict[str, bool]) -> None:
    if not reference.startswith(("@source-dir/", "@toolchain-dir/", "@work-dir/")):
        _fail("include_directory")
    role, path = reference.split("/", 1)
    prefix = role.removesuffix("-dir") + "/" + path + "/"
    if not any(item.startswith(prefix) for item in available):
        _fail("prior_input")


def _compile(command: dict, available: dict[str, bool], *, source_data: bool = False) -> None:
    argv = command["argv"]
    if argv[:2] != ["@toolchain/zig", "cc"] or argv.count("-c") != 1 or argv.count("-o") != 1:
        _fail("compile")
    if len(argv) < 11:
        _fail("compile")
    source, target = argv[argv.index("-c") + 1], argv[argv.index("-o") + 1]
    if not source.startswith("@source/") or not target.startswith("@work/") or not target.endswith(".o"):
        _fail("compile")
    _prior(source, available, source_data=source_data)
    depfile = "@work/dependencies/" + target.removeprefix("@work/") + ".d"
    if argv[-5:] != ["-MD", "-MF", depfile, "-MQ", target]:
        _fail("compile_capture")
    _outputs(command, [(target, False), (depfile, False)])
    if command["outputs"][1]["max_size"] != MAX_DEPFILE_BYTES:
        _fail("compile_capture")
    _directory("@toolchain-dir/lib", available)
    seen = set()
    index = 2
    while index < len(argv) - 5:
        arg = argv[index]
        if arg in _COMPILE_FLAGS:
            index += 1
            continue
        if arg not in {"-target", "-I", "-c", "-o"}:
            _fail("compile_option")
        if index + 1 >= len(argv) - 5:
            _fail("compile_option")
        value = argv[index + 1]
        if arg != "-I":
            if arg in seen:
                _fail("compile_option")
            seen.add(arg)
        if arg == "-target" and value != "x86_64-linux-musl":
            _fail("target")
        if arg == "-I":
            _directory(value, available)
        index += 2
    if seen != {"-target", "-c", "-o"}:
        _fail("compile_required_options")


def _archive(command: dict, available: dict[str, bool]) -> None:
    argv = command["argv"]
    if (len(argv) < 5 or argv[:3] != ["@toolchain/zig", "ar", "rcsD"]
            or not argv[3].startswith("@work/libraries/") or not argv[3].endswith(".a")
            or len(set(argv[4:])) != len(argv[4:])):
        _fail("archive")
    for reference in argv[4:]:
        if not reference.startswith("@work/") or not reference.endswith(".o"):
            _fail("archive_input")
        _prior(reference, available)
    _outputs(command, [(argv[3], False)])


def _freezer(command: dict, available: dict[str, bool], *, source_data: bool = False) -> None:
    argv = command["argv"]
    if len(argv) != 4 or _GENERATOR.fullmatch(argv[1]) is None or not argv[2].startswith("@source/"):
        _fail("freezer")
    target = "@work/generated-sources/Python/frozen_modules/" + argv[1] + ".h"
    if argv[3] != target:
        _fail("freezer")
    _prior(argv[0], available, executable=True)
    _prior(argv[2], available, source_data=source_data)
    _outputs(command, [(target, False)])


def _validate_dependency_command_graph(recipe: dict, *, source_data: bool) -> None:
    """Refuse every unaccounted command/input before the original runner starts.

    ``recipe`` is freshly parsed by its explicit capture-plan validator. All
    generated inputs must be outputs of an earlier command, with the required
    executable role; no same-command declaration grants itself an input. This
    finite graph is an explicit-input contract, not a consumed-input observer.
    """
    if any(key not in _ENVIRONMENT or value != _ENVIRONMENT[key]
           for key, value in recipe["environment"].items()):
        _fail("environment")
    available = {"@" + role + "/" + item["path"]: item["executable"]
                 for role, records in recipe["inputs"].items() for item in records}
    archives = 0
    for stage in recipe["stages"]:
        for command in stage["commands"]:
            argv = command["argv"]
            if source_data and argv[0].startswith("@source/"):
                _fail("source_execution")
            _prior(argv[0], available, executable=True)
            if argv[:2] == ["@toolchain/zig", "cc"]:
                if "-c" in argv:
                    if stage["stage"] not in {"configure", "freeze", "compile"}:
                        _fail("stage")
                    _compile(command, available, source_data=source_data)
                else:
                    link = _link(command)
                    if link is None or stage["stage"] not in {"freeze", "link"}:
                        _fail("link")
                    target, references = link
                    _directory("@toolchain-dir/lib", available)
                    for reference in references:
                        _prior(reference, available)
                    depfile = "@work/link-dependencies/" + target.removeprefix("@work/") + ".d"
                    _outputs(command, [(target, True), (depfile, False)])
            elif argv[:2] == ["@toolchain/zig", "ar"]:
                if stage["stage"] != "link":
                    _fail("stage")
                _archive(command, available)
                archives += 1
            elif (argv[0] == "@toolchain/" + LINKER_PATH
                  or source_data and argv[:2] == ["@toolchain/zig", "ld.lld"]):
                link = _link(command)
                if link is None or stage["stage"] not in {"freeze", "link"}:
                    _fail("link")
                target, references = link
                for reference in references:
                    _prior(reference, available)
                depfile = "@work/link-dependencies/" + target.removeprefix("@work/") + ".d"
                _outputs(command, [(target, True), (depfile, False)])
                if command["outputs"][1]["max_size"] != MAX_DEPFILE_BYTES:
                    _fail("link_capture")
            elif argv[0] == "@work/bin/lunar-freeze-module":
                if stage["stage"] != "freeze":
                    _fail("stage")
                _freezer(command, available, source_data=source_data)
            else:
                _fail("command")
            available.update(("@work/" + item["path"], item["executable"])
                             for item in command["outputs"])
    if archives != 1:
        _fail("archive_set")


def validate_dependency_command_graph(recipe: dict) -> None:
    """Validate only the original v3 finite command graph."""
    from tools.static_python_rsi_fixture.execution_backend import RECIPE_V3_SCHEMA

    if recipe.get("schema") != RECIPE_V3_SCHEMA or "input_projection" in recipe:
        _fail("recipe_profile")
    _validate_dependency_command_graph(recipe, source_data=False)


def validate_dependency_command_graph_v4(recipe: dict) -> None:
    """Source execute bits remain observations, never executable tool authority."""
    from tools.static_python_rsi_fixture.execution_backend import (
        INPUT_PROJECTION_V4,
        RECIPE_V4_SCHEMA,
    )

    if (recipe.get("schema") != RECIPE_V4_SCHEMA
            or recipe.get("input_projection") != INPUT_PROJECTION_V4):
        _fail("recipe_profile")
    _validate_dependency_command_graph(recipe, source_data=True)
