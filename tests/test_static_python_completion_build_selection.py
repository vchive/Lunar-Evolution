"""Opt-in source selection only; no build, producer or sealed target execution."""

from __future__ import annotations

import hashlib
import json

import pytest
import test_static_python_concrete_recipe as concrete_tests

from lunar_evolution.static_python_fixed_live_modules import FIXED_LIVE_SINK_LAUNCHER_PATH
from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from tools.static_python_fixture.profile import ALIASES, CORE_BUILTINS, STATIC_ADDITIONS
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture.build_driver import _preparation_wire
from tools.static_python_rsi_fixture.completion_source import (
    prepare_fixed_producer_completion_sources,
)
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_sink_launcher
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

concrete_inputs = concrete_tests.concrete_inputs


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _closure(facts, sources):
    facts = {**facts, "sources": [
        {"path": path, "size": len(raw), "sha256": _sha(raw)} for path, raw in sorted(sources.items())
    ]}
    return FixedRuntimeClosure(canonical(facts), tuple(sorted(sources.items())))


def _completion_closure(prep, solver):
    tasks = [dict(task) for task in _preparation_wire(prep)["candidate_build_inputs"]["freeze_tasks"]]
    for name, package in ((solver, True), (solver + ".lunar_fixed", False)):
        tasks.append({"name": name, "generator_id": name, "package": package,
                      "source": "producer/" + name.replace(".", "/") + ("/__init__.py" if package else ".py"),
                      "output": "generated-sources/Python/frozen_modules/" + name + ".h"})
    prepared = prepare_fixed_producer_completion_sources(
        solver, frozen_names=tuple(sorted(task["name"] for task in tasks)),
        builtin_names=tuple(sorted(set(CORE_BUILTINS) | set(STATIC_ADDITIONS))),
        aliases=tuple(sorted((target, name) for name, target in ALIASES)),
        frozen_packages=tuple(sorted(task["name"] for task in tasks if task["package"])),
        profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
    )
    sources = {
        "runtime/Modules/config.c": b"/* inert source graph table */\n",
        "runtime/Python/frozen.c": b"/* inert source graph frozen table */\n",
        "runtime/Python/stdlib_module_names.h": b"/* inert source graph names */\n",
        "runtime/frozen_main.py": prepared.frozen_main_source,
        "producer/" + solver + "/__init__.py": b"# inert solver package\n",
        "producer/" + solver + "/lunar_fixed.py": prepared.producer_source,
        COMPLETION_LAUNCHER_PATH: prepared.launcher_source,
    }
    if solver == "shinka":
        # The prospective graph validates its explicit SQLite include directory.
        # This inert header only supplies that graph input; no compile or
        # configured SQLite/native closure acceptance is claimed by this test.
        sources["sqlite/sqlite3.h"] = b"/* inert SQLite include graph input; not a configured header */\n"
    next(task for task in tasks if task["name"] == "_lunar_static_main")["source"] = "runtime/frozen_main.py"
    for task in tasks:
        if task["source"] in sources:
            raw = sources[task["source"]]
            task.update(source_size=len(raw), source_sha256=_sha(raw))
    facts = {"schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": solver,
             "production_admission": False, "runtime_execution_performed": False,
             "native_units": [], "frozen": tasks, "runtime_module_aliases": []}
    return facts, sources


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_only_explicit_completion_profile_selects_pinned_new_launcher(concrete_inputs, solver):
    prep, arguments = concrete_inputs
    facts, sources = _completion_closure(prep, solver)
    result = concrete.prepare_cpython_build_recipe(
        prep, **arguments, runtime_closure=_closure(facts, sources),
        producer_lifecycle_profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
    )
    wire = json.loads(result.recipe_bytes)
    compile_sources = [argument for stage in wire["stages"] if stage["stage"] == "compile"
                       for command in stage["commands"] for argument in command["argv"]
                       if argument.startswith("@source/")]
    assert "@source/" + COMPLETION_LAUNCHER_PATH in compile_sources
    assert "@source/tools/static_python_rsi_fixture/assets/launcher.c" not in compile_sources
    assert "@source/" + FIXED_LIVE_SINK_LAUNCHER_PATH not in compile_sources
    manifest = json.loads(result.manifest_bytes)
    assert manifest["producer_lifecycle_profile"] == FIXED_PRODUCER_LIFECYCLE_PROFILE
    assert manifest["build_performed"] is manifest["production_admission"] is False
    assert dict(result.sources)["runtime/frozen_main.py"] == sources["runtime/frozen_main.py"]


@pytest.mark.parametrize("remove_launcher", (False, True))
def test_completion_sources_never_implicitly_select_legacy_launcher(concrete_inputs, remove_launcher):
    prep, arguments = concrete_inputs
    facts, sources = _completion_closure(prep, "openevolve")
    if remove_launcher:
        del sources[COMPLETION_LAUNCHER_PATH]
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_required"):
        concrete.prepare_cpython_build_recipe(prep, **arguments, runtime_closure=_closure(facts, sources))


@pytest.mark.parametrize("profile", (True, "", "unknown", FIXED_PRODUCER_LIFECYCLE_PROFILE))
def test_completion_selection_requires_exact_profile_and_closure(concrete_inputs, profile):
    prep, arguments = concrete_inputs
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_invalid"):
        concrete.prepare_cpython_build_recipe(prep, **arguments, producer_lifecycle_profile=profile)


@pytest.mark.parametrize("mutation", (
    "missing_launcher", "launcher", "missing_producer", "producer", "dispatch", "collector", "main_task",
))
def test_resigned_completion_source_mutations_refuse_without_fallback(concrete_inputs, mutation):
    prep, arguments = concrete_inputs
    facts, sources = _completion_closure(prep, "openevolve")
    if mutation == "missing_launcher":
        del sources[COMPLETION_LAUNCHER_PATH]
    elif mutation == "launcher":
        raw = sources[COMPLETION_LAUNCHER_PATH]
        sources[COMPLETION_LAUNCHER_PATH] = bytes([raw[0] ^ 1]) + raw[1:]
    elif mutation == "missing_producer":
        del sources["producer/openevolve/lunar_fixed.py"]
    elif mutation == "producer":
        raw = sources["producer/openevolve/lunar_fixed.py"]
        sources["producer/openevolve/lunar_fixed.py"] = bytes([raw[0] ^ 1]) + raw[1:]
    elif mutation == "dispatch":
        sources["runtime/frozen_main.py"] = sources["runtime/frozen_main.py"].replace(
            b"return _lunar_completion_main(", b"return _lunar_completion_fake(", 1,
        )
    elif mutation == "collector":
        sources["runtime/frozen_main.py"] = sources["runtime/frozen_main.py"][:-1] + b" "
    else:
        next(task for task in facts["frozen"] if task["name"] == "_lunar_static_main")["package"] = True
    # Re-sign all caller records; independent pins/canonical composition still refuse.
    for task in facts["frozen"]:
        if task["source"] in sources:
            raw = sources[task["source"]]
            task.update(source_size=len(raw), source_sha256=_sha(raw))
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_source_drift"):
        concrete.prepare_cpython_build_recipe(
            prep, **arguments, runtime_closure=_closure(facts, sources),
            producer_lifecycle_profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
        )


def test_completion_profile_refuses_mixed_legacy_launcher(concrete_inputs):
    prep, arguments = concrete_inputs
    facts, sources = _completion_closure(prep, "openevolve")
    sources[FIXED_LIVE_SINK_LAUNCHER_PATH] = prepare_fixed_live_sink_launcher()
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_mismatch"):
        concrete.prepare_cpython_build_recipe(
            prep, **arguments, runtime_closure=_closure(facts, sources),
            producer_lifecycle_profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
        )


def test_shinka_completion_recipe_still_refuses_missing_sqlite_include_inputs(concrete_inputs):
    prep, arguments = concrete_inputs
    facts, sources = _completion_closure(prep, "shinka")
    del sources["sqlite/sqlite3.h"]
    with pytest.raises(BuildExecutionError, match="directory_reference_not_available"):
        concrete.prepare_cpython_build_recipe(
            prep, **arguments, runtime_closure=_closure(facts, sources),
            producer_lifecycle_profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
        )
