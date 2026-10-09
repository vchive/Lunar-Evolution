"""Fixed candidate input plans; no actual configure, compiler or freezer run."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tools.static_python_fixture import build_inputs as policy
from tools.static_python_fixture.source_patches import source_patch_manifest
from tools.static_python_fixture.tables import emit_static_python_tables

_ROOT = Path(__file__).resolve().parents[1]
_INPUT = _ROOT / "tools/static_python_fixture/reviewed-build-inputs.json"
_PARSER_OBJECTS = {
    "Parser/token.o", "Parser/pegen.o", "Parser/pegen_errors.o", "Parser/action_helpers.o",
    "Parser/parser.o", "Parser/string_parser.o", "Parser/peg_api.o", "Parser/lexer/buffer.o",
    "Parser/lexer/lexer.o", "Parser/lexer/state.o", "Parser/tokenizer/file_tokenizer.o",
    "Parser/tokenizer/readline_tokenizer.o", "Parser/tokenizer/string_tokenizer.o",
    "Parser/tokenizer/utf8_tokenizer.o", "Parser/tokenizer/helpers.o", "Parser/myreadline.o",
}
_BUILTIN_OBJECTS = {
    "Modules/atexitmodule.o", "Modules/faulthandler.o", "Modules/posixmodule.o",
    "Modules/signalmodule.o", "Modules/_codecsmodule.o", "Modules/_io/_iomodule.o",
    "Modules/_io/iobase.o", "Modules/_io/fileio.o", "Modules/_io/bytesio.o",
    "Modules/_io/bufferedio.o", "Modules/_io/textio.o", "Modules/_io/stringio.o",
    "Modules/_threadmodule.o", "Modules/_weakref.o", "Modules/_abc.o", "Modules/lunar_fixture_pipe.o",
}
_CORE_BUILTIN_SOURCES = {
    "Python/marshal.c", "Python/import.c", "Python/Python-ast.c", "Python/Python-tokenize.c",
    "Python/bltinmodule.c", "Python/sysmodule.c", "Modules/gcmodule.c", "Python/_warnings.c",
    "Objects/unicodeobject.c",
}


def _raw():
    return _INPUT.read_bytes()


def _data():
    return json.loads(_raw())


def _encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False,
                       allow_nan=False) + "\n").encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _refusal(reason):
    return pytest.raises(policy.StaticPythonBuildInputsError,
                         match="^static_python_build_inputs_" + reason + "$")


def test_fixed_tracked_input_pin_and_detached_candidate_emission():
    raw = _raw()
    assert len(raw) == 79459
    assert _sha(raw) == "ba5221310c10360b010d0b5a5b104586d3a1529f159c93a9c02a83319701a92b"
    result = policy.emit_static_python_build_inputs(raw)
    assert result["schema"] == "lunar-static-python-build-inputs-v1"
    assert result["reviewed_inputs_size"] == len(raw)
    assert result["reviewed_inputs_sha256"] == _sha(raw)
    assert result["source_version"] == "3.13.12"
    assert result["source_commit"] == "1cbe481834751b0125e006042ffbd8cd5eaec8a8"
    result["shared_units"][0]["source"] = "changed"
    result["states"]["production_admission"] = True
    result["freeze_tasks"].clear()
    fresh = policy.emit_static_python_build_inputs(raw)
    assert len(fresh["freeze_tasks"]) == 9
    assert fresh["shared_units"][0]["source"] == "Parser/token.c"
    assert fresh["states"]["production_admission"] is False


def test_shared_inventory_roles_and_core_builtin_origin_deduplication():
    units = policy.emit_static_python_build_inputs(_raw())["shared_units"]
    assert len(units) == len({unit["object"] for unit in units}) == 162
    assert sum(unit["compile_role"] == "core" for unit in units) == 146
    assert {unit["object"] for unit in units if unit["compile_role"] == "builtin"} == _BUILTIN_OBJECTS
    assert {unit["object"] for unit in units if unit["object"].startswith("Parser/")} == _PARSER_OBJECTS
    assert sum(unit["object"].startswith("Objects/") for unit in units) == 43
    assert sum(unit["object"].startswith("Python/") for unit in units) == 83
    for source in _CORE_BUILTIN_SOURCES:
        matches = [unit for unit in units if unit["source"] == source]
        assert len(matches) == 1
        assert matches[0]["compile_role"] == "core"


def test_freezer_and_target_extra_units_are_separate_from_shared_and_each_other():
    result = policy.emit_static_python_build_inputs(_raw())
    shared = {unit["object"] for unit in result["shared_units"]}
    freezer = {unit["object"] for unit in result["freezer_units"]}
    target = {unit["object"] for unit in result["target_units"]}
    assert freezer == {"Programs/_freeze_module.o", "Modules/getpath_noop.o"}
    assert target == {
        "installation-owned-launcher.o", "installation-owned-profile.o",
        "installation-owned-strict-getpath.o", "installation-owned-finite-frozen.o",
    }
    assert not (shared & freezer or shared & target or freezer & target)
    assert not (shared | freezer | target) & {
        "Python/frozen.o", "Modules/getpath.o", "Programs/python.o", "Programs/_bootstrap_python.o",
    }
    assert result["compile_requirements"]["freezer_frozen_tables"] == (
        "defined-empty-by-reviewed-Programs/_freeze_module.c"
    )


def test_controls_distinguish_actual_configure_from_candidate_mislabeled_configure_ac():
    result = policy.emit_static_python_build_inputs(_raw())
    controls = {record["path"]: record for record in result["reviewed_controls"]}
    assert set(controls) == {"Makefile.pre.in", "configure", "configure.ac", "Misc/platform_triplet.c"}
    assert controls["configure"]["source_size"] == 893475
    assert controls["configure"]["sha256"] == (
        "0495fd50c8441437de8df5bd681b94bda00492ad3cf0d0db07f52f928dc12f20"
    )
    assert controls["configure.ac"]["source_size"] == 255967
    assert controls["configure.ac"]["sha256"] == (
        "8e47d53509f130d4a300d85ee51d899a21631ba40b83c5c8b32b2b8b33e525b8"
    )


def test_generated_and_owned_source_pins_match_reviewed_assets_without_host_discovery():
    result = policy.emit_static_python_build_inputs(_raw())
    tables = emit_static_python_tables()
    records = {record["path"]: record for record in result["generated_sources"]}
    assert set(records) == {"generated-sources/" + path for path in tables}
    for path, raw in tables.items():
        assert records["generated-sources/" + path]["source_size"] == len(raw)
        assert records["generated-sources/" + path]["sha256"] == _sha(raw)
    for unit in result["shared_units"] + result["target_units"]:
        if unit["origin"] == "fixture-asset":
            raw = (_ROOT / unit["source"]).read_bytes()
        elif unit["origin"] == "installation-owned-table":
            raw = tables[unit["source"].removeprefix("generated-sources/")]
        else:
            continue
        assert unit["source_size"] == len(raw)
        assert unit["source_sha256"] == _sha(raw)
    assert len(result["fixture_headers"]) == 1
    header = result["fixture_headers"][0]
    assert header["path"] == "assets/lunar_fixture_profile.h"
    raw = (_ROOT / "tools/static_python_fixture/assets/lunar_fixture_profile.h").read_bytes()
    assert header["source_size"] == len(raw)
    assert header["sha256"] == _sha(raw)


def test_prepared_import_c_and_frozen_sources_use_existing_postimage_pins():
    result = policy.emit_static_python_build_inputs(_raw())
    patches = source_patch_manifest()
    assert result["source_preparation"]["patch_set_sha256"] == patches["patch_set_sha256"]
    prepared = {record["path"]: record for record in patches["files"]}
    import_unit = next(unit for unit in result["shared_units"] if unit["source"] == "Python/import.c")
    assert import_unit["reviewed_source_sha256"] == prepared["Python/import.c"]["before_sha256"]
    assert import_unit["source_sha256"] == prepared["Python/import.c"]["after_sha256"]
    assert import_unit["source_size"] == prepared["Python/import.c"]["after_size"]
    for task in result["freeze_tasks"]:
        if task["source"] in prepared:
            assert task["source_sha256"] == prepared[task["source"]]["after_sha256"]
            assert task["source_size"] == prepared[task["source"]]["after_size"]


def test_nine_frozen_tasks_have_matching_header_layout_symbols_and_no_header_digests():
    tasks = policy.emit_static_python_build_inputs(_raw())["freeze_tasks"]
    assert {task["name"] for task in tasks} == {
        "_frozen_importlib", "_frozen_importlib_external", "abc", "codecs", "io",
        "encodings", "encodings.aliases", "encodings.utf_8", "_lunar_static_main",
    }
    source = emit_static_python_tables()["Python/frozen.c"].decode("ascii")
    for task in tasks:
        assert task["output"] == "generated-sources/Python/frozen_modules/" + task["generator_id"] + ".h"
        assert '#include "frozen_modules/' + task["generator_id"] + '.h"' in source
        assert task["symbol"] == "_Py_M__" + task["generator_id"].replace(".", "_")
        assert task["symbol"] in source
        assert "output_sha256" not in task
        assert task["package"] is (task["name"] == "encodings")
    custom = next(task for task in tasks if task["name"] == "_lunar_static_main")
    assert custom["source"] == "assets/frozen_main.py"
    assert custom["origin"] == "expanded-fixture-asset"
    assert custom["source_size"] == 6794


def test_compile_requirements_keep_aliasing_proposed_configuration_and_open_substitutions():
    result = policy.emit_static_python_build_inputs(_raw())
    dtoa = next(unit for unit in result["shared_units"] if unit["object"] == "Python/dtoa.o")
    assert dtoa["extra_flags"] == ["-fno-strict-aliasing"]
    assert all(unit["extra_flags"] == [] for unit in result["shared_units"] if unit is not dtoa)
    compile = result["compile_requirements"]
    assert compile["core_flags"] == "PY_CORE_CFLAGS"
    assert compile["builtin_flags"] == "PY_BUILTIN_MODULE_CFLAGS"
    assert compile["configure_state"] == "proposal-only-not-configured"
    assert compile["proposed_configure_argv"] == [
        "--host=x86_64-linux-musl", "--build=x86_64-linux-musl", "--disable-shared",
        "--disable-test-modules", "--with-ensurepip=no", "--with-computed-gotos", "--with-pymalloc",
    ]
    assert compile["compiler_and_sysroot"] == "not-observed"
    assert compile["link_closure"] == "unresolved"
    assert result["getbuildinfo_requirements"] == ["DATE", "TIME", "GITVERSION", "GITTAG", "GITBRANCH"]
    assert result["unresolved_configuration"] == [
        "LIBOBJS", "MACHDEP_OBJS", "DTRACE_OBJS", "PLATFORM_OBJS", "PERF_TRAMPOLINE_OBJ",
        "MODOBJS/MODLIBS", "LIBS/SYSLIBS/compiler-support/CRT/libc/libm",
    ]
    assert result["stock_excluded"]["optional_module_discovery"] == "not-disabled-by-this-input-plan"
    assert all(type(value) is bool and value is False for value in result["states"].values())


class _HostileBytes(bytes):
    def __len__(self):
        raise AssertionError("metadata byte subclass callback executed")

    def decode(self, *args, **kwargs):
        raise AssertionError("metadata byte subclass callback executed")


@pytest.mark.parametrize("raw", [
    None, {}, "{}", bytearray(b"{}"), memoryview(b"{}"),
    pytest.param(_HostileBytes(b"{}"), id="hostile-bytes"),
])
def test_input_requires_exact_bytes_without_callbacks(raw):
    with _refusal("bytes_invalid"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("raw", [
    pytest.param(b"", id="empty"),
    pytest.param(b"x" * (policy.MAX_REVIEWED_BUILD_INPUTS_BYTES + 1), id="above-byte-budget"),
])
def test_input_byte_budget_refuses_before_parsing(raw):
    with _refusal("byte_budget_exceeded"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("raw", [b"{", b"\xff", b'{"schema":NaN}', b'{"schema":Infinity}'])
def test_json_encoding_and_nonfinite_are_fixed_refusals(raw):
    with _refusal("json_invalid"):
        policy.emit_static_python_build_inputs(raw)


def test_deep_top_level_list_refuses_with_bounded_fixed_error():
    # JSON backends differ in when they reject nesting. A backend that decodes
    # this legal list must still refuse its top-level shape before emission.
    raw = b"[" * 1100 + b"]" * 1100
    with pytest.raises(policy.StaticPythonBuildInputsError,
                       match=r"^static_python_build_inputs_(json_invalid|shape_invalid)$"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("raw", [b"null", b"[]", b"true", b"{}"])
def test_top_level_json_shape_refuses(raw):
    with _refusal("shape_invalid"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("nested", [False, True])
def test_duplicate_keys_cannot_hide_identical_fields(nested):
    raw = _raw()
    needle = b'"compile_role": "core"' if nested else b'"source_version": "3.13.12"'
    raw = raw.replace(needle, needle + b", " + needle, 1)
    with _refusal("duplicate_json_key"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("style", ["compact", "missing-lf", "extra-lf", "reordered"])
def test_fixed_pretty_sorted_encoding_is_part_of_review_pin(style):
    raw = _raw()
    if style == "compact":
        raw = json.dumps(_data(), separators=(",", ":")).encode()
    elif style == "missing-lf":
        raw = raw[:-1]
    elif style == "extra-lf":
        raw += b"\n"
    else:
        raw = (json.dumps(dict(reversed(list(_data().items()))), indent=2) + "\n").encode()
    with _refusal("noncanonical_json"):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("surface", ["extra", "missing", "unit-extra", "unit-missing"])
def test_exact_top_and_unit_field_sets(surface):
    data = _data()
    if surface == "extra":
        data["auto_discover_modules"] = True
    elif surface == "missing":
        del data["source_commit"]
    elif surface == "unit-extra":
        data["shared_units"][0]["run_command"] = "bad"
    else:
        del data["shared_units"][0]["source"]
    with _refusal("shape_invalid"):
        policy.emit_static_python_build_inputs(_encoded(data))


@pytest.mark.parametrize("field,value,reason", [
    ("source_size", True, "source_size_invalid"),
    ("source_size", 0, "source_size_invalid"),
    ("source_size", -1, "integer_invalid"),
    ("source_size", 8 * 1024 * 1024 + 1, "integer_invalid"),
    ("source_sha256", "0" * 64, "digest_invalid"),
    ("source_sha256", "f" * 64, "digest_invalid"),
    ("source_sha256", "F" * 64, "digest_invalid"),
    ("source", "/absolute.c", "path_invalid"),
    ("source", "Python/../changed.c", "path_invalid"),
    ("source", "Python//changed.c", "path_invalid"),
    ("source", "Python\\changed.c", "path_invalid"),
    ("source", "Python/C:changed.c", "path_invalid"),
    ("source", "\ud800", "text_invalid"),
    ("source", "Python/\x80changed.c", "text_invalid"),
    ("compile_role", True, "compile_role_invalid"),
    ("compile_role", "extension", "compile_role_invalid"),
    ("origin", "ambient-host-source", "source_origin_invalid"),
    ("extra_flags", ["-fPIC"], "extra_flags_invalid"),
])
def test_unit_primitive_paths_flags_and_digest_shape(field, value, reason):
    data = _data()
    data["shared_units"][0][field] = value
    raw = ((json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
           if field == "source" and value == "\ud800" else _encoded(data))
    with _refusal(reason):
        policy.emit_static_python_build_inputs(raw)


@pytest.mark.parametrize("group", ["shared_units", "freezer_units", "target_units"])
def test_unit_inventory_count_refuses_missing_members(group):
    data = _data()
    data[group].pop()
    with _refusal("unit_inventory_invalid"):
        policy.emit_static_python_build_inputs(_encoded(data))


def test_duplicate_shared_object_refuses_before_a_build_can_duplicate_core_origins():
    data = _data()
    data["shared_units"][1] = copy.deepcopy(data["shared_units"][0])
    with _refusal("duplicate_object"):
        policy.emit_static_python_build_inputs(_encoded(data))


@pytest.mark.parametrize("group", ["reviewed_controls", "generated_sources", "fixture_headers", "freeze_tasks"])
def test_control_generated_and_freeze_inventories_are_finite(group):
    data = _data()
    data[group].pop()
    reason = "freeze_inventory_invalid" if group == "freeze_tasks" else "control_inventory_invalid"
    with _refusal(reason):
        policy.emit_static_python_build_inputs(_encoded(data))


def test_package_flags_cannot_use_integer_in_place_of_boolean():
    data = _data()
    data["freeze_tasks"][0]["package"] = 0
    with _refusal("package_flag_invalid"):
        policy.emit_static_python_build_inputs(_encoded(data))


@pytest.mark.parametrize("state", [
    "source_archive_verified", "toolchain_verified", "configure_performed", "compile_performed",
    "link_performed", "frozen_headers_generated", "execution_performed", "runtime_load_protection",
    "production_admission", "general_code_origin_protection",
])
def test_no_completed_or_protection_claim_is_accepted(state):
    data = _data()
    data["states"][state] = True
    with _refusal("unsupported_completion_claim"):
        policy.emit_static_python_build_inputs(_encoded(data))


@pytest.mark.parametrize("surface", ["version", "unit-pin", "prepared-pin", "unresolved", "dtoa", "header"])
def test_valid_metadata_changes_still_refuse_the_fixed_external_policy_pin(surface):
    data = _data()
    if surface == "version":
        data["source_version"] = "3.13.13"
    elif surface == "unit-pin":
        data["shared_units"][0]["source_sha256"] = "1" * 64
    elif surface == "prepared-pin":
        data["source_preparation"]["files"][0]["after_sha256"] = "1" * 64
    elif surface == "unresolved":
        data["unresolved_configuration"] = []
    elif surface == "dtoa":
        next(unit for unit in data["shared_units"] if unit["object"] == "Python/dtoa.o")["extra_flags"] = []
    else:
        data["freeze_tasks"][0]["output"] = "generated/wrong-layout.h"
    with _refusal("policy_pin_drift"):
        policy.emit_static_python_build_inputs(_encoded(data))


def test_json_tree_depth_is_bounded_before_canonical_encoding():
    data = _data()
    deep = []
    for _ in range(10):
        deep = [deep]
    data["compile_requirements"]["compiler_and_sysroot"] = deep
    with _refusal("shape_budget_exceeded"):
        policy.emit_static_python_build_inputs(_encoded(data))


def test_pure_emitter_succeeds_with_filesystem_network_and_process_apis_blocked(monkeypatch):
    import builtins
    import os
    import socket
    import subprocess
    import tarfile
    import urllib.request

    raw = _raw()

    def forbidden(*args, **kwargs):
        raise AssertionError("pure build-input emitter attempted external IO")

    for owner, name in (
        (builtins, "open"), (os, "open"), (Path, "open"),
        (socket, "socket"), (subprocess, "run"), (subprocess, "Popen"),
        (tarfile, "open"), (urllib.request, "urlopen"),
    ):
        monkeypatch.setattr(owner, name, forbidden)
    result = policy.emit_static_python_build_inputs(raw)
    assert len(result["shared_units"]) == 162
    assert result["states"]["execution_performed"] is False
