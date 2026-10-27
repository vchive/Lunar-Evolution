"""Artificial source graphs only; no actual upstream Python or C is executed."""

from __future__ import annotations

import ast
import hashlib
import json

import pytest

from tools.static_python_fixture.profile import FROZEN
from tools.static_python_rsi_fixture import runtime_closure as closure


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(params=["openevolve", "shinka"])
def closure_inputs(request, monkeypatch):
    solver = request.param
    cpython = {path: b"pass\n" for _, _, path, _ in FROZEN if path.startswith("Lib/")}
    cpython["Lib/importlib/__init__.py"] = b"pass\n"
    cpython["Lib/__future__.py"] = b"pass\n"
    cpython["Lib/json/__init__.py"] = b"from . import decoder\n"
    cpython["Lib/json/decoder.py"] = b"import _json\n"
    if solver == "shinka":
        cpython.update({"Lib/sqlite3/__init__.py": b"from .dbapi2 import *\n",
                        "Lib/sqlite3/dbapi2.py": b"import _sqlite3\n",
                        "Lib/datetime.py": b"import _datetime\n", "Lib/_strptime.py": b"pass\n"})
    native = dict(closure._NATIVE)
    if solver == "shinka":
        native["_sqlite3"] = closure._SQLITE
    for sources in native.values():
        for path in sources:
            cpython["Modules/" + path] = b"/* inert C source, never compiled */\n"
    source_modules = {solver: b"pass\n", solver + ".lunar_fixed": b"from . import helper\nimport json\n",
                      solver + ".helper": b"from __future__ import annotations\n"}
    files = {}
    records = []
    for name, raw in source_modules.items():
        path = name.replace(".", "/") + ("/__init__.py" if name == solver else ".py")
        files[path] = raw
        records.append({"path": path, "module": name, "result": {"bytes": len(raw), "sha256": sha(raw)}})
    files.update({"LICENSE": b"upstream fixture notice", "LICENSE.lunar": b"local fixture notice"})
    manifest = json.dumps({"sources": records, "license": {
        key: {"result": {"bytes": len(files[path]), "sha256": sha(files[path])}}
        for key, path in (("upstream", "LICENSE"), ("lunar", "LICENSE.lunar"))
    }}, sort_keys=True).encode()
    monkeypatch.setitem(closure._PRODUCER_PINS, solver, sha(manifest))
    sql = {"sqlite3.c": b"/* independently pinned synthetic amalgamation */\n",
           "sqlite3.h": b"#define SQLITE_VERSION_NUMBER 3050000\n"
                        b"void *sqlite3_serialize(void); int sqlite3_deserialize(void);\n"}
    return {"solver": solver, "cpython_sources": cpython,
            "expected_cpython_inventory_sha256": sha(closure.source_inventory(cpython)),
            "producer_files": files, "producer_manifest": manifest,
            **({"sqlite_sources": sql, "expected_sqlite_inventory_sha256": sha(closure.source_inventory(sql))}
               if solver == "shinka" else {})}


def refresh_cpython_pin(args):
    args["expected_cpython_inventory_sha256"] = sha(closure.source_inventory(args["cpython_sources"]))


def test_finite_import_graph_native_units_and_solver_entrypoint(closure_inputs):
    args = closure_inputs
    result = closure.prepare_fixed_runtime_closure(**args)
    facts = json.loads(result.wire_bytes)
    frozen = {r["name"]: r for r in facts["frozen"]}
    assert {n for n, _, _, _ in FROZEN} <= set(frozen)
    assert {args["solver"], args["solver"] + ".helper", "json", "json.decoder", "__future__"} <= set(frozen)
    assert "_json" not in frozen
    assert any(u["module"] == "_json" for u in facts["native_units"])
    assert any(u["source"] == "Modules/_hacl/Hacl_Hash_SHA2.c" for u in facts["native_units"])
    generated = dict(result.sources)
    main = ast.parse(generated["runtime/frozen_main.py"])
    launch = main.body[0]
    assert isinstance(launch, ast.FunctionDef) and launch.name == "_rsi_launch"
    source_import = next(n for n in ast.walk(launch) if isinstance(n, ast.ImportFrom))
    assert source_import.module == args["solver"] + ".lunar_fixed"
    assert b'_main("baseline")' not in generated["runtime/frozen_main.py"]
    assert b"_PyImport_Inittab" in generated["runtime/Modules/config.c"]
    assert b"_PyImport_FrozenBootstrap" in generated["runtime/Python/frozen.c"]
    assert facts["production_admission"] is False
    assert facts["runtime_execution_performed"] is False
    assert facts["dynamic_import_closure_verified"] is False
    if args["solver"] == "shinka":
        sqlite = [u for u in facts["native_units"] if u["module"] == "_sqlite3"]
        assert len(sqlite) == 9
        assert all("-DPY_SQLITE_HAVE_SERIALIZE=1" in u["extra_flags"] for u in sqlite)
        library = next(u for u in facts["native_units"] if u["module"] == "sqlite-library")
        assert "-DSQLITE_OMIT_LOAD_EXTENSION=1" in library["extra_flags"]
        assert generated["sqlite/sqlite3.c"] == args["sqlite_sources"]["sqlite3.c"]


def test_cpython_source_drift_before_any_resolution(closure_inputs):
    closure_inputs["cpython_sources"]["Lib/abc.py"] += b"# changed\n"
    with pytest.raises(closure.RuntimeClosureError, match="inventory_pin_mismatch"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_function_local_diagnostics_and_inspection_require_native_closure(closure_inputs):
    """Model real 3.13 typing/inspect and warnings/traceback import edges."""
    cpython = closure_inputs["cpython_sources"]
    cpython.update({
        "Lib/json/decoder.py": b"import typing\nimport warnings\nimport traceback\n",
        "Lib/typing.py": b"def diagnostics():\n    import inspect\n",
        "Lib/inspect.py": b"import dis\n",
        "Lib/dis.py": b"import opcode\n",
        "Lib/opcode.py": b"import _opcode\n",
        "Lib/warnings.py": (
            b"def diagnostics():\n    try:\n        import tracemalloc\n"
            b"    except ImportError:\n        pass\n"
        ),
        "Lib/tracemalloc.py": b"from _tracemalloc import *\n",
        "Lib/traceback.py": b"def suggestions():\n    import _suggestions\n",
    })
    refresh_cpython_pin(closure_inputs)
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    frozen = {record["name"] for record in facts["frozen"]}
    assert {"typing", "inspect", "dis", "opcode", "warnings", "tracemalloc", "traceback"} <= frozen
    units = {record["module"]: record["source"] for record in facts["native_units"]}
    generated = dict(result.sources)
    for name in ("_opcode", "_suggestions", "_tracemalloc"):
        assert name not in frozen
        assert name not in facts["guarded_absent_imports"]
        assert units[name] == "Modules/" + name + ".c"
        assert ('{"' + name + '", PyInit_' + name + '},').encode() in generated["runtime/Modules/config.c"]


@pytest.mark.parametrize("module", ["_opcode", "_suggestions", "_tracemalloc"])
def test_diagnostic_native_source_cannot_be_substituted_by_absence(closure_inputs, module):
    closure_inputs["cpython_sources"]["Lib/json/decoder.py"] = (
        b"def diagnostics():\n    import " + module.encode() + b"\n"
    )
    del closure_inputs["cpython_sources"]["Modules/" + module + ".c"]
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="native_source_missing"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def add_runtime_alias_sources(args, imports):
    args["cpython_sources"].update({
        "Lib/json/decoder.py": imports,
        "Lib/collections/__init__.py": (
            b"import _collections_abc\nimport sys as _sys\n"
            b"_sys.modules['collections.abc'] = _collections_abc\nabc = _collections_abc\n"
        ),
        "Lib/_collections_abc.py": b"__name__ = 'collections.abc'\n",
        "Lib/os.py": (
            b"import sys\n_names = sys.builtin_module_names\n"
            b"if 'posix' in _names:\n    name = 'posix'\n"
            b"    from posix import *\n    import posixpath as path\n"
            b"elif 'nt' in _names:\n    name = 'nt'\n"
            b"    from nt import *\n    import ntpath as path\n"
            b"sys.modules['os.path'] = path\n"
            b"if name == 'nt':\n    def add_dll_directory(path):\n        import nt\n"
            b"if name != 'posix':\n    import nt\n"
        ),
        "Lib/posixpath.py": b"import os\n",
    })
    refresh_cpython_pin(args)


@pytest.mark.parametrize("imports", [
    b"import collections.abc\nimport os.path\n",
    b"from collections import abc\nfrom os import path\n",
    b"from collections.abc import Sequence\nfrom os.path import join\n",
])
def test_official_runtime_aliases_keep_real_source_and_parent_initializers(closure_inputs, imports):
    add_runtime_alias_sources(closure_inputs, imports)
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    frozen = {record["name"]: record for record in facts["frozen"]}
    assert {"collections", "_collections_abc", "os", "posixpath"} <= set(frozen)
    assert not {"collections.abc", "os.path", "ntpath"} & set(frozen)
    assert frozen["collections"]["source"] == "Lib/collections/__init__.py"
    assert frozen["collections"]["package"] is True
    assert frozen["_collections_abc"]["source"] == "Lib/_collections_abc.py"
    assert frozen["posixpath"]["source"] == "Lib/posixpath.py"
    assert facts["runtime_module_aliases"] == [
        {"name": "collections.abc", "source_module": "_collections_abc", "parent_module": "collections"},
        {"name": "os.path", "source_module": "posixpath", "parent_module": "os"},
    ]
    assert all(not path.endswith(("collections/abc.py", "os/path.py")) for path, _ in result.sources)
    assert "nt" not in facts["guarded_absent_imports"]


def test_runtime_alias_requires_its_real_parent_initializer(closure_inputs):
    add_runtime_alias_sources(closure_inputs, b"import collections.abc\n")
    del closure_inputs["cpython_sources"]["Lib/collections/__init__.py"]
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="unresolved_import"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_runtime_alias_refuses_fake_source_at_the_alias_path(closure_inputs):
    add_runtime_alias_sources(closure_inputs, b"import collections.abc\n")
    closure_inputs["cpython_sources"]["Lib/collections/abc.py"] = b"pass\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="runtime_alias_source_conflict"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_os_builtin_branch_requires_the_single_official_names_binding(closure_inputs):
    add_runtime_alias_sources(closure_inputs, b"import os.path\n")
    closure_inputs["cpython_sources"]["Lib/os.py"] += b"_names = ()\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="unguarded_absent_import"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


@pytest.mark.parametrize("extra", [
    b"name = 'nt'\n",
    b"def local_name(name):\n    if name == 'nt':\n        import nt\n",
])
def test_os_global_platform_name_cannot_prune_rebound_or_function_local_conditions(closure_inputs, extra):
    add_runtime_alias_sources(closure_inputs, b"import os.path\n")
    closure_inputs["cpython_sources"]["Lib/os.py"] += extra
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="unguarded_absent_import"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def add_interpreter_main_source(args):
    args["cpython_sources"].update({
        "Lib/json/decoder.py": b"import __main__\n",
        "Python/pylifecycle.c": (
            b"/* Synthetic lifecycle source identity, never compiled. */\n"
            b"status = add_main_module(interp);\n"
            b"add_main_module(PyInterpreterState *interp)\n"
            b"m = PyImport_AddModuleObject(&_Py_ID(__main__));\n"
        ),
    })
    refresh_cpython_pin(args)


def test_interpreter_main_is_lifecycle_provided_without_frozen_or_native_shim(closure_inputs):
    add_interpreter_main_source(closure_inputs)
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    raw = closure_inputs["cpython_sources"]["Python/pylifecycle.c"]
    assert facts["interpreter_provided_modules"] == [{
        "name": "__main__", "kind": "interpreter-lifecycle", "source": "Python/pylifecycle.c",
        "source_size": len(raw), "source_sha256": sha(raw),
        "creation_function": "add_main_module", "startup_api": "Py_InitializeFromConfig",
        "required_init_main": 1,
    }]
    assert "__main__" not in {record["name"] for record in facts["frozen"]}
    assert "__main__" not in {record["module"] for record in facts["native_units"]}
    generated = dict(result.sources)
    assert b"PyInit___main__" not in generated["runtime/Modules/config.c"]
    assert all(not path.endswith("__main__.py") for path in generated)


@pytest.mark.parametrize("change", ["missing_lifecycle", "changed_lifecycle", "fake_python_module"])
def test_interpreter_main_requires_original_lifecycle_source(closure_inputs, change):
    add_interpreter_main_source(closure_inputs)
    if change == "missing_lifecycle":
        del closure_inputs["cpython_sources"]["Python/pylifecycle.c"]
    elif change == "changed_lifecycle":
        closure_inputs["cpython_sources"]["Python/pylifecycle.c"] = b"/* no main initialization */\n"
    else:
        closure_inputs["cpython_sources"]["Lib/__main__.py"] = b"pass\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="interpreter_module_source_"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def add_platform_java_source(args, monkeypatch):
    args["cpython_sources"].update({
        "Lib/json/decoder.py": b"import platform\n",
        "Lib/platform.py": (
            b"def _java_getprop(name, default):\n"
            b"    from java.lang import System\n    return System.getProperty(name)\n\n"
            b"def java_ver(release='', vendor=''):\n"
            b"    try:\n        import java.lang\n"
            b"    except ImportError:\n        return release, vendor\n"
            b"    vendor = _java_getprop('java.vendor', vendor)\n"
            b"    return _java_getprop('java.version', release), vendor\n"
        ),
    })
    # Synthetic source graphs deliberately substitute their own reviewed-source
    # pin. The real release pin is exercised by the retained source-only gate.
    monkeypatch.setattr(closure, "_PLATFORM_JAVA_SOURCE_SHA256", sha(args["cpython_sources"]["Lib/platform.py"]))
    refresh_cpython_pin(args)


def test_platform_private_java_helper_inherits_only_its_proven_caller_guard(closure_inputs, monkeypatch):
    add_platform_java_source(closure_inputs, monkeypatch)
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    assert facts["guarded_absent_imports"] == ["java.lang"]
    assert facts["guarded_call_imports"] == [{
        "module": "platform", "function": "_java_getprop", "caller": "java_ver", "import": "java.lang",
        "guard": "prior-try-import-except-ImportError-return", "guard_lineno": 6,
        "literal_call_count": 2, "dynamic_reflection_verified": False,
        "module_source_sha256": sha(closure_inputs["cpython_sources"]["Lib/platform.py"]),
    }]
    assert "java.lang" not in {record["name"] for record in facts["frozen"]}


@pytest.mark.parametrize("change", [
    "missing_guard", "nonreturn_handler", "extra_caller", "alias", "rebind", "module_call", "external_call",
])
def test_platform_java_helper_guard_cannot_hide_unprotected_calls(closure_inputs, change, monkeypatch):
    add_platform_java_source(closure_inputs, monkeypatch)
    raw = closure_inputs["cpython_sources"]["Lib/platform.py"]
    if change == "missing_guard":
        raw = raw.replace(b"except ImportError:", b"except AttributeError:")
    elif change == "nonreturn_handler":
        raw = raw.replace(b"return release, vendor", b"pass")
    elif change == "extra_caller":
        raw += b"def other():\n    return _java_getprop('key', '')\n"
    elif change == "alias":
        raw += b"alias = _java_getprop\n"
    elif change == "rebind":
        raw += b"_java_getprop = lambda *args: None\n"
    elif change == "module_call":
        raw += b"_java_getprop('key', '')\n"
    else:
        closure_inputs["cpython_sources"]["Lib/json/decoder.py"] += b"platform._java_getprop('key', '')\n"
    closure_inputs["cpython_sources"]["Lib/platform.py"] = raw
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="platform_helper_source_drift|platform_helper_reference_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_producer_pin_and_exact_module_notice_inventory(closure_inputs):
    closure_inputs["producer_files"]["LICENSE"] += b"changed"
    with pytest.raises(closure.RuntimeClosureError, match="producer_license_drift"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_producer_extra_file_refused(closure_inputs):
    closure_inputs["producer_files"]["arbitrary.py"] = b"raise RuntimeError('never execute')\n"
    with pytest.raises(closure.RuntimeClosureError, match="producer_inventory_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_no_unknown_import_or_host_fallback(closure_inputs):
    closure_inputs["cpython_sources"]["Lib/json/decoder.py"] = b"import unknown_plugin_from_host\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="unresolved_import"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_unguarded_missing_native_dependency_refuses(closure_inputs):
    closure_inputs["cpython_sources"]["Lib/json/decoder.py"] = b"import _socket\n"
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="unguarded_absent_import"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_optional_import_is_explicitly_absent_and_linux_branch_is_resolved(closure_inputs):
    closure_inputs["cpython_sources"]["Lib/json/decoder.py"] = (
        b"import sys\nif sys.platform == 'win32':\n    import _winapi\n"
        b"try:\n    import _hashlib\nexcept ImportError:\n    import _sha2\n")
    refresh_cpython_pin(closure_inputs)
    result = closure.prepare_fixed_runtime_closure(**closure_inputs)
    facts = json.loads(result.wire_bytes)
    assert facts["guarded_absent_imports"] == ["_hashlib"]


def test_native_source_missing_refuses(closure_inputs):
    del closure_inputs["cpython_sources"]["Modules/sha2module.c"]
    refresh_cpython_pin(closure_inputs)
    with pytest.raises(closure.RuntimeClosureError, match="native_source_missing"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_sqlite_bytes_and_serialization_are_mandatory(closure_inputs):
    if closure_inputs["solver"] != "shinka":
        return
    closure_inputs["sqlite_sources"]["sqlite3.h"] = b"#define SQLITE_VERSION_NUMBER 3020000\n"
    closure_inputs["expected_sqlite_inventory_sha256"] = sha(closure.source_inventory(closure_inputs["sqlite_sources"]))
    with pytest.raises(closure.RuntimeClosureError, match="sqlite_serialization_required"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)


def test_sqlite_host_library_is_not_a_source_substitute(closure_inputs):
    if closure_inputs["solver"] != "shinka":
        return
    closure_inputs["sqlite_sources"] = {"libsqlite3.so": b"not an amalgamation"}
    closure_inputs["expected_sqlite_inventory_sha256"] = sha(closure.source_inventory(closure_inputs["sqlite_sources"]))
    with pytest.raises(closure.RuntimeClosureError, match="sqlite_inventory_invalid"):
        closure.prepare_fixed_runtime_closure(**closure_inputs)
