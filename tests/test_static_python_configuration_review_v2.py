"""Synthetic external v2 review fixtures with real CPython output shapes.

These fixtures exercise the original recipe generator without running configure,
a compiler, an interpreter target or a solver. They do not approve real outputs.
"""

from __future__ import annotations

import copy
import json

import pytest

from tests.test_static_python_configuration_review import (
    _arguments as v1_arguments,
)
from tests.test_static_python_configuration_review import (
    _bind as v1_bind,
)
from tests.test_static_python_configuration_review import (
    _roles,
    concrete_inputs,  # noqa: F401 - dependency of the imported pytest fixture
    review_case,  # noqa: F401 - shared pytest fixture
    sha,
)
from tools.static_python_fixture.configure_plan import _DISABLED, emit_configure_plan_assets
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import configuration_review as v1
from tools.static_python_rsi_fixture import configuration_review_v2 as v2
from tools.static_python_rsi_fixture.build_driver import _preparation_wire
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

_REAL_OVERRIDE_EXPRESSIONS = {
    "PY_CFLAGS": "$(BASECFLAGS) $(OPT) $(CONFIGURE_CFLAGS) $(CFLAGS) $(EXTRA_CFLAGS)",
    "PY_CFLAGS_NODIST": ("$(CONFIGURE_CFLAGS_NODIST) $(CFLAGS_NODIST) "
                          "-I$(srcdir)/Include/internal -I$(srcdir)/Include/internal/mimalloc"),
    "PY_CPPFLAGS": "$(BASECPPFLAGS) -I. -I$(srcdir)/Include $(CONFIGURE_CPPFLAGS) $(CPPFLAGS)",
    "PY_LDFLAGS": "$(CONFIGURE_LDFLAGS) $(LDFLAGS)",
    "PY_LDFLAGS_NODIST": "$(CONFIGURE_LDFLAGS_NODIST) $(LDFLAGS_NODIST)",
}
_REAL_BOOTSTRAP_LINK_REFERENCES = (
    "MODULE_ATEXIT_LDFLAGS", "MODULE_FAULTHANDLER_LDFLAGS", "MODULE_POSIX_LDFLAGS",
    "MODULE__SIGNAL_LDFLAGS", "MODULE__CODECS_LDFLAGS", "MODULE__IO_LDFLAGS",
    "MODULE__THREAD_LDFLAGS", "MODULE__WEAKREF_LDFLAGS", "MODULE__ABC_LDFLAGS",
)
_REAL_OVERRIDE_PARENTS = {
    "CFLAGS": "PY_CFLAGS", "EXTRA_CFLAGS": "PY_CFLAGS", "CFLAGS_NODIST": "PY_CFLAGS_NODIST",
    "CPPFLAGS": "PY_CPPFLAGS", "LDFLAGS": "PY_LDFLAGS", "LDFLAGS_NODIST": "PY_LDFLAGS_NODIST",
}


def _v2_stages(stages):
    """Declare the two fixed v2 includes separately from default generation."""
    stages = copy.deepcopy(stages)
    for stage in stages:
        for command in stage["commands"]:
            argv = command["argv"]
            if "-c" in argv:
                offset = argv.index("@source-dir/Include/internal/mimalloc") + 1
                argv[offset:offset] = ["-I", "@source-dir/Objects", "-I", "@source-dir/Python"]
    return stages


def _facts(arguments, outputs, stages, roles):
    originals = dict(outputs)
    variables = v2._make(originals["Makefile"])
    semantics = v1._semantics(stages, roles)
    return {
        "schema": v2.SCHEMA, "profile": v2.PROFILE, "target": "x86_64-linux-musl",
        "source_inventory_sha256": arguments["expected_source_inventory_sha256"],
        "zig_manifest_sha256": sha(arguments["zig_manifest_bytes"]),
        "outputs": [{"path": name, "size": len(raw), "sha256": sha(raw)} for name, raw in outputs],
        "header_directives": v2._header(originals["pyconfig.h"]),
        "make_variables": variables,
        "make_absences": v2._make_absences(originals["Makefile"]),
        "make_absent_references": v2._make_absent_references(originals["Makefile"]),
        "setup_rows": {
            "Modules/Setup.bootstrap": v1._setup(originals["Modules/Setup.bootstrap"]),
            "Modules/Setup.local": v1._setup(emit_configure_plan_assets()["Modules/Setup.local"]),
        },
        "stdlib_discovery_rows": v2._stdlib_discovery(originals["Modules/Setup.stdlib"]),
        "config_modules": v1._config_modules(originals["Modules/config.c"]),
        "recipe_semantics": semantics,
        "concrete_stages_sha256": sha(canonical(stages)),
        "adaptations": v2._adaptations(variables, semantics),
    }


@pytest.fixture
def review_v2_case(review_case):  # noqa: F811
    prep, arguments, originals, _, _, _, _ = review_case
    arguments = arguments.copy()
    header = (b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n" + originals[0][1]
              + b"#endif /*Py_PYCONFIG_H*/\n")
    arguments.update(configuration_header=header, expected_configuration_sha256=sha(header))
    legacy = concrete.prepare_cpython_build_recipe(prep, **arguments)
    stages = _v2_stages(json.loads(legacy.recipe_bytes)["stages"])
    roles = _roles(prep)
    makefile = dict(originals)["Makefile"]
    for name in ("PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ"):
        makefile = makefile.replace((name + " = \n").encode(), b"")
    makefile = makefile.replace(b"MODDISABLED_NAMES = \n",
                                ("MODDISABLED_NAMES = " + " ".join(_DISABLED) + "\n").encode())
    for name, expression in _REAL_OVERRIDE_EXPRESSIONS.items():
        makefile = _make_value(makefile, name, expression)
    makefile = _make_value(makefile, "MODLIBS", "$(LOCALMODLIBS)")
    makefile += ("BASECFLAGS =\nOPT = -O2 -g0\nCONFIGURE_CFLAGS =\nCONFIGURE_CFLAGS_NODIST =\n"
                 "BASECPPFLAGS = -IObjects -IInclude -IPython\nCONFIGURE_CPPFLAGS =\nsrcdir = .\n"
                 "CONFIGURE_LDFLAGS =\nCONFIGURE_LDFLAGS_NODIST =\nLOCALMODLIBS = "
                 + " ".join("$(" + name + ")" for name in _REAL_BOOTSTRAP_LINK_REFERENCES) + "\n").encode()
    archive = next(command["argv"] for stage in stages for command in stage["commands"]
                   if command["argv"][:2] == ["@toolchain/zig", "ar"])
    members = " ".join(token.removeprefix("@work/objects/") for token in archive[4:])
    makefile += ("LIBRARY_OBJS = " + members + "\n").encode()
    discovery = (b"# synthetic discovery, not enabled modules\n*shared*\n"
                 b"_md5 md5module.c -I$(srcdir)/Modules/_hacl/include _hacl/Hacl_Hash_MD5.c\n"
                 b"_socket socketmodule.c\n")
    outputs = tuple((name, header if name == "pyconfig.h" else makefile if name == "Makefile"
                     else discovery if name == "Modules/Setup.stdlib" else raw) for name, raw in originals)
    return prep, arguments, outputs, _facts(arguments, outputs, stages, roles), stages, roles, legacy


def _arguments(case, *, outputs=None, facts=None):
    raw = canonical(case[3] if facts is None else facts)
    return {**case[1], "configuration_outputs": case[2] if outputs is None else outputs,
            "review_manifest_bytes": raw, "expected_review_manifest_sha256": sha(raw)}


def _bind(case, *, outputs=None, facts=None, stages=None, roles=None, zig_pin=None):
    raw = canonical(case[3] if facts is None else facts)
    return v2.bind_reviewed_cpython_configuration(
        configuration_outputs=case[2] if outputs is None else outputs, review_manifest_bytes=raw,
        expected_review_manifest_sha256=sha(raw),
        source_inventory_sha256=case[1]["expected_source_inventory_sha256"],
        zig_manifest_sha256=sha(case[1]["zig_manifest_bytes"]) if zig_pin is None else zig_pin,
        configuration_header=case[1]["configuration_header"],
        stages=case[4] if stages is None else stages, compile_roles=case[5] if roles is None else roles,
    )


def _changed_outputs(case, name, raw):
    return tuple((path, raw if path == name else original) for path, original in case[2])


def _make_value(raw, name, value):
    selected = (name + " = " + value).encode()
    return b"\n".join(selected if line.split(b"=", 1)[0].strip() == name.encode() else line
                      for line in raw.splitlines()) + b"\n"


def _stock_outputs(case):
    original = dict(case[2])["Makefile"]
    raw = original.replace(b"LIBRARY_OBJS = ", b"LIBRARY_OBJS = Modules/getpath.o Python/frozen.o ")
    return _changed_outputs(case, "Makefile", raw)


def _runtime_case(case, *, module="_json", source="Modules/_json.c", obj="Modules/_json.o"):
    """Generate the original graph with an inert, explicit runtime closure."""
    prep, original_arguments, _, _, _, original_roles, _ = case
    arguments = original_arguments.copy()
    native_source = b"/* synthetic native source; never compiled */\n"
    inventory = json.loads(arguments["source_inventory_bytes"])
    inventory.append({"path": source, "size": len(native_source), "sha256": sha(native_source),
                      "executable": False})
    inventory.append({"path": "Modules/_hacl/include/fixture.h", "size": 1, "sha256": sha(b"x"),
                      "executable": False})
    arguments["source_inventory_bytes"] = canonical(sorted(inventory, key=lambda row: row["path"]))
    arguments["expected_source_inventory_sha256"] = sha(arguments["source_inventory_bytes"])
    generated = {
        "runtime/Modules/config.c": b"/* synthetic runtime table */\n",
        "runtime/Python/frozen.c": b"/* synthetic runtime frozen table */\n",
        "runtime/Python/stdlib_module_names.h": b"/* synthetic runtime names */\n",
        "runtime/frozen_main.py": b"def _rsi_launch(x): pass\n",
    }
    tasks = copy.deepcopy(_preparation_wire(prep)["candidate_build_inputs"]["freeze_tasks"])
    tasks[-1].update(source="runtime/frozen_main.py", source_size=len(generated["runtime/frozen_main.py"]),
                     source_sha256=sha(generated["runtime/frozen_main.py"]))
    closure_facts = {
        "schema": "lunar-fixed-python-runtime-source-closure-v1", "solver": "openevolve",
        "production_admission": False, "runtime_execution_performed": False,
        "native_units": [{"module": module, "source": source, "object": obj,
                          "source_size": len(native_source), "source_sha256": sha(native_source),
                          "extra_flags": []}],
        "frozen": tasks,
        "sources": [{"path": path, "size": len(raw), "sha256": sha(raw)}
                    for path, raw in sorted(generated.items())],
    }
    closure = FixedRuntimeClosure(canonical(closure_facts), tuple(sorted(generated.items())))
    legacy = concrete.prepare_cpython_build_recipe(prep, **arguments, runtime_closure=closure)
    stages = _v2_stages(json.loads(legacy.recipe_bytes)["stages"])
    roles = original_roles.copy()
    for old, new in (("generated-sources/Modules/config.c", "runtime/Modules/config.c"),
                     ("generated-sources/Python/frozen.c", "runtime/Python/frozen.c")):
        roles["@source/" + new] = roles.pop("@source/" + old)
    roles["@source/" + source] = "builtin"
    # Configure's original baseline has neither the fixed fixture pipe nor the
    # runtime native unit. The v2 relation must describe both finite additions.
    makefile = dict(case[2])["Makefile"]
    library = v2._make(makefile)["LIBRARY_OBJS"]["tokens"]
    makefile = _make_value(makefile, "LIBRARY_OBJS",
                           " ".join(token for token in library if token != "Modules/lunar_fixture_pipe.o"))
    outputs = _changed_outputs(case, "Makefile", makefile)
    return (prep, arguments, outputs, _facts(arguments, outputs, stages, roles), stages, roles, legacy), closure


@pytest.fixture
def runtime_review_v2_case(review_v2_case):
    return _runtime_case(review_v2_case)


def _shinka_runtime_case(case):
    """Hand-author the finite SQL addition from inert command copies."""
    stages, roles, facts = copy.deepcopy(case[4]), case[5].copy(), copy.deepcopy(case[3])
    freeze = next(stage["commands"] for stage in stages if stage["stage"] == "freeze")
    template = next(command for command in freeze if "@source/Modules/_json.c" in command["argv"])
    sources = [("_sqlite3", "Modules/_sqlite/" + name + ".c") for name in (
        "blob", "connection", "cursor", "microprotocols", "module", "prepare_protocol", "row", "statement", "util",
    )] + [("sqlite-library", "sqlite/sqlite3.c")]
    additions = []
    for module, source in sources:
        obj = source[:-2] + ".o"
        command = copy.deepcopy(template)
        command["argv"][command["argv"].index("-c") + 1] = "@source/" + source
        command["argv"][command["argv"].index("-o") + 1] = "@work/objects/" + obj
        command["outputs"][0]["path"] = "objects/" + obj
        freeze.insert(freeze.index(template), command)
        roles["@source/" + source] = "builtin"
        additions.append({"module": module, "source": "@source/" + source, "object": "@work/objects/" + obj,
                          "role": "builtin", "links": ["freeze", "link"]})
    for stage in stages:
        for command in stage["commands"]:
            argv = command["argv"]
            if argv[:2] == ["@toolchain/zig", "cc"] and "-c" not in argv:
                if stage["stage"] == "freeze":
                    argv[-3:-3] = [row["object"] for row in additions]
                else:
                    argv[6] = "@work/bin/lunar-shinka"
                    command["outputs"][0]["path"] = "bin/lunar-shinka"
            elif argv[:2] == ["@toolchain/zig", "ar"]:
                argv.extend(row["object"] for row in additions)
    facts["recipe_semantics"] = v1._semantics(stages, roles)
    facts["concrete_stages_sha256"] = sha(canonical(stages))
    # Expected relations are authored independently of the production
    # adaptation parser, which must derive the same complete finite group.
    facts["adaptations"]["runtime_native_additions"] = sorted(
        [*facts["adaptations"]["runtime_native_additions"], *additions], key=lambda row: row["source"],
    )
    return (*case[:3], facts, stages, roles, case[6])


def test_explicit_v2_review_reaches_the_original_complete_recipe(review_v2_case):
    prep, _, outputs, facts, stages, _, _ = review_v2_case
    build = concrete.prepare_cpython_build_recipe(prep, **_arguments(review_v2_case))
    wire = _recipe(build.recipe_bytes, build.sha256, version3=True)
    assert wire["stages"] == stages
    assert facts["schema"] != v1.SCHEMA
    staged = dict(build.sources)
    for name, raw in outputs:
        assert staged["configuration/original/" + name] == raw
    assert staged["configuration/review.json"] == canonical(facts)
    manifest = json.loads(build.manifest_bytes)
    assert manifest["configuration_review_manifest_sha256"] == sha(canonical(facts))
    assert manifest["reviewed_concrete_stages_sha256"] == sha(canonical(stages))
    assert manifest["configured_closure_verified"] is False
    assert manifest["production_admission"] is False and manifest["build_performed"] is False


def test_explicit_runtime_native_and_fixture_pipe_additions_reach_the_original_generator(runtime_review_v2_case):
    case, closure = runtime_review_v2_case
    build = concrete.prepare_cpython_build_recipe(case[0], **_arguments(case), runtime_closure=closure)
    wire = _recipe(build.recipe_bytes, build.sha256, version3=True)
    assert wire["stages"] == case[4]
    assert json.loads(build.manifest_bytes)["runtime_closure_sha256"] == closure.sha256
    adaptations = json.loads(dict(build.sources)["configuration/review.json"])["adaptations"]
    assert adaptations["runtime_native_additions"] == [{
        "module": "_json", "source": "@source/Modules/_json.c", "object": "@work/objects/Modules/_json.o",
        "role": "builtin", "links": ["freeze", "link"],
    }]
    assert adaptations["fixture_pipe_addition"] == {
        "source": "@source/tools/static_python_fixture/assets/pipe.c",
        "object": "@work/objects/Modules/lunar_fixture_pipe.o", "role": "builtin", "links": ["freeze", "link"],
    }
    library = case[3]["make_variables"]["LIBRARY_OBJS"]["tokens"]
    assert "Modules/_json.o" not in library and "Modules/lunar_fixture_pipe.o" not in library
    assert "Modules/config.o" in library


def test_original_generator_accepts_the_fixed_pipe_addition_without_a_runtime_closure(review_v2_case):
    original = dict(review_v2_case[2])["Makefile"]
    library = review_v2_case[3]["make_variables"]["LIBRARY_OBJS"]["tokens"]
    raw = _make_value(original, "LIBRARY_OBJS", " ".join(t for t in library if t != "Modules/lunar_fixture_pipe.o"))
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    build = concrete.prepare_cpython_build_recipe(review_v2_case[0], **_arguments(
        review_v2_case, outputs=outputs, facts=facts,
    ))
    assert json.loads(build.manifest_bytes)["runtime_closure_sha256"] is None
    assert facts["adaptations"]["runtime_native_additions"] == []
    assert facts["adaptations"]["fixture_pipe_addition"] == {
        "source": "@source/tools/static_python_fixture/assets/pipe.c",
        "object": "@work/objects/Modules/lunar_fixture_pipe.o", "role": "builtin", "links": ["freeze", "link"],
    }


@pytest.mark.parametrize("module,source,obj", [
    ("_unapproved", "Modules/_unapproved.c", "Modules/_unapproved.o"),
    ("_json", "Modules/_json.c", "Modules/unapproved_json_alias.o"),
    ("_json", "Modules/unapproved_json_alias.c", "Modules/_json.o"),
    ("_sha2", "Modules/sha2module.c", "Modules/sha2module.o"),
])
def test_runtime_gate_does_not_grant_arbitrary_native_sources_or_object_aliases(review_v2_case, module, source, obj):
    with pytest.raises(v1.ConfigurationReviewError):
        case, closure = _runtime_case(review_v2_case, module=module, source=source, obj=obj)
        concrete.prepare_cpython_build_recipe(case[0], **_arguments(case), runtime_closure=closure)


@pytest.mark.parametrize("mutation", [
    "target-name", "config-table", "frozen-table", "freezer-link", "target-link", "native-role",
])
def test_re_signed_runtime_additions_require_the_fixed_tables_and_both_links(runtime_review_v2_case, mutation):
    case, _ = runtime_review_v2_case
    stages, roles, facts = copy.deepcopy(case[4]), case[5].copy(), copy.deepcopy(case[3])
    for stage in stages:
        for command in stage["commands"]:
            argv = command["argv"]
            if mutation == "target-name" and stage["stage"] == "link" and argv[:2] == ["@toolchain/zig", "cc"]:
                argv[6] = "@work/bin/lunar-marker-fixture"
            elif mutation in {"config-table", "frozen-table"} and "-c" in argv:
                source = "runtime/Modules/config.c" if mutation == "config-table" else "runtime/Python/frozen.c"
                if "@source/" + source in argv:
                    old = "@source/" + source
                    new = "@source/" + source.replace("runtime/", "generated-sources/")
                    argv[argv.index(old)] = new
                    roles[new] = roles[old]
            elif (mutation == "freezer-link" and stage["stage"] == "freeze"
                    and argv[:2] == ["@toolchain/zig", "cc"] and "-c" not in argv) or mutation == "target-link" and argv[:2] == ["@toolchain/zig", "ar"]:
                argv.remove("@work/objects/Modules/_json.o")
            elif mutation == "native-role" and "-c" in argv and "@source/Modules/_json.c" in argv:
                argv.remove("-DPy_BUILD_CORE_BUILTIN")
                roles["@source/Modules/_json.c"] = "core"
    facts["recipe_semantics"] = v1._semantics(stages, roles)
    facts["concrete_stages_sha256"] = sha(canonical(stages))
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(case, facts=facts, stages=stages, roles=roles)


def test_shinka_sqlite_additions_require_and_accept_the_complete_finite_group(runtime_review_v2_case):
    case, _ = runtime_review_v2_case
    shinka = _shinka_runtime_case(case)
    binding = _bind(shinka)
    additions = shinka[3]["adaptations"]["runtime_native_additions"]
    assert sum(row["module"] == "_sqlite3" for row in additions) == 9
    assert sum(row["module"] == "sqlite-library" for row in additions) == 1
    assert binding.concrete_stages_sha256 == sha(canonical(shinka[4]))


@pytest.mark.parametrize("mutation", ["missing-sqlite-unit", "missing-sqlite-library", "openevolve-target"])
def test_re_signed_sqlite_groups_cannot_omit_units_or_use_another_solver(runtime_review_v2_case, mutation):
    case, _ = runtime_review_v2_case
    shinka = _shinka_runtime_case(case)
    stages, roles, facts = shinka[4], shinka[5], shinka[3]
    missing = "@source/Modules/_sqlite/blob.c" if mutation == "missing-sqlite-unit" else "@source/sqlite/sqlite3.c"
    obj = "@work/objects/" + missing.removeprefix("@source/")[:-2] + ".o"
    for stage in stages:
        for command in list(stage["commands"]):
            argv = command["argv"]
            if mutation == "openevolve-target":
                if stage["stage"] == "link" and argv[:2] == ["@toolchain/zig", "cc"]:
                    argv[6] = "@work/bin/lunar-openevolve"
                    command["outputs"][0]["path"] = "bin/lunar-openevolve"
            elif "-c" in argv and missing in argv:
                stage["commands"].remove(command)
            elif obj in argv:
                argv.remove(obj)
    if mutation != "openevolve-target":
        facts["adaptations"]["runtime_native_additions"] = [
            row for row in facts["adaptations"]["runtime_native_additions"] if row["source"] != missing
        ]
    facts["recipe_semantics"] = v1._semantics(stages, roles)
    facts["concrete_stages_sha256"] = sha(canonical(stages))
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(shinka, facts=facts, stages=stages, roles=roles)


@pytest.mark.parametrize("missing", ["Modules/config.o", "Python/ceval.o"])
def test_runtime_additions_cannot_exempt_a_missing_original_make_baseline(runtime_review_v2_case, missing):
    case, closure = runtime_review_v2_case
    library = case[3]["make_variables"]["LIBRARY_OBJS"]["tokens"]
    assert missing in library
    raw = _make_value(dict(case[2])["Makefile"], "LIBRARY_OBJS", " ".join(t for t in library if t != missing))
    outputs = _changed_outputs(case, "Makefile", raw)
    facts = copy.deepcopy(case[3])
    facts["make_variables"] = v2._make(raw)
    facts["outputs"] = [{"path": name, "size": len(value), "sha256": sha(value)} for name, value in outputs]
    # Re-sign the external fixture, retaining the valid runtime additions. A
    # separately pinned review cannot redefine a missing original core object.
    with pytest.raises(v1.ConfigurationReviewError):
        concrete.prepare_cpython_build_recipe(
            case[0], **_arguments(case, outputs=outputs, facts=facts), runtime_closure=closure,
        )


def test_v4_recipe_uses_the_same_explicit_v2_review_gate(review_v2_case):
    build = concrete.prepare_cpython_build_recipe_v4(review_v2_case[0], **_arguments(review_v2_case))
    wire = _recipe(build.recipe_bytes, build.sha256, version4=True)
    assert dict(build.sources)["configuration/review.json"] == canonical(review_v2_case[3])
    assert any(row["path"] == "configuration/original/config.status" for row in wire["inputs"]["source"])


def test_v2_real_shapes_do_not_change_the_original_v1_refusals(review_v2_case):
    originals = dict(review_v2_case[2])
    with pytest.raises(v1.ConfigurationReviewError, match="header_condition"):
        v1._header(originals["pyconfig.h"])
    with pytest.raises(v1.ConfigurationReviewError, match="make_assignment"):
        v1._make(originals["Makefile"])
    with pytest.raises(v1.ConfigurationReviewError, match="setup_row"):
        v1._setup(originals["Modules/Setup.stdlib"])


def test_v1_dispatch_and_unselected_recipe_keep_exact_original_bytes(review_case):  # noqa: F811
    kwargs = v1_arguments(review_case)
    binding = v2.bind_selected_cpython_configuration(
        configuration_outputs=kwargs["configuration_outputs"], review_manifest_bytes=kwargs["review_manifest_bytes"],
        expected_review_manifest_sha256=kwargs["expected_review_manifest_sha256"],
        source_inventory_sha256=kwargs["expected_source_inventory_sha256"],
        zig_manifest_sha256=sha(kwargs["zig_manifest_bytes"]), configuration_header=kwargs["configuration_header"],
        stages=review_case[4], compile_roles=review_case[5],
    )
    assert binding == v1_bind(review_case)
    assert concrete.prepare_cpython_build_recipe(review_case[0], **review_case[1]) == review_case[6]


def test_original_guard_comment_is_inventory_data_not_discarded(review_v2_case):
    directives = review_v2_case[3]["header_directives"]
    assert directives[0] == "#ifndef Py_PYCONFIG_H"
    assert directives[-1] == "#endif /*Py_PYCONFIG_H*/"


@pytest.mark.parametrize("suffix", [b"#endif /*OTHER_GUARD*/\n", b"#endif extra\n",
                                     b"#else\n#endif /*Py_PYCONFIG_H*/\n"])
def test_comment_compatibility_does_not_allow_unknown_guard_closures(review_v2_case, suffix):
    header = review_v2_case[1]["configuration_header"].replace(b"#endif /*Py_PYCONFIG_H*/\n", suffix)
    with pytest.raises(v1.ConfigurationReviewError):
        v2._header(header)


@pytest.mark.parametrize("mutation", ["nested-critical", "duplicate-critical", "guard-reopened"])
def test_critical_feature_ambiguity_stays_refused(review_v2_case, mutation):
    header = review_v2_case[1]["configuration_header"]
    if mutation == "nested-critical":
        header = header.replace(b"#define WITH_PYMALLOC 1", b"#if UNKNOWN\n#define WITH_PYMALLOC 1\n#endif")
    elif mutation == "duplicate-critical":
        header = header.replace(b"#define WITH_PYMALLOC 1", b"#define WITH_PYMALLOC 1\n#define WITH_PYMALLOC 1")
    else:
        header += b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n#endif\n"
    with pytest.raises(v1.ConfigurationReviewError):
        v2._header(header)


def test_exact_make_absence_is_distinct_from_an_empty_assignment(review_v2_case):
    original = dict(review_v2_case[2])["Makefile"]
    assert set(review_v2_case[3]["make_absences"]) == {"PERF_TRAMPOLINE_OBJ", "PLATFORM_OBJS"}
    assert not {"PERF_TRAMPOLINE_OBJ", "PLATFORM_OBJS"}.intersection(review_v2_case[3]["make_variables"])
    explicit = original + b"PLATFORM_OBJS =\n"
    assert "PLATFORM_OBJS" not in v2._make_absences(explicit)
    assert v2._make(explicit)["PLATFORM_OBJS"]["tokens"] == []


def test_original_unassigned_make_leaves_are_finite_absence_facts(review_v2_case):
    facts = review_v2_case[3]
    expected = [{"name": name, "referenced_by": [parent],
                 "semantics": "unassigned-user-override-not-consumed-by-direct-recipe"}
                for name, parent in _REAL_OVERRIDE_PARENTS.items()]
    expected.extend({"name": name, "referenced_by": ["LOCALMODLIBS"],
                     "semantics": "fixed-bootstrap-no-extra-link-flags"}
                    for name in _REAL_BOOTSTRAP_LINK_REFERENCES)
    assert facts["make_absent_references"] == sorted(expected, key=lambda row: row["name"])
    assert not set(_REAL_OVERRIDE_PARENTS).intersection(facts["make_variables"])
    assert not set(_REAL_BOOTSTRAP_LINK_REFERENCES).intersection(facts["make_variables"])
    assert set(facts["make_absences"]) == {"PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ"}
    _bind(review_v2_case)


@pytest.mark.parametrize("parent", ["PY_CFLAGS", "LOCALMODLIBS"])
def test_fixed_missing_leaf_parent_whitespace_is_preserved_without_changing_edges(review_v2_case, parent):
    expression = review_v2_case[3]["make_variables"][parent]["expression"].replace(" ", "  \t ")
    raw = _make_value(dict(review_v2_case[2])["Makefile"], parent, expression)
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    assert facts["make_variables"][parent]["expression"] == expression
    assert facts["make_absent_references"] == review_v2_case[3]["make_absent_references"]
    _bind(review_v2_case, outputs=outputs, facts=facts)


@pytest.mark.parametrize("name", [*_REAL_OVERRIDE_PARENTS, *_REAL_BOOTSTRAP_LINK_REFERENCES])
def test_present_empty_make_leaves_are_assignments_instead_of_absence_facts(review_v2_case, name):
    raw = dict(review_v2_case[2])["Makefile"] + (name + " =\n").encode()
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    assert facts["make_variables"][name] == {"expression": "", "expanded": "", "tokens": []}
    assert name not in {row["name"] for row in facts["make_absent_references"]}
    _bind(review_v2_case, outputs=outputs, facts=facts)


@pytest.mark.parametrize("name,value", [
    ("CFLAGS", "-DUNREVIEWED_FEATURE=1"), ("CPPFLAGS", "-DUNREVIEWED_FEATURE=1"),
    ("LDFLAGS", "-lunapproved"), ("MODULE_ATEXIT_LDFLAGS", "-lunapproved"),
])
def test_present_nonempty_make_leaves_are_validated_against_the_actual_recipe(review_v2_case, name, value):
    raw = dict(review_v2_case[2])["Makefile"] + (name + " = " + value + "\n").encode()
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    assert facts["make_variables"][name]["tokens"] == [value]
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, outputs=outputs, facts=facts)


@pytest.mark.parametrize("mutation", [
    "short-user-parent", "user-alias", "wrong-user-parent", "immediate-parent", "unknown-leaf",
    "bootstrap-reordered", "bootstrap-subset", "bootstrap-alias", "unknown-bootstrap-leaf",
])
def test_unassigned_leaf_policy_cannot_expand_to_other_make_edges(review_v2_case, mutation):
    raw = dict(review_v2_case[2])["Makefile"]
    local = " ".join("$(" + name + ")" for name in _REAL_BOOTSTRAP_LINK_REFERENCES)
    if mutation == "short-user-parent":
        raw = _make_value(raw, "PY_CFLAGS", "$(CFLAGS)")
    elif mutation == "user-alias":
        raw = _make_value(raw, "PY_CFLAGS", _REAL_OVERRIDE_EXPRESSIONS["PY_CFLAGS"].replace("$(CFLAGS)", "$(ALIAS)"))
        raw += b"ALIAS = $(CFLAGS)\n"
    elif mutation == "wrong-user-parent":
        raw = _make_value(raw, "PY_CPPFLAGS", _REAL_OVERRIDE_EXPRESSIONS["PY_CPPFLAGS"] + " $(CFLAGS)")
    elif mutation == "immediate-parent":
        raw = raw.replace(b"PY_CFLAGS = ", b"PY_CFLAGS := ")
    elif mutation == "unknown-leaf":
        raw = _make_value(raw, "PY_CFLAGS", "$(UNASSIGNED_FLAG)")
    elif mutation == "bootstrap-reordered":
        raw = _make_value(raw, "LOCALMODLIBS", " ".join(reversed(local.split())))
    elif mutation == "bootstrap-subset":
        raw = _make_value(raw, "LOCALMODLIBS", " ".join(local.split()[:-1]))
    elif mutation == "bootstrap-alias":
        raw = _make_value(raw, "LOCALMODLIBS", "$(ALIASED_BOOTSTRAP)")
        raw += ("ALIASED_BOOTSTRAP = " + local + "\n").encode()
    else:
        raw = _make_value(raw, "LOCALMODLIBS", local + " $(MODULE_UNKNOWN_LDFLAGS)")
    with pytest.raises(v1.ConfigurationReviewError):
        v2._make(raw)


@pytest.mark.parametrize("mutation", ["omitted", "invented", "wrong-parent", "wrong-reason", "fake-assignment"])
def test_re_signed_absent_reference_inventory_cannot_change_original_make_facts(review_v2_case, mutation):
    facts = copy.deepcopy(review_v2_case[3])
    if mutation == "omitted":
        facts["make_absent_references"].pop()
    elif mutation == "invented":
        facts["make_absent_references"].append({"name": "UNKNOWN", "referenced_by": ["PY_CFLAGS"],
                                                "semantics": "unassigned-user-override-not-consumed-by-direct-recipe"})
    elif mutation == "wrong-parent":
        facts["make_absent_references"][0]["referenced_by"] = ["PY_CPPFLAGS"]
    elif mutation == "wrong-reason":
        facts["make_absent_references"][0]["semantics"] = "generic-missing-default"
    else:
        facts["make_variables"]["CFLAGS"] = {"expression": "", "expanded": "", "tokens": []}
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, facts=facts)


def test_v2_adds_real_objects_and_python_include_edges_without_changing_unselected_bytes(review_v2_case):
    prep, arguments, _, _, stages, _, legacy = review_v2_case
    assert concrete.prepare_cpython_build_recipe(prep, **arguments) == legacy
    assert _v2_stages(json.loads(legacy.recipe_bytes)["stages"]) == stages
    selected = concrete.prepare_cpython_build_recipe(prep, **_arguments(review_v2_case))
    for stage in json.loads(selected.recipe_bytes)["stages"]:
        for command in stage["commands"]:
            argv = command["argv"]
            if "-c" in argv:
                offset = argv.index("@source-dir/Include/internal/mimalloc") + 1
                assert argv[offset:offset + 4] == ["-I", "@source-dir/Objects", "-I", "@source-dir/Python"]


def test_real_include_flags_cannot_be_normalized_away_from_the_actual_graph(review_v2_case):
    stages = json.loads(review_v2_case[6].recipe_bytes)["stages"]
    facts = copy.deepcopy(review_v2_case[3])
    facts["recipe_semantics"] = v1._semantics(stages, review_v2_case[5])
    facts["concrete_stages_sha256"] = sha(canonical(stages))
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, facts=facts, stages=stages)


@pytest.mark.parametrize("key", ["make_absences", "make_absent_references", "stdlib_discovery_rows", "adaptations"])
def test_new_v2_sections_are_required_and_cannot_be_omitted(review_v2_case, key):
    facts = copy.deepcopy(review_v2_case[3])
    del facts[key]
    with pytest.raises(v1.ConfigurationReviewError, match="manifest_schema"):
        _bind(review_v2_case, facts=facts)


@pytest.mark.parametrize("name", ["LIBOBJS", "MACHDEP_OBJS", "DTRACE_OBJS", "LIBRARY_OBJS"])
def test_missing_other_object_variables_are_not_filled_with_defaults(review_v2_case, name):
    original = dict(review_v2_case[2])["Makefile"]
    raw = b"\n".join(line for line in original.splitlines() if not line.startswith((name + " =").encode())) + b"\n"
    with pytest.raises(v1.ConfigurationReviewError):
        v2._make(raw)


@pytest.mark.parametrize("name", ["PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ"])
def test_an_absent_variable_referenced_by_library_objects_refuses(review_v2_case, name):
    original = dict(review_v2_case[2])["Makefile"]
    raw = original.replace(b"LIBRARY_OBJS = ", ("LIBRARY_OBJS = $(" + name + ") ").encode())
    with pytest.raises(v1.ConfigurationReviewError):
        v2._make(raw)


def test_disabled_shared_discovery_never_adds_compiled_modules(review_v2_case):
    _bind(review_v2_case)
    semantics = review_v2_case[3]["recipe_semantics"]
    sources = {unit["source"] for role in semantics["roles"].values() for unit in role["units"]}
    assert "@source/Modules/md5module.c" not in sources
    assert "@source/Modules/socketmodule.c" not in sources
    assert "Modules/Setup.stdlib" not in review_v2_case[3]["setup_rows"]
    assert review_v2_case[3]["stdlib_discovery_rows"]


@pytest.mark.parametrize("row", [b"atexit atexitmodule.c", b"unknown_plugin plugin.c"])
def test_shared_discovery_outside_the_fixed_disabled_policy_refuses(review_v2_case, row):
    with pytest.raises(v1.ConfigurationReviewError):
        v2._stdlib_discovery(b"*shared*\n" + row + b"\n")


@pytest.mark.parametrize("text", [b"*shared*\n_md5 $(shell touch forbidden)\n",
                                   b"*shared*\n_md5 md5module.c ; touch forbidden\n",
                                   b"*shared*\n_md5 ../outside.c\n"])
def test_disabled_discovery_cannot_smuggle_shell_or_path_expressions(review_v2_case, text):
    with pytest.raises(v1.ConfigurationReviewError):
        v2._stdlib_discovery(text)


def test_exact_stock_link_and_warning_adaptations_are_separately_review_bound(review_v2_case):
    original = dict(review_v2_case[2])["Makefile"]
    raw = _make_value(original, "PY_CFLAGS", "-Wunreachable-code")
    raw = _make_value(raw, "LIBS", "-ldl -lpthread")
    raw = _make_value(raw, "LINKFORSHARED", "-Xlinker -export-dynamic")
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    # This detached synthetic review uses the fixed profile's digest as an
    # input binding. It contains no real toolchain bytes or acquired authority.
    facts["zig_manifest_sha256"] = v2._ZIG_MANIFEST_SHA256
    binding = _bind(review_v2_case, outputs=outputs, facts=facts, zig_pin=v2._ZIG_MANIFEST_SHA256)
    assert binding.manifest_sha256 == sha(canonical(facts))
    adaptations = facts["adaptations"]
    assert adaptations["warning_only_flags"] == ["-Wunreachable-code"]
    assert adaptations["unconsumed_linkforshared"]["tokens"] == ["-Xlinker", "-export-dynamic"]
    assert adaptations["musl_libdl"]["actual_cc_token"] == "-lc"
    assert adaptations["musl_libdl"]["dynamic_loading_supported"] is False
    assert adaptations["musl_libdl"]["independent_explicit_libc_support_pin_required"] is True
    for key, value in (("dynamic_loading_supported", 0), ("independent_explicit_libc_support_pin_required", 1)):
        changed = copy.deepcopy(facts)
        changed["adaptations"]["musl_libdl"][key] = value
        with pytest.raises(v1.ConfigurationReviewError):
            _bind(review_v2_case, outputs=outputs, facts=changed, zig_pin=v2._ZIG_MANIFEST_SHA256)
    changed = copy.deepcopy(facts)
    changed["zig_manifest_sha256"] = sha(b"unapproved other toolchain")
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, outputs=outputs, facts=changed, zig_pin=changed["zig_manifest_sha256"])


@pytest.mark.parametrize("name,value", [
    ("PY_CFLAGS", "-Werror=unreachable-code"), ("PY_CFLAGS", "-Wunreviewed-warning"),
    ("LIBS", "-ldl2"), ("SYSLIBS", "-ldl"), ("LIBS", "-ldl -ldl"),
    ("LINKFORSHARED", "-Wl,--export-dynamic"), ("LINKFORSHARED", "-Xlinker -export-dynamic -shared"),
])
def test_nearby_unapproved_semantic_adaptations_stay_refused(review_v2_case, name, value):
    raw = _make_value(dict(review_v2_case[2])["Makefile"], name, value)
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    with pytest.raises(v1.ConfigurationReviewError):
        facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
        _bind(review_v2_case, outputs=outputs, facts=facts)


def test_stock_object_names_bind_only_the_existing_role_specific_replacements(review_v2_case):
    outputs = _stock_outputs(review_v2_case)
    facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
    binding = _bind(review_v2_case, outputs=outputs, facts=facts)
    replacements = {row["make_object"]: row for row in facts["adaptations"]["library_object_replacements"]}
    assert set(replacements) == {"Modules/getpath.o", "Python/frozen.o"}
    assert replacements["Modules/getpath.o"]["freezer"]["source"] == "@source/Modules/getpath_noop.c"
    assert replacements["Modules/getpath.o"]["target"]["object"].endswith("/installation-owned-strict-getpath.o")
    assert replacements["Python/frozen.o"]["freezer"]["source"] == "@source/Programs/_freeze_module.c"
    assert replacements["Python/frozen.o"]["target"]["object"].endswith("/installation-owned-finite-frozen.o")
    assert binding.concrete_stages_sha256 == sha(canonical(review_v2_case[4]))


@pytest.mark.parametrize("object_name", ["Modules/getpath_noop.o", "installation-owned-strict-getpath.o",
                                         "Programs/_freeze_module.o", "installation-owned-finite-frozen.o"])
@pytest.mark.parametrize("mutation", ["missing", "wrong-source", "not-linked"])
def test_resigned_stock_replacements_require_original_source_and_link_reachability(
    review_v2_case, object_name, mutation,
):
    outputs = _stock_outputs(review_v2_case)
    stages, roles = copy.deepcopy(review_v2_case[4]), review_v2_case[5].copy()
    target = "@work/objects/" + object_name
    stage_name = "freeze" if object_name in {"Modules/getpath_noop.o", "Programs/_freeze_module.o"} else "link"
    for stage in stages:
        for command in list(stage["commands"]):
            argv = command["argv"]
            if "-c" in argv and argv[argv.index("-o") + 1] == target:
                if mutation == "missing":
                    stage["commands"].remove(command)
                elif mutation == "wrong-source":
                    old_source = argv[argv.index("-c") + 1]
                    new_source = "@source/Modules/unapproved_replacement.c"
                    argv[argv.index("-c") + 1] = new_source
                    roles[new_source] = roles[old_source]
            if (mutation == "not-linked" and stage["stage"] == stage_name
                    and argv[:2] == ["@toolchain/zig", "cc"] and "-c" not in argv):
                argv.remove(target)
    with pytest.raises(v1.ConfigurationReviewError):
        # Re-author all stage-derived fixture fields and the external graph pin;
        # a valid signature still cannot grant arbitrary replacement semantics.
        facts = _facts(review_v2_case[1], outputs, stages, roles)
        _bind(review_v2_case, outputs=outputs, facts=facts, stages=stages, roles=roles)


def test_compiling_a_forbidden_stock_object_is_never_a_replacement_policy(review_v2_case):
    outputs = _stock_outputs(review_v2_case)
    stages = copy.deepcopy(review_v2_case[4])
    for stage in stages:
        for command in stage["commands"]:
            argv = command["argv"]
            if "-c" in argv and "@source/Modules/getpath_noop.c" in argv:
                argv[argv.index("-o") + 1] = "@work/objects/Modules/getpath.o"
    with pytest.raises(v1.ConfigurationReviewError):
        facts = _facts(review_v2_case[1], outputs, stages, review_v2_case[5])
        _bind(review_v2_case, outputs=outputs, facts=facts, stages=stages)


@pytest.mark.parametrize("index", range(8))
def test_all_original_outputs_remain_required_and_independently_pinned(review_v2_case, index):
    outputs = review_v2_case[2]
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, outputs=outputs[:index] + outputs[index + 1:])
    changed = list(outputs)
    name, raw = changed[index]
    changed[index] = (name, raw + b"changed\n")
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, outputs=tuple(changed))


@pytest.mark.parametrize("key", ["source_inventory_sha256", "zig_manifest_sha256", "concrete_stages_sha256"])
def test_resigned_source_toolchain_and_graph_changes_still_refuse(review_v2_case, key):
    facts = copy.deepcopy(review_v2_case[3])
    facts[key] = "0" * 64
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, facts=facts)


def test_external_pin_cannot_be_replaced_by_a_draft_digest(review_v2_case):
    arguments = _arguments(review_v2_case)
    arguments["expected_review_manifest_sha256"] = sha(b"different independent fixture review")
    with pytest.raises(v1.ConfigurationReviewError, match="manifest_pin"):
        concrete.prepare_cpython_build_recipe(review_v2_case[0], **arguments)


def test_an_actual_stage_change_is_not_covered_by_original_v2_review(review_v2_case):
    stages = copy.deepcopy(review_v2_case[4])
    stages[0]["commands"][0]["argv"].insert(6, "-DUNREVIEWED_FEATURE=1")
    with pytest.raises(v1.ConfigurationReviewError):
        _bind(review_v2_case, stages=stages)


@pytest.mark.parametrize("name", ["LIBRARY_OBJS", "PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ"])
def test_present_or_library_objects_must_still_be_compiled_and_linked(review_v2_case, name):
    original = dict(review_v2_case[2])["Makefile"]
    if name == "LIBRARY_OBJS":
        raw = original.replace(b"LIBRARY_OBJS = ", b"LIBRARY_OBJS = uncompiled.o ")
    else:
        raw = original + (name + " = uncompiled.o\n").encode()
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    with pytest.raises(v1.ConfigurationReviewError):
        facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
        _bind(review_v2_case, outputs=outputs, facts=facts)


@pytest.mark.parametrize("line", [b"LIBS = -lunapproved", b"MODSHARED_NAMES = _ssl", b"MODDISABLED_NAMES =",
                                   b"LINKFORSHARED = -shared", b"PY_CFLAGS = -DUNIMPLEMENTED=1"])
def test_re_signed_unsupported_semantics_do_not_become_accepted(review_v2_case, line):
    original = dict(review_v2_case[2])["Makefile"]
    name = line.split(b"=", 1)[0].strip()
    raw = b"\n".join(line if row.split(b"=", 1)[0].strip() == name else row
                      for row in original.splitlines()) + b"\n"
    outputs = _changed_outputs(review_v2_case, "Makefile", raw)
    with pytest.raises(v1.ConfigurationReviewError):
        facts = _facts(review_v2_case[1], outputs, review_v2_case[4], review_v2_case[5])
        _bind(review_v2_case, outputs=outputs, facts=facts)


def test_unknown_review_schema_has_no_v1_or_v2_fallback(review_v2_case):
    facts = copy.deepcopy(review_v2_case[3])
    facts["schema"] = "lunar-unknown-review"
    with pytest.raises(v1.ConfigurationReviewError):
        concrete.prepare_cpython_build_recipe(review_v2_case[0], **_arguments(review_v2_case, facts=facts))


@pytest.mark.parametrize("operand", [
    pytest.param(b"<stddef.h>", id="angle-basename"),
    pytest.param(b'"relative.h"', id="quoted-basename"),
    pytest.param(b"<sys/types.h>", id="angle-relative"),
    pytest.param(b'"internal/pycore_runtime.h"', id="quoted-relative"),
    pytest.param(b"<config>", id="no-header-suffix"),
    pytest.param(b'"vendor-1/build+config.inc"', id="finite-punctuation"),
    pytest.param(b'"v1.2/settings"', id="dotted-directory"),
    pytest.param(b'".private/header"', id="non-dot-hidden-segment"),
    pytest.param(b"<0compat>", id="numeric-prefix"),
])
def test_v2_literal_include_preserves_the_complete_supported_operand(review_v2_case, operand):
    original = review_v2_case[1]["configuration_header"]
    line = b" \t# \tinclude\t" + operand + b" \t\n"
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n", line + b"#endif /*Py_PYCONFIG_H*/\n")
    directives = v2._header(header)
    previous = review_v2_case[3]["header_directives"]
    assert directives == [*previous[:-1], "#include " + operand.decode("ascii"), previous[-1]]


@pytest.mark.parametrize("operand", [
    pytest.param(b"", id="missing-operand"),
    pytest.param(b"<>", id="empty-angle"),
    pytest.param(b'""', id="empty-quoted"),
    pytest.param(b"HEADER_FILE", id="macro-name"),
    pytest.param(b"HEADER(header.h)", id="macro-call"),
    pytest.param(b"header.h", id="bare-name"),
    pytest.param(b"<header.h", id="missing-angle-close"),
    pytest.param(b'"header.h', id="missing-quote-close"),
    pytest.param(b'<header.h"', id="mixed-delimiters"),
    pytest.param(b"</absolute.h>", id="absolute-angle"),
    pytest.param(b'"/absolute.h"', id="absolute-quoted"),
    pytest.param(b'"C:/absolute.h"', id="drive-path"),
    pytest.param(b"<../outside.h>", id="parent-prefix"),
    pytest.param(b'"internal/../outside.h"', id="parent-middle"),
    pytest.param(b'"internal/.."', id="parent-final"),
    pytest.param(b"<./header.h>", id="dot-prefix"),
    pytest.param(b'"internal/./header.h"', id="dot-middle"),
    pytest.param(b'"internal/."', id="dot-final"),
    pytest.param(b"<internal//header.h>", id="empty-middle"),
    pytest.param(b'"internal/"', id="empty-final"),
    pytest.param(b'"internal\\header.h"', id="backslash"),
    pytest.param(b'"internal/header name.h"', id="inner-space"),
    pytest.param(b'"internal/header\tname.h"', id="inner-tab"),
    pytest.param(b'"header\x07.h"', id="control"),
    pytest.param(b'"\xc3\xa9.h"', id="non-ascii"),
    pytest.param(b'"header$NAME.h"', id="substitution-token"),
    pytest.param(b'"header:variant.h"', id="unsupported-punctuation"),
    pytest.param(b"<header.h> EXTRA", id="angle-trailing-expression"),
    pytest.param(b'"header.h" EXTRA', id="quote-trailing-expression"),
    pytest.param(b'"first.h" "second.h"', id="adjacent-strings"),
    pytest.param(b"<first.h><second.h>", id="adjacent-angle-operands"),
    pytest.param(b"<header.h> /* unsupported comment */", id="trailing-block-comment"),
    pytest.param(b'"header.h" // unsupported comment', id="trailing-line-comment"),
    pytest.param(b'/* unsupported prefix */ "header.h"', id="prefix-comment"),
])
def test_v2_literal_include_refuses_nonliteral_or_noncanonical_operands(review_v2_case, operand):
    original = review_v2_case[1]["configuration_header"]
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n",
                              b"#include " + operand + b"\n#endif /*Py_PYCONFIG_H*/\n")
    with pytest.raises(v1.ConfigurationReviewError, match="header_include$"):
        v2._header(header)


def test_v2_literal_include_does_not_evaluate_an_inactive_condition(review_v2_case):
    original = review_v2_case[1]["configuration_header"]
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n",
                              b"#if 0\n#include HEADER_MACRO\n#endif\n#endif /*Py_PYCONFIG_H*/\n")
    with pytest.raises(v1.ConfigurationReviewError, match="header_include$"):
        v2._header(header)


@pytest.mark.parametrize("operand", [
    pytest.param(b"<header.h>\vEXTRA", id="vertical-tab-tail"),
    pytest.param(b"<header.h>\fEXTRA", id="form-feed-tail"),
    pytest.param(b"<header.h>\x1cEXTRA", id="file-separator-tail"),
    pytest.param(b"<header.h>\x1dEXTRA", id="group-separator-tail"),
    pytest.param(b"<header.h>\x1eEXTRA", id="record-separator-tail"),
    pytest.param(b"<header.h>\x1f", id="unit-separator-trim"),
    pytest.param(b"\v<header.h>", id="vertical-tab-leading"),
    pytest.param(b"\f<header.h>", id="form-feed-leading"),
    pytest.param(b"<header.h>\xc2\x85EXTRA", id="unicode-next-line-tail"),
    pytest.param(b"<header.h>\xe2\x80\xa8EXTRA", id="unicode-line-separator-tail"),
    pytest.param(b"<header.h>\xe2\x80\xa9EXTRA", id="unicode-paragraph-separator-tail"),
    pytest.param(b"\xc2\xa0<header.h>", id="nonbreaking-space-leading"),
    pytest.param(b"<header.h>\xc2\xa0", id="nonbreaking-space-trailing"),
    pytest.param(b"\xe3\x80\x80<header.h>", id="ideographic-space-leading"),
    pytest.param(b"<header.h>\xe3\x80\x80", id="ideographic-space-trailing"),
])
def test_v2_literal_include_preserves_non_lf_lexical_boundaries(review_v2_case, operand):
    original = review_v2_case[1]["configuration_header"]
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n",
                              b"#include " + operand + b"\n#endif /*Py_PYCONFIG_H*/\n")
    with pytest.raises(v1.ConfigurationReviewError, match="header_include$"):
        v2._header(header)


@pytest.mark.parametrize("operand", [b"HEADER_MACRO", b'"../outside.h"', b"<header.h> EXTRA"],
                         ids=["macro", "parent-path", "trailing-expression"])
def test_v2_literal_include_gate_cannot_be_replaced_by_re_signed_facts(review_v2_case, operand):
    original = review_v2_case[1]["configuration_header"]
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n",
                              b"#include " + operand + b"\n#endif /*Py_PYCONFIG_H*/\n")
    arguments = {**review_v2_case[1], "configuration_header": header, "expected_configuration_sha256": sha(header)}
    outputs = _changed_outputs(review_v2_case, "pyconfig.h", header)
    facts = copy.deepcopy(review_v2_case[3])
    facts["outputs"] = [{"path": name, "size": len(raw), "sha256": sha(raw)} for name, raw in outputs]
    facts["header_directives"].insert(-1, "#include " + operand.decode("ascii"))
    case = (review_v2_case[0], arguments, outputs, facts, *review_v2_case[4:])
    with pytest.raises(v1.ConfigurationReviewError, match="header_include$"):
        _bind(case)


def test_v2_literal_include_binding_keeps_original_bytes_and_exact_review_wire(review_v2_case):
    original = review_v2_case[1]["configuration_header"]
    header = original.replace(b"#endif /*Py_PYCONFIG_H*/\n",
                              b'#include "internal/config.inc"\n#endif /*Py_PYCONFIG_H*/\n')
    arguments = {**review_v2_case[1], "configuration_header": header, "expected_configuration_sha256": sha(header)}
    outputs = _changed_outputs(review_v2_case, "pyconfig.h", header)
    facts = copy.deepcopy(review_v2_case[3])
    facts["outputs"] = [{"path": name, "size": len(raw), "sha256": sha(raw)} for name, raw in outputs]
    facts["header_directives"].insert(-1, '#include "internal/config.inc"')
    case = (review_v2_case[0], arguments, outputs, facts, *review_v2_case[4:])
    binding = _bind(case)
    assert binding.sources == (*(("configuration/original/" + name, raw) for name, raw in outputs),
                               ("configuration/review.json", canonical(facts)))
    assert binding.manifest_sha256 == sha(canonical(facts))
    assert binding.concrete_stages_sha256 == review_v2_case[3]["concrete_stages_sha256"]


def _lexical_header(case, payload):
    return case[1]["configuration_header"].replace(
        b"#endif /*Py_PYCONFIG_H*/\n", payload + b"#endif /*Py_PYCONFIG_H*/\n",
    )


@pytest.mark.parametrize("payload", [
    pytest.param(b'/* prefix */ #include "../outside.h"\n', id="comment-prefix"),
    pytest.param(b'/* prefix\n*/ #include "../outside.h"\n', id="multiline-comment-prefix"),
    pytest.param(b'/* one */ /* two */ #include "../outside.h"\n', id="two-comment-prefixes"),
    pytest.param(b'/**/#include "../outside.h"\n', id="adjacent-comment-prefix"),
    pytest.param(b'%:include "../outside.h"\n', id="digraph"),
    pytest.param(b'%: include "../outside.h"\n', id="digraph-space"),
    pytest.param(b'#/**/include "../outside.h"\n', id="comment-after-sharp"),
    pytest.param(b'# /* gap */ include "../outside.h"\n', id="spaced-comment-after-sharp"),
    pytest.param(b'/\\\n* prefix */ #include "../outside.h"\n', id="spliced-comment-prefix"),
    pytest.param(b'%\\\n:include "../outside.h"\n', id="spliced-digraph"),
    pytest.param(b'# /\\\n**/ include "../outside.h"\n', id="spliced-comment-after-sharp"),
    pytest.param(b'# 123 "external.h"\n', id="line-marker"),
    pytest.param(b"#\n", id="empty-directive"),
    pytest.param(b'#@include "../outside.h"\n', id="punctuation-operation"),
    pytest.param(b'\xc2\xa0#include "relative.h"\n', id="unicode-prefix-space"),
    pytest.param(b'\v#include "relative.h"\n', id="control-prefix-space"),
])
def test_v2_header_lexical_refuses_noncanonical_directive_introducers(review_v2_case, payload):
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(_lexical_header(review_v2_case, payload))


@pytest.mark.parametrize("payload", [
    pytest.param(b"int injected;\n", id="declaration"),
    pytest.param(b"typedef int injected;\n", id="typedef"),
    pytest.param(b"/\n", id="stray-slash"),
    pytest.param(b"*/\n", id="stray-comment-close"),
    pytest.param(b'"standalone token"\n', id="standalone-string"),
    pytest.param(b"/* missing close\n", id="unterminated-block-comment"),
    pytest.param(b"/* first\n * still open\n", id="unterminated-multiline-comment"),
    pytest.param(b'#define LEXICAL_TEXT "unterminated\n', id="unterminated-string"),
    pytest.param(b"#define LEXICAL_CHAR 'unterminated\n", id="unterminated-character"),
    pytest.param(b'#define LEXICAL_TEXT "dangling\\\n', id="dangling-string-escape"),
    pytest.param(b"#define LEXICAL_VALUE 1 /* missing close\n", id="directive-unclosed-comment"),
    pytest.param(b"// harmless comment\ninjected\n", id="content-after-line-comment"),
])
def test_v2_header_lexical_refuses_free_content_and_unterminated_states(review_v2_case, payload):
    # The outer guard's existing comment terminator must not close these fixtures.
    unclosed_block = payload in {
        b"/* missing close\n", b"/* first\n * still open\n",
        b"#define LEXICAL_VALUE 1 /* missing close\n",
    }
    header = (review_v2_case[1]["configuration_header"] + payload if unclosed_block else
              _lexical_header(review_v2_case, payload))
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(header)


@pytest.mark.parametrize("context", ["comment", "string"])
@pytest.mark.parametrize("trigraph", [
    b"??=", b"??/", b"??'", b"??(", b"??)", b"??!", b"??<", b"??>", b"??-",
], ids=["sharp", "backslash", "caret", "left-bracket", "right-bracket", "bar", "left-brace", "right-brace", "tilde"])
def test_v2_header_lexical_refuses_every_trigraph_even_inside_comments_or_quotes(
    review_v2_case, context, trigraph,
):
    payload = (b"/* text " + trigraph + b" text */\n" if context == "comment" else
               b'#define LEXICAL_TEXT "text ' + trigraph + b' text"\n')
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(_lexical_header(review_v2_case, payload))


@pytest.mark.parametrize("payload,extra", [
    pytest.param(b"/* harmless #include HEADER and %:include text */\n", [], id="comment-markers"),
    pytest.param(b"/* first\n * #include HEADER and %:include text\n */\n", [], id="multiline-comment-markers"),
    pytest.param(b"// harmless #include HEADER %:include /* text\n", [], id="line-comment-markers"),
    pytest.param(b'// continued comment\\\n%:include "../ignored.h"\n', [], id="spliced-line-comment"),
    pytest.param(b'/\\\n* harmless # and %: *\\\n/\n', [], id="spliced-comment-delimiters"),
    pytest.param(b'#define LEXICAL_TEXT "/* not comment */ // # %:"\n',
                 ['#define LEXICAL_TEXT "/* not comment */ // # %:"'], id="quoted-markers"),
    pytest.param(b'#define LEXICAL_TEXT "escaped \\" quote /* // # %:"\n',
                 ['#define LEXICAL_TEXT "escaped \\" quote /* // # %:"'], id="escaped-quote"),
    pytest.param(b"#define LEXICAL_CHAR '/'\n", ["#define LEXICAL_CHAR '/'"], id="character-slash"),
    pytest.param(b"#define LEXICAL_CHAR '\\''\n", ["#define LEXICAL_CHAR '\\''"], id="escaped-character-quote"),
    pytest.param(b"#define LEXICAL_CHAR '\\\\'\n", ["#define LEXICAL_CHAR '\\\\'"], id="escaped-backslash"),
    pytest.param(b'#define LEXICAL_TEXT "first \\\nsecond /* // %: #"\n',
                 ['#define LEXICAL_TEXT "first  second /* // %: #"'], id="spliced-string-inventory"),
    pytest.param(b'#include \\\n\t"internal/config.inc"\n',
                 ['#include "internal/config.inc"'], id="direct-literal-with-spliced-space"),
])
def test_v2_header_lexical_preserves_harmless_text_and_original_inventory(review_v2_case, payload, extra):
    previous = review_v2_case[3]["header_directives"]
    assert v2._header(_lexical_header(review_v2_case, payload)) == [*previous[:-1], *extra, previous[-1]]


def test_v2_header_lexical_classification_does_not_replace_literal_inventory_splicing(review_v2_case):
    header = _lexical_header(review_v2_case, b'#include "inter\\\nnal/config.inc"\n')
    with pytest.raises(v1.ConfigurationReviewError, match="header_include$"):
        v2._header(header)


def test_v2_header_lexical_does_not_evaluate_an_inactive_branch(review_v2_case):
    header = _lexical_header(review_v2_case, b'#if 0\n%:include "../outside.h"\n#endif\n')
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(header)


@pytest.mark.parametrize("payload", [
    pytest.param(b'/* prefix */ #include "../outside.h"\n', id="comment-prefix"),
    pytest.param(b'%:include "../outside.h"\n', id="digraph"),
    pytest.param(b'#/**/include "../outside.h"\n', id="comment-after-sharp"),
    pytest.param(b"int injected;\n", id="free-content"),
    pytest.param(b'#define LEXICAL_TEXT "unterminated\n', id="unterminated-state"),
])
def test_v2_header_lexical_refusal_cannot_be_replaced_by_re_signed_public_facts(review_v2_case, payload):
    header = _lexical_header(review_v2_case, payload)
    arguments = {**review_v2_case[1], "configuration_header": header, "expected_configuration_sha256": sha(header)}
    outputs = _changed_outputs(review_v2_case, "pyconfig.h", header)
    facts = copy.deepcopy(review_v2_case[3])
    facts["outputs"] = [{"path": name, "size": len(raw), "sha256": sha(raw)} for name, raw in outputs]
    # Model the former silent-drop inventory while explicitly pinning every new original byte.
    case = (review_v2_case[0], arguments, outputs, facts, *review_v2_case[4:])
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        _bind(case)


def test_v2_header_lexical_refuses_a_critical_feature_hidden_in_a_block(review_v2_case):
    header = review_v2_case[1]["configuration_header"].replace(
        b"#define WITH_PYMALLOC 1\n", b"/* inactive feature\n#define WITH_PYMALLOC 1\n*/\n",
    )
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(header)


def test_v2_commented_guard_and_features_cannot_be_re_signed_as_public_configuration(review_v2_case):
    claimed = [*review_v2_case[3]["header_directives"][:-1], "#endif"]
    body = ("\n".join(claimed) + "\n").encode("ascii")
    assert b"*/" not in body
    header = b"/* inactive configuration\n" + body + b"*/\n"
    arguments = {**review_v2_case[1], "configuration_header": header, "expected_configuration_sha256": sha(header)}
    outputs = _changed_outputs(review_v2_case, "pyconfig.h", header)
    facts = copy.deepcopy(review_v2_case[3])
    facts["header_directives"] = claimed
    facts["outputs"] = [{"path": name, "size": len(raw), "sha256": sha(raw)} for name, raw in outputs]
    # Every changed byte and the manifest are re-pinned, while the claimed
    # guard/features still come from the original text inventory inside a block.
    case = (review_v2_case[0], arguments, outputs, facts, *review_v2_case[4:])
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        _bind(case)


def test_v2_header_lexical_refuses_a_legacy_disabled_row_inside_an_open_block(review_v2_case):
    # The second line's terminator closes the original block; there is no stray close.
    header = _lexical_header(review_v2_case, b"/* inactive row\n/* #undef LEXICAL_DISABLED */\n")
    with pytest.raises(v1.ConfigurationReviewError, match="header_lexical$"):
        v2._header(header)


def test_v2_header_lexical_uses_the_legacy_splice_view_for_block_conflicts(review_v2_case):
    # Deletion forms one identifier; the inventory's space convention forms two.
    # Only the former matches the disabled-row spelling, so no inventory conflict exists.
    header = _lexical_header(review_v2_case, b"/* inactive row\n/* #undef LEXICAL_\\\nDISABLED */\n")
    assert v2._header(header) == review_v2_case[3]["header_directives"]
