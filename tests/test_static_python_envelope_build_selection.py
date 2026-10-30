"""Default-off v2 source/build selection; no target, compiler or solver runs."""

from __future__ import annotations

import json

import pytest
import test_static_python_completion_build_selection as completion_tests
import test_static_python_fixed_runtime_closure as closure_tests

from lunar_evolution.static_python_fixed_live_modules import FIXED_LIVE_SINK_LAUNCHER_PATH
from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
)
from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
)
from tools.static_python_fixture.profile import ALIASES, CORE_BUILTINS, STATIC_ADDITIONS
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import runtime_closure
from tools.static_python_rsi_fixture.envelope_source import prepare_fixed_producer_envelope_sources
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_sink_launcher

concrete_inputs = completion_tests.concrete_inputs
closure_inputs = closure_tests.closure_inputs


def _envelope_closure(prep, solver):
    facts, sources = completion_tests._completion_closure(prep, solver)
    prepared = prepare_fixed_producer_envelope_sources(
        solver, frozen_names=tuple(sorted(task["name"] for task in facts["frozen"])),
        builtin_names=tuple(sorted(set(CORE_BUILTINS) | set(STATIC_ADDITIONS))),
        aliases=tuple(sorted((target, name) for name, target in ALIASES)),
        frozen_packages=tuple(sorted(task["name"] for task in facts["frozen"] if task["package"])),
        profile=FIXED_PRODUCER_ENVELOPE_PROFILE,
    )
    del sources[COMPLETION_LAUNCHER_PATH]
    sources.update({ENVELOPE_LAUNCHER_PATH: prepared.launcher_source,
                    "producer/" + solver + "/lunar_fixed.py": prepared.producer_source,
                    "runtime/frozen_main.py": prepared.frozen_main_source})
    _resign_tasks(facts, sources)
    return facts, sources


def _resign_tasks(facts, sources):
    for task in facts["frozen"]:
        if task["source"] in sources:
            raw = sources[task["source"]]
            task.update(source_size=len(raw), source_sha256=completion_tests._sha(raw))


def _recipe(prep, arguments, facts, sources, profile=FIXED_PRODUCER_ENVELOPE_PROFILE):
    return concrete.prepare_cpython_build_recipe(
        prep, **arguments, runtime_closure=completion_tests._closure(facts, sources),
        producer_lifecycle_profile=profile,
    )


@pytest.mark.parametrize("solver", ("openevolve", "shinka"))
def test_explicit_v2_selects_only_new_pinned_envelope_launcher(concrete_inputs, solver):
    prep, arguments = concrete_inputs
    facts, sources = _envelope_closure(prep, solver)
    result = _recipe(prep, arguments, facts, sources)
    wire = json.loads(result.recipe_bytes)
    compile_sources = [argument for stage in wire["stages"] if stage["stage"] == "compile"
                       for command in stage["commands"] for argument in command["argv"]
                       if argument.startswith("@source/")]
    assert "@source/" + ENVELOPE_LAUNCHER_PATH in compile_sources
    assert "@source/" + COMPLETION_LAUNCHER_PATH not in compile_sources
    assert "@source/" + FIXED_LIVE_SINK_LAUNCHER_PATH not in compile_sources
    assert "@source/tools/static_python_rsi_fixture/assets/launcher.c" not in compile_sources
    manifest = json.loads(result.manifest_bytes)
    assert manifest["producer_lifecycle_profile"] == FIXED_PRODUCER_ENVELOPE_PROFILE
    assert manifest["build_performed"] is manifest["installation_accepted"] is manifest["production_admission"] is False


@pytest.mark.parametrize("remove_launcher", (False, True))
def test_v2_sources_cannot_implicitly_select_default_or_v1(concrete_inputs, remove_launcher):
    prep, arguments = concrete_inputs
    facts, sources = _envelope_closure(prep, "openevolve")
    if remove_launcher:
        del sources[ENVELOPE_LAUNCHER_PATH]
    with pytest.raises(concrete.ConcreteRecipeError, match="envelope_profile_required"):
        _recipe(prep, arguments, facts, sources, profile=None)
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_mismatch|completion_source_drift"):
        _recipe(prep, arguments, facts, sources, profile=FIXED_PRODUCER_LIFECYCLE_PROFILE)


@pytest.mark.parametrize("mutation", (
    "missing_launcher", "launcher", "missing_producer", "producer", "main", "main_task", "producer_task",
))
def test_v2_resigned_source_or_freezer_changes_refuse(concrete_inputs, mutation):
    prep, arguments = concrete_inputs
    facts, sources = _envelope_closure(prep, "openevolve")
    if mutation == "missing_launcher":
        del sources[ENVELOPE_LAUNCHER_PATH]
    elif mutation == "missing_producer":
        del sources["producer/openevolve/lunar_fixed.py"]
    elif mutation in {"launcher", "producer", "main"}:
        path = {"launcher": ENVELOPE_LAUNCHER_PATH, "producer": "producer/openevolve/lunar_fixed.py",
                "main": "runtime/frozen_main.py"}[mutation]
        raw = sources[path]
        sources[path] = bytes([raw[0] ^ 1]) + raw[1:]
    else:
        name = "_lunar_static_main" if mutation == "main_task" else "openevolve.lunar_fixed"
        next(task for task in facts["frozen"] if task["name"] == name)["package"] = True
    _resign_tasks(facts, sources)
    with pytest.raises(concrete.ConcreteRecipeError, match="envelope_source_drift"):
        _recipe(prep, arguments, facts, sources)


@pytest.mark.parametrize("mixed", ("v1", "private_sink"))
def test_v2_refuses_mixed_launchers(concrete_inputs, mixed):
    prep, arguments = concrete_inputs
    facts, sources = _envelope_closure(prep, "openevolve")
    if mixed == "v1":
        _old_facts, old_sources = completion_tests._completion_closure(prep, "openevolve")
        sources[COMPLETION_LAUNCHER_PATH] = old_sources[COMPLETION_LAUNCHER_PATH]
    else:
        sources[FIXED_LIVE_SINK_LAUNCHER_PATH] = prepare_fixed_live_sink_launcher()
    with pytest.raises(concrete.ConcreteRecipeError, match="envelope_profile_mismatch"):
        _recipe(prep, arguments, facts, sources)


@pytest.mark.parametrize("relabel", ("profile_only", "launcher_path", "producer", "main"))
def test_v1_source_cannot_be_upgraded_through_relabelled_metadata(concrete_inputs, relabel):
    prep, arguments = concrete_inputs
    old_facts, old_sources = completion_tests._completion_closure(prep, "openevolve")
    if relabel == "profile_only":
        facts, sources = old_facts, old_sources
        error = "envelope_profile_mismatch"
    else:
        facts, sources = _envelope_closure(prep, "openevolve")
        path = {"launcher_path": ENVELOPE_LAUNCHER_PATH, "producer": "producer/openevolve/lunar_fixed.py",
                "main": "runtime/frozen_main.py"}[relabel]
        sources[path] = old_sources[COMPLETION_LAUNCHER_PATH if relabel == "launcher_path" else path]
        _resign_tasks(facts, sources)
        error = "envelope_source_drift"
    with pytest.raises(concrete.ConcreteRecipeError, match=error):
        _recipe(prep, arguments, facts, sources)


@pytest.mark.parametrize("profile", (FIXED_PRODUCER_ENVELOPE_PROFILE, "fixed-producer-lifecycle-v3", True))
def test_v2_requires_explicit_exact_profile_and_runtime_closure(concrete_inputs, profile):
    prep, arguments = concrete_inputs
    with pytest.raises(concrete.ConcreteRecipeError, match="completion_profile_invalid"):
        concrete.prepare_cpython_build_recipe(prep, **arguments, producer_lifecycle_profile=profile)


def test_default_runtime_closure_still_preserves_legacy_source_and_launcher(closure_inputs):
    result = runtime_closure.prepare_fixed_runtime_closure(**closure_inputs)
    sources = dict(result.sources)
    assert ENVELOPE_LAUNCHER_PATH not in sources
    assert COMPLETION_LAUNCHER_PATH not in sources
    assert sources["producer/" + closure_inputs["solver"] + "/lunar_fixed.py"] == (
        b"from . import helper\nimport json\n"
    )
    assert b"deadline_monotonic_ns" not in sources["runtime/frozen_main.py"]


def test_v2_runtime_closure_refuses_unpinned_original_entrypoint_before_traversal(closure_inputs):
    with pytest.raises(ValueError, match="source_pin"):
        runtime_closure.prepare_fixed_runtime_closure(
            **closure_inputs, live_modules_profile=FIXED_PRODUCER_ENVELOPE_PROFILE,
        )
