"""Synthetic external-review fixtures; never approval of real CPython files.

The fixture manifest is authored outside configure and supplied through its
separate expected pin. No production manifest-authoring API is provided.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from tests.test_static_python_concrete_recipe import (
    concrete_inputs,  # noqa: F401 - shared pytest fixture
)
from tests.test_static_python_dependency_profile_selection import _GENERATORS, _extras
from tools.static_python_fixture.configure_plan import _ENABLED
from tools.static_python_fixture.profile import CORE_BUILTINS
from tools.static_python_rsi_fixture import concrete_recipe as concrete
from tools.static_python_rsi_fixture import configuration_review as review
from tools.static_python_rsi_fixture.build_driver import _preparation_wire
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.runtime_closure import canonical


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def test_fixed_header_guard_is_only_transparent_condition(review_case):
    header = review_case[2][0][1]
    guarded = b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n" + header + b"#endif\n"
    assert review._header(guarded)[2:-1] == review._header(header)


@pytest.mark.parametrize("prefix,suffix", [
    (b"#ifndef OTHER_GUARD\n#define OTHER_GUARD\n", b"#endif\n"),
    (b"#ifndef Py_PYCONFIG_H\n", b"#endif\n"),
    (b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n#if SOMETHING\n", b"#endif\n#endif\n"),
    (b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n#else\n", b"#endif\n"),
    (b"#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n", b"#endif\n#ifndef Py_PYCONFIG_H\n#define Py_PYCONFIG_H\n#endif\n"),
])
def test_header_guard_does_not_enable_conditional_feature_evaluation(review_case, prefix, suffix):
    with pytest.raises(review.ConfigurationReviewError):
        review._header(prefix + review_case[2][0][1] + suffix)


def _roles(preparation):
    plan = _preparation_wire(preparation)["candidate_build_inputs"]
    result = {"@source/configuration/probe.c": "configuration"}
    for key, role in (("shared_units", "core"), ("freezer_units", "freezer"), ("target_units", "target")):
        for unit in plan[key]:
            result["@source/" + unit["source"]] = "builtin" if unit["compile_role"] == "builtin" else role
    return result


@pytest.fixture
def review_case(concrete_inputs):  # noqa: F811
    prep, arguments = concrete_inputs
    arguments = arguments.copy()
    header = (b"/* synthetic external review fixture, not a real configuration */\n"
              b"#define WITH_PYMALLOC 1\n#define WITH_MIMALLOC 1\n"
              b"#define USE_COMPUTED_GOTOS 1\n#define SIZEOF_VOID_P 8\n"
              b"/* #undef Py_ENABLE_SHARED */\n/* #undef HAVE_DLOPEN */\n/* #undef ENABLE_IPV6 */\n")
    arguments.update(configuration_header=header, expected_configuration_sha256=sha(header))
    # The independent fixture describes a known source-owned graph; this is not
    # a workflow for approving output of a real configure/build invocation.
    legacy = concrete.prepare_cpython_build_recipe(prep, **arguments)
    stages = json.loads(legacy.recipe_bytes)["stages"]
    values = dict.fromkeys(review.REQUIRED_VARIABLES, "")
    values.update(PY_CORE_CFLAGS="-DPy_BUILD_CORE", PY_BUILTIN_MODULE_CFLAGS="-DPy_BUILD_CORE_BUILTIN",
                  DYNLOADFILE="dynload_stub.o", LIBS="-lm", SYSLIBS="-lpthread -lc",
                  MODBUILT_NAMES=" ".join(name for name, _ in _ENABLED),
                  MODOBJS=" ".join("Modules/" + path.removesuffix(".c") + ".o"
                                   for _, paths in _ENABLED for path in paths))
    makefile = "".join(name + " = " + value + "\n" for name, value in sorted(values.items())).encode()
    bootstrap = ("*static*\n" + "".join(name + " " + " ".join(paths) + "\n" for name, paths in _ENABLED)).encode()
    config = ("struct _inittab _PyImport_Inittab[] = {\n"
              + "".join('{"' + name + '", PyInit_' + name + "},\n"
                        for name in sorted(set(CORE_BUILTINS) | {name for name, _ in _ENABLED}))
              + "{0, 0}\n};\n").encode()
    outputs = (("pyconfig.h", header), ("Makefile", makefile), ("Makefile.pre", b"reviewed inert template\n"),
               ("config.log", b"reviewed inert log\n"), ("config.status", b"reviewed inert status\n"),
               ("Modules/Setup.bootstrap", bootstrap), ("Modules/Setup.stdlib", b"# no extra static modules\n"),
               ("Modules/config.c", config))
    roles = _roles(prep)
    facts = {"schema": review.SCHEMA, "profile": review.PROFILE, "target": "x86_64-linux-musl",
             "source_inventory_sha256": arguments["expected_source_inventory_sha256"],
             "zig_manifest_sha256": sha(arguments["zig_manifest_bytes"]),
             "outputs": [{"path": path, "size": len(raw), "sha256": sha(raw)} for path, raw in outputs],
             "header_directives": review._header(header), "make_variables": review._make(makefile),
             "setup_rows": {path: review._setup(raw) for path, raw in outputs if path.startswith("Modules/Setup.")},
             "config_modules": review._config_modules(config), "recipe_semantics": review._semantics(stages, roles),
             "concrete_stages_sha256": sha(canonical(stages))}
    return prep, arguments, outputs, facts, stages, roles, legacy


def _arguments(case, *, outputs=None, facts=None):
    _, arguments, originals, manifest, _, _, _ = case
    raw = canonical(manifest if facts is None else facts)
    return {**arguments, "configuration_outputs": originals if outputs is None else outputs,
            "review_manifest_bytes": raw, "expected_review_manifest_sha256": sha(raw)}


def _bind(case, *, outputs=None, facts=None, stages=None):
    _, arguments, originals, manifest, original_stages, roles, _ = case
    raw = canonical(manifest if facts is None else facts)
    return review.bind_reviewed_cpython_configuration(
        configuration_outputs=originals if outputs is None else outputs, review_manifest_bytes=raw,
        expected_review_manifest_sha256=sha(raw), source_inventory_sha256=arguments["expected_source_inventory_sha256"],
        zig_manifest_sha256=sha(arguments["zig_manifest_bytes"]), configuration_header=arguments["configuration_header"],
        stages=original_stages if stages is None else stages, compile_roles=roles,
    )


def test_original_eight_bytes_and_external_manifest_reach_actual_recipe_inputs(review_case):
    prep, _, outputs, facts, _, _, _ = review_case
    result = concrete.prepare_cpython_build_recipe(prep, **_arguments(review_case))
    wire = _recipe(result.recipe_bytes, result.sha256, version3=True)
    staged, inputs = dict(result.sources), {row["path"]: row for row in wire["inputs"]["source"]}
    for path, raw in (*(("configuration/original/" + name, value) for name, value in outputs),
                      ("configuration/review.json", canonical(facts))):
        assert staged[path] == raw
        assert inputs[path] == {"path": path, "size": len(raw), "sha256": sha(raw), "executable": False}
    manifest = json.loads(result.manifest_bytes)
    assert manifest["reviewed_concrete_stages_sha256"] == sha(canonical(wire["stages"]))
    assert manifest["configuration_review_manifest_sha256"] == sha(canonical(facts))
    assert manifest["configured_closure_verified"] is False
    assert manifest["build_performed"] is False and manifest["production_admission"] is False


def test_omitted_or_none_review_keeps_legacy_bytes(review_case):
    prep, arguments, _, _, _, _, legacy = review_case
    result = concrete.prepare_cpython_build_recipe(
        prep, **arguments, configuration_outputs=None, review_manifest_bytes=None, expected_review_manifest_sha256=None,
    )
    assert result == legacy


@pytest.mark.parametrize("keys", [("configuration_outputs",), ("review_manifest_bytes",),
                                  ("expected_review_manifest_sha256",),
                                  ("configuration_outputs", "review_manifest_bytes"),
                                  ("configuration_outputs", "expected_review_manifest_sha256"),
                                  ("review_manifest_bytes", "expected_review_manifest_sha256")])
def test_partial_review_selection_refuses_at_original_generator(review_case, keys):
    prep, arguments, _, _, _, _, _ = review_case
    selected = _arguments(review_case)
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_review_incomplete"):
        concrete.prepare_cpython_build_recipe(prep, **arguments, **{key: selected[key] for key in keys})


@pytest.mark.parametrize("index", range(8))
def test_every_original_output_required(review_case, index):
    outputs = review_case[2]
    with pytest.raises(review.ConfigurationReviewError, match="output_set"):
        _bind(review_case, outputs=outputs[:index] + outputs[index + 1:])


@pytest.mark.parametrize("index", range(8))
def test_every_original_output_separately_pinned(review_case, index):
    outputs = list(review_case[2])
    path, raw = outputs[index]
    outputs[index] = (path, raw + b"changed\n")
    with pytest.raises(review.ConfigurationReviewError, match="output_pin"):
        _bind(review_case, outputs=tuple(outputs))


@pytest.mark.parametrize("key", sorted(review._KEYS))
def test_every_review_section_required(review_case, key):
    facts = copy.deepcopy(review_case[3])
    del facts[key]
    with pytest.raises(review.ConfigurationReviewError, match="manifest_schema"):
        _bind(review_case, facts=facts)


def test_external_manifest_pin_not_replaced_by_observation(review_case):
    prep, _, _, _, _, _, _ = review_case
    arguments = _arguments(review_case)
    arguments["expected_review_manifest_sha256"] = sha(b"a different independently approved fixture")
    with pytest.raises(review.ConfigurationReviewError, match="manifest_pin"):
        concrete.prepare_cpython_build_recipe(prep, **arguments)


@pytest.mark.parametrize("mutation", ["duplicate", "reordered", "bool_size", "header_mismatch", "stage_pin", "source", "zig"])
def test_resigned_invalid_bindings_refuse(review_case, mutation):
    facts, outputs = copy.deepcopy(review_case[3]), review_case[2]
    if mutation == "duplicate":
        outputs = (outputs[0], outputs[0], *outputs[2:])
    elif mutation == "reordered":
        outputs = (outputs[1], outputs[0], *outputs[2:])
    elif mutation == "bool_size":
        facts["outputs"][0]["size"] = True
    elif mutation == "header_mismatch":
        outputs = (("pyconfig.h", b"not the separately supplied header"), *outputs[1:])
        facts["outputs"][0].update(size=len(outputs[0][1]), sha256=sha(outputs[0][1]))
    elif mutation == "stage_pin":
        facts["concrete_stages_sha256"] = "0" * 64
    elif mutation == "source":
        facts["source_inventory_sha256"] = "0" * 64
    else:
        facts["zig_manifest_sha256"] = "0" * 64
    with pytest.raises(review.ConfigurationReviewError):
        _bind(review_case, outputs=outputs, facts=facts)


@pytest.mark.parametrize("suffix", [b"LIBOBJS += extra.o\n", b"LIBOBJS = extra.o\n",
                                     b"override LIBOBJS = extra.o\n", b"thing: LIBOBJS = extra.o\n",
                                     b"ifeq (x,x)\nLIBOBJS =\nendif\n"])
def test_duplicate_and_unsupported_make_assignments_refuse(review_case, suffix):
    makefile = dict(review_case[2])["Makefile"]
    with pytest.raises(review.ConfigurationReviewError, match="make_assignment"):
        review._make(makefile + suffix)


@pytest.mark.parametrize("expression", ["$(shell echo forbidden)", "$(wildcard *.o)", "$(UNDEFINED)",
                                        "$(LIBOBJS)", "@response", "`echo forbidden`", "-shared"])
def test_unsupported_make_expressions_refuse(review_case, expression):
    makefile = dict(review_case[2])["Makefile"].replace(b"LIBOBJS = \n", ("LIBOBJS = " + expression + "\n").encode())
    with pytest.raises(review.ConfigurationReviewError):
        review._make(makefile)


def test_immediate_make_reference_refuses_instead_of_misreading_assignment_order(review_case):
    makefile = dict(review_case[2])["Makefile"].replace(b"LIBOBJS = \n", b"LIBOBJS := $(REPLACEMENTS)\n")
    with pytest.raises(review.ConfigurationReviewError, match="make_expression"):
        review._make(makefile + b"REPLACEMENTS =\n")


def test_finite_make_reference_is_expanded_and_independently_bound(review_case):
    original = dict(review_case[2])["Makefile"]
    makefile = original.replace(b"LIBOBJS = \n", b"LIBOBJS = $(REPLACEMENTS)\n") + b"REPLACEMENTS := Python/dynload_stub.o\n"
    variables = review._make(makefile)
    assert variables["LIBOBJS"]["tokens"] == ["Python/dynload_stub.o"]
    assert variables["REPLACEMENTS"]["expression"] == "Python/dynload_stub.o"


@pytest.mark.parametrize("name,value", [("HAVE_DLOPEN", "1"), ("Py_ENABLE_SHARED", "1"),
                                        ("SIZEOF_VOID_P", "4"), ("WITH_MIMALLOC", "0")])
def test_fixed_feature_contract_cannot_be_resigned_away(review_case, name, value):
    header = dict(review_case[2])["pyconfig.h"]
    header += ("#define " + name + " " + value + "\n").encode()
    with pytest.raises(review.ConfigurationReviewError, match="feature_ambiguous"):
        review._header(header)


@pytest.mark.parametrize("mutation", ["object", "module_object", "library", "shared", "module", "role"])
def test_independently_resigned_unsupported_closure_refuses(review_case, mutation):
    variables = copy.deepcopy(review_case[3]["make_variables"])
    setup, semantics = review_case[3]["setup_rows"], review_case[3]["recipe_semantics"]
    if mutation == "object":
        variables["LIBOBJS"]["tokens"] = ["uncompiled-replacement.o"]
    elif mutation == "module_object":
        variables["MODOBJS"]["tokens"] = []
    elif mutation == "library":
        variables["LIBS"]["tokens"] = ["-lunapproved"]
    elif mutation == "shared":
        variables["MODSHARED_NAMES"]["tokens"] = ["_ssl"]
    elif mutation == "module":
        variables["MODBUILT_NAMES"]["tokens"] = []
    else:
        variables["PY_CORE_CFLAGS"]["tokens"] = []
    with pytest.raises(review.ConfigurationReviewError):
        review._closure(variables, setup, semantics)


@pytest.mark.parametrize("variable", ["PY_CFLAGS", "PY_CFLAGS_NODIST", "PY_CPPFLAGS", "PY_STDMODULE_CFLAGS",
                                      "PY_CORE_CFLAGS", "PY_BUILTIN_MODULE_CFLAGS"])
def test_every_reviewed_compile_role_variable_must_reach_actual_flags(review_case, variable):
    facts = copy.deepcopy(review_case[3])
    facts["make_variables"][variable]["tokens"].append("-DUNIMPLEMENTED_CONFIG_FEATURE=1")
    with pytest.raises(review.ConfigurationReviewError, match="role_flag_relation"):
        review._closure(facts["make_variables"], facts["setup_rows"], facts["recipe_semantics"])


def test_only_fixed_source_owned_flag_adaptations_are_accepted(review_case):
    facts = copy.deepcopy(review_case[3])
    facts["make_variables"]["PY_CFLAGS"]["tokens"] = ["-Wall", "-O3", "-O2", "-g", "-g0", "-fwrapv"]
    facts["make_variables"]["srcdir"] = {"expanded": "/explicit-pinned-source"}
    facts["make_variables"]["PY_CPPFLAGS"]["tokens"] = ["-I.", "-I/explicit-pinned-source/Include"]
    review._closure(facts["make_variables"], facts["setup_rows"], facts["recipe_semantics"])


@pytest.mark.parametrize("flag", ["-O3", "-g", "-I/ambient/include", "-Werror=unapproved", "-fplugin=unapproved"])
def test_unknown_role_flag_adaptations_refuse(review_case, flag):
    facts = copy.deepcopy(review_case[3])
    facts["make_variables"]["PY_CFLAGS"]["tokens"] = [flag]
    with pytest.raises(review.ConfigurationReviewError):
        review._closure(facts["make_variables"], facts["setup_rows"], facts["recipe_semantics"])


def test_changed_actual_stage_is_not_covered_by_original_review(review_case):
    stages = copy.deepcopy(review_case[4])
    stages[0]["commands"][0]["argv"].insert(6, "-DCHANGED_ACTUAL_COMPILATION")
    with pytest.raises(review.ConfigurationReviewError, match="recipe_semantics"):
        _bind(review_case, stages=stages)


def test_declared_compiled_module_object_must_reach_both_static_links(review_case):
    facts = copy.deepcopy(review_case[3])
    argv = facts["recipe_semantics"]["archives"][0]["argv"]
    argv.remove("@work/objects/Modules/atexitmodule.o")
    with pytest.raises(review.ConfigurationReviewError, match="replacement_object"):
        review._closure(facts["make_variables"], facts["setup_rows"], facts["recipe_semantics"])


@pytest.mark.parametrize("kind", ("compiler", "linker", "standalone", "support"))
def test_all_successors_select_the_same_original_review_gate(review_case, kind):
    prep = review_case[0]
    result = _GENERATORS[kind](prep, **_arguments(review_case), **_extras(kind, prep, review_case[1]))
    wire = _recipe(result.recipe_bytes, result.sha256, version3=True)
    assert dict(result.sources)["configuration/review.json"] == canonical(review_case[3])
    assert any(row["path"] == "configuration/original/config.status" for row in wire["inputs"]["source"])
    # Successor instrumentation changes stages; the external approval remains
    # precisely the concrete-stage projection, not this execution transcript.
    assert sha(canonical(wire["stages"])) != review_case[3]["concrete_stages_sha256"]


@pytest.mark.parametrize("kind", ("compiler", "linker", "standalone", "support"))
def test_all_successors_preserve_legacy_bytes_when_review_is_none(review_case, kind):
    prep, arguments, _, _, _, _, _ = review_case
    extras = _extras(kind, prep, arguments)
    old = _GENERATORS[kind](prep, **arguments, **extras)
    explicit_none = _GENERATORS[kind](
        prep, **arguments, **extras,
        configuration_outputs=None, review_manifest_bytes=None, expected_review_manifest_sha256=None,
    )
    assert explicit_none == old


@pytest.mark.parametrize("kind", ("compiler", "linker", "standalone", "support"))
def test_all_successors_reach_original_partial_selection_gate(review_case, kind):
    prep, arguments, outputs, _, _, _, _ = review_case
    with pytest.raises(concrete.ConcreteRecipeError, match="configuration_review_incomplete"):
        _GENERATORS[kind](prep, **arguments, **_extras(kind, prep, arguments), configuration_outputs=outputs)


def test_duplicate_manifest_keys_refuse_before_binding(review_case):
    prep = review_case[0]
    arguments = _arguments(review_case)
    raw = arguments["review_manifest_bytes"]
    arguments["review_manifest_bytes"] = b'{"schema":"duplicate",' + raw[1:]
    arguments["expected_review_manifest_sha256"] = sha(arguments["review_manifest_bytes"])
    with pytest.raises(review.ConfigurationReviewError, match="manifest_schema"):
        concrete.prepare_cpython_build_recipe(prep, **arguments)
